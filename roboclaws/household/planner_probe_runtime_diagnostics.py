from __future__ import annotations

import faulthandler
import importlib
import importlib.metadata
import importlib.util
import os
import platform
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

CUROBO_EXTENSION_NAMES = (
    "geom_cu",
    "kinematics_fused_cu",
    "tensor_step_cu",
    "lbfgs_step_cu",
    "line_search_cu",
)

_MODULE_STARTED_AT = time.monotonic()
_WARP_COMPATIBILITY_ADAPTER: dict[str, Any] = {"applied": False}


def runtime_diagnostics(
    args: Any,
    *,
    curobo_memory_profile_request: dict[str, Any],
) -> dict[str, Any]:
    modules = {}
    for module_name in (
        "molmo_spaces",
        "mujoco",
        "jax",
        "jaxlib",
        "curobo",
        "warp",
        "mujoco_warp",
        "mlspaces_tests",
    ):
        spec = importlib.util.find_spec(module_name)
        package_name = module_name.replace("_", "-")
        modules[module_name] = {
            "available": spec is not None,
            "version": _package_version(package_name),
        }
    renderer_device_id = renderer_device_id_for_probe(
        probe_mode=args.probe_mode,
        renderer_device_id=args.renderer_device_id,
    )
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "embodiment": args.embodiment,
        "probe_mode": args.probe_mode,
        "modules": modules,
        "faulthandler_enabled": faulthandler.is_enabled(),
        "python_faulthandler_env": os.environ.get("PYTHONFAULTHANDLER", ""),
        "mujoco_gl_env": os.environ.get("MUJOCO_GL", ""),
        "pyopengl_platform_env": os.environ.get("PYOPENGL_PLATFORM", ""),
        "cuda_home_env": os.environ.get("CUDA_HOME", ""),
        "torch_cuda_arch_list_env": os.environ.get("TORCH_CUDA_ARCH_LIST", ""),
        "cuda_visible_devices_env": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        "pytorch_cuda_alloc_conf_env": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""),
        "torch_extensions_dir_env": os.environ.get("TORCH_EXTENSIONS_DIR", ""),
        "torch": torch_diagnostics(),
        "cuda_memory": cuda_memory_diagnostics(),
        "curobo_extension_cache": curobo_extension_cache_diagnostics(),
        "warp_compatibility": warp_compatibility_diagnostics(),
        "renderer_adapter_enabled": renderer_device_id is not None,
        "renderer_device_id": renderer_device_id,
        "curobo_memory_profile_request": curobo_memory_profile_request,
    }


def _package_version(package_name: str) -> str | None:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def torch_diagnostics() -> dict[str, Any]:
    if importlib.util.find_spec("torch") is None:
        return {"available": False}
    try:
        import torch
        from torch.utils import cpp_extension

        return {
            "available": True,
            "version": getattr(torch, "__version__", None),
            "cuda_version": getattr(torch.version, "cuda", None),
            "cuda_available": bool(torch.cuda.is_available()),
            "cpp_extension_cuda_home": cpp_extension.CUDA_HOME,
        }
    except BaseException as exc:  # noqa: BLE001 - diagnostics should not fail the probe.
        return {
            "available": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def cuda_memory_diagnostics() -> dict[str, Any]:
    if importlib.util.find_spec("torch") is None:
        return {
            "available": False,
            "torch_available": False,
            "cuda_visible_devices_env": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
            "pytorch_cuda_alloc_conf_env": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""),
        }
    try:
        import torch

        return cuda_memory_diagnostics_from_torch(torch)
    except BaseException as exc:  # noqa: BLE001 - diagnostics should not fail the probe.
        return {
            "available": False,
            "torch_available": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cuda_visible_devices_env": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
            "pytorch_cuda_alloc_conf_env": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""),
        }


def cuda_memory_diagnostics_from_torch(torch_module: Any) -> dict[str, Any]:
    cuda = getattr(torch_module, "cuda", None)
    available = bool(cuda and cuda.is_available())
    diagnostics: dict[str, Any] = {
        "available": available,
        "torch_available": True,
        "cuda_visible_devices_env": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        "pytorch_cuda_alloc_conf_env": os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""),
        "device_count": _cuda_device_count(cuda),
    }
    if not available:
        return diagnostics
    diagnostics["current_device_index"] = _cuda_current_device(cuda)
    diagnostics["devices"] = [
        _cuda_device_entry(cuda, index) for index in range(int(diagnostics["device_count"] or 0))
    ]
    diagnostics["current_snapshot"] = cuda_memory_snapshot_from_torch(
        torch_module,
        "runtime_diagnostics",
    )
    return diagnostics


def cuda_memory_snapshot(stage: str, *, started_at: float | None = None) -> dict[str, Any]:
    if importlib.util.find_spec("torch") is None:
        return {
            "stage": stage,
            "elapsed_s": _elapsed_seconds(started_at),
            "available": False,
            "torch_available": False,
        }
    try:
        import torch

        return cuda_memory_snapshot_from_torch(torch, stage, started_at=started_at)
    except BaseException as exc:  # noqa: BLE001 - diagnostics should not fail the probe.
        return {
            "stage": stage,
            "elapsed_s": _elapsed_seconds(started_at),
            "available": False,
            "torch_available": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def cuda_memory_snapshot_from_torch(
    torch_module: Any,
    stage: str,
    *,
    started_at: float | None = None,
) -> dict[str, Any]:
    cuda = getattr(torch_module, "cuda", None)
    snapshot: dict[str, Any] = {
        "stage": stage,
        "elapsed_s": _elapsed_seconds(started_at),
        "torch_available": True,
        "available": bool(cuda and cuda.is_available()),
    }
    if not snapshot["available"]:
        return snapshot
    device_index = _cuda_current_device(cuda)
    snapshot["device_index"] = device_index
    device_entry = _cuda_device_entry(cuda, device_index)
    snapshot["device_name"] = device_entry.get("name")
    snapshot["device_total_memory_bytes"] = device_entry.get("total_memory_bytes")
    free_bytes, total_bytes = _cuda_mem_get_info(cuda, device_index)
    if free_bytes is not None:
        snapshot["free_bytes"] = free_bytes
    if total_bytes is not None:
        snapshot["total_bytes"] = total_bytes
        if free_bytes is not None:
            snapshot["used_bytes"] = total_bytes - free_bytes
            snapshot["free_fraction"] = round(free_bytes / total_bytes, 6) if total_bytes else None
    snapshot["torch_allocated_bytes"] = _cuda_memory_metric(
        cuda,
        "memory_allocated",
        device_index,
    )
    snapshot["torch_reserved_bytes"] = _cuda_memory_metric(
        cuda,
        "memory_reserved",
        device_index,
    )
    snapshot["torch_max_allocated_bytes"] = _cuda_memory_metric(
        cuda,
        "max_memory_allocated",
        device_index,
    )
    snapshot["torch_max_reserved_bytes"] = _cuda_memory_metric(
        cuda,
        "max_memory_reserved",
        device_index,
    )
    return snapshot


def _elapsed_seconds(started_at: float | None) -> float:
    start = _MODULE_STARTED_AT if started_at is None else started_at
    return round(time.monotonic() - start, 6)


def _cuda_device_count(cuda: Any) -> int:
    if not cuda or not hasattr(cuda, "device_count"):
        return 0
    try:
        return int(cuda.device_count())
    except BaseException:  # noqa: BLE001 - diagnostics should not fail the probe.
        return 0


def _cuda_current_device(cuda: Any) -> int:
    try:
        return int(cuda.current_device())
    except BaseException:  # noqa: BLE001 - diagnostics should not fail the probe.
        return 0


def _cuda_device_entry(cuda: Any, index: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"index": index}
    try:
        props = cuda.get_device_properties(index)
    except BaseException as exc:  # noqa: BLE001 - diagnostics should not fail the probe.
        entry.update({"error_type": type(exc).__name__, "error": str(exc)})
        return entry
    entry["name"] = getattr(props, "name", "")
    entry["total_memory_bytes"] = getattr(props, "total_memory", None)
    major = getattr(props, "major", None)
    minor = getattr(props, "minor", None)
    if major is not None and minor is not None:
        entry["compute_capability"] = f"{major}.{minor}"
    return entry


def _cuda_mem_get_info(cuda: Any, device_index: int) -> tuple[int | None, int | None]:
    try:
        free_bytes, total_bytes = cuda.mem_get_info(device_index)
    except TypeError:
        try:
            free_bytes, total_bytes = cuda.mem_get_info()
        except BaseException:  # noqa: BLE001 - diagnostics should not fail the probe.
            return None, None
    except BaseException:  # noqa: BLE001 - diagnostics should not fail the probe.
        return None, None
    return int(free_bytes), int(total_bytes)


def _cuda_memory_metric(cuda: Any, name: str, device_index: int) -> int | None:
    metric = getattr(cuda, name, None)
    if not callable(metric):
        return None
    try:
        return int(metric(device_index))
    except TypeError:
        try:
            return int(metric())
        except BaseException:  # noqa: BLE001 - diagnostics should not fail the probe.
            return None
    except BaseException:  # noqa: BLE001 - diagnostics should not fail the probe.
        return None


def curobo_extension_cache_diagnostics() -> dict[str, Any]:
    if importlib.util.find_spec("torch") is None:
        return {"available": False, "extensions": {}}
    try:
        from torch.utils.cpp_extension import _get_build_directory

        extensions = {}
        for name in CUROBO_EXTENSION_NAMES:
            build_dir = Path(_get_build_directory(name, verbose=False))
            extensions[name] = curobo_extension_cache_entry(name, build_dir)
        return {
            "available": True,
            "configured_dir": os.environ.get("TORCH_EXTENSIONS_DIR", ""),
            "extensions": extensions,
        }
    except BaseException as exc:  # noqa: BLE001 - diagnostics should not fail the probe.
        return {
            "available": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "configured_dir": os.environ.get("TORCH_EXTENSIONS_DIR", ""),
            "extensions": {},
        }


def curobo_extension_cache_entry(name: str, build_dir: Path) -> dict[str, Any]:
    files = []
    if build_dir.is_dir():
        for path in sorted(build_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_time": round(stat.st_mtime, 3),
                }
            )
    return {
        "build_dir": str(build_dir),
        "exists": build_dir.is_dir(),
        "so_exists": (build_dir / f"{name}.so").is_file(),
        "lock_exists": (build_dir / "lock").exists(),
        "files": files,
    }


def warp_compatibility_diagnostics() -> dict[str, Any]:
    if importlib.util.find_spec("warp") is None:
        return {"available": False, "adapter": dict(_WARP_COMPATIBILITY_ADAPTER)}
    try:
        import warp as wp

        return warp_compatibility_from_module(wp, _WARP_COMPATIBILITY_ADAPTER)
    except BaseException as exc:  # noqa: BLE001 - diagnostics should not fail the probe.
        return {
            "available": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "adapter": dict(_WARP_COMPATIBILITY_ADAPTER),
        }


def warp_compatibility_from_module(
    wp_module: Any, adapter: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "available": True,
        "version": getattr(wp_module, "__version__", None),
        "has_torch_attr": hasattr(wp_module, "torch"),
        "has_device_from_torch": hasattr(wp_module, "device_from_torch"),
        "has_from_torch": hasattr(wp_module, "from_torch"),
        "has_stream_from_torch": hasattr(wp_module, "stream_from_torch"),
        "adapter": dict(adapter or {}),
    }


def apply_warp_torch_adapter() -> dict[str, Any]:
    try:
        import warp as wp
    except BaseException as exc:  # noqa: BLE001 - adapter should report failures.
        adapter = {
            "available": False,
            "applied": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        _WARP_COMPATIBILITY_ADAPTER.clear()
        _WARP_COMPATIBILITY_ADAPTER.update(adapter)
        return adapter
    adapter = apply_warp_torch_adapter_to_module(wp)
    _WARP_COMPATIBILITY_ADAPTER.clear()
    _WARP_COMPATIBILITY_ADAPTER.update(adapter)
    return adapter


def apply_warp_torch_adapter_to_module(wp_module: Any) -> dict[str, Any]:
    if hasattr(wp_module, "torch"):
        return {
            "available": True,
            "applied": False,
            "reason": "warp.torch already available",
        }
    if not hasattr(wp_module, "device_from_torch"):
        return {
            "available": True,
            "applied": False,
            "reason": "warp.device_from_torch unavailable",
        }
    setattr(
        wp_module,
        "torch",
        SimpleNamespace(device_from_torch=getattr(wp_module, "device_from_torch")),
    )
    return {
        "available": True,
        "applied": True,
        "provided": ["warp.torch.device_from_torch"],
    }


def renderer_device_id_for_probe(
    *,
    probe_mode: str,
    renderer_device_id: int,
) -> int | None:
    if probe_mode != "execute" or renderer_device_id < 0:
        return None
    return renderer_device_id


def configure_headless_renderer_env(args: Any) -> None:
    renderer_device_id = renderer_device_id_for_probe(
        probe_mode=args.probe_mode,
        renderer_device_id=args.renderer_device_id,
    )
    if renderer_device_id is None:
        return
    os.environ["MUJOCO_GL"] = "egl"
    os.environ["PYOPENGL_PLATFORM"] = "egl"
    os.environ["ROBOCLAWS_MOLMOSPACES_RENDERER_DEVICE_ID"] = str(renderer_device_id)


def apply_headless_renderer_adapter(renderer_device_id: int | None) -> dict[str, Any]:
    if renderer_device_id is None:
        return {"enabled": False}
    targets = []
    already_patched = []
    for module_name in (
        "molmo_spaces.env.env",
        "molmo_spaces.utils.scene_maps",
    ):
        module = importlib.import_module(module_name)
        if not hasattr(module, "MjOpenGLRenderer"):
            continue
        targets.append(f"{module_name}.MjOpenGLRenderer")
        module_already_patched = bool(
            getattr(module.MjOpenGLRenderer, "_roboclaws_renderer_adapter", False)
        )
        already_patched.append(module_already_patched)
        if not module_already_patched:
            patch_renderer_constructor(module, renderer_device_id)
    return {
        "enabled": True,
        "device_id": renderer_device_id,
        "targets": targets,
        "already_patched": all(already_patched) if already_patched else False,
    }


def patch_renderer_constructor(env_module: Any, renderer_device_id: int) -> None:
    renderer_cls = env_module.MjOpenGLRenderer

    def renderer_with_device(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("device_id") is None:
            kwargs["device_id"] = renderer_device_id
        return renderer_cls(*args, **kwargs)

    renderer_with_device._roboclaws_renderer_adapter = True  # type: ignore[attr-defined]
    renderer_with_device._roboclaws_renderer_device_id = renderer_device_id  # type: ignore[attr-defined]
    env_module.MjOpenGLRenderer = renderer_with_device
