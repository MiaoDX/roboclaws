from __future__ import annotations

from roboclaws.worlds.molmospaces.sampling import (
    READINESS_BLOCKED,
    scanner_admission_report,
    selection_gap_report,
)


def test_scene_sampler_selection_gap_report_records_expanded_range_capacity(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = selection_gap_report(candidate_indices=tuple(range(20)))

    assert report["summary"]["candidate_range_insufficient_source_count"] == 0
    assert report["summary"]["candidate_range_sufficient_source_count"] == 1
    assert report["summary"]["source_prep_required_count"] == 1
    assert report["summary"]["next_actions"] == {
        "run_source_prep_before_scanner": 1,
        "do_not_scan_without_new_human_curation": 2,
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["selection_capacity_status"] == "candidate_range_sufficient"
    assert procthor["next_action"] == "run_source_prep_before_scanner"
    assert procthor["eval_scan_candidate_count"] == 4
    assert procthor["next_eval_scan_world_ids"] == [
        "molmospaces/procthor-10k-val/16",
        "molmospaces/procthor-10k-val/19",
        "molmospaces/procthor-10k-val/18",
        "molmospaces/procthor-10k-val/17",
    ]
    assert report["sources"]["procthor-objaverse-val"]["selection_capacity_status"] == "complete"
    assert (
        report["sources"]["holodeck-objaverse-val"]["selection_capacity_status"]
        == "rejected_exhausted"
    )


def test_scene_sampler_scanner_admission_accepts_reviewable_prepared_label_packets(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "candidate_readiness_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "ui_ready_count": 0,
                    "eval_ready_count": 0,
                    "candidates": []
                    if source != "ithor"
                    else [
                        {
                            "scene_family": "ithor",
                            "scene_split": "not_applicable",
                            "scene_source": "ithor",
                            "scene_index": 1,
                            "world_id": "molmospaces/ithor/1",
                            "readiness_status": READINESS_BLOCKED,
                            "lanes": [],
                            "eval_ready": False,
                            "failure_class": "environment_blocked",
                            "blocked_reason": "map build product smoke pending",
                            "selected_reason": "scanner_candidate_ready_for_product_smoke",
                            "room_count": 4,
                            "waypoint_count": 4,
                            "category_provenance": "prepared_visual_label_manifest",
                            "preview_statuses": {
                                "fpv": "reviewable",
                                "map": "reviewable",
                                "chase": "reviewable",
                                "topdown": "reviewable",
                            },
                            "candidate_file": {
                                "exists": True,
                                "path": "/tmp/FloorPlan1_physics.xml",
                            },
                        }
                    ],
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
                    "ui_needed_count": 3 if source == "ithor" else 0,
                    "eval_needed_count": 10 if source == "ithor" else 0,
                    "next_scan_candidates": [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    report = scanner_admission_report(candidate_indices=(1,))
    row = report["sources"]["ithor"]["admission_rows"][0]

    assert row["admission_status"] == "blocked"
    assert row["passed_gates"] == [
        "source_asset_available",
        "preview_metadata",
        "public_room_count",
        "public_waypoints",
        "trusted_category_provenance",
    ]
    assert row["missing_gates"] == ["map_build_artifacts"]
    assert row["next_action"] == "run_map_build_product_smoke_before_eval_admission"
