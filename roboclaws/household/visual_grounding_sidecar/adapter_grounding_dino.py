from __future__ import annotations

import os
import time
from typing import Any

from roboclaws.household.visual_grounding_sidecar.adapter_candidates import (
    _grounding_dino_candidates_from_result,
)
from roboclaws.household.visual_grounding_sidecar.adapter_contracts import (
    ADAPTER_SPECS,
    DEFAULT_GROUNDING_DINO_BOX_THRESHOLD,
    DEFAULT_GROUNDING_DINO_TEXT_THRESHOLD,
    _required_adapter_record,
)
from roboclaws.household.visual_grounding_sidecar.adapter_errors import (
    VisualGroundingDeviceError,
    VisualGroundingRuntimeParameterError,
)
from roboclaws.household.visual_grounding_sidecar.adapter_responses import (
    _real_adapter_failure_response,
    _real_adapter_ok_response,
)
from roboclaws.household.visual_grounding_sidecar.adapter_runtime import (
    _category_hints,
    _decode_request_image,
    _elapsed_ms,
    _label_prompt,
    _load_grounding_dino,
    _request_model_id,
    _request_runtime_parameters,
    _runtime_float_param,
)


def grounding_dino_real_response(
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
