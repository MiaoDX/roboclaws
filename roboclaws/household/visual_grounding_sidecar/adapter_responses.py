from __future__ import annotations

from typing import Any

from roboclaws.household.visual_grounding import (
    VISUAL_GROUNDING_RESPONSE_SCHEMA,
    validate_visual_grounding_response,
)


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
