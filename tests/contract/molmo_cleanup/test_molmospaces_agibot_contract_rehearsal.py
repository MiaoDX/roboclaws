from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_contract_rehearsal import (
    BLOCKED_MANIPULATION_TOOLS,
    CLEANUP_ACTION_CONFIDENCE_LAYER,
    CONFIDENCE_LAYER,
    EXECUTION_BACKEND,
    NAVIGATION_PROVENANCE,
    PRE_HARDWARE_CONFIDENCE_LAYER,
    REHEARSAL_MODE_CLEANUP_ACTIONS,
    RUNTIME_FIXTURE,
    run_molmospaces_agibot_contract_rehearsal,
    run_molmospaces_agibot_prehardware_rehearsal,
)
from roboclaws.mcp.profiles import HOUSEHOLD_MANIPULATION_PROFILE

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "molmo_cleanup" / ("run_molmospaces_agibot_contract_rehearsal.py")
ROBOT_MAP_9_ARTIFACT = REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / "robot_map_9"
ROBOT_MAP_9_CONTEXT = REPO_ROOT / "tests" / "fixtures" / "agibot_robot_map_9_context.completed.json"


def _require_robot_map_9_artifact() -> None:
    if not (ROBOT_MAP_9_ARTIFACT / "source.json").is_file():
        pytest.skip("Agibot robot_map_9 artifact is unavailable in this checkout")


def _assert_static_fixture_projection_artifact_only(run_dir: Path, run_result: dict) -> None:
    assert [item["stage"] for item in run_result["agibot_sdk_runner"]["subphase_reports"]] == [
        "agent_view_export",
        "observe",
        "navigate_waypoint",
        "blocked_manipulation",
    ]
    assert (run_dir / "preflight" / "static_fixture_projection.json").is_file()
    runner_task_input = json.loads(
        (run_dir / "preflight" / "runner_task_input.json").read_text(encoding="utf-8")
    )
    trace_events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "static_fixture_projection" not in runner_task_input["public_tool_sequence"]
    assert (
        "static_fixture_projection" not in runner_task_input["stage_mapping"]["agent_view_export"]
    )
    assert not any(event.get("tool") == "static_fixture_projection" for event in trace_events)


def _assert_contract_rehearsal_artifacts(run_dir: Path) -> None:
    for relpath in (
        "preflight/agent_view.json",
        "preflight/metric_map.json",
        "preflight/static_fixture_projection.json",
        "preflight/scene_identity.json",
        "preflight/molmospaces_metric_map.png",
        "preflight/waypoint_sequence.json",
        "preflight/runner_task_input.json",
        "runtime/observation.json",
        "runtime/navigation.json",
        "runtime/blocked_manipulation.json",
        "runtime/runtime_export.json",
        "runtime/policy_observation.png",
        "subphases/01-agent-view/report.html",
        "subphases/02-observe/report.html",
        "subphases/03-navigate-waypoint/report.html",
        "subphases/04-blocked-manipulation/report.html",
    ):
        assert (run_dir / relpath).is_file(), relpath


def _read_contract_rehearsal_outputs(run_dir: Path) -> tuple[dict, dict, str, str]:
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    runtime_export = json.loads(
        (run_dir / "runtime" / "runtime_export.json").read_text(encoding="utf-8")
    )
    report_text = (run_dir / "report.html").read_text(encoding="utf-8")
    serialized = json.dumps(run_result, sort_keys=True)
    return run_result, runtime_export, report_text, serialized


def _assert_fixture_contract_rehearsal_identity(result: dict, run_result: dict) -> None:
    assert result["confidence_layer"] == CONFIDENCE_LAYER
    assert run_result["report_title"] == CONFIDENCE_LAYER
    assert run_result["evidence_lane"] == "world-public-labels"
    assert run_result["simulated"] is True
    assert run_result["physical_robot"] is False
    assert run_result["execution_backend"] == EXECUTION_BACKEND
    assert run_result["navigation_backend"] == EXECUTION_BACKEND
    assert run_result["primitive_provenance"] == NAVIGATION_PROVENANCE
    assert run_result["agibot_sdk_runner"]["runtime"] == RUNTIME_FIXTURE
    assert run_result["agibot_sdk_runner"]["gdk_imported_by_roboclaws"] is False
    assert run_result["agibot_sdk_runner"]["real_movement_enabled"] is False
    assert run_result["molmospaces_agibot_contract_rehearsal"]["physical_robot"] is False
    assert run_result["molmospaces_scene"]["runtime"] == RUNTIME_FIXTURE
    assert run_result["molmospaces_scene"]["scene_source"] == "deterministic_fixture_projection"
    assert run_result["molmospaces_scene"]["scenario_id"] == "molmo-cleanup-default-7"


def _assert_no_active_gdk_navigation_claim(run_result: dict) -> None:
    assert run_result["agibot_sdk_runner"]["gdk_imported_by_roboclaws"] is False
    assert run_result["agibot_sdk_runner"]["real_movement_enabled"] is False
    assert run_result["agibot_sdk_runner"].get("primitive_provenance", "") != (
        "agibot_gdk_normal_navi"
    )
    assert run_result["primitive_provenance"] != "agibot_gdk_normal_navi"
    assert (
        run_result["molmospaces_agibot_contract_rehearsal"]["navigation_primitive_provenance"]
        != "agibot_gdk_normal_navi"
    )
    assert not any(
        item.get("tool_response", {}).get("primitive_provenance") == "agibot_gdk_normal_navi"
        for item in run_result["agibot_sdk_runner"]["subphase_reports"]
    )


def test_molmospaces_agibot_contract_rehearsal_writes_simulated_report(
    tmp_path: Path,
) -> None:
    sys.modules.pop("agibot_gdk", None)

    result = run_molmospaces_agibot_contract_rehearsal(run_dir=tmp_path / "run")

    run_dir = tmp_path / "run"
    run_result, runtime_export, report_text, serialized = _read_contract_rehearsal_outputs(run_dir)

    _assert_fixture_contract_rehearsal_identity(result, run_result)
    assert runtime_export["simulated"] is True
    assert runtime_export["physical_robot"] is False
    assert runtime_export["observation"]["ok"] is True
    assert runtime_export["navigation"]["navigation_status"] == "succeeded"
    assert runtime_export["navigation"]["navigation_backend"] == EXECUTION_BACKEND
    assert [item["tool"] for item in runtime_export["blocked_manipulation_results"]] == list(
        BLOCKED_MANIPULATION_TOOLS
    )
    capabilities = agent_view_module.capabilities(run_result["agent_view"])
    blocked_details = {item["name"]: item for item in capabilities["blocked_capability_details"]}
    assert set(blocked_details) == set(BLOCKED_MANIPULATION_TOOLS)
    assert blocked_details["pick"]["source_profile_id"] == HOUSEHOLD_MANIPULATION_PROFILE
    assert all(
        item["status"] == "blocked_capability"
        for item in runtime_export["blocked_manipulation_results"]
    )
    _assert_static_fixture_projection_artifact_only(run_dir, run_result)
    _assert_contract_rehearsal_artifacts(run_dir)

    assert "MolmoSpaces Agibot Contract Rehearsal" in report_text
    assert "MolmoSpaces Scene &amp; Map" in report_text
    assert "deterministic_fixture_projection" in report_text
    assert "molmo-cleanup-default-7" in report_text
    assert "preflight/molmospaces_metric_map.png" in report_text
    assert "CI-safe fixture runtime" in report_text
    assert "AgiBot-Shaped Sim Evidence" in report_text
    assert "MolmoSpaces contract rehearsal" in report_text
    assert "not Agibot Map Visual Dry Run" in report_text
    assert "not Agibot SDK Dry Run" in report_text
    assert "semantic cleanup mock evidence" in report_text
    assert "real Agibot GDK execution" in report_text
    assert "blocked_capability" in report_text
    assert "pick, place, place_inside, open_receptacle, close_receptacle" in report_text
    assert "Raw FPV Observations" in report_text
    assert "No semantic cleanup actions recorded" in report_text
    assert "source_agibot_map" not in serialized
    assert "current_agibot_map" not in serialized
    assert "agibot_gdk_normal_navi" not in report_text
    _assert_no_active_gdk_navigation_claim(run_result)
    assert "agibot_gdk" not in sys.modules


def test_molmospaces_agibot_contract_rehearsal_cli_runs_without_gdk(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "cli-run"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-dir",
            str(run_dir),
            "--runtime",
            RUNTIME_FIXTURE,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    summary = json.loads(completed.stdout)
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))

    assert summary["confidence_layer"] == CONFIDENCE_LAYER
    assert summary["simulated"] is True
    assert summary["physical_robot"] is False
    assert Path(summary["report"]).is_file()
    assert run_result["agibot_sdk_runner"]["gdk_imported_by_roboclaws"] is False
    assert run_result["execution_backend"] == EXECUTION_BACKEND
    _assert_no_active_gdk_navigation_claim(run_result)


def test_molmospaces_agibot_backend_records_old_map_as_reference_only(
    tmp_path: Path,
) -> None:
    _require_robot_map_9_artifact()
    run_dir = tmp_path / "robot-map-9-reference"

    result = run_molmospaces_agibot_contract_rehearsal(
        run_dir=run_dir,
        context_json=ROBOT_MAP_9_CONTEXT,
        agibot_map_artifact_dir=ROBOT_MAP_9_ARTIFACT,
    )

    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    reference = json.loads(
        (run_dir / "preflight" / "agibot_map_reference.json").read_text(encoding="utf-8")
    )

    assert result["backend"] == "agibot_molmospaces_sim"
    assert run_result["backend"] == "agibot_molmospaces_sim"
    assert run_result["backend_variant"] == EXECUTION_BACKEND
    assert run_result["simulated"] is True
    assert run_result["physical_robot"] is False
    assert reference["status"] == "referenced_for_contract_only"
    assert reference["context_json"] == str(ROBOT_MAP_9_CONTEXT)
    assert reference["environment_id"] == "agibot-robot-map-9"
    assert reference["agibot_map_artifact_dir"] == str(ROBOT_MAP_9_ARTIFACT)
    assert reference["agibot_map_artifact_present"] is True
    assert reference["used_as_scene_source"] is False
    assert reference["used_for_navigation_execution"] is False
    assert run_result["agibot_map_reference"] == reference
    assert run_result["molmospaces_scene"]["scene_source"] == "deterministic_fixture_projection"
    assert run_result["molmospaces_agibot_contract_rehearsal"]["agibot_map_reference"] == (
        "preflight/agibot_map_reference.json"
    )


def test_molmospaces_agibot_cleanup_action_rehearsal_records_simulated_substeps(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "cleanup-actions"

    result = run_molmospaces_agibot_contract_rehearsal(
        run_dir=run_dir,
        rehearsal_mode=REHEARSAL_MODE_CLEANUP_ACTIONS,
        cleanup_object_count=2,
    )

    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    runtime_export = json.loads(
        (run_dir / "runtime" / "runtime_export.json").read_text(encoding="utf-8")
    )
    cleanup_actions = json.loads(
        (run_dir / "runtime" / "cleanup_actions.json").read_text(encoding="utf-8")
    )
    report_text = (run_dir / "report.html").read_text(encoding="utf-8")

    assert result["report_title"] == CLEANUP_ACTION_CONFIDENCE_LAYER
    assert run_result["rehearsal_mode"] == REHEARSAL_MODE_CLEANUP_ACTIONS
    assert run_result["simulated"] is True
    assert run_result["physical_robot"] is False
    assert run_result["execution_backend"] == EXECUTION_BACKEND
    assert run_result["primitive_provenance"] == "api_semantic"
    assert run_result["manipulation_evidence"]["planner_backed"] is False
    assert run_result["manipulation_evidence"]["physical_robot"] is False
    assert run_result["cleanup_primitive_evidence"]["planner_backed"] is False
    assert cleanup_actions["attempted_object_count"] == 2
    assert cleanup_actions["completed_object_count"] == 2
    assert runtime_export["rehearsal_mode"] == REHEARSAL_MODE_CLEANUP_ACTIONS
    assert runtime_export["attempted_object_count"] == 2
    assert runtime_export["completed_object_count"] == 2
    assert runtime_export["semantic_substeps"]

    phases = [
        step["phase"]
        for item in runtime_export["semantic_substeps"]
        for step in item.get("steps", [])
    ]
    assert "pick" in phases
    assert {"place", "place_inside"} & set(phases)
    assert run_result["final_locations"]
    for target in cleanup_actions["selected_targets"]:
        object_id = target["internal_object_id"]
        assert run_result["final_locations"][object_id]

    assert (run_dir / "runtime" / "cleanup_actions.json").is_file()
    assert (run_dir / "subphases" / "04-cleanup-actions" / "report.html").is_file()
    assert CLEANUP_ACTION_CONFIDENCE_LAYER in report_text
    assert "api_semantic" in report_text
    assert "No semantic cleanup actions recorded" not in report_text
    assert "agibot_gdk_normal_navi" not in report_text
    _assert_no_active_gdk_navigation_claim(run_result)


def test_agibot_molmospaces_prehardware_map_build_starts_from_base_metric_map(
    tmp_path: Path,
) -> None:
    _require_robot_map_9_artifact()
    run_dir = tmp_path / "prehardware-map-build"

    result = run_molmospaces_agibot_prehardware_rehearsal(
        run_dir=run_dir,
        intent="map-build",
        profile="camera-grounded-labels",
        generated_mess_count=5,
        camera_labeler="grounding-dino",
        context_json=ROBOT_MAP_9_CONTEXT,
        agibot_map_artifact_dir=ROBOT_MAP_9_ARTIFACT,
    )

    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    runtime_metric_map = json.loads(
        (run_dir / "runtime_metric_map.json").read_text(encoding="utf-8")
    )
    runtime_export = json.loads(
        (run_dir / "runtime" / "runtime_export.json").read_text(encoding="utf-8")
    )
    agent_view = json.loads((run_dir / "agent_view.json").read_text(encoding="utf-8"))

    assert result["backend"] == "agibot_molmospaces_sim"
    assert run_result["confidence_layer"] == PRE_HARDWARE_CONFIDENCE_LAYER
    assert run_result["task_name"] == "household-world"
    assert run_result["task_intent"] == "map-build"
    assert run_result["cleanup_actions_disabled"] is True
    assert run_result["map_build_mode"] is True
    assert "map_mode" not in run_result
    assert run_result["perception_mode"] == "camera_model_policy"
    assert run_result["visual_grounding_pipeline_id"] == "grounding-dino"
    assert run_result["simulated"] is True
    assert run_result["physical_robot"] is False
    assert "minimal_map_mode" not in runtime_metric_map
    assert runtime_metric_map["source_map_mutated"] is False
    assert runtime_metric_map["generated_exploration_candidates"]
    assert runtime_metric_map["public_semantic_anchors"]
    assert agent_view_module.base_metric_map(agent_view)["rooms"] == []
    assert agent_view_module.base_metric_map(agent_view)["inspection_waypoints"]
    assert agent_view_module.forbidden_private_fields_absent(agent_view) is True
    assert runtime_export["base_metric_map_start"] is True
    assert runtime_export["online_map_build"] is True
    assert runtime_export["cleanup_actions_included"] is False
    assert runtime_export["runtime_metric_map_summary"]["base_metric_map_enabled"] is True
    assert runtime_export["runtime_metric_map_summary"]["source_map_mutated"] is False
    reference = run_result["agibot_map_reference"]
    assert reference["used_as_scene_source"] is False
    assert reference["used_for_navigation_execution"] is False
    assert (run_dir / "report.html").is_file()


def test_agibot_molmospaces_prehardware_cleanup_uses_same_base_metric_map(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "prehardware-cleanup"

    result = run_molmospaces_agibot_prehardware_rehearsal(
        run_dir=run_dir,
        intent="cleanup",
        profile="camera-raw-fpv",
        generated_mess_count=5,
    )

    runtime_metric_map = json.loads(
        (run_dir / "runtime_metric_map.json").read_text(encoding="utf-8")
    )
    runtime_export = json.loads(
        (run_dir / "runtime" / "runtime_export.json").read_text(encoding="utf-8")
    )

    assert result["backend"] == "agibot_molmospaces_sim"
    assert result["confidence_layer"] == PRE_HARDWARE_CONFIDENCE_LAYER
    assert result["task_name"] == "household-world"
    assert result["task_intent"] == "cleanup"
    assert result["cleanup_actions_disabled"] is False
    assert result["map_build_mode"] is False
    assert "map_mode" not in result
    assert result["perception_mode"] == "raw_fpv_only"
    assert "minimal_map_mode" not in runtime_metric_map
    assert runtime_metric_map["source_map_mutated"] is False
    assert runtime_export["cleanup_actions_included"] is True
    assert runtime_export["runtime_metric_map_summary"]["base_metric_map_enabled"] is True
    assert result["semantic_substeps"]
