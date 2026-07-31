"""Explicit calibration policy for normalized live model timing."""

from __future__ import annotations

import math
from typing import Any


def normalized_model_timing(
    timing: dict[str, Any],
    model_work: dict[str, Any],
    *,
    calibration: dict[str, Any] | None = None,
    run_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    estimate = _estimate_model_work_s(model_work, calibration, run_identity)
    observed = _float(calibration_value=timing.get("observed_model_api_s"))
    residual = None
    if observed is not None and estimate["estimated_s"] is not None:
        residual = round(observed - float(estimate["estimated_s"]), 3)
    broader_residual = None
    if observed is None:
        runner_agent = _float(calibration_value=timing.get("runner_agent_s"))
        mcp_elapsed = _float(calibration_value=timing.get("mcp_elapsed_s"))
        if runner_agent is not None and mcp_elapsed is not None:
            broader_residual = round(max(0.0, runner_agent - mcp_elapsed), 3)
    return {
        "estimated_model_work_s": estimate,
        "model_latency_residual_s": residual,
        "model_or_sdk_residual_s": broader_residual,
        "model_work_available": bool(model_work.get("available")),
    }


def _estimate_model_work_s(
    model_work: dict[str, Any],
    calibration: dict[str, Any] | None,
    run_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    calibration = _dict(calibration)
    if not calibration:
        return _unavailable()
    limitations = [str(item) for item in calibration.get("limitations") or [] if str(item)]
    if calibration.get("schema") != "roboclaws_model_latency_calibration_v1":
        return _unavailable(
            source=_source(calibration), limitations=["calibration_schema_unrecognized"]
        )
    if calibration.get("available") is not True:
        return _unavailable(
            calibration=calibration,
            source=_source(calibration),
            limitations={"calibration_unavailable", *limitations},
        )
    selection = _select_coefficients(calibration, run_identity)
    coefficients = selection["coefficients"]
    if not coefficients:
        return _unavailable(
            calibration=calibration,
            source=_source(calibration),
            limitations={
                "calibration_coefficients_unavailable",
                *limitations,
                *selection["limitations"],
            },
        )
    values, missing = _coefficient_values(model_work, coefficients)
    image_units = _image_units(model_work)
    image_coefficient = _first_float(
        coefficients, "image_input_s_per_unit", "image_s_per_unit", "image_input_s_per_pixel"
    )
    if image_units > 0 and image_coefficient is None:
        missing.append("image_s_per_unit")
        image_coefficient = 0.0
    if missing or not model_work.get("available"):
        return _unavailable(
            calibration=calibration,
            source=_source(calibration),
            limitations={
                *limitations,
                *selection["limitations"],
                *(f"{item}_unavailable" for item in missing),
                *([] if model_work.get("available") else ["model_work_unavailable"]),
            },
        )
    estimated = (
        values["intercept_s"]
        + (_integer(model_work.get("total_uncached_input_tokens")) or 0)
        * values["uncached_input_s_per_token"]
        + (_integer(model_work.get("total_cached_input_tokens")) or 0)
        * values["cached_input_s_per_token"]
        + (_integer(model_work.get("total_output_tokens")) or 0) * values["output_s_per_token"]
        + (_integer(model_work.get("total_reasoning_tokens")) or 0)
        * values["reasoning_s_per_token"]
        + image_units * (image_coefficient or 0.0)
    )
    return {
        "available": True,
        "source": _source(calibration),
        "estimated_s": round(estimated, 3),
        "limitations": sorted({*limitations, *selection["limitations"]}),
        "policy": "calibrated_explicit_packet_required_for_normalized_model_time",
        "sample_count": _integer(calibration.get("sample_count")),
        "total_row_count": _integer(calibration.get("total_row_count")),
        "coefficient_scope": selection["scope"],
    }


def _unavailable(
    *,
    source: str = "unavailable",
    limitations: set[str] | list[str] | None = None,
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packet = {
        "available": False,
        "source": source,
        "estimated_s": None,
        "limitations": sorted({str(item) for item in limitations if str(item)})
        if limitations is not None
        else ["calibration_coefficients_unavailable"],
        "policy": (
            "No authoritative repo-default coefficients are committed for v1. "
            "Use calibrate_model_latency.py with a named dataset before making "
            "normalized speed claims."
        ),
    }
    if calibration is not None:
        packet["sample_count"] = _integer(calibration.get("sample_count"))
        packet["total_row_count"] = _integer(calibration.get("total_row_count"))
    return packet


def _coefficient_values(
    model_work: dict[str, Any], coefficients: dict[str, Any]
) -> tuple[dict[str, float], list[str]]:
    values = {"intercept_s": _float(calibration_value=coefficients.get("intercept_s")) or 0.0}
    missing: list[str] = []
    for coefficient_key, work_key in {
        "uncached_input_s_per_token": "total_uncached_input_tokens",
        "cached_input_s_per_token": "total_cached_input_tokens",
        "output_s_per_token": "total_output_tokens",
        "reasoning_s_per_token": "total_reasoning_tokens",
    }.items():
        coefficient = _float(calibration_value=coefficients.get(coefficient_key))
        work = _integer(model_work.get(work_key))
        if work is None:
            if coefficient not in {None, 0.0}:
                missing.append(work_key)
            values[coefficient_key] = 0.0
        elif coefficient is None:
            if work > 0:
                missing.append(coefficient_key)
            values[coefficient_key] = 0.0
        else:
            values[coefficient_key] = coefficient
    return values, missing


def _select_coefficients(
    calibration: dict[str, Any], identity: dict[str, Any] | None
) -> dict[str, Any]:
    sets = calibration.get("coefficient_sets")
    if not isinstance(sets, list):
        return {
            "coefficients": _dict(calibration.get("coefficients")),
            "limitations": [],
            "scope": {"type": "global"},
        }
    identity = _dict(identity)
    ranked: list[tuple[int, dict[str, Any]]] = []
    keys = ("agent_engine", "provider_profile", "model", "wire_api", "evidence_lane")
    for item in sets:
        if not isinstance(item, dict):
            continue
        expected = {key: str(item.get(key) or "") for key in keys}
        if any(
            value and identity.get(key) and value != str(identity.get(key))
            for key, value in expected.items()
        ):
            continue
        ranked.append((sum(bool(value) for value in expected.values()), item))
    if not ranked:
        return {
            "coefficients": {},
            "limitations": ["calibration_no_matching_coefficient_set"],
            "scope": {},
        }
    best = max(ranked, key=lambda pair: pair[0])[1]
    scope = {key: best.get(key) for key in keys if best.get(key)} or {
        "type": "matched_coefficient_set"
    }
    return {
        "coefficients": _dict(best.get("coefficients")),
        "limitations": [str(item) for item in best.get("limitations") or [] if str(item)],
        "scope": scope,
    }


def _source(calibration: dict[str, Any]) -> str:
    return str(calibration.get("source_path") or "calibration_packet")


def _image_units(model_work: dict[str, Any]) -> int:
    return (
        _integer(model_work.get("image_input_pixels"))
        or _integer(model_work.get("image_input_count"))
        or 0
    )


def _first_float(container: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float(calibration_value=container.get(key))
        if value is not None:
            return value
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(*, calibration_value: Any) -> float | None:
    try:
        result = float(calibration_value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
