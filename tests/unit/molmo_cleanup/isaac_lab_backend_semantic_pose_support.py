from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.backends.isaaclab import runtime as runtime_cli
from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _unit_isaac_object_index,
    _unit_isaac_receptacle_index,
    _write_nonblank_image,
    _write_robot_view_images,
)


def _setup_semantic_pose_recapture_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SimpleNamespace:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "scene.usda"
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    _write_nonblank_image(image_path)
    monkeypatch.setattr(
        runtime_state,
        "ISAAC_RBY1M_ROBOT_USD_PATH",
        tmp_path / "missing_rby1m_holobase_isaac.usda",
    )
    monkeypatch.setattr(
        runtime_state,
        "ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH",
        tmp_path / "missing_rby1m_holobase_isaac.import_summary.json",
    )
    context = SimpleNamespace(
        run_dir=run_dir,
        state_path=state_path,
        image_path=image_path,
        robot_view_images=robot_view_images,
        scene_usd=scene_usd,
    )

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
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

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    return context


def _patch_semantic_pose_recapture_captures(
    monkeypatch: pytest.MonkeyPatch,
    context: SimpleNamespace,
) -> None:
    def fake_capture_semantic_pose_robot_views(
        *,
        state: dict[str, object],
        scene_usd: Path,
        view_paths: dict[str, Path],
        width: int,
        height: int,
        render_settle_frames: int = 0,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
    ) -> dict[str, object]:
        del focus_object_id, focus_receptacle_id
        assert scene_usd == context.scene_usd
        assert width == 64
        assert height == 48
        assert render_settle_frames == 16
        semantic_pose = state["semantic_pose_state"]
        assert isinstance(semantic_pose, dict)
        assert semantic_pose["rendered_to_usd"] is False
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "scene_bounds": {
                "min": [-2.0, -3.0, 0.0],
                "max": [4.0, 5.0, 2.5],
                "size": [6.0, 8.0, 2.5],
                "center": [1.0, 1.0, 1.25],
            },
            "render_steps": 9,
            "render_settle_frames": render_settle_frames,
            "robot_view_uses_mounted_head_camera": False,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "applied",
                "applied_object_count": 1,
                "failed_object_count": 0,
                "rendered_to_usd": True,
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {
                    "fpv": {
                        "schema": "isaac_eye_target_camera_diagnostics_v1",
                        "status": "ready",
                        "camera_type": "eye_target_scene_camera",
                    }
                },
            },
        }

    def fake_capture_scene_camera_views(
        *,
        scene_usd: Path,
        camera_request: dict[str, object],
        output_dir: Path,
        width: int,
        height: int,
        simulation_app: object,
        semantic_pose_state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert scene_usd == context.scene_usd
        assert simulation_app == "unit-simulation-app"
        assert semantic_pose_state is not None
        assert camera_request["api_name"] == "roboclaws.camera_control.render_views"
        output_dir.mkdir(parents=True, exist_ok=True)
        views = []
        images: dict[str, str] = {}
        for item in camera_request["views"]:
            assert isinstance(item, dict)
            assert item["robot_view_role"] in {"fpv", "verify"}
            image_path = output_dir / f"{item['view_id']}.png"
            _write_nonblank_image(image_path)
            views.append({**item, "image_path": str(image_path), "shape": [height, width, 3]})
            images[str(item["view_id"])] = str(image_path)
        return {
            "camera_control_api": camera_request["api_name"],
            "color_profile": camera_request.get("color_profile"),
            "color_management": {
                "isaac_robot_view_fpv": {
                    "after": {"overexposed_fraction": 0.0},
                }
            },
            "views": views,
            "images": images,
            "render_steps": 6,
        }

    monkeypatch.setattr(
        runtime_capture,
        "capture_semantic_pose_robot_views",
        fake_capture_semantic_pose_robot_views,
    )
    monkeypatch.setattr(
        runtime_camera,
        "_capture_isaac_lab_scene_camera_views",
        fake_capture_scene_camera_views,
    )


def _init_real_worker_with_scene_usd(context: SimpleNamespace) -> None:
    init_args = runtime_cli.parse_args(
        [
            "--state-path",
            str(context.state_path),
            "init",
            "--run-dir",
            str(context.run_dir),
            "--runtime-mode",
            "real",
            "--include-robot",
            "--scene-usd-path",
            str(context.scene_usd),
        ]
    )
    runtime_initialization.init_state(init_args)


def _navigate_real_worker_to_receptacle(context: SimpleNamespace) -> None:
    nav_args = runtime_cli.parse_args(
        [
            "--state-path",
            str(context.state_path),
            "navigate_to_receptacle",
            "--receptacle-id",
            "sink_01",
        ]
    )
    nav_result = runtime_commands.navigate_to_receptacle(
        nav_args,
        runtime_commands.read_state(context.state_path),
    )
    assert nav_result["ok"] is True
    assert nav_result["robot_pose"]["pose_source"] == "roboclaws_shared_scene_frame_support_pose"


def _write_semantic_pose_robot_views(context: SimpleNamespace) -> dict[str, object]:
    result = runtime_commands.write_robot_views(
        runtime_cli.parse_args(
            [
                "--state-path",
                str(context.state_path),
                "robot_views",
                "--output-dir",
                str(context.run_dir / "robot_views"),
                "--label",
                "0001_semantic_pose",
                "--render-width",
                "64",
                "--render-height",
                "48",
                "--render-settle-frames",
                "16",
            ]
        ),
        runtime_commands.read_state(context.state_path),
    )
    assert isinstance(result, dict)
    return result


def _assert_semantic_pose_recapture_result(result: dict[str, object]) -> None:
    assert result["ok"] is True
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is True
    assert result["view_provenance"]["canonical_camera_control"] is False
    assert result["view_provenance"]["head_camera_equivalent"] is True
    assert result["camera_control_contract"]["status"] == (
        "robot_head_camera_equivalent_robot_view"
    )
    assert result["camera_control_contract"]["camera_model"] == "robot_head_camera_equivalent_v1"
    assert result["camera_control_contract"]["same_pose_api"] is False
    assert result["camera_control_contract"]["camera_control_api"] is None
    assert result["camera_control_contract"]["robot_pose"]["pose_source"] == (
        "roboclaws_shared_scene_frame_support_pose"
    )
    assert result["camera_control_contract"]["robot_pose"]["pose_request"]["resolver"] == (
        "roboclaws.cleanup_robot_pose.near_target_v1"
    )
    assert result["camera_diagnostics"]["schema"] == "isaac_robot_view_camera_diagnostics_v1"
    assert result["camera_diagnostics"]["views"]["fpv"]["camera_type"] == (
        "eye_target_scene_camera"
    )
    assert "isaac_lab_camera_rgb_head_camera_equivalent" in json.dumps(result["view_provenance"])


def _assert_semantic_pose_recapture_state(state: dict[str, object]) -> None:
    assert state["semantic_pose_state"]["rendered_to_usd"] is True
    assert state["robot_view_provenance"]["semantic_pose_state_refreshed"] is True
    assert state["robot_view_provenance"]["canonical_camera_control"] is False
    assert state["robot_view_provenance"]["head_camera_equivalent"] is True
    assert state["semantic_pose_view_capture"]["render_steps"] == 9
    assert state["semantic_pose_view_capture"]["render_settle_frames"] == 16
    assert state["scene_bounds"]["center"] == [1.0, 1.0, 1.25]
    assert state["semantic_pose_view_capture"]["scene_bounds"]["size"] == [6.0, 8.0, 2.5]
    assert state["semantic_pose_view_capture"]["canonical_camera_control"] is False
    assert state["semantic_pose_view_capture"]["head_camera_equivalent"] is True
    assert "canonical_robot_view_camera_control_capture" not in state
    assert state["semantic_pose_state"]["semantic_pose_view_capture"]["render_steps"] == 9
    assert state["semantic_pose_state"]["semantic_pose_view_capture"]["scene_bounds"]["center"] == [
        1.0,
        1.0,
        1.25,
    ]
    assert state["semantic_pose_state"]["semantic_pose_view_capture"]["render_settle_frames"] == 16
    robot_view_gap = next(
        item for item in state["mapping_gaps"] if item["area"] == "robot_view_variants"
    )
    assert robot_view_gap["source"] == "isaac_lab_camera_rgb_semantic_pose_robot_views"
    assert "recaptured from the loaded USD scene" in robot_view_gap["detail"]
    assert "static Phase B" not in robot_view_gap["detail"]
