from __future__ import annotations

from typing import Any

from roboclaws.household.visual_grounding_sidecar.adapter_contracts import (
    ADAPTER_MODE_REAL,
    adapter_unavailable_response,
    effective_pipeline_id,
    pipeline_mismatch_response,
    pipeline_request_is_allowed,
    request_pipeline_id,
)


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
        from roboclaws.household.visual_grounding_sidecar import adapter_grounding_dino

        return adapter_grounding_dino.grounding_dino_real_response(
            payload=payload,
            pipeline_id=pipeline_id,
            latency_ms=latency_ms,
        )
    if producer_id in {"yoloe", "yolo-world"}:
        from roboclaws.household.visual_grounding_sidecar import adapter_yolo

        return adapter_yolo.yolo_real_response(
            payload=payload,
            pipeline_id=pipeline_id,
            producer_id=producer_id,
            latency_ms=latency_ms,
        )
    if producer_id == "omdet-turbo":
        from roboclaws.household.visual_grounding_sidecar import adapter_omdet

        return adapter_omdet.omdet_turbo_real_response(
            payload=payload,
            pipeline_id=pipeline_id,
            latency_ms=latency_ms,
        )
    return None


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
