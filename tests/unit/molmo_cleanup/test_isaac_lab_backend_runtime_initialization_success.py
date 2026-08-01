from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import runtime as runtime_cli
from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_lifecycle as runtime_lifecycle
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
)
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _unit_isaac_object_index,
    _unit_isaac_receptacle_index,
    _write_nonblank_image,
    _write_robot_view_images,
)


def test_isaac_worker_robot_views_accept_camera_offsets(tmp_path: Path) -> None:
    args = runtime_cli.parse_args(
        [
            "--state-path",
            str(tmp_path / "state.json"),
            "robot_views",
            "--output-dir",
            str(tmp_path / "robot_views"),
            "--label",
            "0001_adjusted",
            "--camera-yaw-offset-deg",
            "12.5",
            "--camera-pitch-offset-deg",
            "-10.0",
        ]
    )

    assert args.camera_yaw_offset_deg == pytest.approx(12.5)
    assert args.camera_pitch_offset_deg == pytest.approx(-10.0)


def test_isaac_worker_hard_exits_after_deferred_app_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_codes: list[int] = []

    def fake_exit(code: int) -> None:
        exit_codes.append(code)
        raise SystemExit(code)

    class BlockingClose:
        def close(self, **_: object) -> None:  # pragma: no cover - should not be called.
            raise AssertionError("deferred SimulationApp close should not run on success")

    monkeypatch.setattr(runtime_cli.os, "_exit", fake_exit)
    runtime_lifecycle.DEFERRED_SIMULATION_APP[0] = BlockingClose()

    with pytest.raises(SystemExit) as exc:
        runtime_cli._finish_command({"ok": True, "tool": "robot_views"})

    assert exc.value.code == 0
    assert exit_codes == [0]
    assert '"tool": "robot_views"' in capsys.readouterr().out
    assert runtime_lifecycle.DEFERRED_SIMULATION_APP[0] is not None
    runtime_lifecycle.DEFERRED_SIMULATION_APP[0] = None


def test_isaac_lab_real_init_uses_phase_a_smoke_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
    scene_usd = run_dir / "roboclaws_phase_a_smoke_scene.usda"
    _write_nonblank_image(image_path)
    scene_usd.parent.mkdir(parents=True, exist_ok=True)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")

    def fake_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del scenario
        assert getattr(args, "runtime_mode") == "real"
        assert getattr(args, "scene_usd_path") == scene_usd
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
            "render_steps": 3,
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
            "segmentation": {
                "schema": "isaac_segmentation_diagnostics_v1",
                "source": "isaac_lab_camera",
                "capture_method": "isaac_lab_camera_segmentation",
                "requested_data_types": [
                    "semantic_segmentation",
                    "instance_segmentation_fast",
                    "instance_id_segmentation_fast",
                ],
                "output_data_types": ["instance_id_segmentation_fast"],
                "tensor_output_available": True,
                "candidate_bbox_count": 1,
                "candidate_bboxes": [
                    {
                        "view": "fpv",
                        "data_type": "instance_id_segmentation_fast",
                        "label_id": 3,
                        "label": "/World/Objects/mug_01",
                        "usd_prim_path": "/World/Objects/mug_01",
                        "bbox_xyxy": [8, 8, 32, 36],
                        "pixel_count": 144,
                        "image_size": [540, 360],
                    }
                ],
                "no_simulator_label_fallback": True,
            },
        }

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )

    args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(run_dir),
            "--runtime-mode",
            "real",
            "--generated-mess-count",
            "1",
            "--scene-usd-path",
            str(scene_usd),
        ]
    )
    result = runtime_initialization.init_state(args)

    assert result["ok"] is True
    assert result["runtime"]["runtime_mode"] == "real"
    assert result["runtime"]["rendering"]["status"] == "real_rendering_proven"
    assert result["runtime"]["rendering"]["real_rendering_proven"] is True
    assert result["runtime"]["rendering"]["placeholder_visuals"] is False
    assert result["runtime"]["visual_artifact_provenance"] == "isaac_lab_camera_rgb"
    assert result["scene_usd"] == str(scene_usd)
    assert result["scene_load"]["status"] == "loaded"
    assert result["scene_load"]["usd_stage_loaded"] is True
    assert result["scene_load"]["loaded_asset_kind"] == "local_scene_usd"
    assert result["artifacts"]["runtime_smoke_image"] == str(image_path)
    assert result["artifacts"]["robot_view_images"] == robot_view_images
    assert result["scene_index_diagnostics"]["status"] == "indexed"
    assert result["scene_index_diagnostics"]["object_candidate_count"] == 1
    assert result["object_index"]["mug_01"]["usd_prim_path"] == "/World/Objects/mug_01"
    assert result["receptacle_index"]["sink_01"]["usd_prim_path"] == ("/World/Receptacles/sink_01")
    assert any(
        item["area"] == "camera_capture" and item["status"] == "real_rendering_proven"
        for item in result["mapping_gaps"]
    )
    assert any(
        item["area"] == "local_usd_scene_loading" and item["status"] == "loaded"
        for item in result["mapping_gaps"]
    )
    assert any(
        item["area"] == "robot_view_variants" and item["status"] == "real_rendering_proven"
        for item in result["mapping_gaps"]
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["runtime"]["rendering"]["status"] == "real_rendering_proven"
    assert state["scene_load"]["usd_stage_loaded"] is True
    assert state["real_runtime_smoke"]["scene_usd"] == str(scene_usd)
    assert state["robot_view_images"] == robot_view_images
    assert state["scene_index_diagnostics"]["status"] == "indexed"
    assert state["scene_binding_diagnostics"]["status"] == "selected_bound"
    assert state["scene_binding_diagnostics"]["selected_object_bound_count"] == 1
    assert state["scene_binding_diagnostics"]["selected_target_receptacle_bound_count"] == 1
    assert state["segmentation"]["status"] == "available"
    assert state["segmentation"]["candidate_bbox_count"] == 1
    assert state["segmentation"]["selected_usd_prim_match_count"] == 1
    assert state["segmentation"]["agent_facing"] is False
    assert state["segmentation"]["no_simulator_label_fallback"] is True


def test_isaac_lab_real_worker_views_reuse_real_smoke_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    state_path = tmp_path / "state.json"
    image_path = run_dir / "isaac_runtime_smoke.png"
    robot_view_images = _write_robot_view_images(run_dir)
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
            "robot_view_capture_method": "isaac_lab_camera_rgb_static_robot_views",
            "robot_view_images": robot_view_images,
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
            "--include-robot",
        ]
    )
    runtime_initialization.init_state(init_args)
    view_args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "robot_views",
            "--output-dir",
            str(run_dir / "robot_views"),
            "--label",
            "runtime smoke",
            "--render-width",
            "64",
            "--render-height",
            "48",
        ]
    )
    result = runtime_commands.write_robot_views(
        view_args,
        runtime_commands.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_variant"] == ISAACLAB_ROBOT_VIEW_VARIANT
    assert "placeholder" not in json.dumps(result["view_provenance"])
    assert set(result["views"]) == {"fpv", "chase", "topdown", "verify"}
    assert result["shapes"]["fpv"] == [48, 64, 3]
    for path in result["views"].values():
        assert Path(path).is_file()


def test_isaac_lab_real_worker_views_accept_robot_pose_only_rerender(
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
                "object_candidate_count": 0,
                "receptacle_candidate_count": 1,
                "blockers": [],
            },
            "object_index": {},
            "receptacle_index": _unit_isaac_receptacle_index(),
        }

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
        del state, scene_usd, width, height, render_settle_frames
        del focus_object_id, focus_receptacle_id
        for path in view_paths.values():
            _write_nonblank_image(path)
        return {
            "robot_view_images": {key: str(path) for key, path in view_paths.items()},
            "render_steps": 7,
            "robot_view_uses_mounted_head_camera": False,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "blocked",
                "applied_object_count": 0,
                "failed_object_count": 0,
                "rendered_to_usd": False,
            },
            "robot_pose_stage_application": {
                "schema": "isaac_robot_head_camera_pose_application_v1",
                "status": "applied",
                "robot_prim_path": "/World/robot_0",
                "position": [1.0, 2.0, 0.0],
                "position_source": "semantic_pose_state.robot_pose",
            },
            "camera_diagnostics": {
                "schema": "isaac_robot_view_camera_diagnostics_v1",
                "views": {},
            },
        }

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
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
    runtime_initialization.init_state(init_args)
    result = runtime_commands.write_robot_views(
        runtime_cli.parse_args(
            [
                "--state-path",
                str(state_path),
                "robot_views",
                "--output-dir",
                str(run_dir / "robot_views"),
                "--label",
                "0001_robot_pose_only",
                "--render-width",
                "64",
                "--render-height",
                "48",
            ]
        ),
        runtime_commands.read_state(state_path),
    )

    assert result["ok"] is True
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is True
    assert result["camera_control_contract"]["robot_pose"]["pose_source"]
    state = runtime_commands.read_state(state_path)
    assert state["semantic_pose_view_capture"]["rendered_to_usd"] is True
    assert state["semantic_pose_view_capture"]["robot_pose_stage_application"]["status"] == (
        "applied"
    )
    assert state["semantic_pose_state"]["robot_pose_rendered_to_usd"] is True
    assert not any(
        item.get("area") == "semantic_pose_robot_view_rerender" for item in state["mapping_gaps"]
    )
