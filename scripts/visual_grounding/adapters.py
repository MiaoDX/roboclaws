from __future__ import annotations

import base64
import importlib.util
import io
import math
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PIL import Image

from roboclaws.household.visual_grounding import (
    VISUAL_GROUNDING_RESPONSE_SCHEMA,
    safe_runtime_parameters,
    validate_visual_grounding_response,
)

ADAPTER_MODE_AUTO = "auto"
ADAPTER_MODE_REAL = "real"
ADAPTER_MODE_UNAVAILABLE = "unavailable"
REAL_ROUTER_PIPELINE_ID = "real-router"
DEFAULT_PIPELINE_ID = "grounding-dino"
DEFAULT_GROUNDING_DINO_MODEL_ID = "IDEA-Research/grounding-dino-base"
DEFAULT_GROUNDING_DINO_BOX_THRESHOLD = 0.25
DEFAULT_GROUNDING_DINO_TEXT_THRESHOLD = 0.20
ADAPTER_CATALOG_SCHEMA = "visual_grounding_adapter_catalog_v1"
_GROUNDING_DINO_LOAD_LOCK = threading.Lock()


@dataclass(frozen=True)
class AdapterSpec:
    producer_id: str
    role: str
    status: str
    model_id: str
    optional_extra: str
    setup_hint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "producer_id": self.producer_id,
            "role": self.role,
            "status": self.status,
            "model_id": self.model_id,
            "optional_extra": self.optional_extra,
            "runtime": adapter_runtime_status(self.producer_id),
            "setup_hint": self.setup_hint,
        }


ADAPTER_SPECS: dict[str, AdapterSpec] = {
    "grounding-dino": AdapterSpec(
        producer_id="grounding-dino",
        role="proposer",
        status="adapter_unavailable",
        model_id=DEFAULT_GROUNDING_DINO_MODEL_ID,
        optional_extra="visual-grounding-dino",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Transformers, Torch, and the selected Grounding DINO model weights."
        ),
    ),
    "yoloe": AdapterSpec(
        producer_id="yoloe",
        role="proposer",
        status="adapter_unavailable",
        model_id="yoloe-11s-seg.pt",
        optional_extra="visual-grounding-yoloe",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Ultralytics, the CLIP tokenizer package, and approved YOLOE weights."
        ),
    ),
    "yolo-world": AdapterSpec(
        producer_id="yolo-world",
        role="proposer",
        status="adapter_unavailable",
        model_id="yolov8s-world.pt",
        optional_extra="visual-grounding-yolo-world",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Ultralytics and approved YOLO-World weights."
        ),
    ),
    "omdet-turbo": AdapterSpec(
        producer_id="omdet-turbo",
        role="proposer",
        status="adapter_unavailable",
        model_id="omlab/omdet-turbo-swin-tiny-hf",
        optional_extra="visual-grounding-omdet",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Torch, Transformers, and approved OmDet-Turbo weights."
        ),
    ),
}


def visual_grounding_service_response(
    *,
    payload: dict[str, Any],
    configured_pipeline_id: str,
    adapter_mode: str,
    latency_ms: int,
) -> dict[str, Any]:
    requested_pipeline_id = request_pipeline_id(payload)
    selected_pipeline_id = effective_pipeline_id(
        configured_pipeline_id=configured_pipeline_id,
        requested_pipeline_id=requested_pipeline_id,
    )
    if not pipeline_request_is_allowed(
        configured_pipeline_id=configured_pipeline_id,
        requested_pipeline_id=requested_pipeline_id,
        effective_pipeline_id=selected_pipeline_id,
    ):
        return pipeline_mismatch_response(
            configured_pipeline_id=configured_pipeline_id,
            requested_pipeline_id=requested_pipeline_id,
        )
    if adapter_mode == ADAPTER_MODE_REAL:
        return real_adapter_response(
            payload=payload,
            pipeline_id=selected_pipeline_id,
            latency_ms=latency_ms,
        )

    return adapter_unavailable_response(
        pipeline_id=selected_pipeline_id,
        adapter_mode=adapter_mode,
        latency_ms=latency_ms,
    )


def visual_grounding_adapter_catalog() -> dict[str, Any]:
    return {
        "schema": ADAPTER_CATALOG_SCHEMA,
        "real_router_pipeline_id": REAL_ROUTER_PIPELINE_ID,
        "default_pipeline_id": DEFAULT_PIPELINE_ID,
        "adapter_modes": [
            ADAPTER_MODE_AUTO,
            ADAPTER_MODE_REAL,
            ADAPTER_MODE_UNAVAILABLE,
        ],
        "adapters": [spec.as_dict() for spec in ADAPTER_SPECS.values()],
        "private_truth_included": False,
    }


def adapter_runtime_status(producer_id: str) -> dict[str, Any]:
    if producer_id == "grounding-dino":
        checks = _module_checks("torch", "transformers")
        return _dependency_runtime_status(
            checks=checks,
            ready_message=(
                "Grounding DINO Python dependencies are importable; model weights "
                "are verified only by a real adapter run."
            ),
            missing_message=(
                "Grounding DINO real mode requires importable torch and transformers "
                "in the sidecar environment."
            ),
        )
    if producer_id in {"yoloe", "yolo-world"}:
        checks = _module_checks("ultralytics")
        return _dependency_runtime_status(
            checks=checks,
            ready_message=(
                "Ultralytics is importable; YOLO-family weights are verified only "
                "by a real adapter run."
            ),
            missing_message=(
                f"{producer_id} real mode requires importable ultralytics in the "
                "sidecar environment."
            ),
        )
    if producer_id == "omdet-turbo":
        checks = _module_checks("torch", "transformers")
        return _dependency_runtime_status(
            checks=checks,
            ready_message=(
                "Torch and Transformers are importable; OmDet-Turbo weights are "
                "verified only by a real adapter run."
            ),
            missing_message=(
                "omdet-turbo real mode requires importable torch and transformers "
                "in the sidecar environment."
            ),
        )
    return {
        "status": "unknown_adapter",
        "checks": [],
        "auth_mode": "none",
        "model_weights_verified": False,
        "message": "No runtime readiness probe is registered for this adapter.",
    }


def _dependency_runtime_status(
    *,
    checks: list[dict[str, Any]],
    ready_message: str,
    missing_message: str,
) -> dict[str, Any]:
    missing = [str(item["name"]) for item in checks if not item["available"]]
    if missing:
        return {
            "status": "missing_dependency",
            "checks": checks,
            "missing_dependencies": missing,
            "auth_mode": "none",
            "model_weights_verified": False,
            "message": missing_message,
        }
    return {
        "status": "dependency_ready_model_unverified",
        "checks": checks,
        "missing_dependencies": [],
        "auth_mode": "none",
        "model_weights_verified": False,
        "message": ready_message,
    }


def _module_checks(*module_names: str) -> list[dict[str, Any]]:
    return [
        {
            "name": module_name,
            "available": importlib.util.find_spec(module_name) is not None,
        }
        for module_name in module_names
    ]


def request_pipeline_id(payload: dict[str, Any]) -> str:
    pipeline_request = payload.get("pipeline_request") or {}
    return str(pipeline_request.get("pipeline_id") or "").strip()


def effective_pipeline_id(
    *,
    configured_pipeline_id: str,
    requested_pipeline_id: str,
) -> str:
    configured = str(configured_pipeline_id or "").strip()
    requested = str(requested_pipeline_id or "").strip()
    if configured == REAL_ROUTER_PIPELINE_ID:
        return requested or DEFAULT_PIPELINE_ID
    return configured or requested or DEFAULT_PIPELINE_ID


def pipeline_request_is_allowed(
    *,
    configured_pipeline_id: str,
    requested_pipeline_id: str,
    effective_pipeline_id: str,
) -> bool:
    if configured_pipeline_id == REAL_ROUTER_PIPELINE_ID:
        return True
    if not requested_pipeline_id:
        return True
    return requested_pipeline_id == effective_pipeline_id


def real_adapter_response(
    *,
    payload: dict[str, Any],
    pipeline_id: str,
    latency_ms: int,
) -> dict[str, Any]:
    proposer_id = pipeline_id
    proposer_response = _real_proposer_response(
        payload=payload,
        pipeline_id=pipeline_id,
        producer_id=proposer_id,
        latency_ms=latency_ms,
    )
    if proposer_response is not None:
        return proposer_response
    return adapter_unavailable_response(
        pipeline_id=pipeline_id,
        adapter_mode=ADAPTER_MODE_REAL,
        latency_ms=latency_ms,
    )


def _real_proposer_response(
    *,
    payload: dict[str, Any],
    pipeline_id: str,
    producer_id: str,
    latency_ms: int,
) -> dict[str, Any] | None:
    if producer_id == "grounding-dino":
        return _grounding_dino_real_response(
            payload=payload,
            pipeline_id=pipeline_id,
            latency_ms=latency_ms,
        )
    if producer_id in {"yoloe", "yolo-world"}:
        return _yolo_real_response(
            payload=payload,
            pipeline_id=pipeline_id,
            producer_id=producer_id,
            latency_ms=latency_ms,
        )
    if producer_id == "omdet-turbo":
        return _omdet_turbo_real_response(
            payload=payload,
            pipeline_id=pipeline_id,
            latency_ms=latency_ms,
        )
    return None


class VisualGroundingDeviceError(RuntimeError):
    """Requested sidecar model device is unavailable or invalid."""


class VisualGroundingRuntimeParameterError(ValueError):
    """Requested sidecar runtime parameter is malformed or out of range."""


def _grounding_dino_real_response(
    *,
    payload: dict[str, Any],
    pipeline_id: str,
    latency_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    producer_id = "grounding-dino"
    spec = ADAPTER_SPECS[producer_id]
    model_id = _request_model_id(payload, producer_id) or os.environ.get(
        "VISUAL_GROUNDING_DINO_MODEL_ID",
        spec.model_id,
    )
    runtime_parameters = _request_runtime_parameters(payload, producer_id)
    device_request = str(
        runtime_parameters.get("device") or os.environ.get("VISUAL_GROUNDING_DEVICE", "auto")
    )
    dtype_request = str(
        runtime_parameters.get("torch_dtype")
        or runtime_parameters.get("dtype")
        or os.environ.get("VISUAL_GROUNDING_TORCH_DTYPE", "auto")
    )
    runtime_diagnostics: dict[str, Any] = {
        "requested_device": device_request,
        "requested_dtype": dtype_request,
        "runtime_parameters": runtime_parameters,
    }
    try:
        image = _decode_request_image(payload)
        labels = _category_hints(payload)
        threshold = _runtime_float_param(
            runtime_parameters,
            "box_threshold",
            env_name="VISUAL_GROUNDING_DINO_BOX_THRESHOLD",
            default=DEFAULT_GROUNDING_DINO_BOX_THRESHOLD,
            minimum=0.0,
            maximum=1.0,
        )
        text_threshold = _runtime_float_param(
            runtime_parameters,
            "text_threshold",
            env_name="VISUAL_GROUNDING_DINO_TEXT_THRESHOLD",
            default=DEFAULT_GROUNDING_DINO_TEXT_THRESHOLD,
            minimum=0.0,
            maximum=1.0,
        )
        runtime_parameters = {
            **runtime_parameters,
            "box_threshold": threshold,
            "text_threshold": text_threshold,
        }
        runtime_diagnostics = {
            **runtime_diagnostics,
            "runtime_parameters": runtime_parameters,
        }
        if not labels:
            return _real_adapter_ok_response(
                pipeline_id=pipeline_id,
                stage="proposer",
                producer_id=producer_id,
                model_id=model_id,
                latency_ms=_elapsed_ms(started, minimum=latency_ms),
                candidates=[],
                raw_proposals=[],
                diagnostic_mode="real_grounding_dino",
                stage_metadata={
                    "runtime": runtime_diagnostics,
                    "runtime_parameters": runtime_parameters,
                },
                diagnostics_extra={"runtime": runtime_diagnostics},
            )
        processor, model, torch_module, runtime_diagnostics = _load_grounding_dino(
            model_id,
            device_request,
            dtype_request,
        )
        text_labels = [[_label_prompt(label) for label in labels]]
        inputs = processor(images=image, text=text_labels, return_tensors="pt")
        device = runtime_diagnostics.get("device")
        if device and hasattr(inputs, "to"):
            inputs = inputs.to(str(device))
        with torch_module.no_grad():
            outputs = model(**inputs)
        runtime_diagnostics = {
            **runtime_diagnostics,
            "runtime_parameters": runtime_parameters,
        }
        try:
            results = processor.post_process_grounded_object_detection(
                outputs,
                getattr(inputs, "input_ids", None),
                box_threshold=threshold,
                text_threshold=text_threshold,
                target_sizes=[(image.height, image.width)],
            )
        except TypeError:
            results = processor.post_process_grounded_object_detection(
                outputs,
                getattr(inputs, "input_ids", None),
                threshold=threshold,
                text_threshold=text_threshold,
                target_sizes=[(image.height, image.width)],
            )
        candidates = _grounding_dino_candidates_from_result(
            payload=payload,
            image=image,
            result=(results or [{}])[0],
            category_hints=labels,
        )
        return _real_adapter_ok_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            candidates=candidates,
            raw_proposals=candidates,
            diagnostic_mode="real_grounding_dino",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_diagnostics["runtime_parameters"],
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except VisualGroundingRuntimeParameterError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="invalid_runtime_parameter",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_grounding_dino",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except ImportError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="missing_dependency",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_grounding_dino",
            required_adapter=_required_adapter_record(
                {"stage": "proposer", "producer_id": producer_id},
                spec,
            ),
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except VisualGroundingDeviceError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="device_unavailable",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_grounding_dino",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except Exception as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="adapter_error",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_grounding_dino",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )


def _yolo_real_response(
    *,
    payload: dict[str, Any],
    pipeline_id: str,
    producer_id: str,
    latency_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    spec = ADAPTER_SPECS[producer_id]
    env_name = {
        "yolo-world": "VISUAL_GROUNDING_YOLO_WORLD_MODEL_ID",
    }.get(producer_id, "VISUAL_GROUNDING_YOLOE_MODEL_ID")
    model_id = _request_model_id(payload, producer_id) or os.environ.get(env_name, spec.model_id)
    runtime_parameters = _request_runtime_parameters(payload, producer_id)
    try:
        image = _decode_request_image(payload)
        labels = _yolo_prompt_labels(
            _category_hints(payload),
            runtime_parameters=runtime_parameters,
        )
        predict_kwargs = _yolo_predict_kwargs(runtime_parameters)
        if not labels:
            return _real_adapter_ok_response(
                pipeline_id=pipeline_id,
                stage="proposer",
                producer_id=producer_id,
                model_id=model_id,
                latency_ms=_elapsed_ms(started, minimum=latency_ms),
                candidates=[],
                raw_proposals=[],
                diagnostic_mode=f"real_{producer_id}",
                stage_metadata={"runtime_parameters": runtime_parameters},
                diagnostics_extra={"runtime_parameters": runtime_parameters},
            )
        model = _load_yolo_model(model_id, producer_id=producer_id)
        if hasattr(model, "set_classes"):
            _set_yolo_classes_if_needed(model, labels, producer_id=producer_id)
        candidates = _yolo_candidates_from_model(
            payload=payload,
            image=image,
            model=model,
            category_hints=labels,
            predict_kwargs=predict_kwargs,
        )
        return _real_adapter_ok_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            candidates=candidates,
            raw_proposals=candidates,
            diagnostic_mode=f"real_{producer_id}",
            stage_metadata={"runtime_parameters": runtime_parameters},
            diagnostics_extra={"runtime_parameters": runtime_parameters},
        )
    except VisualGroundingRuntimeParameterError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="invalid_runtime_parameter",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode=f"real_{producer_id}",
            stage_metadata={"runtime_parameters": runtime_parameters},
            diagnostics_extra={"runtime_parameters": runtime_parameters},
        )
    except ImportError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="missing_dependency",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode=f"real_{producer_id}",
            required_adapter=_required_adapter_record(
                {"stage": "proposer", "producer_id": producer_id},
                spec,
            ),
            stage_metadata={"runtime_parameters": runtime_parameters},
            diagnostics_extra={"runtime_parameters": runtime_parameters},
        )
    except Exception as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="adapter_error",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode=f"real_{producer_id}",
            stage_metadata={"runtime_parameters": runtime_parameters},
            diagnostics_extra={"runtime_parameters": runtime_parameters},
        )


def _omdet_turbo_real_response(
    *,
    payload: dict[str, Any],
    pipeline_id: str,
    latency_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    producer_id = "omdet-turbo"
    spec = ADAPTER_SPECS[producer_id]
    model_id = _request_model_id(payload, producer_id) or os.environ.get(
        "VISUAL_GROUNDING_OMDET_MODEL_ID",
        spec.model_id,
    )
    runtime_parameters = _request_runtime_parameters(payload, producer_id)
    device_request = str(
        runtime_parameters.get("device") or os.environ.get("VISUAL_GROUNDING_DEVICE", "auto")
    )
    dtype_request = str(
        runtime_parameters.get("torch_dtype")
        or runtime_parameters.get("dtype")
        or os.environ.get("VISUAL_GROUNDING_TORCH_DTYPE", "auto")
    )
    runtime_diagnostics: dict[str, Any] = {
        "requested_device": device_request,
        "requested_dtype": dtype_request,
        "runtime_parameters": runtime_parameters,
    }
    try:
        image = _decode_request_image(payload)
        labels = _category_hints(payload)
        threshold = _runtime_float_param(
            runtime_parameters,
            "confidence_threshold",
            env_name="VISUAL_GROUNDING_OMDET_CONFIDENCE_THRESHOLD",
            default=0.25,
            minimum=0.0,
            maximum=1.0,
        )
        nms_threshold = _runtime_float_param(
            runtime_parameters,
            "nms_threshold",
            env_name="VISUAL_GROUNDING_OMDET_NMS_THRESHOLD",
            default=0.5,
            minimum=0.0,
            maximum=1.0,
        )
        max_num_det = _runtime_int_param(
            runtime_parameters,
            "max_detections",
            env_name="VISUAL_GROUNDING_OMDET_MAX_DET",
            minimum=1,
        )
        runtime_parameters = {
            **runtime_parameters,
            "confidence_threshold": threshold,
            "nms_threshold": nms_threshold,
            **({"max_detections": max_num_det} if max_num_det is not None else {}),
        }
        runtime_diagnostics = {
            **runtime_diagnostics,
            "runtime_parameters": runtime_parameters,
        }
        if not labels:
            return _real_adapter_ok_response(
                pipeline_id=pipeline_id,
                stage="proposer",
                producer_id=producer_id,
                model_id=model_id,
                latency_ms=_elapsed_ms(started, minimum=latency_ms),
                candidates=[],
                raw_proposals=[],
                diagnostic_mode="real_omdet-turbo",
                stage_metadata={
                    "runtime": runtime_diagnostics,
                    "runtime_parameters": runtime_parameters,
                },
                diagnostics_extra={"runtime": runtime_diagnostics},
            )
        processor, model, torch_module, runtime_diagnostics = _load_omdet_turbo(
            model_id,
            device_request,
            dtype_request,
        )
        text_labels = [_label_prompt(label) for label in labels]
        task = str(
            runtime_parameters.get("task")
            or os.environ.get("VISUAL_GROUNDING_OMDET_TASK", "")
            or f"Detect {', '.join(text_labels)}."
        )
        inputs = processor(images=image, text=text_labels, task=task, return_tensors="pt")
        device = runtime_diagnostics.get("device")
        if device and hasattr(inputs, "to"):
            inputs = inputs.to(str(device))
        with torch_module.no_grad():
            outputs = model(**inputs)
        runtime_diagnostics = {
            **runtime_diagnostics,
            "runtime_parameters": runtime_parameters,
        }
        results = processor.post_process_grounded_object_detection(
            outputs,
            text_labels=text_labels,
            threshold=threshold,
            nms_threshold=nms_threshold,
            target_sizes=[(image.height, image.width)],
            max_num_det=max_num_det,
        )
        candidates = _omdet_candidates_from_result(
            payload=payload,
            image=image,
            result=(results or [{}])[0],
            category_hints=labels,
        )
        return _real_adapter_ok_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            candidates=candidates,
            raw_proposals=candidates,
            diagnostic_mode="real_omdet-turbo",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_diagnostics["runtime_parameters"],
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except VisualGroundingRuntimeParameterError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="invalid_runtime_parameter",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_omdet-turbo",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except ImportError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="missing_dependency",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_omdet-turbo",
            required_adapter=_required_adapter_record(
                {"stage": "proposer", "producer_id": producer_id},
                spec,
            ),
            stage_metadata={"runtime_parameters": runtime_parameters},
            diagnostics_extra={"runtime_parameters": runtime_parameters},
        )
    except VisualGroundingDeviceError as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="device_unavailable",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_omdet-turbo",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )
    except Exception as exc:
        return _real_adapter_failure_response(
            pipeline_id=pipeline_id,
            stage="proposer",
            producer_id=producer_id,
            model_id=model_id,
            reason="adapter_error",
            message=str(exc),
            latency_ms=_elapsed_ms(started, minimum=latency_ms),
            diagnostic_mode="real_omdet-turbo",
            stage_metadata={
                "runtime": runtime_diagnostics,
                "runtime_parameters": runtime_parameters,
            },
            diagnostics_extra={"runtime": runtime_diagnostics},
        )


def adapter_unavailable_response(
    *,
    pipeline_id: str,
    adapter_mode: str,
    latency_ms: int,
) -> dict[str, Any]:
    producer_id = str(pipeline_id or DEFAULT_PIPELINE_ID)
    spec = ADAPTER_SPECS.get(producer_id)
    stage = {
        "stage": "proposer",
        "producer_id": producer_id,
        "model_id": spec.model_id if spec is not None else "",
        "status": "adapter_unavailable",
        "version": "adapter-unavailable-v1",
        "latency_ms": latency_ms,
    }
    if spec is not None:
        stage["optional_extra"] = spec.optional_extra
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "failed",
        "pipeline": {
            "pipeline_id": pipeline_id,
            "stages": [stage],
        },
        "candidates": [],
        "error": {
            "reason": "adapter_unavailable",
            "message": (
                f"visual grounding adapter for '{pipeline_id}' is not installed; "
                "install the optional sidecar adapter or run with --adapter-mode real "
                "in an environment with the selected model dependencies and weights."
            ),
        },
        "diagnostics": {
            "schema": "visual_grounding_diagnostics_v1",
            "diagnostic_mode": "adapter_registry_stub",
            "adapter_mode": adapter_mode,
            "required_adapters": [_required_adapter_record(stage, spec)],
            "raw_proposals": [],
            "rejected_proposals": [],
            "private_truth_included": False,
        },
    }
    return validate_visual_grounding_response(response)


def pipeline_mismatch_response(
    *,
    configured_pipeline_id: str,
    requested_pipeline_id: str,
) -> dict[str, Any]:
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "failed",
        "pipeline": {
            "pipeline_id": requested_pipeline_id or configured_pipeline_id,
            "stages": [
                {
                    "stage": "router",
                    "producer_id": configured_pipeline_id,
                    "model_id": "",
                    "status": "pipeline_mismatch",
                    "latency_ms": 0,
                }
            ],
        },
        "candidates": [],
        "error": {
            "reason": "pipeline_mismatch",
            "message": (
                f"service pipeline '{configured_pipeline_id}' cannot satisfy "
                f"request pipeline '{requested_pipeline_id}'"
            ),
        },
    }
    return validate_visual_grounding_response(response)


def _required_adapter_record(
    stage: dict[str, Any],
    spec: AdapterSpec | None,
) -> dict[str, Any]:
    producer_id = str(stage.get("producer_id") or "")
    if spec is None:
        return {
            "stage": str(stage.get("stage") or ""),
            "producer_id": producer_id,
            "status": "adapter_unavailable",
            "model_id": str(stage.get("model_id") or ""),
            "optional_extra": "",
            "setup_hint": "No adapter spec is registered for this producer id.",
        }
    return {
        "stage": str(stage.get("stage") or ""),
        "producer_id": producer_id,
        "status": spec.status,
        "model_id": spec.model_id,
        "optional_extra": spec.optional_extra,
        "setup_hint": spec.setup_hint,
    }


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


def _grounding_dino_candidates_from_result(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    result: dict[str, Any],
    category_hints: list[str],
) -> list[dict[str, Any]]:
    boxes = _rows(result.get("boxes"))
    scores = _vector(result.get("scores"))
    labels = _vector(result.get("text_labels") or result.get("labels"))
    candidates: list[dict[str, Any]] = []
    for index, box in enumerate(boxes):
        confidence = _float_at(scores, index, default=0.0)
        category = _category_from_model_label(
            _value_at(labels, index, default=""),
            category_hints,
        )
        candidate = _candidate_from_xyxy(
            payload=payload,
            image=image,
            category=category,
            xyxy=box,
            confidence=confidence,
            evidence_note=f"Grounding DINO detected {category} from RAW_FPV pixels",
        )
        if candidate is not None:
            candidates.append(candidate)
    return _top_candidates(candidates)


def _omdet_candidates_from_result(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    result: dict[str, Any],
    category_hints: list[str],
) -> list[dict[str, Any]]:
    boxes = _rows(result.get("boxes"))
    scores = _vector(result.get("scores"))
    labels = _vector(result.get("text_labels") or result.get("labels"))
    candidates: list[dict[str, Any]] = []
    for index, box in enumerate(boxes):
        category = _category_from_model_label(
            _value_at(labels, index, default=""),
            category_hints,
        )
        candidate = _candidate_from_xyxy(
            payload=payload,
            image=image,
            category=category,
            xyxy=box,
            confidence=_float_at(scores, index, default=0.0),
            evidence_note=f"OmDet-Turbo detected {category} from RAW_FPV pixels",
        )
        if candidate is not None:
            candidates.append(candidate)
    return _top_candidates(candidates)


def _yolo_candidates_from_model(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    model: Any,
    category_hints: list[str],
    predict_kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    results = _run_yolo_prediction(
        image=image,
        model=model,
        predict_kwargs=predict_kwargs,
    )
    candidates: list[dict[str, Any]] = []
    for result in results or []:
        candidates.extend(
            _yolo_candidates_from_result(
                payload=payload,
                image=image,
                result=result,
                category_hints=category_hints,
            )
        )
    return _top_candidates(candidates)


def _yolo_predict_kwargs(runtime_parameters: dict[str, Any]) -> dict[str, Any]:
    threshold = _runtime_float_param(
        runtime_parameters,
        "confidence_threshold",
        env_name="VISUAL_GROUNDING_YOLO_CONFIDENCE_THRESHOLD",
        default=0.25,
        minimum=0.0,
        maximum=1.0,
    )
    predict_kwargs: dict[str, Any] = {
        "conf": threshold,
        "verbose": False,
    }
    imgsz = _runtime_int_param(
        runtime_parameters,
        "image_size",
        env_name="VISUAL_GROUNDING_YOLO_IMAGE_SIZE",
        minimum=1,
    )
    if imgsz is not None:
        predict_kwargs["imgsz"] = imgsz
    iou_value = runtime_parameters.get("iou_threshold")
    iou = _float_env_optional(
        "VISUAL_GROUNDING_YOLO_IOU_THRESHOLD",
        minimum=0.0,
        maximum=1.0,
    )
    if iou_value is not None:
        iou = _float_setting(
            iou_value,
            "runtime_parameters.iou_threshold",
            minimum=0.0,
            maximum=1.0,
        )
    if iou is not None:
        predict_kwargs["iou"] = iou
    max_det = _runtime_int_param(
        runtime_parameters,
        "max_detections",
        env_name="VISUAL_GROUNDING_YOLO_MAX_DET",
        minimum=1,
    )
    if max_det is not None:
        predict_kwargs["max_det"] = max_det
    agnostic_nms = _runtime_bool_param(
        runtime_parameters,
        "agnostic_nms",
        env_name="VISUAL_GROUNDING_YOLO_AGNOSTIC_NMS",
    )
    if agnostic_nms is not None:
        predict_kwargs["agnostic_nms"] = agnostic_nms
    augment = _runtime_bool_param(
        runtime_parameters,
        "augment",
        env_name="VISUAL_GROUNDING_YOLO_AUGMENT",
    )
    if augment is not None:
        predict_kwargs["augment"] = augment
    retina_masks = _runtime_bool_param(
        runtime_parameters,
        "retina_masks",
        env_name="VISUAL_GROUNDING_YOLO_RETINA_MASKS",
    )
    if retina_masks is not None:
        predict_kwargs["retina_masks"] = retina_masks
    return predict_kwargs


def _run_yolo_prediction(
    *,
    image: Image.Image,
    model: Any,
    predict_kwargs: dict[str, Any],
) -> Any:
    with tempfile.NamedTemporaryFile(suffix=".jpg") as temp_image:
        image.save(temp_image.name, format="JPEG", quality=90)
        if hasattr(model, "predict"):
            return model.predict(source=temp_image.name, **predict_kwargs)
        return model(temp_image.name)


def _yolo_candidates_from_result(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    result: Any,
    category_hints: list[str],
) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    rows = _rows(getattr(boxes, "xyxy", []))
    confidences = _vector(getattr(boxes, "conf", []))
    classes = _vector(getattr(boxes, "cls", []))
    names = getattr(result, "names", {}) or {}
    candidates: list[dict[str, Any]] = []
    for index, box in enumerate(rows):
        class_id = int(_float_at(classes, index, default=index))
        category = _category_from_yolo_class(
            class_id=class_id,
            names=names,
            category_hints=category_hints,
        )
        candidate = _candidate_from_xyxy(
            payload=payload,
            image=image,
            category=category,
            xyxy=box,
            confidence=_float_at(confidences, index, default=0.0),
            evidence_note=f"YOLOE detected {category} from RAW_FPV pixels",
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _yolo_prompt_labels(
    category_hints: list[str],
    *,
    runtime_parameters: dict[str, Any] | None = None,
) -> list[str]:
    runtime_parameters = runtime_parameters or {}
    expand = _runtime_bool_param(
        runtime_parameters,
        "prompt_expansion",
        env_name="VISUAL_GROUNDING_YOLO_EXPAND_CLEANUP_HINTS",
        default=True,
    )
    if not expand:
        return category_hints
    expansions = {
        "dish": ("dish", "plate", "bowl", "cup", "mug", "utensil"),
        "food": ("food", "apple", "potato", "bread", "fruit", "vegetable"),
        "book": ("book", "paper", "magazine", "newspaper"),
        "linen": ("linen", "towel", "cloth", "blanket"),
        "toy": ("toy", "ball", "plush toy", "teddy bear"),
        "electronics": ("electronics", "remote control", "remote", "phone"),
        "pillow": ("pillow", "cushion"),
    }
    labels: list[str] = []
    seen: set[str] = set()
    for hint in category_hints:
        for label in expansions.get(_norm(hint), (hint,)):
            key = _norm(label)
            if not key or key in seen:
                continue
            seen.add(key)
            labels.append(label)
    return labels


def _candidate_from_xyxy(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    category: str,
    xyxy: Any,
    confidence: float,
    evidence_note: str,
) -> dict[str, Any] | None:
    bbox = _normalized_xyxy_to_xywh(xyxy, width=image.width, height=image.height)
    if bbox is None:
        return None
    return {
        "category": category or "object",
        "image_region": {"type": "bbox", "value": bbox},
        "confidence": _clamp_float(confidence, 0.0, 1.0),
        "evidence_note": evidence_note,
        "source_fixture_id": "",
        "destination_hint": _destination_hint(payload, category),
    }


def _real_adapter_ok_response(
    *,
    pipeline_id: str,
    stage: str,
    producer_id: str,
    model_id: str,
    latency_ms: int,
    candidates: list[dict[str, Any]],
    raw_proposals: list[dict[str, Any]],
    diagnostic_mode: str,
    stage_metadata: dict[str, Any] | None = None,
    diagnostics_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_row = {
        "stage": stage,
        "producer_id": producer_id,
        "model_id": model_id,
        "version": "real-sidecar-adapter-v1",
        "status": "ok",
        "latency_ms": latency_ms,
    }
    if stage_metadata:
        stage_row.update(stage_metadata)
    diagnostics = {
        "schema": "visual_grounding_diagnostics_v1",
        "diagnostic_mode": diagnostic_mode,
        "raw_proposals": raw_proposals,
        "rejected_proposals": [],
        "private_truth_included": False,
    }
    if diagnostics_extra:
        diagnostics.update(diagnostics_extra)
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "ok",
        "pipeline": {
            "pipeline_id": pipeline_id,
            "stages": [stage_row],
        },
        "candidates": candidates,
        "diagnostics": diagnostics,
    }
    return validate_visual_grounding_response(response)


def _real_adapter_pipeline_ok_response(
    *,
    pipeline_id: str,
    stages: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    raw_proposals: list[dict[str, Any]],
    rejected_proposals: list[dict[str, Any]],
    diagnostic_mode: str,
    auth_mode: str = "",
) -> dict[str, Any]:
    diagnostics = {
        "schema": "visual_grounding_diagnostics_v1",
        "diagnostic_mode": diagnostic_mode,
        "raw_proposals": raw_proposals,
        "rejected_proposals": rejected_proposals,
        "private_truth_included": False,
    }
    if auth_mode:
        diagnostics["auth_mode"] = auth_mode
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "ok",
        "pipeline": {
            "pipeline_id": pipeline_id,
            "stages": stages,
        },
        "candidates": candidates,
        "diagnostics": diagnostics,
    }
    return validate_visual_grounding_response(response)


def _pipeline_failure_from_stage_response(
    *,
    pipeline_id: str,
    response: dict[str, Any],
    diagnostic_mode: str,
) -> dict[str, Any]:
    copied = dict(response)
    copied["pipeline"] = dict(response.get("pipeline") or {})
    copied["pipeline"]["pipeline_id"] = pipeline_id
    diagnostics = dict(copied.get("diagnostics") or {})
    diagnostics.setdefault("schema", "visual_grounding_diagnostics_v1")
    diagnostics["diagnostic_mode"] = diagnostic_mode
    diagnostics.setdefault("private_truth_included", False)
    copied["diagnostics"] = diagnostics
    return validate_visual_grounding_response(copied)


def _real_adapter_failure_response(
    *,
    pipeline_id: str,
    stage: str,
    producer_id: str,
    model_id: str,
    reason: str,
    message: str,
    latency_ms: int,
    diagnostic_mode: str,
    required_adapter: dict[str, Any] | None = None,
    stage_metadata: dict[str, Any] | None = None,
    diagnostics_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = {
        "schema": "visual_grounding_diagnostics_v1",
        "diagnostic_mode": diagnostic_mode,
        "required_adapters": [required_adapter] if required_adapter is not None else [],
        "raw_proposals": [],
        "rejected_proposals": [],
        "private_truth_included": False,
    }
    if diagnostics_extra:
        diagnostics.update(diagnostics_extra)
    stage_row = {
        "stage": stage,
        "producer_id": producer_id,
        "model_id": model_id,
        "version": "real-sidecar-adapter-v1",
        "status": reason,
        "latency_ms": latency_ms,
    }
    if stage_metadata:
        stage_row.update(stage_metadata)
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "failed",
        "pipeline": {
            "pipeline_id": pipeline_id,
            "stages": [stage_row],
        },
        "candidates": [],
        "error": {
            "reason": reason,
            "message": message,
        },
        "diagnostics": diagnostics,
    }
    return validate_visual_grounding_response(response)


def _normalized_xyxy_to_xywh(
    value: Any,
    *,
    width: int,
    height: int,
) -> list[float] | None:
    numbers = [_float_or_none(item) for item in _vector(value)[:4]]
    if len(numbers) != 4 or any(item is None for item in numbers):
        return None
    x1, y1, x2, y2 = [float(item) for item in numbers]
    x1, x2 = sorted((_clamp_float(x1, 0.0, float(width)), _clamp_float(x2, 0.0, float(width))))
    y1, y2 = sorted(
        (
            _clamp_float(y1, 0.0, float(height)),
            _clamp_float(y2, 0.0, float(height)),
        )
    )
    box_width = max(0.0, x2 - x1)
    box_height = max(0.0, y2 - y1)
    if box_width <= 0.0 or box_height <= 0.0 or width <= 0 or height <= 0:
        return None
    return [
        round(x1 / width, 6),
        round(y1 / height, 6),
        round(box_width / width, 6),
        round(box_height / height, 6),
    ]


def _destination_hint(payload: dict[str, Any], category: str) -> dict[str, Any]:
    preferences = _destination_preferences(category)
    if not preferences:
        return {}
    public_map_hints = payload.get("public_map_hints") or {}
    for fixture in public_map_hints.get("fixture_hints") or []:
        searchable = " ".join(
            [
                str(fixture.get("fixture_id") or ""),
                str(fixture.get("category") or ""),
                str(fixture.get("name") or ""),
                " ".join(str(item) for item in fixture.get("affordances") or []),
            ]
        ).lower()
        if any(preference in searchable for preference in preferences):
            return {
                "candidate_fixture_id": str(fixture.get("fixture_id") or ""),
                "confidence": 0.45,
                "basis": "sidecar_public_fixture_affordance_hint",
            }
    return {}


def _destination_preferences(category: str) -> tuple[str, ...]:
    category_norm = _norm(category)
    if category_norm in {"dish", "cup", "mug", "plate", "bowl", "utensil"}:
        return ("sink", "countertop")
    if category_norm in {"food", "apple", "bread", "potato", "fruit", "vegetable"}:
        return ("fridge", "refrigerator")
    if category_norm in {"book", "paper", "magazine", "newspaper"}:
        return ("shelf", "bookshelf", "desk")
    if category_norm in {"linen", "towel", "cloth", "blanket", "clothing"}:
        return ("hamper", "laundry")
    if category_norm in {"toy", "ball", "plush", "teddy"}:
        return ("toy", "bin", "shelf")
    if category_norm in {"remotecontrol", "remote", "electronics", "phone"}:
        return ("tv", "stand", "desk")
    if category_norm in {"pillow", "cushion"}:
        return ("bed", "sofa")
    return ()


def _category_from_model_label(raw_label: Any, category_hints: list[str]) -> str:
    if isinstance(raw_label, (int, float)):
        index = int(raw_label)
        if 0 <= index < len(category_hints):
            return category_hints[index]
    label = str(raw_label or "").strip()
    if not label:
        return category_hints[0] if category_hints else "object"
    label_norm = _norm(label.removeprefix("a ").removeprefix("an "))
    for hint in category_hints:
        hint_norm = _norm(hint)
        if hint_norm and (hint_norm == label_norm or hint_norm in label_norm):
            return hint
    return label.replace("a ", "", 1).replace("an ", "", 1) or "object"


def _category_from_yolo_class(
    *,
    class_id: int,
    names: Any,
    category_hints: list[str],
) -> str:
    if isinstance(names, dict) and class_id in names:
        return str(names[class_id])
    if isinstance(names, list) and 0 <= class_id < len(names):
        return str(names[class_id])
    if 0 <= class_id < len(category_hints):
        return category_hints[class_id]
    return category_hints[0] if category_hints else "object"


def _top_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_candidates = _int_env(
        "VISUAL_GROUNDING_MAX_CANDIDATES",
        8,
        minimum=1,
    )
    return sorted(
        candidates,
        key=lambda item: -float(item.get("confidence") or 0.0),
    )[:max_candidates]


def _rows(value: Any) -> list[list[Any]]:
    raw = _as_list(value)
    if not raw:
        return []
    if isinstance(raw[0], (list, tuple)):
        return [list(item) for item in raw]
    return [raw]


def _vector(value: Any) -> list[Any]:
    raw = _as_list(value)
    if raw and isinstance(raw[0], (list, tuple)):
        return [item[0] if item else None for item in raw]
    return raw


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return value
    return [value]


def _value_at(values: list[Any], index: int, *, default: Any) -> Any:
    return values[index] if index < len(values) else default


def _float_at(values: list[Any], index: int, *, default: float) -> float:
    return _float_or_none(_value_at(values, index, default=default)) or default


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
