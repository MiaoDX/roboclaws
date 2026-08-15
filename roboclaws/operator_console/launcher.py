"""Safe launcher for operator-console SDK/direct routes."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from roboclaws.agents.provider_registry import (
    openai_agents_runtime_settings,
    provider_readiness,
)
from roboclaws.core.dotenv import load_dotenv_file
from roboclaws.core.provider_catalog import default_provider_profile
from roboclaws.core.rerun import public_surface_rerun_argv
from roboclaws.household.evidence_lane_policy import evidence_lane_compatibility
from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.launch.executor import LaunchProcess, spawn_launch_plan
from roboclaws.launch.plans import LaunchPlan
from roboclaws.launch.runners import export_env_from_plan
from roboclaws.launch.worlds import optional_world_dependency_status
from roboclaws.operator_console import context_packets
from roboclaws.operator_console.interactions import (
    MESSAGE_LOG,
    RESUME_REQUEST_LOG,
    attach_run_to_session,
)
from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.launch_lifecycle import (
    _existing_terminal_phase,
    _JsonSourceError,
    _live_run_pid,
    _read_json_source,
    _read_optional_json_source,
    _remove_empty_reserved_run_dir,
    _reserve_new_run_dir,
    _tmux_session_active,
)
from roboclaws.operator_console.launch_request import LaunchRequest
from roboclaws.operator_console.launch_support import (
    apply_env_overrides,
    build_surface_launch_args,
    launch_prompt_for_intent,
    provider_env_overrides_for_route,
    public_env_overrides,
)
from roboclaws.operator_console.locks import LockState, ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.prompt_preview import (
    PromptPreviewRequest,
    build_prompt_preview,
    prompt_preview_env,
)
from roboclaws.operator_console.readiness import route_gate_rows
from roboclaws.operator_console.routes import ConsoleLaunchSelection, get_selection
from roboclaws.operator_console.runtime_blocker_policy import (
    background_blocker_message,
    blocking_tasks_for_route,
    requested_mcp_endpoint,
)
from roboclaws.operator_console.runtime_compat import pid_is_active  # noqa: F401
from roboclaws.operator_console.runtime_inventory import runtime_inventory_payload
from roboclaws.operator_console.state import resolve_display_run_dir
from roboclaws.operator_console.state_summary import (
    is_terminal_run_phase,
)
from roboclaws.operator_console.workflows import (
    get_operator_workflow,
    runtime_map_prior_for_workflow,
    runtime_prior_override_exists,
)


def load_repo_dotenv(root: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment with repo-local ``.env`` values loaded when present."""

    return load_dotenv_file(root / ".env", env)


def provider_key_present(route: ConsoleLaunchSelection, env: dict[str, str] | None = None) -> bool:
    env_map = os.environ if env is None else env
    if route.agent_engine_id == "openai-agents-sdk":
        return _openai_agents_provider_status(env_map)["ok"]
    return False


def build_launch_args(
    route: ConsoleLaunchSelection,
    *,
    root: Path,
    run_id: str,
    intent: str = "",
    prompt: str = "",
    overrides: dict[str, str] | None = None,
) -> list[str]:
    """Build canonical public-surface arguments for a console route."""

    output_dir = console_output_root(root) / "runs" / run_id
    args = build_surface_launch_args(
        route,
        selected_intent=intent,
        prompt=prompt,
        overrides=overrides,
        output_dir=output_dir,
        error_type=ConsoleLaunchError,
    )
    return args


def build_workflow_launch_args(
    route: ConsoleLaunchSelection,
    *,
    workflow_id: str,
    root: Path,
    run_id: str,
    prompt: str = "",
    overrides: dict[str, str] | None = None,
) -> list[str]:
    """Build launch arguments for an operator workflow action."""

    workflow = get_operator_workflow(workflow_id)
    if workflow.intent_id != route.intent_id:
        raise ConsoleLaunchError(
            f"workflow {workflow.id} requires intent {workflow.intent_id}, "
            f"but route uses {route.intent_id}"
        )
    request_overrides = dict(overrides or {})
    request_overrides.setdefault("scenario_setup", workflow.scenario_setup)
    try:
        runtime_map_prior = runtime_map_prior_for_workflow(
            workflow=workflow,
            world_id=route.world_id,
            backend_id=route.backend_id,
            override_path=str(request_overrides.get("runtime_map_prior") or ""),
        )
    except ValueError as exc:
        raise ConsoleLaunchError(str(exc)) from exc
    if runtime_map_prior:
        if not runtime_prior_override_exists(runtime_map_prior, root=root):
            raise ConsoleLaunchError(f"runtime_map_prior path does not exist: {runtime_map_prior}")
        request_overrides["runtime_map_prior"] = runtime_map_prior
    elif (
        "runtime_map_prior" in request_overrides
        and not str(request_overrides["runtime_map_prior"]).strip()
    ):
        raise ConsoleLaunchError("runtime_map_prior override cannot be empty")
    return build_launch_args(
        route,
        root=root,
        run_id=run_id,
        intent=workflow.intent_id,
        prompt=prompt,
        overrides=request_overrides,
    )


def _build_request_launch_args(
    route: ConsoleLaunchSelection,
    request: LaunchRequest,
    *,
    root: Path,
    run_id: str,
    selected_intent: str,
    launch_prompt: str,
    overrides: dict[str, str],
) -> list[str]:
    if request.workflow_id:
        return build_workflow_launch_args(
            route,
            workflow_id=request.workflow_id,
            root=root,
            run_id=run_id,
            prompt=launch_prompt,
            overrides=overrides,
        )
    return build_launch_args(
        route,
        root=root,
        run_id=run_id,
        intent=selected_intent,
        prompt=launch_prompt,
        overrides=overrides,
    )


def _resolve_console_launch_plan(launch_args: list[str]) -> LaunchPlan:
    try:
        return resolve_surface_launch(launch_args)
    except LaunchError as exc:
        raise ConsoleLaunchError(str(exc)) from exc


def _reap_console_child(pid: int) -> None:
    while True:
        try:
            os.waitpid(pid, 0)
            return
        except InterruptedError:
            continue
        except ChildProcessError:
            return


def _start_console_child_reaper(process: LaunchProcess) -> None:
    threading.Thread(
        target=_reap_console_child,
        args=(process.pid,),
        name=f"roboclaws-console-reaper-{process.pid}",
        daemon=True,
    ).start()


def _terminate_and_reap_console_child(process: LaunchProcess) -> None:
    process.terminate()
    _start_console_child_reaper(process)


def _register_console_process(
    lock: ResourceLock,
    *,
    run_id: str,
    process: LaunchProcess,
) -> LockState:
    lock_state = lock.update_pid(run_id=run_id, pid=process.pid)
    _start_console_child_reaper(process)
    return lock_state


def start_console_run(
    root: Path,
    request: LaunchRequest,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate gates, acquire the route lock, and spawn the live run."""

    run_env = load_repo_dotenv(root, env)
    route = get_selection(request.selection_id)
    gate_payload = request.gates or {}
    overrides = dict(request.overrides or {})
    env_overrides = dict(request.env_overrides or {})
    next_goal_packet = context_packets.sanitize_operator_context_packet(request.next_goal_packet)
    if request.provider_profile:
        overrides.setdefault("provider_profile", request.provider_profile)
    if request.scenario_setup:
        overrides.setdefault("scenario_setup", request.scenario_setup)
    operator_session_context_json = context_packets.context_packet_json(next_goal_packet)
    if operator_session_context_json:
        overrides.setdefault("operator_session_context_json", operator_session_context_json)
    env_overrides = provider_env_overrides_for_route(
        route, overrides, env_overrides, error_type=ConsoleLaunchError
    )
    run_env = apply_env_overrides(route, run_env, env_overrides, error_type=ConsoleLaunchError)
    readiness = route_readiness(root, route, overrides=overrides, gates=gate_payload, env=run_env)
    if not readiness["can_start"]:
        raise ConsoleLaunchError(str(readiness["blocker"]))

    run_id, run_dir = _reserve_new_run_dir(root, route)
    lock = ResourceLock(root, route.lock_name)
    process: LaunchProcess | None = None
    try:
        if route.supports_operator_steer:
            overrides.setdefault("operator_messages_path", str(run_dir / MESSAGE_LOG))
        if route.supports_paused_handoff_resume:
            overrides.setdefault("operator_resume_requests_path", str(run_dir / RESUME_REQUEST_LOG))
        selected_intent = request.intent_id or route.intent_id
        launch_prompt = launch_prompt_for_intent(route, selected_intent, request.prompt)
        preview = build_prompt_preview(
            route,
            PromptPreviewRequest(
                intent_id=selected_intent,
                prompt=launch_prompt,
                overrides=overrides,
                env_overrides=prompt_preview_env(run_env, env_overrides),
            ),
        )
        launch_args = _build_request_launch_args(
            route,
            request,
            root=root,
            run_id=run_id,
            selected_intent=selected_intent,
            launch_prompt=launch_prompt,
            overrides=overrides,
        )
        plan = _resolve_console_launch_plan(launch_args)
        mcp_host, mcp_port = requested_mcp_endpoint(overrides)
        mcp_url = f"http://{mcp_host}:{mcp_port}/mcp"
        log_path = run_dir / "console-launch.log"
        lock_state = lock.acquire(run_id=run_id)
        with log_path.open("ab") as log_stream:
            process = spawn_launch_plan(
                plan,
                cwd=root,
                env={**run_env, **export_env_from_plan(plan)},
                stdout=log_stream,
                stderr=log_stream,
            )
        lock_state = _register_console_process(lock, run_id=run_id, process=process)
    except Exception:
        if process is not None:
            _terminate_and_reap_console_child(process)
        lock.release(run_id=run_id, force=True)
        _remove_empty_reserved_run_dir(run_dir)
        raise
    started_at_epoch = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    session = attach_run_to_session(root, run_id, request.operator_session_id)
    state = {
        "run_id": run_id,
        "operator_session_id": session["operator_session_id"],
        "parent_run_id": request.parent_run_id,
        "next_goal_packet": next_goal_packet,
        "prompt_preview": preview,
        "operator_prompt": preview["operator_prompt"],
        "agent_kickoff_prompt": preview["agent_kickoff_prompt"],
        "launch_selection": route.to_payload(),
        "route": route.to_payload(),
        "workflow_id": request.workflow_id,
        "selected_intent": selected_intent,
        "world_id": route.world_id,
        "backend_id": route.backend_id,
        "intent_id": selected_intent,
        "agent_engine_id": route.agent_engine_id,
        "provider_profile": env_overrides.get("ROBOCLAWS_PROVIDER_PROFILE")
        or route.provider_profile
        or "",
        "evidence_lane": route.evidence_lane,
        "scenario_setup": request.scenario_setup or route.scenario_setup,
        "phase": "starting",
        "pid": process.pid,
        "started_at_epoch": started_at_epoch,
        "started_at": started_at,
        "backend_lock": route.lock_name,
        "lock": lock_state.to_payload(),
        "mcp_host": mcp_host,
        "mcp_port": mcp_port,
        "mcp_url": mcp_url,
        "argv": public_surface_rerun_argv(launch_args),
        "env_overrides": public_env_overrides(env_overrides),
        "run_dir": str(run_dir),
    }
    (run_dir / "operator_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def route_readiness(
    root: Path,
    route: ConsoleLaunchSelection,
    *,
    overrides: dict[str, str] | None = None,
    env_overrides: dict[str, str] | None = None,
    gates: dict[str, bool] | None = None,
    env: dict[str, str] | None = None,
    runtime_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return route gate state used by both API and UI."""

    if not route.enabled:
        return {
            "can_start": False,
            "blocker": route.disabled_reason,
            "blocker_kind": "unavailable",
            "gates": [],
        }

    override_map = overrides or {}
    env_override_map = provider_env_overrides_for_route(
        route, override_map, env_overrides or {}, error_type=ConsoleLaunchError
    )
    env_map = apply_env_overrides(
        route, load_repo_dotenv(root, env), env_override_map, error_type=ConsoleLaunchError
    )
    gate_map = gates or {}
    if runtime_tasks is None:
        _, port = requested_mcp_endpoint(override_map)
        runtime_tasks = runtime_inventory_payload(root, ports=[port])["tasks"]
    lock_state, attachable_run, blocker, blocker_kind = _route_lock_readiness(root, route)
    provider_status = _provider_status(route, env_map)
    dependency_status = optional_world_dependency_status(
        route.world_id,
        overrides=override_map,
        env=env_map,
        root=root,
    )
    gate_rows, gate_blocker, gate_blocker_kind = route_gate_rows(
        root,
        route,
        override_map,
        gate_map,
        provider_status,
        runtime_tasks=runtime_tasks,
    )
    host, port = requested_mcp_endpoint(override_map)
    background_blockers = blocking_tasks_for_route(route, runtime_tasks, host=host, port=port)
    self_blocker_ids = set()
    if attachable_run:
        self_blocker_ids.add(f"operator-run:{attachable_run['run_id']}")
    launch_blockers = [
        task for task in background_blockers if str(task.get("id") or "") not in self_blocker_ids
    ]
    named_launch_blockers = [
        task for task in launch_blockers if str(task.get("owner") or "") != "port-owner"
    ]
    if gate_blocker and named_launch_blockers and gate_blocker_kind == "mcp_port_in_use":
        blocker = background_blocker_message(named_launch_blockers)
        blocker_kind = "background_task"
    elif not blocker and gate_blocker:
        blocker = gate_blocker
        blocker_kind = gate_blocker_kind
    if not blocker and not dependency_status["ok"]:
        blocker = str(dependency_status["message"])
        blocker_kind = "optional_world_dependency"
    if not blocker and named_launch_blockers:
        blocker = background_blocker_message(named_launch_blockers)
        blocker_kind = "background_task"
    return {
        "can_start": not blocker,
        "blocker": blocker,
        "blocker_kind": blocker_kind,
        "lock": lock_state.to_payload(),
        "attachable_run": attachable_run,
        "background_blockers": background_blockers,
        "provider": provider_status,
        "optional_world_dependencies": {
            key: value for key, value in dependency_status.items() if key != "values"
        },
        "gates": gate_rows,
    }


def _route_lock_readiness(
    root: Path,
    route: ConsoleLaunchSelection,
) -> tuple[Any, dict[str, Any] | None, str, str]:
    lock = ResourceLock(root, route.lock_name)
    lock_state = lock.read()
    lock_source_error = ""
    try:
        released_terminal_lock = _release_terminal_owner_lock(root, lock_state)
    except _JsonSourceError as exc:
        released_terminal_lock = False
        lock_source_error = _lock_source_error_message(exc)
    if released_terminal_lock:
        lock_state = lock.read()
    try:
        attachable_run = _attachable_run_payload(root, lock_state)
    except _JsonSourceError as exc:
        attachable_run = None
        lock_source_error = _lock_source_error_message(exc)
    if lock_source_error:
        return lock_state, attachable_run, lock_source_error, "source_error"
    lock_active = lock_state.held and (not lock_state.stale or bool(attachable_run))
    if not lock_active:
        return lock_state, attachable_run, "", ""
    if attachable_run:
        blocker = (
            f"Backend lock is held by run {attachable_run['run_id']}. "
            "Attach to the existing run or wait for it to finish."
        )
    else:
        blocker = "Backend lock is held by another run. Open that run or wait for it to finish."
    return lock_state, attachable_run, blocker, "locked"


def _lock_source_error_message(error: _JsonSourceError) -> str:
    return f"Backend lock owner source error: {error.path.name} {error.reason}"


def _provider_status(route: ConsoleLaunchSelection, env_map: dict[str, str]) -> dict[str, Any]:
    if route.agent_engine_id == "openai-agents-sdk":
        return _with_evidence_lane_compatibility(
            route,
            _openai_agents_provider_status(env_map),
        )
    return {
        "agent_engine": route.agent_engine_id,
        "provider": "",
        "model": "",
        "required_env": [],
        "missing_env": [],
        "ok": provider_key_present(route, env_map),
        "message": "",
    }


def _with_evidence_lane_compatibility(
    selection: ConsoleLaunchSelection,
    status: dict[str, Any],
) -> dict[str, Any]:
    provider = str(status.get("provider") or selection.provider_profile or "")
    model = str(status.get("model") or "")
    if not provider:
        return status
    try:
        compatibility = evidence_lane_compatibility(
            evidence_lane=selection.evidence_lane,
            agent_engine=selection.agent_engine_id,
            provider_profile=provider,
            model_id=model,
        )
    except (KeyError, ValueError) as exc:
        blocked = dict(status)
        blocked["ok"] = False
        blocked["message"] = (
            "provider/evidence-lane compatibility lookup failed for "
            f"{selection.agent_engine_id}+{provider} on {selection.evidence_lane}: {exc}"
        )
        return blocked
    enriched = dict(status)
    enriched["evidence_lane_compatible"] = compatibility.allowed
    if not compatibility.allowed:
        enriched["capability_blocker"] = compatibility.reason
    return enriched


def _openai_agents_provider_status(env_map: dict[str, str]) -> dict[str, Any]:
    provider = env_map.get("ROBOCLAWS_PROVIDER_PROFILE") or default_provider_profile(
        "openai-agents-sdk"
    )
    try:
        settings = openai_agents_runtime_settings(
            provider_profile=provider,
            request_provider_profile=None,
            model=None,
            request_model=None,
            base_url=None,
            api_key=None,
            env=env_map,
        )
    except ValueError as exc:
        readiness = provider_readiness(
            agent_engine="openai-agents-sdk",
            provider_profile=provider,
            env=env_map,
        )
        blocked = dict(readiness)
        blocked["ok"] = False
        blocked["message"] = str(exc)
        return blocked
    return provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile=settings["provider_profile"],
        model=settings["model"],
        env=env_map,
    )


def _attachable_run_payload(root: Path, lock_state: Any) -> dict[str, Any] | None:
    if not lock_state.held or not lock_state.owner_run_id:
        return None
    run_dir = console_output_root(root) / "runs" / lock_state.owner_run_id
    state_path = run_dir / "operator_state.json"
    if not state_path.exists():
        return None
    state = _read_json_source(state_path)
    route_payload = state.get("route") if isinstance(state.get("route"), dict) else {}
    display_run_dir = resolve_display_run_dir(run_dir)
    live_status = _read_optional_json_source(display_run_dir / "live_status.json")
    if _existing_terminal_phase(display_run_dir, state):
        return None
    active_pid = _live_run_pid(display_run_dir) or lock_state.pid
    if lock_state.stale and not _display_run_attachable(display_run_dir, live_status, active_pid):
        return None
    launch_payload = (
        state.get("launch_selection") if isinstance(state.get("launch_selection"), dict) else {}
    )
    return {
        "run_id": str(state.get("run_id") or lock_state.owner_run_id),
        "selection_id": str(
            route_payload.get("selection_id")
            or launch_payload.get("id")
            or route_payload.get("id")
            or ""
        ),
        "route_label": str(route_payload.get("label") or "Agent run"),
        "phase": str(live_status.get("phase") or state.get("phase") or "running"),
        "run_dir": str(state.get("run_dir") or run_dir),
        "display_run_dir": str(display_run_dir),
        "backend_lock": str(state.get("backend_lock") or lock_state.name),
        "pid": active_pid,
        "started_at": str(state.get("started_at") or ""),
    }


def _display_run_attachable(
    display_run_dir: Path,
    live_status: dict[str, Any],
    active_pid: int | None,
) -> bool:
    phase = str(live_status.get("phase") or "").lower()
    if is_terminal_run_phase(phase) and "exit_status" in live_status:
        return False
    if phase:
        return True
    if active_pid and pid_is_active(active_pid):
        return True
    if _tmux_session_active(display_run_dir):
        return True
    return False


def _release_terminal_owner_lock(root: Path, lock_state: Any) -> bool:
    if not lock_state.held or not lock_state.owner_run_id:
        return False
    run_dir = console_output_root(root) / "runs" / lock_state.owner_run_id
    state_path = run_dir / "operator_state.json"
    if not state_path.exists():
        return False
    state = _read_json_source(state_path)
    display_run_dir = resolve_display_run_dir(run_dir)
    if not _existing_terminal_phase(display_run_dir, state):
        return False
    ResourceLock(root, lock_state.name).release(run_id=lock_state.owner_run_id, force=True)
    return True
