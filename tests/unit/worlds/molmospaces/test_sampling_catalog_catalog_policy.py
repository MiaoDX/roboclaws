from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS, world_spec
from roboclaws.worlds.molmospaces import prefilter as scene_sampler_prefilter
from roboclaws.worlds.molmospaces.sampling import (
    EVAL_STRESS_LANE,
    READINESS_BLOCKED,
    UI_LANE,
    MolmoSpacesSceneRef,
    candidate_profile_report,
    eval_sample_payload,
    eval_sample_ref,
    eval_sampler_rows,
    eval_suite_payload,
    parse_molmospaces_world_id,
    readiness_report,
    sampler_manifest,
    sampler_rows,
    scanner_execution_plan,
    scene_only_prefilter_report,
    source_prep_report,
    ui_molmospaces_world_ids,
    validate_sampler_manifest,
)
from tests.unit.worlds.molmospaces.sampling_support import (
    HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES,
    HOLODECK_PREFILTER_GATE_MISMATCH_INDICES,
    HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES,
    HOLODECK_REJECTED_INDICES,
    ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES,
    ITHOR_REJECTED_INDICES,
    REPO_ROOT,
    UI_WORLD_IDS,
    _assert_partial_procthor_source_prep,
)


def test_scene_sampler_manifest_separates_ui_and_eval_worlds() -> None:
    validate_sampler_manifest()

    assert ui_molmospaces_world_ids() == UI_WORLD_IDS
    assert MOLMOSPACES_CONSOLE_WORLD_IDS == ui_molmospaces_world_ids()

    ui_rows = [row for row in sampler_rows() if row.ui_ready]
    eval_rows = eval_sampler_rows()
    assert [(row.scene_source, row.scene_index) for row in ui_rows] == [
        ("procthor-10k-val", 0),
        ("procthor-10k-val", 11),
        ("procthor-10k-val", 15),
        ("procthor-objaverse-val", 0),
        ("procthor-objaverse-val", 1),
        ("procthor-objaverse-val", 10),
    ]
    assert [(row.scene_source, row.scene_index) for row in eval_rows] == [
        ("procthor-10k-val", 0),
        ("procthor-10k-val", 10),
        ("procthor-10k-val", 11),
        ("procthor-10k-val", 12),
        ("procthor-10k-val", 13),
        ("procthor-10k-val", 15),
        ("procthor-objaverse-val", 0),
        ("procthor-objaverse-val", 1),
        ("procthor-objaverse-val", 4),
        ("procthor-objaverse-val", 5),
        ("procthor-objaverse-val", 7),
        ("procthor-objaverse-val", 10),
        ("procthor-objaverse-val", 11),
        ("procthor-objaverse-val", 12),
        ("procthor-objaverse-val", 13),
        ("procthor-objaverse-val", 14),
    ]
    assert all(UI_LANE in row.lanes for row in ui_rows)
    assert all(EVAL_STRESS_LANE in row.lanes for row in eval_rows)

    assert "molmospaces/procthor-10k-val/9" not in WORLD_SPECS
    assert world_spec("molmospaces/procthor-10k-val/9").availability == "hidden"


def test_scene_sampler_ui_selection_is_seeded_and_room_diverse() -> None:
    manifest = sampler_manifest()
    policy = manifest["selection_policy"]

    assert policy["schema"] == "molmospaces_scene_sampler_selection_policy_v1"
    assert policy["selection_seed"] == "2026-06-16.source-diverse-selection-v1"
    assert policy["selection_strategy"] == (
        "deterministic_seeded_random_order_with_room_count_diversity_first"
    )
    assert policy["sources"]["procthor-10k-val"]["ui"]["selected_indices"] == [11, 15, 0]
    assert policy["sources"]["procthor-10k-val"]["ui"]["selected_room_counts"] == [4, 10, 7]
    assert policy["sources"]["procthor-objaverse-val"]["ui"]["selected_indices"] == [10, 0, 1]
    assert policy["sources"]["procthor-objaverse-val"]["ui"]["selected_room_counts"] == [
        5,
        4,
        7,
    ]


def test_world_spec_sampler_metadata_is_immutable() -> None:
    spec = world_spec("molmospaces/procthor-10k-val/0")

    with pytest.raises(TypeError):
        spec.sampler_metadata["selected_reason"] = "changed"  # type: ignore[index]


def test_scene_sampler_parses_source_aware_world_ids() -> None:
    assert parse_molmospaces_world_id("molmospaces/procthor-10k-val/9") == MolmoSpacesSceneRef(
        scene_source="procthor-10k-val",
        scene_index=9,
    )
    assert parse_molmospaces_world_id("molmospaces/ithor/3") == MolmoSpacesSceneRef(
        scene_source="ithor",
        scene_index=3,
    )
    assert parse_molmospaces_world_id("molmospaces/holodeck-objaverse-val/12") == (
        MolmoSpacesSceneRef(scene_source="holodeck-objaverse-val", scene_index=12)
    )


def test_scene_sampler_eval_suite_payload_matches_committed_fixture() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/household_world/suites/scene_sampler_stress.json").read_text(
            encoding="utf-8"
        )
    )

    assert eval_suite_payload() == fixture


def test_scene_sampler_eval_sample_payloads_match_committed_fixtures() -> None:
    for row in eval_sampler_rows():
        fixture_path = REPO_ROOT / eval_sample_ref(row)
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

        assert eval_sample_payload(row) == fixture


def test_scene_sampler_requires_exactly_three_ui_rows_per_visible_source() -> None:
    manifest = copy.deepcopy(sampler_manifest())
    row = next(
        row
        for row in manifest["rows"]
        if row["scene_source"] == "procthor-objaverse-val" and row["scene_index"] == 4
    )
    row["readiness_status"] = "ready"
    row["lanes"] = [UI_LANE, EVAL_STRESS_LANE]

    with pytest.raises(ValueError, match="more than 3 UI samples"):
        validate_sampler_manifest(manifest)


def test_scene_sampler_limits_eval_stress_rows_per_source() -> None:
    manifest = copy.deepcopy(sampler_manifest())
    template = next(
        row
        for row in manifest["rows"]
        if row["readiness_status"] == "ready" and row["scene_index"] == 0
    )
    manifest["rows"] = [
        {
            **template,
            "world_id": f"molmospaces/procthor-10k-val/0/eval-{index}",
            "lanes": [EVAL_STRESS_LANE],
        }
        for index in range(11)
    ]

    with pytest.raises(ValueError, match="more than 10 eval-stress samples"):
        validate_sampler_manifest(manifest)


def test_scene_sampler_readiness_report_is_per_source() -> None:
    report = readiness_report()

    assert report["schema"] == "molmospaces_scene_sampler_readiness_report_v1"
    assert report["summary"]["source_count"] == 4
    assert report["summary"]["ui_supported_source_count"] == 2
    assert report["summary"]["eval_complete_source_count"] == 1
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["ui_status"] == "ready"
    assert procthor["ui_ready_count"] == 3
    assert procthor["eval_status"] == "partial_or_blocked"
    assert procthor["eval_ready_count"] == 6

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["ui_status"] == "ready"
    assert objaverse["ui_ready_count"] == 3
    assert objaverse["eval_status"] == "complete"
    assert objaverse["eval_ready_count"] == 10
    assert {row["scene_index"] for row in objaverse["blocked_rows"]} == {2, 3, 6, 8, 9}

    ithor = report["sources"]["ithor"]
    assert ithor["ui_status"] == "not_visible"
    assert ithor["ui_ready_count"] == 0
    assert ithor["eval_status"] == "partial_or_blocked"
    assert ithor["eval_ready_count"] == 0
    assert {row["scene_index"] for row in ithor["blocked_rows"]} == ITHOR_REJECTED_INDICES
    assert {
        row["scene_index"]
        for row in ithor["blocked_rows"]
        if row["failure_class"] == "environment_blocked"
    } == ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["ui_status"] == "not_visible"
    assert holodeck["ui_ready_count"] == 0
    assert holodeck["eval_status"] == "partial_or_blocked"
    assert holodeck["eval_ready_count"] == 0
    assert {row["scene_index"] for row in holodeck["blocked_rows"]} == (HOLODECK_REJECTED_INDICES)
    assert {
        row["scene_index"]
        for row in holodeck["blocked_rows"]
        if row["failure_class"] == "environment_blocked"
    } == HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    assert all(
        row["failure_class"] == "map_actionability_failure"
        for row in holodeck["blocked_rows"]
        if row["scene_index"] not in HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    )
    assert {
        row["scene_index"]
        for row in holodeck["blocked_rows"]
        if row["blocked_reason"] == "preview_not_reviewable"
    } == HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES
    assert {
        row["scene_index"]
        for row in holodeck["blocked_rows"]
        if row["scene_index"] in HOLODECK_PREFILTER_GATE_MISMATCH_INDICES
    } == HOLODECK_PREFILTER_GATE_MISMATCH_INDICES


def test_scene_sampler_candidate_profile_lists_metadata_first_worklists() -> None:
    report = candidate_profile_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_candidate_profile_v1"
    assert report["probe_mode"] == "no_download_no_backend_no_vlm"
    assert report["download_policy"] == "manual_operator_only"
    assert report["summary"]["source_count"] == 4
    assert report["summary"]["metadata_worklist_source_count"] == 2
    assert report["summary"]["metadata_worklist_candidate_count"] == 20
    assert report["summary"]["next_actions"] == {
        "choose_new_candidate_indices_or_gate_change": 1,
        "metadata_first_human_curation": 2,
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["profile_status"] == "metadata_worklist_ready"
    assert procthor["next_action"] == "metadata_first_human_curation"
    assert procthor["metadata_worklist_candidate_count"] == 10
    assert report["sources"]["procthor-objaverse-val"]["profile_status"] == "complete"

    ithor = report["sources"]["ithor"]
    assert ithor["profile_status"] == "known_rejected_exhausted"
    assert ithor["next_action"] == "choose_new_candidate_indices_or_gate_change"
    assert set(range(1, 13)).issubset(ithor["known_rejected_indices"])
    assert {201, 208, 209, 210, 211, 303, 304, 305, 307, 309}.issubset(
        ithor["known_rejected_indices"]
    )
    assert {404, 406, 408, 409, 411}.issubset(ithor["known_rejected_indices"])
    assert ithor["metadata_worklist_candidate_count"] == 0
    assert ithor["metadata_worklist_world_ids"] == []
    assert ithor["metadata_worklist_candidates"] == []

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["profile_status"] == "metadata_worklist_ready"
    assert holodeck["next_action"] == "metadata_first_human_curation"
    assert set(range(20)).issubset(holodeck["known_rejected_indices"])
    assert {71, 106, 157, 173, 280, 292, 323, 349, 360, 396}.issubset(
        holodeck["known_rejected_indices"]
    )
    assert holodeck["metadata_worklist_candidate_count"] == 10
    assert all(
        index not in holodeck["known_rejected_indices"]
        for index in holodeck["metadata_worklist_indices"]
    )
    assert holodeck["metadata_worklist_world_ids"][0].startswith(
        "molmospaces/holodeck-objaverse-val/"
    )


def test_scene_sampler_prefilter_optional_json_loads_object(tmp_path: Path) -> None:
    source = tmp_path / "prefilter.json"
    source.write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    assert scene_sampler_prefilter._read_json_if_exists(source) == {"status": "ready"}


@pytest.mark.parametrize("source_text", ["{bad json\n", "[]\n"])
def test_scene_sampler_prefilter_optional_json_ignores_bad_source(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "prefilter.json"
    source.write_text(source_text, encoding="utf-8")

    assert scene_sampler_prefilter._read_json_if_exists(source) == {}


def test_scene_sampler_scene_only_prefilter_selects_high_confidence_descriptor(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco><geom name='room_0'/></mujoco>", encoding="utf-8")
    candidate_path.with_suffix(".json").write_text(
        json.dumps({"rooms": [{"id": "kitchen"}, {"id": "living"}, {"id": "hall"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        scene_sampler,
        "candidate_profile_report",
        lambda *, candidate_indices: {
            "selection_policy": {},
            "sources": {
                source: {
                    "scene_family": "holodeck-objaverse",
                    "scene_split": "val",
                    "profile_status": (
                        "metadata_worklist_ready"
                        if source == "holodeck-objaverse-val"
                        else "complete"
                    ),
                    "next_action": (
                        "metadata_first_human_curation"
                        if source == "holodeck-objaverse-val"
                        else "none"
                    ),
                    "metadata_worklist_candidate_count": 1
                    if source == "holodeck-objaverse-val"
                    else 0,
                    "metadata_worklist_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "metadata_worklist_rank": 0,
                            "known_failure_class": "environment_blocked",
                            "known_blocked_reason": "map build product smoke pending",
                            "candidate_file": {
                                "scene_source": "holodeck-objaverse-val",
                                "scene_index": 22,
                                "path": str(candidate_path),
                                "exists": True,
                                "status": "available",
                                "source": "molmospaces_get_scenes",
                                "paths": [
                                    {
                                        "role": "base",
                                        "path": str(candidate_path),
                                        "exists": True,
                                    }
                                ],
                                "missing_paths": [],
                            },
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            },
        },
    )

    report = scene_only_prefilter_report(candidate_indices=tuple(range(40)))
    holodeck = report["sources"]["holodeck-objaverse-val"]

    assert holodeck["prefilter_status"] == "high_confidence_ready"
    assert holodeck["next_action"] == "run_expensive_proof_for_prefiltered_candidates"
    assert holodeck["high_confidence_candidate_count"] == 1
    assert holodeck["expensive_proof_candidate_count"] == 1
    candidate = holodeck["candidates"][0]
    assert candidate["prefilter_status"] == "high_confidence"
    assert candidate["prefilter_reason"] == "likely_multi_area"
    assert candidate["cheap_room_count"] == 3
    assert candidate["scene_descriptor_path"] == str(candidate_path.with_suffix(".json"))
    assert candidate["expensive_proof_selected"] is True
    assert candidate["admission_effect"] == "none_prefilter_only"


def test_scene_sampler_scene_only_prefilter_marks_single_room_low_confidence(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_23.xml"
    candidate_path.write_text("<mujoco><geom name='room_0'/></mujoco>", encoding="utf-8")

    monkeypatch.setattr(
        scene_sampler,
        "candidate_profile_report",
        lambda *, candidate_indices: {
            "selection_policy": {},
            "sources": {
                source: {
                    "scene_family": "holodeck-objaverse",
                    "scene_split": "val",
                    "profile_status": (
                        "metadata_worklist_ready"
                        if source == "holodeck-objaverse-val"
                        else "complete"
                    ),
                    "next_action": (
                        "metadata_first_human_curation"
                        if source == "holodeck-objaverse-val"
                        else "none"
                    ),
                    "metadata_worklist_candidate_count": 1
                    if source == "holodeck-objaverse-val"
                    else 0,
                    "metadata_worklist_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 23,
                            "world_id": "molmospaces/holodeck-objaverse-val/23",
                            "candidate_file": {
                                "scene_source": "holodeck-objaverse-val",
                                "scene_index": 23,
                                "path": str(candidate_path),
                                "exists": True,
                                "status": "available",
                                "source": "molmospaces_get_scenes",
                                "paths": [
                                    {
                                        "role": "base",
                                        "path": str(candidate_path),
                                        "exists": True,
                                    }
                                ],
                                "missing_paths": [],
                            },
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            },
        },
    )

    report = scene_only_prefilter_report(candidate_indices=tuple(range(40)))
    holodeck = report["sources"]["holodeck-objaverse-val"]

    assert holodeck["prefilter_status"] == "low_confidence_only"
    assert holodeck["next_action"] == "stop_prefilter_inconclusive"
    assert holodeck["expensive_proof_candidate_count"] == 0
    candidate = holodeck["candidates"][0]
    assert candidate["prefilter_status"] == "low_confidence"
    assert candidate["prefilter_reason"] == "single_room_likely"
    assert candidate["cheap_room_count"] == 1
    assert candidate["next_action"] == "do_not_run_expensive_proof_without_gate_change"


def test_scene_sampler_source_prep_report_lists_manual_prep_steps(monkeypatch) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = source_prep_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_source_prep_v1"
    assert report["probe_mode"] == "no_download_no_vlm"
    assert report["download_policy"] == "manual_operator_only"
    assert report["summary"]["source_count"] == 4
    assert report["summary"]["missing_resource_summary"]["by_resource_type"] == {}
    assert report["summary"]["missing_resource_summary"]["by_reason"] == {}
    assert report["summary"]["prep_status_counts"] == {
        "blocked_prefilter_inconclusive": 2,
        "complete": 1,
        "gate_mismatch": 1,
    }
    assert report["summary"]["worklist"][0]["scene_source"] == "procthor-10k-val"
    assert report["summary"]["worklist"][0]["next_action"] == "run_scene_only_prefilter_or_stop"
    assert report["summary"]["worklist"][0]["metadata_worklist_candidate_count"] == 10
    assert report["summary"]["worklist"][0]["install_candidate_count"] == 2

    _assert_partial_procthor_source_prep(report["sources"]["procthor-10k-val"])

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["prep_status"] == "complete"
    assert objaverse["recommended_candidate_range"] == "0:9"
    assert objaverse["molmospaces_get_scenes_call"] == ('get_scenes("procthor-objaverse", "val")')
    assert objaverse["missing_resources"] == []

    ithor = report["sources"]["ithor"]
    assert ithor["molmospaces_get_scenes_call"] == 'get_scenes("ithor", "train")'
    assert ithor["prep_status"] == "blocked_prefilter_inconclusive"
    assert ithor["candidate_profile_status"] == "metadata_worklist_ready"
    assert ithor["candidate_profile_next_action"] == "metadata_first_human_curation"
    assert ithor["metadata_worklist_candidate_count"] == 10
    assert ithor["scene_prefilter_status"] == "prefilter_inconclusive"
    assert ithor["scene_prefilter_next_action"] == "stop_prefilter_inconclusive"
    assert ithor["scene_prefilter_expensive_proof_candidate_count"] == 0
    assert ithor["next_scan_world_ids"] == []
    assert ithor["install_candidates"] == []
    assert any(
        command["name"] == "rerun_readiness_after_prep" for command in ithor["operator_commands"]
    )

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["prep_status"] == "gate_mismatch"
    assert holodeck["gate_mismatch_candidate_count"] == 2
    assert holodeck["gate_mismatch_world_ids"] == [
        "molmospaces/holodeck-objaverse-val/231",
        "molmospaces/holodeck-objaverse-val/344",
    ]
    assert holodeck["install_candidates"] == []
    assert holodeck["missing_resources"] == []


def test_scene_sampler_source_prep_promotes_metadata_worklist_when_assets_exist(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco />", encoding="utf-8")
    candidate_path.with_suffix(".json").write_text(
        json.dumps({"rooms": [{"id": "kitchen"}, {"id": "living"}, {"id": "hall"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scene_sampler,
        "source_availability_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "scene_source": source,
                    "status": "available",
                    "module_available": True,
                    "scene_root_available": True,
                    "scene_index_map_status": "available",
                    "molmospaces_scene_version": "test",
                    "scene_index_map_reason": "",
                    "scene_index_map_stdout": "",
                    "source_dir": str(tmp_path),
                    "source_dir_available": True,
                    "candidate_files": [
                        {
                            "scene_source": source,
                            "scene_index": 22,
                            "path": str(candidate_path),
                            "exists": True,
                            "status": "available",
                            "source": "molmospaces_get_scenes",
                            "raw_ref_type": "dict",
                            "paths": [
                                {
                                    "role": "base",
                                    "path": str(candidate_path),
                                    "exists": True,
                                }
                            ],
                            "missing_paths": [],
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
        scene_sampler,
        "selection_gap_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "scene_source": source,
                    "status": "incomplete",
                    "selection_capacity_status": (
                        "rejected_exhausted" if source == "holodeck-objaverse-val" else "complete"
                    ),
                    "ui_needed_count": 3 if source == "holodeck-objaverse-val" else 0,
                    "eval_needed_count": 10 if source == "holodeck-objaverse-val" else 0,
                    "next_scan_candidates": [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler,
        "candidate_profile_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "profile_status": (
                        "metadata_worklist_ready"
                        if source == "holodeck-objaverse-val"
                        else "complete"
                    ),
                    "next_action": (
                        "metadata_first_human_curation"
                        if source == "holodeck-objaverse-val"
                        else "none"
                    ),
                    "metadata_worklist_indices": [22] if source == "holodeck-objaverse-val" else [],
                    "metadata_worklist_world_ids": ["molmospaces/holodeck-objaverse-val/22"]
                    if source == "holodeck-objaverse-val"
                    else [],
                    "metadata_worklist_candidate_count": 1
                    if source == "holodeck-objaverse-val"
                    else 0,
                    "metadata_worklist_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "known_failure_class": "environment_blocked",
                            "known_blocked_reason": "map build product smoke pending",
                            "candidate_file": {
                                "scene_source": "holodeck-objaverse-val",
                                "scene_index": 22,
                                "path": str(candidate_path),
                                "exists": True,
                                "status": "available",
                                "source": "molmospaces_get_scenes",
                                "paths": [
                                    {
                                        "role": "base",
                                        "path": str(candidate_path),
                                        "exists": True,
                                    }
                                ],
                                "missing_paths": [],
                            },
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    prep = source_prep_report(candidate_indices=tuple(range(40)))
    holodeck = prep["sources"]["holodeck-objaverse-val"]

    assert holodeck["prep_status"] == "ready_for_scanner"
    assert holodeck["scene_prefilter_status"] == "high_confidence_ready"
    assert holodeck["scene_prefilter_expensive_proof_candidate_count"] == 1
    assert holodeck["metadata_worklist_scan_world_ids"] == ["molmospaces/holodeck-objaverse-val/22"]
    assert holodeck["install_candidates"][0]["world_id"] == (
        "molmospaces/holodeck-objaverse-val/22"
    )
    assert holodeck["install_candidates"][0]["primary_path"] == str(candidate_path)
    assert holodeck["install_candidates"][0]["prefilter_status"] == "high_confidence"
    assert holodeck["install_candidates"][0]["prefilter_reason"] == "likely_multi_area"
    assert holodeck["install_candidates"][0]["prefilter_score"] == 3


def test_scene_sampler_scanner_execution_plan_runs_metadata_worklist_candidates(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco />", encoding="utf-8")
    monkeypatch.setattr(
        scene_sampler,
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
        scene_sampler,
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
                            "readiness_status": READINESS_BLOCKED,
                            "admission_status": "blocked",
                            "lanes": [],
                            "failure_class": "environment_blocked",
                            "blocked_reason": "map build product smoke pending",
                            "selected_reason": "scanner_evidence_incomplete_for_source_sampler",
                            "room_count": 1,
                            "waypoint_count": 2,
                            "category_provenance": "unavailable",
                            "preview_statuses": {
                                "fpv": "reviewable",
                                "map": "reviewable",
                                "chase": "reviewable",
                                "topdown": "reviewable",
                            },
                            "passed_gates": ["source_asset_available", "preview_metadata"],
                            "required_gates": [
                                "source_asset_available",
                                "preview_metadata",
                                "public_room_count",
                                "public_waypoints",
                                "trusted_category_provenance",
                                "map_build_artifacts",
                            ],
                            "missing_gates": [
                                "public_room_count",
                                "public_waypoints",
                                "trusted_category_provenance",
                                "map_build_artifacts",
                            ],
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

    assert 22 in plan["candidate_indices"]
    assert plan["summary"]["candidate_count"] == 1
    assert plan["summary"]["ready_for_product_smoke_count"] == 1
    assert holodeck["prep_status"] == "ready_for_scanner"
    assert holodeck["candidates"][0]["scanner_status"] == "ready_for_product_smoke"
    assert holodeck["candidates"][0]["world_id"] == "molmospaces/holodeck-objaverse-val/22"
    assert (
        "render_scene_previews.py --world molmospaces/holodeck-objaverse-val/22"
        in (holodeck["candidates"][0]["preview_command"])
    )
    assert (
        "world=molmospaces/holodeck-objaverse-val/22"
        in (holodeck["candidates"][0]["map_build_product_smoke_command"])
    )


def test_scene_sampler_source_prep_install_command_resolves_dict_scene_refs() -> None:
    from roboclaws.worlds.molmospaces.preparation import install_candidate_command

    command = install_candidate_command(
        dataset_name="procthor-10k",
        split="val",
        scene_index=4,
    )

    assert 'mapping = get_scenes("procthor-10k", "val")["val"]' in command
    assert "scene_ref = mapping[4]" in command
    assert "_scene_xml_path_from_ref(scene_ref, get_scenes_root())" in command
    assert "for role in ('base', 'physics', 'ceiling')" in command
    assert "install_scene_with_objects_and_grasps_from_path(scene_path)" in command


def test_scene_sampler_preview_metadata_loads_valid_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(scene_sampler, "_PREVIEW_ROOT", tmp_path)
    payload = {
        "scene_source": "procthor-10k-val",
        "scene_index": 4,
        "backend": scene_sampler.PRIMARY_MOLMOSPACES_BACKEND,
    }
    (tmp_path / "molmospaces-val_4-preview.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    assert scene_sampler._preview_metadata(4) == payload


def test_scene_sampler_scanner_execution_plan_skips_prefilter_inconclusive_sources(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    plan = scanner_execution_plan(candidate_indices=tuple(range(11)))
    ithor = plan["sources"]["ithor"]

    assert plan["schema"] == "molmospaces_scene_sampler_scanner_execution_plan_v1"
    assert plan["download_policy"] == "manual_operator_only"
    assert plan["summary"]["candidate_count"] == 2
    assert plan["summary"]["ready_for_product_smoke_count"] == 0
    assert plan["summary"]["blocked_count"] == 2
    assert plan["summary"]["blocked_source_count"] == 1
    procthor = plan["sources"]["procthor-10k-val"]
    assert procthor["prep_status"] == "blocked_prefilter_inconclusive"
    assert procthor["candidate_count"] == 2
    assert procthor["blocked_count"] == 2
    assert ithor["prep_status"] == "blocked_prefilter_inconclusive"
    assert ithor["candidates"] == []
