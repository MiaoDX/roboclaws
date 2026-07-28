from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import agibot_operator_gates as gates
from roboclaws.household.agibot_household_backend import AgibotHouseholdBackend
from roboclaws.household.agibot_map_defaults import (
    DEFAULT_AGIBOT_CONFIDENCE_LAYER,
)
from roboclaws.household.agibot_sdk_runner import (
    BLOCKED_MANIPULATION_TOOLS,
    AgibotSDKRunnerAdapter,
    run_physical_agibot_cleanup_pilot,
)
from roboclaws.household.artifact_report import (
    is_cleanup_run_result_artifact,
    rerender_cleanup_report_from_artifact_path,
)
from roboclaws.household.household_mcp_server import (
    MCP_SERVER_NAME,
    make_household_world_mcp,
)
from roboclaws.household.profiles import AGIBOT_SDK_RUNNER_BACKEND
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)

AGIBOT_MAP_BUILD_TOOLS = (
    "metric_map",
    "navigate_to_room",
    "navigate_to_waypoint",
    "navigate_to_relative_pose",
    "observe",
    "adjust_camera",
    "declare_visual_candidates",
    "navigate_to_visual_candidate",
    "inspect_visible_object",
    "navigate_to_object",
    "navigate_to_receptacle",
    "check_operator_messages",
    "done",
)


def _make_common_agibot_map_build_server(
    *,
    run_dir: Path,
    context_json: Path,
    visual_grounding_pipeline_id: str = "grounding-dino",
    visual_grounding_timeout_s: float | None = None,
):
    _require_agibot_sdk_runner()
    contract = AgibotHouseholdBackend(
        run_dir=run_dir,
        context_json=context_json,
        **_sdk_kwargs(),
        visual_grounding_pipeline_id=visual_grounding_pipeline_id,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
    )
    return make_household_world_mcp(
        run_dir=run_dir,
        contract=contract,
        map_bundle_dir=PREBUILT_BUNDLE,
        task_intent="map-build",
        evidence_lane=None,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPLETED_CONTEXT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "agibot_map_context.completed.json"
ROBOT_MAP_12_CONTEXT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "agibot_robot_map_12_context.completed.json"
)
ROBOT_MAP_12_ARTIFACT = REPO_ROOT / "tests" / "fixtures" / "runtime_map_prior" / "robot_map_12"


def _configured_runner_path() -> Path | None:
    value = os.environ.get("ROBOCLAWS_AGIBOT_RUNNER_SCRIPT", "").strip()
    return Path(value) if value else None


PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def _require_agibot_sdk_runner() -> None:
    runner = _configured_runner_path()
    if runner is None or not runner.is_file():
        pytest.skip("ROBOCLAWS_AGIBOT_RUNNER_SCRIPT is not configured")


def _sdk_kwargs() -> dict:
    _require_agibot_sdk_runner()
    return {
        "runner_script": _configured_runner_path(),
        "runner_python": sys.executable,
        "agibot_map_artifact_dir": ROBOT_MAP_12_ARTIFACT,
    }


def _assert_static_fixture_projection_artifact_only(
    run_result: dict,
    runtime_map: dict,
    trace_events: list[dict],
) -> None:
    assert "static_fixture_projection" not in AGIBOT_MAP_BUILD_TOOLS
    assert "static_fixture_projection" not in agent_view_module.public_tool_names(
        run_result["agent_view"]
    )
    assert "static_fixture_projection" not in run_result["agent_view"]
    assert "static_fixture_projection" in runtime_map
    assert not any(event.get("tool") == "static_fixture_projection" for event in trace_events)


def _assert_camera_grounding_failure_evidence(run_result: dict) -> None:
    camera_policy = run_result["camera_model_policy_evidence"]
    assert camera_policy["enabled"] is True
    assert camera_policy["visual_grounding_pipeline_id"] == "grounding-dino"
    assert camera_policy["visual_grounding_failure_count"] == 1
    assert camera_policy["model_provenance"] == "external_visual_grounding_service"
    assert camera_policy["events"][0]["visual_grounding_pipeline"]["status"] == "failed"
    assert agent_view_module.camera_model_policy_evidence(run_result["agent_view"]) == (
        camera_policy
    )


def _assert_agibot_map_build_tool_responses(
    metric_map: dict,
    nav: dict,
    observe: dict,
    done: dict,
) -> None:
    assert metric_map["tool"] == "metric_map"
    assert nav["tool"] == "navigate_to_waypoint"
    assert nav["waypoint_id"] == "wp_sofa_front"
    assert observe["tool"] == "observe"
    assert done["agent_driven"] is True


def _assert_agibot_map_build_run_identity(run_result: dict) -> None:
    assert run_result["agent_driven"] is True
    assert run_result["mcp_server"] == MCP_SERVER_NAME
    assert run_result["backend_variant"] == "agibot_gdk"
    assert run_result["evidence_lane"] == "physical-robot-evidence"
    assert run_result["evidence_lane_metadata"]["evidence_lane"] == "physical-robot-evidence"
    assert run_result["perception_mode"] == "camera_model_policy"
    assert run_result["visual_grounding_pipeline_id"] == "grounding-dino"
    assert run_result["raw_fpv_observations"][0]["camera"] == "head_color"
    capabilities = agent_view_module.capabilities(run_result["agent_view"])
    assert capabilities["capability_profiles"] == [
        HOUSEHOLD_WORLD_PROFILE,
        HOUSEHOLD_EPISODE_PROFILE,
    ]
    assert not set(BLOCKED_MANIPULATION_TOOLS) & set(
        agent_view_module.public_tool_names(run_result["agent_view"])
    )


def _assert_agibot_map_build_policy_trace(run_result: dict) -> None:
    assert run_result["cleanup_policy_trace"]["agent_reasoning_visible"] is True
    assert run_result["cleanup_policy_trace"]["agent_review_kind"] == (
        "agibot_codex_map_build_review"
    )
    assert run_result["cleanup_policy_trace"]["events"][0]["decision"] == (
        "inspect_public_metric_map"
    )
    assert all(
        event["tool"] not in BLOCKED_MANIPULATION_TOOLS
        for event in run_result["cleanup_policy_trace"]["events"]
    )


def _assert_agibot_map_build_runtime_map(run_result: dict, runtime_map: dict) -> None:
    assert run_result["real_robot_readiness"]["map_build"] is True
    assert run_result["real_robot_readiness"]["visited_waypoint_ids"] == ["wp_sofa_front"]
    assert run_result["runtime_metric_map"]["visited_waypoint_ids"] == ["wp_sofa_front"]
    assert runtime_map["source"] == "household_world_mcp"
    assert runtime_map["visited_waypoint_ids"] == ["wp_sofa_front"]


def _assert_agibot_map_build_artifacts(
    run_result: dict,
    trace_events: list[dict],
    report_text: str,
) -> None:
    assert run_result["manipulation_evidence"]["status"] == "blocked_capability"
    assert any(
        str(path).endswith("runtime_metric_map.json") for path in run_result["artifacts"].values()
    )
    assert any(event.get("tool") == "observe" for event in trace_events)
    assert "AgiBot Backend Evidence" in report_text
    assert "Camera Labeler Evidence" in report_text
    assert "grounding-dino" in report_text


def _read_physical_pilot_artifacts(run_dir: Path) -> tuple[str, dict, dict, dict]:
    report_text = (run_dir / "report.html").read_text(encoding="utf-8")
    persisted = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    public_agent_view_artifact = json.loads(
        (run_dir / "subphases" / "01-agent-view" / "agent_view.json").read_text(encoding="utf-8")
    )
    vendor_agent_view_artifact = json.loads(
        (run_dir / "subphases" / "01-agent-view" / "vendor_agent_view.json").read_text(
            encoding="utf-8"
        )
    )
    return report_text, persisted, public_agent_view_artifact, vendor_agent_view_artifact


def _assert_physical_pilot_run_identity(run_result: dict) -> None:
    assert run_result["evidence_lane"] == "physical-robot-evidence"
    assert run_result["evidence_lane_metadata"]["evidence_lane"] == "physical-robot-evidence"
    assert run_result["backend"] == AGIBOT_SDK_RUNNER_BACKEND
    assert run_result["backend_variant"] == "agibot_gdk"
    assert run_result["primitive_provenance"] == "blocked_capability"
    assert run_result["real_robot_readiness"]["status"] == (
        "physical_agibot_navigation_pilot_rehearsal"
    )
    assert run_result["real_robot_readiness"]["movement_enabled"] is False
    assert run_result["real_robot_readiness"]["physical_navigation_pilot"] is True
    assert run_result["real_robot_readiness"]["physical_cleanup_ready"] is False
    assert run_result["physical_agibot_pilot"]["navigation_attempt"]["navigation_status"] == (
        "dry_run_not_executed"
    )


def test_physical_agibot_pilot_uses_sdk_runner_reports_without_movement(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")

    run_result = run_physical_agibot_cleanup_pilot(
        run_dir=tmp_path / "run",
        context_json=context_path,
        **_sdk_kwargs(),
    )

    run_dir = tmp_path / "run"
    (
        report_text,
        persisted,
        public_agent_view_artifact,
        vendor_agent_view_artifact,
    ) = _read_physical_pilot_artifacts(run_dir)
    runner = run_result["agibot_sdk_runner"]
    subphase_reports = runner["subphase_reports"]

    _assert_physical_pilot_run_identity(run_result)
    capabilities = agent_view_module.capabilities(run_result["agent_view"])
    assert public_agent_view_artifact == run_result["agent_view"]
    assert public_agent_view_artifact["schema"] == agent_view_module.AGENT_VIEW_SCHEMA
    assert vendor_agent_view_artifact.get("schema") != agent_view_module.AGENT_VIEW_SCHEMA
    assert vendor_agent_view_artifact["metric_map"]["inspection_waypoints"][0]["waypoint_id"] == (
        "wp_sofa_front"
    )
    assert capabilities["capability_profiles"] == [
        HOUSEHOLD_WORLD_PROFILE,
        HOUSEHOLD_MANIPULATION_PROFILE,
        HOUSEHOLD_EPISODE_PROFILE,
    ]
    blocked_details = {item["name"]: item for item in capabilities["blocked_capability_details"]}
    assert set(blocked_details) == set(BLOCKED_MANIPULATION_TOOLS)
    assert blocked_details["pick"]["source_profile_id"] == HOUSEHOLD_MANIPULATION_PROFILE
    assert [
        item["tool"] for item in run_result["physical_agibot_pilot"]["blocked_manipulation_results"]
    ] == list(BLOCKED_MANIPULATION_TOOLS)
    assert [item["stage"] for item in subphase_reports] == [
        "agent_view_export",
        "observe",
        "navigate_waypoint",
    ]
    for item in subphase_reports:
        assert (run_dir / item["report"]).is_file()
        assert (run_dir / item["run_result"]).is_file()

    assert "AgiBot Backend Evidence" in report_text
    assert "CLI boundary" in report_text
    assert "One Roboclaws pilot run" in report_text
    assert "movement_enabled=false" in report_text
    assert "Agibot pilot progress" in report_text
    assert "Dry-run blocked by movement gate" in report_text
    assert "Physical manipulation is intentionally blocked" in report_text
    assert persisted["semantic_substeps"] == []
    assert persisted["cleanup_policy_trace"]["agent_review_kind"] == (
        "agibot_navigation_perception_pilot_review"
    )
    assert persisted["cleanup_policy_trace"]["agent_reasoning_visible"] is True
    assert persisted["cleanup_policy_trace"]["events"][0]["decision"] == "observe_head_color"
    assert persisted["cleanup_policy_trace"]["events"][1]["decision"] == "visit_public_waypoint"
    assert persisted["cleanup_policy_trace"]["events"][-1]["decision"] == "block_manipulation"
    assert persisted["agibot_sdk_runner"]["gdk_imported_by_roboclaws"] is False
    assert persisted["agibot_sdk_runner"]["next_confidence_layer"] == (
        DEFAULT_AGIBOT_CONFIDENCE_LAYER
    )
    assert is_cleanup_run_result_artifact(run_dir)
    assert rerender_cleanup_report_from_artifact_path(run_dir) == run_dir / "report.html"


def test_physical_agibot_pilot_report_uses_default_robot_map_12_artifact(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    run_result = run_physical_agibot_cleanup_pilot(
        run_dir=tmp_path / "run",
        context_json=ROBOT_MAP_12_CONTEXT_FIXTURE,
        **_sdk_kwargs(),
        waypoint_id="central_floor_scan",
    )

    run_dir = tmp_path / "run"
    metric_map = agent_view_module.base_metric_map(run_result["agent_view"])
    bundle = run_result["nav2_map_bundle"]
    report_text = (run_dir / "report.html").read_text(encoding="utf-8")

    assert metric_map["map_id"] == "agibot-robot-map-12"
    assert metric_map["occupancy_grid_artifact"] == "map_artifacts/occupancy.pgm"
    assert metric_map["map_preview_artifact"] == "map_artifacts/map_preview.png"
    assert bundle["environment_id"] == "agibot-robot-map-12"
    assert bundle["source_bundle_root"] == str(ROBOT_MAP_12_ARTIFACT)
    assert bundle["source_provenance"] == "agibot_gdk_map_artifact"
    assert (run_dir / "map_bundle" / "map.pgm").stat().st_size > 600_000
    assert (run_dir / "map_bundle" / "preview.png").is_file()
    assert not (run_dir / "map_bundle" / "report_static_navigation_map.png").exists()
    assert "agibot-robot-map-12" in report_text


def test_agibot_adapter_resolves_public_navigation_tool_family(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")
    adapter = AgibotSDKRunnerAdapter(
        context_json=context_path,
        run_dir=tmp_path / "run",
        **_sdk_kwargs(),
    )

    room_nav = adapter.navigate_to_room(room_id="living_room")
    candidate_nav = adapter.navigate_to_visual_candidate(
        source_observation_id="agibot_observe_001",
        candidate_id="candidate_001",
        target_fixture_id="sofa",
    )
    object_nav = adapter.navigate_to_object(object_id="observed_unknown")

    assert room_nav["tool"] == "navigate_to_room"
    assert room_nav["room_id"] == "living_room"
    assert room_nav["waypoint_id"] == "wp_sofa_front"
    assert room_nav["navigation_status"] == "dry_run_not_executed"
    assert candidate_nav["tool"] == "navigate_to_visual_candidate"
    assert candidate_nav["source_observation_id"] == "agibot_observe_001"
    assert candidate_nav["target_fixture_id"] == "sofa"
    assert candidate_nav["waypoint_id"] == "wp_sofa_front"
    assert candidate_nav["bounded_local_nudge"]["agent_facing_tool"] is False
    assert candidate_nav["bounded_local_nudge"]["enabled"] is False
    assert candidate_nav["bounded_local_nudge"]["max_distance_m"] == 0.25
    assert candidate_nav["bounded_local_nudge"]["max_yaw_rad"] == 0.35
    assert candidate_nav["bounded_local_nudge"]["timeout_s"] == 3.0
    assert candidate_nav["bounded_local_nudge"]["operator_config_required"] is True
    assert "simple obstacle stop" in candidate_nav["bounded_local_nudge"]["safety_model"]
    assert object_nav["tool"] == "navigate_to_object"
    assert object_nav["status"] == "blocked_capability"
    assert object_nav["failure_type"] == "object_not_mapped_to_public_waypoint"


def test_agibot_bounded_local_nudge_uses_operator_config_with_conservative_caps(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    context = _completed_context()
    context["operator_bounded_local_nudge"] = {
        "operator_configured": True,
        "max_distance_m": 0.12,
        "max_yaw_rad": 0.2,
        "timeout_s": 1.5,
        "source": "operator_safety_review",
    }
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    adapter = AgibotSDKRunnerAdapter(
        context_json=context_path,
        run_dir=tmp_path / "run",
        **_sdk_kwargs(),
    )

    candidate_nav = adapter.navigate_to_visual_candidate(
        source_observation_id="agibot_observe_001",
        target_fixture_id="sofa",
    )
    nudge = candidate_nav["bounded_local_nudge"]

    assert nudge["enabled"] is False
    assert nudge["agent_facing_tool"] is False
    assert nudge["operator_config_required"] is True
    assert nudge["operator_config_present"] is True
    assert nudge["operator_config_valid"] is True
    assert nudge["operator_config_source"] == "operator_safety_review"
    assert nudge["max_distance_m"] == 0.12
    assert nudge["max_yaw_rad"] == 0.2
    assert nudge["timeout_s"] == 1.5


def test_agibot_bounded_local_nudge_rejects_unconfirmed_or_loose_operator_config(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    context = _completed_context()
    context["operator_bounded_local_nudge"] = {
        "operator_configured": True,
        "max_distance_m": 0.5,
        "max_yaw_rad": 0.5,
        "timeout_s": 5.0,
    }
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    adapter = AgibotSDKRunnerAdapter(
        context_json=context_path,
        run_dir=tmp_path / "run",
        **_sdk_kwargs(),
    )

    candidate_nav = adapter.navigate_to_visual_candidate(
        source_observation_id="agibot_observe_001",
        target_fixture_id="sofa",
    )
    nudge = candidate_nav["bounded_local_nudge"]

    assert nudge["enabled"] is False
    assert nudge["operator_config_present"] is True
    assert nudge["operator_config_valid"] is False
    assert nudge["max_distance_m"] == 0.25
    assert nudge["max_yaw_rad"] == 0.35
    assert nudge["timeout_s"] == 3.0
    assert "conservative defaults" in nudge["config_reason"]


def test_agibot_map_build_mcp_records_agent_driven_public_trace(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")
    run_dir = tmp_path / "run"
    server = _make_common_agibot_map_build_server(
        run_dir=run_dir,
        context_json=context_path,
        visual_grounding_pipeline_id="grounding-dino",
    )

    try:
        metric_map = server.call_tool("metric_map")
        with pytest.raises(ValueError, match="static_fixture_projection"):
            server.call_tool("static_fixture_projection")
        nav = server.call_tool("navigate_to_waypoint", waypoint_id="wp_sofa_front")
        observe = server.call_tool("observe")
        with pytest.raises(ValueError, match="not entitled"):
            server.call_tool("pick", object_id="observed_unknown")
        done = server.call_tool("done", reason="mocked public sweep complete")
    finally:
        server.close()

    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    runtime_map = json.loads((run_dir / "runtime_metric_map.json").read_text(encoding="utf-8"))
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report_text = (run_dir / "report.html").read_text(encoding="utf-8")

    _assert_agibot_map_build_tool_responses(metric_map, nav, observe, done)
    _assert_static_fixture_projection_artifact_only(run_result, runtime_map, trace_events)
    _assert_agibot_map_build_run_identity(run_result)
    _assert_camera_grounding_failure_evidence(run_result)
    _assert_agibot_map_build_policy_trace(run_result)
    _assert_agibot_map_build_runtime_map(run_result, runtime_map)
    _assert_agibot_map_build_artifacts(run_result, trace_events, report_text)


def test_agibot_map_build_mcp_done_surfaces_corrupt_trace_source(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")
    run_dir = tmp_path / "run"
    server = _make_common_agibot_map_build_server(
        run_dir=run_dir,
        context_json=context_path,
    )

    try:
        with (run_dir / "trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("[]\n")

        response = server.call_tool("done", reason="source validation probe")
    finally:
        server.close()

    assert response["ok"] is False
    assert response["status"] == "error"
    assert response["error_reason"] == "exception"
    assert "MCP trace source row must contain a JSON object" in response["error"]
    assert "trace.jsonl:" in response["error"]


def test_agibot_map_build_camera_labels_call_external_grounding(
    tmp_path: Path,
) -> None:
    grounding_client = _StaticAgibotVisualGroundingClient()
    camera_path = tmp_path / "subphases" / "02-observe" / "head_color.jpg"
    camera_path.parent.mkdir(parents=True)
    Image.new("RGB", (16, 12), (120, 130, 140)).save(camera_path)

    contract = AgibotHouseholdBackend(
        run_dir=tmp_path,
        context_json=COMPLETED_CONTEXT_FIXTURE,
        **_sdk_kwargs(),
        visual_grounding_client=grounding_client,
    )
    contract._raw_fpv_observations = [
        {
            "schema": "raw_fpv_observation_v1",
            "observation_id": "agibot_observe_001",
            "source": "agibot_g2_policy_camera",
            "camera": "head_color",
            "perception_mode": "camera_model_policy",
            "status": "ok",
            "ok": True,
            "primitive_provenance": "agibot_gdk_head_color_camera",
            "image_artifacts": {"fpv": "subphases/02-observe/head_color.jpg"},
        }
    ]
    evidence = contract.camera_model_policy_payload()

    event = evidence["events"][0]
    assert grounding_client.last_request is not None
    assert grounding_client.last_request["observation_id"] == "agibot_observe_001"
    assert grounding_client.last_request["pipeline_request"]["pipeline_id"] == "grounding-dino"
    assert "static_fixture_projection" not in grounding_client.last_request
    public_hints = grounding_client.last_request["public_map_hints"]
    assert public_hints["source"] == "public_agent_view_map_evidence"
    assert public_hints["fixture_hints"][0]["fixture_id"]
    assert public_hints["private_truth_included"] is False
    assert evidence["candidate_count"] == 1
    assert evidence["visual_grounding_failure_count"] == 0
    assert event["candidate_count"] == 1
    assert event["visual_grounding_pipeline"]["status"] == "ok"


def test_agibot_map_build_server_accepts_visual_grounding_timeout(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    server = _make_common_agibot_map_build_server(
        run_dir=tmp_path / "run",
        context_json=COMPLETED_CONTEXT_FIXTURE,
        visual_grounding_pipeline_id="grounding-dino",
        visual_grounding_timeout_s=9.5,
    )

    try:
        config = getattr(server.contract.visual_grounding_client, "config", None)
        assert config is not None
        assert config.timeout_s == 9.5
    finally:
        server.close()


def test_agibot_adapter_integrates_with_shared_cleanup_mcp_contract(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    contract = AgibotHouseholdBackend(
        run_dir=tmp_path / "run",
        context_json=COMPLETED_CONTEXT_FIXTURE,
        **_sdk_kwargs(),
    )
    server = make_household_world_mcp(
        run_dir=tmp_path / "run",
        contract=contract,
        map_bundle_dir=PREBUILT_BUNDLE,
        required_capability_profiles=(
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ),
    )

    try:
        metric_map = server.call_tool("metric_map")
        static_fixture_projection = contract.static_fixture_projection()
        with pytest.raises(ValueError, match="static_fixture_projection"):
            server.call_tool("static_fixture_projection")
        nav = server.call_tool("navigate_to_waypoint", waypoint_id="wp_sofa_front")
        observe = server.call_tool("observe")
        pick = server.call_tool("pick", object_id="observed_unknown")
        done = server.call_tool("done", reason="shared Agibot cleanup MCP rehearsal")
    finally:
        server.close()

    run_dir = tmp_path / "run"
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")

    assert metric_map["schema"] == "real_robot_map_bundle_v1"
    assert static_fixture_projection["schema"] == "static_fixture_projection_v1"
    assert nav["tool"] == "navigate_to_waypoint"
    assert nav["primitive_provenance"] == "blocked_capability"
    assert observe["raw_fpv_observation"]["camera"] == "head_color"
    assert pick["status"] == "blocked_capability"
    assert done["agent_driven"] is True
    assert run_result["mcp_server"] == "household_world"
    assert run_result["evidence_lane"] == "physical-robot-evidence"
    assert run_result["evidence_lane_metadata"]["evidence_lane"] == "physical-robot-evidence"
    assert run_result["backend"] == AGIBOT_SDK_RUNNER_BACKEND
    assert run_result["backend_variant"] == "agibot_gdk"
    assert (
        agent_view_module.policy_view(run_result["agent_view"])["policy_observation_camera"]
        == "head_color"
    )
    assert run_result["manipulation_evidence"]["status"] == "blocked_capability"
    assert run_result["real_robot_readiness"]["backend_variant"] == "agibot_gdk"
    assert run_result["real_robot_readiness"]["physical_cleanup_ready"] is False
    assert run_result["requested_generated_mess_count"] == 0
    assert "final_locations" not in done
    assert "final_containment" not in done
    assert run_result["final_locations"] == {}
    assert run_result["final_containment"] == {}
    assert "scene_objects" not in trace_text


def test_physical_agibot_real_movement_requires_operator_gates(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")

    run_result = run_physical_agibot_cleanup_pilot(
        run_dir=tmp_path / "run",
        context_json=context_path,
        **_sdk_kwargs(),
        real_movement_enabled=True,
    )

    readiness = run_result["real_robot_readiness"]
    pilot = run_result["physical_agibot_pilot"]
    runner = run_result["agibot_sdk_runner"]

    assert readiness["movement_enabled"] is True
    assert readiness["operator_localization_gate"]["status"] == "missing"
    assert readiness["operator_run_enablement_gate"]["status"] == "missing"
    assert readiness["human_takeover_stop"] is True
    assert pilot["observation"]["failure_type"] == "operator_localization_gate_not_confirmed"
    assert pilot["navigation_attempt"]["failure_type"] == "operator_localization_gate_not_confirmed"
    assert [item["stage"] for item in runner["subphase_reports"]] == ["agent_view_export"]
    assert "navigate_to_room" in runner["public_tool_boundary"]
    assert "navigate_to_visual_candidate" in runner["public_tool_boundary"]


def test_physical_agibot_human_takeover_stop_covers_runtime_navigation_failures() -> None:
    assert gates.human_takeover_stop_required(
        {},
        {"failure_type": "operator_run_enablement_gate_not_confirmed"},
    )
    assert gates.human_takeover_stop_required({}, {"failure_type": "timeout"})
    assert gates.human_takeover_stop_required({}, {"failure_type": "pnc_failed"})
    assert gates.human_takeover_stop_required({}, {"failure_type": "normal_navi_exception"})
    assert gates.human_takeover_stop_required({}, {"failure_type": "gdk_localization_not_ready"})
    assert gates.human_takeover_stop_required({}, {"failure_type": "map_mismatch"})
    assert gates.human_takeover_stop_required({}, {"failure_type": "bounded_local_nudge_failed"})
    assert not gates.human_takeover_stop_required(
        {},
        {"failure_type": "real_movement_not_enabled"},
    )
    assert not gates.human_takeover_stop_required(
        {},
        {"failure_type": "waypoint_not_pnc_verified"},
    )


def test_physical_agibot_localization_gate_enforces_optional_thresholds() -> None:
    confirmed = gates.operator_localization_gate(
        {
            "operator_localization_gate": {
                "selected_map_confirmed": True,
                "g02_pad_relocalized": True,
                "localization_ready": True,
                "localization_confidence": 0.92,
                "min_localization_confidence": 0.9,
                "localization_state": "localized",
                "accepted_localization_states": ["localized", "tracking"],
            }
        }
    )
    low_confidence = gates.operator_localization_gate(
        {
            "operator_localization_gate": {
                "selected_map_confirmed": True,
                "g02_pad_relocalized": True,
                "localization_ready": True,
                "localization_confidence": 0.7,
                "min_localization_confidence": 0.9,
                "localization_state": "localized",
                "accepted_localization_states": ["localized"],
            }
        }
    )
    wrong_state = gates.operator_localization_gate(
        {
            "operator_localization_gate": {
                "selected_map_confirmed": True,
                "g02_pad_relocalized": True,
                "localization_ready": True,
                "localization_confidence": 0.95,
                "min_localization_confidence": 0.9,
                "localization_state": "lost",
                "accepted_localization_states": ["localized"],
            }
        }
    )

    assert confirmed["ok"] is True
    assert confirmed["localization_confidence_ok"] is True
    assert confirmed["localization_state_ok"] is True
    assert confirmed["accepted_localization_states"] == ["localized", "tracking"]
    assert low_confidence["ok"] is False
    assert low_confidence["localization_confidence_ok"] is False
    assert low_confidence["localization_state_ok"] is True
    assert wrong_state["ok"] is False
    assert wrong_state["localization_confidence_ok"] is True
    assert wrong_state["localization_state_ok"] is False


def _completed_context() -> dict:
    return json.loads(COMPLETED_CONTEXT_FIXTURE.read_text(encoding="utf-8"))


class _StaticAgibotVisualGroundingClient:
    pipeline_id = "grounding-dino"

    def __init__(self) -> None:
        self.last_request: dict | None = None

    def request_candidates(self, request: dict) -> dict:
        self.last_request = request
        return {
            "schema": "visual_grounding_response_v1",
            "status": "ok",
            "pipeline": {
                "pipeline_id": self.pipeline_id,
                "stages": [
                    {
                        "stage": "fake_detector",
                        "producer_id": self.pipeline_id,
                        "model_id": "fake",
                        "status": "ok",
                        "latency_ms": 1,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "dish",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.8,
                }
            ],
        }
