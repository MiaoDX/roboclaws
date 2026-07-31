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


def test_isaac_runtime_smoke_checker_rejects_blocked_segmentation(
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
        },
        "segmentation": {
            "schema": "isaac_segmentation_diagnostics_v1",
            "status": "blocked_capability",
            "available": False,
            "tensor_output_available": False,
            "candidate_bbox_count": 0,
            "selected_usd_prim_match_count": 0,
            "candidate_overlay_status": "blocked_capability",
            "agent_facing": False,
            "no_simulator_label_fallback": True,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-segmentation-evidence",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "Isaac segmentation evidence is not available" in summary["errors"]
    assert "Isaac segmentation tensors were not captured" in summary["errors"]
    assert "Isaac segmentation produced no bbox candidates" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_missing_usd_scene_index(
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
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-usd-scene-index",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "missing USD scene index diagnostics" in summary["errors"]
    assert "USD scene index has no object candidates" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_missing_selected_usd_bindings(
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
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-selected-usd-bindings",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "missing selected USD binding diagnostics" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_partial_selected_usd_bindings(
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
        "scene_binding_diagnostics": {
            "schema": "isaac_public_scene_bindings_v1",
            "status": "partial",
            "source": "usd_stage_traversal",
            "selected_object_count": 1,
            "selected_target_receptacle_count": 1,
            "selected_object_bound_count": 1,
            "selected_target_receptacle_bound_count": 0,
            "blockers": ["Selected target receptacle has no USD binding: sink_01"],
            "private_manifest_exposed_to_agent": False,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-selected-usd-bindings",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "selected cleanup handles are not fully bound to USD prims" in summary["errors"]
    assert "not all selected target receptacles have USD prim bindings" in summary["errors"]
    assert "selected USD binding diagnostics still report blockers" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_missing_selected_binding_rows(
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
        "scene_binding_diagnostics": {
            "schema": "isaac_public_scene_bindings_v1",
            "status": "selected_bound",
            "source": "usd_stage_traversal",
            "selected_object_count": 1,
            "selected_target_receptacle_count": 1,
            "selected_object_bound_count": 1,
            "selected_target_receptacle_bound_count": 1,
            "blockers": [],
            "private_manifest_exposed_to_agent": False,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-selected-usd-bindings",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "selected object binding rows are missing" in summary["errors"]
    assert "selected target receptacle binding rows are missing" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_invalid_selected_binding_row(
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
                    "usd_handle": "",
                    "usd_prim_path": "",
                    "index_source": "scenario_fixture",
                    "private_manifest": {"target": "sink_01"},
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "unresolved",
                    "usd_handle": "sink_01",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "index_source": "usd_stage_traversal",
                }
            },
            "blockers": [],
            "private_manifest_exposed_to_agent": False,
        },
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-selected-usd-bindings",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "selected object binding row has no USD handle: mug_01" in summary["errors"]
    assert "selected object binding row has no USD prim path: mug_01" in summary["errors"]
    assert (
        "selected object binding row is not from USD stage traversal: mug_01" in (summary["errors"])
    )
    assert "selected object binding row has no match strategy: mug_01" in summary["errors"]
    assert "selected object binding row exposes private manifest: mug_01" in (summary["errors"])
    assert "selected target receptacle binding row is not bound: sink_01" in (summary["errors"])


def test_isaac_runtime_smoke_checker_rejects_selected_binding_index_mismatch(
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
                    "usd_handle": "mug_01",
                    "usd_prim_path": "/World/Objects/mug_01",
                    "match_strategy": "exact_public_id",
                    "index_source": "usd_stage_traversal",
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_handle": "sink_01",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "match_strategy": "exact_public_id",
                    "index_source": "usd_stage_traversal",
                }
            },
            "blockers": [],
            "private_manifest_exposed_to_agent": False,
        },
        "object_index": {"mug_01": {"usd_prim_path": "/World/Objects/other_mug"}},
        "receptacle_index": {},
        "artifacts": {"runtime_smoke_image": str(image_path)},
    }

    completed = run_checker(
        tmp_path,
        result,
        "--require-selected-usd-bindings",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert (
        "selected object binding row USD prim path does not match object index: mug_01"
        in summary["errors"]
    )
    assert (
        "selected target receptacle binding row USD handle is missing from receptacle index: "
        "sink_01"
    ) in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_missing_robot_views(
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

    completed = run_checker(
        tmp_path,
        result,
        "--require-real-rendering",
        "--require-robot-view-images",
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "missing robot views result" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_placeholder_robot_views(
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
    robot_views = write_robot_views_result(tmp_path)
    robot_views["view_provenance"] = {"fpv": "fake_protocol_placeholder_image"}

    completed = run_checker(
        tmp_path,
        result,
        "--require-real-rendering",
        "--require-robot-view-images",
        robot_views=robot_views,
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "robot view provenance still reports placeholder visuals" in summary["errors"]


def test_isaac_runtime_smoke_checker_rejects_low_detail_gray_robot_views(
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
    robot_views = write_robot_views_result(tmp_path)
    write_low_detail_gray_image(Path(str(robot_views["views"]["fpv"])))

    completed = run_checker(
        tmp_path,
        result,
        "--require-real-rendering",
        "--require-robot-view-images",
        robot_views=robot_views,
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert "fpv robot view has too little visual detail" in summary["errors"]
    assert "fpv robot view has too few distinct colors" in summary["errors"]


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
