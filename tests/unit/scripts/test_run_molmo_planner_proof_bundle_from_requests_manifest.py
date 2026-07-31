from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import planner_proof_bundle_runner
from tests.unit.scripts.run_molmo_planner_proof_bundle_from_requests_support import (
    _assert_inline_dry_run_artifacts,
    _assert_inline_dry_run_command,
    _assert_inline_dry_run_manifest,
    _proof_requests,
)


def test_runner_writes_dry_run_manifest_and_report_from_inline_requests(tmp_path: Path) -> None:
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

    result = planner_proof_bundle_runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
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


def test_runner_filters_to_requested_request_ids(tmp_path: Path) -> None:
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

    result = planner_proof_bundle_runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
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


def test_runner_merges_multiple_prior_manifests_for_discovery_and_filters(
    tmp_path: Path,
) -> None:
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

    result = planner_proof_bundle_runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
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


def test_runner_carries_nested_prior_proof_result_summary_from_prior_manifest(
    tmp_path: Path,
) -> None:
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

    result = planner_proof_bundle_runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
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


def test_runner_executes_warmup_before_proof_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(planner_proof_bundle_runner, "_run_command", fake_run_command)

    result = planner_proof_bundle_runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
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


def test_runner_cli_prints_manifest_report_and_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundle"
    planner_proof_bundle_runner.main(
        [
            str(cleanup_run_result),
            "--output-dir",
            str(output_dir),
            "--runner-python",
            "python",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["manifest"].endswith("proof_bundle_run_manifest.json")
    assert payload["report"].endswith("report.html")
    assert (output_dir / "report.html").is_file()
