from __future__ import annotations

import copy
from pathlib import Path

import pytest

from roboclaws.worlds.molmospaces import prefilter as scene_sampler_prefilter
from roboclaws.worlds.molmospaces import readiness as scene_sampler_readiness
from roboclaws.worlds.molmospaces import worklists as scene_sampler_worklists
from roboclaws.worlds.molmospaces.catalog_projection import (
    eval_projection_metadata,
    eval_sample_payload,
)
from roboclaws.worlds.molmospaces.contracts import EVAL_STRESS_LANE, READINESS_REJECTED, UI_LANE
from roboclaws.worlds.molmospaces.readiness import (
    candidate_profile_report,
    candidate_readiness_report,
    scene_only_prefilter_report,
    selection_gap_report,
    source_availability_report,
)
from roboclaws.worlds.molmospaces.sampling import (
    sampler_manifest,
    sampler_rows,
)
from roboclaws.worlds.molmospaces.sampling_validation import (
    load_room_label_manifest,
    validate_sampler_manifest,
)
from roboclaws.worlds.molmospaces.worklists import (
    scanner_admission_report,
    scanner_execution_plan,
    source_prep_report,
)
from roboclaws.worlds.molmospaces.world_ids import parse_molmospaces_world_id
from tests.unit.worlds.molmospaces.sampling_support import (
    HOLODECK_REJECTED_INDICES,
    ITHOR_REJECTED_INDICES,
    TOTAL_REJECTED_ROW_COUNT,
    _assert_complete_projection_source,
    _assert_partial_projection_source,
    _assert_rejected_holodeck_projection_source,
    _assert_rejected_ithor_projection_source,
    _assert_scene_sampler_projection_summary,
)


def test_scene_sampler_rejects_unknown_source_aware_world_ids() -> None:
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene_source"):
        parse_molmospaces_world_id("molmospaces/unknown-source/1")
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene index"):
        parse_molmospaces_world_id("molmospaces/ithor/not-an-index")
    with pytest.raises(ValueError, match="negative MolmoSpaces scene index"):
        parse_molmospaces_world_id("molmospaces/ithor/-1")


def test_scene_sampler_records_partial_and_blocked_source_projection() -> None:
    projection = eval_projection_metadata()

    _assert_scene_sampler_projection_summary(projection)
    _assert_partial_projection_source(
        projection["scene_sources"]["procthor-10k-val"],
        scene_source="procthor-10k-val",
        expected_rejected_indices={1, 2, 3, 4, 5, 7, 9},
    )
    _assert_complete_projection_source(
        projection["scene_sources"]["procthor-objaverse-val"],
        scene_source="procthor-objaverse-val",
        expected_rejected_indices={2, 3, 6, 8, 9},
    )
    _assert_rejected_ithor_projection_source(projection["scene_sources"]["ithor"])
    _assert_rejected_holodeck_projection_source(
        projection["scene_sources"]["holodeck-objaverse-val"]
    )


def test_scene_sampler_eval_sample_payload_rejects_non_eval_rows() -> None:
    rejected = next(row for row in sampler_rows() if row.scene_index == 1)

    with pytest.raises(ValueError, match="eval-ready sampler row"):
        eval_sample_payload(rejected)


def test_scene_sampler_rejects_heuristic_room_category_provenance() -> None:
    manifest = copy.deepcopy(sampler_manifest())
    ready_row = next(
        row
        for row in manifest["rows"]
        if row["readiness_status"] == "ready" and row["scene_index"] == 0
    )
    ready_row["category_provenance"] = "heuristic_room_count"

    with pytest.raises(ValueError, match="trusted room-category provenance"):
        validate_sampler_manifest(manifest)


@pytest.mark.parametrize(
    ("source_text", "expected_message"),
    [
        ("{", "room label manifest source must contain valid JSON object"),
        ("[]", "room label manifest source must contain a JSON object"),
    ],
)
def test_scene_sampler_room_label_manifest_reports_source_errors(
    tmp_path: Path,
    source_text: str,
    expected_message: str,
) -> None:
    manifest_path = tmp_path / "room-labels.json"
    manifest_path.write_text(source_text, encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_room_label_manifest(manifest_path)

    message = str(exc_info.value)
    assert expected_message in message
    assert str(manifest_path) in message


def test_scene_sampler_source_availability_reports_missing_molmospaces_module(
    monkeypatch,
) -> None:

    monkeypatch.setattr(
        scene_sampler_readiness,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = source_availability_report(candidate_indices=(0, 2))

    assert report["schema"] == "molmospaces_scene_source_availability_report_v1"
    assert report["probe_mode"] == "no_download_no_vlm"
    assert report["python_executable"]
    assert report["python_version"]
    assert report["molmospaces_module_available"] is False
    assert "molmospaces_module_stdout" in report
    assert "scene_root_stdout" in report
    assert report["summary"] == {
        "source_count": 4,
        "available_source_count": 0,
        "blocked_source_count": 4,
        "scene_root_available_source_count": 0,
        "source_dir_available_count": 0,
        "scene_index_map_available_count": 0,
        "missing_candidate_count": 8,
        "invalid_candidate_count": 0,
    }
    for source in ("ithor", "procthor-objaverse-val", "holodeck-objaverse-val"):
        source_report = report["sources"][source]
        assert source_report["status"] == "blocked"
        assert source_report["failure_class"] == "environment_blocked"
        assert "module is not importable" in source_report["blocked_reason"]
        assert source_report["candidate_indices"] == [0, 2]


def test_scene_sampler_candidate_readiness_keeps_ready_rejected_and_blocked_rows(
    monkeypatch,
) -> None:

    monkeypatch.setattr(
        scene_sampler_readiness,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = candidate_readiness_report(candidate_indices=(0, 1, 2))

    assert report["schema"] == "molmospaces_scene_sampler_candidate_readiness_v1"
    assert report["summary"] == {
        "source_count": 4,
        "candidate_count": 16 + TOTAL_REJECTED_ROW_COUNT + 1,
        "ready_candidate_count": 16,
        "blocked_candidate_count": 1,
        "rejected_candidate_count": TOTAL_REJECTED_ROW_COUNT,
        "ui_ready_count": 6,
        "ui_needed_count": 6,
        "eval_ready_count": 16,
        "eval_needed_count": 24,
        "ui_supported_source_count": 2,
        "eval_complete_source_count": 1,
        "blocked_source_count": 1,
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["ui_ready_count"] == 3
    assert procthor["eval_ready_count"] == 6
    assert procthor["candidate_count"] == 13
    assert procthor["ready_candidate_count"] == 6
    assert procthor["rejected_candidate_count"] == 7
    val_1 = next(item for item in procthor["candidates"] if item["scene_index"] == 1)
    assert val_1["readiness_status"] == READINESS_REJECTED
    assert val_1["blocked_reason"] == "fewer_than_three_public_navigation_areas"

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["ui_ready_count"] == 3
    assert objaverse["eval_ready_count"] == 10
    assert objaverse["candidate_count"] == 15
    assert objaverse["ready_candidate_count"] == 10
    assert objaverse["rejected_candidate_count"] == 5
    assert {
        item["scene_index"]
        for item in objaverse["candidates"]
        if item["readiness_status"] == READINESS_REJECTED
    } == {2, 3, 6, 8, 9}

    ithor = report["sources"]["ithor"]
    assert ithor["blocked_candidate_count"] == 1
    assert ithor["rejected_candidate_count"] == len(ITHOR_REJECTED_INDICES)
    assert ithor["candidates"][0]["world_id"] == "molmospaces/ithor/0"
    assert ithor["candidates"][0]["failure_class"] == "environment_blocked"
    assert {
        item["scene_index"]
        for item in ithor["candidates"]
        if item["readiness_status"] == READINESS_REJECTED
    } == ITHOR_REJECTED_INDICES

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["blocked_candidate_count"] == 0
    assert holodeck["rejected_candidate_count"] == len(HOLODECK_REJECTED_INDICES)
    assert {
        item["scene_index"]
        for item in holodeck["candidates"]
        if item["readiness_status"] == READINESS_REJECTED
    } == HOLODECK_REJECTED_INDICES


def test_scene_sampler_selection_gap_report_prioritizes_missing_samples(
    monkeypatch,
) -> None:

    monkeypatch.setattr(
        scene_sampler_readiness,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = selection_gap_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_selection_gaps_v1"
    assert report["summary"]["ui_needed_count"] == 6
    assert report["summary"]["eval_needed_count"] == 24
    assert report["summary"]["candidate_range_sufficient_source_count"] == 0
    assert report["summary"]["candidate_range_insufficient_source_count"] == 1
    assert report["summary"]["source_prep_required_count"] == 0
    assert report["summary"]["next_actions"] == {
        "expand_candidate_range": 1,
        "do_not_scan_without_new_human_curation": 2,
    }
    assert report["summary"]["worklist"][0] == {
        "scene_source": "procthor-10k-val",
        "next_action": "expand_candidate_range",
        "selection_capacity_status": "candidate_range_insufficient",
        "source_availability_status": "blocked",
        "ui_needed_count": 0,
        "ui_scan_candidate_count": 0,
        "eval_needed_count": 4,
        "eval_scan_candidate_count": 2,
        "next_scan_world_ids": [
            "molmospaces/procthor-10k-val/8",
            "molmospaces/procthor-10k-val/6",
        ],
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["ui_needed_count"] == 0
    assert procthor["eval_needed_count"] == 4
    assert procthor["selection_capacity_status"] == "candidate_range_insufficient"
    assert procthor["next_action"] == "expand_candidate_range"
    assert procthor["next_ui_scan_world_ids"] == []
    assert procthor["next_eval_scan_world_ids"] == [
        "molmospaces/procthor-10k-val/8",
        "molmospaces/procthor-10k-val/6",
    ]
    assert procthor["rejected_candidate_indices"] == [1, 2, 3, 4, 5, 7, 9]

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["ui_needed_count"] == 0
    assert objaverse["eval_needed_count"] == 0
    assert objaverse["selection_capacity_status"] == "complete"
    assert objaverse["next_action"] == "none"
    assert objaverse["next_ui_scan_world_ids"] == []
    assert objaverse["next_eval_scan_world_ids"] == []
    assert objaverse["rejected_candidate_indices"] == [2, 3, 6, 8, 9]

    ithor = report["sources"]["ithor"]
    assert ithor["ui_needed_count"] == 3
    assert ithor["eval_needed_count"] == 10
    assert ithor["selection_capacity_status"] == "rejected_exhausted"
    assert ithor["next_action"] == "do_not_scan_without_new_human_curation"
    assert ithor["next_ui_scan_world_ids"] == []
    assert ithor["next_eval_scan_world_ids"] == []

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["ui_needed_count"] == 3
    assert holodeck["eval_needed_count"] == 10
    assert holodeck["selection_capacity_status"] == "rejected_exhausted"
    assert holodeck["next_action"] == "do_not_scan_without_new_human_curation"
    assert holodeck["next_ui_scan_world_ids"] == []
    assert holodeck["next_eval_scan_world_ids"] == []
    assert holodeck["rejected_candidate_indices"] == sorted(HOLODECK_REJECTED_INDICES)


def test_scene_sampler_selection_gap_marks_ithor_rejected_when_assets_are_visible() -> None:
    report = selection_gap_report(candidate_indices=tuple(range(13)))

    ithor = report["sources"]["ithor"]
    assert ithor["selection_capacity_status"] == "rejected_exhausted"
    assert ithor["next_action"] == "do_not_scan_without_new_human_curation"
    assert ithor["next_ui_scan_world_ids"] == []
    assert ithor["next_eval_scan_world_ids"] == []
    rejected_ithor = set(ithor["rejected_candidate_indices"])
    assert set(range(1, 13)).issubset(rejected_ithor)
    assert {209, 210, 211, 303, 305}.issubset(rejected_ithor)
    assert {404, 406, 408, 411}.issubset(rejected_ithor)

    prep = source_prep_report(candidate_indices=tuple(range(13)))
    assert prep["sources"]["ithor"]["prep_status"] == "rejected_exhausted"
    assert prep["sources"]["ithor"]["install_candidates"] == []


def test_scene_sampler_candidate_profile_does_not_reoffer_failed_preview_candidates() -> None:
    report = candidate_profile_report(candidate_indices=(404, 406, 408, 411))

    ithor = report["sources"]["ithor"]
    assert {404, 406, 408, 411}.issubset(ithor["known_rejected_indices"])
    assert {404, 406, 408, 411}.isdisjoint(ithor["metadata_worklist_indices"])

    failed = {
        candidate["scene_index"]: candidate
        for candidate in ithor["candidates"]
        if candidate["scene_index"] in {404, 406, 408, 411}
    }
    assert failed[404]["known_blocked_reason"] == "missing_public_inspection_waypoints"
    assert all(
        candidate["next_action"] == "do_not_scan_without_gate_change_or_new_curation"
        for candidate in failed.values()
    )


def test_scene_sampler_prefilter_optional_json_ignores_missing_source(tmp_path: Path) -> None:
    assert scene_sampler_prefilter._read_json_if_exists(tmp_path / "missing.json") == {}


def test_scene_sampler_scene_only_prefilter_stops_when_descriptors_are_missing(
    monkeypatch,
) -> None:

    monkeypatch.setattr(
        scene_sampler_readiness,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = scene_only_prefilter_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_scene_prefilter_v1"
    assert report["probe_mode"] == "no_download_no_backend_no_vlm"
    assert report["download_policy"] == "manual_operator_only"
    assert report["prefilter_policy"]["admission_effect"] == "none_prefilter_only"
    assert report["summary"]["metadata_worklist_source_count"] == 3
    assert report["summary"]["expensive_proof_candidate_count"] == 0
    assert report["summary"]["next_actions"] == {"stop_prefilter_inconclusive": 3}

    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["prefilter_status"] == "prefilter_inconclusive"
    assert procthor["next_action"] == "stop_prefilter_inconclusive"
    assert procthor["candidate_count"] == 10
    assert procthor["expensive_proof_candidate_count"] == 0

    ithor = report["sources"]["ithor"]
    assert ithor["prefilter_status"] == "prefilter_inconclusive"
    assert ithor["next_action"] == "stop_prefilter_inconclusive"
    assert ithor["candidate_count"] == 10
    assert ithor["expensive_proof_candidate_count"] == 0
    assert {candidate["prefilter_reason"] for candidate in ithor["candidates"]}.issubset(
        {"descriptor_missing", "source_index_reference_missing"}
    )


def test_scene_sampler_scanner_execution_plan_does_not_rerun_rejected_metadata_candidates(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco />", encoding="utf-8")
    monkeypatch.setattr(
        scene_sampler_worklists,
        "source_prep_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "prep_status": (
                        "ready_for_scanner" if source == "holodeck-objaverse-val" else "complete"
                    ),
                    "install_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "primary_path": str(candidate_path),
                            "path_status": "available",
                            "paths": [
                                {
                                    "role": "base",
                                    "path": str(candidate_path),
                                    "exists": True,
                                }
                            ],
                            "missing_paths": [],
                            "install_command": "",
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler_worklists,
        "scanner_admission_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "admission_rows": [
                        {
                            "scene_family": "holodeck-objaverse",
                            "scene_split": "val",
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "readiness_status": READINESS_REJECTED,
                            "admission_status": "rejected",
                            "lanes": [],
                            "failure_class": "map_actionability_failure",
                            "blocked_reason": "fewer_than_three_public_navigation_areas",
                            "selected_reason": "fewer_than_three_public_navigation_areas",
                            "room_count": 1,
                            "waypoint_count": 2,
                            "category_provenance": "source_metadata",
                            "preview_statuses": {
                                "fpv": "reviewable",
                                "map": "reviewable",
                                "chase": "reviewable",
                                "topdown": "reviewable",
                            },
                            "passed_gates": [],
                            "required_gates": [
                                "source_asset_available",
                                "preview_metadata",
                                "public_room_count",
                                "public_waypoints",
                                "trusted_category_provenance",
                                "map_build_artifacts",
                            ],
                            "missing_gates": [],
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    plan = scanner_execution_plan(candidate_indices=tuple(range(40)))
    holodeck = plan["sources"]["holodeck-objaverse-val"]

    assert plan["summary"]["candidate_count"] == 1
    assert plan["summary"]["ready_for_product_smoke_count"] == 0
    assert plan["summary"]["blocked_count"] == 1
    assert holodeck["candidates"][0]["scanner_status"] == "rejected_by_admission"
    assert holodeck["candidates"][0]["next_action"] == ("do_not_scan_without_new_human_curation")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"valid JSON object: .*preview\.json",
        ),
        (
            "[]\n",
            r"scene sampler preview metadata source must contain a JSON object: .*preview\.json",
        ),
    ],
)
def test_scene_sampler_preview_metadata_rejects_bad_sources(
    monkeypatch,
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(scene_sampler, "_PREVIEW_ROOT", tmp_path)
    (tmp_path / "molmospaces-val_4-preview.json").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        scene_sampler._preview_metadata(4)


def test_scene_sampler_preview_metadata_rejects_missing_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(scene_sampler, "_PREVIEW_ROOT", tmp_path)

    with pytest.raises(
        ValueError,
        match=r"missing preview metadata for scene 4: .*molmospaces-val_4-preview\.json",
    ):
        scene_sampler._preview_metadata(4)


def test_scene_sampler_scanner_admission_report_records_missing_gates(monkeypatch) -> None:

    monkeypatch.setattr(
        scene_sampler_readiness,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = scanner_admission_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_scanner_admission_v1"
    assert report["probe_mode"] == "no_download_no_backend_no_vlm"
    assert report["summary"]["admitted_count"] == 16
    assert report["summary"]["blocked_count"] == 3
    assert report["summary"]["rejected_count"] == TOTAL_REJECTED_ROW_COUNT
    assert report["summary"]["missing_gate_counts"] == {
        "source_asset_available": 3,
        "preview_metadata": 3,
        "public_room_count": 3,
        "public_waypoints": 3,
        "trusted_category_provenance": 3,
        "map_build_artifacts": 3,
    }
    procthor = report["sources"]["procthor-10k-val"]
    val_0 = next(item for item in procthor["admission_rows"] if item["scene_index"] == 0)
    assert val_0["admission_status"] == "admitted"
    assert val_0["lanes"] == [UI_LANE, EVAL_STRESS_LANE]
    assert val_0["failure_class"] == ""
    val_1 = next(item for item in procthor["admission_rows"] if item["scene_index"] == 1)
    assert val_1["admission_status"] == "rejected"
    assert val_1["failure_class"] == "map_actionability_failure"
    val_10 = next(item for item in procthor["admission_rows"] if item["scene_index"] == 10)
    assert val_10["admission_status"] == "admitted"
    assert val_10["lanes"] == [EVAL_STRESS_LANE]

    objaverse = report["sources"]["procthor-objaverse-val"]
    objaverse_0 = next(item for item in objaverse["admission_rows"] if item["scene_index"] == 0)
    assert objaverse_0["admission_status"] == "admitted"
    assert objaverse_0["category_provenance"] == "source_metadata"
    objaverse_2 = next(item for item in objaverse["admission_rows"] if item["scene_index"] == 2)
    assert objaverse_2["admission_status"] == "rejected"
    assert objaverse_2["failure_class"] == "map_actionability_failure"

    holodeck = report["sources"]["holodeck-objaverse-val"]
    holodeck_0 = next(item for item in holodeck["admission_rows"] if item["scene_index"] == 0)
    assert holodeck_0["admission_status"] == "rejected"
    assert holodeck_0["failure_class"] == "map_actionability_failure"
    assert holodeck_0["blocked_reason"] == "fewer_than_three_public_navigation_areas"
    assert holodeck_0["category_provenance"] == "source_metadata"
    assert holodeck_0["missing_gates"] == []
    assert holodeck_0["next_action"] == "do_not_scan_without_new_human_curation"

    ithor = report["sources"]["ithor"]
    assert ithor["needed_ui_count"] == 3
    assert ithor["needed_eval_count"] == 10
    assert ithor["admission_rows"][0]["world_id"] == "molmospaces/ithor/0"
    assert ithor["admission_rows"][0]["admission_status"] == "blocked"
    ithor_1 = next(item for item in ithor["admission_rows"] if item["scene_index"] == 1)
    assert ithor_1["admission_status"] == "rejected"
    assert ithor_1["blocked_reason"] == "fewer_than_three_public_navigation_areas"
