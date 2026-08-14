from __future__ import annotations

from pathlib import Path

from PIL import Image

from roboclaws.household.advisory_scoring import build_advisory_evaluation
from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup


def test_state_snapshot_keeps_bottom_row_objects_visible(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    locations = {
        obj.object_id: ("bookshelf_01", "laundry_hamper_01", "fridge_01")[index % 3]
        for index, obj in enumerate(scenario.objects)
    }

    snapshot = write_state_snapshot(
        scenario,
        locations,
        tmp_path / "bottom-row.png",
        title="Bottom row",
    )

    image = Image.open(snapshot).convert("RGB")
    background = (249, 250, 252)
    marker_colors = {(117, 86, 160), (78, 154, 96), (206, 108, 65)}
    bottom_marker_pixels = [
        image.getpixel((x, y))
        for y in range(509, 530)
        for x in range(image.width)
        if image.getpixel((x, y)) in marker_colors
    ]
    assert image.size == (900, 580)
    assert all(image.getpixel((x, image.height - 1)) == background for x in range(image.width))
    assert bottom_marker_pixels


def test_cleanup_report_explains_nav2_map_bundle_contract(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    map_bundle = tmp_path / "map_bundle"
    map_bundle.mkdir()
    Image.new("RGB", (320, 180), (247, 249, 252)).save(map_bundle / "preview.png")
    Image.new("RGB", (900, 560), (247, 249, 252)).save(tmp_path / "runtime_metric_map_preview.png")
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "nav2_map_bundle": {
            "environment_id": "molmospaces-procthor-val-0-7",
            "robot_profile_id": "rby1m",
            "costmap_profile_id": "rby1m_static_global",
            "parameter_hash": "abcdef0123456789",
            "map_id": "molmospaces-procthor-val-0-7_base_metric_map",
            "source_provenance": "molmospaces_base_metric_map",
            "source_schema": "nav2_cleanup_semantics_v1",
            "source_bundle_root": "assets/maps/molmospaces-procthor-val-0-7",
            "artifact_paths": {
                "map_yaml": "map_bundle/map.yaml",
                "occupancy_image": "map_bundle/map.pgm",
                "semantics_json": "map_bundle/semantics.json",
                "robot_profile": "map_bundle/profiles/rby1m.yaml",
                "costmap_params": "map_bundle/costmaps/rby1m.costmap_params.yaml",
                "preview_png": "map_bundle/preview.png",
            },
            "artifact_hashes": {"map_yaml": "abcdef0123456789"},
            "runtime_costmap_gaps": ["tf_timing_not_simulated"],
        },
        "artifacts": {
            "runtime_metric_map": str(tmp_path / "runtime_metric_map.json"),
            "runtime_metric_map_preview": str(tmp_path / "runtime_metric_map_preview.png"),
        },
        "agent_view": {
            "metric_map": {
                "rooms": [
                    {
                        "room_id": "room_1",
                        "room_label": "room 1",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 2.0, "y": 0.0},
                            {"x": 2.0, "y": 2.0},
                            {"x": 0.0, "y": 2.0},
                        ],
                    }
                ],
                "inspection_waypoints": [{"waypoint_id": "room_1_scan_1", "x": 1.0, "y": 1.0}],
                "robot_pose": {"x": 1.0, "y": 1.0},
            },
            "static_fixture_projection": {
                "rooms": [
                    {
                        "room_id": "room_1",
                        "fixtures": [
                            {
                                "category": "Sink",
                                "name": "Sink (Sink|1|0)",
                                "pose": {"x": 0.4, "y": 0.3},
                                "footprint": {"width_m": 0.5, "depth_m": 0.4},
                            }
                        ],
                    }
                ]
            },
        },
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert (
        "Base Metric Map Preview <span>Nav2 Map Bundle / Agibot-shaped static map contract</span>"
    ) in html
    assert "What it proves" in html
    assert "What it does not prove" in html
    assert "Agibot-shaped base navigation map preview" in html
    assert "molmospaces_base_metric_map" in html
    assert "not a real Agibot GDK map" in html
    assert 'src="map_bundle/preview.png"' in html
    assert "semantic_map.png" not in html
    assert "map_overlay.json" not in html
    assert "report_static_navigation_map.png" not in html
    assert "Green dots" in html
    assert "Runtime Metric Map preview" in html
    assert 'src="runtime_metric_map_preview.png"' in html
    assert "not a camera image" in html
    assert "Map files, hashes, and known gaps" in html
    assert "tf_timing_not_simulated" in html
    assert not (tmp_path / "map_bundle" / "report_static_navigation_map.png").exists()
    assert not (tmp_path / "semantic_map.png").exists()
    assert not (tmp_path / "map_overlay.json").exists()


def test_cleanup_report_does_not_generate_schematic_preview_when_occupancy_frame_is_degenerate(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    map_bundle = tmp_path / "map_bundle"
    map_bundle.mkdir()
    Image.new("L", (411, 190), 0).save(map_bundle / "map.pgm")
    (map_bundle / "map.yaml").write_text(
        "\n".join(
            [
                "image: map.pgm",
                "resolution: 0.050000",
                "origin: [0.000000, 0.000000, 0.000000]",
                "negate: 0",
                "occupied_thresh: 0.650000",
                "free_thresh: 0.250000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    Image.new("RGB", (320, 180), (247, 249, 252)).save(map_bundle / "preview.png")
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "nav2_map_bundle": {
            "environment_id": "molmospaces-procthor-val-0-7",
            "robot_profile_id": "rby1m",
            "costmap_profile_id": "rby1m_static_global",
            "parameter_hash": "abcdef0123456789",
            "map_id": "molmospaces-procthor-val-0-7_base_metric_map",
            "source_provenance": "molmospaces_base_metric_map",
            "artifact_paths": {
                "map_yaml": "map_bundle/map.yaml",
                "occupancy_image": "map_bundle/map.pgm",
                "preview_png": "map_bundle/preview.png",
            },
            "artifact_hashes": {"map_yaml": "abcdef0123456789"},
            "runtime_costmap_gaps": [],
        },
        "agent_view": {
            "metric_map": {
                "rooms": [
                    {
                        "room_id": "room_1",
                        "room_label": "room 1",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 2.0, "y": 0.0},
                            {"x": 2.0, "y": 2.0},
                            {"x": 0.0, "y": 2.0},
                        ],
                    }
                ],
                "inspection_waypoints": [{"waypoint_id": "room_1_scan_1", "x": 1.0, "y": 1.0}],
                "robot_pose": {"x": 1.0, "y": 1.0},
            },
            "static_fixture_projection": {"rooms": []},
        },
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert 'src="map_bundle/preview.png"' in html
    assert "report_static_navigation_map.png" not in html
    assert not (map_bundle / "report_static_navigation_map.png").exists()


def test_cleanup_report_keeps_visual_core_before_audit_sections(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    final_locations = scenario.object_locations()
    final_locations.update({"mug_01": "sink_01"})
    score = score_cleanup(final_locations, scenario.private_manifest).to_dict()
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(scenario, final_locations, tmp_path / "after.png", title="After")
    semantic_substeps = [
        {
            "object_id": "observed_001",
            "source_receptacle_id": "table_01",
            "target_receptacle_id": "sink_01",
            "steps": [
                {"phase": "navigate_to_object", "primitive_provenance": API_SEMANTIC_PROVENANCE},
                {"phase": "pick", "primitive_provenance": API_SEMANTIC_PROVENANCE},
                {
                    "phase": "navigate_to_receptacle",
                    "primitive_provenance": API_SEMANTIC_PROVENANCE,
                },
                {
                    "phase": "place",
                    "location_id": "sink_01",
                    "primitive_provenance": API_SEMANTIC_PROVENANCE,
                },
            ],
        }
    ]
    run_result = {
        "contract": "realworld_cleanup_v1",
        "backend": "api_semantic_synthetic",
        "cleanup_status": score["status"],
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "policy": "camera_model_policy_baseline",
        "score": score,
        "semantic_substeps": semantic_substeps,
        "cleanup_primitive_evidence": cleanup_primitive_evidence_from_substeps(semantic_substeps),
        "agent_view": {
            "perception_mode": "camera_model_policy",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "observed_objects": [
                {
                    "object_id": "observed_001",
                    "category": "dish",
                    "support_estimate": {"fixture_id": "table_01"},
                    "source_observation_id": "raw_fpv_001",
                    "model_provenance": "simulated_camera_model",
                }
            ],
            "raw_fpv_observations": [
                {
                    "observation_id": "raw_fpv_001",
                    "room_id": "kitchen",
                    "waypoint_id": "kitchen_scan_1",
                    "artifact_status": "recorded",
                    "image_artifacts": {"fpv": "robot_views/raw.fpv.png"},
                }
            ],
            "camera_model_policy_evidence": {
                "enabled": True,
                "event_count": 1,
                "candidate_count": 1,
                "model_provenance": "simulated_camera_model",
                "private_truth_included": False,
                "events": [
                    {
                        "observation_id": "raw_fpv_001",
                        "room_id": "kitchen",
                        "model_provenance": "simulated_camera_model",
                        "candidate_count": 1,
                        "registered_observed_handles": ["observed_001"],
                    }
                ],
            },
        },
        "raw_fpv_observations": [
            {
                "observation_id": "raw_fpv_001",
                "room_id": "kitchen",
                "waypoint_id": "kitchen_scan_1",
                "artifact_status": "recorded",
                "image_artifacts": {"fpv": "robot_views/raw.fpv.png"},
            }
        ],
        "camera_model_policy_evidence": {
            "enabled": True,
            "event_count": 1,
            "candidate_count": 1,
            "model_provenance": "simulated_camera_model",
            "private_truth_included": False,
            "events": [
                {
                    "observation_id": "raw_fpv_001",
                    "room_id": "kitchen",
                    "model_provenance": "simulated_camera_model",
                    "candidate_count": 1,
                    "registered_observed_handles": ["observed_001"],
                }
            ],
        },
        "advisory_evaluation": build_advisory_evaluation(
            score=score,
            scenario_id=scenario.scenario_id,
        ),
        "private_evaluation": {
            "generated_mess_count": 1,
            "generated_mess_set": ["mug_01"],
            "acceptable_destination_sets": {"mug_01": ["sink_01"]},
            "mess_restoration_rate": 1.0,
            "sweep_coverage_rate": 1.0,
            "disturbance_count": 0,
        },
    }
    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[
            {
                "tool": "place",
                "event": "response",
                "response": {
                    "ok": True,
                    "object_id": "observed_001",
                    "receptacle_id": "sink_01",
                    "primitive_provenance": API_SEMANTIC_PROVENANCE,
                },
            }
        ],
        before_snapshot=before,
        after_snapshot=after,
        robot_view_steps=[
            {
                "action": "place observed_001",
                "semantic_phase": "place",
                "robot_pose": {},
                "views": {"fpv": "robot_views/place.fpv.png"},
                "focus": {},
            }
        ],
    )

    html = report_path.read_text(encoding="utf-8")
    ordered_headings = [
        "<h2>Before And After</h2>",
        "<h2>Object Moves</h2>",
        "<h2>Robot View Timeline</h2>",
        "<h2>Semantic Substeps</h2>",
        "<h2>Score</h2>",
        "<h2>Cleanup Primitive Gate</h2>",
        "<h2>Agent View</h2>",
        "<h2>Raw FPV Observations</h2>",
        "<h2>Camera Labeler Evidence</h2>",
        "<h2>Advisory Review</h2>",
        "<h2>Private Evaluation</h2>",
    ]
    positions = [html.index(heading) for heading in ordered_headings]
    assert positions == sorted(positions)
    assert "<td>place</td>" in html
    assert "<td>surface</td>" in html
