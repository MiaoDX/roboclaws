"""Typed product execution for the household-world launch surface."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import roboclaws.launch.household_execution as household_execution
from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from roboclaws.core.dotenv import update_env_from_dotenv_file
from roboclaws.core.open_ended_artifacts import validate_open_ended_artifacts
from roboclaws.core.provider_catalog import provider_route_spec
from roboclaws.household.cleanup_validation import load_run_results, validate_run_result
from roboclaws.household.household_mcp_smoke import run_smoke
from roboclaws.household.household_runtime_contract import CAMERA_MODEL_POLICY_NAME
from roboclaws.household.household_world_episode import run_household_world_episode
from roboclaws.household.nav2_map_bundle import selected_nav2_map_bundle_dir
from roboclaws.household.visual_grounding_sidecar.process import ManagedVisualGroundingProcess
from roboclaws.launch.plans import LaunchPlan
from roboclaws.launch.runners import _die, _exec_or_trace, _get
from roboclaws.maps.runtime_prior_conversion import (
    runtime_prior_snapshot_from_nav2_cleanup_bundle,
)
from roboclaws.maps.runtime_prior_materialization import materialize_runtime_prior_targets
from roboclaws.worlds.molmospaces.map_bundles import molmospaces_nav2_map_bundle_path

_REPO_PYTHON = ".venv/bin/python"
_B1_RUN_ARTIFACTS = (
    "b1_robot_consumption_manifest.json",
    "runtime_map_prior_snapshot.json",
    "runtime_map_prior_targets.json",
)


def execute_household_plan(
    *,
    plan: LaunchPlan,
    kv: dict[str, str],
) -> int:
    os.environ["ROBOCLAWS_LAUNCH_WORLD_ID"] = plan.world
    execution = household_execution.resolve_household_execution(plan, kv=kv)
    if plan.dispatch_runner == "openai-agents-live" and len(execution.seeds) != 1:
        _die("live agent drivers accept exactly one seed per interactive run")
    if plan.dispatch_runner not in {"direct", "mcp-smoke", "openai-agents-live"}:
        _die(f"unsupported household-world driver {plan.dispatch_runner!r}")

    map_bundle = _resolve_map_bundle(execution, validate=not _trace_enabled())
    run_root = _run_root(execution)
    if _trace_enabled():
        run_dir = _run_dir(execution, run_root=run_root, seed=execution.seeds[0])
        return _exec_or_trace(_run_command(execution, run_dir=run_dir, map_bundle=map_bundle))

    run_root.mkdir(parents=True, exist_ok=True)
    if _is_b1(execution):
        map_bundle = _prepare_b1_map(execution, source_bundle=map_bundle)

    sidecar = _sidecar_for(execution)
    try:
        if plan.dispatch_runner == "openai-agents-live":
            return _run_live(execution, run_root=run_root, map_bundle=map_bundle, sidecar=sidecar)
        for seed in execution.seeds:
            status = _run_seed(
                execution,
                seed=seed,
                run_root=run_root,
                map_bundle=map_bundle,
                sidecar=sidecar,
            )
            if status:
                return status
        return _validate_runs(execution, run_root=run_root)
    finally:
        if sidecar is not None:
            sidecar.close()


def _run_seed(
    execution: household_execution.HouseholdExecution,
    *,
    seed: str,
    run_root: Path,
    map_bundle: Path,
    sidecar: ManagedVisualGroundingProcess | None,
) -> int:
    run_dir = _run_dir(execution, run_root=run_root, seed=seed)
    run_dir.mkdir(parents=True, exist_ok=True)
    if sidecar is not None:
        sidecar.ensure_ready(run_dir)
    _copy_b1_artifacts(execution, run_dir)
    if _requires_process_boundary(execution):
        return _run_subprocess(_run_command(execution, run_dir=run_dir, map_bundle=map_bundle))
    return _run_deterministic(
        execution,
        seed=int(seed),
        run_dir=run_dir,
        map_bundle=map_bundle,
    )


def _run_command(
    execution: household_execution.HouseholdExecution,
    *,
    run_dir: Path,
    map_bundle: Path,
) -> list[str]:
    if execution.plan.dispatch_runner == "openai-agents-live":
        return _live_command(execution, run_dir=run_dir, map_bundle=map_bundle)
    module = (
        "roboclaws.household.household_mcp_smoke"
        if execution.plan.dispatch_runner == "mcp-smoke"
        else "roboclaws.household.household_world_episode"
    )
    command = [_REPO_PYTHON, "-m", module]
    seed = run_dir.name.removeprefix("seed-")
    command.extend(
        [
            "--seed",
            seed,
            "--backend",
            execution.backend,
            "--task",
            execution.task,
            "--perception-mode",
            execution.perception_mode,
            "--map-bundle-dir",
            str(map_bundle),
            "--generated-mess-count",
            str(execution.generated_mess_count),
            "--goal-contract-json",
            execution.plan.goal_contract.to_json(),
            "--output-dir",
            str(run_dir),
        ]
    )
    if execution.profile != "smoke":
        command.extend(["--evidence-lane", execution.evidence_lane])
    if module.endswith("household_world_episode"):
        command.extend(
            [
                "--scene-source",
                _get(execution.kv, "scene_source", "procthor-10k-val"),
                "--scene-index",
                _get(execution.kv, "scene_index", "0"),
                "--static-fixture-projection-mode",
                "room_only",
                "--intent",
                execution.plan.intent,
            ]
        )
    else:
        command.extend(["--policy", "household_contract_smoke_agent"])
    command.extend(household_execution.common_run_args(execution))
    return command


def _run_deterministic(
    execution: household_execution.HouseholdExecution,
    *,
    seed: int,
    run_dir: Path,
    map_bundle: Path,
) -> int:
    common = {
        "output_dir": run_dir,
        "seed": seed,
        "backend": execution.backend,
        "generated_mess_count": execution.generated_mess_count,
        "generated_mess_object_ids": household_execution.comma_values(
            _get(execution.kv, "generated_mess_object_ids", "")
        ),
        "map_bundle_dir": map_bundle,
        "perception_mode": execution.perception_mode,
        "include_robot": execution.profile != "smoke",
        "robot_name": "rby1m",
        "record_robot_views": household_execution.record_robot_views(execution),
        "evidence_lane": None if execution.profile == "smoke" else execution.evidence_lane,
        "runtime_map_prior_path": household_execution.optional_path(
            execution.kv, "runtime_map_prior"
        ),
        "visual_grounding": execution.visual_grounding,
        "visual_grounding_timeout_s": execution.visual_grounding_timeout_s,
        "goal_contract_json": execution.plan.goal_contract.to_json(),
        "goal_contract_path": household_execution.optional_path(execution.kv, "goal_contract_path"),
    }
    if execution.plan.dispatch_runner == "mcp-smoke":
        result = run_smoke(
            task=execution.task,
            policy="household_contract_smoke_agent",
            **common,
        )
    else:
        result = run_household_world_episode(
            task_prompt=execution.task,
            static_fixture_projection_mode="room_only",
            scene_source=_get(execution.kv, "scene_source", "procthor-10k-val"),
            scene_index=int(_get(execution.kv, "scene_index", "0")),
            isaac_scene_usd_path=household_execution.optional_path(
                execution.kv, "isaac_scene_usd_path"
            ),
            intent=execution.plan.intent,
            **common,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _live_command(
    execution: household_execution.HouseholdExecution,
    *,
    run_dir: Path,
    map_bundle: Path,
) -> list[str]:
    update_env_from_dotenv_file(Path(".env"))
    provider = execution.plan.provider_profile or ""
    route = provider_route_spec(provider)
    model = _get(execution.kv, "model", os.environ.get("ROBOCLAWS_OPENAI_AGENTS_MODEL", ""))
    if not model and not route.request_model_env:
        model = route.default_model_id
    prompt_count = (
        (execution.generated_mess_count * 7 + 9) // 10
        if execution.profile == "camera-raw-fpv"
        else execution.generated_mess_count
    )
    composite = _env_true("ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS")
    max_observe = int(
        os.environ.get(
            "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT",
            "4" if execution.profile == "camera-raw-fpv" else "1",
        )
    )
    if execution.map_build:
        kickoff = render_map_build_prompt(
            execution.profile,
            execution.task,
            camera_grounded_composite_tools=composite,
            max_observe_per_waypoint=max_observe,
            operator_session_context_json=_get(execution.kv, "operator_session_context_json", ""),
        )
    else:
        kickoff = render_kickoff_prompt(
            execution.profile,
            task=execution.task,
            target_cleanup_count=prompt_count,
            intent=execution.plan.intent,
            goal_contract=execution.plan.goal_contract,
            raw_fpv_candidate_budget=int(
                os.environ.get("ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET", "24")
            ),
            max_observe_per_waypoint=max_observe,
            done_retry_budget=int(os.environ.get("ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET", "1")),
            camera_grounded_composite_tools=composite,
            operator_session_context_json=_get(execution.kv, "operator_session_context_json", ""),
        )
    host = _get(execution.kv, "host", "127.0.0.1")
    port = _get(
        execution.kv,
        "port",
        os.environ.get("ROBOCLAWS_EVAL_HARNESS_MCP_PORT", "18788"),
    )
    timeout = os.environ.get("ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S") or (
        "120" if execution.backend == "isaaclab_subprocess" else "30"
    )
    lock_backend = "".join(
        character if character.isalnum() or character in "_.-" else "-"
        for character in execution.backend
    )
    command = [
        _REPO_PYTHON,
        "-m",
        "roboclaws.agents.household_live_runner",
        "--repo-root",
        os.getcwd(),
        "--run-dir",
        str(run_dir),
        "--status-path",
        str(run_dir / "live_status.json"),
        "--client-url",
        f"http://{host}:{port}/mcp",
        "--host",
        host,
        "--port",
        port,
        "--lock-path",
        f"output/molmo/live-locks/{lock_backend}.openai-agents.lock",
        "--provider-profile",
        provider,
        "--model",
        model,
        "--mcp-client-session-timeout-s",
        timeout,
        "--agent-sdk-perf-profile",
        os.environ.get("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", ""),
        "--continuation-mode",
        os.environ.get("ROBOCLAWS_OPENAI_AGENTS_CONTINUATION_MODE", ""),
        "--model-thinking-mode",
        os.environ.get("ROBOCLAWS_OPENAI_AGENTS_THINKING_MODE", "default"),
        "--server-startup-timeout-s",
        os.environ.get("ROBOCLAWS_MOLMO_LIVE_SERVER_STARTUP_TIMEOUT_S", "600"),
        "--kickoff-prompt",
        kickoff,
        "--backend",
        execution.backend,
        "--task-surface",
        execution.plan.surface,
        "--intent",
        execution.plan.intent,
        "--skill-name",
        execution.plan.skill_name,
        "--policy",
        "openai_agents_agent",
        "--task",
        execution.task,
        "--min-generated-mess-count",
        str(execution.min_generated_mess_count),
        "--profile",
        execution.profile,
        "--checker-profile",
        execution.evidence_lane,
    ]
    for flag in execution.checker_flags:
        command.append(f"--checker-visual-arg={flag}")
    for argument in _server_args(
        execution, run_dir=run_dir, map_bundle=map_bundle, host=host, port=port
    ):
        command.append(f"--server-arg={argument}")
    _append_live_env_options(command)
    operator_resume = _get(execution.kv, "operator_resume_requests_path", "")
    if operator_resume:
        command.extend(["--operator-resume-requests-path", operator_resume])
    return command


def _server_args(
    execution: household_execution.HouseholdExecution,
    *,
    run_dir: Path,
    map_bundle: Path,
    host: str,
    port: str,
) -> list[str]:
    args = [
        "--host",
        host,
        "--port",
        port,
        "--output-dir",
        str(run_dir),
        "--seed",
        execution.seeds[0],
        "--policy",
        "openai_agents_agent",
        "--intent",
        execution.plan.intent,
        "--backend",
        execution.backend,
        "--task",
        execution.task,
        "--generated-mess-count",
        str(execution.generated_mess_count),
        "--perception-mode",
        execution.perception_mode,
        "--scene-source",
        _get(execution.kv, "scene_source", "procthor-10k-val"),
        "--scene-index",
        _get(execution.kv, "scene_index", "0"),
        "--map-bundle-dir",
        str(map_bundle),
        "--goal-contract-json",
        execution.plan.goal_contract.to_json(),
    ]
    if execution.profile != "smoke":
        args.extend(["--evidence-lane", execution.evidence_lane])
    args.extend(household_execution.common_run_args(execution))
    operator_messages = _get(execution.kv, "operator_messages_path", "")
    if operator_messages:
        args.extend(["--operator-messages-path", operator_messages])
    return args


def _validate_runs(
    execution: household_execution.HouseholdExecution,
    *,
    run_root: Path,
) -> int:
    if execution.open_ended:
        checked = validate_open_ended_artifacts(run_root)
        for run_dir in checked:
            print(f"open-ended artifacts ok: {run_dir}")
        return 0

    run_results = load_run_results(run_root)
    expected_seeds = {int(seed) for seed in execution.seeds}
    actual_seeds = {int(data["seed"]) for data, _path in run_results}
    assert expected_seeds <= actual_seeds, (expected_seeds, actual_seeds)
    assert run_results, run_root
    policy = _expected_validation_policy(execution)
    for data, path in run_results:
        validate_run_result(
            data,
            path.parent,
            expect_task=execution.task,
            expect_backend=execution.backend,
            expect_policy=policy,
            expect_profile=None if execution.profile == "smoke" else execution.profile,
            expect_mcp_server=(
                "household_world" if execution.plan.dispatch_runner == "mcp-smoke" else None
            ),
            min_generated_mess_count=execution.min_generated_mess_count,
            require_agent_driven=execution.plan.dispatch_runner == "mcp-smoke",
            require_clean_agent_run=execution.plan.dispatch_runner == "mcp-smoke",
            **execution.validation_options,
        )
    print(f"household-world ok: {run_root} ({len(run_results)} run(s))")
    return 0


def _expected_validation_policy(execution: household_execution.HouseholdExecution) -> str:
    if execution.plan.dispatch_runner == "mcp-smoke":
        return "household_contract_smoke_agent"
    if execution.validation_options.get("require_map_build"):
        return "map_build_baseline"
    if execution.validation_options.get("require_camera_model_policy"):
        return CAMERA_MODEL_POLICY_NAME
    return "deterministic_sweep_baseline"


def _resolve_map_bundle(
    execution: household_execution.HouseholdExecution,
    *,
    validate: bool,
) -> Path:
    raw = _get(execution.kv, "map_bundle", "auto")
    if raw == "auto":
        raw = str(
            molmospaces_nav2_map_bundle_path(
                scene_source=_get(execution.kv, "scene_source", "procthor-10k-val"),
                scene_index=int(_get(execution.kv, "scene_index", "0")),
            )
        )
    if raw.lower() in {"none", "false", "off"}:
        _die(f"{execution.plan.surface}/{execution.plan.intent} requires a Base Metric Map")
    if not validate:
        return Path(raw)
    if _is_b1(execution):
        path = Path(raw)
        if not path.is_dir():
            _die(f"world=b1-map12 received invalid map_bundle {raw!r}")
        return path
    try:
        selected = selected_nav2_map_bundle_dir(raw, required=True)
    except ValueError as exc:
        _die(str(exc))
    assert selected is not None
    return selected


def _prepare_b1_map(
    execution: household_execution.HouseholdExecution,
    *,
    source_bundle: Path,
) -> Path:
    required = {
        "isaac_scene_usd_path": Path(_get(execution.kv, "isaac_scene_usd_path", "")),
        "b1_alignment_artifact": Path(_get(execution.kv, "b1_alignment_artifact", "")),
        "b1_navigation_artifact": Path(_get(execution.kv, "b1_navigation_artifact", "")),
    }
    missing = [name for name, path in required.items() if not str(path) or not path.is_file()]
    if missing:
        _die("world=b1-map12 requires valid " + ", ".join(missing))
    from roboclaws.backends.isaaclab.b1_base_metric_augmentation import (
        augment_base_metric_map_bundle,
    )
    from roboclaws.maps.b1_base_metric_map import build_base_metric_map_bundle

    base = execution.output_dir / "b1-map12-base-metric-map"
    augmented = execution.output_dir / "b1-map12-base-metric-map-with-proof"
    build_base_metric_map_bundle(map_bundle=source_bundle, output_dir=base)
    augment_base_metric_map_bundle(
        base_map_bundle=base,
        alignment_artifact_path=required["b1_alignment_artifact"],
        navigation_artifact_path=required["b1_navigation_artifact"],
        output_dir=augmented,
    )
    execution.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        augmented / "b1_robot_consumption_manifest.json",
        execution.output_dir / "b1_robot_consumption_manifest.json",
    )
    snapshot = runtime_prior_snapshot_from_nav2_cleanup_bundle(augmented)
    _write_json(execution.output_dir / "runtime_map_prior_snapshot.json", snapshot)
    _write_json(
        execution.output_dir / "runtime_map_prior_targets.json",
        materialize_runtime_prior_targets(snapshot),
    )
    return augmented


def _copy_b1_artifacts(
    execution: household_execution.HouseholdExecution,
    run_dir: Path,
) -> None:
    if not _is_b1(execution):
        return
    for name in _B1_RUN_ARTIFACTS:
        source = execution.output_dir / name
        if not source.is_file():
            _die(f"required B1 run artifact is missing: {source}")
        shutil.copy2(source, run_dir / name)


def _run_live(
    execution: household_execution.HouseholdExecution,
    *,
    run_root: Path,
    map_bundle: Path,
    sidecar: ManagedVisualGroundingProcess | None,
) -> int:
    run_dir = _run_dir(execution, run_root=run_root, seed=execution.seeds[0])
    run_dir.mkdir(parents=True, exist_ok=True)
    if sidecar is not None:
        sidecar.ensure_ready(run_dir)
    _copy_b1_artifacts(execution, run_dir)
    return _run_subprocess(_live_command(execution, run_dir=run_dir, map_bundle=map_bundle))


def _sidecar_for(
    execution: household_execution.HouseholdExecution,
) -> ManagedVisualGroundingProcess | None:
    if execution.profile != "camera-grounded-labels" or execution.visual_grounding == "sim":
        return None
    return ManagedVisualGroundingProcess(
        pipeline_id=execution.visual_grounding,
        timeout_s=execution.visual_grounding_timeout_s,
    )


def _run_root(execution: household_execution.HouseholdExecution) -> Path:
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m%d_%H%M")
    return execution.output_dir / stamp


def _run_dir(
    execution: household_execution.HouseholdExecution,
    *,
    run_root: Path,
    seed: str,
) -> Path:
    override = _get(execution.kv, "run_dir", "")
    if override and execution.plan.dispatch_runner == "openai-agents-live":
        return Path(override)
    return run_root / f"seed-{seed}"


def _run_subprocess(command: list[str]) -> int:
    return subprocess.run(command, check=False, env=os.environ.copy()).returncode


def _requires_process_boundary(execution: household_execution.HouseholdExecution) -> bool:
    return _is_b1(execution) or Path(_REPO_PYTHON).resolve() != Path(sys.executable).resolve()


def _trace_enabled() -> bool:
    return os.environ.get("ROBOCLAWS_JUST_TRACE") == "1"


def _is_b1(execution: household_execution.HouseholdExecution) -> bool:
    return household_execution.is_b1_plan(execution.plan, execution.backend)


def _append_live_env_options(command: list[str]) -> None:
    value_options = dict(
        ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS="--max-turns",
        ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS=(
            "--incomplete-turn-continuation-attempts"
        ),
        ROBOCLAWS_OPENAI_AGENTS_CONTEXT_SOFT_LIMIT_TOKENS="--context-soft-limit-tokens",
        ROBOCLAWS_OPENAI_AGENTS_CONTEXT_HARD_LIMIT_TOKENS="--context-hard-limit-tokens",
        ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING_ARM_COUNT="--model-racing-arm-count",
        ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT="--max-observe-per-waypoint",
        ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET="--raw-fpv-candidate-budget",
        ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_REPEATED_FAILURE_LIMIT=("--raw-fpv-repeated-failure-limit"),
        ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY="--robot-view-capture-policy",
        ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY_RETAIN="--raw-fpv-image-memory-retain",
        ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_RETAIN=("--camera-grounded-history-retain"),
        ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET="--done-retry-budget",
    )
    for env_name, flag in value_options.items():
        if value := os.environ.get(env_name):
            command.extend([flag, value])
    bool_options = dict(
        ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING="--model-racing",
        ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY="--raw-fpv-image-memory",
        ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_COMPACTION=(
            "--camera-grounded-history-compaction"
        ),
        ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST="--cache-tools-list",
    )
    for env_name, flag in bool_options.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            command.append(flag if _bool_value(raw) else "--no-" + flag.removeprefix("--"))


def _env_true(name: str) -> bool:
    raw = os.environ.get(name)
    return _bool_value(raw) if raw is not None else False


def _bool_value(raw: str) -> bool:
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
