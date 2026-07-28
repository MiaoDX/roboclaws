from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.launch.scene_sampler import MolmoSpacesSceneRef
from scripts.operator_console.render_scene_previews import (
    B1_MAP12_WORLD_ID,
    PREVIEW_METADATA_SCHEMA,
    _first_public_waypoint,
    _molmospaces_scene_ref,
    _preview_metadata,
    _promote_b1_camera_previews,
    _scene_alignment,
    _scene_center_and_span,
    _topdown_camera_request,
    parse_args,
    render_b1_map12_preview,
)


def test_render_scene_previews_rejects_non_positive_dimensions() -> None:
    for flag in ("--width", "--height"):
        try:
            parse_args([flag, "0"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - argparse should exit for invalid input
            raise AssertionError(f"expected invalid {flag} to fail at parse time")


def test_render_scene_previews_accepts_positive_dimensions() -> None:
    args = parse_args(["--width", "1", "--height", "1"])

    assert args.width == 1
    assert args.height == 1


def test_topdown_preview_request_uses_scene_camera_not_semantic_map() -> None:
    state = {
        "room_outlines": [
            {"center": [1.0, 2.0, 0.0], "half_extents": [2.0, 3.0]},
            {"center": [5.0, 4.0, 0.0], "half_extents": [1.0, 1.5]},
        ],
        "objects": {"mug_01": {"position": [6.0, 5.0, 0.8]}},
        "receptacles": {"sink_01": {"position": [-1.0, -1.0, 0.9]}},
    }

    request = _topdown_camera_request(state, width=900, height=560)

    view = request["views"][0]
    assert request["camera_model"] == "canonical_eye_target_camera_v1"
    assert request["render_resolution"] == {"width": 900, "height": 560}
    assert view["view_id"] == "topdown_scene"
    assert view["camera_basis"] == "whole_scene_true_topdown_aligned_to_scene_bounds"
    assert view["eye"][2] > view["target"][2]
    assert view["eye"][:2] == pytest.approx(view["target"][:2])
    assert view["azimuth"] == pytest.approx(90.0)
    assert view["scene_alignment"]["schema"] == "operator_console_scene_alignment_v1"


def test_preview_metadata_marks_topdown_as_rendered_scene_not_map_fallback(
    tmp_path: Path,
) -> None:
    fpv_path = tmp_path / "molmospaces-val_9-fpv.png"
    map_path = tmp_path / "molmospaces-val_9-map.png"
    chase_path = tmp_path / "molmospaces-val_9-chase.png"
    topdown_path = tmp_path / "molmospaces-val_9-topdown.png"
    Image.new("RGB", (8, 8), (20, 30, 40)).save(fpv_path)
    Image.new("RGB", (8, 8), (30, 40, 50)).save(map_path)
    Image.new("RGB", (8, 8), (100, 120, 140)).save(chase_path)
    Image.new("RGB", (8, 8), (60, 90, 120)).save(topdown_path)
    scene_alignment = {
        "schema": "operator_console_scene_alignment_v1",
        "bounds": {"min_x": 0.0, "max_x": 4.0, "min_y": 0.0, "max_y": 3.0},
        "center": [2.0, 1.5, 0.4],
        "span_x_m": 4.0,
        "span_y_m": 3.0,
        "camera_span_m": 4.0,
        "screen_coordinate_convention": "screen_x_world_positive_x_screen_y_world_negative_y",
        "topdown_azimuth_deg": 90.0,
    }

    metadata = _preview_metadata(
        world_id="molmospaces/val_9",
        scene_source="procthor-10k-val",
        scene_index=9,
        seed=7,
        width=900,
        height=560,
        waypoint={"waypoint_id": "generated_exploration_001"},
        navigation={"status": "ok"},
        robot_views={
            "camera_diagnostics": {
                "views": {
                    "fpv": {"status": "ready", "camera_name": "robot_0/head_camera"},
                    "chase": {
                        "status": "ready",
                        "camera_name": "robot_0/camera_follower",
                    },
                }
            }
        },
        topdown_result={
            "views": [
                {
                    "view_id": "topdown_scene",
                    "eye": [1.0, 2.0, 10.0],
                    "target": [1.0, 2.0, 0.4],
                    "azimuth": 90.0,
                    "elevation": -90.0,
                    "distance": 9.6,
                }
            ]
        },
        topdown_request={"camera_model": "canonical_eye_target_camera_v1"},
        fpv_path=fpv_path,
        map_path=map_path,
        chase_path=chase_path,
        chase_waypoint={"waypoint_id": "generated_exploration_004"},
        chase_navigation={"status": "ok"},
        chase_robot_views={
            "camera_diagnostics": {
                "views": {
                    "chase": {
                        "status": "ready",
                        "camera_name": "robot_0/camera_follower",
                    }
                }
            }
        },
        chase_selection={
            "status": "alternate_waypoint_reviewable",
            "candidate_count_evaluated": 4,
        },
        topdown_path=topdown_path,
        scene_alignment=scene_alignment,
    )

    assert metadata["schema"] == PREVIEW_METADATA_SCHEMA
    assert metadata["scene_source"] == "procthor-10k-val"
    assert metadata["views"]["fpv"]["view"] == "raw_fpv"
    assert metadata["views"]["fpv"]["provenance"] == (
        "mujoco_robot_head_camera_first_public_waypoint"
    )
    assert metadata["views"]["chase"]["view"] == "chase_camera"
    assert metadata["views"]["chase"]["provenance"] == (
        "mujoco_robot_camera_follower_public_waypoint"
    )
    assert metadata["views"]["chase"]["waypoint_id"] == "generated_exploration_004"
    assert metadata["views"]["chase"]["selection_status"] == "alternate_waypoint_reviewable"
    assert metadata["views"]["chase"]["candidate_count_evaluated"] == 4
    assert metadata["views"]["chase"]["path"].endswith("-chase.png")
    assert metadata["views"]["chase"]["camera_diagnostics"]["camera_name"] == (
        "robot_0/camera_follower"
    )
    assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["visual_role"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
    assert metadata["views"]["map"]["provenance"] == "map_bundle_preview_png"
    assert "scene_alignment" not in metadata["views"]["map"]
    assert "semantic_projection" not in metadata["views"]["map"]
    assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["visual_role"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
    assert metadata["views"]["topdown"]["camera_pose"]["azimuth"] == pytest.approx(90.0)
    assert metadata["views"]["topdown"]["scene_alignment"] == scene_alignment
    assert metadata["views"]["topdown"]["path"].endswith("-topdown.png")
    assert metadata["views"]["topdown"]["image_diagnostics"]["visual_status"] == "low_detail"


def test_molmospaces_preview_scene_ref_preserves_legacy_alias_source() -> None:
    assert _molmospaces_scene_ref("molmospaces/val_9") == MolmoSpacesSceneRef(
        scene_source="procthor-10k-val",
        scene_index=9,
    )


def test_molmospaces_preview_scene_ref_accepts_source_aware_world_id() -> None:
    assert _molmospaces_scene_ref("molmospaces/ithor/3") == MolmoSpacesSceneRef(
        scene_source="ithor",
        scene_index=3,
    )
    assert _molmospaces_scene_ref("molmospaces/procthor-objaverse-val/12") == (
        MolmoSpacesSceneRef(scene_source="procthor-objaverse-val", scene_index=12)
    )


def test_molmospaces_preview_scene_ref_rejects_unknown_source_or_index() -> None:
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene_source"):
        _molmospaces_scene_ref("molmospaces/unknown-source/1")
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene index"):
        _molmospaces_scene_ref("molmospaces/ithor/not-an-index")
    with pytest.raises(ValueError, match="negative MolmoSpaces scene index"):
        _molmospaces_scene_ref("molmospaces/ithor/-1")


def test_b1_map12_preview_generates_static_map_and_gaussian_topdown_assets(
    tmp_path: Path,
) -> None:
    Image.new("RGB", (16, 16), (10, 20, 30)).save(tmp_path / "b1-map12-map.png")
    Image.new("RGB", (16, 16), (30, 20, 10)).save(tmp_path / "b1-map12-topdown.png")

    result = render_b1_map12_preview(output_dir=tmp_path, width=320, height=200)

    assert result["world_id"] == B1_MAP12_WORLD_ID
    assert result["status"] == "rendered"
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    metadata = json.loads((tmp_path / "b1-map12-preview.json").read_text(encoding="utf-8"))
    assert metadata["schema"] == PREVIEW_METADATA_SCHEMA
    assert metadata["backend"] == "isaaclab"
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert set(metadata["views"]) == {"map", "topdown"}
    assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
    assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
    assert metadata["views"]["topdown"]["provenance"] == "b1_scene_gaussian_topdown_crop_z1p8_png"
    assert metadata["views"]["topdown"]["alignment_status"] == (
        "height_cropped_gaussian_scene_topdown"
    )
    assert metadata["views"]["topdown"]["source_packet"] == (
        "output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json"
    )
    assert metadata["views"]["topdown"]["source_status"] in {
        "captured_gaussian_topdown_packet",
        "checked_in_operator_preview_png",
    }
    assert "first_waypoint_id" not in metadata["views"]["topdown"]
    assert "diagnostic_views" not in metadata
    assert "runtime_map_bundle" not in metadata


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


def test_b1_map12_skip_existing_rewrites_stale_camera_preview_metadata(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), (1, 2, 3)).save(tmp_path / "b1-map12-fpv.png")
    Image.new("RGB", (16, 16), (4, 5, 6)).save(tmp_path / "b1-map12-chase.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "views": {
                    "fpv": {"path": "b1-map12-fpv.png"},
                    "chase": {"path": "b1-map12-chase.png"},
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_map12_reviewed_semantic_topdown_png",
                    },
                },
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
        skip_existing=True,
    )

    assert result["status"] == "rendered"
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]
    assert metadata["views"]["topdown"]["provenance"] == "b1_scene_gaussian_topdown_crop_z1p8_png"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"


def test_b1_map12_rewrites_prepared_nurec_scene_probe_camera_previews(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), (80, 90, 100)).save(tmp_path / "b1-map12-fpv.png")
    Image.new("RGB", (16, 16), (100, 90, 80)).save(tmp_path / "b1-map12-chase.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "renderer": "static_b1_map12_with_prepared_nurec_camera_previews",
                "views": {
                    "fpv": {
                        "path": "b1-map12-fpv.png",
                        "provenance": "prepared_b1_nurec_scene_camera_preview",
                    },
                    "chase": {
                        "path": "b1-map12-chase.png",
                        "provenance": "prepared_b1_nurec_scene_camera_preview",
                    },
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_scene_gaussian_topdown_crop_z1p8_png",
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    result = render_b1_map12_preview(output_dir=tmp_path, width=320, height=200)

    assert result["status"] == "rendered"
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]


def test_b1_map12_skip_existing_rewrites_missing_real_camera_files(tmp_path: Path) -> None:
    Image.new("RGB", (16, 16), (10, 20, 30)).save(tmp_path / "b1-map12-map.png")
    Image.new("RGB", (16, 16), (30, 20, 10)).save(tmp_path / "b1-map12-topdown.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "views": {
                    "fpv": {
                        "path": "b1-map12-fpv.png",
                        "provenance": "isaac_runtime_robot_mounted_head_camera_fpv",
                    },
                    "chase": {
                        "path": "b1-map12-chase.png",
                        "provenance": "isaac_runtime_report_chase_camera",
                    },
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_scene_gaussian_topdown_crop_z1p8_png",
                    },
                },
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
        skip_existing=True,
    )

    assert result["status"] == "rendered"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]


def test_b1_map12_skip_existing_rewrites_real_camera_metadata_without_alignment(
    tmp_path: Path,
) -> None:
    old_artifact = tmp_path / "old-run" / "run_result.json"
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=old_artifact,
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
        camera_artifact=old_artifact,
    )

    assert result["status"] == "camera_preview_unavailable"
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "fpv" not in metadata["views"]
    assert "chase" not in metadata["views"]
    assert "map" in metadata["views"]
    assert "topdown" in metadata["views"]


def test_b1_map12_skip_existing_keeps_complete_matching_camera_metadata(tmp_path: Path) -> None:
    artifact = tmp_path / "run" / "run_result.json"
    alignment_artifact = tmp_path / "run" / "alignment_residuals.json"
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=artifact,
        waypoint_id="generated_exploration_002",
        alignment_artifact=alignment_artifact,
        alignment_transform_source="reviewed_correspondence_fit",
    )

    result = render_b1_map12_preview(
        output_dir=tmp_path,
        width=320,
        height=200,
        skip_existing=True,
        camera_artifact=artifact,
    )

    assert result["status"] == "skipped"
    assert result["metadata"] == str(metadata_path)
    assert (tmp_path / "b1-map12-fpv.png").exists()
    assert (tmp_path / "b1-map12-chase.png").exists()


def test_b1_map12_static_preview_does_not_carry_forward_real_camera_previews(
    tmp_path: Path,
) -> None:
    metadata_path = _write_stale_b1_real_camera_preview_metadata(
        tmp_path,
        artifact_path=tmp_path / "old-run" / "run_result.json",
    )

    result = render_b1_map12_preview(output_dir=tmp_path, width=320, height=200)

    assert result["status"] == "rendered"
    assert set(result["removed_stale"]) == {
        str(tmp_path / "b1-map12-fpv.png"),
        str(tmp_path / "b1-map12-chase.png"),
    }
    assert not (tmp_path / "b1-map12-fpv.png").exists()
    assert not (tmp_path / "b1-map12-chase.png").exists()
    assert (tmp_path / "b1-map12-map.png").is_file()
    assert (tmp_path / "b1-map12-topdown.png").is_file()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_previews"
    assert "camera_preview_artifact" not in metadata
    assert set(metadata["views"]) == {"map", "topdown"}


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


def _write_stale_b1_real_camera_preview_metadata(
    tmp_path: Path,
    *,
    artifact_path: Path,
    waypoint_id: str = "",
    alignment_artifact: Path | None = None,
    alignment_transform_source: str = "",
) -> Path:
    alignment_artifact_raw = str(alignment_artifact or "")
    Image.new("RGB", (16, 16), (10, 20, 30)).save(tmp_path / "b1-map12-map.png")
    Image.new("RGB", (16, 16), (30, 20, 10)).save(tmp_path / "b1-map12-topdown.png")
    Image.new("RGB", (16, 16), (120, 130, 140)).save(tmp_path / "b1-map12-fpv.png")
    Image.new("RGB", (16, 16), (80, 90, 100)).save(tmp_path / "b1-map12-chase.png")
    metadata_path = tmp_path / "b1-map12-preview.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema": PREVIEW_METADATA_SCHEMA,
                "renderer": "static_b1_map12_with_isaac_runtime_camera_previews",
                "camera_preview_artifact": {
                    "path": str(artifact_path),
                    "selected_waypoint_id": waypoint_id,
                    "alignment_artifact": alignment_artifact_raw,
                    "alignment_transform_source": alignment_transform_source,
                },
                "views": {
                    "fpv": {
                        "path": "b1-map12-fpv.png",
                        "waypoint_id": waypoint_id,
                        "alignment_artifact": alignment_artifact_raw,
                        "alignment_transform_source": alignment_transform_source,
                        "provenance": "isaac_runtime_robot_mounted_head_camera_fpv",
                    },
                    "chase": {
                        "path": "b1-map12-chase.png",
                        "waypoint_id": waypoint_id,
                        "alignment_artifact": alignment_artifact_raw,
                        "alignment_transform_source": alignment_transform_source,
                        "provenance": "isaac_runtime_report_chase_camera",
                    },
                    "map": {
                        "path": "b1-map12-map.png",
                        "provenance": "b1_map12_base_metric_map_preview_png",
                    },
                    "topdown": {
                        "path": "b1-map12-topdown.png",
                        "provenance": "b1_scene_gaussian_topdown_crop_z1p8_png",
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return metadata_path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_b1_camera_artifact(run_dir: Path, *, label: str) -> Path:
    views_dir = run_dir / "robot_views"
    views_dir.mkdir(parents=True)
    _write_pattern_image(views_dir / f"{label}.fpv.png", accent=(220, 220, 220))
    _write_pattern_image(views_dir / f"{label}.chase.png", accent=(120, 90, 60))
    artifact = run_dir / "run_result.json"
    artifact.write_text(
        json.dumps(
            {
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "robot_view_steps": [
                    {
                        "label": label,
                        "waypoint_id": "generated_exploration_002",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "camera_control_contract": _robot_camera_control_contract(),
                        "views": {
                            "fpv": f"robot_views/{label}.fpv.png",
                            "chase": f"robot_views/{label}.chase.png",
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
    return artifact


def _write_b1_navigation_smoke_artifact(
    run_dir: Path,
    *,
    fpv_path: str,
    chase_path: str,
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact = run_dir / "navigation_smoke.json"
    artifact.write_text(
        json.dumps(
            {
                "schema": "b1_map12_navigation_smoke_v1",
                "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "waypoint_evidence": [
                    {
                        "waypoint_id": "point_a",
                        "robot_pose_applied": True,
                        "alignment_artifact": str(run_dir / "alignment_residuals.json"),
                        "alignment_transform_source": "reviewed_correspondence_fit",
                        "views": {"fpv": fpv_path, "chase": chase_path},
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact


def _robot_camera_control_contract() -> dict[str, object]:
    return {
        "agent_facing_fpv": {
            "camera_prim_path": "/World/robot_0/head_camera",
            "robot_mounted": True,
            "source": "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
        },
        "report_chase_view": {
            "source": "isaac_lab_camera_rgb_scene_camera:chase",
        },
    }


def _write_pattern_image(path: Path, *, accent: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (96, 64), (48, 56, 64))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if (x // 6 + y // 4) % 2 == 0:
                pixels[x, y] = accent
            elif x == y or x + y == image.width - 1:
                pixels[x, y] = (20, 24, 28)
    image.save(path)


def test_preview_helpers_use_first_public_waypoint_and_scene_bounds() -> None:
    waypoint = _first_public_waypoint(
        {"inspection_waypoints": [{"waypoint_id": "first"}, {"waypoint_id": "second"}]}
    )
    center, span = _scene_center_and_span(
        {"room_outlines": [{"center": [2.0, 3.0], "half_extents": [1.0, 2.0]}]}
    )

    assert waypoint["waypoint_id"] == "first"
    assert center == pytest.approx([2.0, 3.0, 0.4])
    assert span >= 4.0


def test_scene_alignment_expands_bounds_to_preview_aspect() -> None:
    alignment = _scene_alignment(
        {"room_outlines": [{"center": [2.0, 3.0], "half_extents": [1.0, 2.0]}]},
        width=900,
        height=560,
    )

    assert alignment["schema"] == "operator_console_scene_alignment_v1"
    assert (
        alignment["screen_coordinate_convention"]
        == "screen_x_world_positive_x_screen_y_world_negative_y"
    )
    assert alignment["topdown_azimuth_deg"] == pytest.approx(90.0)
    assert alignment["span_x_m"] / alignment["span_y_m"] == pytest.approx(900 / 560)
