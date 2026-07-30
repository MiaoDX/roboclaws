"""Safe launcher for operator-console SDK/direct routes."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.provider_registry import (
    default_provider_profile,
    openai_agents_runtime_settings,
    provider_readiness,
)
from roboclaws.core.dotenv import load_dotenv_file
from roboclaws.core.json_sources import read_json_object
from roboclaws.household.evidence_lane_policy import evidence_lane_compatibility
from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.launch.executor import LaunchProcess, spawn_launch_plan
from roboclaws.launch.worlds import optional_world_dependency_status
from roboclaws.operator_console import context_packets
from roboclaws.operator_console.interactions import (
    MESSAGE_LOG,
    RESUME_REQUEST_LOG,
    attach_run_to_session,
)
from roboclaws.operator_console.launch_support import (
    DockerMountSourceError,
    apply_env_overrides,
    build_surface_launch_args,
    docker_container_ids_with_mount,
    launch_prompt_for_intent,
    provider_env_overrides_for_route,
    public_env_overrides,
)
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.prompt_preview import (
    PromptPreviewRequest,
    build_prompt_preview,
    prompt_preview_env,
)
from roboclaws.operator_console.readiness import route_gate_rows
from roboclaws.operator_console.routes import (
    ConsoleLaunchSelection,
    get_selection,
    selection_task_selector,
)
from roboclaws.operator_console.runtime_compat import pid_is_active  # noqa: F401
from roboclaws.operator_console.runtime_inventory import (
    background_blocker_message,
    blocking_tasks_for_route,
    requested_mcp_endpoint,
    runtime_inventory_payload,
)
from roboclaws.operator_console.state import resolve_display_run_dir
from roboclaws.operator_console.state_summary import (
    existing_terminal_phase,
    existing_terminal_reason,
    is_terminal_run_phase,
)
from roboclaws.operator_console.workflows import (
    get_operator_workflow,
    runtime_map_prior_for_workflow,
    runtime_prior_override_exists,
)

RUN_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class ConsoleLaunchError(ValueError):
    """User-facing launch validation error."""


class _JsonSourceError(ValueError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


@dataclass(frozen=True)
class LaunchRequest:
    world_id: str = ""
    backend_id: str = ""
    intent_id: str = ""
    agent_engine_id: str = ""
    provider_profile: str = ""
    evidence_lane: str = ""
    scenario_setup: str = ""
    prompt: str = ""
    overrides: dict[str, str] | None = None
    env_overrides: dict[str, str] | None = None
    gates: dict[str, bool] | None = None
    operator_session_id: str = ""
    parent_run_id: str = ""
    next_goal_packet: dict[str, Any] | None = None
    selection_id_override: str = ""
    workflow_id: str = ""

    @property
    def selection_id(self) -> str:
        if self.world_id and self.backend_id and self.intent_id and self.agent_engine_id:
            lane = self.evidence_lane or "world-public-labels"
            return "::".join(
                (
                    self.world_id,
                    self.backend_id,
                    selection_task_selector(self.intent_id),
                    self.agent_engine_id,
                    lane,
                )
            )
        if not self.selection_id_override:
            raise ConsoleLaunchError(
                "launch requires world/backend/intent/agent_engine/evidence_lane or selection_id"
            )
        return self.selection_id_override


def load_repo_dotenv(root: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment with repo-local ``.env`` values loaded when present."""

    return load_dotenv_file(root / ".env", env)


def provider_key_present(route: ConsoleLaunchSelection, env: dict[str, str] | None = None) -> bool:
    env_map = os.environ if env is None else env
    if route.agent_engine_id == "openai-agents-sdk":
        return _openai_agents_provider_status(env_map)["ok"]
    return False


def build_launch_argv(
    route: ConsoleLaunchSelection,
    *,
    root: Path,
    run_id: str,
    intent: str = "",
    prompt: str = "",
    overrides: dict[str, str] | None = None,
) -> list[str]:
    """Build a fixed argv list for a console route."""

    output_dir = console_output_root(root) / "runs" / run_id
    args = build_surface_launch_args(
        route,
        selected_intent=intent,
        prompt=prompt,
        overrides=overrides,
        output_dir=output_dir,
        error_type=ConsoleLaunchError,
    )
    try:
        resolve_surface_launch(args)
    except LaunchError as exc:
        raise ConsoleLaunchError(str(exc)) from exc
    return ["just", "run::surface", *args]


def build_workflow_launch_argv(
    route: ConsoleLaunchSelection,
    *,
    workflow_id: str,
    root: Path,
    run_id: str,
    prompt: str = "",
    overrides: dict[str, str] | None = None,
) -> list[str]:
    """Build argv for an operator workflow action through the route catalog."""

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
    return build_launch_argv(
        route,
        root=root,
        run_id=run_id,
        intent=workflow.intent_id,
        prompt=prompt,
        overrides=request_overrides,
    )


def _build_request_launch_argv(
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
        return build_workflow_launch_argv(
            route,
            workflow_id=request.workflow_id,
            root=root,
            run_id=run_id,
            prompt=launch_prompt,
            overrides=overrides,
        )
    return build_launch_argv(
        route,
        root=root,
        run_id=run_id,
        intent=selected_intent,
        prompt=launch_prompt,
        overrides=overrides,
    )


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
        argv = _build_request_launch_argv(
            route,
            request,
            root=root,
            run_id=run_id,
            selected_intent=selected_intent,
            launch_prompt=launch_prompt,
            overrides=overrides,
        )
        plan = resolve_surface_launch(argv[2:])
        mcp_host, mcp_port = requested_mcp_endpoint(overrides)
        mcp_url = f"http://{mcp_host}:{mcp_port}/mcp"
        log_path = run_dir / "console-launch.log"
        lock_state = lock.acquire(run_id=run_id)
        with log_path.open("ab") as log_stream:
            process = spawn_launch_plan(
                plan,
                cwd=root,
                env=run_env,
                stdout=log_stream,
                stderr=log_stream,
            )
        lock_state = lock.update_pid(run_id=run_id, pid=process.pid)
    except Exception:
        if process is not None:
            process.terminate()
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
        "argv": argv,
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


def stop_console_run(root: Path, run_id: str, *, emergency: bool = False) -> dict[str, Any]:
    run_dir = console_output_root(root) / "runs" / run_id
    state_path = run_dir / "operator_state.json"
    if not state_path.exists():
        raise ConsoleLaunchError(f"unknown run id: {run_id}")
    try:
        state = _read_json_source(state_path)
    except _JsonSourceError as exc:
        raise _operator_stop_source_error(exc) from exc
    display_run_dir = resolve_display_run_dir(run_dir)
    terminal_phase = "human_takeover_stop" if emergency else "stopped_by_operator"
    try:
        existing_phase = _existing_terminal_phase(display_run_dir, state)
        terminal_reason = (
            _existing_terminal_reason(display_run_dir, state) if existing_phase else ""
        )
    except _JsonSourceError as exc:
        raise _operator_stop_source_error(exc) from exc
    _stop_live_child_run(display_run_dir)
    pid = state.get("pid")
    _terminate_process_group(pid if isinstance(pid, int) else None)
    if existing_phase:
        state["phase"] = existing_phase
        state["terminal_reason"] = terminal_reason or (
            state.get("terminal_reason") or existing_phase
        )
    else:
        try:
            _mark_live_child_stopped(display_run_dir, terminal_phase)
        except _JsonSourceError as exc:
            raise _operator_stop_source_error(exc) from exc
        state["phase"] = terminal_phase
        state["terminal_reason"] = state["phase"]
    state["stopped_at_epoch"] = time.time()
    state["display_run_dir"] = str(display_run_dir)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    route_payload = state.get("route") or {}
    lock_name = str(route_payload.get("lock_name") or state.get("backend_lock") or "")
    if lock_name:
        ResourceLock(root, lock_name).release(run_id=run_id, force=True)
    return state


def _operator_stop_source_error(error: _JsonSourceError) -> ConsoleLaunchError:
    return ConsoleLaunchError(f"operator stop source error: {error.path.name} {error.reason}")


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


def _existing_terminal_phase(display_run_dir: Path, state: dict[str, Any]) -> str:
    return existing_terminal_phase(
        display_run_dir,
        state,
        read_json=_read_optional_json_source,
    )


def _existing_terminal_reason(display_run_dir: Path, state: dict[str, Any]) -> str:
    return existing_terminal_reason(
        display_run_dir,
        state,
        read_json=_read_optional_json_source,
    )


def _live_run_pid(display_run_dir: Path) -> int | None:
    server_pid_path = display_run_dir / "server.pid"
    if not server_pid_path.is_file():
        return None
    try:
        pid = int(server_pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _stop_live_child_run(display_run_dir: Path) -> None:
    live_pid = _live_run_pid(display_run_dir)
    stop_pids = _live_run_stop_pids(live_pid)
    _stop_docker_containers_for_run(display_run_dir)
    _kill_tmux_session(display_run_dir)
    for pid in stop_pids:
        _terminate_process_group(pid)


def _mark_live_child_stopped(display_run_dir: Path, phase: str) -> None:
    display_run_dir.mkdir(parents=True, exist_ok=True)
    status_path = display_run_dir / "live_status.json"
    payload = _read_optional_json_source(status_path)
    payload.update(
        {
            "phase": phase,
            "terminal_reason": phase,
            "finished_at_epoch": time.time(),
            "exit_status": 130,
        }
    )
    status_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _live_run_stop_pids(live_pid: int | None) -> list[int]:
    if not live_pid or live_pid <= 0:
        return []
    pids = [live_pid]
    parent_pid = _process_parent_pid(live_pid)
    if parent_pid and _safe_process_pid(parent_pid):
        pids.append(parent_pid)
        pids.extend(_descendant_pids(parent_pid))
    else:
        pids.extend(_descendant_pids(live_pid))
    return _dedupe_pids(pids)


def _terminate_process_group(pid: int | None) -> None:
    if not pid or pid <= 0:
        return
    _signal_process_group_or_pid(pid, signal.SIGTERM)
    deadline = time.monotonic() + 1.0
    while pid_is_active(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if pid_is_active(pid):
        _signal_process_group_or_pid(pid, signal.SIGKILL)


def _signal_process_group_or_pid(pid: int, sig: signal.Signals) -> None:
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        pgid = pid
    except (PermissionError, OSError):
        pgid = None
    if pgid and pgid > 0:
        try:
            os.killpg(pgid, int(sig))
            return
        except ProcessLookupError:
            pass
        except (PermissionError, OSError):
            pass
    try:
        os.kill(pid, int(sig))
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _process_parent_pid(pid: int) -> int | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_proc_stat_parent_pid(raw)


def _descendant_pids(root_pid: int) -> list[int]:
    children_by_parent: dict[int, list[int]] = {}
    try:
        stat_paths = list(Path("/proc").glob("[0-9]*/stat"))
    except OSError:
        return []
    for stat_path in stat_paths:
        try:
            pid = int(stat_path.parent.name)
            parent_pid = _parse_proc_stat_parent_pid(stat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if parent_pid is None:
            continue
        children_by_parent.setdefault(parent_pid, []).append(pid)
    descendants: list[int] = []
    queue = list(children_by_parent.get(root_pid, []))
    while queue:
        pid = queue.pop(0)
        if not _safe_process_pid(pid):
            continue
        descendants.append(pid)
        queue.extend(children_by_parent.get(pid, []))
    return descendants


def _parse_proc_stat_parent_pid(raw: str) -> int | None:
    try:
        suffix = raw.rsplit(") ", 1)[1]
        fields = suffix.split()
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def _safe_process_pid(pid: int) -> bool:
    return pid > 1 and pid not in {os.getpid(), os.getppid()}


def _dedupe_pids(pids: list[int]) -> list[int]:
    seen: set[int] = set()
    output: list[int] = []
    for pid in pids:
        if pid in seen or not _safe_process_pid(pid):
            continue
        seen.add(pid)
        output.append(pid)
    return output


def _stop_docker_containers_for_run(display_run_dir: Path) -> None:
    workspace = (display_run_dir / "agent-docker-workspace").resolve()
    if not workspace.exists():
        return
    try:
        container_ids = _docker_container_ids_with_mount(workspace)
    except DockerMountSourceError as exc:
        raise ConsoleLaunchError(f"operator stop source error: {exc}") from exc
    for container_id in container_ids:
        subprocess.run(
            ["docker", "stop", "--time", "5", container_id],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _docker_container_ids_with_mount(source: Path) -> list[str]:
    return docker_container_ids_with_mount(source, run_command=subprocess.run)


def _read_optional_json_source(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json_source(path)


def _read_json_source(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label=path.name)
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            raise _JsonSourceError(path, f"contains invalid JSON at line {cause.lineno}") from exc
        raise _JsonSourceError(path, "must contain a JSON object") from exc
    except FileNotFoundError as exc:
        raise _JsonSourceError(path, "cannot be read: missing source") from exc
    except OSError as exc:
        raise _JsonSourceError(path, f"cannot be read: {exc}") from exc


def _tmux_session_active(display_run_dir: Path) -> bool:
    session_path = display_run_dir / "tmux_session.txt"
    if not session_path.is_file():
        return False
    try:
        session_name = session_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not session_name:
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _kill_tmux_session(display_run_dir: Path) -> None:
    session_path = display_run_dir / "tmux_session.txt"
    if not session_path.is_file():
        return
    try:
        session_name = session_path.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not session_name:
        return
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _new_run_id(route: ConsoleLaunchSelection) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return f"{timestamp}-{_safe_run_id_suffix(route.id)}"


def _reserve_new_run_dir(root: Path, route: ConsoleLaunchSelection) -> tuple[str, Path]:
    runs_dir = console_output_root(root) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    base_run_id = _new_run_id(route)
    for suffix in ("", *(f"-{index}" for index in range(2, 100))):
        run_id = f"{base_run_id}{suffix}"
        run_dir = runs_dir / run_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return run_id, run_dir
    raise ConsoleLaunchError(f"could not allocate unique operator-console run id: {base_run_id}")


def _remove_empty_reserved_run_dir(run_dir: Path) -> None:
    try:
        run_dir.rmdir()
    except OSError:
        pass


def _safe_run_id_suffix(raw: str) -> str:
    """Return a readable id fragment that is safe in paths and Docker bind specs."""

    slug = RUN_ID_SAFE_RE.sub("-", raw).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "run"
