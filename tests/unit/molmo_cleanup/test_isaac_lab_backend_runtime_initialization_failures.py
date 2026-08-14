from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import isaac_runtime_smoke_usd
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


def test_isaac_worker_read_state_rejects_missing_state_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing_state.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"Isaac worker state source is missing: .*missing_state\.json",
    ):
        runtime_commands.read_state(missing)


def test_isaac_worker_read_state_rejects_malformed_state_source(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Isaac worker state source must contain valid JSON object: .*state\.json",
    ):
        runtime_commands.read_state(state_path)


def test_isaac_worker_read_state_rejects_non_object_state_source(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("[]", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Isaac worker state source must contain a JSON object: .*state\.json",
    ):
        runtime_commands.read_state(state_path)


def test_isaac_runtime_smoke_accepts_official_blocks_generated_scene(
    tmp_path: Path,
) -> None:
    args = runtime_cli.parse_args(
        [
            "--state-path",
            str(tmp_path / "state.json"),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "fake",
            "--generated-scene-kind",
            "isaac_official_blocks",
        ]
    )

    assert args.generated_scene_kind == "isaac_official_blocks"
    assert (
        isaac_runtime_smoke_usd.generated_scene_filename(args.generated_scene_kind)
        == "roboclaws_isaac_official_blocks_scene.usda"
    )


def test_isaac_lab_real_worker_views_fallback_when_semantic_pose_rerender_fails(
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

    def fail_capture_semantic_pose_robot_views(**_: object) -> dict[str, object]:
        raise RuntimeError("unit rerender failure")

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        fake_real_runtime_smoke,
    )
    monkeypatch.setattr(
        runtime_capture,
        "capture_semantic_pose_robot_views",
        fail_capture_semantic_pose_robot_views,
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
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is False
    assert "isaac_lab_camera_rgb_static_robot_views" in json.dumps(result["view_provenance"])
    state = runtime_commands.read_state(state_path)
    assert state["semantic_pose_state"]["rendered_to_usd"] is False
    assert any(
        item["area"] == "semantic_pose_robot_view_rerender"
        and item["status"] == "blocked_capability"
        and "unit rerender failure" in item["detail"]
        for item in state["mapping_gaps"]
    )


def test_isaac_lab_real_worker_views_do_not_claim_refresh_without_usd_pose_application(
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
            "render_steps": 7,
            "robot_view_uses_mounted_head_camera": False,
            "semantic_pose_stage_application": {
                "schema": "isaac_semantic_pose_stage_application_v1",
                "status": "blocked",
                "applied_object_count": 0,
                "failed_object_count": 1,
                "rendered_to_usd": False,
                "failed_objects": [{"object_id": "mug_01", "reason": "missing_object_prim"}],
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
    assert result["view_provenance"]["semantic_pose_state_refreshed"] is False
    assert "isaac_lab_camera_rgb_static_robot_views" in json.dumps(result["view_provenance"])
    state = runtime_commands.read_state(state_path)
    assert state["semantic_pose_state"]["rendered_to_usd"] is False
    assert any(
        item["area"] == "semantic_pose_robot_view_rerender"
        and item["status"] == "blocked_capability"
        and item["semantic_pose_stage_application"]["rendered_to_usd"] is False
        for item in state["mapping_gaps"]
    )


def test_isaac_lab_real_init_fails_without_renderer_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"

    def fail_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        raise RuntimeError("camera capture failed")

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        fail_real_runtime_smoke,
    )
    args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "real",
        ]
    )

    with pytest.raises(RuntimeError, match="Real Isaac runtime smoke failed"):
        runtime_initialization.init_state(args)
    assert state_path.exists() is False


def test_isaac_lab_real_init_does_not_persist_missing_smoke_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    missing_image = tmp_path / "run" / "missing.png"

    def missing_image_real_runtime_smoke(
        args: object,
        scenario: object,
    ) -> dict[str, object]:
        del args, scenario
        return {
            "image_path": str(missing_image),
            "scene_usd": str(tmp_path / "run" / "scene.usda"),
            "loaded_asset_kind": "generated_runtime_smoke_usd",
            "requested_scene_source": "procthor-10k-val",
            "requested_scene_index": 0,
            "renderer_mode": "isaac_lab_headless_rtx",
            "capture_method": "isaac_lab_camera_rgb",
            "camera_resolution": [540, 360],
            "stage_prim_count": 6,
            "render_steps": 3,
        }

    monkeypatch.setattr(
        runtime_capture,
        "real_runtime_smoke",
        missing_image_real_runtime_smoke,
    )
    args = runtime_cli.parse_args(
        [
            "--state-path",
            str(state_path),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "real",
        ]
    )

    with pytest.raises(RuntimeError, match="real Isaac smoke image is missing"):
        runtime_initialization.init_state(args)
    assert state_path.exists() is False
