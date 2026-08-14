from __future__ import annotations

import json
import os
from pathlib import Path

from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
)
from tests.support.operator_console_grounding import write_grounding_gallery_agent_view
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)


def test_state_reports_camera_angles_and_navigation_reset(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "wrapper-run"
    attempt_dir = run_dir / "0609_1110" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "wrapper-run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "starting",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "request",
                "tool": "adjust_camera",
                "request": {"yaw_delta_deg": 0, "pitch_delta_deg": -10},
            }
        )
        + "\n"
        + json.dumps(
            {
                "event": "response",
                "tool": "adjust_camera",
                "response": {
                    "ok": True,
                    "status": "ok",
                    "camera_offset": {"yaw_delta_deg": 0.0, "pitch_delta_deg": -10.0},
                    "previous_camera_offset": {"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0},
                    "waypoint_id": "generated_exploration_001",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["camera_state"]["active"] is True
    assert state["camera_state"]["summary"] == "yaw 0 deg, pitch -10 deg (active)"
    assert state["camera_state"]["latest_adjust"]["requested_pitch_delta_deg"] == -10.0

    with (attempt_dir / "trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "response",
                    "tool": "navigate_to_object",
                    "response": {"ok": True, "status": "ok", "object_id": "observed_001"},
                }
            )
            + "\n"
        )

    reset_state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert reset_state["camera_state"]["active"] is False
    assert reset_state["camera_state"]["summary"] == "yaw 0 deg, pitch 0 deg (neutral)"
    assert reset_state["camera_state"]["latest_event"] == "navigate_to_object_reset"


def test_state_splits_semantic_map_from_top_down_scene_preview(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    robot_views = run_dir / "robot_views"
    map_bundle = run_dir / "map_bundle"
    robot_views.mkdir(parents=True)
    map_bundle.mkdir()
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    robot_map = robot_views / "0042_observe.map.png"
    robot_topdown = robot_views / "0042_observe.topdown.png"
    stale_report_map = map_bundle / "report_static_navigation_map.png"
    bundle_preview = map_bundle / "preview.png"
    semantic_map = run_dir / "semantic_map.png"
    robot_map.write_bytes(b"robot map")
    robot_topdown.write_bytes(b"robot topdown")
    stale_report_map.write_bytes(b"stale report map")
    bundle_preview.write_bytes(b"bundle preview")
    semantic_map.write_bytes(b"semantic map")
    runtime_preview = run_dir / "runtime_metric_map_preview.png"
    runtime_preview.write_bytes(b"runtime map preview")
    os.utime(robot_map, (1, 1))
    os.utime(robot_topdown, (4, 4))
    os.utime(stale_report_map, (2, 2))
    os.utime(bundle_preview, (3, 3))
    os.utime(semantic_map, (3, 3))
    os.utime(runtime_preview, (5, 5))
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "agent_view": {
                    "metric_map": {
                        "robot_pose": {
                            "frame_id": "map",
                            "x": 8.544,
                            "y": 6.408,
                            "yaw": 90.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_view_assets"]["map"]["path"] == str(bundle_preview.resolve())
    assert state["latest_view_assets"]["map"]["visual_role"] == "base_metric_map_preview"
    assert state["latest_view_assets"]["map"]["artifact_source_family"] == (
        "base_metric_map_bundle"
    )
    assert state["latest_view_assets"]["runtime_map"]["path"] == str(runtime_preview.resolve())
    assert state["latest_view_assets"]["runtime_map"]["visual_role"] == (
        "runtime_metric_map_preview"
    )
    assert state["latest_view_assets"]["runtime_map"]["artifact_source_family"] == (
        "runtime_metric_map"
    )
    assert state["latest_view_assets"]["topdown"]["path"] == str(robot_topdown.resolve())
    assert state["latest_view_assets"]["topdown"]["visual_role"] == "topdown_scene_render"
    assert state["latest_view_assets"]["topdown"]["artifact_source_family"] == (
        "scene_camera_render"
    )
    assert state["latest_view_assets"]["map"]["href"].startswith("/artifacts/")
    assert "?v=" in state["latest_view_assets"]["map"]["href"]


def test_state_does_not_use_map_artifacts_as_top_down_scene_view(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_MAP_BUILD).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    semantic_map = run_dir / "semantic_map.png"
    semantic_map.write_bytes(b"semantic map")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_MAP_BUILD))

    assert "map" not in state["latest_view_assets"]
    assert "topdown" not in state["latest_view_assets"]


def test_state_groups_visual_grounding_candidates_without_replacing_fpv(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    robot_views = run_dir / "robot_views"
    overlays = run_dir / "visual_grounding" / "overlays" / "raw_fpv_001"
    robot_views.mkdir(parents=True)
    overlays.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    raw_fpv = robot_views / "raw_fpv_001.fpv.png"
    second_raw_fpv = robot_views / "raw_fpv_002.fpv.png"
    first_overlay = overlays / "candidate_001.jpg"
    latest_overlay = overlays / "candidate_002.jpg"
    raw_fpv.write_bytes(b"raw fpv")
    second_raw_fpv.write_bytes(b"second raw fpv")
    first_overlay.write_bytes(b"first dino overlay")
    latest_overlay.write_bytes(b"latest dino overlay")
    os.utime(raw_fpv, (1, 1))
    os.utime(second_raw_fpv, (4, 4))
    os.utime(first_overlay, (2, 2))
    os.utime(latest_overlay, (3, 3))
    write_grounding_gallery_agent_view(run_dir)

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_view_assets"]["grounding"]["path"] == str(latest_overlay.resolve())
    assert state["latest_view_assets"]["fpv"]["path"] == str(second_raw_fpv.resolve())
    assert "display_source" not in state["latest_view_assets"]["fpv"]
    grounding_frames = state["latest_view_assets"]["grounding_frames"]
    assert grounding_frames["frame_count"] == 1
    assert grounding_frames["candidate_count"] == 2
    frame = grounding_frames["frames"][0]
    assert frame["observation_id"] == "raw_fpv_001"
    assert frame["image"]["path"] == str(raw_fpv.resolve())
    assert [candidate["category"] for candidate in frame["candidates"]] == [
        "book",
        "electronics",
    ]
    assert frame["candidates"][0]["bbox_xywh"] == [0.1, 0.2, 0.3, 0.4]
    assert frame["candidates"][0]["overlay"]["path"] == str(first_overlay.resolve())


def test_state_does_not_promote_report_bbox_images_as_grounding_overlay(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run"
    robot_views = run_dir / "robot_views"
    report_assets = run_dir / "report_assets"
    robot_views.mkdir(parents=True)
    report_assets.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "route": get_selection(MUJOCO_SDK_CLEANUP).to_payload(),
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
            }
        ),
        encoding="utf-8",
    )
    raw_fpv = robot_views / "raw_fpv_001.fpv.png"
    report_bbox = report_assets / "raw_fpv_001.bbox.png"
    raw_fpv.write_bytes(b"raw fpv")
    report_bbox.write_bytes(b"report bbox")
    os.utime(raw_fpv, (1, 1))
    os.utime(report_bbox, (3, 3))

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_SDK_CLEANUP))

    assert state["latest_view_assets"]["fpv"]["path"] == str(raw_fpv.resolve())
    assert "display_source" not in state["latest_view_assets"]["fpv"]
    assert "grounding" not in state["latest_view_assets"]
