from __future__ import annotations

import json
from pathlib import Path

from roboclaws.backends.isaaclab.b1_navigation_report import main as render_main
from roboclaws.backends.isaaclab.b1_navigation_smoke import parse_args as smoke_parse_args
from roboclaws.backends.isaaclab.b1_readiness_artifacts import readiness_artifact_with_navigation
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    READINESS_SCHEMA,
    SEMANTIC_SOURCE,
    SEMANTIC_USD_BLOCKED,
    WAYPOINT_POSE_REQUESTS_SCHEMA,
)
from tests.contract.maps.test_b1_map12_digital_twin_readiness import (
    _write_reviewable_image,
    navigation_payload,
    static_readiness_payload,
)


def test_b1_map12_navigation_smoke_rejects_non_positive_render_dimensions() -> None:
    for flag, value in (("--render-width", "0"), ("--render-height", "-1")):
        try:
            smoke_parse_args([flag, value])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - argparse should exit for invalid input
            raise AssertionError(f"expected invalid {flag} to fail at parse time")


def test_b1_map12_navigation_smoke_accepts_positive_render_dimensions() -> None:
    args = smoke_parse_args(["--render-width", "1280", "--render-height", "720"])

    assert args.render_width == 1280
    assert args.render_height == 720


def test_b1_map12_navigation_report_renders_reviewable_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    navigation = navigation_payload(run_dir)
    for index, waypoint in enumerate(navigation["waypoint_evidence"], start=1):
        views = waypoint["views"]
        view_dir = run_dir / f"waypoint_{index:02d}_views"
        view_dir.mkdir()
        for view_name in ("chase", "map", "verify"):
            path = view_dir / f"{waypoint['waypoint_id']}.{view_name}.png"
            _write_reviewable_image(path, offset=20 * index)
            views[view_name] = str(path)
    navigation["validation"] = {"status": "passed", "errors": []}
    readiness = readiness_artifact_with_navigation(
        static_readiness_payload(),
        navigation,
        navigation_artifact_path=run_dir / "navigation_smoke.json",
    )
    readiness["schema"] = READINESS_SCHEMA
    readiness["semantic_source"] = SEMANTIC_SOURCE
    readiness["semantic_usd_binding_status"] = SEMANTIC_USD_BLOCKED
    readiness["readiness_alignment_status"] = "global_verified"
    readiness["map12_to_b1_usd_transform_status"] = "verified"
    readiness["residual_evidence"] = {
        "status": "available",
        "matched_anchor_count": 6,
        "mean_residual_m": 0.23,
        "max_residual_m": 0.71,
        "transform_source": "reviewed_correspondence_fit",
    }
    readiness["validation"] = {"status": "passed", "errors": []}
    pose_requests = {
        "schema": WAYPOINT_POSE_REQUESTS_SCHEMA,
        "status": "blocked",
        "semantic_source": SEMANTIC_SOURCE,
        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "selected_transform_type": "mixed",
        "source_map_frame": "robot_map_12_map",
        "target_scene_frame": "b1_rebuilt_scene_usd_world",
        "waypoint_count": 1,
        "waypoints": [
            {
                "waypoint_id": "manual_point_a",
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "selected_transform_type": "rigid_2d",
                "coverage_decision": {
                    "status": "verified_global",
                    "fit_scope": "global_transform",
                },
                "map12_nav_goal": {"x": -8.0, "y": 0.0, "yaw_deg": 90.0},
                "b1_pose": {
                    "frame": "b1_rebuilt_scene_usd_world",
                    "x": -6.6,
                    "y": -8.0,
                    "z": 0.0,
                    "yaw_deg": 90.0,
                },
                "planner_backed": False,
                "physical_robot": False,
            }
        ],
        "blocked_request_count": 1,
        "blocked_requests": [
            {
                "waypoint_id": "unknown_area",
                "request_status": "blocked",
                "reason": "navigation_area_id 'not_verified_area' is not verified",
                "coverage_decision": {
                    "status": "blocked",
                    "fit_scope": "local_area_transform",
                    "navigation_area_id": "not_verified_area",
                },
                "map12_nav_goal": {"x": 0.5, "y": 0.5},
                "planner_backed": False,
                "physical_robot": False,
            }
        ],
        "artifact_errors": [],
        "planner_backed": False,
        "physical_robot": False,
        "robot_navigation_supported": False,
        "validation": {"status": "passed", "errors": []},
    }
    (run_dir / "navigation_smoke.json").write_text(
        json.dumps(navigation, indent=2),
        encoding="utf-8",
    )
    (run_dir / "readiness_with_navigation.json").write_text(
        json.dumps(readiness, indent=2),
        encoding="utf-8",
    )
    (run_dir / "waypoint_pose_requests.json").write_text(
        json.dumps(pose_requests, indent=2),
        encoding="utf-8",
    )

    rc = render_main(["--run-dir", str(run_dir)])

    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert rc == 0
    assert "B1 / Map 12 Navigation Smoke" in report
    assert "navigation_ready" in report
    assert "kinematic_pose_driven" in report
    assert "blocked_until_segmentation_or_manifest" in report
    assert "manipulation: unsupported" in report
    assert "global_verified" in report
    assert "available, anchors=6, mean=0.23 m, max=0.71 m" in report
    assert "Waypoint Pose Requests" in report
    assert "manual_point_a" in report
    assert "verified_global / global_transform" in report
    assert "unknown_area" in report
    assert "navigation_area_id &#x27;not_verified_area&#x27; is not verified" in report
    assert "known-poor search seed" in report
    assert "planner-backed" not in report
    assert "first.fpv.png" in report
    assert "wp_1.chase.png" in report
    assert "navigation_smoke.json" in report
    assert "readiness_with_navigation.json" in report
    assert "waypoint_pose_requests.json" in report


def test_b1_map12_navigation_report_rejects_explicit_missing_optional_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "navigation_smoke.json").write_text(
        json.dumps(navigation_payload(run_dir), indent=2),
        encoding="utf-8",
    )

    missing_readiness = run_dir / "missing_readiness.json"

    message = _assert_render_fails_without_report(
        [
            "--run-dir",
            str(run_dir),
            "--readiness-artifact",
            str(missing_readiness),
        ],
        run_dir=run_dir,
    )

    assert f"readiness artifact source is missing: {missing_readiness}" in message
    assert not (run_dir / "report.html").exists()


def test_b1_map12_navigation_report_rejects_malformed_navigation_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "navigation_smoke.json").write_text("{not-json\n", encoding="utf-8")

    message = _assert_render_fails_without_report(["--run-dir", str(run_dir)], run_dir=run_dir)

    assert "navigation artifact source must contain valid JSON object" in message
    assert not (run_dir / "report.html").exists()


def test_b1_map12_navigation_report_rejects_present_malformed_default_sidecar(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "navigation_smoke.json").write_text(
        json.dumps(navigation_payload(run_dir), indent=2),
        encoding="utf-8",
    )
    (run_dir / "readiness_with_navigation.json").write_text("{not-json\n", encoding="utf-8")

    message = _assert_render_fails_without_report(["--run-dir", str(run_dir)], run_dir=run_dir)

    assert "readiness artifact source must contain valid JSON object" in message
    assert not (run_dir / "report.html").exists()


def test_b1_map12_navigation_report_rejects_non_object_waypoint_pose_requests(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pose_requests = run_dir / "waypoint_pose_requests.json"
    (run_dir / "navigation_smoke.json").write_text(
        json.dumps(navigation_payload(run_dir), indent=2),
        encoding="utf-8",
    )
    pose_requests.write_text("[]\n", encoding="utf-8")

    message = _assert_render_fails_without_report(
        [
            "--run-dir",
            str(run_dir),
            "--waypoint-pose-requests",
            str(pose_requests),
        ],
        run_dir=run_dir,
    )

    assert (
        f"waypoint pose request artifact source must contain a JSON object: {pose_requests}"
        in message
    )
    assert not (run_dir / "report.html").exists()


def _assert_render_fails_without_report(argv: list[str], *, run_dir: Path) -> str:
    try:
        render_main(argv)
    except (FileNotFoundError, ValueError) as exc:
        message = str(exc)
    else:  # pragma: no cover - source truth must fail before report writes
        raise AssertionError("expected navigation report rendering to fail")
    assert not (run_dir / "report.html").exists()
    return message
