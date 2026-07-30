from __future__ import annotations

from pathlib import Path

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup


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
