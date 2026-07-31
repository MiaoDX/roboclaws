from __future__ import annotations

import base64
import io
import math
import os
import threading
import time
from functools import lru_cache
from typing import Any

from PIL import Image

from roboclaws.household.visual_grounding import (
    safe_runtime_parameters,
)
from roboclaws.household.visual_grounding_sidecar.adapter_errors import (
    VisualGroundingDeviceError,
    VisualGroundingRuntimeParameterError,
)

_GROUNDING_DINO_LOAD_LOCK = threading.Lock()


def _load_grounding_dino(
    model_id: str,
    requested_device: str,
    requested_dtype: str,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    with _GROUNDING_DINO_LOAD_LOCK:
        return _load_grounding_dino_cached(model_id, requested_device, requested_dtype)


@lru_cache(maxsize=8)
def _load_grounding_dino_cached(
    model_id: str,
    requested_device: str,
    requested_dtype: str,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    try:
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, GroundingDinoProcessor
    except ImportError as exc:
        raise ImportError(
            "Grounding DINO real mode requires sidecar dependencies: transformers and torch"
        ) from exc

    device = _resolve_torch_device(torch, requested_device)
    dtype, dtype_name = _resolve_torch_dtype(torch, requested_dtype)
    processor = _from_pretrained_local_first(GroundingDinoProcessor, model_id)
    model = _from_pretrained_local_first(AutoModelForZeroShotObjectDetection, model_id)
    try:
        model = model.to(device)
        if dtype is not None:
            model = model.to(dtype=dtype)
    except Exception as exc:
        raise VisualGroundingDeviceError(
            f"failed to place Grounding DINO on device={device} dtype={dtype_name}: {exc}"
        ) from exc
    model.eval()
    runtime = _torch_runtime_diagnostics(
        torch,
        requested_device=requested_device,
        requested_dtype=requested_dtype,
        device=device,
        dtype_name=dtype_name,
        model_id=model_id,
    )
    return processor, model, torch, runtime


def _from_pretrained_local_first(factory: Any, model_id: str) -> Any:
    try:
        return factory.from_pretrained(model_id, local_files_only=True)
    except OSError:
        return factory.from_pretrained(model_id)


@lru_cache(maxsize=4)
def _load_omdet_turbo(
    model_id: str,
    requested_device: str,
    requested_dtype: str,
) -> tuple[Any, Any, Any, dict[str, Any]]:
    try:
        import torch
        from transformers import OmDetTurboForObjectDetection, OmDetTurboProcessor
    except ImportError as exc:
        raise ImportError(
            "OmDet-Turbo real mode requires sidecar dependencies: transformers and torch"
        ) from exc

    device = _resolve_torch_device(torch, requested_device)
    dtype, dtype_name = _resolve_torch_dtype(torch, requested_dtype)
    processor = OmDetTurboProcessor.from_pretrained(model_id)
    model = OmDetTurboForObjectDetection.from_pretrained(model_id)
    _materialize_omdet_meta_attention_masks(model, torch, device=device, dtype=dtype)
    try:
        model = model.to(device)
        if dtype is not None:
            model = model.to(dtype=dtype)
    except Exception as exc:
        raise VisualGroundingDeviceError(
            f"failed to place OmDet-Turbo on device={device} dtype={dtype_name}: {exc}"
        ) from exc
    model.eval()
    runtime = _torch_runtime_diagnostics(
        torch,
        requested_device=requested_device,
        requested_dtype=requested_dtype,
        device=device,
        dtype_name=dtype_name,
        model_id=model_id,
    )
    return processor, model, torch, runtime


def _materialize_omdet_meta_attention_masks(
    model: Any,
    torch_module: Any,
    *,
    device: str,
    dtype: Any | None,
) -> None:
    torch_device = torch_module.device(device)
    mask_dtype = dtype or torch_module.float32
    for module in model.modules():
        attn_mask = getattr(module, "attn_mask", None)
        if attn_mask is None or not bool(getattr(attn_mask, "is_meta", False)):
            continue
        get_attn_mask = getattr(module, "get_attn_mask", None)
        if not callable(get_attn_mask):
            continue
        module.attn_mask = get_attn_mask(device=torch_device, dtype=mask_dtype)


def _resolve_torch_device(torch_module: Any, requested_device: str) -> str:
    requested = str(requested_device or "auto").strip().lower()
    if requested in {"", "auto"}:
        return "cuda" if bool(torch_module.cuda.is_available()) else "cpu"
    if requested.startswith("cuda") and not bool(torch_module.cuda.is_available()):
        raise VisualGroundingDeviceError(
            f"VISUAL_GROUNDING_DEVICE={requested} requested CUDA, but torch.cuda.is_available() "
            "is false in the sidecar environment"
        )
    try:
        torch_module.device(requested)
    except Exception as exc:
        raise VisualGroundingDeviceError(f"invalid VISUAL_GROUNDING_DEVICE={requested}") from exc
    return requested


def _resolve_torch_dtype(torch_module: Any, requested_dtype: str) -> tuple[Any | None, str]:
    requested = str(requested_dtype or "auto").strip().lower()
    if requested in {"", "auto", "none"}:
        return None, "auto"
    aliases = {
        "fp16": "float16",
        "float16": "float16",
        "half": "float16",
        "bf16": "bfloat16",
        "bfloat16": "bfloat16",
        "fp32": "float32",
        "float32": "float32",
    }
    dtype_name = aliases.get(requested)
    if dtype_name is None or not hasattr(torch_module, dtype_name):
        raise VisualGroundingDeviceError(
            "VISUAL_GROUNDING_TORCH_DTYPE must be one of auto, float16, bfloat16, or float32"
        )
    return getattr(torch_module, dtype_name), dtype_name


def _torch_runtime_diagnostics(
    torch_module: Any,
    *,
    requested_device: str,
    requested_dtype: str,
    device: str,
    dtype_name: str,
    model_id: str,
) -> dict[str, Any]:
    cuda_available = bool(torch_module.cuda.is_available())
    diagnostics: dict[str, Any] = {
        "model_id": model_id,
        "requested_device": str(requested_device or "auto"),
        "device": device,
        "requested_dtype": str(requested_dtype or "auto"),
        "dtype": dtype_name,
        "torch_version": str(getattr(torch_module, "__version__", "")),
        "cuda_available": cuda_available,
    }
    if cuda_available:
        try:
            diagnostics["cuda_device_count"] = int(torch_module.cuda.device_count())
            current = int(torch_module.cuda.current_device())
            diagnostics["cuda_current_device"] = current
            diagnostics["cuda_device_name"] = str(torch_module.cuda.get_device_name(current))
        except Exception:
            diagnostics["cuda_device_count"] = int(torch_module.cuda.device_count())
    return diagnostics


@lru_cache(maxsize=4)
def _load_yolo_model(model_id: str, *, producer_id: str) -> Any:
    try:
        if producer_id == "yolo-world":
            from ultralytics import YOLOWorld

            return YOLOWorld(model_id)
        from ultralytics import YOLOE

        return YOLOE(model_id)
    except ImportError as exc:
        raise ImportError(
            f"{producer_id} real mode requires the sidecar dependency: ultralytics"
        ) from exc


def _set_yolo_classes_if_needed(model: Any, labels: list[str], *, producer_id: str) -> None:
    label_key = tuple(labels)
    if getattr(model, "_roboclaws_class_labels", None) == label_key:
        return
    if producer_id == "yolo-world":
        world_model = getattr(model, "model", None)
        if world_model is not None and hasattr(world_model, "clip_model"):
            world_model.clip_model = None
    model.set_classes(labels)
    setattr(model, "_roboclaws_class_labels", label_key)


def _decode_request_image(payload: dict[str, Any]) -> Image.Image:
    image_payload = payload.get("image") or {}
    data = base64.b64decode(str(image_payload.get("bytes_base64") or ""), validate=True)
    if not data:
        raise ValueError("visual grounding request image has no bytes")
    return Image.open(io.BytesIO(data)).convert("RGB")


def _category_hints(payload: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    hints: list[str] = []
    for value in payload.get("category_hints") or []:
        label = str(value or "").strip()
        if not label:
            continue
        key = _norm(label)
        if key in seen:
            continue
        seen.add(key)
        hints.append(label)
    return hints


def _request_model_id(payload: dict[str, Any], producer_id: str) -> str:
    pipeline_request = payload.get("pipeline_request") or {}
    item = pipeline_request.get("proposer") or {}
    if str(item.get("producer_id") or "") == producer_id:
        return str(item.get("model_id") or "")
    return ""


def _request_runtime_parameters(payload: dict[str, Any], producer_id: str) -> dict[str, Any]:
    pipeline_request = payload.get("pipeline_request") or {}
    item = pipeline_request.get("proposer") or {}
    if str(item.get("producer_id") or "") == producer_id:
        params = item.get("runtime_parameters") or item.get("knobs") or {}
        return safe_runtime_parameters(params)
    return {}


def _runtime_float_param(
    runtime_parameters: dict[str, Any],
    key: str,
    *,
    env_name: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = runtime_parameters.get(key)
    if value is None:
        return _float_env(env_name, default, minimum=minimum, maximum=maximum)
    return _float_setting(
        value,
        f"runtime_parameters.{key}",
        minimum=minimum,
        maximum=maximum,
    )


def _runtime_int_param(
    runtime_parameters: dict[str, Any],
    key: str,
    *,
    env_name: str,
    minimum: int | None = None,
) -> int | None:
    value = runtime_parameters.get(key)
    if value is None:
        return _int_env_optional(env_name, minimum=minimum)
    return _int_setting(value, f"runtime_parameters.{key}", minimum=minimum)


def _runtime_bool_param(
    runtime_parameters: dict[str, Any],
    key: str,
    *,
    env_name: str,
    default: bool | None = None,
) -> bool | None:
    value = runtime_parameters.get(key)
    if value is None:
        if _env_is_set(env_name):
            return _bool_env(env_name)
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise VisualGroundingRuntimeParameterError(
        f"visual grounding runtime parameter runtime_parameters.{key} must be a boolean, "
        f"got {value!r}"
    )


def _label_prompt(label: str) -> str:
    cleaned = str(label or "").strip()
    if not cleaned:
        return "object"
    return cleaned if cleaned.lower().startswith(("a ", "an ")) else f"a {cleaned}"


def _float_at(values: list[Any], index: int, *, default: float) -> float:
    return _float_or_none(_value_at(values, index, default=default)) or default


def _value_at(values: list[Any], index: int, *, default: Any) -> Any:
    return values[index] if index < len(values) else default


def _float_or_none(value: Any) -> float | None:
    try:
        if hasattr(value, "item"):
            value = value.item()
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if hasattr(value, "item"):
            value = value.item()
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_env(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.environ.get(name)
    if raw in {None, ""}:
        return default
    return _float_setting(raw, name, minimum=minimum, maximum=maximum)


def _float_env_optional(
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    raw = os.environ.get(name)
    if raw in {None, ""}:
        return None
    return _float_setting(raw, name, minimum=minimum, maximum=maximum)


def _float_setting(
    value: Any,
    setting_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be numeric, got {value!r}"
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be numeric, got {value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be finite, got {value!r}"
        )
    if minimum is not None and parsed < minimum:
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be >= {minimum}, got {value!r}"
        )
    if maximum is not None and parsed > maximum:
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be <= {maximum}, got {value!r}"
        )
    return parsed


def _int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw in {None, ""}:
        return default
    return _int_setting(raw, name, minimum=minimum)


def _int_env_optional(name: str, *, minimum: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw in {None, ""}:
        return None
    return _int_setting(raw, name, minimum=minimum)


def _int_setting(value: Any, setting_name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be an integer, got {value!r}"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be an integer, got {value!r}"
        ) from exc
    if minimum is not None and parsed < minimum:
        raise VisualGroundingRuntimeParameterError(
            f"visual grounding runtime parameter {setting_name} must be >= {minimum}, got {value!r}"
        )
    return parsed


def _bool_env(name: str) -> bool:
    raw = os.environ.get(name, "")
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise VisualGroundingRuntimeParameterError(
        f"visual grounding runtime parameter {name} must be a boolean, got {raw!r}"
    )


def _env_is_set(name: str) -> bool:
    return os.environ.get(name) not in {None, ""}


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _elapsed_ms(started: float, *, minimum: int) -> int:
    return max(int(minimum), round((time.monotonic() - started) * 1000))


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())
