from __future__ import annotations

import os
import time
from typing import Any

from roboclaws.household.visual_grounding_sidecar.adapter_candidates import (
    _yolo_candidates_from_model,
    _yolo_predict_kwargs,
    _yolo_prompt_labels,
)
from roboclaws.household.visual_grounding_sidecar.adapter_contracts import (
    ADAPTER_SPECS,
    _required_adapter_record,
)
from roboclaws.household.visual_grounding_sidecar.adapter_errors import (
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
    _load_yolo_model,
    _request_model_id,
    _request_runtime_parameters,
    _set_yolo_classes_if_needed,
)


def yolo_real_response(
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
