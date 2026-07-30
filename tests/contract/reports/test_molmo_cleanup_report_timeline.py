from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup
from tests.contract.reports.molmo_cleanup_report_support import (
    _assert_robot_visual_timeline_layout,
    _assert_robot_visual_timeline_lightbox,
    _assert_robot_visual_timeline_pose_and_focus,
    _assert_robot_visual_timeline_semantic_substeps,
    _assert_robot_visual_timeline_static_isaac_caveat,
    _assert_robot_visual_timeline_yaw_rendering,
    _robot_visual_timeline_report_context,
    _robot_visual_timeline_steps,
)


def test_cleanup_report_renders_robot_visual_timeline(tmp_path: Path) -> None:
    context = _robot_visual_timeline_report_context(tmp_path)
    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=context.scenario,
        run_result=context.run_result,
        trace_events=[],
        before_snapshot=context.before,
        after_snapshot=context.after,
        robot_view_steps=_robot_visual_timeline_steps(),
    )

    html = report_path.read_text(encoding="utf-8")
    _assert_robot_visual_timeline_layout(html)
    _assert_robot_visual_timeline_lightbox(html)
    _assert_robot_visual_timeline_semantic_substeps(html)
    _assert_robot_visual_timeline_pose_and_focus(html)
    _assert_robot_visual_timeline_static_isaac_caveat(html)
    _assert_robot_visual_timeline_yaw_rendering(tmp_path, context)


def test_cleanup_report_renders_runtime_timing_breakdown(tmp_path: Path) -> None:
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
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
    }
    trace_events = [
        {"tool": "<runtime>", "event": "initialized", "wallclock_elapsed": 0.1},
        {"tool": "metric_map", "event": "request", "wallclock_elapsed": 0.2},
        {"tool": "metric_map", "event": "response", "wallclock_elapsed": 0.5},
        {"tool": "static_fixture_projection", "event": "request", "wallclock_elapsed": 1.5},
        {"tool": "static_fixture_projection", "event": "response", "wallclock_elapsed": 1.7},
        {
            "tool": "<runtime>",
            "event": "robot_view_capture",
            "wallclock_elapsed": 2.1,
            "elapsed_s": 0.4,
        },
        {"tool": "done", "event": "request", "wallclock_elapsed": 3.0},
        {"tool": "done", "event": "response", "wallclock_elapsed": 3.2},
    ]
    (tmp_path / "live_timing.json").write_text(
        json.dumps(
            {
                "runner_timing": {
                    "total_elapsed_s": 5.0,
                    "pre_codex_setup_s": 0.5,
                    "codex_exec_elapsed_s": 3.5,
                    "checker_elapsed_s": 0.4,
                    "final_overhead_s": 0.1,
                }
            }
        ),
        encoding="utf-8",
    )

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=trace_events,
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert 'class="report-tabs"' in html
    assert "scrollIntoView" in html
    assert 'block: "start"' in html
    assert "Runtime Timing" in html
    assert "Run wall clock" in html
    assert "MCP trace attribution" in html
    assert "Tool and gap tables" in html
    assert "MCP elapsed" in html
    assert "3.2s" in html
    assert "Tool/backend handling" in html
    assert "0.7s" in html
    assert "Robot-view capture" in html
    assert "0.4s" in html
    assert "Between-tool gap" in html
    assert "1.9s" in html
    assert "Other MCP overhead" in html
    assert "0.2s" in html
    assert "static_fixture_projection" in html


def test_cleanup_report_renders_per_object_timing_cycles(tmp_path: Path) -> None:
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
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
    }
    trace_events = [
        {
            "tool": "navigate_to_visual_candidate",
            "event": "request",
            "request": {},
            "wallclock_elapsed": 1.0,
        },
        {
            "tool": "navigate_to_visual_candidate",
            "event": "response",
            "response": {"ok": True, "object_id": "mug_01"},
            "wallclock_elapsed": 1.1,
        },
        {
            "tool": "<runtime>",
            "event": "robot_view_capture",
            "wallclock_elapsed": 2.0,
            "elapsed_s": 0.4,
        },
        {
            "tool": "pick",
            "event": "request",
            "request": {"object_id": "mug_01"},
            "wallclock_elapsed": 2.2,
        },
        {
            "tool": "pick",
            "event": "response",
            "response": {"ok": True, "object_id": "mug_01"},
            "wallclock_elapsed": 2.3,
        },
        {
            "tool": "navigate_to_receptacle",
            "event": "request",
            "request": {"fixture_id": "sink_01"},
            "wallclock_elapsed": 3.0,
        },
        {
            "tool": "navigate_to_receptacle",
            "event": "response",
            "response": {"ok": True, "object_id": "mug_01", "fixture_id": "sink_01"},
            "wallclock_elapsed": 3.1,
        },
        {
            "tool": "place",
            "event": "request",
            "request": {"fixture_id": "sink_01"},
            "wallclock_elapsed": 4.0,
        },
        {
            "tool": "place",
            "event": "response",
            "response": {"ok": True, "object_id": "mug_01", "fixture_id": "sink_01"},
            "wallclock_elapsed": 4.1,
        },
        {"tool": "observe", "event": "request", "request": {}, "wallclock_elapsed": 5.0},
        {
            "tool": "observe",
            "event": "response",
            "response": {"ok": True},
            "wallclock_elapsed": 5.5,
        },
        {
            "tool": "navigate_to_object",
            "event": "request",
            "request": {"object_id": "towel_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "navigate_to_object",
            "event": "response",
            "response": {"ok": True, "object_id": "towel_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "pick",
            "event": "request",
            "request": {"object_id": "towel_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "pick",
            "event": "response",
            "response": {"ok": True, "object_id": "towel_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "navigate_to_receptacle",
            "event": "request",
            "request": {"fixture_id": "hamper_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "navigate_to_receptacle",
            "event": "response",
            "response": {"ok": True, "object_id": "towel_01", "fixture_id": "hamper_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "place",
            "event": "request",
            "request": {"fixture_id": "hamper_01"},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "place",
            "event": "response",
            "response": {"ok": True, "object_id": "towel_01", "fixture_id": "hamper_01"},
            "wallclock_elapsed": 6.0,
        },
        {"tool": "observe", "event": "request", "request": {}, "wallclock_elapsed": 6.0},
        {
            "tool": "observe",
            "event": "response",
            "response": {"ok": True},
            "wallclock_elapsed": 6.0,
        },
        {
            "tool": "navigate_to_object",
            "event": "request",
            "request": {"object_id": "book_01"},
            "wallclock_elapsed": 7.0,
        },
        {
            "tool": "navigate_to_object",
            "event": "response",
            "response": {"ok": True, "object_id": "book_01"},
            "wallclock_elapsed": 7.001,
        },
        {
            "tool": "pick",
            "event": "request",
            "request": {"object_id": "book_01"},
            "wallclock_elapsed": 7.001,
        },
        {
            "tool": "pick",
            "event": "response",
            "response": {"ok": True, "object_id": "book_01"},
            "wallclock_elapsed": 7.002,
        },
        {
            "tool": "navigate_to_receptacle",
            "event": "request",
            "request": {"fixture_id": "bookshelf_01"},
            "wallclock_elapsed": 7.002,
        },
        {
            "tool": "navigate_to_receptacle",
            "event": "response",
            "response": {
                "ok": True,
                "object_id": "book_01",
                "fixture_id": "bookshelf_01",
            },
            "wallclock_elapsed": 7.003,
        },
        {
            "tool": "place",
            "event": "request",
            "request": {"fixture_id": "bookshelf_01"},
            "wallclock_elapsed": 7.003,
        },
        {
            "tool": "place",
            "event": "response",
            "response": {"ok": True, "object_id": "book_01", "fixture_id": "bookshelf_01"},
            "wallclock_elapsed": 7.004,
        },
        {"tool": "observe", "event": "request", "request": {}, "wallclock_elapsed": 7.004},
        {
            "tool": "observe",
            "event": "response",
            "response": {"ok": True},
            "wallclock_elapsed": 7.004,
        },
    ]

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=trace_events,
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert "Per-object cleanup cycles" in html
    assert "mug_01" in html
    assert "towel_01" in html
    assert "book_01" in html
    assert "Agent thinking / orchestration" in html
    assert "response-to-next-request time" in html
    assert "Sweep/search overhead" in html
    assert "no projections" in html
    assert "navigate_to_visual_candidate -&gt; pick" in html
    assert html.count("<h3>Measured distribution</h3>") == 3
    assert html.count("<strong>No measurable split</strong>") == 2
    assert "timestamps were identical" in html
    assert "<strong>Tool handlers</strong><span>0.0s</span>" not in html


def test_cleanup_report_labels_observe_roles_and_zero_pixel_focus(tmp_path: Path) -> None:
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
    robot_dir = tmp_path / "robot_views"
    robot_dir.mkdir()
    for name in (
        "place.fpv.png",
        "post.fpv.png",
        "scan.fpv.png",
        "nav.fpv.png",
        "nav.verify.png",
    ):
        (robot_dir / name).write_bytes(b"placeholder")

    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "cleanup_policy_trace": {
            "waypoint_source": "static_map_fixture_coverage",
            "loop_style": "interleaved_cleanup_loop",
            "scan_observe_count": 1,
            "cleanup_action_count": 2,
            "post_place_observe_count": 1,
            "post_place_observe_complete": True,
            "first_cleanup_before_full_survey": True,
            "events": [],
        },
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
        robot_view_steps=[
            {
                "action": "place observed_001",
                "semantic_phase": "place",
                "robot_pose": {},
                "views": {"fpv": "robot_views/place.fpv.png"},
                "focus": {},
            },
            {
                "action": "observe",
                "robot_pose": {},
                "views": {"fpv": "robot_views/post.fpv.png"},
                "focus": {},
            },
            {
                "action": "observe",
                "robot_pose": {},
                "views": {"fpv": "robot_views/scan.fpv.png"},
                "focus": {},
            },
            {
                "action": "navigate_to_object observed_002",
                "semantic_phase": "navigate_to_object",
                "robot_pose": {},
                "views": {
                    "fpv": "robot_views/nav.fpv.png",
                    "verify": "robot_views/nav.verify.png",
                },
                "focus": {
                    "has_focus": True,
                    "object_label": "Book book",
                    "receptacle_label": "DiningTable diningtable",
                    "provenance": "public_mujoco_state_report_aid",
                    "fpv_visibility": {
                        "status": "ok",
                        "object_pixels": 0,
                        "receptacle_pixels": 57359,
                    },
                    "visibility": {
                        "status": "ok",
                        "object_pixels": 0,
                        "receptacle_pixels": 55138,
                    },
                },
            },
        ],
    )

    html = report_path.read_text(encoding="utf-8")
    assert "post-place verification" in html
    assert "post_place_observe" in html
    assert "waypoint scan" in html
    assert "coverage_scan_observe" in html
    assert "close_receptacle" in html
    assert "Handle: <strong>observed_002</strong>" in html
    assert "Book book" in html
    assert "weak_object_visibility" in html
    assert "object not visible, target 57359 px" in html
    assert "object not visible, target 55138 px" in html
    assert "object 0 px" not in html


def test_cleanup_report_renders_raw_fpv_observations(tmp_path: Path) -> None:
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
    fpv = tmp_path / "robot_views" / "raw.fpv.png"
    fpv.parent.mkdir()
    fpv.write_bytes(b"placeholder")
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": "failed",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "agent_view": {
            "perception_mode": "raw_fpv_only",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "observed_objects": [],
            "raw_fpv_observations": [
                {
                    "observation_id": "raw_fpv_001",
                    "room_id": "kitchen",
                    "waypoint_id": "kitchen_scan_1",
                    "perception_mode": "raw_fpv_only",
                    "structured_detections_available": False,
                    "artifact_status": "recorded",
                    "image_artifacts": {"fpv": "robot_views/raw.fpv.png"},
                }
            ],
        },
        "raw_fpv_observations": [
            {
                "observation_id": "raw_fpv_001",
                "room_id": "kitchen",
                "waypoint_id": "kitchen_scan_1",
                "perception_mode": "raw_fpv_only",
                "structured_detections_available": False,
                "artifact_status": "recorded",
                "image_artifacts": {"fpv": "robot_views/raw.fpv.png"},
            }
        ],
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
    assert "Agent View" in html
    assert "Raw FPV Observations" in html
    assert "raw_fpv_001" in html
    assert "robot_views/raw.fpv.png" in html
    assert "support estimates" in html


def test_cleanup_report_keeps_raw_fpv_scans_out_of_primary_robot_timeline(
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
    robot_dir = tmp_path / "robot_views"
    robot_dir.mkdir()
    for name in ("raw.fpv.png", "nav.fpv.png", "after.fpv.png"):
        (robot_dir / name).write_bytes(b"placeholder")
    camera_contract = {
        "schema": "robot_view_camera_control_contract_v1",
        "status": "backend_local_robot_camera",
        "camera_model": "backend_local_robot_view",
        "same_pose_api": False,
        "lighting_profile": {"profile_id": "scene_probe_existing_usd_lights_v1"},
        "color_profile": {"profile_id": "display_srgb_soft_highlight_v1"},
        "agent_facing_fpv": {
            "source": "robot_0/head_camera",
            "canonical_camera_control": False,
        },
    }
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "semantic_substeps": [
            {
                "object_id": "observed_001",
                "source_receptacle_id": "counter_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {"phase": "navigate_to_object"},
                    {"phase": "pick"},
                    {"phase": "navigate_to_receptacle"},
                    {"phase": "place", "location_id": "sink_01"},
                ],
            }
        ],
        "agent_view": {
            "perception_mode": "raw_fpv_only",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "observed_objects": [],
            "raw_fpv_observations": [
                {
                    "observation_id": "raw_fpv_001",
                    "room_id": "kitchen",
                    "waypoint_id": "kitchen_scan_1",
                    "perception_mode": "raw_fpv_only",
                    "structured_detections_available": False,
                    "artifact_status": "recorded",
                    "image_artifacts": {"fpv": "robot_views/raw.fpv.png"},
                    "camera_control_contract": camera_contract,
                }
            ],
        },
        "raw_fpv_observations": [
            {
                "observation_id": "raw_fpv_001",
                "room_id": "kitchen",
                "waypoint_id": "kitchen_scan_1",
                "perception_mode": "raw_fpv_only",
                "structured_detections_available": False,
                "artifact_status": "recorded",
                "image_artifacts": {"fpv": "robot_views/raw.fpv.png"},
                "camera_control_contract": camera_contract,
            }
        ],
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
        robot_view_steps=[
            {
                "action": "before",
                "robot_pose": {},
                "views": {"fpv": "robot_views/nav.fpv.png"},
                "focus": {},
            },
            {
                "label": "0001_raw_fpv_001",
                "action": "observe raw_fpv_001",
                "robot_pose": {},
                "views": {"fpv": "robot_views/raw.fpv.png"},
                "camera_control_contract": camera_contract,
                "focus": {},
            },
            {
                "action": "navigate_to_visual_candidate observed_001",
                "semantic_phase": "navigate_to_object",
                "action_evidence": {
                    "schema": "robot_timeline_action_evidence_v1",
                    "agent_tool": "navigate_to_visual_candidate",
                    "agent_action": "navigate_to_visual_candidate observed_001",
                    "backend_primitive": "navigate_to_object",
                    "resolved_object_id": "observed_001",
                    "source_observation_id": "raw_fpv_001",
                    "source_image_bbox": [10, 20, 30, 40],
                    "reviewability_status": "reviewable",
                    "grounding_status": "resolved",
                    "grounding_confidence": 0.72,
                    "declared_category": "dish",
                    "evidence_note": "white dish visible in the FPV crop",
                },
                "robot_pose": {},
                "views": {"fpv": "robot_views/nav.fpv.png"},
                "focus": {},
            },
            {
                "action": "after",
                "robot_pose": {},
                "views": {"fpv": "robot_views/after.fpv.png"},
                "focus": {},
            },
        ],
    )

    html = report_path.read_text(encoding="utf-8")
    timeline_html = html[html.index("<h2>Robot View Timeline</h2>") : html.index("<h2>Score</h2>")]
    raw_fpv_html = html[html.index("<h2>Raw FPV Observations</h2>") :]
    assert "navigate_to_visual_candidate observed_001" in timeline_html
    assert "Subphase: <strong>nav</strong>" in timeline_html
    assert "Agent tool: <strong>navigate_to_visual_candidate</strong>" in timeline_html
    assert "Source observe: <strong>raw_fpv_001</strong>" in timeline_html
    assert "Source FPV bbox: <strong>[10, 20, 30, 40]</strong>" in timeline_html
    assert "Grounding: <strong>resolved (0.72)</strong>" in timeline_html
    assert "Backend primitive: <strong>navigate_to_object</strong>" in timeline_html
    assert "Declared category: <strong>dish</strong>" in timeline_html
    assert "white dish visible in the FPV crop" in timeline_html
    assert "robot_views/raw.fpv.png" not in timeline_html
    assert "raw_fpv_001" in raw_fpv_html
    assert "robot_views/raw.fpv.png" in raw_fpv_html
    assert "Camera contract" in raw_fpv_html
    assert "backend_local_robot_camera" in raw_fpv_html
    assert "Head-camera FPV" in raw_fpv_html
    assert "scene_probe_existing_usd_lights_v1" in raw_fpv_html
    assert "display_srgb_soft_highlight_v1" in raw_fpv_html


def test_cleanup_report_renders_world_label_navigation_evidence(tmp_path: Path) -> None:
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
    robot_dir = tmp_path / "robot_views"
    robot_dir.mkdir()
    Image.new("RGB", (32, 24), color=(230, 230, 230)).save(robot_dir / "nav.fpv.png")
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
        robot_view_steps=[
            {
                "action": "observe",
                "robot_pose": {},
                "views": {"fpv": "robot_views/nav.fpv.png"},
                "focus": {},
            },
            {
                "action": "navigate_to_object observed_001",
                "semantic_phase": "navigate_to_object",
                "action_evidence": {
                    "schema": "robot_timeline_action_evidence_v1",
                    "agent_tool": "navigate_to_object",
                    "agent_action": "navigate_to_object observed_001",
                    "backend_primitive": "navigate_to_object",
                    "resolved_object_id": "observed_001",
                    "source_observation_id": (
                        "visible_detection:generated_exploration_001:observed_001"
                    ),
                    "source_image_bbox": [81, 65, 42, 31],
                    "reviewability_status": "reviewable",
                },
                "robot_pose": {},
                "views": {"fpv": "robot_views/nav.fpv.png"},
                "focus": {},
            },
        ],
    )

    timeline_html = report_path.read_text(encoding="utf-8")
    timeline_html = timeline_html[
        timeline_html.index("<h2>Robot View Timeline</h2>") : timeline_html.index("<h2>Score</h2>")
    ]
    assert "navigate_to_object observed_001" in timeline_html
    assert "Agent tool: <strong>navigate_to_object</strong>" in timeline_html
    assert (
        "Source observe: <strong>visible_detection:generated_exploration_001:observed_001</strong>"
        in timeline_html
    )
    assert "Source FPV bbox: <strong>[81, 65, 42, 31]</strong>" in timeline_html
    assert "Backend primitive: <strong>navigate_to_object</strong>" in timeline_html


def test_cleanup_report_renders_camera_model_policy(tmp_path: Path) -> None:
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
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "agent_view": {
            "perception_mode": "camera_model_policy",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "raw_fpv_observations": [
                {
                    "observation_id": "raw_fpv_001",
                    "room_id": "kitchen",
                    "waypoint_id": "kitchen_scan_1",
                    "perception_mode": "camera_model_policy",
                    "structured_detections_available": False,
                    "artifact_status": "pending_robot_view_capture",
                    "image_artifacts": {},
                }
            ],
            "observed_objects": [
                {
                    "object_id": "observed_001",
                    "category": "dish",
                    "name": "Mug",
                    "current_room_id": "kitchen",
                    "perception_source": "camera_model_policy",
                    "model_provenance": "simulated_camera_model",
                    "source_observation_id": "raw_fpv_001",
                    "support_estimate": {
                        "fixture_id": "coffee_table_01",
                        "source": "camera_model_policy",
                        "model_provenance": "simulated_camera_model",
                    },
                }
            ],
            "camera_model_policy_evidence": {
                "schema": "camera_model_policy_v1",
                "enabled": True,
                "model_provenance": "simulated_camera_model",
                "event_count": 1,
                "candidate_count": 1,
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
            "model_declared_observation_evidence": {
                "schema": "model_declared_observations_v1",
                "observation_count": 1,
                "resolved_count": 1,
                "acted_count": 1,
                "private_truth_included": False,
                "observations": [
                    {
                        "object_id": "observed_001",
                        "source_observation_id": "raw_fpv_001",
                        "producer_type": "simulated_camera_model",
                        "producer_id": "camera_labels_agent",
                        "category": "dish",
                        "target_fixture_id": "sink_01",
                        "image_region": {"type": "bbox", "value": [1, 2, 3, 4]},
                        "evidence_note": "mug on table",
                        "grounding_status": "resolved",
                        "grounding_confidence": 0.81,
                        "grounding_basis": "single public match",
                        "recovery_hint": "",
                        "target_plausibility": {"status": "plausible"},
                        "acted_on": True,
                        "private_truth_included": False,
                    }
                ],
            },
        },
    }
    run_result["raw_fpv_observations"] = run_result["agent_view"]["raw_fpv_observations"]
    run_result["camera_model_policy_evidence"] = run_result["agent_view"][
        "camera_model_policy_evidence"
    ]
    run_result["model_declared_observations"] = run_result["agent_view"][
        "model_declared_observation_evidence"
    ]["observations"]
    run_result["model_declared_observation_evidence"] = run_result["agent_view"][
        "model_declared_observation_evidence"
    ]

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert "Camera Labeler Evidence" in html
    assert "Model-Declared Observations" in html
    assert "simulated_camera_model" in html
    assert "observed_001" in html
    assert "raw_fpv_001" in html
    assert "Raw FPV Observations" in html
