"""Typed execution adapters for resolved public launch plans."""

from __future__ import annotations

import os
import shlex
import signal
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any

from roboclaws.household.household_mcp_endpoint import (
    DEFAULT_MCP_PORT,
    EVAL_HARNESS_MCP_PORT_ENV,
)
from roboclaws.household.planner_proof_execution import (
    DEFAULT_MAP_BUNDLE,
    PlannerProofRequest,
    execute_planner_proof,
)
from roboclaws.household.profiles import validate_evidence_lane_camera_labeler
from roboclaws.household.subprocess_backend import DEFAULT_MOLMOSPACES_PYTHON
from roboclaws.launch.household import execute_household_plan
from roboclaws.launch.plans import LaunchPlan
from roboclaws.launch.runners import _append_optional, _die, _exec_or_trace, _get
from roboclaws.launch.worlds import resolve_optional_world_dependencies

SUPPORTED_OVERRIDE_KEYS = frozenset(
    (
        "agibot_map_artifact_dir agent_engine b1_alignment_artifact b1_navigation_artifact "
        "backend camera_labeler "
        "context_json evidence_lane "
        "generated_mess_manifest_path generated_mess_object_ids goal_contract_path "
        "host intent isaac_scene_usd_path map_bundle "
        "min_generated_mess_count mode model molmospaces_python operator_messages_path "
        "operator_resume_requests_path operator_session_context_json output_dir policy port preset "
        "prompt provider_profile real_movement_enabled "
        "relocation_count report robot_name robot_views run_dir "
        "run_preset runner_python runner_script runtime runtime_map_prior scenario_setup "
        "scene_index scene_source "
        "seed seeds steps surface timeout_s "
        "visual_grounding_timeout_s "
        "waypoint_id world"
    ).split()
)


def validate_named_overrides(overrides: tuple[str, ...]) -> None:
    """Reject malformed or unknown launch inputs before adapter selection."""

    for override in overrides:
        key, separator, _value = override.partition("=")
        if not separator or not key:
            raise ValueError(f"launch argument {override!r} is not key=value")
        if key not in SUPPORTED_OVERRIDE_KEYS:
            raise ValueError(f"unsupported launch override {key!r}")


class LaunchProcess:
    """Minimal process handle for a forked typed-plan execution."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        waited_pid, status = os.waitpid(self.pid, os.WNOHANG)
        if waited_pid:
            self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        import time

        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                import subprocess

                raise subprocess.TimeoutExpired("typed launch plan", timeout)
            time.sleep(0.05)
        return int(self.returncode)

    def terminate(self) -> None:
        if self.poll() is None:
            os.killpg(self.pid, signal.SIGTERM)


def spawn_launch_plan(
    plan: LaunchPlan,
    *,
    cwd: Path,
    env: dict[str, str],
    stdout: IO[Any],
    stderr: IO[Any],
) -> LaunchProcess:
    """Fork a child that executes an already resolved launch plan."""

    pid = os.fork()
    if pid:
        return LaunchProcess(pid)
    try:
        os.setsid()
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(env)
        os.dup2(stdout.fileno(), 1)
        os.dup2(stderr.fileno(), 2)
        raise SystemExit(execute_launch_plan(plan))
    except BaseException as exc:  # noqa: BLE001 - child must terminate without unwinding parent.
        code = int(exc.code) if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        if not isinstance(exc, SystemExit):
            traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)


def execute_launch_plan(plan: LaunchPlan) -> int:
    """Execute one already validated launch plan through its typed adapter."""

    kv = dict(plan.adapter_options)
    if plan.surface == "household-world":
        return _household_run(
            plan=plan,
            adapter_options=plan.adapter_options,
            kv=kv,
        )
    if plan.surface == "planner-proof":
        return _planner_proof_run(
            plan=plan,
            adapter_options=plan.adapter_options,
            kv=kv,
        )
    _die(f"unsupported launch surface {plan.surface!r}")


def _household_run(
    *,
    plan: LaunchPlan,
    adapter_options: Mapping[str, str],
    kv: dict[str, str],
) -> int:
    dispatch_surface = plan.surface
    dispatch_intent = plan.intent
    driver = plan.dispatch_runner
    profile = plan.profile or plan.evidence_mode
    backend = plan.implementation_backend
    world_id = plan.world
    try:
        kv = {
            **kv,
            **resolve_optional_world_dependencies(
                world_id,
                overrides=kv,
                env=dict(os.environ),
            ),
        }
    except ValueError as exc:
        _die(str(exc))

    seeds = _get(kv, "seeds", _get(kv, "seed", "7"))
    output_dir = _get(
        kv,
        "output_dir",
        f"output/household/{dispatch_surface}/{dispatch_intent}/{driver}-{profile}",
    )
    prompt = _prompt_for(dispatch_intent, plan.goal_contract.raw_prompt)
    camera_labeler, visual_grounding_timeout_s = _profile_options(profile, kv)

    if backend == "agibot_gdk":
        return _agibot_gdk_run(
            dispatch_intent=dispatch_intent,
            agent_engine=plan.agent_engine,
            provider_profile=plan.provider_profile,
            driver=driver,
            profile=profile,
            seeds=seeds,
            output_dir=output_dir,
            prompt=prompt,
            host=_get(kv, "host", "127.0.0.1"),
            port=_get(
                kv,
                "port",
                os.environ.get(EVAL_HARNESS_MCP_PORT_ENV, str(DEFAULT_MCP_PORT)),
            ),
            camera_labeler=camera_labeler,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            resolved_task_intent=plan.intent,
            backend=backend,
            kv=kv,
        )
    _export_rerun_command(plan=plan, adapter_options=adapter_options)
    return execute_household_plan(
        plan=plan,
        kv=kv,
    )


def _profile_options(profile: str, kv: dict[str, str]) -> tuple[str, str]:
    camera_labeler = _get(kv, "camera_labeler", "")
    visual_grounding_timeout_s = _get(
        kv,
        "visual_grounding_timeout_s",
        "auto",
    )
    try:
        camera_labeler = validate_evidence_lane_camera_labeler(
            evidence_lane="world-public-labels" if profile == "smoke" else profile,
            camera_labeler=camera_labeler,
        )
    except ValueError as exc:
        _die(str(exc))
    return camera_labeler, visual_grounding_timeout_s


def _agibot_gdk_run(
    *,
    dispatch_intent: str,
    agent_engine: str,
    provider_profile: str | None,
    driver: str,
    profile: str,
    seeds: str,
    output_dir: str,
    prompt: str,
    host: str,
    port: str,
    camera_labeler: str,
    visual_grounding_timeout_s: str,
    resolved_task_intent: str,
    backend: str,
    kv: dict[str, str],
) -> int:
    if dispatch_intent == "map-build" and driver == "openai-agents-live":
        return _agibot_gdk_live_map_build(
            agent_engine=agent_engine,
            provider_profile=provider_profile,
            profile=profile,
            seeds=seeds,
            output_dir=output_dir,
            prompt=prompt,
            host=host,
            port=port,
            camera_labeler=camera_labeler,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            resolved_task_intent=resolved_task_intent,
            backend=backend,
            kv=kv,
        )
    return _agibot_gdk_cleanup(output_dir, kv)


def _agibot_gdk_live_map_build(
    *,
    agent_engine: str,
    provider_profile: str | None,
    profile: str,
    seeds: str,
    output_dir: str,
    prompt: str,
    host: str,
    port: str,
    camera_labeler: str,
    visual_grounding_timeout_s: str,
    resolved_task_intent: str,
    backend: str,
    kv: dict[str, str],
) -> int:
    context_json = _get(kv, "context_json", "")
    if not context_json:
        _die(
            f"backend=agibot_gdk surface=household-world task_intent=map-build {agent_engine} "
            "requires context_json=<agibot map context JSON>"
        )
    if len(seeds.split()) != 1:
        _die(
            f"Agibot surface=household-world task_intent=map-build {agent_engine} "
            "accepts exactly one seed per live run"
        )
    run_dir = _get(kv, "run_dir", "") or f"{output_dir}/seed-{seeds}"
    policy = _get(kv, "policy", "openai_agents_agibot_map_build")
    server_args = _agibot_gdk_server_args(
        host=host,
        port=port,
        run_dir=run_dir,
        context_json=context_json,
        policy=policy,
        prompt=prompt,
        profile=profile,
        camera_labeler=camera_labeler,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        kv=kv,
    )
    cmd = [
        ".venv/bin/python",
        "-m",
        "roboclaws.agents.household_live_runner",
        "--repo-root",
        os.getcwd(),
        "--run-dir",
        run_dir,
        "--status-path",
        f"{run_dir}/live_status.json",
        "--client-url",
        f"http://{host}:{port}/mcp",
        "--host",
        host,
        "--port",
        port,
        "--lock-path",
        f"{run_dir}/household-live.lock",
        "--provider-profile",
        provider_profile or "",
        "--model",
        _get(
            kv,
            "model",
            os.environ.get(
                "ROBOCLAWS_OPENAI_AGENTS_MODEL",
                "",
            ),
        ),
        "--server-startup-timeout-s",
        os.environ.get("ROBOCLAWS_AGIBOT_MAP_BUILD_LIVE_SERVER_STARTUP_TIMEOUT_S", "600"),
        "--kickoff-prompt",
        prompt,
        "--profile",
        profile,
        "--checker-profile",
        profile,
        "--min-generated-mess-count",
        "0",
        "--backend",
        backend,
        "--policy",
        policy,
        "--task",
        resolved_task_intent,
    ]
    cmd.extend(f"--server-arg={arg}" for arg in server_args)
    return _exec_or_trace(cmd)


def _agibot_gdk_server_args(
    *,
    host: str,
    port: str,
    run_dir: str,
    context_json: str,
    policy: str,
    prompt: str,
    profile: str,
    camera_labeler: str,
    visual_grounding_timeout_s: str,
    kv: dict[str, str],
) -> list[str]:
    server_args = [
        "--host",
        host,
        "--port",
        port,
        "--output-dir",
        run_dir,
        "--backend",
        "agibot_gdk",
        "--intent",
        "map-build",
        "--context-json",
        context_json,
        "--policy",
        policy,
        "--task",
        prompt,
        "--evidence-lane",
        profile,
    ]
    if profile == "camera-grounded-labels":
        server_args.extend(["--visual-grounding", camera_labeler])
    if visual_grounding_timeout_s not in {"", "auto"}:
        server_args.extend(["--visual-grounding-timeout-s", visual_grounding_timeout_s])
    for capability_profile in ("household_world", "household_episode"):
        server_args.extend(["--required-capability-profile", capability_profile])
    _append_optional(server_args, kv, "runner_python", "--runner-python")
    _append_optional(server_args, kv, "runner_script", "--runner-script")
    _append_optional(server_args, kv, "agibot_map_artifact_dir", "--agibot-map-artifact-dir")
    _append_bool_flag(server_args, kv, "real_movement_enabled", "--real-movement-enabled")
    return server_args


def _agibot_gdk_cleanup(output_dir: str, kv: dict[str, str]) -> int:
    cmd = [
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        output_dir,
    ]
    _append_optional(cmd, kv, "context_json", "--context-json")
    _append_optional(cmd, kv, "waypoint_id", "--waypoint-id")
    _append_optional(cmd, kv, "run_dir", "--run-dir")
    _append_optional(cmd, kv, "runner_python", "--runner-python")
    _append_optional(cmd, kv, "runner_script", "--runner-script")
    _append_optional(cmd, kv, "agibot_map_artifact_dir", "--agibot-map-artifact-dir")
    _append_bool_flag(cmd, kv, "real_movement_enabled", "--real-movement-enabled")
    return _exec_or_trace(cmd)


def _append_bool_flag(cmd: list[str], kv: dict[str, str], key: str, flag: str) -> None:
    real_movement_enabled = _get(kv, "real_movement_enabled", "false")
    if real_movement_enabled in {"true", "1", "yes", "on"}:
        cmd.append(flag)
    elif real_movement_enabled not in {"false", "0", "no", "off", ""}:
        _die(f"unsupported real_movement_enabled '{real_movement_enabled}' (expected true|false)")


def _planner_proof_run(
    *,
    plan: LaunchPlan,
    adapter_options: Mapping[str, str],
    kv: dict[str, str],
) -> int:
    if (plan.surface, plan.intent, plan.dispatch_runner) not in {
        ("planner-proof", "planner-proof", "direct"),
        ("planner-proof", "planner-proof", "mcp-smoke"),
    }:
        _die(
            "unsupported surface/intent/driver route "
            f"'{plan.surface}.{plan.intent}:{plan.dispatch_runner}'"
        )
    requested_mode = _get(kv, "mode", "dry-run")
    if requested_mode == "dry-run":
        mode = "dry-run"
        default_output_dir = "output/molmo-planner-proof-bundle-runner-harness"
    elif requested_mode == "execute-rerun":
        mode = "execute-rerun"
        default_output_dir = "output/molmo-planner-proof-bundle-execute-rerun"
    else:
        _die(
            f"unsupported molmo-planner-proof mode '{requested_mode}' "
            "(expected dry-run|execute-rerun)"
        )

    request = PlannerProofRequest(
        output_dir=Path(_get(kv, "output_dir", default_output_dir)),
        mode=mode,
        seed=int(_get(kv, "seed", "7")),
        task_prompt=_prompt_for("cleanup", plan.goal_contract.raw_prompt),
        generated_mess_count=10,
        min_generated_mess_count=int(_get(kv, "min_generated_mess_count", "5")),
        map_bundle_dir=Path(_get(kv, "map_bundle", str(DEFAULT_MAP_BUNDLE))),
        steps=int(_get(kv, "steps", "2")),
        timeout_s=float(_get(kv, "timeout_s", "600")),
        runner_python=Path(_get(kv, "runner_python", sys.executable)),
        molmospaces_python=Path(_get(kv, "molmospaces_python", str(DEFAULT_MOLMOSPACES_PYTHON))),
    )
    _export_rerun_command(plan=plan, adapter_options=adapter_options)
    if os.environ.get("ROBOCLAWS_JUST_TRACE") == "1":
        return _exec_or_trace(_planner_proof_trace_command(request))
    execute_planner_proof(request)
    return 0


def _planner_proof_trace_command(request: PlannerProofRequest) -> list[str]:
    return [
        sys.executable,
        "-m",
        "roboclaws.household.planner_proof_execution",
        "--output-dir",
        str(request.output_dir),
        "--mode",
        request.mode,
        "--seed",
        str(request.seed),
        "--task",
        request.task_prompt,
        "--generated-mess-count",
        str(request.generated_mess_count),
        "--min-generated-mess-count",
        str(request.min_generated_mess_count),
        "--map-bundle-dir",
        str(request.map_bundle_dir),
        "--steps",
        str(request.steps),
        "--timeout-s",
        str(request.timeout_s),
        "--runner-python",
        str(request.runner_python),
        "--molmospaces-python",
        str(request.molmospaces_python),
    ]


def _prompt_for(dispatch_intent: str, raw_prompt: str) -> str:
    default = (
        "帮我建立这个房间的 Runtime Metric Map"
        if dispatch_intent == "map-build"
        else "帮我收拾这个房间"
    )
    return raw_prompt or default


def _export_rerun_command(
    *,
    plan: LaunchPlan,
    adapter_options: Mapping[str, str],
) -> None:
    parts = [
        "just",
        "run::surface",
        f"surface={plan.surface}",
        f"world={plan.world}",
        f"backend={plan.backend}",
        f"agent_engine={plan.agent_engine}",
    ]
    parts.append(f"preset={plan.preset}" if plan.preset else f"intent={plan.intent}")
    if plan.provider_profile:
        parts.append(f"provider_profile={plan.provider_profile}")
    if plan.surface == "household-world":
        if plan.evidence_mode == "smoke":
            parts.extend(["run_preset=smoke", "evidence_lane=world-public-labels"])
        else:
            parts.append(f"evidence_lane={plan.profile or plan.evidence_mode}")
    elif plan.report:
        parts.append(f"report={plan.report}")
    if plan.goal_contract.raw_prompt:
        parts.append(f"prompt={plan.goal_contract.raw_prompt}")
    if plan.scenario_setup:
        parts.append(f"scenario_setup={plan.scenario_setup}")
    if plan.relocation_count is not None:
        parts.append(f"relocation_count={plan.relocation_count}")
    parts.extend(f"{key}={value}" for key, value in adapter_options.items())
    os.environ["ROBOCLAWS_REPORT_RERUN_COMMAND"] = shlex.join(parts)
