from __future__ import annotations

import json
from pathlib import Path

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
