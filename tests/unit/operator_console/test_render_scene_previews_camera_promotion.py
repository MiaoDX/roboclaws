from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.operator_console.scene_preview_b1 import render_b1_map12_preview
from roboclaws.operator_console.scene_preview_b1_camera import _promote_b1_camera_previews
from tests.unit.operator_console.render_scene_previews_support import (
    _file_sha256,
    _robot_camera_control_contract,
    _write_b1_camera_artifact,
    _write_b1_navigation_smoke_artifact,
    _write_pattern_image,
    _write_stale_b1_real_camera_preview_metadata,
)


def test_b1_map12_preview_promotes_real_isaac_camera_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "0001_observe.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "0001_observe.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "contract": "realworld_cleanup_v1",
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "action": "observe",
                        "label": "0001_observe",
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": {
                            "agent_facing_fpv": {
                                "camera_prim_path": "/World/robot_0/head_camera",
                                "robot_mounted": True,
                                "source": "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
                            },
                            "report_chase_view": {
                                "source": "isaac_lab_camera_rgb_scene_camera:chase",
                            },
                        },
                        "views": {
                            "fpv": "robot_views/0001_observe.fpv.png",
                            "chase": "robot_views/0001_observe.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        camera_artifact=artifact,
    )

    assert result["status"] == "rendered"
    for view_name in ("fpv", "map", "chase", "topdown"):
        assert (tmp_path / f"b1-map12-{view_name}.png").is_file()
    metadata = json.loads((tmp_path / "b1-map12-preview.json").read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_with_isaac_runtime_camera"
    assert set(metadata["views"]) == {"fpv", "map", "chase", "topdown"}
    assert metadata["camera_preview_artifact"]["source_artifact_name"] == "run_result.json"
    assert metadata["camera_preview_artifact"]["source_artifact_sha256"] == _file_sha256(artifact)
    assert "path" not in metadata["camera_preview_artifact"]
    assert metadata["camera_preview_artifact"]["alignment_artifact"] == str(
        run_dir / "alignment_residuals.json"
    )
    assert metadata["camera_preview_artifact"]["alignment_transform_source"] == (
        "reviewed_correspondence_fit"
    )
    assert metadata["views"]["fpv"]["provenance"] == ("isaac_runtime_robot_mounted_head_camera_fpv")
    assert metadata["views"]["fpv"]["camera"] == "/World/robot_0/head_camera"
    assert metadata["views"]["fpv"]["waypoint_id"] == "generated_exploration_002"
    assert metadata["views"]["fpv"]["alignment_transform_source"] == "reviewed_correspondence_fit"
    assert metadata["views"]["chase"]["provenance"] == "isaac_runtime_report_chase_camera"
    assert metadata["views"]["chase"]["source"] == "isaac_lab_camera_rgb_scene_camera:chase"


def test_b1_camera_promotion_rejects_low_detail_pairs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    Image.new("RGB", (64, 48), (120, 120, 120)).save(views_dir / "flat.fpv.png")
    _write_pattern_image(views_dir / "flat.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": "flat",
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": "robot_views/flat.fpv.png",
                            "chase": "robot_views/flat.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    assert result["evaluated_candidates"][0]["status"] == "quality_rejected"
    assert any(
        error.startswith("fpv:") for error in result["evaluated_candidates"][0]["quality_errors"]
    )


def test_b1_camera_promotion_rejects_generic_artifact_without_camera_contract(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "probe.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "probe.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": "probe",
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "views": {
                            "fpv": "robot_views/probe.fpv.png",
                            "chase": "robot_views/probe.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    assert result["evaluated_candidates"][0]["status"] == "provenance_rejected"
    assert (
        "missing_camera_control_contract" in result["evaluated_candidates"][0]["provenance_errors"]
    )


def test_b1_camera_promotion_rejects_scene_probe_camera_sources(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "probe.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "probe.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": "probe",
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": {
                            "agent_facing_fpv": {
                                "robot_mounted": False,
                                "head_camera_equivalent": False,
                                "source": "scene_probe_camera:fpv",
                            },
                            "report_chase_view": {
                                "source": "bbox_fit_scene_probe_camera:chase",
                            },
                        },
                        "views": {
                            "fpv": "robot_views/probe.fpv.png",
                            "chase": "robot_views/probe.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    errors = result["evaluated_candidates"][0]["provenance_errors"]
    assert "fpv_not_robot_mounted_or_head_camera_equivalent" in errors
    assert "fpv_source_not_robot_runtime" in errors
    assert "chase_source_not_robot_runtime" in errors


def test_b1_camera_promotion_rejects_missing_waypoint_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "probe.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "probe.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": "probe",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": "robot_views/probe.fpv.png",
                            "chase": "robot_views/probe.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    assert result["evaluated_candidates"][0]["status"] == "provenance_rejected"
    assert "missing_waypoint_id" in result["evaluated_candidates"][0]["provenance_errors"]


def test_b1_camera_promotion_rejects_mixed_fpv_chase_view_pair(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "point_a.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "point_b.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": "mixed",
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": "robot_views/point_a.fpv.png",
                            "chase": "robot_views/point_b.chase.png",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    assert result["evaluated_candidates"][0]["status"] == "provenance_rejected"
    assert "mixed_fpv_chase_view_pair" in result["evaluated_candidates"][0]["provenance_errors"]


def test_b1_camera_promotion_accepts_navigation_smoke_waypoint_evidence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "waypoint_01_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "point_a.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "point_a.chase.png", accent=(120, 90, 60))
    artifact = _write_b1_navigation_smoke_artifact(
        run_dir,
        fpv_path="waypoint_01_views/point_a.fpv.png",
        chase_path="waypoint_01_views/point_a.chase.png",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "promoted"
    assert result["artifact"]["source_kind"] == "navigation_smoke_waypoint_evidence"
    assert result["views"]["fpv"]["waypoint_id"] == "point_a"


def test_b1_camera_promotion_accepts_repo_relative_navigation_smoke_views(
    tmp_path: Path,
) -> None:
    run_dir = Path("tmp") / "b1-camera-promotion-repo-relative"
    if run_dir.exists():
        import shutil

        shutil.rmtree(run_dir)
    views_dir = run_dir / "waypoint_01_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "point_a.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "point_a.chase.png", accent=(120, 90, 60))
    try:
        artifact = _write_b1_navigation_smoke_artifact(
            run_dir,
            fpv_path=(views_dir / "point_a.fpv.png").as_posix(),
            chase_path=(views_dir / "point_a.chase.png").as_posix(),
        )

        result = _promote_b1_camera_previews(
            camera_artifact=artifact,
            fpv_path=tmp_path / "b1-map12-fpv.png",
            chase_path=tmp_path / "b1-map12-chase.png",
            width=320,
            height=200,
        )
    finally:
        if run_dir.exists():
            import shutil

            shutil.rmtree(run_dir)

    assert result["status"] == "promoted"
    assert result["views"]["fpv"]["waypoint_id"] == "point_a"


def test_b1_camera_promotion_uses_first_accepted_waypoint_pair(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "first.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "first.chase.png", accent=(120, 90, 60))
    _write_pattern_image(views_dir / "second.fpv.png", accent=(240, 240, 240))
    _write_pattern_image(views_dir / "second.chase.png", accent=(30, 180, 220))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": "first",
                        "waypoint_id": "first_waypoint",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": "robot_views/first.fpv.png",
                            "chase": "robot_views/first.chase.png",
                        },
                    },
                    {
                        "label": "second",
                        "waypoint_id": "second_waypoint",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": "robot_views/second.fpv.png",
                            "chase": "robot_views/second.chase.png",
                        },
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "promoted"
    assert result["selection_status"] == "selected_first_accepted_real_isaac_camera_pair"
    assert result["artifact"]["selected_waypoint_id"] == "first_waypoint"
    assert result["views"]["fpv"]["waypoint_id"] == "first_waypoint"


@pytest.mark.parametrize(
    (
        "fpv_path",
        "chase_path",
        "external_dir",
        "chdir_to_tmp",
        "expected_status",
        "expect_empty_source",
    ),
    [
        (
            "stale_views/point_a.fpv.png",
            "stale_views/point_a.chase.png",
            "stale_views",
            True,
            "missing_view_file",
            False,
        ),
        (
            "../outside_views/point_a.fpv.png",
            "../outside_views/point_a.chase.png",
            "outside_views",
            False,
            "missing_view_path",
            True,
        ),
        (
            None,
            None,
            "absolute_views",
            False,
            "missing_view_path",
            True,
        ),
    ],
)
def test_b1_camera_promotion_keeps_relative_views_bound_to_artifact_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fpv_path: str,
    chase_path: str,
    external_dir: str,
    chdir_to_tmp: bool,
    expected_status: str,
    expect_empty_source: bool,
) -> None:
    stale_dir = tmp_path / external_dir
    fpv_path = fpv_path or str(stale_dir / "point_a.fpv.png")
    chase_path = chase_path or str(stale_dir / "point_a.chase.png")
    artifact = _write_b1_navigation_smoke_artifact(
        tmp_path / "run",
        fpv_path=fpv_path,
        chase_path=chase_path,
    )
    stale_dir.mkdir()
    _write_pattern_image(stale_dir / "point_a.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(stale_dir / "point_a.chase.png", accent=(120, 90, 60))
    if chdir_to_tmp:
        monkeypatch.chdir(tmp_path)

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    candidate = result["evaluated_candidates"][0]
    assert candidate["status"] == expected_status
    if expect_empty_source:
        assert candidate["fpv_source"] == ""
        assert candidate["chase_source"] == ""
    else:
        assert candidate["fpv_source"].startswith(str(tmp_path / "run"))
        assert candidate["chase_source"].startswith(str(tmp_path / "run"))
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()


def test_b1_camera_promotion_rejects_missing_residual_alignment_provenance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / "probe.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / "probe.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "robot_view_steps": [
                    {
                        "label": "probe",
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": "robot_views/probe.fpv.png",
                            "chase": "robot_views/probe.chase.png",
                        },
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _promote_b1_camera_previews(
        camera_artifact=artifact,
        fpv_path=tmp_path / "b1-map12-fpv.png",
        chase_path=tmp_path / "b1-map12-chase.png",
        width=320,
        height=200,
    )

    assert result["status"] == "no_usable_camera_pair"
    assert result["evaluated_candidates"][0]["status"] == "provenance_rejected"
    assert result["evaluated_candidates"][0]["provenance_errors"] == [
        "missing_alignment_artifact",
        "missing_reviewed_correspondence_transform_source",
    ]


def test_b1_map12_skip_existing_requires_matching_camera_artifact(tmp_path: Path) -> None:
    old_artifact = tmp_path / "old-run" / "run_result.json"
    new_artifact = _write_b1_camera_artifact(tmp_path / "new-run", label="fresh_observe")
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=old_artifact,
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
        camera_artifact=new_artifact,
    )

    assert result["status"] == "rendered"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["camera_preview_artifact"]["source_artifact_name"] == "run_result.json"
    assert metadata["camera_preview_artifact"]["source_artifact_sha256"] == _file_sha256(
        new_artifact
    )
    assert "path" not in metadata["camera_preview_artifact"]
    assert metadata["camera_preview_artifact"]["selected_label"] == "fresh_observe"
    assert metadata["views"]["fpv"]["label"] == "fresh_observe"
    assert metadata["views"]["chase"]["label"] == "fresh_observe"
