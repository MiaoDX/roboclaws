from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.backends.isaaclab import runtime as runtime_cli
from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_dependencies as runtime_dependencies
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _unit_isaac_object_index,
    _unit_isaac_receptacle_index,
    _write_nonblank_image,
    _write_robot_view_images,
)


def test_isaac_lab_real_worker_robot_views_use_imported_head_camera(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    robot_usd = tmp_path / "rby1m_holobase_isaac.usda"
    summary_path = tmp_path / "rby1m_holobase_isaac.import_summary.json"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    robot_usd.write_text("#usda 1.0\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps({"schema": "isaac_rby1m_robot_usd_import_v1", "status": "ready"}) + "\n",
        encoding="utf-8",
    )
    _write_nonblank_image(image_path)

    monkeypatch.setattr(runtime_state, "ISAAC_RBY1M_ROBOT_USD_PATH", robot_usd)
    monkeypatch.setattr(
        runtime_dependencies,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(runtime_state, "_repo_path", lambda path: path)

    def fake_real_runtime_smoke(args: object, scenario: object) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "robot_view_uses_mounted_head_camera": True,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
    ) -> dict[str, object]:
        del state, scene_usd, width, height, focus_object_id, focus_receptacle_id
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 11,
            "robot_view_uses_mounted_head_camera": True,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 1,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "robot_stage": {
                "status": "referenced",
                "head_camera_prim_exists": True,
                "head_camera_prim_path": "/World/robot_0/head_camera",
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {
                    "fpv": {
                        "schema": "isaac_usd_camera_diagnostics_v1",
                        "status": "ready",
                        "camera_type": "usd_camera_prim",
                        "prim_path": "/World/robot_0/head_camera",
                    },
                    "chase": {
                        "schema": "isaac_eye_target_camera_diagnostics_v1",
                        "status": "ready",
                        "camera_type": "eye_target_scene_camera",
                        "camera_basis": "robot_relative_camera_follower",
                        "vertical_fov_deg": 45.0,
                    },
                },
            },
        }

    monkeypatch.setattr(runtime_capture, "real_runtime_smoke", fake_real_runtime_smoke)
    monkeypatch.setattr(
        runtime_capture,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    init_args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
            "--scene-usd-path",
            str(scene_usd),
        ]
    )
    init = runtime_initialization.init_state(init_args)
    assert init["robot"]["embodiment"] == "rby1m"
    assert init["robot_import"]["status"] == "imported"
    state = runtime_commands.read_state(state_path)
    state["semantic_pose_state"]["robot_pose"] = {
        "frame": "molmospaces_scene_frame_v1",
        "x": 6.37057,
        "y": 8.8752,
        "z": 0.0,
        "theta": math.pi / 2.0,
        "yaw_deg": 90.0,
        "head_pitch": 0.653613,
        "pose_source": "apple2apple_shared_robot_pose",
    }
    runtime_commands.write_state(state_path, state)

    result = runtime_commands.write_robot_views(
        runtime_cli.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_semantic_pose",
                "--render-width",
                "64",
                "--render-height",
                "48",
            ]
        ),
        runtime_commands.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_provenance"]["robot_mounted_head_camera"] is True
    assert result["view_provenance"]["head_camera_equivalent"] is False
    assert result["camera_control_contract"]["status"] == "robot_mounted_head_camera_robot_view"
    assert result["camera_control_contract"]["camera_model"] == "robot_mounted_head_camera_v1"
    assert result["camera_control_contract"]["agent_facing_fpv"]["robot_mounted"] is True
    assert result["camera_control_contract"]["agent_facing_fpv"]["camera_prim_path"] == (
        "/World/robot_0/head_camera"
    )
    assert result["camera_control_contract"]["report_chase_view"]["source"] == (
        "robot_relative_camera_follower"
    )
    assert result["camera_control_contract"]["robot_pose"]["pose_source"] == (
        "apple2apple_shared_robot_pose"
    )
    assert result["camera_control_contract"]["robot_pose"]["x"] == pytest.approx(6.37057)
    assert result["camera_control_contract"]["robot_pose"]["yaw_deg"] == pytest.approx(90.0)
    assert result["camera_diagnostics"]["schema"] == "isaac_robot_view_camera_diagnostics_v1"
    assert result["camera_diagnostics"]["views"]["fpv"]["prim_path"] == (
        "/World/robot_0/head_camera"
    )
    assert result["camera_diagnostics"]["views"]["chase"]["camera_basis"] == (
        "robot_relative_camera_follower"
    )
    assert result["camera_diagnostics"]["views"]["chase"]["vertical_fov_deg"] == pytest.approx(45.0)
    state = runtime_commands.read_state(state_path)
    assert state["semantic_pose_view_capture"]["robot_mounted_head_camera"] is True
    assert state["semantic_pose_view_capture"]["head_camera_equivalent"] is False


def test_isaac_lab_real_worker_robot_views_record_capture_quality_settle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(args: object, scenario: object) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(scene_usd),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    def fake_capture_semantic_pose_robot_views(**kwargs: object) -> dict[str, object]:
        assert kwargs["render_settle_frames"] == 16
        view_paths = kwargs["view_paths"]
        assert isinstance(view_paths, dict)
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 80,
            "render_settle_frames": 16,
            "robot_view_uses_mounted_head_camera": True,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 1,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "render_settle_frames": 16,
                "native_render_diagnostics": {
                    "schema": "isaac_native_render_diagnostics_v1",
                    "status": "captured",
                    "capture_quality_settings": {
                        "schema": "isaac_capture_quality_settings_v1",
                        "render_settle_frames": 16,
                        "anti_aliasing": {"status": "not_available", "value": None},
                        "denoise": {"status": "not_available", "value": None},
                        "taa": {"status": "not_available", "value": None},
                        "samples_per_pixel": {"status": "not_available", "value": None},
                        "texture_filtering": {"status": "not_available", "value": None},
                    },
                },
            },
            "native_render_diagnostics": {
                "schema": "isaac_native_render_diagnostics_v1",
                "status": "captured",
                "default_render_settings_changed": False,
                "capture_quality_settings": {
                    "schema": "isaac_capture_quality_settings_v1",
                    "render_settle_frames": 16,
                    "anti_aliasing": {"status": "not_available", "value": None},
                    "denoise": {"status": "not_available", "value": None},
                    "taa": {"status": "not_available", "value": None},
                    "samples_per_pixel": {"status": "not_available", "value": None},
                    "texture_filtering": {"status": "not_available", "value": None},
                },
            },
        }

    monkeypatch.setattr(runtime_capture, "real_runtime_smoke", fake_real_runtime_smoke)
    monkeypatch.setattr(
        runtime_capture,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    runtime_initialization.init_state(
        runtime_cli.parse_args(
            [
                "--state-path",
                str(state_path),
                "init",
                "--run-dir",
                str(run_dir),
                "--runtime-mode",
                "real",
                "--include-robot",
                "--scene-usd-path",
                str(scene_usd),
            ]
        )
    )
    result = runtime_commands.write_robot_views(
        runtime_cli.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_settle",
                "--render-width",
                "64",
                "--render-height",
                "48",
                "--render-settle-frames",
                "16",
            ]
        ),
        runtime_commands.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["render_settle_frames"] == 16
    assert result["camera_diagnostics"]["render_settle_frames"] == 16
    assert (
        result["native_render_diagnostics"]["capture_quality_settings"]["render_settle_frames"]
        == 16
    )
    state = runtime_commands.read_state(state_path)
    assert state["semantic_pose_view_capture"]["render_settle_frames"] == 16
    assert (
        state["native_render_diagnostics"]["capture_quality_settings"]["render_settle_frames"] == 16
    )


def test_isaac_lab_real_worker_snapshot_reuses_real_smoke_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    _write_nonblank_image(image_path)

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(image_path),
            "scene_usd": str(run_dir / "scene.usda"),
            "loaded_asset_kind": "generated_runtime_smoke_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "requested_molmospaces_scene_usd": "molmospaces://procthor-10k-val/scene-0.usd",
            "isaac_lab_version": "unit-isaaclab",
            "isaac_sim_version": "unit-isaacsim",
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 4,
            "scene_index_diagnostics": {
                "schema": "isaac_usd_scene_index_v1",
                "status": "indexed",
                "source": str(run_dir / "scene.usda"),
                "stage_prim_count": 6,
                "object_candidate_count": 1,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": _unit_isaac_object_index(),
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    init_args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
        ]
    )
    runtime_initialization.init_state(init_args)
    snapshot_path = run_dir / "before.png"
    snapshot_args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "snapshot",
            "--output-path",
            str(snapshot_path),
            "--title",
            "Before cleanup",
            "--render-width",
            "64",
            "--render-height",
            "48",
        ]
    )
    result = runtime_commands.write_snapshot(
        snapshot_args,
        runtime_commands.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["placeholder_visuals"] is False
    assert result["visual_artifact_provenance"] == "isaac_lab_camera_rgb"
    assert result["snapshot_provenance"]["source_path"] == str(image_path)
    assert result["snapshot_provenance"]["static_isaac_capture"] is True
    assert result["snapshot_provenance"]["semantic_pose_rendered"] is False
    with Image.open(snapshot_path) as image:
        assert image.size == (64, 48)
