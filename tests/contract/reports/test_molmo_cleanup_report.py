from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from roboclaws.household.advisory_scoring import build_advisory_evaluation
from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.manipulation_provenance import (
    api_semantic_manipulation_evidence,
    blocked_planner_probe_evidence,
    planner_backed_probe_evidence,
)
from roboclaws.household.rby1m_curobo_gate import (
    rby1m_curobo_gate_from_planner_probe,
)
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_planner import (
    render_planner_manipulation_report,
    render_planner_proof_bundle_runner_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup
from roboclaws.household.semantic_timeline import SEMANTIC_LOOP_DISPLAY_NOTE


def test_cleanup_report_renders_score_moves_and_provenance(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    final_locations = scenario.object_locations()
    final_locations.update({"mug_01": "sink_01", "book_01": "bookshelf_01"})
    score = score_cleanup(final_locations, scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(scenario, final_locations, tmp_path / "after.png", title="After")
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend="api_semantic_synthetic",
            primitive_summary={API_SEMANTIC_PROVENANCE: 1},
        ),
        "score": score.to_dict(),
        "advisory_evaluation": build_advisory_evaluation(
            score=score.to_dict(),
            scenario_id=scenario.scenario_id,
        ),
    }
    trace_events = [
        {
            "tool": "place",
            "event": "response",
            "response": {
                "ok": True,
                "object_id": "mug_01",
                "receptacle_id": "sink_01",
                "primitive_provenance": API_SEMANTIC_PROVENANCE,
            },
        }
    ]
    run_result["cleanup_primitive_evidence"] = cleanup_primitive_evidence_from_substeps(
        [
            {
                "object_id": "mug_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {
                        "phase": "navigate_to_object",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                    },
                    {
                        "phase": "pick",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                    },
                    {
                        "phase": "navigate_to_receptacle",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                    },
                    {
                        "phase": "place",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                        "state_mutation": "mujoco_freejoint_qpos",
                    },
                ],
            }
        ]
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
    assert "MolmoSpaces Cleanup Pilot" in html
    assert "Rerun Locally" not in html
    assert "rerun_command" not in run_result
    assert "api_semantic" in html
    assert "Manipulation Provenance" in html
    assert "Cleanup Primitive Gate" in html
    assert "<td>nav</td>" in html
    assert "<td>object</td>" in html
    assert "mujoco_freejoint_qpos" in html
    assert "does not prove planner-backed robot manipulation" in html
    assert "mug_01" in html
    assert "Semantic acceptability" in html
    assert "Advisory Review" in html
    assert "authoritative=false" in html
    assert "valid_receptacle_ids" not in html
    assert before.is_file()
    assert after.is_file()


def test_cleanup_report_prefers_recorded_rerun_command(
    tmp_path: Path,
    monkeypatch,
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
    prior = "output/household/household-world/map-build/anchor/seed-7/runtime_metric_map.json"
    command = (
        "just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 "
        "backend=mujoco intent=cleanup agent_engine=openai-agents-sdk "
        "provider_profile=kimi-openai-chat evidence_lane=world-public-labels seed=7 "
        "scenario_setup=relocate-cleanup-related-objects relocation_count=5 "
        "robot_views=on "
        f"runtime_map_prior={prior} "
        "output_dir=output/household/cleanup/sdk-from-semantic-map-with-views"
    )
    monkeypatch.setenv(
        "ROBOCLAWS_REPORT_RERUN_COMMAND",
        "just run::surface surface=household-world agent_engine=direct-runner "
        "intent=cleanup evidence_lane=world-public-labels seed=7",
    )
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "rerun_command": command,
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
    assert "just run::surface \\\n" in html
    assert "surface=household-world" in html
    assert "agent_engine=openai-agents-sdk" in html
    assert "provider_profile=kimi-openai-chat" in html
    assert f"runtime_map_prior={prior}" in html
    assert run_result["rerun_command"] == command
    assert "household-cleanup direct world-public-labels" not in html


def test_cleanup_report_surfaces_failure_reason_on_summary(tmp_path: Path) -> None:
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
    reason = (
        "Task could not be completed with public robot capabilities; "
        "generated_exploration_004 was blocked by goal_occupied."
    )
    run_result = {
        "cleanup_status": "failed",
        "completion_status": "failed",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": {**score.to_dict(), "completion_summary": "less specific summary"},
        "terminate_reason": reason,
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
    assert "Failure Reason" in html
    assert reason in html
    assert html.index("Failure Reason") < html.index("Run metadata")


def test_cleanup_report_hides_failure_reason_on_success(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    final_locations = scenario.object_locations()
    final_locations.update({"mug_01": "sink_01", "book_01": "bookshelf_01"})
    score = score_cleanup(final_locations, scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(scenario, final_locations, tmp_path / "after.png", title="After")
    run_result = {
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "terminate_reason": "successful completion note",
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
    assert "Failure Reason" not in html
    assert "successful completion note" not in html


def test_open_ended_report_ignores_advisory_cleanup_failure(tmp_path: Path) -> None:
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
        "task_intent": "open-ended",
        "goal_contract": {"intent": "open-ended"},
        "cleanup_status_role": "advisory",
        "intent_status": "success",
        "goal_status": "success",
        "final_status": "success",
        "cleanup_status": "failed",
        "completion_status": "failed",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": {**score.to_dict(), "status": "success"},
        "terminate_reason": "open-ended task completed",
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
    assert "MolmoSpaces Open-ended Pilot" in html
    assert "Open-ended artifact" in html
    assert "Failure Reason" not in html
    assert "<span>Status</span><strong>Success</strong>" in html


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


def _robot_visual_timeline_report_context(tmp_path: Path) -> SimpleNamespace:
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
    for name in ("step.fpv.png", "step.chase.png", "step.topdown.png", "step.verify.png"):
        (tmp_path / "robot_views" / name).parent.mkdir(exist_ok=True)
        (tmp_path / "robot_views" / name).write_bytes(b"placeholder")
    return SimpleNamespace(
        scenario=scenario,
        before=before,
        after=after,
        run_result=_robot_visual_timeline_run_result(score),
    )


def _robot_visual_timeline_run_result(score: object) -> dict[str, object]:
    return {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "robot_name": "rby1m",
        "semantic_substeps": [
            {
                "object_id": "mug_01",
                "source_receptacle_id": "table_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {"phase": "navigate_to_object"},
                    {"phase": "pick"},
                    {"phase": "navigate_to_receptacle"},
                    {"phase": "place", "location_id": "sink_01"},
                    {
                        "phase": "object_done",
                        "location_id": "sink_01",
                        "location_relation": "on",
                    },
                ],
            },
        ],
    }


def _robot_visual_timeline_steps() -> list[dict[str, object]]:
    static_view_provenance = {
        "fpv": "isaac_lab_camera_rgb_static_robot_views:fpv",
        "topdown": "isaac_lab_camera_rgb_static_robot_views:topdown",
        "semantic_pose_state_refreshed": False,
        "evidence_note": "Robot-view images are static captures from the loaded USD scene.",
    }
    return [
        {
            "action": "before",
            "robot_pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
            "view_provenance": static_view_provenance,
            "views": {
                "fpv": "robot_views/step.fpv.png",
                "chase": "robot_views/step.chase.png",
                "topdown": "robot_views/step.topdown.png",
                "verify": "robot_views/bootstrap.verify.png",
            },
            "focus": {
                "has_focus": False,
                "fpv_visibility": {"status": "ok", "object_pixels": 0, "receptacle_pixels": 0},
                "visibility": {"status": "ok", "object_pixels": 0, "receptacle_pixels": 0},
            },
        },
        {
            "action": "goto sink",
            "semantic_phase": "navigate_to_receptacle",
            "view_provenance": static_view_provenance,
            "robot_pose": {
                "x": 1.0,
                "y": 2.0,
                "theta": 0.5,
                "theta_source": "target_facing_base_yaw",
                "head_pitch": 0.6,
                "head_pitch_source": "target_framing_head_pitch",
                "robot_room_id": "room_1",
                "target_room_id": "room_1",
                "same_room_as_target": True,
            },
            "views": {
                "fpv": "robot_views/step.fpv.png",
                "chase": "robot_views/step.chase.png",
                "topdown": "robot_views/step.topdown.png",
                "verify": "robot_views/step.verify.png",
            },
            "focus": {
                "has_focus": True,
                "object_label": "Mug mug",
                "receptacle_label": "Sink sink",
                "provenance": "public_mujoco_state_report_aid",
                "fpv_visibility": {"status": "ok", "object_pixels": 12, "receptacle_pixels": 80},
                "visibility": {"status": "ok", "object_pixels": 24, "receptacle_pixels": 120},
            },
        },
        _robot_visual_timeline_action_step("pick mug_01", "pick"),
        _robot_visual_timeline_action_step("place mug_01", "place"),
    ]


def _robot_visual_timeline_action_step(action: str, phase: str) -> dict[str, object]:
    return {
        "action": action,
        "semantic_phase": phase,
        "robot_pose": {"x": 1.0, "y": 2.0, "theta": 0.5},
        "views": {
            "fpv": "robot_views/step.fpv.png",
            "verify": "robot_views/step.verify.png",
        },
        "focus": {"has_focus": True},
    }


def _assert_robot_visual_timeline_layout(html: str) -> None:
    assert "Robot View Timeline" in html
    assert 'data-report-tab-button="timeline"' in html
    assert html.index('data-report-tab-button="timeline"') < html.index(
        'data-report-tab-button="timing"'
    )
    assert '<details class="robot-timeline-details" open>' in html
    assert "captured robot-view" in html
    assert "Top-down Scene View" in html


def _assert_robot_visual_timeline_lightbox(html: str) -> None:
    assert "Pick/place visual checks" in html
    assert '<details class="comparison-item" open>' in html
    assert '<a class="image-link" href="robot_views/step.fpv.png" data-lightbox-image' in html
    assert (
        '<img src="robot_views/step.fpv.png" alt="Pick view" loading="lazy" decoding="async">'
        in html
    )
    assert '<img src="robot_views/step.verify.png" alt="Pick view">' not in html
    assert 'data-lightbox-caption="Pick view"' in html
    assert 'class="image-lightbox"' in html
    assert "Close image review" in html
    assert "sim-only-grid-single" in html


def _assert_robot_visual_timeline_semantic_substeps(html: str) -> None:
    assert "Semantic Substeps" in html
    assert '<details class="semantic-card">' in html
    assert "semantic-card-status" in html
    assert SEMANTIC_LOOP_DISPLAY_NOTE in html
    assert "<span>nav</span><small>object</small>" in html
    assert "<span>pick</span><small>object</small>" in html
    assert "<span>nav</span><small>target</small>" in html
    assert "<span>place</span><small>surface</small>" in html
    assert "Subphase" in html
    assert "Role" in html
    assert "object_done" not in html


def _assert_robot_visual_timeline_pose_and_focus(html: str) -> None:
    assert "rby1m" in html
    assert "robot_views/step.fpv.png" in html
    assert "robot_views/bootstrap.verify.png" not in html
    assert "Chase sim-only" in html
    assert "Top-view bbox verification sim-only" in html
    assert "object 0 px" not in html
    assert "navigate_to_receptacle" in html
    assert "Mug mug" in html
    assert "public_mujoco_state_report_aid" in html
    assert "target_facing_base_yaw" in html
    assert "target_framing_head_pitch" in html


def _assert_robot_visual_timeline_yaw_rendering(
    tmp_path: Path,
    context: SimpleNamespace,
) -> None:
    assert "yaw_deg=257.0" in render_cleanup_report(
        run_dir=tmp_path,
        scenario=context.scenario,
        run_result=context.run_result,
        trace_events=[],
        before_snapshot=context.before,
        after_snapshot=context.after,
        robot_view_steps=[
            {
                "action": "isaac waypoint",
                "robot_pose": {"x": 0.0, "y": 0.39, "yaw_deg": 257.0},
                "views": {
                    "fpv": "robot_views/isaac.fpv.png",
                    "topdown": "robot_views/isaac.topdown.png",
                },
            }
        ],
    ).read_text(encoding="utf-8")


def _assert_robot_visual_timeline_static_isaac_caveat(html: str) -> None:
    assert "FPV visibility" in html
    assert "same room" in html
    assert "object 24 px" in html
    assert "Isaac report-only view caveat" in html
    assert "static report-only" in html
    assert "Step render: <strong>not refreshed</strong>" in html
    assert "backend JSON as isaac_semantic_pose" in html
    assert "diagnostic-view" not in html
    assert "decision-card" not in html


def test_cleanup_report_marks_refreshed_isaac_semantic_pose_views(tmp_path: Path) -> None:
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
    for name in ("step.fpv.png", "step.chase.png", "step.topdown.png", "step.verify.png"):
        (tmp_path / "robot_views" / name).parent.mkdir(exist_ok=True)
        (tmp_path / "robot_views" / name).write_bytes(b"placeholder")
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "robot_name": "rby1m",
        "isaac_runtime": {
            "runtime": {},
            "semantic_pose_state": {
                "rendered_to_usd": True,
                "semantic_pose_view_capture": {
                    "schema": "isaac_semantic_pose_robot_view_capture_v1",
                    "capture_method": "isaac_lab_camera_rgb_semantic_pose_robot_views",
                    "render_steps": 4,
                    "rendered_to_usd": True,
                },
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
        robot_view_steps=[
            {
                "action": "place mug_01",
                "semantic_phase": "place",
                "robot_pose": {"x": 1.0, "y": 2.0, "theta": 0.5},
                "view_provenance": {
                    "fpv": "isaac_lab_camera_rgb_semantic_pose_robot_views:fpv",
                    "topdown": "isaac_lab_camera_rgb_semantic_pose_robot_views:topdown",
                    "semantic_pose_state_refreshed": True,
                    "evidence_note": (
                        "Robot-view images were recaptured from the loaded USD scene "
                        "after applying backend semantic pose state."
                    ),
                },
                "views": {
                    "fpv": "robot_views/step.fpv.png",
                    "chase": "robot_views/step.chase.png",
                    "topdown": "robot_views/step.topdown.png",
                    "verify": "robot_views/step.verify.png",
                },
                "focus": {"has_focus": True},
            }
        ],
    )

    html = report_path.read_text(encoding="utf-8")
    assert "Isaac report-only view caveat" not in html
    assert "semantic pose rerender" in html
    assert "Step render: <strong>refreshed</strong>" in html
    assert "after applying backend semantic pose state" in html
    assert "Pose view capture" in html
    assert "isaac_lab_camera_rgb_semantic_pose_robot_views" in html
    assert "Pose render steps" in html


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


def test_cleanup_report_renders_planner_proof_requests_before_agent_view(
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
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "planner_cleanup_bridge_evidence": {
            "status": "blocked_capability",
            "target_runtime": {"embodiment": "rby1m"},
            "cleanup_primitives": {"status": "blocked_capability", "subphase_count": 4},
            "blockers": [],
            "target_runtime_ready": True,
            "cleanup_primitives_ready": False,
            "planner_backed": False,
        },
        "planner_proof_requests": {
            "schema": "planner_cleanup_proof_requests_v1",
            "request_count": 2,
            "ready_count": 1,
            "agent_view_exposed": False,
            "blockers": [{"code": "planner_binding_backend_unavailable"}],
            "requests": [
                {
                    "request_id": "proof_001",
                    "ready": True,
                    "object_id": "observed_001",
                    "source_receptacle_id": "counter_01",
                    "target_receptacle_id": "sink_01",
                    "tools": [
                        "navigate_to_object",
                        "pick",
                        "navigate_to_receptacle",
                        "place",
                    ],
                    "binding": {
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "planner_probe_args": {},
                    "blockers": [],
                },
                {
                    "request_id": "proof_002",
                    "ready": False,
                    "object_id": "observed_002",
                    "source_receptacle_id": "table_01",
                    "target_receptacle_id": "cabinet_01",
                    "tools": ["navigate_to_object"],
                    "binding": {},
                    "planner_probe_args": {},
                    "blockers": [{"code": "planner_binding_backend_unavailable"}],
                },
            ],
        },
        "agent_view": {
            "contract": "realworld_cleanup_v1",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "observed_objects": [{"object_id": "observed_001", "category": "dish"}],
        },
        "private_evaluation": {
            "generated_mess_count": 1,
            "generated_mess_set": ["mug_01"],
            "acceptable_destination_sets": {"mug_01": ["sink_01"]},
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
    ordered_headings = [
        "<h2>Planner Cleanup Bridge</h2>",
        "<h2>Planner Proof Requests</h2>",
        "<h2>Agent View</h2>",
    ]
    positions = [html.index(heading) for heading in ordered_headings]
    assert positions == sorted(positions)
    assert "Requests" in html
    assert "proof_001" in html
    assert "ready" in html
    assert "blocked" in html
    assert "observed_001" in html
    assert "counter_01" in html
    assert "sink_01" in html
    assert "navigate_to_object, pick, navigate_to_receptacle, place" in html
    assert "pickup/body" in html
    assert "sink/body" in html
    assert "planner_binding_backend_unavailable" in html
    agent_view_html = html[html.index("<h2>Agent View</h2>") :]
    assert "pickup/body" not in agent_view_html
    assert "sink/body" not in agent_view_html


def test_planner_proof_bundle_runner_report_renders_commands(tmp_path: Path) -> None:
    manifest = {
        "schema": "planner_cleanup_proof_bundle_run_manifest_v1",
        "status": "dry_run",
        "cleanup_run_result": str(tmp_path / "cleanup" / "run_result.json"),
        "output_dir": str(tmp_path),
        "proof_request_count": 1,
        "ready_request_count": 1,
        "proof_execution_horizon": {
            "schema": "planner_cleanup_proof_execution_horizon_v1",
            "status": "aligned",
            "command_steps": 2,
            "command_quality_target": "multi_step_motion",
            "prior_covered_min_proof_steps": 1,
            "prior_covered_quality_floor": "one_step_motion",
            "blockers": [],
            "evidence_note": "requested horizon",
        },
        "proof_request_selection": {
            "schema": "planner_cleanup_proof_request_selection_v1",
            "mode": "exclude_task_feasibility_blocked",
            "ready_request_count": 1,
            "selected_count": 1,
            "excluded_count": 1,
            "generated_fallback_request_count": 1,
            "fallback_required": False,
            "selected_request_ids": ["proof_001_fallback_01"],
            "selected_requests": [
                {
                    "request_id": "proof_001_fallback_01",
                    "request_type": "fallback_generated",
                    "source_request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "prior_task_feasibility_status": "blocked",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_result_match_kind": "request_id",
                }
            ],
            "excluded_requests": [
                {
                    "request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "reason": "prior_task_feasibility_blocked",
                    "prior_task_feasibility_status": "blocked",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "prior_result_match_kind": "request_id",
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                }
            ],
            "target_feasibility_blocker_count": 2,
            "target_feasibility_blockers": [
                {
                    "kind": "source_request",
                    "source_request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "reason": "prior_task_feasibility_blocked",
                    "prior_task_feasibility_status": "blocked",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "prior_result_match_kind": "request_id",
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                },
                {
                    "kind": "fallback_pair",
                    "source_request_id": "proof_001",
                    "object_alias": "pickup/body",
                    "target_alias": "sink/body_alt",
                    "derived_from": "proof_001_fallback_02",
                    "reason": "prior_task_feasibility_blocked_pair",
                    "prior_task_feasibility_status": "blocked",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "prior_result_match_kind": "request_id",
                    "last_worker_stage": "worker_exception",
                    "prior_report": str(tmp_path / "prior-proof" / "report.html"),
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                },
            ],
            "grasp_feasibility_blocker_count": 2,
            "grasp_feasibility_blockers": [
                {
                    "kind": "source_request",
                    "source_request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "reason": "prior_task_feasibility_blocked",
                    "prior_task_feasibility_status": "blocked",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "prior_result_match_kind": "request_id",
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                },
                {
                    "kind": "fallback_pair",
                    "source_request_id": "proof_001",
                    "object_alias": "pickup/body",
                    "target_alias": "sink/body_alt",
                    "derived_from": "proof_001_fallback_02",
                    "reason": "prior_task_feasibility_blocked_pair",
                    "prior_task_feasibility_status": "blocked",
                    "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                    "prior_task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "prior_result_match_kind": "request_id",
                    "last_worker_stage": "worker_exception",
                    "prior_report": str(tmp_path / "prior-proof" / "report.html"),
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                },
            ],
            "fallback_generation": {
                "schema": "planner_cleanup_proof_request_fallback_generation_v1",
                "status": "generated",
                "enabled": True,
                "generated_request_count": 1,
                "discovered_alias_count": 1,
                "filtered_alias_count": 1,
                "filtered_pair_count": 1,
                "generated_requests": [
                    {
                        "request_id": "proof_001_fallback_01",
                        "source_request_id": "proof_001",
                        "ready": True,
                        "object_id": "observed_001",
                        "target_receptacle_id": "sink_01",
                        "planner_probe_args": {
                            "--cleanup-object-id": "observed_001",
                            "--cleanup-target-receptacle-id": "sink_01",
                            "--cleanup-planner-object-id": "pickup/alt",
                            "--cleanup-planner-target-receptacle-id": "sink/alt",
                        },
                        "fallback_request": {
                            "source_request_id": "proof_001",
                            "reason": "prior_task_feasibility_blocked",
                            "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                            "prior_task_feasibility_blocker_summary": (
                                "3 grasp failures; 1 candidate-removal calls"
                            ),
                            "prior_result_match_kind": "request_id",
                            "prior_blockers": [{"code": "HouseInvalidForTask"}],
                        },
                    }
                ],
                "discovered_aliases": [
                    {
                        "source_request_id": "proof_001",
                        "axis": "target",
                        "alias": "sink/body_alt",
                        "derived_from": "proof_001_fallback_01",
                        "invalid_alias": "Sink|1|2",
                        "reason": "valid_name_sibling_from_prior_keyerror",
                    }
                ],
                "filtered_aliases": [
                    {
                        "source_request_id": "proof_001",
                        "axis": "target",
                        "alias": "Sink|1|2",
                        "reason": "not_exact_scene_runtime_alias",
                    }
                ],
                "filtered_pairs": [
                    {
                        "source_request_id": "proof_001",
                        "object_alias": "pickup/body",
                        "target_alias": "sink/body_alt",
                        "derived_from": "proof_001_fallback_02",
                        "reason": "prior_task_feasibility_blocked_pair",
                        "prior_task_feasibility_blocker_kind": "grasp_feasibility",
                        "prior_task_feasibility_blocker_summary": (
                            "3 grasp failures; 1 candidate-removal calls"
                        ),
                        "prior_result_match_kind": "request_id",
                        "prior_blockers": [{"code": "HouseInvalidForTask"}],
                    }
                ],
            },
        },
        "warmup": {
            "kind": "rby1m_curobo_config_import",
            "output_dir": str(tmp_path / "warmup"),
            "run_result": str(tmp_path / "warmup" / "run_result.json"),
            "report": str(tmp_path / "warmup" / "report.html"),
            "command": [
                "python",
                "probe.py",
                "--probe-mode",
                "config_import",
                "--torch-extensions-dir",
                str(tmp_path / "torch_extensions"),
            ],
        },
        "prior_proof_result_summary": {
            "schema": "merged_prior_planner_proof_result_summary_v1",
            "result_count": 1,
            "view_artifact_count": 2,
            "results": [
                {
                    "request_id": "standalone_observed_001_to_sink_01",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "run_result": str(tmp_path / "prior-proof" / "run_result.json"),
                    "report": str(tmp_path / "prior-proof" / "report.html"),
                    "status": "blocked_capability",
                    "task_feasibility_status": "blocked",
                    "task_feasibility_blocker_kind": "grasp_feasibility",
                    "task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "grasp_feasibility_signature": {
                        "schema": "planner_grasp_feasibility_signature_v1",
                        "kind": "grasp_feasibility",
                        "subkind": "grasp_cache_missing",
                        "pattern_key": "prior-grasp-cache-missing",
                        "summary": (
                            "3 grasp failures; 1 candidate-removal calls; "
                            "3 grasp-load failures; missing grasp cache: PriorBread_1"
                        ),
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_attempt_count": 3,
                        "grasp_load_failure_count": 3,
                        "grasp_collision_check_count": 0,
                        "zero_noncolliding_grasp_check_count": 0,
                        "grasp_load_exception_asset_uids": ["PriorBread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 0,
                        "place_robot_near_call_count": 1,
                        "object_name_count": 1,
                        "object_names": ["prior/pickup"],
                        "image_artifact_count": 2,
                    },
                    "views": [
                        {
                            "label": "initial",
                            "path": str(tmp_path / "prior-proof" / "initial.png"),
                        },
                        {
                            "label": "final",
                            "path": str(tmp_path / "prior-proof" / "final.png"),
                        },
                    ],
                }
            ],
        },
        "command_count": 1,
        "commands": [
            {
                "request_id": "proof_001_fallback_01",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "tools": [
                    "navigate_to_object",
                    "pick",
                    "navigate_to_receptacle",
                    "place",
                ],
                "semantic_subphases": [
                    {"phase": "navigate_to_object", "label": "nav", "detail": "object"},
                    {"phase": "pick", "label": "pick", "detail": "object"},
                    {"phase": "navigate_to_receptacle", "label": "nav", "detail": "target"},
                    {"phase": "place", "label": "place", "detail": "surface"},
                ],
                "run_result": str(tmp_path / "proofs" / "001" / "run_result.json"),
                "report": str(tmp_path / "proofs" / "001" / "report.html"),
                "command": [
                    "python",
                    "probe.py",
                    "--cleanup-object-id",
                    "observed_001",
                    "--cleanup-planner-target-receptacle-id",
                    "sink/alt",
                ],
            }
        ],
        "proof_result_summary": {
            "schema": "planner_cleanup_proof_result_summary_v1",
            "expected_count": 1,
            "result_count": 1,
            "planner_backed_count": 0,
            "blocked_count": 1,
            "timeout_count": 1,
            "rby1m_config_import_timeout_count": 1,
            "missing_result_count": 0,
            "cleanup_binding_promoted_count": 0,
            "execution_attempted_count": 0,
            "task_feasibility_blocked_count": 1,
            "grasp_feasibility_blocked_count": 1,
            "grasp_feasibility_signature_count": 1,
            "grasp_feasibility_signature_counts": [
                {
                    "schema": "planner_grasp_feasibility_signature_group_v1",
                    "pattern_key": "grasp=3;removals=1",
                    "subkind": "grasp_cache_missing",
                    "summary": (
                        "3 grasp failures; 1 candidate-removal calls; "
                        "3 grasp-load failures; missing grasp cache: Bread_1"
                    ),
                    "count": 1,
                    "request_ids": ["proof_001"],
                    "object_names": ["pickup/body"],
                    "grasp_load_failure_count": 3,
                    "grasp_collision_check_count": 0,
                    "zero_noncolliding_grasp_check_count": 0,
                    "grasp_load_exception_asset_uids": ["Bread_1"],
                    "grasp_load_exception_types": ["ValueError"],
                    "robot_placement_failure_count": 1,
                    "place_robot_near_call_count": 1,
                    "image_artifact_count": 2,
                }
            ],
            "worker_stage_event_count": 2,
            "last_worker_stage_counts": {"rby1m_config_import": 1},
            "view_artifact_count": 2,
            "results": [
                {
                    "request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "sink_01",
                    "run_result": str(tmp_path / "proofs" / "001" / "run_result.json"),
                    "report": str(tmp_path / "proofs" / "001" / "report.html"),
                    "run_result_exists": True,
                    "report_exists": True,
                    "status": "blocked_capability",
                    "planner_backed": False,
                    "cleanup_binding_promoted": False,
                    "execution_attempted": False,
                    "task_feasibility_status": "blocked",
                    "task_feasibility_blocker_kind": "grasp_feasibility",
                    "task_feasibility_blocker_summary": (
                        "3 grasp failures; 1 candidate-removal calls"
                    ),
                    "grasp_feasibility_signature": {
                        "schema": "planner_grasp_feasibility_signature_v1",
                        "kind": "grasp_feasibility",
                        "subkind": "grasp_cache_missing",
                        "pattern_key": "grasp=3;removals=1",
                        "summary": (
                            "3 grasp failures; 1 candidate-removal calls; "
                            "3 grasp-load failures; missing grasp cache: Bread_1"
                        ),
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_attempt_count": 3,
                        "grasp_load_failure_count": 3,
                        "grasp_collision_check_count": 0,
                        "zero_noncolliding_grasp_check_count": 0,
                        "grasp_load_exception_asset_uids": ["Bread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 1,
                        "place_robot_near_call_count": 1,
                        "object_name_count": 1,
                        "object_names": ["pickup/body"],
                        "image_artifact_count": 2,
                    },
                    "visual_status": "views_recorded",
                    "blockers": [
                        {"code": "HouseInvalidForTask", "message": "robot placement"},
                        {"code": "timeout", "message": "Probe exceeded 1.0s"},
                    ],
                    "cleanup_binding_blockers": [],
                    "last_worker_stage": "rby1m_config_import",
                    "worker_stage_event_count": 2,
                    "worker_stage_events": [
                        {"elapsed_s": 0.1, "event": "worker_start", "stage": "worker_start"},
                        {
                            "elapsed_s": 3.2,
                            "event": "rby1m_config_import_start",
                            "stage": "rby1m_config_import",
                        },
                    ],
                    "stdout": str(tmp_path / "proofs" / "001" / "planner_probe_stdout.txt"),
                    "stderr": str(tmp_path / "proofs" / "001" / "planner_probe_stderr.txt"),
                    "requested_cleanup_primitive_binding": {
                        "scene_xml": "/tmp/scene.xml",
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "task_sampler_robot_placement_profile": {
                        "profile": "relaxed",
                        "requested": True,
                        "applied": True,
                        "place_robot_near_overrides": {"max_tries": 50},
                    },
                    "cleanup_task_sampler_adapter": {
                        "applied": True,
                        "task_sampler_class": "PickAndPlaceTaskSampler",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "task_sampler_failure_diagnostics": {
                        "applied": True,
                        "task_sampler_class": "PickAndPlaceTaskSampler",
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 1,
                        "asset_failure_count": 1,
                        "grasp_failure_count": 3,
                        "candidate_name_miss_count": 0,
                        "grasp_failures": [
                            {
                                "object_name": "pickup/body",
                                "count_before": 2,
                                "count_after": 3,
                                "max_failures": 2,
                                "candidate_count_before": 1,
                                "candidate_count_after": 0,
                                "removed_candidate": True,
                            }
                        ],
                        "last_placement_scene_diagnostic": {
                            "target_name": "pickup/body",
                            "valid_free_point_count": 3,
                            "valid_neighborhood_fraction": 0.000017,
                            "nearest_free_point_distance_m": 0.42,
                        },
                        "last_robot_placement_failure": {
                            "pickup_obj_name": "pickup/body",
                            "message": "Failed to place robot near object: pickup/body",
                        },
                    },
                    "views": [
                        {
                            "label": "initial",
                            "path": str(tmp_path / "proofs" / "001" / "initial.png"),
                        },
                        {
                            "label": "final",
                            "path": str(tmp_path / "proofs" / "001" / "final.png"),
                        },
                    ],
                }
            ],
        },
        "grasp_feasibility_mitigation_decision": {
            "schema": "planner_grasp_feasibility_mitigation_decision_v1",
            "status": "action_required",
            "primary_route": "grasp_cache_mitigation",
            "recommendation": "mitigate_missing_grasp_cache_before_retry",
            "rationale": "Cached grasps could not be loaded for a requested asset.",
            "source_rotation_state": "available_for_unproven_requests",
            "selected_request_count": 1,
            "excluded_request_count": 1,
            "signature_group_count": 1,
            "subkind_counts": {"grasp_cache_missing": 1},
            "missing_grasp_asset_uids": ["Bread_1"],
            "grasp_load_exception_types": ["ValueError"],
            "evidence_request_ids": ["proof_001"],
            "signature_groups": [
                {
                    "source": "proof_result_summary",
                    "subkind": "grasp_cache_missing",
                    "count": 1,
                    "summary": "3 grasp-load failures; missing grasp cache: Bread_1",
                    "request_ids": ["proof_001"],
                    "object_names": ["pickup/body"],
                    "grasp_load_exception_asset_uids": ["Bread_1"],
                    "grasp_load_exception_types": ["ValueError"],
                }
            ],
        },
        "grasp_cache_availability_preflight": {
            "schema": "planner_grasp_cache_availability_preflight_v1",
            "status": "missing_cache",
            "assets_dir": str(tmp_path / "assets"),
            "assets_dir_source": "argument",
            "assets_dir_exists": True,
            "missing_grasp_asset_uids": ["Bread_1"],
            "asset_count": 1,
            "ready_asset_count": 0,
            "missing_cache_asset_count": 1,
            "cache_ready_asset_uids": [],
            "cache_missing_asset_uids": ["Bread_1"],
            "loader_sources": ["droid", "droid_objaverse", "rum"],
            "mitigation_recommendation": "generate_or_install_rigid_grasp_cache_before_retry",
            "upstream_loader": "molmo_spaces.utils.grasp_sample.load_grasps_for_object",
            "evidence_note": "Preflights the rigid-object grasp files used by MolmoSpaces.",
            "assets": [
                {
                    "asset_uid": "Bread_1",
                    "status": "missing_cache",
                    "loader_file_status": "missing",
                    "object_asset_status": "present",
                    "candidate_grasp_files": [
                        {
                            "asset_uid": "Bread_1",
                            "source": "droid",
                            "gripper": "droid",
                            "loader_role": "rigid_object_loader",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "droid"
                                / "Bread_1"
                                / "Bread_1_grasps_filtered.npz"
                            ),
                            "relative_path": ("grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"),
                            "exists": False,
                            "size_bytes": 0,
                        },
                        {
                            "asset_uid": "Bread_1",
                            "source": "droid_objaverse",
                            "gripper": "droid",
                            "loader_role": "rigid_object_loader",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "droid_objaverse"
                                / "Bread_1"
                                / "Bread_1_grasps_filtered.npz"
                            ),
                            "relative_path": (
                                "grasps/droid_objaverse/Bread_1/Bread_1_grasps_filtered.npz"
                            ),
                            "exists": False,
                            "size_bytes": 0,
                        },
                        {
                            "asset_uid": "Bread_1",
                            "source": "rum",
                            "gripper": "rum",
                            "loader_role": "rigid_object_loader",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "rum"
                                / "Bread_1"
                                / "Bread_1_grasps_filtered.json"
                            ),
                            "relative_path": ("grasps/rum/Bread_1/Bread_1_grasps_filtered.json"),
                            "exists": False,
                            "size_bytes": 0,
                        },
                    ],
                    "folder_probe_files": [
                        {
                            "asset_uid": "Bread_1",
                            "source": "droid",
                            "gripper": "droid",
                            "loader_role": "has_grasp_folder_only",
                            "path": str(
                                tmp_path
                                / "assets"
                                / "grasps"
                                / "droid"
                                / "Bread_1"
                                / "Bread_1_joint_grasps_filtered.npz"
                            ),
                            "relative_path": (
                                "grasps/droid/Bread_1/Bread_1_joint_grasps_filtered.npz"
                            ),
                            "exists": False,
                            "size_bytes": 0,
                        }
                    ],
                    "object_asset_files": [
                        {
                            "kind": "xml",
                            "path": str(tmp_path / "assets" / "objects" / "thor" / "Bread_1.xml"),
                            "relative_path": "objects/thor/Bread_1.xml",
                            "exists": True,
                            "size_bytes": 10,
                        }
                    ],
                }
            ],
        },
        "grasp_cache_generation_preflight": {
            "schema": "planner_grasp_cache_generation_preflight_v1",
            "status": "blocked",
            "ready": False,
            "asset_count": 1,
            "blocker_count": 2,
            "molmospaces_python": str(tmp_path / "molmospaces-python"),
            "molmospaces_root": str(tmp_path / "molmospaces"),
            "assets_dir": str(tmp_path / "assets"),
            "objects_list_path": str(tmp_path / "grasp_generation" / "rigid_objects_list.json"),
            "working_dir": str(tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation"),
            "command": [
                str(tmp_path / "molmospaces-python"),
                str(
                    tmp_path / "molmospaces" / "molmo_spaces" / "grasp_generation" / "run_rigid.py"
                ),
                "--objects_list",
                str(tmp_path / "grasp_generation" / "rigid_objects_list.json"),
            ],
            "mitigation_recommendation": (
                "install_grasp_generation_prerequisites_before_cache_generation"
            ),
            "evidence_note": "Preflights rigid grasp generation.",
            "assets": [
                {
                    "asset_uid": "Bread_1",
                    "object_xml": str(tmp_path / "assets" / "objects" / "thor" / "Bread_1.xml"),
                    "object_xml_exists": True,
                    "generated_npz_path": str(
                        tmp_path
                        / "molmospaces"
                        / "grasp_results"
                        / "rigid_objects"
                        / "Bread_1"
                        / "Bread_1_grasps_filtered.npz"
                    ),
                    "cache_target_resolved_path": str(
                        tmp_path
                        / "assets"
                        / "grasps"
                        / "droid"
                        / "Bread_1"
                        / "Bread_1_grasps_filtered.npz"
                    ),
                }
            ],
            "checks": [
                {
                    "name": "python_module_sklearn",
                    "status": "blocked",
                    "code": "sklearn_missing",
                    "message": "No module named sklearn",
                },
                {
                    "name": "manifold_executable",
                    "status": "blocked",
                    "code": "manifold_executable_missing",
                    "path": str(
                        tmp_path
                        / "molmospaces"
                        / "external_src"
                        / "Manifold"
                        / "build"
                        / "manifold"
                    ),
                    "message": "Required path is not ready",
                },
            ],
            "blockers": [
                {
                    "code": "sklearn_missing",
                    "name": "python_module_sklearn",
                    "message": "No module named sklearn",
                },
                {
                    "code": "manifold_executable_missing",
                    "name": "manifold_executable",
                    "message": "Required path is not ready",
                },
            ],
        },
        "cleanup_command": ["python", "cleanup.py", "--planner-proof-run-result", "proof.json"],
    }

    report_path = render_planner_proof_bundle_runner_report(
        output_dir=tmp_path,
        manifest=manifest,
    )

    html = report_path.read_text(encoding="utf-8")
    _assert_planner_proof_bundle_runner_overview(html)
    _assert_planner_proof_bundle_runner_selection(html)
    _assert_planner_proof_bundle_runner_proof_results(html, tmp_path)
    _assert_planner_proof_bundle_runner_sampler_diagnostics(html)
    _assert_planner_proof_bundle_runner_artifacts(html)


def _assert_html_contains(html: str, fragments: tuple[str, ...]) -> None:
    missing = [fragment for fragment in fragments if fragment not in html]
    assert not missing, f"Missing expected HTML fragments: {missing}"


def _assert_html_omits(html: str, fragments: tuple[str, ...]) -> None:
    unexpected = [fragment for fragment in fragments if fragment in html]
    assert not unexpected, f"Unexpected HTML fragments: {unexpected}"


def _assert_planner_proof_bundle_runner_overview(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Planner Proof Bundle Runner",
            "Source Cleanup Artifact",
            "Proof Execution Horizon",
            "multi_step_motion",
            "Grasp Feasibility Mitigation Decision",
            "decision-card",
            "grasp_cache_mitigation",
            "mitigate_missing_grasp_cache_before_retry",
            "Grasp Cache Availability Preflight",
            "Grasp Cache Generation Preflight",
            "python_module_sklearn",
            "manifold_executable_missing",
            "run_rigid.py",
            "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz",
            "has_grasp_folder_only",
            "objects/thor/Bread_1.xml",
            "available_for_unproven_requests",
            "RBY1M/CuRobo Warmup",
            "config_import",
            "torch_extensions",
            "Cleanup Rerun Command",
            "--planner-proof-run-result",
        ),
    )


def _assert_planner_proof_bundle_runner_selection(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Proof Request Selection",
            "dry_run",
            "proof_001",
            "proof_001_fallback_01",
            "observed_001",
            "sink/alt",
            "HouseInvalidForTask",
            "Fallback status",
            "generated",
            "Fallback required",
            "prior_task_feasibility_blocked",
            "Generated Fallback Requests",
            "Discovered Runtime Aliases",
            "Discovered aliases",
            "sink/body_alt",
            "valid_name_sibling_from_prior_keyerror",
            "Filtered Fallback Aliases",
            "Filtered aliases",
            "Sink|1|2",
            "not_exact_scene_runtime_alias",
            "Filtered Fallback Pairs",
            "Filtered pairs",
            "Target Feasibility Blockers",
            "Target blockers",
            "Grasp Feasibility Blockers",
            "Grasp Feasibility Blocker Matrix",
            "Grasp blockers",
            "Prior match",
            "request_id",
            "source_request",
            "fallback_pair",
            "worker_exception",
            "pickup/body",
            "prior_task_feasibility_blocked_pair",
            "fallback_generated",
        ),
    )


def _assert_planner_proof_bundle_runner_proof_results(html: str, tmp_path: Path) -> None:
    _assert_html_contains(
        html,
        (
            "Prior Proof Evidence",
            "Proof Probe Commands",
            "Semantic subphases",
            "surface / place",
            "Proof Probe Results",
            "Task feasibility",
            "blocked",
            "Grasp-feasible blocked",
            "Grasp Feasibility Signature Matrix",
            "Grasp-load failures",
            "grasp_cache_missing",
            "Bread_1",
            "PriorBread_1",
            "prior/pickup",
            "Diagnostic views",
            "Task feasibility blocker",
            "grasp_feasibility",
            "3 grasp failures; 1 candidate-removal calls",
            "standalone_observed_001_to_sink_01",
            "prior-proof/run_result.json",
            "prior-proof/report.html",
            "prior-proof/initial.png",
            "prior-proof/final.png",
            'src="prior-proof/initial.png"',
            'src="prior-proof/final.png"',
            'src="proofs/001/initial.png"',
            'src="proofs/001/final.png"',
        ),
    )
    _assert_html_omits(
        html,
        (
            f'src="{tmp_path}/prior-proof/initial.png"',
            f'src="{tmp_path}/proofs/001/initial.png"',
        ),
    )


def _assert_planner_proof_bundle_runner_sampler_diagnostics(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Robot placement profile",
            "relaxed",
            "place_robot_near max tries",
            "Exact sampler adapter applied",
            "Exact sampler adapter class",
            "PickAndPlaceTaskSampler",
            "Exact sampler adapter target",
            "Task sampler placement failures",
            "Task sampler asset failures",
            "Post-placement grasp failures",
            "Post-placement candidate name misses",
            "Post-Placement Rejection Views",
            "Post-placement rejection flow: pickup/body",
            "Placement free-space fraction",
            "0.000017",
            "Failed to place robot near object: pickup/body",
            "sink/body",
        ),
    )


def _assert_planner_proof_bundle_runner_artifacts(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Timeouts",
            "Config-import timeouts",
            "Last worker stage",
            "rby1m_config_import",
            "Worker stages",
            "planner_probe_stdout.txt",
            "planner_probe_stderr.txt",
            "initial.png",
            "final.png",
            "report.html",
        ),
    )


def test_cleanup_report_renders_attached_planner_proof(tmp_path: Path) -> None:
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
    proof_dir = tmp_path / "planner_proof"
    proof_dir.mkdir()
    (proof_dir / "initial.png").write_bytes(b"initial")
    (proof_dir / "final.png").write_bytes(b"final")
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend="api_semantic_synthetic",
            primitive_summary={API_SEMANTIC_PROVENANCE: 1},
        ),
        "score": score.to_dict(),
        "planner_backed_manipulation_proof": {
            "schema": "planner_backed_cleanup_attachment_v1",
            "status": "planner_backed",
            "primitive_provenance": "planner_backed",
            "planner_backed": True,
            "strict_proof_eligible": True,
            "embodiment": "franka",
            "steps_executed": 2,
            "max_abs_qpos_delta": 0.01,
            "runtime_diagnostics": {"renderer_adapter_enabled": True},
            "image_artifacts": {
                "initial": "planner_proof/initial.png",
                "final": "planner_proof/final.png",
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
    assert "Attached Planner-Backed Proof" in html
    assert "Proof Quality" in html
    assert "multi_step_motion" in html
    assert "Containment proven" in html
    assert "Planner Initial" in html
    assert "Planner Final" in html
    assert "Cleanup object moves" in html
    assert "api_semantic" in html
    assert "planner_proof/initial.png" in html
    assert "planner_proof/final.png" in html


def test_cleanup_report_renders_attached_planner_proof_bundle(tmp_path: Path) -> None:
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
    for proof_id in ("proof_001", "proof_002"):
        proof_dir = tmp_path / "planner_proof" / proof_id
        proof_dir.mkdir(parents=True)
        (proof_dir / "initial.png").write_bytes(b"initial")
        (proof_dir / "final.png").write_bytes(b"final")
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": score.status,
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend="api_semantic_synthetic",
            primitive_summary={"planner_backed": 8},
        ),
        "score": score.to_dict(),
        "planner_backed_manipulation_proof": {
            "schema": "planner_backed_cleanup_proof_bundle_v1",
            "status": "planner_backed",
            "primitive_provenance": "planner_backed",
            "planner_backed": True,
            "strict_proof_eligible": True,
            "proof_count": 2,
            "attachments": [
                _proof_attachment("proof_001", "observed_001", "sink_01"),
                _proof_attachment("proof_002", "observed_002", "toy_bin_01"),
            ],
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
    assert "Attached Planner-Backed Proofs" in html
    assert "Proof Quality" in html
    assert "multi_step_motion=2" in html
    assert "proof_001 Planner Initial" in html
    assert "proof_002 Planner Final" in html
    assert "observed_001" in html
    assert "toy_bin_01" in html
    assert "planner_proof/proof_001/initial.png" in html
    assert "planner_proof/proof_002/final.png" in html


def _proof_attachment(proof_id: str, object_id: str, target_id: str) -> dict[str, object]:
    return {
        "schema": "planner_backed_cleanup_attachment_v1",
        "proof_id": proof_id,
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "planner_backed": True,
        "strict_proof_eligible": True,
        "embodiment": "rby1m",
        "task": "pick_and_place",
        "probe_mode": "execute",
        "upstream_policy_class": "CuroboPickAndPlacePlannerPolicy",
        "steps_executed": 2,
        "max_abs_qpos_delta": 0.01,
        "runtime_diagnostics": {"modules": {"curobo": {"available": True}}},
        "image_artifacts": {
            "initial": f"planner_proof/{proof_id}/initial.png",
            "final": f"planner_proof/{proof_id}/final.png",
        },
        "cleanup_primitive_binding": {
            "schema": "planner_probe_cleanup_primitive_binding_v1",
            "object_id": object_id,
            "target_receptacle_id": target_id,
            "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
        },
    }


def test_planner_manipulation_probe_report_uses_shared_underlay(tmp_path: Path) -> None:
    stdout = tmp_path / "planner_probe_stdout.txt"
    stderr = tmp_path / "planner_probe_stderr.txt"
    stdout.write_text("{}", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    run_result = {
        "contract": "planner_backed_manipulation_probe_v1",
        "backend": "molmospaces_subprocess",
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": blocked_planner_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="franka",
            task="pick_and_place",
            probe_mode="config_import",
            blockers=[
                {
                    "code": "execution_not_attempted",
                    "message": "Planner execution was not attempted.",
                }
            ],
            upstream_policy_class="PickAndPlacePlannerPolicy",
        ),
        "artifacts": {
            "stdout": str(stdout),
            "stderr": str(stderr),
        },
    }
    run_result["manipulation_evidence"]["runtime_diagnostics"] = {
        "python_executable": "/tmp/molmospaces/.venv/bin/python",
        "python_version": "3.11.8",
        "faulthandler_enabled": True,
        "renderer_adapter_enabled": True,
        "renderer_device_id": 0,
        "mujoco_gl_env": "egl",
        "pyopengl_platform_env": "egl",
        "cuda_home_env": "/usr/local/cuda",
        "torch_cuda_arch_list_env": "8.9",
        "torch": {
            "available": True,
            "version": "2.7.1+cu128",
            "cuda_version": "12.8",
            "cuda_available": True,
            "cpp_extension_cuda_home": "/usr/local/cuda",
        },
        "cuda_visible_devices_env": "0",
        "pytorch_cuda_alloc_conf_env": "expandable_segments:True",
        "cuda_memory": {
            "available": True,
            "device_count": 1,
            "current_device_index": 0,
            "devices": [
                {
                    "index": 0,
                    "name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
                    "total_memory_bytes": 12884901888,
                    "compute_capability": "8.9",
                }
            ],
            "current_snapshot": {
                "stage": "runtime_diagnostics",
                "elapsed_s": 0.02,
                "device_index": 0,
                "device_name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
                "free_bytes": 298844160,
                "total_bytes": 12455405158,
                "torch_allocated_bytes": 10458234880,
                "torch_reserved_bytes": 11408506880,
            },
        },
        "modules": {
            "curobo": {"available": False, "version": None},
            "molmo_spaces": {"available": True, "version": "0.1.0"},
        },
        "curobo_extension_cache": {
            "configured_dir": "output/cache",
            "extensions": {
                "lbfgs_step_cu": {
                    "build_dir": "output/cache/lbfgs_step_cu",
                    "so_exists": False,
                    "lock_exists": True,
                    "files": [{"name": "lock", "size_bytes": 0}],
                },
                "geom_cu": {
                    "build_dir": "output/cache/geom_cu",
                    "so_exists": True,
                    "lock_exists": False,
                    "files": [{"name": "geom_cu.so", "size_bytes": 12}],
                },
            },
        },
        "warp_compatibility": {
            "available": True,
            "version": "1.13.0",
            "has_torch_attr": True,
            "has_device_from_torch": True,
            "has_from_torch": True,
            "has_stream_from_torch": True,
            "adapter": {
                "applied": True,
                "provided": ["warp.torch.device_from_torch"],
            },
        },
    }
    run_result["manipulation_evidence"]["worker_stage_events"] = [
        {
            "event": "worker_start",
            "stage": "worker_start",
            "elapsed_s": 0.01,
            "embodiment": "rby1m",
            "probe_mode": "config_import",
        },
        {
            "event": "rby1m_config_import_start",
            "stage": "rby1m_config_import",
            "elapsed_s": 0.02,
        },
    ]
    run_result["manipulation_evidence"]["cuda_memory_snapshots"] = [
        {
            "stage": "execute_policy_construct_before",
            "elapsed_s": 10.2,
            "device_index": 0,
            "device_name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
            "free_bytes": 2147483648,
            "total_bytes": 12884901888,
            "torch_allocated_bytes": 1073741824,
            "torch_reserved_bytes": 2147483648,
        },
        {
            "stage": "execute_policy_run_start",
            "elapsed_s": 24.5,
            "device_index": 0,
            "device_name": "NVIDIA RTX 3500 Ada Generation Laptop GPU",
            "free_bytes": 298844160,
            "total_bytes": 12455405158,
            "torch_allocated_bytes": 10458234880,
            "torch_reserved_bytes": 11408506880,
        },
    ]
    run_result["manipulation_evidence"]["curobo_memory_profile"] = {
        "profile": "low",
        "applied": True,
        "before": {
            "policy": {
                "batch_size": 4,
                "max_batch_plan_attempts": 4,
                "enable_collision_avoidance": True,
            },
            "planners": {
                "left": {
                    "num_trajopt_seeds": 12,
                    "num_ik_seeds": 128,
                    "max_attempts": 15,
                    "trajopt_tsteps": 48,
                    "enable_finetune_trajopt": True,
                }
            },
        },
        "after": {
            "policy": {
                "batch_size": 1,
                "max_batch_plan_attempts": 1,
                "enable_collision_avoidance": True,
            },
            "planners": {
                "left": {
                    "num_trajopt_seeds": 1,
                    "num_ik_seeds": 16,
                    "max_attempts": 1,
                    "trajopt_tsteps": 24,
                    "enable_finetune_trajopt": False,
                }
            },
        },
    }
    run_result["manipulation_evidence"]["cleanup_task_config"] = {
        "schema": "planner_probe_exact_cleanup_task_config_v1",
        "applied": True,
        "scene_xml": "/tmp/scene.xml",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "blockers": [{"code": "cleanup_scene_xml_missing", "message": "missing stale scene"}],
    }
    run_result["manipulation_evidence"]["task_sampler_robot_placement_profile"] = {
        "schema": "planner_probe_task_sampler_robot_placement_profile_v1",
        "profile": "relaxed",
        "requested": True,
        "applied": True,
        "before": {
            "base_pose_sampling_radius_range": [0.0, 0.7],
            "robot_safety_radius": 0.35,
            "check_robot_placement_visibility": True,
            "max_robot_placement_attempts": 10,
        },
        "after": {
            "base_pose_sampling_radius_range": [0.0, 1.2],
            "robot_safety_radius": 0.15,
            "check_robot_placement_visibility": False,
            "max_robot_placement_attempts": 50,
        },
        "applied_overrides": {"robot_safety_radius": 0.15},
        "place_robot_near_overrides": {"max_tries": 50},
    }
    run_result["manipulation_evidence"]["cleanup_task_sampler_adapter"] = {
        "schema": "planner_probe_exact_cleanup_task_sampler_adapter_v1",
        "applied": True,
        "task_sampler_class": "PickAndPlaceTaskSampler",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "exact_pickup_candidate_binding": {
            "schema": "planner_probe_exact_pickup_candidate_binding_v1",
            "planner_object_id": "pickup/body",
            "candidate_count_before": 17,
            "candidate_count_after": 3,
            "retry_budget": 3,
            "retry_budget_applied": True,
            "requested_present_before": False,
            "requested_present_after": True,
            "action": "injected_requested_candidate_name",
        },
    }
    run_result["manipulation_evidence"]["task_sampler_failure_diagnostics"] = {
        "schema": "planner_probe_task_sampler_failure_diagnostics_v1",
        "applied": True,
        "task_sampler_class": "PickAndPlaceTaskSampler",
        "robot_placement_config": {
            "base_pose_sampling_radius_range": [0.0, 0.7],
            "robot_safety_radius": 0.15,
            "check_robot_placement_visibility": True,
            "max_robot_placement_attempts": 10,
        },
        "hooks": ["_sample_and_place_robot", "report_asset_failure"],
        "robot_placement_attempt_count": 1,
        "robot_placement_failure_count": 1,
        "asset_failure_count": 1,
        "candidate_removal_count": 1,
        "candidate_effective_removal_count": 0,
        "candidate_name_miss_count": 1,
        "grasp_threshold_exceeded_count": 1,
        "robot_placement_attempts": [
            {
                "attempt_index": 1,
                "pickup_obj_name": "pickup/body",
                "asset_uid": "asset-book",
                "result": "failed",
                "exception_type": "RobotPlacementError",
                "message": "Failed to place robot near object: pickup/body",
            }
        ],
        "asset_failures": [
            {
                "asset_uid": "asset-book",
                "reason": "robot placement failed",
            }
        ],
        "grasp_load_attempt_count": 1,
        "grasp_collision_check_count": 1,
        "zero_noncolliding_grasp_check_count": 1,
        "grasp_load_attempts": [
            {
                "schema": "planner_probe_grasp_load_attempt_v1",
                "asset_uid": "asset-book",
                "pickup_obj_name": "pickup/body",
                "requested_grasp_count": 512,
                "result": "loaded",
                "gripper": "droid",
                "cached_grasp_count": 512,
            }
        ],
        "grasp_collision_checks": [
            {
                "schema": "planner_probe_grasp_collision_check_v1",
                "asset_uid": "asset-book",
                "pickup_obj_name": "pickup/body",
                "grasp_pose_count": 512,
                "batch_size": 64,
                "result": "checked",
                "noncolliding_grasp_count": 0,
                "colliding_grasp_count": 512,
                "zero_noncolliding": True,
            }
        ],
        "last_grasp_load_attempt": {
            "schema": "planner_probe_grasp_load_attempt_v1",
            "asset_uid": "asset-book",
            "pickup_obj_name": "pickup/body",
            "requested_grasp_count": 512,
            "result": "loaded",
            "gripper": "droid",
            "cached_grasp_count": 512,
        },
        "last_grasp_collision_check": {
            "schema": "planner_probe_grasp_collision_check_v1",
            "asset_uid": "asset-book",
            "pickup_obj_name": "pickup/body",
            "grasp_pose_count": 512,
            "batch_size": 64,
            "result": "checked",
            "noncolliding_grasp_count": 0,
            "colliding_grasp_count": 512,
            "zero_noncolliding": True,
        },
        "grasp_failure_count": 1,
        "grasp_failures": [
            {
                "object_name": "pickup/body",
                "count_before": 2,
                "count_after": 3,
                "max_failures": 2,
                "threshold_exceeded": True,
                "threshold_crossed": True,
                "candidate_count_before": 1,
                "candidate_count_after": 1,
                "candidate_name_present_before": False,
                "candidate_name_present_after": False,
                "candidate_removal_call_count_delta": 1,
                "removed_candidate": False,
            }
        ],
        "place_robot_near_calls": [
            {
                "call_index": 1,
                "requested": {"max_tries": 10},
                "effective": {
                    "max_tries": 50,
                    "robot_safety_radius": 0.15,
                    "check_camera_visibility": False,
                },
                "result": False,
            }
        ],
        "placement_scene_diagnostic_count": 1,
        "placement_scene_diagnostics": [
            {
                "schema": "planner_probe_placement_scene_diagnostic_v1",
                "call_index": 1,
                "target_name": "pickup/body",
                "target_position": [1.0, 2.0, 0.5],
                "sampling_radius_range": [0.0, 1.2],
                "sampling_area_m2": 4.523893,
                "robot_safety_radius": 0.15,
                "px_per_m": 200,
                "total_free_point_count": 100,
                "valid_free_point_count": 3,
                "valid_neighborhood_fraction": 0.000017,
                "low_free_space": True,
                "nearest_free_point_distance_m": 0.42,
                "nearest_free_point": [1.42, 2.0, 0.0],
                "radius_band_counts": [
                    {"radius_min_m": 0.0, "radius_max_m": 0.25, "free_point_count": 0},
                    {"radius_min_m": 0.25, "radius_max_m": 0.5, "free_point_count": 1},
                ],
            }
        ],
        "last_placement_scene_diagnostic": {
            "schema": "planner_probe_placement_scene_diagnostic_v1",
            "call_index": 1,
            "target_name": "pickup/body",
            "target_position": [1.0, 2.0, 0.5],
            "sampling_radius_range": [0.0, 1.2],
            "sampling_area_m2": 4.523893,
            "robot_safety_radius": 0.15,
            "px_per_m": 200,
            "total_free_point_count": 100,
            "valid_free_point_count": 3,
            "valid_neighborhood_fraction": 0.000017,
            "low_free_space": True,
            "nearest_free_point_distance_m": 0.42,
            "nearest_free_point": [1.42, 2.0, 0.0],
            "radius_band_counts": [
                {"radius_min_m": 0.0, "radius_max_m": 0.25, "free_point_count": 0},
                {"radius_min_m": 0.25, "radius_max_m": 0.5, "free_point_count": 1},
            ],
        },
        "candidate_removals": [
            {
                "object_name": "pickup/body",
                "candidate_count_before": 1,
                "candidate_count_after": 1,
                "candidate_name_present_before": False,
                "candidate_name_present_after": False,
                "effective_removal": False,
            }
        ],
        "last_robot_placement_failure": {
            "pickup_obj_name": "pickup/body",
            "message": "Failed to place robot near object: pickup/body",
        },
    }
    run_result["manipulation_evidence"]["sampled_task_binding"] = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "pickup/body",
        "place_receptacle_name": "sink/body",
        "place_target_name": "sink/body",
    }
    run_result["manipulation_evidence"]["requested_cleanup_primitive_binding"] = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "requested": True,
        "object_id": "pickup/body",
        "target_receptacle_id": "sink/body",
        "source_receptacle_id": "counter/body",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    run_result["manipulation_evidence"]["cleanup_primitive_binding"] = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "pickup/body",
        "target_receptacle_id": "sink/body",
        "source_receptacle_id": "counter/body",
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
    }
    run_result["manipulation_evidence"]["policy_exception_context"] = {
        "schema": "planner_probe_policy_exception_context_v1",
        "stage": "execute_policy_run",
        "steps_requested": 1,
        "exception_type": "ValueError",
        "message": "_execute_trajectory was called with no planned trajectory",
        "failure_kind": "curobo_no_planned_trajectory",
        "no_planned_trajectory": True,
        "policy_class": "PickAndPlacePlannerPolicy",
        "policy_current_phase": "pre_grasp",
        "action_primitive_count": 1,
        "action_primitives": [
            {
                "index": 0,
                "primitive_class": "PickAndPlacePrimitive",
                "current_phase": "pre_grasp",
                "planned_trajectory_present": True,
                "planned_trajectory_len": 0,
                "trajectory_index": 0,
            }
        ],
    }
    run_result["manipulation_evidence"]["last_worker_stage"] = "rby1m_config_import"
    run_result["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(run_result)

    report_path = render_planner_manipulation_report(run_dir=tmp_path, run_result=run_result)
    html = report_path.read_text(encoding="utf-8")

    _assert_planner_manipulation_probe_overview(html)
    _assert_planner_manipulation_probe_cleanup_binding(html)
    _assert_planner_manipulation_probe_sampler_failures(html)
    _assert_planner_manipulation_probe_runtime_diagnostics(html)


def _assert_planner_manipulation_probe_overview(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Planner-Backed Manipulation Probe",
            "Manipulation Provenance",
            "Planner Proof Quality",
            "Runtime Diagnostics",
            "Planner Probe Diagnostic Views",
            "Task sampler diagnostic: pickup/body",
            "Planner Probe Cleanup Binding",
            "Capability Blockers",
            "RBY1M CuRobo Gate",
            "wrong_embodiment",
        ),
    )


def _assert_planner_manipulation_probe_cleanup_binding(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Task Sampler Robot Placement Profile",
            "relaxed",
            "place_robot_near max tries",
            "Exact task config applied",
            "Exact task config blockers",
            "cleanup_scene_xml_missing",
            "Exact sampler adapter class",
            "Exact sampler adapter object",
            "Exact pickup candidate action",
            "Exact pickup retry budget",
            "injected_requested_candidate_name",
            "PickAndPlaceTaskSampler",
            "pickup/body",
            "sink/body",
            "Planner object alias",
            "navigate_to_receptacle",
        ),
    )


def _assert_planner_manipulation_probe_sampler_failures(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Task Sampler Failure Diagnostics",
            "Placement failures",
            "Effective max tries",
            "Post-Placement Candidate Rejections",
            "Post-Placement Rejection Views",
            "Post-placement rejection flow: pickup/body",
            "Removed by grasp threshold",
            "Candidate Removal Effectiveness",
            "Effective removals",
            "Candidate name misses",
            "Removal-call delta",
            "Placement Scene Diagnostics",
            "Free-space fraction",
            "0.000017",
            "Nearest free distance",
            "Failed to place robot near object: pickup/body",
            "asset-book",
        ),
    )


def _assert_planner_manipulation_probe_runtime_diagnostics(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "CUDA Memory Headroom",
            "CuRobo Memory Profile",
            "Policy Exception Diagnostics",
            "curobo_no_planned_trajectory",
            "_execute_trajectory was called with no planned trajectory",
            "pre_grasp",
            "Trajectory len",
            "CuRobo Extension Cache",
            "lbfgs_step_cu",
            "Warp Compatibility",
            "Adapter applied",
            "Worker Stage Timeline",
            "PickAndPlacePlannerPolicy",
            "rby1m_config_import_start",
            "rby1m_config_import",
            "faulthandler=True",
            "renderer_adapter=True",
            "MUJOCO_GL=egl",
            "CUDA_HOME=/usr/local/cuda",
            "torch_cuda_available=True",
            "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
            "execute_policy_run_start",
            "num_ik_seeds",
            "Collision avoidance",
            "10.6 GiB",
            "curobo",
        ),
    )


def test_planner_manipulation_probe_report_renders_proof_quality(tmp_path: Path) -> None:
    views = tmp_path / "planner_views"
    views.mkdir()
    (views / "initial.png").write_bytes(b"initial")
    (views / "final.png").write_bytes(b"final")
    run_result = {
        "contract": "planner_backed_manipulation_probe_v1",
        "backend": "molmospaces_subprocess",
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": planner_backed_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="rby1m",
            task="pick_and_place",
            probe_mode="execute",
            upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
            steps_requested=2,
            steps_executed=2,
            max_abs_qpos_delta=0.01,
            image_artifacts={
                "initial": "planner_views/initial.png",
                "final": "planner_views/final.png",
            },
        ),
        "artifacts": {},
    }

    report_path = render_planner_manipulation_report(run_dir=tmp_path, run_result=run_result)
    html = report_path.read_text(encoding="utf-8")

    assert "Planner Proof Quality" in html
    assert "multi_step_motion" in html
    assert "Containment proven" in html
    assert "Planner Probe Views" in html


def test_planner_manipulation_probe_report_renders_diagnostic_image_artifacts(
    tmp_path: Path,
) -> None:
    views = tmp_path / "planner_views"
    views.mkdir()
    image = views / "post_placement_attempt_001_head_camera.png"
    image.write_bytes(b"not a real image but enough for an html src")
    run_result = {
        "contract": "planner_backed_manipulation_probe_v1",
        "backend": "molmospaces_subprocess",
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": blocked_planner_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="rby1m",
            task="pick_and_place",
            probe_mode="execute",
            blockers=[{"code": "HouseInvalidForTask", "message": "candidate removed"}],
            execution_attempted=True,
        ),
        "artifacts": {"stdout": "stdout.txt", "stderr": "stderr.txt"},
    }
    run_result["manipulation_evidence"]["image_artifacts"] = {
        "post_placement_attempt_001_head_camera": (
            "planner_views/post_placement_attempt_001_head_camera.png"
        )
    }
    run_result["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(run_result)

    report_path = render_planner_manipulation_report(run_dir=tmp_path, run_result=run_result)

    html = report_path.read_text(encoding="utf-8")
    assert "Planner Probe Views" in html
    assert "Post Placement Attempt 001 Head Camera" in html
    assert 'src="planner_views/post_placement_attempt_001_head_camera.png"' in html
    assert "diagnostic-view" in html
