#!/usr/bin/env python3
"""Expose the ADR-0003 Molmo real-world cleanup contract to external agents."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from roboclaws.household.agibot_household_backend import (
    AgibotHouseholdBackend,
)
from roboclaws.household.household_backend_contract import (
    SYNTHETIC_BACKEND,
    build_household_backend_session,
    validate_cleanup_run_options,
)
from roboclaws.household.household_mcp_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MCP_SERVER_NAME,
    ROBOT_VIEW_CAPTURE_POLICIES,
    ROBOT_VIEW_CAPTURE_POLICY_FULL,
    HouseholdWorldMCPServer,
    make_household_world_mcp,
)
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    DEFAULT_REALWORLD_TASK,
    RAW_FPV_ONLY_MODE,
    VISIBLE_OBJECT_DETECTIONS_MODE,
)
from roboclaws.household.isaac_lab_backend import ISAACLAB_SUBPROCESS_BACKEND
from roboclaws.household.nav2_map_bundle import selected_nav2_map_bundle_dir
from roboclaws.household.profiles import evidence_lane_names
from roboclaws.household.scenario import CleanupScenario, build_cleanup_scenario
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND
from roboclaws.household.task_intent import (
    HOUSEHOLD_INTENT_CLEANUP,
    household_intent_from_goal_contract,
    household_intent_is_open_ended,
    normalize_household_intent,
)
from roboclaws.household.visual_grounding import (
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
)
from roboclaws.launch.goals import goal_contract_from_file, goal_contract_from_json
from roboclaws.maps.runtime_prior_snapshot import read_runtime_map_prior_artifact

log = logging.getLogger("household-world-agent-server")
AGIBOT_GDK_BACKEND = "agibot_gdk"


@dataclass(frozen=True)
class _ServerBackendSetup:
    base_contract: Any
    scenario: CleanupScenario
    selected_bundle_dir: Path | None
    runtime_map_prior: dict[str, Any] | None
    agibot_contract: AgibotHouseholdBackend | None
    perception_mode: str
    evidence_lane: str | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expose ADR-0003 Molmo cleanup tools to Codex, Claude Code, or OpenClaw.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--policy", default="codex_agent")
    parser.add_argument("--intent", default=HOUSEHOLD_INTENT_CLEANUP)
    parser.add_argument("--task", default=DEFAULT_REALWORLD_TASK)
    parser.add_argument("--goal-contract", type=Path)
    parser.add_argument("--goal-contract-json")
    parser.add_argument(
        "--required-capability-profile",
        action="append",
        default=[],
        help="Resolved immutable MCP capability profile. Repeat in registration order.",
    )
    parser.add_argument(
        "--backend",
        choices=(
            SYNTHETIC_BACKEND,
            MOLMOSPACES_SUBPROCESS_BACKEND,
            ISAACLAB_SUBPROCESS_BACKEND,
            AGIBOT_GDK_BACKEND,
        ),
        default=SYNTHETIC_BACKEND,
    )
    parser.add_argument(
        "--context-json",
        type=Path,
        help="Agibot map context JSON, required when --backend=agibot_gdk.",
    )
    parser.add_argument("--runner-python", help="Python executable for the Agibot SDK runner.")
    parser.add_argument("--runner-script", type=Path, help="Override Agibot SDK runner path.")
    parser.add_argument("--agibot-map-artifact-dir", type=Path)
    parser.add_argument("--real-movement-enabled", action="store_true")
    parser.add_argument("--generated-mess-count", type=int, default=10)
    parser.add_argument(
        "--generated-mess-object-id",
        action="append",
        help="Private run-control object id to include in the generated mess set. Repeatable.",
    )
    parser.add_argument(
        "--generated-mess-manifest-path",
        type=Path,
        help="Private generated-mess manifest path for run-control placement.",
    )
    parser.add_argument(
        "--map-bundle-dir",
        type=Path,
        help="Prebuilt Nav2 map bundle path, or environment id under assets/maps.",
    )
    parser.add_argument(
        "--perception-mode",
        choices=(VISIBLE_OBJECT_DETECTIONS_MODE, RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE),
        default=VISIBLE_OBJECT_DETECTIONS_MODE,
    )
    parser.add_argument(
        "--evidence-lane",
        choices=evidence_lane_names(),
        help="Public cleanup evidence lane or smoke preset selected by the command facade.",
    )
    parser.add_argument(
        "--runtime-map-prior",
        type=Path,
        help="Prior runtime_metric_map.json snapshot to seed as non-actionable priors.",
    )
    parser.add_argument("--include-robot", action="store_true")
    parser.add_argument("--robot-name", default="rby1m")
    parser.add_argument("--record-robot-views", action="store_true")
    parser.add_argument(
        "--robot-view-capture-policy",
        choices=tuple(sorted(ROBOT_VIEW_CAPTURE_POLICIES)),
        default=ROBOT_VIEW_CAPTURE_POLICY_FULL,
        help=(
            "Report robot-view capture policy. The default captures every eligible "
            "tool; action_timeline keeps before/after and cleanup action views while "
            "skipping report-only observe/scene_objects captures."
        ),
    )
    parser.add_argument("--scene-source", default="procthor-10k-val")
    parser.add_argument("--scene-index", type=int, default=0)
    parser.add_argument(
        "--isaac-scene-usd-path",
        type=Path,
        help="Prepared local USD/USDA scene for backend=isaaclab_subprocess real-mode runs.",
    )
    parser.add_argument("--visual-grounding", default=SIM_VISUAL_GROUNDING_PIPELINE_ID)
    parser.add_argument("--visual-grounding-base-url")
    parser.add_argument("--visual-grounding-timeout-s", type=float)
    parser.add_argument(
        "--rerun-command",
        help="Exact public command that launched this run, shown in report.html.",
    )
    parser.add_argument(
        "--operator-messages-path",
        type=Path,
        help="Operator-console JSONL inbox for active-run steering messages.",
    )
    parser.add_argument(
        "--agent-sdk-camera-grounded-composite-tools",
        action="store_true",
        help=(
            "Private OpenAI Agents SDK Candidate-O shortcut: add an opt-in "
            "observe_camera_grounded_candidates MCP tool for camera-grounded-labels. "
            "Default public MCP/profile tools are unchanged."
        ),
    )
    return parser.parse_args(argv)


def default_output_dir(policy: str) -> Path:
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d%H%M%S")
    return Path("output") / "molmo-realworld-agent-dogfood" / policy / stamp


def mcp_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/mcp"


def client_setup_commands(url: str) -> dict[str, str]:
    port = url.rsplit(":", 1)[-1].split("/", 1)[0]
    return {
        "OpenClaw": (
            "SKILLS_DIR=$PWD/skills/household-world "
            f"ROBOCLAWS_MCP_URL=http://host.docker.internal:{port}/mcp "
            "just chat::run"
        ),
    }


def print_setup(
    output_dir: Path,
    url: str,
    policy: str,
    *,
    backend: str = SYNTHETIC_BACKEND,
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    record_robot_views: bool = False,
    evidence_lane: str | None = None,
    task_intent: str = "",
) -> None:
    commands = client_setup_commands(url)
    print("\nMolmo real-world cleanup MCP server is ready.")
    print(f"MCP URL       : {url}")
    print(f"Artifacts     : {output_dir}")
    print(f"Policy label  : {policy}")
    print("Contract      : realworld_cleanup_v1")
    print(f"MCP server    : {MCP_SERVER_NAME}")
    print(f"Backend       : {backend}")
    print(f"Perception    : {perception_mode}")
    if evidence_lane:
        print(f"Evidence lane : {evidence_lane}")
    print(f"Visual report : {'enabled' if record_robot_views else 'disabled'}")
    print("\nFor OpenClaw, start the Gateway with the same MCP URL, for example:")
    if _is_loopback_url(url):
        print(
            "  Docker note: restart this server with --host 0.0.0.0 for OpenClaw; "
            "the Gateway container cannot reach a host-only 127.0.0.1 bind."
        )
    print(f"  {commands['OpenClaw']}")
    print("\nThen start the agent and use this kickoff:")
    open_ended_task = household_intent_is_open_ended(task_intent)
    if open_ended_task:
        print("  Treat the operator task as the authoritative goal scope.")
        print("  Call roboclaws__metric_map first.")
        print("  Observe only as needed for the open-ended task; stop when the task is satisfied.")
    else:
        print("  Read skills/household-world/SKILL.md.")
        print("  Call roboclaws__metric_map first.")
        print("  Sweep waypoints with roboclaws__navigate_to_waypoint then roboclaws__observe.")
    if perception_mode == RAW_FPV_ONLY_MODE:
        print("  Raw FPV mode returns camera observations, not observed_* detections.")
        print("  Inspect image blocks and call navigate_to_visual_candidate before pick.")
    elif perception_mode == CAMERA_MODEL_POLICY_MODE:
        print("  Observe returns raw FPV evidence first; call declare_visual_candidates.")
        print("  Candidates come from the configured server-side camera labeler.")
        print("  Clean plausible observed_* camera candidates with the semantic cleanup loop.")
    else:
        if open_ended_task:
            print("  Act only on task-relevant observed_* objects.")
        else:
            print(
                "  Clean plausible observed_* objects with navigate->pick->navigate->open?->place."
            )
    print("  The server rejects skipped semantic phases; follow required_tool if returned.")
    print("  Do not call scene_objects or read private scoring artifacts.")
    print("\nThis server exits when the agent calls roboclaws__done or you press Ctrl-C.\n")
    sys.stdout.flush()


def _is_loopback_url(url: str) -> bool:
    hostname = urlparse(url).hostname
    return hostname in {"127.0.0.1", "localhost"}


def _load_runtime_map_prior(path: str | Path | None) -> dict[str, Any] | None:
    return read_runtime_map_prior_artifact(path)


def _prepare_server_backend_setup(
    *,
    output_dir: Path,
    seed: int,
    backend: str,
    generated_mess_count: int,
    generated_mess_object_ids: tuple[str, ...],
    generated_mess_manifest_path: str | Path | None,
    map_bundle_dir: str | Path | None,
    perception_mode: str,
    include_robot: bool,
    robot_name: str,
    record_robot_views: bool,
    scene_source: str,
    scene_index: int,
    isaac_scene_usd_path: str | Path | None,
    evidence_lane: str | None,
    runtime_map_prior_path: str | Path | None,
    context_json: str | Path | None,
    runner_python: str | Path | None,
    runner_script: str | Path | None,
    agibot_map_artifact_dir: str | Path | None,
    real_movement_enabled: bool,
    task_prompt: str,
    visual_grounding: str,
    visual_grounding_timeout_s: float | None,
) -> _ServerBackendSetup:
    selected_bundle_dir = selected_nav2_map_bundle_dir(
        map_bundle_dir,
        required=True,
    )
    runtime_map_prior = _load_runtime_map_prior(runtime_map_prior_path)
    if backend == AGIBOT_GDK_BACKEND:
        return _prepare_agibot_backend_setup(
            output_dir=output_dir,
            seed=seed,
            context_json=context_json,
            runner_python=runner_python,
            runner_script=runner_script,
            agibot_map_artifact_dir=agibot_map_artifact_dir,
            real_movement_enabled=real_movement_enabled,
            task_prompt=task_prompt,
            visual_grounding_pipeline_id=visual_grounding,
            visual_grounding_timeout_s=visual_grounding_timeout_s,
            include_robot=include_robot,
            record_robot_views=record_robot_views,
            selected_bundle_dir=selected_bundle_dir,
            runtime_map_prior=runtime_map_prior,
        )
    validate_cleanup_run_options(
        backend_name=backend,
        include_robot=include_robot,
        record_robot_views=record_robot_views,
        generated_mess_count=generated_mess_count,
    )
    return _prepare_generic_backend_setup(
        output_dir=output_dir,
        seed=seed,
        backend=backend,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
        generated_mess_manifest_path=generated_mess_manifest_path,
        scene_source=scene_source,
        scene_index=scene_index,
        include_robot=include_robot,
        robot_name=robot_name,
        selected_bundle_dir=selected_bundle_dir,
        isaac_scene_usd_path=isaac_scene_usd_path,
        runtime_map_prior=runtime_map_prior,
        perception_mode=perception_mode,
        evidence_lane=evidence_lane,
    )


def _prepare_agibot_backend_setup(
    *,
    output_dir: Path,
    seed: int,
    context_json: str | Path | None,
    runner_python: str | Path | None,
    runner_script: str | Path | None,
    agibot_map_artifact_dir: str | Path | None,
    real_movement_enabled: bool,
    task_prompt: str,
    visual_grounding_pipeline_id: str,
    visual_grounding_timeout_s: float | None,
    include_robot: bool,
    record_robot_views: bool,
    selected_bundle_dir: Path | None,
    runtime_map_prior: dict[str, Any] | None,
) -> _ServerBackendSetup:
    if context_json is None or str(context_json) == "":
        raise ValueError("backend=agibot_gdk requires --context-json")
    if runner_script is None or str(runner_script) == "":
        raise ValueError("backend=agibot_gdk requires --runner-script")
    if runner_python is None or str(runner_python) == "":
        raise ValueError("backend=agibot_gdk requires --runner-python")
    if agibot_map_artifact_dir is None or str(agibot_map_artifact_dir) == "":
        raise ValueError("backend=agibot_gdk requires --agibot-map-artifact-dir")
    if include_robot:
        raise ValueError("robot inclusion requires a visual subprocess backend")
    if record_robot_views:
        raise ValueError(
            "record_robot_views requires a visual subprocess backend and include_robot"
        )
    scenario = build_cleanup_scenario(seed=seed)
    agibot_contract = AgibotHouseholdBackend(
        run_dir=output_dir,
        context_json=Path(context_json),
        runner_script=Path(runner_script),
        runner_python=runner_python,
        real_movement_enabled=real_movement_enabled,
        agibot_map_artifact_dir=Path(agibot_map_artifact_dir),
        scenario=scenario,
        task_prompt=task_prompt,
        visual_grounding_pipeline_id=visual_grounding_pipeline_id,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
    )
    return _ServerBackendSetup(
        base_contract=agibot_contract.contract,
        scenario=scenario,
        selected_bundle_dir=selected_bundle_dir,
        runtime_map_prior=runtime_map_prior,
        agibot_contract=agibot_contract,
        perception_mode=agibot_contract.perception_mode,
        evidence_lane=None,
    )


def _prepare_generic_backend_setup(
    *,
    output_dir: Path,
    seed: int,
    backend: str,
    generated_mess_count: int,
    generated_mess_object_ids: tuple[str, ...],
    generated_mess_manifest_path: str | Path | None,
    scene_source: str,
    scene_index: int,
    include_robot: bool,
    robot_name: str,
    selected_bundle_dir: Path | None,
    isaac_scene_usd_path: str | Path | None,
    runtime_map_prior: dict[str, Any] | None,
    perception_mode: str,
    evidence_lane: str | None,
) -> _ServerBackendSetup:
    base_contract = build_household_backend_session(
        backend_name=backend,
        run_dir=output_dir,
        seed=seed,
        include_robot=include_robot,
        robot_name=robot_name,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
        generated_mess_manifest_path=generated_mess_manifest_path,
        scene_source=scene_source,
        scene_index=scene_index,
        map_bundle_dir=selected_bundle_dir,
        isaac_scene_usd_path=isaac_scene_usd_path,
    )
    return _ServerBackendSetup(
        base_contract=base_contract,
        scenario=base_contract.scenario,
        selected_bundle_dir=selected_bundle_dir,
        runtime_map_prior=runtime_map_prior,
        agibot_contract=None,
        perception_mode=perception_mode,
        evidence_lane=evidence_lane,
    )


def _run_server_until_done(
    *,
    server: HouseholdWorldMCPServer,
    output_dir: Path,
    url: str,
    poll_interval_s: float,
) -> dict[str, Any]:
    terminated_by = "unknown"
    error: str | None = None
    try:
        server.run_in_thread()
        server.write_runtime_event("direct_molmo_realworld_cleanup_server_started", mcp_url=url)
        while not server.done_event.wait(poll_interval_s):
            pass
        terminated_by = "agent_done"
    except KeyboardInterrupt:
        terminated_by = "keyboard_interrupt"
        server.write_runtime_event("keyboard_interrupt")
    except Exception as exc:
        terminated_by = "error"
        error = str(exc)
        server.write_runtime_event("direct_molmo_realworld_cleanup_server_error", error=error)
        raise
    finally:
        result = _server_result(
            output_dir=output_dir,
            terminated_by=terminated_by,
            error=error,
        )
        server.write_runtime_event(
            "direct_molmo_realworld_cleanup_server_finished",
            terminated_by=terminated_by,
            error=error,
        )
        server.close()
    return result


def _server_result(
    *,
    output_dir: Path,
    terminated_by: str,
    error: str | None,
) -> dict[str, Any]:
    return {
        "terminated_by": terminated_by,
        "output_dir": str(output_dir),
        "run_result": str(output_dir / "run_result.json"),
        "error": error,
    }


def run_molmo_realworld_cleanup_agent_server(
    *,
    output_dir: Path,
    seed: int = 7,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    policy: str = "codex_agent",
    task_surface: str = "household-world",
    task_intent: str = HOUSEHOLD_INTENT_CLEANUP,
    task_prompt: str = DEFAULT_REALWORLD_TASK,
    backend: str = SYNTHETIC_BACKEND,
    generated_mess_count: int = 10,
    generated_mess_object_ids: tuple[str, ...] = (),
    generated_mess_manifest_path: str | Path | None = None,
    map_bundle_dir: str | Path | None = None,
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    record_robot_views: bool = False,
    scene_source: str = "procthor-10k-val",
    scene_index: int = 0,
    isaac_scene_usd_path: str | Path | None = None,
    evidence_lane: str | None = None,
    runtime_map_prior_path: str | Path | None = None,
    visual_grounding: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_base_url: str | None = None,
    visual_grounding_timeout_s: float | None = None,
    operator_messages_path: str | Path | None = None,
    context_json: str | Path | None = None,
    runner_python: str | Path | None = None,
    runner_script: str | Path | None = None,
    agibot_map_artifact_dir: str | Path | None = None,
    real_movement_enabled: bool = False,
    goal_contract_json: str | None = None,
    goal_contract_path: str | Path | None = None,
    required_capability_profiles: tuple[str, ...] = (),
    rerun_command: str | None = None,
    agent_sdk_camera_grounded_composite_tools: bool = False,
    robot_view_capture_policy: str = ROBOT_VIEW_CAPTURE_POLICY_FULL,
    poll_interval_s: float = 0.25,
    print_setup_text: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if backend == AGIBOT_GDK_BACKEND:
        generated_mess_count = 0
    backend_setup = _prepare_server_backend_setup(
        output_dir=output_dir,
        seed=seed,
        backend=backend,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
        generated_mess_manifest_path=generated_mess_manifest_path,
        map_bundle_dir=map_bundle_dir,
        perception_mode=perception_mode,
        include_robot=include_robot,
        robot_name=robot_name,
        record_robot_views=record_robot_views,
        scene_source=scene_source,
        scene_index=scene_index,
        isaac_scene_usd_path=isaac_scene_usd_path,
        evidence_lane=evidence_lane,
        runtime_map_prior_path=runtime_map_prior_path,
        context_json=context_json,
        runner_python=runner_python,
        runner_script=runner_script,
        agibot_map_artifact_dir=agibot_map_artifact_dir,
        real_movement_enabled=real_movement_enabled,
        task_prompt=task_prompt,
        visual_grounding=visual_grounding,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
    )
    url = mcp_url(host, port)
    goal_contract = goal_contract_from_json(goal_contract_json) or goal_contract_from_file(
        goal_contract_path
    )
    normalized_task_intent = household_intent_from_goal_contract(
        goal_contract,
        fallback=normalize_household_intent(task_intent),
    )
    server = make_household_world_mcp(
        run_dir=output_dir,
        scenario=backend_setup.scenario,
        base_contract=backend_setup.base_contract,
        contract=backend_setup.agibot_contract,
        host=host,
        port=port,
        policy=policy,
        task_surface=task_surface,
        task_intent=normalized_task_intent,
        task_prompt=task_prompt,
        static_fixture_projection_mode="room_only",
        perception_mode=backend_setup.perception_mode,
        map_bundle_dir=backend_setup.selected_bundle_dir,
        record_robot_views=record_robot_views,
        evidence_lane=backend_setup.evidence_lane,
        runtime_map_prior=backend_setup.runtime_map_prior,
        runtime_map_prior_source=str(runtime_map_prior_path or ""),
        visual_grounding=visual_grounding,
        visual_grounding_base_url=visual_grounding_base_url,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        goal_contract=goal_contract,
        required_capability_profiles=(
            tuple(required_capability_profiles) if required_capability_profiles else None
        ),
        operator_messages_path=operator_messages_path,
        agent_sdk_camera_grounded_composite_tools=agent_sdk_camera_grounded_composite_tools,
        robot_view_capture_policy=robot_view_capture_policy,
        rerun_command=rerun_command,
    )
    if print_setup_text:
        print_setup(
            output_dir,
            url,
            policy,
            backend=backend,
            perception_mode=backend_setup.perception_mode,
            record_robot_views=record_robot_views,
            evidence_lane=backend_setup.evidence_lane,
            task_intent=normalized_task_intent,
        )
    return _run_server_until_done(
        server=server,
        output_dir=output_dir,
        url=url,
        poll_interval_s=poll_interval_s,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    args = parse_args(argv)
    output_dir = args.output_dir or default_output_dir(args.policy)
    try:
        result = run_molmo_realworld_cleanup_agent_server(
            output_dir=output_dir,
            seed=args.seed,
            host=args.host,
            port=args.port,
            policy=args.policy,
            task_intent=args.intent,
            task_prompt=args.task,
            backend=args.backend,
            generated_mess_count=args.generated_mess_count,
            generated_mess_object_ids=tuple(args.generated_mess_object_id or ()),
            generated_mess_manifest_path=args.generated_mess_manifest_path,
            map_bundle_dir=args.map_bundle_dir,
            perception_mode=args.perception_mode,
            include_robot=args.include_robot,
            robot_name=args.robot_name,
            record_robot_views=args.record_robot_views,
            scene_source=args.scene_source,
            scene_index=args.scene_index,
            isaac_scene_usd_path=args.isaac_scene_usd_path,
            evidence_lane=args.evidence_lane,
            runtime_map_prior_path=args.runtime_map_prior,
            visual_grounding=args.visual_grounding,
            visual_grounding_base_url=args.visual_grounding_base_url,
            visual_grounding_timeout_s=args.visual_grounding_timeout_s,
            operator_messages_path=args.operator_messages_path,
            context_json=args.context_json,
            runner_python=args.runner_python,
            runner_script=args.runner_script,
            agibot_map_artifact_dir=args.agibot_map_artifact_dir,
            real_movement_enabled=args.real_movement_enabled,
            goal_contract_json=args.goal_contract_json,
            goal_contract_path=args.goal_contract,
            required_capability_profiles=tuple(args.required_capability_profile),
            rerun_command=args.rerun_command,
            agent_sdk_camera_grounded_composite_tools=(
                args.agent_sdk_camera_grounded_composite_tools
            ),
            robot_view_capture_policy=args.robot_view_capture_policy,
        )
    except Exception as exc:
        print(f"Molmo real-world cleanup agent server failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
