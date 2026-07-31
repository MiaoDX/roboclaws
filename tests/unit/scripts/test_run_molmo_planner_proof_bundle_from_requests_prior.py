from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household import planner_proof_prior_sources
from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from tests.unit.scripts.run_molmo_planner_proof_bundle_from_requests_support import (
    _load_module,
    _proof_requests,
)


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


def test_runner_preserves_prior_blocker_detail_from_excluded_requests() -> None:
    results = planner_proof_prior_sources._merged_prior_results(
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
