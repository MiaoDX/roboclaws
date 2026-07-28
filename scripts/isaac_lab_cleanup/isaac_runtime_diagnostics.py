from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from scripts.isaac_lab_cleanup.isaac_render_diagnostics import (
    native_render_diagnostics_unavailable,
)


def module_version(module_name: str) -> str | None:
    try:
        module = __import__(module_name)
    except Exception:
        return None
    version = str(getattr(module, "__version__", "unknown"))
    if module_name == "isaacsim" and version == "unknown":
        return _isaac_sim_version_file("docs/py/VERSION") or version
    return version


def isaac_sim_build_version() -> str | None:
    return _isaac_sim_version_file("VERSION")


def _isaac_sim_version_file(relative_path: str) -> str | None:
    root = Path(os.environ.get("ISAACSIM_ROOT_PATH", "/isaac-sim"))
    path = root / relative_path
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def runtime_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
    default_width: int,
    default_height: int,
    primitive_provenance: str,
    real_smoke_renderer_mode: str,
    real_smoke_capture_method: str,
) -> dict[str, Any]:
    isaac_lab_version = real_smoke.get("isaac_lab_version") if real_smoke else None
    isaac_sim_version = real_smoke.get("isaac_sim_version") if real_smoke else None
    isaac_sim_build = real_smoke.get("isaac_sim_build") if real_smoke else None
    if runtime_mode == "real":
        isaac_lab_version = isaac_lab_version or module_version("isaaclab")
        isaac_sim_version = isaac_sim_version or module_version("isaacsim")
        isaac_sim_build = isaac_sim_build or isaac_sim_build_version()
    cuda_available = False
    gpu_name = ""
    gpu_vram_mb = None
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            gpu_name = str(torch.cuda.get_device_name(0))
            props = torch.cuda.get_device_properties(0)
            gpu_vram_mb = int(props.total_memory / (1024 * 1024))
    except Exception:
        pass
    rendering = rendering_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        real_smoke_renderer_mode=real_smoke_renderer_mode,
        real_smoke_capture_method=real_smoke_capture_method,
    )
    camera_resolution = (
        list(real_smoke["camera_resolution"])
        if real_smoke and real_smoke.get("camera_resolution")
        else [default_width, default_height]
    )
    return {
        "runtime_mode": runtime_mode,
        "python_version": platform.python_version(),
        "isaac_sim_version": isaac_sim_version,
        "isaac_sim_build": isaac_sim_build,
        "isaac_lab_version": isaac_lab_version,
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
        "gpu_vram_mb": gpu_vram_mb,
        "renderer_mode": rendering["renderer_mode"],
        "rendering": rendering,
        "visual_artifact_provenance": rendering["visual_artifact_provenance"],
        "camera_resolution": camera_resolution,
        "physical_robot": False,
        "planner_backed": False,
        "primitive_provenance": primitive_provenance,
    }


def rendering_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
    real_smoke_renderer_mode: str,
    real_smoke_capture_method: str,
) -> dict[str, Any]:
    if real_smoke is not None:
        native_render_diagnostics = _dict(real_smoke.get("native_render_diagnostics"))
        return {
            "status": "real_rendering_proven",
            "renderer_mode": str(real_smoke.get("renderer_mode") or real_smoke_renderer_mode),
            "real_rendering_proven": True,
            "placeholder_visuals": False,
            "visual_artifact_provenance": real_smoke_capture_method,
            "capture_method": str(real_smoke.get("capture_method") or real_smoke_capture_method),
            "render_steps": int(real_smoke.get("render_steps") or 0),
            "image_path": str(real_smoke["image_path"]),
            "native_render_diagnostics": native_render_diagnostics
            or native_render_diagnostics_unavailable(
                runtime_mode="real",
                reason="real runtime smoke did not return native render diagnostics",
            ),
            "reason": (
                "The worker launched Isaac Lab, loaded a generated Phase A USD "
                "stage, and saved an RGB camera frame from the Isaac renderer."
            ),
        }
    if runtime_mode == "real":
        return {
            "status": "runtime_import_only",
            "renderer_mode": "isaac_runtime_unvalidated",
            "real_rendering_proven": False,
            "placeholder_visuals": True,
            "visual_artifact_provenance": "placeholder_protocol_image",
            "native_render_diagnostics": native_render_diagnostics_unavailable(
                runtime_mode="real",
                reason="real Isaac app launch and camera capture have not produced diagnostics",
            ),
            "reason": (
                "The worker imports Isaac Lab in real mode, but real Isaac app "
                "launch, scene loading, and camera capture are not implemented "
                "in this semantic-pose scaffold yet."
            ),
        }
    return {
        "status": "fake_protocol",
        "renderer_mode": "fake_isaac_protocol",
        "real_rendering_proven": False,
        "placeholder_visuals": True,
        "visual_artifact_provenance": "fake_protocol_placeholder_image",
        "native_render_diagnostics": native_render_diagnostics_unavailable(
            runtime_mode="fake",
            reason="CI fake mode does not launch Isaac Kit or mutate renderer settings",
        ),
        "reason": "CI-safe fake mode writes deterministic placeholder images only.",
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
