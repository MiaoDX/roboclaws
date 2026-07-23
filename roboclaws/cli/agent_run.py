"""agent::run dispatch for the maintainer Just facade."""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence

from roboclaws.cli.agent_common import (
    _append_optional,
    _die,
    _exec_or_trace,
    _get,
    _strip_prefixes,
)
from roboclaws.cli.agent_constants import AGENT_RUN_KEYS

HOUSEHOLD_DISPATCH_TARGET = "household-world"
HOUSEHOLD_PROFILES = {
    "smoke",
    "world-public-labels",
    "camera-raw-fpv",
    "camera-grounded-labels",
}


def agent_run(args: Sequence[str]) -> int:
    if len(args) < 2:
        _die("agent run requires dispatch_target and agent_engine")

    dispatch_target = _strip_prefixes(args[0], "dispatch_target=", "task=")
    agent_engine = _strip_prefixes(args[1], "agent_engine=", "driver=")
    mode = args[2] if len(args) > 2 else ""
    raw_overrides = list(args[3:])

    dispatch_surface, dispatch_intent = _dispatch_parts(dispatch_target, raw_overrides)
    driver = _driver_for(agent_engine, mode, dispatch_intent)
    mode, raw_overrides = _normalize_mode(mode, raw_overrides)
    kv = _parse_overrides(raw_overrides)

    if dispatch_surface == "household-world":
        profile = mode or _get(kv, "profile", _get(kv, "evidence_lane", "world-public-labels"))
        if profile not in HOUSEHOLD_PROFILES:
            _die(
                f"unsupported household-world evidence_lane '{profile}' "
                "(expected smoke|world-public-labels|camera-grounded-labels|camera-raw-fpv)"
            )
    else:
        report = mode or "visual"
        if report not in {"visual", "minimal"}:
            _die(f"unsupported report '{report}' (expected visual|minimal)")

    if dispatch_surface == "household-world":
        return _household_run(
            dispatch_surface=dispatch_surface,
            dispatch_intent=dispatch_intent,
            agent_engine=agent_engine,
            driver=driver,
            profile=profile,
            raw_overrides=raw_overrides,
            kv=kv,
        )
    return _planner_proof_run(
        dispatch_surface=dispatch_surface,
        dispatch_intent=dispatch_intent,
        driver=driver,
        kv=kv,
    )


def _household_run(
    *,
    dispatch_surface: str,
    dispatch_intent: str,
    agent_engine: str,
    driver: str,
    profile: str,
    raw_overrides: list[str],
    kv: dict[str, str],
) -> int:
    _validate_household_route(dispatch_surface, dispatch_intent, driver)
    backend = _get(kv, "backend", "auto")
    world_id = _get(kv, "world", "")
    _validate_household_backend(dispatch_intent, agent_engine, driver, backend, world_id)

    seeds = _get(kv, "seeds", _get(kv, "seed", "7"))
    output_dir = _get(
        kv,
        "output_dir",
        f"output/household/{dispatch_surface}/{dispatch_intent}/{driver}-{profile}",
    )
    prompt = _prompt_for(dispatch_intent, kv)
    resolved_task_intent = _resolved_task_intent(dispatch_intent, kv)
    camera_labeler, visual_grounding_timeout_s = _profile_options(profile, kv)

    if backend == "agibot_molmospaces_sim":
        return _agibot_sim_run(
            dispatch_intent=dispatch_intent,
            driver=driver,
            profile=profile,
            seeds=seeds,
            output_dir=output_dir,
            prompt=prompt,
            generated_mess_count=_get(kv, "generated_mess_count", "10"),
            robot_views=_get(kv, "robot_views", _get(kv, "record_robot_views", "auto")),
            camera_labeler=camera_labeler,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            resolved_task_intent=resolved_task_intent,
            kv=kv,
        )
    if backend == "agibot_gdk":
        return _agibot_gdk_run(
            dispatch_intent=dispatch_intent,
            agent_engine=agent_engine,
            driver=driver,
            profile=profile,
            seeds=seeds,
            output_dir=output_dir,
            prompt=prompt,
            host=_get(kv, "host", "127.0.0.1"),
            port=_get(kv, "port", os.environ.get("ROBOCLAWS_EVAL_HARNESS_MCP_PORT", "18788")),
            camera_labeler=camera_labeler,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            resolved_task_intent=resolved_task_intent,
            backend=backend,
            kv=kv,
        )
    return _molmo_household_run(
        dispatch_surface=dispatch_surface,
        dispatch_intent=dispatch_intent,
        driver=driver,
        profile=profile,
        raw_overrides=raw_overrides,
        kv=kv,
        seeds=seeds,
        output_dir=output_dir,
        prompt=prompt,
        backend=backend,
        world_id=world_id,
        camera_labeler=camera_labeler,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        resolved_task_intent=resolved_task_intent,
    )


def _validate_household_route(dispatch_surface: str, dispatch_intent: str, driver: str) -> None:
    allowed = {
        ("map-build", "direct"),
        ("map-build", "openai-agents-live"),
        ("cleanup", "direct"),
        ("cleanup", "mcp-smoke"),
        ("cleanup", "openclaw-smoke"),
        ("cleanup", "openai-agents-live"),
        ("cleanup", "openclaw"),
        ("open-ended", "direct"),
        ("open-ended", "mcp-smoke"),
        ("open-ended", "openclaw-smoke"),
        ("open-ended", "openai-agents-live"),
        ("open-ended", "openclaw"),
    }
    if (dispatch_intent, driver) not in allowed:
        _die(
            "unsupported surface/intent/driver route "
            f"'{dispatch_surface}.{dispatch_intent}:{driver}'"
        )
    if dispatch_intent == "map-build" and driver not in {"direct", "openai-agents-live"}:
        _die(
            "surface=household-world task_intent=map-build currently supports "
            "direct-runner or openai-agents-sdk only"
        )


def _validate_household_backend(
    dispatch_intent: str,
    agent_engine: str,
    driver: str,
    backend: str,
    world_id: str,
) -> None:
    if dispatch_intent == "map-build":
        allowed_backends = {"auto", "molmospaces_subprocess", "isaaclab_subprocess", "agibot_gdk"}
        if backend == "agibot_molmospaces_sim":
            if driver != "direct":
                _die("backend=agibot_molmospaces_sim currently supports direct driver only")
        elif backend not in allowed_backends:
            _die(
                f"surface=household-world task_intent=map-build {agent_engine} "
                f"unsupported backend '{backend}' "
                "(expected auto|molmospaces_subprocess|isaaclab_subprocess|agibot_gdk)"
            )
    if backend == "isaaclab_subprocess" and world_id != "b1-map12":
        _die(
            "backend=isaaclab_subprocess is scoped to world=b1-map12; "
            "MolmoSpaces household routes use backend=molmospaces_subprocess"
        )


def _resolved_task_intent(dispatch_intent: str, kv: dict[str, str]) -> str:
    task_intent = _get(kv, "task_intent", os.environ.get("ROBOCLAWS_TASK_INTENT", ""))
    return task_intent or dispatch_intent


def _skill_name(dispatch_intent: str, resolved_task_intent: str, kv: dict[str, str]) -> str:
    skill_name = _get(kv, "skill_name", os.environ.get("ROBOCLAWS_TASK_SKILL", ""))
    if skill_name:
        return skill_name
    return HOUSEHOLD_DISPATCH_TARGET


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
        _get(kv, "visual_grounding_timeout", "auto"),
    )
    if profile != "camera-grounded-labels":
        if camera_labeler:
            _die("camera_labeler is only valid for evidence_lane=camera-grounded-labels")
        return "", visual_grounding_timeout_s
    if not camera_labeler:
        _die("evidence_lane=camera-grounded-labels requires camera_labeler")
    if camera_labeler not in {"grounding-dino", "yoloe", "omdet-turbo", "yolo-world"}:
        _die(f"unsupported camera_labeler '{camera_labeler}'")
    return camera_labeler, visual_grounding_timeout_s


def _molmo_household_run(
    *,
    dispatch_surface: str,
    dispatch_intent: str,
    driver: str,
    profile: str,
    raw_overrides: list[str],
    kv: dict[str, str],
    seeds: str,
    output_dir: str,
    prompt: str,
    backend: str,
    world_id: str,
    camera_labeler: str,
    visual_grounding_timeout_s: str,
    resolved_task_intent: str,
) -> int:
    impl_driver = {"openclaw": "openclaw-live"}.get(driver, driver)
    generated_mess_count = _get(kv, "generated_mess_count", "10")
    host = _get(kv, "host", "127.0.0.1")
    port = _get(kv, "port", os.environ.get("ROBOCLAWS_EVAL_HARNESS_MCP_PORT", "18788"))
    map_bundle = _get(kv, "map_bundle", "auto")
    b1_alignment_artifact = _get(kv, "b1_alignment_artifact", "")
    b1_navigation_artifact = _get(kv, "b1_navigation_artifact", "")
    cleanup_routine = _get(kv, "cleanup_routine", "skill")
    if cleanup_routine not in {"auto", "skill"}:
        _die(f"unsupported cleanup_routine '{cleanup_routine}' (expected auto|skill)")
    robot_views = _get(kv, "robot_views", _get(kv, "record_robot_views", "auto"))
    map_build = _get(kv, "map_build", "off")
    if dispatch_intent == "map-build":
        map_build = "on"
    runtime_map_prior = _get(kv, "runtime_map_prior", "")
    operator_messages_path = _get(kv, "operator_messages_path", "")
    min_generated_mess_count = _get(kv, "min_generated_mess_count", "auto")
    generated_mess_object_ids = _get(kv, "generated_mess_object_ids", "")
    scene_source = _get(kv, "scene_source", "procthor-10k-val")
    scene_index = _get(kv, "scene_index", "0")
    isaac_scene_usd_path = _get(kv, "isaac_scene_usd_path", "")

    molmo_args = [
        impl_driver,
        profile,
        seeds,
        output_dir,
        prompt,
        generated_mess_count,
        host,
        port,
        map_bundle,
        cleanup_routine,
        robot_views,
        camera_labeler,
        visual_grounding_timeout_s,
        map_build,
        runtime_map_prior,
        backend,
        scene_source,
        scene_index,
        isaac_scene_usd_path,
        min_generated_mess_count,
        generated_mess_object_ids,
        dispatch_surface,
        resolved_task_intent,
        operator_messages_path,
        b1_alignment_artifact,
        b1_navigation_artifact,
    ]
    run_dir_override = _get(kv, "run_dir", "")
    if run_dir_override:
        molmo_args.extend(["", "", "", run_dir_override])

    skill_name = _skill_name(dispatch_intent, resolved_task_intent, kv)
    env = {
        "ROBOCLAWS_GOAL_CONTRACT_JSON": _get(
            kv,
            "goal_contract_json",
            os.environ.get("ROBOCLAWS_GOAL_CONTRACT_JSON", ""),
        ),
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
        "ROBOCLAWS_LAUNCH_WORLD_ID": world_id,
        "ROBOCLAWS_MOLMO_RUN_DIR_OVERRIDE": run_dir_override,
        "ROBOCLAWS_TASK_INTENT": resolved_task_intent,
        "ROBOCLAWS_TASK_PRESET": kv.get("task_preset", ""),
        "ROBOCLAWS_TASK_SKILL": skill_name,
        "ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES": _get(
            kv,
            "required_capability_profiles",
            os.environ.get("ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES", ""),
        ),
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
        dispatch_surface=dispatch_surface,
        dispatch_intent=dispatch_intent,
        driver=driver,
        profile=profile,
        raw_overrides=raw_overrides,
        kv=kv,
    )
    return _exec_or_trace(["just", "molmo::household-world-impl", *molmo_args], env=env)


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
        "scripts/molmo_cleanup/run_live_openai_agents_agibot_map_build.py",
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
        "--provider-profile",
        _get(
            kv,
            "provider_profile",
            os.environ.get("ROBOCLAWS_PROVIDER_PROFILE", "codex-router-responses"),
        ),
        "--model",
        _get(
            kv,
            "model",
            os.environ.get(
                "ROBOCLAWS_OPENAI_AGENTS_MODEL",
                os.environ.get("ROBOCLAWS_CODEX_MODEL", ""),
            ),
        ),
        "--server-startup-timeout-s",
        os.environ.get("ROBOCLAWS_AGIBOT_MAP_BUILD_LIVE_SERVER_STARTUP_TIMEOUT_S", "600"),
        "--kickoff-prompt",
        prompt,
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
        server_args.extend(["--camera-labeler", camera_labeler])
    if visual_grounding_timeout_s not in {"", "auto"}:
        server_args.extend(["--visual-grounding-timeout-s", visual_grounding_timeout_s])
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
    dispatch_surface: str,
    dispatch_intent: str,
    driver: str,
    kv: dict[str, str],
) -> int:
    if (dispatch_surface, dispatch_intent, driver) not in {
        ("planner-proof", "planner-proof", "direct"),
        ("planner-proof", "planner-proof", "mcp-smoke"),
    }:
        _die(
            "unsupported surface/intent/driver route "
            f"'{dispatch_surface}.{dispatch_intent}:{driver}'"
        )
    mode = _get(kv, "mode", "dry-run").replace("_", "-")
    output_dir = _get(kv, "output_dir", "")
    seed = _get(kv, "seed", "7")
    prompt = _prompt_for("cleanup", kv)
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


def _dispatch_parts(dispatch_target: str, raw_overrides: list[str]) -> tuple[str, str]:
    if dispatch_target == HOUSEHOLD_DISPATCH_TARGET:
        task_intent = ""
        for override in raw_overrides:
            if override.startswith(("task_intent=", "--task-intent=", "--task_intent=")):
                task_intent = override.split("=", 1)[1]
                break
        task_intent = task_intent or os.environ.get("ROBOCLAWS_TASK_INTENT", "") or "cleanup"
        return HOUSEHOLD_DISPATCH_TARGET, task_intent
    if dispatch_target == "planner-proof.planner-proof":
        return "planner-proof", "planner-proof"
    if dispatch_target.startswith("household-world."):
        _die(
            f"unsupported household dispatch target '{dispatch_target}'; "
            "use dispatch_target=household-world with task_intent=cleanup|map-build|open-ended"
        )
    if "." in dispatch_target:
        return tuple(dispatch_target.split(".", 1))  # type: ignore[return-value]
    return dispatch_target, dispatch_target


def _driver_for(agent_engine: str, mode: str, dispatch_intent: str) -> str:
    if agent_engine in {"codex-cli", "claude-code"}:
        _die(f"unsupported agent_engine '{agent_engine}'; expected direct-runner|openai-agents-sdk")
    if agent_engine == "openai-agents-sdk":
        return "openai-agents-live"
    if agent_engine == "direct-runner":
        if mode == "smoke" and dispatch_intent in {"cleanup", "open-ended"}:
            return "mcp-smoke"
        return "direct"
    if agent_engine == "openclaw-gateway":
        return "openclaw"
    return agent_engine


def _normalize_mode(mode: str, raw_overrides: list[str]) -> tuple[str, list[str]]:
    for prefix in ("report=", "profile=", "evidence_lane="):
        if mode.startswith(prefix):
            return mode.removeprefix(prefix), raw_overrides
    if "=" in mode:
        return "", [mode, *raw_overrides]
    return mode, raw_overrides


def _parse_overrides(raw_overrides: Sequence[str]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for override in raw_overrides:
        if not override:
            continue
        if "=" not in override:
            _die(f"override '{override}' is not key=value")
        key, value = override.split("=", 1)
        key = key.removeprefix("--").replace("-", "_")
        if key not in AGENT_RUN_KEYS:
            _die(f"unsupported override key '{key}'")
        kv[key] = value
    return kv


def _prompt_for(dispatch_intent: str, kv: dict[str, str]) -> str:
    default = (
        "帮我建立这个房间的 Runtime Metric Map"
        if dispatch_intent == "map-build"
        else "帮我收拾这个房间"
    )
    return _get(kv, "prompt", _get(kv, "task", default))


def _export_rerun_command(
    *,
    dispatch_surface: str,
    dispatch_intent: str,
    driver: str,
    profile: str,
    raw_overrides: Sequence[str],
    kv: dict[str, str],
) -> None:
    parts = ["just", "run::surface"]
    if dispatch_intent == "map-build":
        parts.extend(["surface=household-world", "preset=map-build"])
    elif dispatch_surface == "household-world":
        task_preset = kv.get("task_preset", "")
        task_intent = kv.get("task_intent", "cleanup")
        if task_preset == "cleanup":
            parts.extend(["surface=household-world", "preset=cleanup"])
        elif task_intent == "open-ended":
            parts.append("surface=household-world")
        else:
            parts.extend(["surface=household-world", f"preset={task_intent}"])
    elif dispatch_surface == "planner-proof":
        parts.extend(["surface=planner-proof", "intent=planner-proof"])
    parts.append(
        {
            "openai-agents-live": "agent_engine=openai-agents-sdk",
            "direct": "agent_engine=direct-runner",
            "mcp-smoke": "agent_engine=direct-runner",
            "openclaw": "agent_engine=openclaw-gateway",
        }.get(driver, f"agent_engine={driver}")
    )
    if dispatch_surface == "household-world":
        if profile == "smoke":
            parts.extend(["run_preset=smoke", "evidence_lane=world-public-labels"])
        else:
            parts.append(f"evidence_lane={profile}")
    for override in raw_overrides:
        if override:
            parts.append(override)
    os.environ["ROBOCLAWS_REPORT_RERUN_COMMAND"] = shlex.join(parts)
