from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.planner_proof_results import proof_result_summary_from_commands

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_planner_proof_bundle_from_requests.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_molmo_planner_proof_bundle_from_requests",
        SCRIPT_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_writes_dry_run_manifest_and_report_from_inline_requests(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps(
            {
                "seed": 7,
                "backend": "api_semantic_synthetic",
                "static_fixture_projection_mode": "room_only",
                "perception_mode": "visible_object_detections",
                "requested_generated_mess_count": 10,
                "planner_proof_requests": _proof_requests(),
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=Path("torch_ext"),
        rby1m_curobo_memory_profile="low",
        task_sampler_robot_placement_profile="relaxed",
    )

    manifest = result["manifest"]
    assert result["status"] == "dry_run"
    _assert_inline_dry_run_manifest(manifest)
    _assert_inline_dry_run_command(manifest["commands"][0])
    _assert_inline_dry_run_artifacts(result)


def _assert_inline_dry_run_manifest(manifest: dict[str, object]) -> None:
    assert manifest["schema"] == "planner_cleanup_proof_bundle_run_manifest_v1"
    assert manifest["report"].endswith("report.html")
    assert manifest["proof_request_count"] == 1
    assert manifest["ready_request_count"] == 1
    assert manifest["command_count"] == 1
    assert manifest["proof_execution_horizon"]["schema"] == (
        "planner_cleanup_proof_execution_horizon_v1"
    )
    assert manifest["proof_execution_horizon"]["status"] == "aligned"
    assert manifest["proof_execution_horizon"]["command_steps"] == 2
    assert manifest["proof_execution_horizon"]["command_quality_target"] == "multi_step_motion"
    assert manifest["proof_execution_horizon"]["prior_covered_min_proof_steps"] == 1
    assert manifest["proof_request_selection"]["mode"] == "all_ready"
    assert manifest["proof_request_selection"]["selected_request_ids"] == ["proof_001"]
    assert manifest["commands"][0]["report"].endswith("report.html")
    assert manifest["planner_scene"]["scene_xml"] == "/tmp/molmospaces-scene.xml"
    assert manifest["proof_result_summary"]["expected_count"] == 1
    assert manifest["proof_result_summary"]["results"][0]["task_feasibility_status"] == "not_run"


def _assert_inline_dry_run_command(command_item: dict[str, object]) -> None:
    command = command_item["command"]
    assert command_item["tools"] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]
    assert command_item["semantic_subphases"] == [
        {"phase": "navigate_to_object", "label": "nav", "detail": "object"},
        {"phase": "pick", "label": "pick", "detail": "object"},
        {"phase": "navigate_to_receptacle", "label": "nav", "detail": "target"},
        {"phase": "place", "label": "place", "detail": "surface"},
    ]
    assert command[command.index("--cleanup-tools") + 1] == (
        "navigate_to_object,pick,navigate_to_receptacle,place"
    )
    assert command[:2] == ["python", "probe.py"]
    assert "--cleanup-object-id" in command
    assert "observed_001" in command
    assert "--cleanup-planner-target-receptacle-id" in command
    assert "sink/body" in command
    assert "--cleanup-scene-xml" in command
    assert "/tmp/molmospaces-scene.xml" in command
    assert "--task-sampler-robot-placement-profile" in command
    assert "relaxed" in command


def _assert_inline_dry_run_artifacts(result: dict[str, object]) -> None:
    assert Path(result["manifest_path"]).is_file()
    assert Path(result["report_path"]).is_file()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Planner Proof Bundle Runner" in report
    assert "Proof Execution Horizon" in report
    assert "multi_step_motion" in report
    assert "Semantic subphases" in report
    assert "navigate_to_object" in report
    assert "surface / place" in report
    assert "Proof Request Selection" in report
    assert "Proof Probe Commands" in report
    assert "Proof Probe Results" in report
    assert "not_run" in report
    assert "Cleanup Rerun Command" in report
    assert "observed_001" in report
    assert "--cleanup-object-id" in report
    assert "sink/body" in report
    assert "/tmp/molmospaces-scene.xml" in report


def test_runner_filters_to_requested_request_ids(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    proof_requests = _proof_requests()
    proof_requests["request_count"] = 2
    proof_requests["ready_count"] = 2
    proof_requests["requests"].append(
        {
            "request_id": "proof_002",
            "ready": True,
            "object_id": "observed_002",
            "target_receptacle_id": "shelf_01",
            "source_receptacle_id": "counter_01",
            "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
            "planner_probe_args": {
                "--cleanup-object-id": "observed_002",
                "--cleanup-target-receptacle-id": "shelf_01",
                "--cleanup-source-receptacle-id": "counter_01",
                "--cleanup-tools": "navigate_to_object,pick,navigate_to_receptacle,place",
                "--cleanup-planner-object-id": "pickup/body2",
                "--cleanup-planner-target-receptacle-id": "shelf/body",
            },
        }
    )
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": proof_requests}),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        request_ids=["proof_002"],
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    assert selection["mode"] == "request_id_filter"
    assert selection["ready_request_count"] == 2
    assert selection["candidate_request_count"] == 1
    assert selection["request_filter"]["requested_request_ids"] == ["proof_002"]
    assert selection["request_filter"]["matched_request_ids"] == ["proof_002"]
    assert selection["selected_request_ids"] == ["proof_002"]
    assert manifest["command_count"] == 1
    assert manifest["commands"][0]["request_id"] == "proof_002"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Request ID Filter" in report
    assert "proof_002" in report
    assert "Semantic subphases" in report


def test_runner_excludes_prior_task_feasibility_blocked_requests(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    requests["request_count"] = 2
    requests["ready_count"] = 2
    requests["requests"] = [
        requests["requests"][0],
        {
            "request_id": "proof_002",
            "ready": True,
            "object_id": "observed_002",
            "target_receptacle_id": "shelf_01",
            "source_receptacle_id": "table_01",
            "planner_probe_args": {
                "--cleanup-object-id": "observed_002",
                "--cleanup-target-receptacle-id": "shelf_01",
                "--cleanup-planner-object-id": "book/body",
                "--cleanup-planner-target-receptacle-id": "shelf/body",
            },
        },
    ]
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}), encoding="utf-8"
    )
    prior = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior.parent.mkdir()
    prior.write_text(
        json.dumps(
            {
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "run_result": str(tmp_path / "prior-proof" / "run_result.json"),
                            "report": str(tmp_path / "prior-proof" / "report.html"),
                            "stdout": str(tmp_path / "prior-proof" / "stdout.txt"),
                            "stderr": str(tmp_path / "prior-proof" / "stderr.txt"),
                            "last_worker_stage": "worker_exception",
                            "execution_attempted": True,
                            "blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
    )

    selection = result["manifest"]["proof_request_selection"]
    assert selection["mode"] == "exclude_task_feasibility_blocked"
    assert selection["selected_request_ids"] == ["proof_002"]
    assert selection["excluded_requests"][0]["request_id"] == "proof_001"
    assert selection["excluded_requests"][0]["prior_report"] == str(
        tmp_path / "prior-proof" / "report.html"
    )
    assert selection["target_feasibility_blocker_count"] == 1
    assert selection["target_feasibility_blockers"][0]["kind"] == "source_request"
    assert selection["target_feasibility_blockers"][0]["prior_report"] == str(
        tmp_path / "prior-proof" / "report.html"
    )
    assert result["manifest"]["command_count"] == 1
    assert result["manifest"]["commands"][0]["request_id"] == "proof_002"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Proof Request Selection" in report
    assert "Target Feasibility Blockers" in report
    assert "source_request" in report
    assert "prior_task_feasibility_blocked" in report
    assert "HouseInvalidForTask" in report
    assert str(tmp_path / "prior-proof" / "report.html") in report


def test_runner_excludes_prior_covered_requests(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    base_request = requests["requests"][0]
    requests["request_count"] = 3
    requests["ready_count"] = 3
    requests["requests"] = [
        base_request,
        {
            **base_request,
            "request_id": "proof_002",
            "object_id": "observed_002",
            "target_receptacle_id": "shelf_01",
            "planner_probe_args": {
                **base_request["planner_probe_args"],
                "--cleanup-object-id": "observed_002",
                "--cleanup-target-receptacle-id": "shelf_01",
                "--cleanup-planner-object-id": "book/body",
                "--cleanup-planner-target-receptacle-id": "shelf/body",
            },
        },
        {
            **base_request,
            "request_id": "proof_003",
            "object_id": "observed_003",
            "target_receptacle_id": "stand_01",
            "planner_probe_args": {
                **base_request["planner_probe_args"],
                "--cleanup-object-id": "observed_003",
                "--cleanup-target-receptacle-id": "stand_01",
                "--cleanup-planner-object-id": "remote/body",
                "--cleanup-planner-target-receptacle-id": "stand/body",
            },
        },
    ]
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}), encoding="utf-8"
    )
    prior = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior.parent.mkdir()
    one_step_quality = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        steps_requested=1,
        steps_executed=1,
        max_abs_qpos_delta=0.01,
    )["proof_quality"]
    prior.write_text(
        json.dumps(
            {
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001",
                            "object_id": "observed_001",
                            "target_receptacle_id": "sink_01",
                            "status": "planner_backed",
                            "task_feasibility_status": "ready",
                            "planner_backed": True,
                            "cleanup_binding_promoted": True,
                            "steps_executed": 1,
                            "max_abs_qpos_delta": 0.01,
                            "proof_quality": one_step_quality,
                            "run_result": str(tmp_path / "prior-proof-1" / "run_result.json"),
                            "report": str(tmp_path / "prior-proof-1" / "report.html"),
                        },
                        {
                            "request_id": "proof_002",
                            "object_id": "observed_002",
                            "target_receptacle_id": "shelf_01",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "task_feasibility_blocker_kind": "grasp_feasibility",
                            "task_feasibility_blocker_summary": (
                                "3 grasp failures; 1 candidate-removal calls"
                            ),
                            "run_result": str(tmp_path / "prior-proof-2" / "run_result.json"),
                            "report": str(tmp_path / "prior-proof-2" / "report.html"),
                            "blockers": [{"code": "HouseInvalidForTask"}],
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
        exclude_prior_covered=True,
    )

    selection = result["manifest"]["proof_request_selection"]
    assert selection["mode"] == "exclude_task_feasibility_blocked_and_prior_covered"
    assert selection["prior_covered_min_proof_steps"] == 1
    assert selection["selected_request_ids"] == ["proof_003"]
    assert selection["covered_request_count"] == 1
    assert [item["reason"] for item in selection["excluded_requests"]] == [
        "prior_planner_proof_covered",
        "prior_task_feasibility_blocked",
    ]
    assert result["manifest"]["command_count"] == 1
    assert result["manifest"]["commands"][0]["request_id"] == "proof_003"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Covered" in report
    assert "prior_planner_proof_covered" in report
    assert "prior_task_feasibility_blocked" in report

    strict_result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle-strict",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
        exclude_prior_covered=True,
        prior_covered_min_proof_steps=2,
    )
    strict_selection = strict_result["manifest"]["proof_request_selection"]
    assert strict_selection["prior_covered_min_proof_steps"] == 2
    assert (
        strict_result["manifest"]["proof_execution_horizon"]["prior_covered_min_proof_steps"] == 2
    )
    assert (
        strict_result["manifest"]["proof_execution_horizon"]["prior_covered_quality_floor"]
        == "multi_step_motion"
    )
    assert strict_selection["selected_request_ids"] == ["proof_001", "proof_003"]
    assert strict_selection["covered_request_count"] == 0
    assert strict_selection["selected_requests"][0]["prior_proof_quality"] == "one_step_motion"
    assert strict_result["manifest"]["command_count"] == 2
    strict_report = Path(strict_result["report_path"]).read_text(encoding="utf-8")
    assert "Coverage min steps" in strict_report
    assert "one_step_motion" in strict_report
    assert "Proof Execution Horizon" in strict_report


def test_runner_reports_misaligned_proof_execution_horizon(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=1,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        exclude_prior_covered=True,
        prior_covered_min_proof_steps=2,
    )

    horizon = result["manifest"]["proof_execution_horizon"]
    assert horizon["status"] == "command_steps_below_coverage_horizon"
    assert horizon["command_quality_target"] == "one_step_motion"
    assert horizon["prior_covered_quality_floor"] == "multi_step_motion"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "command_steps_below_coverage_horizon" in report
    assert "Probe commands request 1 steps" in report


def test_runner_marks_fallback_required_when_all_prior_requests_blocked(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    prior = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior.parent.mkdir()
    prior.write_text(
        json.dumps(
            {
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
    )

    assert result["manifest"]["command_count"] == 0
    selection = result["manifest"]["proof_request_selection"]
    assert selection["fallback_required"] is True
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Fallback required" in report
    assert "No proof requests selected" in report


def test_runner_generates_fallback_requests_from_prior_blocked_aliases(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    request = requests["requests"][0]
    request["binding"] = {
        "candidate_pickup_names": ["pickup/body", "pickup/alt", "Pickup|surface|1|1"],
        "candidate_place_receptacle_names": ["sink/body", "sink/alt", "Sink|1|2"],
    }
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}),
        encoding="utf-8",
    )
    prior = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior.parent.mkdir()
    prior.write_text(
        json.dumps(
            {
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=2,
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    assert manifest["command_count"] == 2
    assert selection["fallback_required"] is False
    assert selection["generated_fallback_request_count"] == 2
    assert manifest["commands"][0]["request_id"] == "proof_001_fallback_01"
    assert manifest["commands"][0]["object_id"] == "observed_001"
    assert manifest["commands"][0]["target_receptacle_id"] == "sink_01"
    assert "sink/alt" in manifest["commands"][0]["command"]
    assert "pickup/alt" in manifest["commands"][1]["command"]
    assert selection["fallback_generation"]["filtered_alias_count"] == 2
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Generated Fallback Requests" in report
    assert "Filtered Fallback Aliases" in report
    assert "proof_001_fallback_01" in report
    assert "Pickup|surface|1|1" in report
    assert "Sink|1|2" in report


def test_runner_discovers_runtime_aliases_from_prior_fallback_keyerrors(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    request = requests["requests"][0]
    request["target_receptacle_id"] = "shelf_01"
    request["planner_probe_args"] = {
        "--cleanup-object-id": "observed_001",
        "--cleanup-target-receptacle-id": "shelf_01",
        "--cleanup-planner-object-id": "book_beef_1_0_8",
        "--cleanup-planner-target-receptacle-id": "shelf_cafe_1_0_2",
    }
    request["binding"] = {
        "candidate_pickup_names": ["book_beef_1_0_8", "Book|surface|8|79"],
        "candidate_place_receptacle_names": ["shelf_cafe_1_0_2", "ShelvingUnit|2|3"],
    }
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}),
        encoding="utf-8",
    )
    prior = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior.parent.mkdir()
    valid_names = [
        "book_beef_1_0_8",
        "book_beef_1_1_8",
        "shelf_cafe_1_0_2",
        "shelf_cafe_1_1_2",
    ]
    prior.write_text(
        json.dumps(
            {
                "proof_request_selection": {
                    "excluded_requests": [
                        {
                            "request_id": "proof_001",
                            "prior_status": "blocked_capability",
                            "prior_task_feasibility_status": "blocked",
                            "prior_blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ]
                },
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001_fallback_01",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "cleanup_task_config": {
                                "planner_object_id": "book_beef_1_0_8",
                                "planner_target_receptacle_id": "ShelvingUnit|2|3",
                            },
                            "blockers": [
                                {
                                    "code": "KeyError",
                                    "message": (
                                        f"\"Invalid name 'ShelvingUnit|2|3'. "
                                        f'Valid names: {valid_names}"'
                                    ),
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    assert manifest["command_count"] == 1
    assert selection["selected_request_ids"] == ["proof_001_fallback_01"]
    assert selection["fallback_generation"]["discovered_alias_count"] == 1
    assert "shelf_cafe_1_1_2" in manifest["commands"][0]["command"]
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Discovered Runtime Aliases" in report
    assert "shelf_cafe_1_1_2" in report
    assert "proof_001_fallback_01" in report


def test_runner_merges_multiple_prior_manifests_for_discovery_and_filters(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    request = requests["requests"][0]
    request["target_receptacle_id"] = "shelf_01"
    request["planner_probe_args"] = {
        "--cleanup-object-id": "observed_001",
        "--cleanup-target-receptacle-id": "shelf_01",
        "--cleanup-planner-object-id": "book_beef_1_0_8",
        "--cleanup-planner-target-receptacle-id": "shelf_cafe_1_0_2",
    }
    request["binding"] = {
        "candidate_pickup_names": ["book_beef_1_0_8", "Book|surface|8|79"],
        "candidate_place_receptacle_names": ["shelf_cafe_1_0_2", "ShelvingUnit|2|3"],
    }
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}),
        encoding="utf-8",
    )

    keyerror_prior = tmp_path / "keyerror_prior" / "proof_bundle_run_manifest.json"
    keyerror_prior.parent.mkdir()
    keyerror_prior.write_text(
        json.dumps(
            {
                "proof_request_selection": {
                    "excluded_requests": [
                        {
                            "request_id": "proof_001",
                            "prior_status": "blocked_capability",
                            "prior_task_feasibility_status": "blocked",
                            "prior_blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ]
                },
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001_fallback_01",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "cleanup_task_config": {
                                "planner_object_id": "book_beef_1_0_8",
                                "planner_target_receptacle_id": "ShelvingUnit|2|3",
                            },
                            "blockers": [
                                {
                                    "code": "KeyError",
                                    "message": (
                                        "\"Invalid name 'ShelvingUnit|2|3'. "
                                        "Valid names: ['book_beef_1_0_8', "
                                        "'shelf_cafe_1_0_2', 'shelf_cafe_1_1_2']\""
                                    ),
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    failed_pair_prior = tmp_path / "failed_pair_prior" / "proof_bundle_run_manifest.json"
    failed_pair_prior.parent.mkdir()
    failed_pair_prior.write_text(
        json.dumps(
            {
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001_fallback_01",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "execution_attempted": True,
                            "last_worker_stage": "worker_exception",
                            "run_result": str(tmp_path / "prior-proof" / "run_result.json"),
                            "report": str(tmp_path / "prior-proof" / "report.html"),
                            "cleanup_task_config": {
                                "planner_object_id": "book_beef_1_0_8",
                                "planner_target_receptacle_id": "shelf_cafe_1_1_2",
                            },
                            "blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=[keyerror_prior, failed_pair_prior],
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=4,
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    fallback = selection["fallback_generation"]
    assert manifest["command_count"] == 0
    assert selection["fallback_required"] is True
    assert selection["prior_result_count"] == 2
    assert selection["target_feasibility_blocker_count"] == 2
    assert {item["kind"] for item in selection["target_feasibility_blockers"]} == {
        "source_request",
        "fallback_pair",
    }
    assert fallback["status"] == "exhausted"
    assert {item["code"] for item in fallback["exhaustion_blockers"]} == {
        "target_task_feasibility_blocked_pairs",
        "no_fallback_candidate_available",
    }
    assert fallback["discovered_alias_count"] == 1
    assert fallback["filtered_pair_count"] == 1
    assert fallback["filtered_pairs"][0]["object_alias"] == "book_beef_1_0_8"
    assert fallback["filtered_pairs"][0]["target_alias"] == "shelf_cafe_1_1_2"
    assert fallback["filtered_pairs"][0]["prior_report"] == str(
        tmp_path / "prior-proof" / "report.html"
    )
    assert fallback["filtered_pairs"][0]["last_worker_stage"] == "worker_exception"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Fallback status" in report
    assert "exhausted" in report
    assert "Fallback Exhaustion Blockers" in report
    assert "Target Feasibility Blockers" in report
    assert "source_request" in report
    assert "fallback_pair" in report
    assert "target_task_feasibility_blocked_pairs" in report
    assert "no_fallback_candidate_available" in report
    assert "shelf_cafe_1_1_2" in report
    assert "prior_task_feasibility_blocked_pair" in report
    assert str(tmp_path / "prior-proof" / "report.html") in report
    assert "worker_exception" in report


def test_runner_ingests_standalone_prior_probe_run_result_by_cleanup_pair(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    requests["requests"][0]["request_id"] = "proof_regenerated"
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}),
        encoding="utf-8",
    )
    prior_probe = tmp_path / "prior-probe" / "run_result.json"
    prior_probe.parent.mkdir()
    prior_probe.write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "artifacts": {
                    "report": "report.html",
                    "stdout": "stdout.txt",
                    "stderr": "stderr.txt",
                },
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "last_worker_stage": "worker_exception",
                    "requested_cleanup_primitive_binding": {
                        "object_id": "observed_001",
                        "target_receptacle_id": "sink_01",
                        "source_receptacle_id": "counter_01",
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "task_sampler_failure_diagnostics": {
                        "grasp_failure_count": 17,
                        "candidate_removal_count": 15,
                    },
                    "image_artifacts": {
                        "initial": "initial.png",
                        "final": "final.png",
                    },
                    "blockers": [
                        {
                            "code": "HouseInvalidForTask",
                            "message": "House invalid after grasp failures",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (prior_probe.parent / "report.html").write_text("<h1>probe</h1>", encoding="utf-8")
    (prior_probe.parent / "initial.png").write_bytes(b"initial")
    (prior_probe.parent / "final.png").write_bytes(b"final")
    (prior_probe.parent / "stdout.txt").write_text("", encoding="utf-8")
    (prior_probe.parent / "stderr.txt").write_text("", encoding="utf-8")

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_planner_probe_run_result=prior_probe,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    assert manifest["command_count"] == 0
    assert selection["selected_request_ids"] == []
    assert selection["excluded_requests"][0]["request_id"] == "proof_regenerated"
    assert selection["excluded_requests"][0]["prior_result_match_kind"] == "object_target"
    assert selection["excluded_requests"][0]["prior_run_result"] == str(prior_probe)
    assert selection["excluded_requests"][0]["prior_task_feasibility_blocker_kind"] == (
        "grasp_feasibility"
    )
    assert selection["grasp_feasibility_blocker_count"] == 1
    assert selection["fallback_generation"]["status"] == "exhausted"
    prior_summary = manifest["prior_proof_result_summary"]
    assert prior_summary["result_count"] == 1
    assert prior_summary["view_artifact_count"] == 2
    assert prior_summary["grasp_feasibility_signature_count"] == 1
    assert prior_summary["grasp_feasibility_signature_counts"][0]["subkind"] == "grasp_rejection"
    decision = manifest["grasp_feasibility_mitigation_decision"]
    assert decision["primary_route"] == "source_rotation"
    assert decision["source_rotation_state"] == "exhausted_by_prior_memory"
    summary = manifest["proof_result_summary"]
    assert summary["expected_count"] == 0
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Prior Proof Evidence" in report
    assert "Prior match" in report
    assert "object_target" in report
    assert "grasp_feasibility" in report
    assert "17 grasp failures; 15 candidate-removal calls" in report
    assert str(prior_probe.parent / "report.html") in report
    assert 'src="../prior-probe/initial.png"' in report
    assert 'src="../prior-probe/final.png"' in report
    assert str(prior_probe.parent / "initial.png") not in report
    assert str(prior_probe.parent / "final.png") not in report


def test_runner_carries_nested_prior_proof_result_summary_from_prior_manifest(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    prior_manifest = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior_manifest.parent.mkdir()
    prior_manifest.write_text(
        json.dumps(
            {
                "schema": "planner_cleanup_proof_bundle_run_manifest_v1",
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "result_count": 1,
                    "results": [
                        {
                            "request_id": "proof_unrelated",
                            "object_id": "observed_other",
                            "target_receptacle_id": "sink_other",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "run_result": str(tmp_path / "other" / "run_result.json"),
                            "report": str(tmp_path / "other" / "report.html"),
                        }
                    ],
                },
                "prior_proof_result_summary": {
                    "schema": "merged_prior_planner_proof_result_summary_v1",
                    "result_count": 1,
                    "results": [
                        {
                            "request_id": "standalone_observed_001_to_sink_01",
                            "object_id": "observed_001",
                            "target_receptacle_id": "sink_01",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "task_feasibility_blocker_kind": "grasp_feasibility",
                            "task_feasibility_blocker_summary": (
                                "17 grasp failures; 15 candidate-removal calls"
                            ),
                            "blockers": [{"code": "HouseInvalidForTask"}],
                            "run_result": str(tmp_path / "prior" / "run_result.json"),
                            "report": str(tmp_path / "prior" / "report.html"),
                        }
                    ],
                },
                "proof_request_selection": {
                    "fallback_generation": {
                        "schema": "planner_cleanup_proof_request_fallback_generation_v1",
                        "status": "exhausted",
                        "enabled": True,
                        "generated_request_count": 0,
                        "generated_requests": [],
                        "discovered_alias_count": 0,
                        "discovered_aliases": [],
                        "filtered_alias_count": 0,
                        "filtered_aliases": [],
                        "filtered_pair_count": 0,
                        "filtered_pairs": [],
                        "normalized_alias_count": 0,
                        "normalized_aliases": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior_manifest,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    assert manifest["command_count"] == 0
    assert selection["selected_request_ids"] == []
    assert selection["excluded_requests"][0]["request_id"] == "proof_001"
    assert selection["excluded_requests"][0]["prior_result_match_kind"] == "object_target"
    assert selection["excluded_requests"][0]["prior_task_feasibility_blocker_kind"] == (
        "grasp_feasibility"
    )
    assert manifest["prior_proof_result_summary"]["result_count"] == 2
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Prior Proof Evidence" in report
    assert "standalone_observed_001_to_sink_01" in report
    assert "proof_unrelated" in report


def test_runner_preserves_prior_blocker_detail_from_excluded_requests() -> None:
    runner = _load_module()

    results = runner._merged_prior_results(
        [],
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "prior_status": "blocked_capability",
                "prior_task_feasibility_status": "blocked",
                "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                "prior_task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "prior_blockers": [{"code": "HouseInvalidForTask"}],
            }
        ],
    )

    assert results[0]["object_id"] == "observed_001"
    assert results[0]["target_receptacle_id"] == "sink_01"
    assert results[0]["task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert results[0]["task_feasibility_blocker_summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )


def test_runner_summarizes_grasp_feasibility_signatures(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001"
    proof_dir.mkdir(parents=True)
    (proof_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "artifacts": {},
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "blockers": [{"code": "HouseInvalidForTask"}],
                    "task_sampler_failure_diagnostics": {
                        "robot_placement_attempt_count": 17,
                        "robot_placement_failure_count": 0,
                        "place_robot_near_call_count": 17,
                        "grasp_failure_count": 17,
                        "candidate_removal_count": 15,
                        "image_artifacts": {
                            "post_placement_attempt_001_head_camera": "planner_views/view.png"
                        },
                        "grasp_failures": [
                            {
                                "object_name": "bread_1",
                                "count_before": 0,
                                "count_after": 1,
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "fridge_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    result = summary["results"][0]
    assert result["task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert result["grasp_feasibility_signature"]["summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )
    assert summary["grasp_feasibility_signature_count"] == 1
    assert summary["grasp_feasibility_signature_counts"][0]["request_ids"] == ["proof_001"]


def test_runner_carries_prior_failed_runtime_fallback_candidates(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    requests = _proof_requests()
    request = requests["requests"][0]
    request["target_receptacle_id"] = "shelf_01"
    request["planner_probe_args"] = {
        "--cleanup-object-id": "observed_001",
        "--cleanup-target-receptacle-id": "shelf_01",
        "--cleanup-planner-object-id": "book_beef_1_0_8",
        "--cleanup-planner-target-receptacle-id": "shelf_cafe_1_0_2",
    }
    request["binding"] = {
        "candidate_pickup_names": ["book_beef_1_0_8", "Book|surface|8|79"],
        "candidate_place_receptacle_names": ["shelf_cafe_1_0_2", "ShelvingUnit|2|3"],
    }
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": requests}),
        encoding="utf-8",
    )
    prior = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior.parent.mkdir()
    prior.write_text(
        json.dumps(
            {
                "proof_request_selection": {
                    "excluded_requests": [
                        {
                            "request_id": "proof_001",
                            "prior_status": "blocked_capability",
                            "prior_task_feasibility_status": "blocked",
                            "prior_blockers": [{"code": "HouseInvalidForTask"}],
                        }
                    ],
                    "fallback_generation": {
                        "discovered_aliases": [
                            {
                                "source_request_id": "proof_001",
                                "axis": "object",
                                "alias": "book_beef_1_1_8",
                                "derived_from": "proof_001_fallback_02",
                                "invalid_alias": "Book|surface|8|79",
                                "reason": "valid_name_sibling_from_prior_keyerror",
                            },
                            {
                                "source_request_id": "proof_001",
                                "axis": "object",
                                "alias": "book_beef_1_2_8",
                                "derived_from": "proof_001_fallback_02",
                                "invalid_alias": "Book|surface|8|79",
                                "reason": "valid_name_sibling_from_prior_keyerror",
                            },
                            {
                                "source_request_id": "proof_001",
                                "axis": "target",
                                "alias": "shelf_cafe_1_1_2",
                                "derived_from": "proof_001_fallback_01",
                                "invalid_alias": "ShelvingUnit|2|3",
                                "reason": "valid_name_sibling_from_prior_keyerror",
                            },
                        ]
                    },
                },
                "proof_result_summary": {
                    "schema": "planner_cleanup_proof_result_summary_v1",
                    "results": [
                        {
                            "request_id": "proof_001_fallback_01",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "cleanup_task_config": {
                                "planner_object_id": "book_beef_1_0_8",
                                "planner_target_receptacle_id": "shelf_cafe_1_1_2",
                            },
                            "blockers": [{"code": "HouseInvalidForTask"}],
                        },
                        {
                            "request_id": "proof_001_fallback_02",
                            "status": "blocked_capability",
                            "task_feasibility_status": "blocked",
                            "cleanup_task_config": {
                                "planner_object_id": "book_beef_1_1_8",
                                "planner_target_receptacle_id": "shelf_cafe_1_0_2",
                            },
                            "blockers": [
                                {
                                    "code": "AssertionError",
                                    "message": "Object is not a root body",
                                }
                            ],
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        prior_proof_bundle_manifest=prior,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=4,
    )

    manifest = result["manifest"]
    selection = manifest["proof_request_selection"]
    assert manifest["command_count"] == 0
    assert selection["fallback_required"] is True
    assert selection["fallback_generation"]["status"] == "exhausted"
    assert selection["fallback_generation"]["filtered_pair_count"] == 1
    assert selection["fallback_generation"]["filtered_alias_count"] == 4
    assert selection["fallback_generation"]["normalized_alias_count"] == 2
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Normalized Pickup Root Aliases" in report
    assert "pickup_root_variant_normalized" in report
    assert "book_beef_1_0_8" in report
    assert "Filtered Fallback Pairs" in report
    assert "prior_task_feasibility_blocked_pair" in report
    assert "prior_non_root_body_alias" in report
    assert "not_pickup_root_body_alias" in report


def test_runner_can_add_visible_warmup_with_output_local_cache(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundle"

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=output_dir,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        warmup_rby1m_curobo=True,
    )

    manifest = result["manifest"]
    warmup = manifest["warmup"]
    shared_cache = str(output_dir / "torch_extensions")
    assert warmup["run_result"].endswith("rby1m_curobo_warmup/run_result.json")
    assert "--probe-mode" in warmup["command"]
    assert "config_import" in warmup["command"]
    assert "--torch-extensions-dir" in warmup["command"]
    assert shared_cache in warmup["command"]
    proof_command = manifest["commands"][0]["command"]
    assert "--torch-extensions-dir" in proof_command
    assert shared_cache in proof_command
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "RBY1M/CuRobo Warmup" in report
    assert "rby1m_curobo_warmup/run_result.json" in report
    assert "config_import" in report


def test_runner_executes_warmup_before_proof_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    commands_run: list[list[str]] = []

    def fake_run_command(command: list[str]) -> None:
        commands_run.append(list(command))
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        if "--cleanup-object-id" in command:
            (output_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "status": "planner_backed",
                        "manipulation_evidence": {
                            "execution_attempted": True,
                            "cleanup_primitive_binding": {
                                "object_id": "observed_001",
                                "target_receptacle_id": "sink_01",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
        else:
            (output_dir / "run_result.json").write_text(
                json.dumps({"status": "blocked_capability"}),
                encoding="utf-8",
            )
        (output_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")

    monkeypatch.setattr(runner, "_run_command", fake_run_command)

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        execute_probes=True,
        warmup_rby1m_curobo=True,
    )

    assert result["status"] == "probes_executed"
    assert len(commands_run) == 2
    assert "--probe-mode" in commands_run[0]
    assert "config_import" in commands_run[0]
    assert "--cleanup-object-id" not in commands_run[0]
    assert "--cleanup-object-id" in commands_run[1]
    shared_cache = str(tmp_path / "bundle" / "torch_extensions")
    assert shared_cache in commands_run[0]
    assert shared_cache in commands_run[1]
    assert result["manifest"]["proof_result_summary"]["planner_backed_count"] == 1


def test_runner_records_local_runtime_preflight_blocker_before_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    fake_python = tmp_path / "molmospaces-python"
    fake_python.write_text(
        "#!/bin/sh\necho \"ModuleNotFoundError: No module named 'molmo_spaces'\" >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    def fail_run_command(command: list[str]) -> None:
        raise AssertionError(f"proof command should not run after failed preflight: {command}")

    monkeypatch.setattr(runner, "_run_command", fail_run_command)

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=fake_python,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        execute_probes=True,
        warmup_rby1m_curobo=True,
    )

    manifest = result["manifest"]
    preflight = manifest["local_runtime_preflight"]
    assert result["status"] == "local_runtime_blocked"
    assert preflight["status"] == "blocked"
    assert preflight["blockers"][0]["code"] == "molmo_spaces_import_failed"
    assert manifest["proof_result_summary"]["result_count"] == 0
    assert manifest["proof_result_summary"]["results"][0]["status"] == "not_run"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Local Runtime Preflight" in report
    assert "molmo_spaces_import_failed" in report
    assert str(fake_python) in report


def test_runner_loads_request_artifact_from_run_result(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_dir = tmp_path / "cleanup"
    cleanup_dir.mkdir()
    (cleanup_dir / "planner_proof_requests.json").write_text(
        json.dumps(_proof_requests()),
        encoding="utf-8",
    )
    cleanup_run_result = cleanup_dir / "run_result.json"
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": "planner_proof_requests.json"}}),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="franka",
        probe_mode="config_import",
        steps=1,
        timeout_s=30.0,
        renderer_device_id=-1,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="none",
    )

    command = result["manifest"]["commands"][0]["command"]
    assert "--embodiment" in command
    assert "franka" in command
    assert "--probe-mode" in command
    assert "config_import" in command


def test_runner_enriches_legacy_requests_with_source_scene(tmp_path: Path) -> None:
    runner = _load_module()
    requests = dict(_proof_requests())
    requests.pop("planner_scene", None)
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps(
            {
                "backend": "molmospaces_subprocess",
                "molmospaces_runtime": {"scene_xml": "/tmp/source-scene.xml"},
                "planner_proof_requests": requests,
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
    )

    command = result["manifest"]["commands"][0]["command"]
    assert result["manifest"]["planner_scene"]["scene_xml"] == "/tmp/source-scene.xml"
    assert "--cleanup-scene-xml" in command
    assert "/tmp/source-scene.xml" in command


def test_runner_records_cleanup_rerun_artifacts_when_rerun_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps(
            {
                "seed": 7,
                "backend": "api_semantic_synthetic",
                "static_fixture_projection_mode": "room_only",
                "perception_mode": "visible_object_detections",
                "requested_generated_mess_count": 10,
                "planner_proof_requests": _proof_requests(),
            }
        ),
        encoding="utf-8",
    )
    commands_run: list[list[str]] = []

    def fake_run_command(command: list[str]) -> None:
        commands_run.append(list(command))
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        if "--cleanup-object-id" in command:
            (output_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "status": "blocked_capability",
                        "manipulation_evidence": {
                            "execution_attempted": True,
                            "blockers": [
                                {
                                    "code": "HouseInvalidForTask",
                                    "message": "robot placement failed",
                                }
                            ],
                            "requested_cleanup_primitive_binding": {
                                "planner_object_id": "pickup/body",
                                "planner_target_receptacle_id": "sink/body",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
        else:
            (output_dir / "run_result.json").write_text("{}", encoding="utf-8")
        (output_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")

    monkeypatch.setattr(runner, "_run_command", fake_run_command)

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=Path("torch_ext"),
        rby1m_curobo_memory_profile="low",
        execute_probes=True,
        rerun_cleanup=True,
        cleanup_output_dir=tmp_path / "rerun",
    )

    manifest = result["manifest"]
    assert result["status"] == "cleanup_rerun"
    assert len(commands_run) == 2
    assert commands_run[-1][:2] == ["python", "cleanup.py"]
    assert "--planner-proof-run-result" in commands_run[-1]
    cleanup_rerun = manifest["cleanup_rerun"]
    assert cleanup_rerun["output_dir"] == str(tmp_path / "rerun")
    assert cleanup_rerun["run_result"] == str(tmp_path / "rerun" / "run_result.json")
    assert cleanup_rerun["report"] == str(tmp_path / "rerun" / "report.html")
    summary = manifest["proof_result_summary"]
    assert summary["result_count"] == 1
    assert summary["task_feasibility_blocked_count"] == 1
    assert summary["results"][0]["task_feasibility_status"] == "blocked"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Proof Probe Results" in report
    assert "HouseInvalidForTask" in report
    assert "Cleanup Rerun Artifact" in report
    assert str(tmp_path / "rerun" / "run_result.json") in report


def test_runner_requires_planner_proof_requests(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "run_result.json"
    cleanup_run_result.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="planner proof requests"):
        runner.run_from_cleanup_result(
            cleanup_run_result=cleanup_run_result,
            output_dir=tmp_path / "bundle",
            runner_python=Path("python"),
            probe_script=Path("probe.py"),
            cleanup_script=Path("cleanup.py"),
            molmospaces_python=None,
            molmospaces_root=None,
            embodiment="rby1m",
            probe_mode="execute",
            steps=2,
            timeout_s=600.0,
            renderer_device_id=0,
            torch_extensions_dir=None,
            rby1m_curobo_memory_profile="low",
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("{not-json\n", "valid JSON object"),
        ("[]\n", "a JSON object"),
    ],
)
def test_runner_rejects_malformed_cleanup_run_result_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(source, encoding="utf-8")

    message = rf"cleanup run result source must contain {message}: .*run_result\.json"
    with pytest.raises(ValueError, match=message):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_rejects_non_object_inline_planner_proof_requests(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": []}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"inline planner proof requests must contain a JSON object: .*run_result\.json",
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_rejects_non_object_artifact_envelope(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(json.dumps({"artifacts": []}), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"cleanup run result artifacts must contain a JSON object: .*run_result\.json",
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_rejects_missing_declared_request_artifact(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": "missing_requests.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(
        FileNotFoundError,
        match=r"planner proof requests artifact is missing: .*missing_requests\.json",
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


@pytest.mark.parametrize("declared_source", [None, [], ""])
def test_runner_rejects_wrong_shaped_declared_request_artifact_path(
    tmp_path: Path,
    declared_source: object,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": declared_source}}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            r"planner proof requests artifact path must be a non-empty string: "
            r".*run_result\.json"
        ),
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


@pytest.mark.parametrize(
    ("source", "valid"),
    [
        ("{not-json\n", False),
        ("[]\n", True),
    ],
)
def test_runner_rejects_malformed_declared_request_artifact_source(
    tmp_path: Path,
    source: str,
    valid: bool,
) -> None:
    runner = _load_module()
    cleanup_dir = tmp_path / "cleanup"
    cleanup_dir.mkdir()
    (cleanup_dir / "planner_proof_requests.json").write_text(source, encoding="utf-8")
    cleanup_run_result = cleanup_dir / "run_result.json"
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": "planner_proof_requests.json"}}),
        encoding="utf-8",
    )

    reason = "a JSON object" if valid else "valid JSON object"
    message = (
        rf"planner proof requests source must contain {reason}: .*planner_proof_requests\.json"
    )
    with pytest.raises(ValueError, match=message):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_cli_prints_manifest_report_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundle"
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_molmo_planner_proof_bundle_from_requests.py",
            str(cleanup_run_result),
            "--output-dir",
            str(output_dir),
            "--runner-python",
            "python",
            "--probe-script",
            "probe.py",
            "--cleanup-script",
            "cleanup.py",
        ],
    )

    runner.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["manifest"].endswith("proof_bundle_run_manifest.json")
    assert payload["report"].endswith("report.html")
    assert (output_dir / "report.html").is_file()


def _run_minimal_bundle(runner, cleanup_run_result: Path, *, output_dir: Path) -> dict[str, object]:
    return runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=output_dir,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
    )


def _proof_requests() -> dict[str, object]:
    return {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "request_count": 1,
        "ready_count": 1,
        "planner_scene": {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": True,
            "scene_xml": "/tmp/molmospaces-scene.xml",
            "backend": "molmospaces_subprocess",
        },
        "agent_view_exposed": False,
        "blockers": [],
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "source_receptacle_id": "counter_01",
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "sink_01",
                    "--cleanup-source-receptacle-id": "counter_01",
                    "--cleanup-tools": "navigate_to_object,pick,navigate_to_receptacle,place",
                    "--cleanup-planner-object-id": "pickup/body",
                    "--cleanup-planner-target-receptacle-id": "sink/body",
                },
            }
        ],
    }
