#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.goals import goal_contract_from_file, goal_contract_from_json  # noqa: E402
from roboclaws.core.json_sources import read_json_object  # noqa: E402
from roboclaws.core.task_intents import (  # noqa: E402
    HOUSEHOLD_INTENT_OPEN_ENDED,
    household_intent_from_goal_contract,
)
from roboclaws.household.household_backend_contract import (  # noqa: E402
    SYNTHETIC_BACKEND,
    build_household_backend_session,
    validate_cleanup_run_options,
)
from roboclaws.household.household_mcp_server import (  # noqa: E402
    make_household_world_mcp,
)
from roboclaws.household.household_runtime_contract import (  # noqa: E402
    CAMERA_MODEL_POLICY_MODE,
    DEFAULT_REALWORLD_TASK,
    RAW_FPV_ONLY_MODE,
    VISIBLE_OBJECT_DETECTIONS_MODE,
)
from roboclaws.household.nav2_map_bundle import selected_nav2_map_bundle_dir  # noqa: E402
from roboclaws.household.profiles import (  # noqa: E402
    evidence_lane_names,
)
from roboclaws.household.semantic_cleanup_loop import (  # noqa: E402
    run_semantic_cleanup_loop,
)
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND  # noqa: E402
from roboclaws.household.tasks import HOUSEHOLD_PRESET_SPECS, HOUSEHOLD_TASK_SPECS  # noqa: E402
from roboclaws.household.visual_grounding import (  # noqa: E402
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
)
from roboclaws.maps.runtime_prior_snapshot import (
    read_runtime_map_prior_artifact,  # noqa: E402
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic smoke agent through the ADR-0003 Molmo MCP surface."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--task", default=DEFAULT_REALWORLD_TASK)
    parser.add_argument("--goal-contract", type=Path)
    parser.add_argument("--goal-contract-json")
    parser.add_argument("--policy", default="household_contract_smoke_agent")
    parser.add_argument(
        "--backend",
        choices=(SYNTHETIC_BACKEND, MOLMOSPACES_SUBPROCESS_BACKEND),
        default=SYNTHETIC_BACKEND,
    )
    parser.add_argument("--generated-mess-count", type=int, default=10)
    parser.add_argument(
        "--generated-mess-object-id",
        action="append",
        help="Private run-control object id to include in the generated mess set. Repeatable.",
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
    parser.add_argument("--visual-grounding", default=SIM_VISUAL_GROUNDING_PIPELINE_ID)
    parser.add_argument("--visual-grounding-base-url")
    parser.add_argument("--visual-grounding-timeout-s", type=float)
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
    return parser.parse_args(argv)


def run_smoke(
    *,
    output_dir: Path,
    seed: int = 1,
    task: str = DEFAULT_REALWORLD_TASK,
    policy: str = "household_contract_smoke_agent",
    backend: str = SYNTHETIC_BACKEND,
    generated_mess_count: int = 10,
    generated_mess_object_ids: tuple[str, ...] = (),
    map_bundle_dir: str | Path | None = None,
    perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    record_robot_views: bool = False,
    evidence_lane: str | None = None,
    runtime_map_prior_path: str | Path | None = None,
    visual_grounding: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_base_url: str | None = None,
    visual_grounding_timeout_s: float | None = None,
    goal_contract_json: str | None = None,
    goal_contract_path: str | Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    validate_cleanup_run_options(
        backend_name=backend,
        include_robot=include_robot,
        record_robot_views=record_robot_views,
        generated_mess_count=generated_mess_count,
    )
    selected_bundle_dir = selected_nav2_map_bundle_dir(
        map_bundle_dir,
        required=True,
    )
    runtime_map_prior = _load_runtime_map_prior(runtime_map_prior_path)

    base_contract = build_household_backend_session(
        backend_name=backend,
        run_dir=output_dir,
        seed=seed,
        include_robot=include_robot,
        robot_name=robot_name,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
    )
    scenario = base_contract.scenario

    goal_contract = goal_contract_from_json(goal_contract_json) or goal_contract_from_file(
        goal_contract_path
    )
    task_intent = household_intent_from_goal_contract(goal_contract)
    required_capability_profiles = (
        goal_contract.required_capabilities
        if goal_contract is not None and goal_contract.required_capabilities
        else (
            HOUSEHOLD_PRESET_SPECS[task_intent].required_capabilities
            if task_intent in HOUSEHOLD_PRESET_SPECS
            else HOUSEHOLD_TASK_SPECS["household-world"].required_capabilities
        )
    )
    server = make_household_world_mcp(
        run_dir=output_dir,
        scenario=scenario,
        base_contract=base_contract,
        port=0,
        policy=policy,
        agent_driven=True,
        task_prompt=task,
        static_fixture_projection_mode="room_only",
        perception_mode=perception_mode,
        map_bundle_dir=selected_bundle_dir,
        record_robot_views=record_robot_views,
        evidence_lane=evidence_lane,
        runtime_map_prior=runtime_map_prior,
        runtime_map_prior_source=str(runtime_map_prior_path or ""),
        visual_grounding=visual_grounding,
        visual_grounding_base_url=visual_grounding_base_url,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        goal_contract=goal_contract,
        required_capability_profiles=required_capability_profiles,
    )
    try:
        if task_intent == HOUSEHOLD_INTENT_OPEN_ENDED:
            _drive_open_ended_probe(server)
            done = server.call_tool("done", reason=f"{policy} open-ended smoke task complete")
        else:
            _drive_public_sweep(server)
            done = server.call_tool("done", reason=f"{policy} cleanup complete")
    finally:
        server.close()

    return _read_smoke_run_result(Path(done["run_result"]))


def _read_smoke_run_result(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="smoke run_result")


def _load_runtime_map_prior(path: str | Path | None) -> dict[str, Any] | None:
    return read_runtime_map_prior_artifact(path)


def _drive_public_sweep(
    server: Any,
) -> None:
    metric_map = server.call_tool("metric_map")
    handled_handles: set[str] = set()
    for waypoint in metric_map["inspection_waypoints"]:
        waypoint_id = str(waypoint["waypoint_id"])
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
        observation = server.call_tool("observe")
        detections = _detections_for_observation(server, observation)
        for detection in detections:
            handle = str(detection["object_id"])
            if handle in handled_handles:
                continue
            detection = _confirm_visual_scan_if_needed(server, detection)
            target_fixture = _target_fixture_for_detection(server, detection)
            if target_fixture is None:
                continue
            fixture_id = str(target_fixture["fixture_id"])
            support = detection.get("support_estimate") or {}
            if support.get("fixture_id") == fixture_id:
                continue
            _clean_handle(
                server,
                handle=handle,
                fixture=target_fixture,
            )
            server.call_tool("observe")
            handled_handles.add(handle)
        _clean_pending_worklist(server, handled_handles)
    _clean_pending_worklist(server, handled_handles)


def _drive_open_ended_probe(server: Any) -> None:
    metric_map = server.call_tool("metric_map")
    waypoints = metric_map.get("inspection_waypoints") or []
    if not waypoints:
        server.call_tool("observe")
        return
    for waypoint in waypoints:
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if waypoint_id:
            server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
        observation = server.call_tool("observe")
        if _detections_for_observation(server, observation):
            return


def _clean_pending_worklist(server: Any, handled_handles: set[str]) -> None:
    while True:
        readiness = server.call_tool("done", reason="probe public cleanup readiness")
        if readiness.get("ok"):
            return
        pending = _pending_cleanup_candidates_from_done(readiness)
        next_item = next(
            (item for item in pending if str(item.get("object_id") or "") not in handled_handles),
            None,
        )
        if next_item is None:
            return
        handle = str(next_item.get("object_id") or "")
        next_item = _confirm_visual_scan_if_needed(server, next_item)
        fixture = _target_fixture_for_detection(server, next_item)
        if fixture is None:
            handled_handles.add(handle)
            continue
        _clean_handle(server, handle=handle, fixture=fixture)
        server.call_tool("observe")
        handled_handles.add(handle)


def _pending_cleanup_candidates_from_done(done_response: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for blocker in (done_response.get("completion") or {}).get("blockers") or []:
        if blocker.get("type") != "pending_cleanup_candidates":
            continue
        candidates.extend(
            dict(item)
            for item in blocker.get("pending_cleanup_candidates") or []
            if isinstance(item, dict)
        )
    if not candidates:
        candidates.extend(
            dict(item)
            for item in done_response.get("pending_cleanup_candidates") or []
            if isinstance(item, dict)
        )
    return candidates


def _target_fixture_for_detection(server: Any, detection: dict[str, Any]) -> dict[str, Any] | None:
    fixture_id = str(detection.get("candidate_fixture_id") or "")
    if not fixture_id:
        options = detection.get("destination_options") or []
        first_option = next(
            (
                item
                for item in options
                if isinstance(item, dict) and str(item.get("candidate_fixture_id") or "")
            ),
            None,
        )
        if first_option is not None:
            fixture_id = str(first_option["candidate_fixture_id"])
    if not fixture_id:
        return None
    fixtures = server.contract.public_receptacles_by_id()
    fixture = fixtures.get(fixture_id)
    if fixture is None:
        return None
    return dict(fixture)


def _detections_for_observation(server: Any, observation: dict[str, Any]) -> list[dict[str, Any]]:
    detections = list(observation.get("visible_object_detections", []))
    if detections or not observation.get("camera_model_policy_available"):
        return detections
    raw = observation.get("raw_fpv_observation") or {}
    observation_id = str(raw.get("observation_id") or "")
    response = server.call_tool("declare_visual_candidates", observation_id=observation_id)
    return list(response.get("camera_model_candidates", []))


def _confirm_visual_scan_if_needed(server: Any, detection: dict[str, Any]) -> dict[str, Any]:
    if str(detection.get("candidate_state") or "") != "visual_scan_required":
        return detection
    handle = str(detection.get("object_id") or "")
    live_detection = _inspect_detection(server, handle)
    waypoint_id = _visual_scan_waypoint_id(server, detection, live_detection)
    if waypoint_id:
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
    server.call_tool("adjust_camera", yaw_delta_deg=15.0, pitch_delta_deg=0.0)
    observation = server.call_tool("observe")
    confirmed = next(
        (
            dict(item)
            for item in observation.get("visible_object_detections", [])
            if str(item.get("object_id") or "") == handle
        ),
        detection,
    )
    if detection.get("destination_options") and not confirmed.get("destination_options"):
        confirmed["destination_options"] = list(detection["destination_options"])
    return confirmed


def _inspect_detection(server: Any, handle: str) -> dict[str, Any]:
    if not handle:
        return {}
    response = server.call_tool("inspect_visible_object", object_id=handle)
    detection = response.get("detection") if response.get("ok") else {}
    return dict(detection) if isinstance(detection, dict) else {}


def _visual_scan_waypoint_id(
    server: Any,
    detection: dict[str, Any],
    live_detection: dict[str, Any],
) -> str:
    for source in (live_detection, detection):
        waypoint_id = str(source.get("waypoint_id") or source.get("last_waypoint_id") or "")
        if waypoint_id:
            return waypoint_id
    for source in (live_detection, detection):
        support = source.get("support_estimate") or {}
        fixture_id = str(source.get("source_fixture_id") or support.get("fixture_id") or "")
        waypoint_id = _preferred_waypoint_for_fixture(server, fixture_id)
        if waypoint_id:
            return waypoint_id
    return ""


def _preferred_waypoint_for_fixture(server: Any, fixture_id: str) -> str:
    if not fixture_id:
        return ""
    fixture = server.contract.public_receptacles_by_id().get(fixture_id) or {}
    return str(
        fixture.get("preferred_inspection_waypoint_id")
        or fixture.get("preferred_manipulation_waypoint_id")
        or fixture.get("waypoint_id")
        or ""
    )


def _clean_handle(
    server: Any,
    *,
    handle: str,
    fixture: dict[str, Any],
) -> None:
    fixture_id = str(fixture["fixture_id"])
    run_semantic_cleanup_loop(
        targets=[
            {
                "object_id": handle,
                "target_receptacle_id": fixture_id,
                "target_receptacle": fixture,
            }
        ],
        contract=_RealWorldMcpLoop(server),
        call_tool=_invoke_shared_loop_tool,
        target_request_key="fixture_id",
        include_object_id_in_receptacle_request=False,
        include_object_id_in_target_requests=False,
    )


def _invoke_shared_loop_tool(
    _tool: str,
    _request: dict[str, Any],
    fn: Any,
) -> dict[str, Any]:
    return fn()


class _RealWorldMcpLoop:
    def __init__(self, server: Any) -> None:
        self._server = server

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return self._server.call_tool("navigate_to_object", object_id=object_id)

    def pick(self, object_id: str) -> dict[str, Any]:
        return self._server.call_tool("pick", object_id=object_id)

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._server.call_tool("navigate_to_receptacle", fixture_id=receptacle_id)

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._server.call_tool("open_receptacle", fixture_id=receptacle_id)

    def place(self, receptacle_id: str) -> dict[str, Any]:
        return self._server.call_tool("place", fixture_id=receptacle_id)

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        return self._server.call_tool("place_inside", fixture_id=receptacle_id)

    def close_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._server.call_tool("close_receptacle", fixture_id=receptacle_id)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_smoke(
        output_dir=args.output_dir,
        seed=args.seed,
        task=args.task,
        policy=args.policy,
        backend=args.backend,
        generated_mess_count=args.generated_mess_count,
        generated_mess_object_ids=tuple(args.generated_mess_object_id or ()),
        map_bundle_dir=args.map_bundle_dir,
        perception_mode=args.perception_mode,
        include_robot=args.include_robot,
        robot_name=args.robot_name,
        record_robot_views=args.record_robot_views,
        evidence_lane=args.evidence_lane,
        runtime_map_prior_path=args.runtime_map_prior,
        visual_grounding=args.visual_grounding,
        visual_grounding_base_url=args.visual_grounding_base_url,
        visual_grounding_timeout_s=args.visual_grounding_timeout_s,
        goal_contract_json=args.goal_contract_json,
        goal_contract_path=args.goal_contract,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
