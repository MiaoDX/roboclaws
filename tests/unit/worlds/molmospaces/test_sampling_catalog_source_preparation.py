from __future__ import annotations

import json
from pathlib import Path

from roboclaws.worlds.molmospaces.sampling import (
    READINESS_BLOCKED,
    scanner_execution_plan,
    source_prep_report,
)
from tests.unit.worlds.molmospaces.sampling_support import (
    _assert_partial_procthor_source_prep,
)


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
