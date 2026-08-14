from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[3]


def write_smoke_image(path: Path) -> None:
    image = Image.new("RGB", (64, 48), color=(20, 40, 60))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = ((x * 5) % 256, (y * 7) % 256, ((x + y) * 3) % 256)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 56, 40), outline=(220, 180, 40), width=3)
    image.save(path)


def write_low_detail_gray_image(path: Path) -> None:
    image = Image.new("RGB", (64, 48), color=(73, 73, 73))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 18, 40, 30), outline=(76, 76, 76), width=1)
    image.save(path)


def run_checker(
    tmp_path: Path,
    result: dict[str, object],
    *args: str,
    robot_views: dict[str, object] | None = None,
    prefix_logs: bool = False,
    state_text: str | None = None,
    robot_views_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result_path = tmp_path / "init_result.json"
    text = json.dumps(result)
    if prefix_logs:
        text = f"Isaac startup log line\n{text}\n"
    result_path.write_text(text, encoding="utf-8")
    robot_views_args: list[str] = []
    if robot_views is not None:
        robot_views_path = tmp_path / "robot_views_result.json"
        robot_views_path.write_text(
            robot_views_text if robot_views_text is not None else json.dumps(robot_views),
            encoding="utf-8",
        )
        robot_views_args = ["--robot-views-result", str(robot_views_path)]
    state_args: list[str] = []
    if state_text is not None:
        state_path = tmp_path / "state.json"
        state_path.write_text(state_text, encoding="utf-8")
        state_args = ["--state-path", str(state_path)]
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.backends.isaaclab.smoke_checker",
            "--init-result",
            str(result_path),
            *state_args,
            *robot_views_args,
            *args,
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def real_runtime_diagnostics(
    *,
    real_rendering_proven: bool = True,
    placeholder_visuals: bool = False,
) -> dict[str, object]:
    return {
        "runtime_mode": "real",
        "python_version": "3.12.3",
        "isaac_sim_version": "unit-isaacsim",
        "isaac_lab_version": "unit-isaaclab",
        "cuda_available": True,
        "gpu_name": "unit-gpu",
        "gpu_vram_mb": 16384,
        "renderer_mode": "isaac_lab_headless_rtx",
        "camera_resolution": [540, 360],
        "rendering": {
            "real_rendering_proven": real_rendering_proven,
            "placeholder_visuals": placeholder_visuals,
        },
    }


def test_isaac_runtime_smoke_checker_rejects_placeholder_real_mode(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "smoke.png"
    write_smoke_image(image_path)
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": real_runtime_diagnostics(
            real_rendering_proven=False,
            placeholder_visuals=True,
        ),
        "scene_load": {
            "status": "blocked_capability",
            "usd_stage_loaded": False,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-real-rendering",
        "--require-usd-stage-loaded",
        "--require-nonblank-image",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert summary["status"] == "failed"
    assert "real Isaac rendering is not proven" in summary["errors"]
    assert "USD stage loading is not proven" in summary["errors"]
    assert "smoke image appears blank" not in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_missing_runtime_diagnostics(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "smoke.png"
    write_smoke_image(image_path)
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": {
            "runtime_mode": "real",
            "rendering": {
                "real_rendering_proven": True,
                "placeholder_visuals": False,
            },
        },
        "scene_load": {
            "status": "loaded",
            "usd_stage_loaded": True,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(tmp_path, result, "--require-real-rendering")

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "missing runtime Python version" in summary["errors"]
    assert "missing Isaac Sim version" in summary["errors"]
    assert "missing Isaac Lab version" in summary["errors"]
    assert "runtime CUDA is not available" in summary["errors"]
    assert "missing runtime GPU name" in summary["errors"]
    assert "missing runtime GPU VRAM" in summary["errors"]
    assert "missing runtime renderer mode" in summary["errors"]
    assert "missing runtime camera resolution" in summary["errors"]


def test_isaac_runtime_smoke_checker_accepts_real_rendering_evidence(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "smoke.png"
    scene_usd = tmp_path / "example.usda"
    state_path = tmp_path / "state.json"
    write_smoke_image(image_path)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    robot_views = write_robot_views_result(tmp_path)
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": real_runtime_diagnostics(),
        "scene_load": {
            "status": "loaded",
            "usd_stage_loaded": True,
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "manual_editor_steps_required": False,
        },
        "scene_index_diagnostics": {
            "status": "indexed",
            "stage_prim_count": 6,
            "object_candidate_count": 1,
            "receptacle_candidate_count": 1,
        },
        "scene_binding_diagnostics": {
            "schema": "isaac_public_scene_bindings_v1",
            "status": "selected_bound",
            "source": "usd_stage_traversal",
            "selected_object_count": 1,
            "selected_target_receptacle_count": 1,
            "selected_object_bound_count": 1,
            "selected_target_receptacle_bound_count": 1,
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "public_id": "mug_01",
                    "usd_handle": "mug_01",
                    "usd_prim_path": "/World/Objects/mug_01",
                    "match_strategy": "exact_public_id",
                    "index_source": "usd_stage_traversal",
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "public_id": "sink_01",
                    "usd_handle": "sink_01",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "match_strategy": "exact_public_id",
                    "index_source": "usd_stage_traversal",
                }
            },
            "blockers": [],
            "private_manifest_exposed_to_agent": False,
        },
        "object_index": {"mug_01": {"usd_prim_path": "/World/Objects/mug_01"}},
        "receptacle_index": {"sink_01": {"usd_prim_path": "/World/Receptacles/sink_01"}},
        "segmentation": available_segmentation_diagnostics(),
        "scene_usd": str(scene_usd),
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }
    state_path.write_text(
        json.dumps(
            {
                "backend": "isaaclab_subprocess",
                "runtime": {"runtime_mode": "real"},
            }
        ),
        encoding="utf-8",
    )

    completed = run_checker(
        tmp_path,
        result,
        "--state-path",
        str(state_path),
        "--require-real-rendering",
        "--require-usd-stage-loaded",
        "--require-local-scene-usd",
        "--require-usd-scene-index",
        "--require-selected-usd-bindings",
        "--require-robot-view-images",
        "--require-nonblank-image",
        "--require-segmentation-evidence",
        robot_views=robot_views,
        prefix_logs=True,
    )

    assert completed.returncode == 0
    summary = json.loads(completed.stdout)
    assert summary["status"] == "passed"
    assert summary["errors"] == []
    assert summary["scene_index_status"] == "indexed"
    assert summary["scene_binding_status"] == "selected_bound"
    assert summary["robot_view_status"] == "present"


def test_isaac_runtime_smoke_checker_keeps_init_result_stdout_json_tolerance(
    tmp_path: Path,
) -> None:
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": {"runtime_mode": "real"},
    }

    completed = run_checker(tmp_path, result, prefix_logs=True)

    assert completed.returncode == 0
    summary = json.loads(completed.stdout)
    assert summary["status"] == "passed"


def test_isaac_runtime_smoke_checker_rejects_prefixed_state_sidecar_json(
    tmp_path: Path,
) -> None:
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": {"runtime_mode": "real"},
    }

    completed = run_checker(
        tmp_path,
        result,
        state_text='Isaac startup log line\n{"backend": "isaaclab_subprocess"}\n',
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert summary["status"] == "failed"
    assert "state runtime_mode does not match init result" in summary["errors"]


def test_isaac_runtime_smoke_checker_recovers_prefixed_robot_views_sidecar_json(
    tmp_path: Path,
) -> None:
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": {"runtime_mode": "real"},
    }
    robot_views = write_robot_views_result(tmp_path)

    completed = run_checker(
        tmp_path,
        result,
        "--require-robot-view-images",
        robot_views=robot_views,
        robot_views_text="Isaac startup log line\n" + json.dumps(robot_views) + "\n",
    )

    assert completed.returncode == 0
    summary = json.loads(completed.stdout)
    assert summary["robot_view_status"] == "present"
    assert summary["status"] == "passed"


def test_isaac_runtime_smoke_checker_rejects_generated_usd_for_local_scene_gate(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "smoke.png"
    scene_usd = tmp_path / "roboclaws_phase_a_smoke_scene.usda"
    write_smoke_image(image_path)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": real_runtime_diagnostics(),
        "scene_load": {
            "status": "loaded",
            "usd_stage_loaded": True,
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "generated_runtime_smoke_usd",
            "manual_editor_steps_required": False,
        },
        "scene_usd": str(scene_usd),
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(tmp_path, result, "--require-local-scene-usd")

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "loaded scene USD was not caller supplied local_scene_usd" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_loaded_stage_without_scene_usd(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "smoke.png"
    write_smoke_image(image_path)
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": real_runtime_diagnostics(),
        "scene_load": {
            "status": "loaded",
            "usd_stage_loaded": True,
            "loaded_asset_kind": "local_scene_usd",
            "manual_editor_steps_required": False,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(tmp_path, result, "--require-usd-stage-loaded")

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "missing loaded scene USD path" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_manual_editor_scene_load(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "smoke.png"
    scene_usd = tmp_path / "manual.usda"
    write_smoke_image(image_path)
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    result = {
        "ok": True,
        "backend": "isaaclab_subprocess",
        "runtime": real_runtime_diagnostics(),
        "scene_load": {
            "status": "loaded",
            "usd_stage_loaded": True,
            "scene_usd": str(scene_usd),
            "loaded_asset_kind": "local_scene_usd",
            "manual_editor_steps_required": True,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(tmp_path, result, "--require-usd-stage-loaded")

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "USD stage loading still requires manual editor steps" in summary["errors"]


def write_robot_views_result(tmp_path: Path) -> dict[str, object]:
    view_dir = tmp_path / "robot_views"
    view_dir.mkdir(parents=True, exist_ok=True)
    views = {}
    for key in ("fpv", "chase", "topdown", "verify"):
        path = view_dir / f"runtime_smoke.{key}.png"
        write_smoke_image(path)
        views[key] = str(path)
    return {
        "ok": True,
        "view_variant": "isaaclab-fpv-topdown-chase-verify",
        "view_provenance": {
            "fpv": "isaac_lab_camera_rgb_static_robot_views:fpv",
            "chase": "isaac_lab_camera_rgb_static_robot_views:chase",
            "topdown": "isaac_lab_camera_rgb_static_robot_views:topdown",
            "verify": "isaac_lab_camera_rgb_static_robot_views:verify",
        },
        "views": views,
    }


def available_segmentation_diagnostics() -> dict[str, object]:
    return {
        "schema": "isaac_segmentation_diagnostics_v1",
        "status": "available",
        "available": True,
        "source": "isaac_lab_camera",
        "capture_method": "isaac_lab_camera_segmentation",
        "requested_data_types": [
            "semantic_segmentation",
            "instance_segmentation_fast",
            "instance_id_segmentation_fast",
        ],
        "output_data_types": ["instance_id_segmentation_fast"],
        "tensor_output_available": True,
        "candidate_overlay_status": "available",
        "candidate_bbox_count": 1,
        "selected_usd_prim_match_count": 1,
        "agent_facing": False,
        "no_simulator_label_fallback": True,
        "candidate_bboxes": [
            {
                "view": "fpv",
                "data_type": "instance_id_segmentation_fast",
                "label_id": 3,
                "label": "/World/Objects/mug_01",
                "usd_prim_path": "/World/Objects/mug_01",
                "bbox_xyxy": [8, 8, 32, 36],
                "pixel_count": 144,
                "image_size": [64, 48],
            }
        ],
    }
