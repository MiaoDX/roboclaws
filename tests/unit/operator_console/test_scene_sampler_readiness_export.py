from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.worlds.molmospaces import sampling as scene_sampler
from scripts.operator_console.export_scene_sampler_readiness import (
    _candidate_indices,
    _write_named_artifacts,
    export_readiness_artifacts,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolate_scanner_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scanner_root = tmp_path / "scanner-output"
    monkeypatch.setattr(scene_sampler, "_SCANNER_OUTPUT_ROOT", scanner_root)
    monkeypatch.setattr(scene_sampler, "_SCANNER_PREVIEW_ROOT", scanner_root / "previews")
    monkeypatch.setattr(
        scene_sampler,
        "_SCANNER_PRODUCT_SMOKE_ROOT",
        scanner_root / "product-smoke",
    )
    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )


def test_scene_sampler_readiness_export_writes_artifacts(tmp_path) -> None:
    result = export_readiness_artifacts(output_dir=tmp_path)
    payloads = _read_export_payloads(tmp_path)

    assert result["status"] == "success"
    assert result["threshold_failures"] == []
    assert result["summary"]["readiness"]["source_count"] == 4
    assert result["summary"]["candidate_readiness"]["source_count"] == 4
    assert result["summary"]["selection_gaps"]["source_count"] == 4
    assert result["summary"]["source_prep"]["source_count"] == 4
    artifacts = result["artifacts"]
    assert set(artifacts) == {
        "candidate_readiness",
        "candidate_profile",
        "generated_eval_samples",
        "generated_eval_suite",
        "manifest",
        "eval_projection",
        "next_flow_worklist",
        "readiness_report",
        "scanner_admission",
        "scanner_execution_plan",
        "scene_prefilter",
        "selection_gaps",
        "source_availability",
        "source_prep",
    }
    _assert_projection_readiness_and_candidates(payloads)
    _assert_selection_and_source_prep(payloads)
    _assert_scanner_artifacts(payloads)
    _assert_next_flow(payloads, result=result, output_dir=tmp_path)
    _assert_generated_eval(
        payloads,
        output_dir=tmp_path,
        sample_count=len(artifacts["generated_eval_samples"]),
    )


def _read_export_payloads(output_dir: Path) -> dict[str, Any]:
    return {
        "manifest": json.loads((output_dir / "scene_sampler_manifest.json").read_text()),
        "projection": json.loads((output_dir / "scene_sampler_eval_projection.json").read_text()),
        "readiness": json.loads((output_dir / "scene_sampler_readiness_report.json").read_text()),
        "availability": json.loads(
            (output_dir / "scene_sampler_source_availability.json").read_text()
        ),
        "candidates": json.loads(
            (output_dir / "scene_sampler_candidate_readiness.json").read_text()
        ),
        "selection": json.loads((output_dir / "scene_sampler_selection_gaps.json").read_text()),
        "candidate_profile": json.loads(
            (output_dir / "scene_sampler_candidate_profile.json").read_text()
        ),
        "scene_prefilter": json.loads(
            (output_dir / "scene_sampler_scene_prefilter.json").read_text()
        ),
        "source_prep": json.loads((output_dir / "scene_sampler_source_prep.json").read_text()),
        "scanner_admission": json.loads(
            (output_dir / "scene_sampler_scanner_admission.json").read_text()
        ),
        "scanner_execution": json.loads(
            (output_dir / "scene_sampler_scanner_execution_plan.json").read_text()
        ),
        "next_flow": json.loads((output_dir / "scene_sampler_next_flow_worklist.json").read_text()),
        "generated_suite": json.loads(
            (output_dir / "generated_eval/scene_sampler_stress.json").read_text()
        ),
    }


def _assert_projection_readiness_and_candidates(payloads: dict[str, Any]) -> None:
    manifest = payloads["manifest"]
    projection = payloads["projection"]
    readiness = payloads["readiness"]
    availability = payloads["availability"]
    candidates = payloads["candidates"]
    candidate_profile = payloads["candidate_profile"]
    scene_prefilter = payloads["scene_prefilter"]

    _assert_manifest_and_projection(manifest, projection)
    _assert_readiness_and_availability(readiness, availability)
    _assert_candidate_readiness(candidates)
    _assert_candidate_profile_and_prefilter(candidate_profile, scene_prefilter)


def _assert_manifest_and_projection(manifest: dict[str, Any], projection: dict[str, Any]) -> None:
    assert manifest["ui_target_per_scene_source"] == 3
    assert manifest["eval_target_per_scene_source"] == 10
    assert manifest["selection_policy"]["selection_seed"] == (
        "2026-06-16.source-diverse-selection-v1"
    )
    assert manifest["selection_policy"]["sources"]["procthor-objaverse-val"]["ui"][
        "selected_indices"
    ] == [10, 0, 1]
    assert manifest["selection_policy"]["sources"]["procthor-10k-val"]["ui"][
        "selected_indices"
    ] == [11, 15, 0]
    assert projection["scene_sources"]["procthor-10k-val"]["ready_count"] == 6
    assert projection["scene_sources"]["procthor-10k-val"]["support_status"] == "partial"
    assert projection["scene_sources"]["procthor-objaverse-val"]["ready_count"] == 10
    assert projection["scene_sources"]["procthor-objaverse-val"]["support_status"] == "complete"
    assert projection["scene_sources"]["ithor"]["support_status"] == "rejected"
    assert projection["summary"]["ready_sample_count"] == 16
    assert projection["summary"]["remaining_sample_count"] == 24


def _assert_readiness_and_availability(
    readiness: dict[str, Any],
    availability: dict[str, Any],
) -> None:
    assert readiness["sources"]["procthor-10k-val"]["ui_ready_count"] == 3
    assert readiness["sources"]["procthor-objaverse-val"]["ui_ready_count"] == 3
    assert readiness["selection_policy"]["sources"]["procthor-10k-val"]["ui"][
        "selected_room_counts"
    ] == [4, 10, 7]
    assert readiness["selection_policy"]["sources"]["procthor-objaverse-val"]["ui"][
        "selected_room_counts"
    ] == [5, 4, 7]
    assert readiness["sources"]["procthor-objaverse-val"]["eval_ready_count"] == 10
    assert readiness["sources"]["ithor"]["blocked_rows"][0]["failure_class"] == (
        "map_actionability_failure"
    )
    assert availability["schema"] == "molmospaces_scene_source_availability_report_v1"
    assert availability["probe_mode"] == "no_download_no_vlm"
    assert availability["summary"]["source_count"] == 4
    assert "blocked_source_count" in availability["summary"]
    assert availability["sources"]["ithor"]["failure_class"] in {
        "",
        "environment_blocked",
    }


def _assert_candidate_readiness(candidates: dict[str, Any]) -> None:
    assert candidates["schema"] == "molmospaces_scene_sampler_candidate_readiness_v1"
    assert candidates["summary"]["source_count"] == 4
    assert "eval_needed_count" in candidates["summary"]
    assert candidates["sources"]["procthor-10k-val"]["ui_ready_count"] == 3
    assert candidates["sources"]["procthor-10k-val"]["eval_ready_count"] == 6
    assert candidates["sources"]["procthor-objaverse-val"]["ui_ready_count"] == 3
    assert candidates["sources"]["procthor-objaverse-val"]["eval_ready_count"] == 10
    assert candidates["sources"]["ithor"]["eval_ready_count"] == 0


def _assert_candidate_profile_and_prefilter(
    candidate_profile: dict[str, Any],
    scene_prefilter: dict[str, Any],
) -> None:
    assert candidate_profile["schema"] == "molmospaces_scene_sampler_candidate_profile_v1"
    assert candidate_profile["summary"]["source_count"] == 4
    assert candidate_profile["summary"]["metadata_worklist_source_count"] == 3
    assert candidate_profile["sources"]["procthor-10k-val"]["profile_status"] == (
        "metadata_worklist_ready"
    )
    assert candidate_profile["sources"]["ithor"]["profile_status"] == "metadata_worklist_ready"
    assert candidate_profile["sources"]["ithor"]["next_action"] == ("metadata_first_human_curation")
    assert (
        candidate_profile["sources"]["holodeck-objaverse-val"]["metadata_worklist_candidate_count"]
        == 10
    )
    assert scene_prefilter["schema"] == "molmospaces_scene_sampler_scene_prefilter_v1"
    assert scene_prefilter["probe_mode"] == "no_download_no_backend_no_vlm"
    assert scene_prefilter["prefilter_policy"]["admission_effect"] == "none_prefilter_only"
    assert scene_prefilter["summary"]["metadata_worklist_source_count"] == 3
    assert scene_prefilter["summary"]["expensive_proof_candidate_count"] == 0
    assert scene_prefilter["summary"]["next_actions"] == {"stop_prefilter_inconclusive": 3}
    assert scene_prefilter["sources"]["ithor"]["prefilter_status"] == "prefilter_inconclusive"


def _assert_selection_and_source_prep(payloads: dict[str, Any]) -> None:
    selection = payloads["selection"]
    source_prep = payloads["source_prep"]

    assert selection["schema"] == "molmospaces_scene_sampler_selection_gaps_v1"
    assert selection["selection_policy"]["selection_strategy"] == (
        "deterministic_seeded_random_order_with_room_count_diversity_first"
    )
    assert selection["summary"]["source_count"] == 4
    assert "worklist" in selection["summary"]
    assert selection["sources"]["procthor-10k-val"]["eval_needed_count"] == 4
    assert (
        selection["sources"]["procthor-10k-val"]["selection_capacity_status"]
        == "candidate_range_insufficient"
    )
    assert selection["sources"]["procthor-10k-val"]["next_action"] == "expand_candidate_range"
    assert selection["sources"]["procthor-objaverse-val"]["eval_needed_count"] == 0
    assert selection["sources"]["procthor-objaverse-val"]["selection_capacity_status"] == "complete"
    assert selection["sources"]["procthor-objaverse-val"]["next_action"] == "none"
    assert selection["sources"]["ithor"]["ui_needed_count"] == 3
    assert selection["sources"]["ithor"]["next_action"] == (
        "do_not_scan_without_new_human_curation"
    )
    assert source_prep["schema"] == "molmospaces_scene_sampler_source_prep_v1"
    assert source_prep["probe_mode"] == "no_download_no_vlm"
    assert source_prep["download_policy"] == "manual_operator_only"
    assert "missing_resource_summary" in source_prep["summary"]
    assert "prep_status_counts" in source_prep["summary"]
    assert "worklist" in source_prep["summary"]
    assert source_prep["worklist"] == source_prep["summary"]["worklist"]
    assert source_prep["worklist"][0]["next_action"] in {
        "install_repo_dev_runtime",
        "run_manual_source_prep",
        "run_scanner_admission",
        "run_scene_only_prefilter_or_stop",
        "expand_candidate_range",
        "inspect_source_prep",
        "do_not_scan_without_new_human_curation",
        "metadata_first_human_curation",
    }
    assert source_prep["sources"]["ithor"]["molmospaces_get_scenes_call"] == (
        'get_scenes("ithor", "train")'
    )
    assert (
        source_prep["sources"]["procthor-objaverse-val"]["molmospaces_get_scenes_call"]
        == 'get_scenes("procthor-objaverse", "val")'
    )
    assert (
        source_prep["sources"]["holodeck-objaverse-val"]["molmospaces_get_scenes_call"]
        == 'get_scenes("holodeck-objaverse", "val")'
    )
    assert source_prep["sources"]["procthor-10k-val"]["recommended_candidate_range"] == "0:39"
    assert source_prep["sources"]["ithor"]["candidate_profile_status"] == (
        "metadata_worklist_ready"
    )
    assert source_prep["sources"]["ithor"]["metadata_worklist_candidate_count"] == 10
    assert source_prep["sources"]["ithor"]["scene_prefilter_status"] == ("prefilter_inconclusive")
    assert source_prep["sources"]["ithor"]["scene_prefilter_next_action"] == (
        "stop_prefilter_inconclusive"
    )
    assert "molmospaces_scene_version" in source_prep["sources"]["procthor-10k-val"]
    assert source_prep["sources"]["procthor-10k-val"]["scene_index_map_status"] in {
        "available",
        "blocked",
    }
    assert "candidate_scene_refs" in source_prep["sources"]["procthor-10k-val"]
    assert any(
        command["name"] == "install_single_scene_example"
        for command in source_prep["sources"]["ithor"]["operator_commands"]
    )


def _assert_scanner_artifacts(payloads: dict[str, Any]) -> None:
    scanner_admission = payloads["scanner_admission"]
    scanner_execution = payloads["scanner_execution"]

    assert scanner_admission["schema"] == "molmospaces_scene_sampler_scanner_admission_v1"
    assert scanner_admission["probe_mode"] == "no_download_no_backend_no_vlm"
    assert scanner_admission["summary"]["source_count"] == 4
    assert "missing_gate_counts" in scanner_admission["summary"]
    assert scanner_admission["sources"]["procthor-10k-val"]["summary"]["admitted_count"] == 6
    assert scanner_admission["sources"]["procthor-objaverse-val"]["summary"]["admitted_count"] == 10
    assert scanner_admission["sources"]["ithor"]["needed_ui_count"] == 3
    assert scanner_execution["schema"] == ("molmospaces_scene_sampler_scanner_execution_plan_v1")
    assert scanner_execution["probe_mode"] == "no_download_no_backend_no_vlm"
    assert scanner_execution["summary"]["source_count"] == 4
    assert "ready_for_product_smoke_count" in scanner_execution["summary"]


def _assert_next_flow(
    payloads: dict[str, Any],
    *,
    result: dict[str, Any],
    output_dir: Path,
) -> None:
    next_flow = payloads["next_flow"]
    scanner_execution = payloads["scanner_execution"]

    _assert_next_flow_summary(next_flow, result=result)
    _assert_next_flow_artifact_paths(next_flow, output_dir=output_dir)
    _assert_next_flow_source_statuses(next_flow)
    _assert_ithor_scanner_plan(scanner_execution)


def _assert_next_flow_summary(next_flow: dict[str, Any], *, result: dict[str, Any]) -> None:
    assert next_flow["schema"] == "molmospaces_scene_sampler_next_flow_worklist_v1"
    assert next_flow["probe_mode"] == "no_download_no_backend_no_vlm"
    assert next_flow["download_policy"] == "manual_operator_only"
    assert next_flow["summary"]["source_count"] == 4
    assert next_flow["summary"]["ui_needed_count"] == 6
    assert next_flow["summary"]["eval_needed_count"] == 24
    assert next_flow["summary"]["next_actions"] == {
        "do_not_scan_without_gate_change": 1,
        "expand_candidate_range": 1,
        "run_scene_only_prefilter_or_stop": 1,
    }
    assert next_flow["summary"]["rejected_exhausted_source_count"] == 0
    assert next_flow["summary"]["gate_mismatch_source_count"] == 1
    assert next_flow["summary"]["metadata_worklist_source_count"] == 3
    assert next_flow["summary"]["metadata_worklist_candidate_count"] >= 30
    assert "worklist" in next_flow["summary"]
    assert next_flow["worklist"] == next_flow["summary"]["worklist"]
    assert next_flow["worklist"][0]["scene_source"] in {
        "ithor",
        "procthor-10k-val",
        "holodeck-objaverse-val",
    }
    assert result["summary"]["next_flow_worklist"]["source_count"] == 4


def _assert_next_flow_artifact_paths(next_flow: dict[str, Any], *, output_dir: Path) -> None:
    assert next_flow["artifact_paths"]["readiness_output_dir"] == str(output_dir)
    assert next_flow["artifact_paths"]["source_prep"] == str(
        output_dir / "scene_sampler_source_prep.json"
    )
    assert next_flow["artifact_paths"]["scene_prefilter"] == str(
        output_dir / "scene_sampler_scene_prefilter.json"
    )


def _assert_next_flow_source_statuses(next_flow: dict[str, Any]) -> None:
    assert next_flow["sources"]["procthor-10k-val"]["ui_status"] == "ready"
    assert next_flow["sources"]["procthor-10k-val"]["eval_ready_count"] == 6
    assert next_flow["sources"]["procthor-10k-val"]["eval_needed_count"] == 4
    assert next_flow["sources"]["procthor-10k-val"]["next_action"] == "expand_candidate_range"
    assert next_flow["sources"]["procthor-objaverse-val"]["ui_status"] == "ready"
    assert next_flow["sources"]["procthor-objaverse-val"]["eval_ready_count"] == 10
    assert next_flow["sources"]["procthor-objaverse-val"]["eval_needed_count"] == 0
    assert next_flow["sources"]["procthor-objaverse-val"]["next_action"] == "none"
    assert next_flow["sources"]["ithor"]["ui_needed_count"] == 3
    assert next_flow["sources"]["ithor"]["eval_needed_count"] == 10
    assert next_flow["sources"]["ithor"]["flow_status"] == "blocked_prefilter_inconclusive"
    assert next_flow["sources"]["ithor"]["next_action"] == "run_scene_only_prefilter_or_stop"
    assert next_flow["sources"]["ithor"]["candidate_profile_status"] == ("metadata_worklist_ready")
    assert next_flow["sources"]["ithor"]["metadata_worklist_candidate_count"] == 10
    assert next_flow["sources"]["ithor"]["recommended_candidate_range"].startswith("0:")
    ithor_commands = next_flow["sources"]["ithor"]["recommended_commands"]
    assert [command["name"] for command in ithor_commands] == [
        "refresh_scene_only_prefilter",
        "inspect_prefilter_stop_reason",
    ]
    holodeck = next_flow["sources"]["holodeck-objaverse-val"]
    assert holodeck["flow_status"] == "gate_mismatch"
    assert holodeck["next_action"] == "do_not_scan_without_gate_change"
    assert holodeck["metadata_worklist_candidate_count"] >= 4
    assert holodeck["scanner_gate_mismatch_count"] == 2
    assert holodeck["recommended_commands"] == []
    assert set(holodeck["blocked_reason_samples"]) == {
        "fewer_than_three_public_navigation_areas",
        "missing_public_inspection_waypoints",
        "preview_not_reviewable",
    }


def _assert_ithor_scanner_plan(scanner_execution: dict[str, Any]) -> None:
    if scanner_execution["sources"]["ithor"]["candidates"]:
        ithor_scanner = scanner_execution["sources"]["ithor"]["candidates"][0]
        assert ithor_scanner["world_id"].startswith("molmospaces/ithor/")
        assert ithor_scanner["scanner_status"] in {
            "blocked_missing_resources",
            "ready_for_product_smoke",
        }
        assert ithor_scanner["scene_family"] == "ithor"
        assert ithor_scanner["failure_class"] == "environment_blocked"
        assert ithor_scanner["room_count"] == 0
        assert ithor_scanner["waypoint_count"] == 0
        assert ithor_scanner["category_provenance"] == "unavailable"
        assert "source_asset_available" in ithor_scanner["required_gates"]
        assert "source_asset_available" in ithor_scanner["missing_gates"]
        assert (
            "render_scene_previews.py --world molmospaces/ithor/"
            in ithor_scanner["preview_command"]
        )
        assert "world=molmospaces/ithor/" in ithor_scanner["map_build_product_smoke_command"]


def _assert_generated_eval(
    payloads: dict[str, Any],
    *,
    output_dir: Path,
    sample_count: int,
) -> None:
    generated_suite = payloads["generated_suite"]

    assert generated_suite == json.loads(
        (REPO_ROOT / "evals/household_world/suites/scene_sampler_stress.json").read_text(
            encoding="utf-8"
        )
    )
    assert sample_count == 16
    generated_sample = json.loads(
        (
            output_dir / "generated_eval/samples/scene_sampler/procthor-10k-val_10_map_build.json"
        ).read_text(encoding="utf-8")
    )
    committed_sample = json.loads(
        (
            REPO_ROOT
            / "evals/household_world/samples/scene_sampler/procthor-10k-val_10_map_build.json"
        ).read_text(encoding="utf-8")
    )
    assert generated_sample == committed_sample


def test_scene_sampler_readiness_export_can_require_ui_supported_source(tmp_path) -> None:
    result = export_readiness_artifacts(
        output_dir=tmp_path,
        required_ui_supported_sources=("procthor-objaverse-val",),
    )

    assert result["status"] == "success"
    assert result["threshold_failures"] == []


def test_scene_sampler_readiness_export_can_require_eval_complete_source(tmp_path) -> None:
    result = export_readiness_artifacts(
        output_dir=tmp_path,
        required_eval_complete_sources=("procthor-objaverse-val",),
    )

    assert result["status"] == "success"
    assert result["threshold_failures"] == []


def test_scene_sampler_readiness_export_fails_missing_eval_completion(tmp_path) -> None:
    result = export_readiness_artifacts(
        output_dir=tmp_path,
        required_eval_complete_sources=("procthor-10k-val",),
    )

    assert result["status"] == "failed"
    assert result["threshold_failures"] == [
        {
            "scene_source": "procthor-10k-val",
            "threshold": "eval_complete",
            "reason": "eval_not_complete",
            "ready_count": 6,
            "target_count": 10,
        }
    ]


def test_scene_sampler_readiness_export_can_require_complete_selection_capacity(
    tmp_path,
) -> None:
    result = export_readiness_artifacts(
        output_dir=tmp_path,
        required_selection_capacity_sources=("procthor-objaverse-val",),
    )

    selection = json.loads((tmp_path / "scene_sampler_selection_gaps.json").read_text())

    assert result["status"] == "success"
    assert result["threshold_failures"] == []
    assert selection["sources"]["procthor-objaverse-val"]["selection_capacity_status"] == "complete"
    assert selection["sources"]["procthor-objaverse-val"]["next_eval_scan_world_ids"] == []


def test_scene_sampler_readiness_export_selection_capacity_fails_for_sparse_ithor_range(
    tmp_path,
) -> None:
    result = export_readiness_artifacts(
        output_dir=tmp_path,
        candidate_indices=(),
        required_selection_capacity_sources=("ithor",),
    )

    selection = json.loads((tmp_path / "scene_sampler_selection_gaps.json").read_text())

    assert result["status"] == "failed"
    assert result["threshold_failures"] == [
        {
            "scene_source": "ithor",
            "threshold": "selection_capacity",
            "reason": "insufficient_candidate_scan_capacity",
            "ui_needed_count": 3,
            "ui_available_count": 0,
            "eval_needed_count": 10,
            "eval_available_count": 0,
        }
    ]
    assert selection["sources"]["ithor"]["next_ui_scan_world_ids"] == []
    assert selection["sources"]["ithor"]["next_eval_scan_world_ids"] == []


def test_scene_sampler_readiness_export_fails_when_scanner_source_has_no_ready_candidate(
    tmp_path,
) -> None:
    result = export_readiness_artifacts(
        output_dir=tmp_path,
        candidate_indices=tuple(range(20)),
        required_scanner_ready_sources=("ithor",),
    )

    assert result["status"] == "failed"
    assert result["threshold_failures"] == [
        {
            "scene_source": "ithor",
            "threshold": "scanner_ready",
            "reason": "no_ready_product_smoke_candidates",
            "ready_for_product_smoke_count": 0,
            "candidate_count": 0,
            "blocked_count": 0,
            "prep_status": "blocked_prefilter_inconclusive",
        }
    ]


def test_scene_sampler_readiness_export_candidate_index_options_are_sorted_unique() -> None:
    assert _candidate_indices(candidate_indexes=(4, 1), candidate_ranges=("2:3", "3:5")) == (
        1,
        2,
        3,
        4,
        5,
    )


def test_scene_sampler_readiness_export_rejects_enabled_artifact_without_payload(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="enabled artifact 'source_availability' has no payload"):
        _write_named_artifacts(
            tmp_path,
            (
                (
                    "source_availability",
                    True,
                    "scene_sampler_source_availability.json",
                    None,
                ),
            ),
        )

    assert not (tmp_path / "scene_sampler_source_availability.json").exists()


def test_scene_sampler_readiness_export_cli_returns_failure_for_unmet_threshold(
    tmp_path,
    capsys,
) -> None:
    code = main(
        [
            "--output-dir",
            str(tmp_path),
            "--require-eval-complete-source",
            "ithor",
        ]
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["summary"]["eval_projection"]["ready_sample_count"] == 16
    assert payload["threshold_failures"][0]["ready_count"] == 0


def test_scene_sampler_readiness_export_cli_rejects_invalid_candidate_range(
    tmp_path: Path,
    capsys,
) -> None:
    code = main(["--output-dir", str(tmp_path), "--candidate-range", "7:3"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "candidate-range end must be >= start" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "scene_sampler_manifest.json").exists()


def test_scene_sampler_readiness_export_cli_accepts_scanner_ready_threshold(
    tmp_path,
    capsys,
) -> None:
    code = main(
        [
            "--output-dir",
            str(tmp_path),
            "--candidate-range",
            "0:19",
            "--require-scanner-ready-source",
            "ithor",
        ]
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["threshold_failures"][0]["threshold"] == "scanner_ready"
    assert payload["threshold_failures"][0]["blocked_count"] == 0
    assert payload["threshold_failures"][0]["prep_status"] == "blocked_prefilter_inconclusive"
