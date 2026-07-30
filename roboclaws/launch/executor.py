"""Typed execution adapters for resolved public launch plans."""

from __future__ import annotations

import os
import shlex
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

from roboclaws.household.profiles import validate_evidence_lane_camera_labeler
from roboclaws.launch.plans import LaunchPlan
from roboclaws.launch.runners import _append_optional, _die, _exec_or_trace, _get
from roboclaws.launch.worlds import resolve_optional_world_dependencies

SUPPORTED_OVERRIDE_KEYS = frozenset(
    (
        "agibot_map_artifact_dir agent_engine b1_alignment_artifact b1_navigation_artifact "
        "b1_semantic_projection_artifact backend camera_labeler cleanup_object_count "
        "cleanup_routine context_json driver evidence_lane environment_setup generated_mess_count "
        "generated_mess_manifest_path generated_mess_object_ids goal_contract_path "
        "host intent isaac_scene_usd_path map_bundle map_mode "
        "min_generated_mess_count mode model molmospaces_python operator_messages_path "
        "operator_resume_requests_path operator_session_context_json output_dir policy port preset "
        "profile prompt provider_profile real_movement_enabled rehearsal_mode "
        "relocation_count report robot_name robot_views run_dir "
        "run_preset runner_python runner_script runtime runtime_map_prior scenario_setup "
        "scene_index scene_source "
        "seed seeds steps surface timeout_s "
        "visual_grounding visual_grounding_timeout_s "
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
        os._exit(code)


def execute_launch_plan(plan: LaunchPlan) -> int:
    """Execute one already validated launch plan through its typed adapter."""

    raw_overrides = list(plan.overrides)
    kv = _parse_overrides(raw_overrides)
    if plan.surface == "household-world":
        return _household_run(
            plan=plan,
            raw_overrides=raw_overrides,
            kv=kv,
        )
    if plan.surface == "planner-proof":
        return _planner_proof_run(
            plan=plan,
            kv=kv,
        )
    _die(f"unsupported launch surface {plan.surface!r}")


def _household_run(
    *,
    plan: LaunchPlan,
    raw_overrides: list[str],
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
    generated_mess_count = str(plan.relocation_count or 0)
    camera_labeler, visual_grounding_timeout_s = _profile_options(profile, kv)

    if backend == "agibot_molmospaces_sim":
        return _agibot_sim_run(
            dispatch_intent=dispatch_intent,
            driver=driver,
            profile=profile,
            seeds=seeds,
            output_dir=output_dir,
            prompt=prompt,
            generated_mess_count=generated_mess_count,
            robot_views=_get(kv, "robot_views", "auto"),
            camera_labeler=camera_labeler,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            resolved_task_intent=plan.intent,
            kv=kv,
        )
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
            port=_get(kv, "port", os.environ.get("ROBOCLAWS_EVAL_HARNESS_MCP_PORT", "18788")),
            camera_labeler=camera_labeler,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            resolved_task_intent=plan.intent,
            backend=backend,
            kv=kv,
        )
    return _molmo_household_run(
        plan=plan,
        raw_overrides=raw_overrides,
        kv=kv,
        seeds=seeds,
        output_dir=output_dir,
        prompt=prompt,
        backend=backend,
        camera_labeler=camera_labeler,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        generated_mess_count=generated_mess_count,
    )


def _profile_options(profile: str, kv: dict[str, str]) -> tuple[str, str]:
    if _get(kv, "visual_grounding", ""):
        _die(
            "visual_grounding is no longer a public task axis; "
            "use camera_labeler=<labeler> with evidence_lane=camera-grounded-labels"
        )
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


def _molmo_household_run(
    *,
    plan: LaunchPlan,
    raw_overrides: list[str],
    kv: dict[str, str],
    seeds: str,
    output_dir: str,
    prompt: str,
    backend: str,
    camera_labeler: str,
    visual_grounding_timeout_s: str,
    generated_mess_count: str,
) -> int:
    impl_driver = plan.dispatch_runner
    profile = plan.profile or plan.evidence_mode
    host = _get(kv, "host", "127.0.0.1")
    port = _get(kv, "port", os.environ.get("ROBOCLAWS_EVAL_HARNESS_MCP_PORT", "18788"))
    map_bundle = _get(kv, "map_bundle", "auto")
    b1_alignment_artifact = _get(kv, "b1_alignment_artifact", "")
    b1_navigation_artifact = _get(kv, "b1_navigation_artifact", "")
    cleanup_routine = _get(kv, "cleanup_routine", "skill")
    if cleanup_routine not in {"auto", "skill"}:
        _die(f"unsupported cleanup_routine '{cleanup_routine}' (expected auto|skill)")
    robot_views = _get(kv, "robot_views", "auto")
    map_build = "on" if plan.intent == "map-build" else "off"
    runtime_map_prior = _get(kv, "runtime_map_prior", "")
    operator_messages_path = _get(kv, "operator_messages_path", "")
    min_generated_mess_count = _get(kv, "min_generated_mess_count", "auto")
    generated_mess_object_ids = _get(kv, "generated_mess_object_ids", "")
    scene_source = _get(kv, "scene_source", "procthor-10k-val")
    scene_index = _get(kv, "scene_index", "0")
    isaac_scene_usd_path = _get(kv, "isaac_scene_usd_path", "")

    run_dir_override = _get(kv, "run_dir", "")
    skill_name = plan.skill_name
    env = {
        "ROBOCLAWS_EXEC_DRIVER": impl_driver,
        "ROBOCLAWS_EXEC_PROFILE": profile,
        "ROBOCLAWS_EXEC_SEEDS": seeds,
        "ROBOCLAWS_EXEC_OUTPUT_DIR": output_dir,
        "ROBOCLAWS_EXEC_TASK": prompt,
        "ROBOCLAWS_EXEC_GENERATED_MESS_COUNT": generated_mess_count,
        "ROBOCLAWS_EXEC_HOST": host,
        "ROBOCLAWS_EXEC_PORT": port,
        "ROBOCLAWS_EXEC_MAP_BUNDLE": map_bundle,
        "ROBOCLAWS_EXEC_CLEANUP_ROUTINE": cleanup_routine,
        "ROBOCLAWS_EXEC_ROBOT_VIEWS": robot_views,
        "ROBOCLAWS_EXEC_CAMERA_LABELER": camera_labeler,
        "ROBOCLAWS_EXEC_VISUAL_GROUNDING_TIMEOUT_S": visual_grounding_timeout_s,
        "ROBOCLAWS_EXEC_MAP_BUILD": map_build,
        "ROBOCLAWS_EXEC_RUNTIME_MAP_PRIOR": runtime_map_prior,
        "ROBOCLAWS_EXEC_BACKEND": backend,
        "ROBOCLAWS_EXEC_SCENE_SOURCE": scene_source,
        "ROBOCLAWS_EXEC_SCENE_INDEX": scene_index,
        "ROBOCLAWS_EXEC_ISAAC_SCENE_USD_PATH": isaac_scene_usd_path,
        "ROBOCLAWS_EXEC_MIN_GENERATED_MESS_COUNT": min_generated_mess_count,
        "ROBOCLAWS_EXEC_GENERATED_MESS_OBJECT_IDS": generated_mess_object_ids,
        "ROBOCLAWS_EXEC_TASK_SURFACE": plan.surface,
        "ROBOCLAWS_EXEC_TASK_INTENT": plan.intent,
        "ROBOCLAWS_EXEC_OPERATOR_MESSAGES_PATH": operator_messages_path,
        "ROBOCLAWS_EXEC_B1_ALIGNMENT_ARTIFACT": b1_alignment_artifact,
        "ROBOCLAWS_EXEC_B1_NAVIGATION_ARTIFACT": b1_navigation_artifact,
        "ROBOCLAWS_EXEC_SKILL_NAME": skill_name,
        "ROBOCLAWS_EXEC_RUN_DIR": run_dir_override,
        "ROBOCLAWS_GOAL_CONTRACT_JSON": plan.goal_contract.to_json(),
        "ROBOCLAWS_GOAL_CONTRACT_PATH": _get(
            kv,
            "goal_contract_path",
            os.environ.get("ROBOCLAWS_GOAL_CONTRACT_PATH", ""),
        ),
        "ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON": _get(
            kv,
            "operator_session_context_json",
            os.environ.get("ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON", ""),
        ),
        "ROBOCLAWS_LAUNCH_WORLD_ID": plan.world,
        "ROBOCLAWS_MOLMO_RUN_DIR_OVERRIDE": run_dir_override,
        "ROBOCLAWS_TASK_INTENT": plan.intent,
        "ROBOCLAWS_TASK_PRESET": plan.preset or "",
        "ROBOCLAWS_TASK_SKILL": skill_name,
        "ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES": ",".join(plan.required_capabilities),
        "ROBOCLAWS_GENERATED_MESS_MANIFEST_PATH": _get(
            kv,
            "generated_mess_manifest_path",
            "",
        ),
    }
    operator_resume_requests_path = _get(kv, "operator_resume_requests_path", "")
    if operator_resume_requests_path:
        env["ROBOCLAWS_OPERATOR_RESUME_REQUESTS_PATH"] = operator_resume_requests_path
    _export_rerun_command(
        plan=plan,
        raw_overrides=raw_overrides,
    )
    trace_args = [
        "just",
        "molmo::household-world-impl",
        *(
            f"{key.removeprefix('ROBOCLAWS_EXEC_').lower()}={value}"
            for key, value in env.items()
            if key.startswith("ROBOCLAWS_EXEC_")
        ),
    ]
    return _exec_or_trace(
        ["just", "molmo::household-world-impl"],
        env=env,
        trace_args=trace_args,
    )


def _agibot_sim_run(
    *,
    dispatch_intent: str,
    driver: str,
    profile: str,
    seeds: str,
    output_dir: str,
    prompt: str,
    generated_mess_count: str,
    robot_views: str,
    camera_labeler: str,
    visual_grounding_timeout_s: str,
    resolved_task_intent: str,
    kv: dict[str, str],
) -> int:
    if driver != "direct":
        _die("backend=agibot_molmospaces_sim currently supports direct driver only")
    if len(seeds.split()) != 1:
        _die("backend=agibot_molmospaces_sim accepts exactly one seed per run")
    rehearsal_mode = _get(
        kv,
        "rehearsal_mode",
        "cleanup-actions" if dispatch_intent in {"cleanup", "open-ended"} else "contract",
    )
    if rehearsal_mode not in {"contract", "cleanup-actions"}:
        _die(f"unsupported rehearsal_mode '{rehearsal_mode}' (expected contract|cleanup-actions)")
    runtime = _get(kv, "runtime", "fixture")
    if runtime not in {"fixture", "molmospaces-subprocess"}:
        _die(f"unsupported runtime '{runtime}' (expected fixture|molmospaces-subprocess)")
    cmd = [
        ".venv/bin/python",
        "scripts/molmo_cleanup/run_molmospaces_agibot_contract_rehearsal.py",
        "--output-dir",
        output_dir,
        "--seed",
        seeds,
        "--generated-mess-count",
        generated_mess_count,
        "--runtime",
        runtime,
        "--flow",
        "prehardware",
        "--intent",
        resolved_task_intent,
        "--profile",
        profile,
        "--task-prompt",
        prompt,
        "--rehearsal-mode",
        rehearsal_mode,
        "--cleanup-object-count",
        _get(kv, "cleanup_object_count", "2"),
    ]
    if profile == "camera-grounded-labels":
        cmd.extend(["--camera-labeler", camera_labeler])
        if visual_grounding_timeout_s not in {"", "auto"}:
            cmd.extend(["--visual-grounding-timeout-s", visual_grounding_timeout_s])
    _append_optional(cmd, kv, "molmospaces_python", "--molmospaces-python")
    _append_optional(cmd, kv, "robot_name", "--robot-name")
    _append_optional(cmd, kv, "waypoint_id", "--waypoint-id")
    _append_optional(cmd, kv, "run_dir", "--run-dir")
    _append_optional(cmd, kv, "context_json", "--context-json")
    _append_optional(cmd, kv, "agibot_map_artifact_dir", "--agibot-map-artifact-dir")
    if robot_views in {"on", "true", "1", "yes"} or (
        robot_views in {"auto", ""} and runtime == "molmospaces-subprocess"
    ):
        cmd.extend(["--include-robot", "--record-robot-views"])
    elif robot_views not in {"off", "false", "0", "no", "auto", ""}:
        _die(f"unsupported robot_views '{robot_views}' (expected auto|on|off)")
    return _exec_or_trace(cmd)


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
        "scripts/molmo_cleanup/run_physical_agibot_cleanup_pilot.py",
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
    mode = _get(kv, "mode", "dry-run").replace("_", "-")
    output_dir = _get(kv, "output_dir", "")
    seed = _get(kv, "seed", "7")
    prompt = _prompt_for("cleanup", plan.goal_contract.raw_prompt)
    generated_mess_count = _get(kv, "generated_mess_count", "10")
    map_bundle = _get(kv, "map_bundle", "assets/maps/molmospaces/procthor-10k-val/0")
    if mode in {"dry-run", "dry"}:
        cmd = ["just", "harness::molmo-planner-proof-bundle-runner"]
        if output_dir:
            cmd.extend([output_dir, seed, prompt, generated_mess_count, map_bundle])
        return _exec_or_trace(cmd)
    if mode in {"execute-rerun", "execute", "local"}:
        return _exec_or_trace(
            [
                "just",
                "harness::molmo-planner-proof-bundle-execute-rerun",
                output_dir or "output/molmo-planner-proof-bundle-execute-rerun",
                seed,
                prompt,
                generated_mess_count,
                _get(kv, "min_generated_mess_count", "5"),
                _get(kv, "steps", "2"),
                _get(kv, "timeout_s", "600"),
            ]
        )
    _die(f"unsupported molmo-planner-proof mode '{mode}' (expected dry-run|execute-rerun)")


def _parse_overrides(raw_overrides: Sequence[str]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for override in raw_overrides:
        if not override:
            continue
        if "=" not in override:
            _die(f"override '{override}' is not key=value")
        key, value = override.split("=", 1)
        key = key.removeprefix("--").replace("-", "_")
        kv[key] = value
    return kv


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
    raw_overrides: Sequence[str],
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
    for override in raw_overrides:
        if override:
            parts.append(override)
    os.environ["ROBOCLAWS_REPORT_RERUN_COMMAND"] = shlex.join(parts)
