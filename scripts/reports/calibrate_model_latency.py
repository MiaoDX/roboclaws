#!/usr/bin/env python3
"""Build a diagnostic model-latency calibration packet from sanitized call rows."""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from roboclaws.core.json_sources import read_jsonl_objects
from roboclaws.core.live_performance import MODEL_CALL_METRIC_SCHEMA

CALIBRATION_SCHEMA = "roboclaws_model_latency_calibration_v1"
MIN_HOLDOUT_R2_FOR_STRONG_NORMALIZED_CLAIM = 0.20
FEATURES = (
    ("intercept_s", "intercept"),
    ("uncached_input_s_per_token", "uncached_input_tokens"),
    ("cached_input_s_per_token", "cached_input_tokens"),
    ("output_s_per_token", "output_tokens"),
    ("reasoning_s_per_token", "reasoning_tokens"),
    ("image_s_per_unit", "image_units"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit a diagnostic roboclaws_model_latency_calibration_v1 packet from "
            "sanitized model_call_metrics.jsonl files or run directories."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("paths", type=Path, nargs="+", help="model_call_metrics.jsonl or run dirs")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dataset-name", default="model-call-metrics")
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--min-group-samples", type=int, default=20)
    parser.add_argument(
        "--validation-path",
        "--holdout-path",
        dest="validation_paths",
        type=Path,
        nargs="+",
        action="extend",
        default=[],
        help=(
            "Optional independent model_call_metrics.jsonl files or run dirs used only for "
            "holdout/cross-run validation statistics."
        ),
    )
    parser.add_argument("--min-validation-samples", type=int, default=5)
    parser.add_argument("--min-group-validation-samples", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_calibration_packet(
        args.paths,
        dataset_name=args.dataset_name,
        min_samples=args.min_samples,
        min_group_samples=args.min_group_samples,
        validation_paths=args.validation_paths,
        min_validation_samples=args.min_validation_samples,
        min_group_validation_samples=args.min_group_validation_samples,
    )
    payload = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"calibration: {args.output}")
    else:
        print(payload, end="")
    return 0 if packet["available"] else 1


def build_calibration_packet(
    paths: list[Path],
    *,
    dataset_name: str,
    min_samples: int = 20,
    min_group_samples: int = 20,
    validation_paths: list[Path] | None = None,
    min_validation_samples: int = 5,
    min_group_validation_samples: int = 5,
) -> dict[str, Any]:
    sources = [_metrics_path(path) for path in paths]
    raw_rows = [row for source in sources for row in _read_jsonl(source)]
    rows = [_model_row(row, source="") for row in raw_rows]
    valid_rows = [row for row in rows if row is not None]
    validation_sources = [_metrics_path(path) for path in validation_paths or []]
    raw_validation_rows = [row for source in validation_sources for row in _read_jsonl(source)]
    validation_rows = [_model_row(row, source="") for row in raw_validation_rows]
    valid_validation_rows = [row for row in validation_rows if row is not None]
    validation_summary = _validation_summary(
        valid_validation_rows,
        coefficients=None,
        min_samples=min_validation_samples,
        sources=validation_sources,
        total_row_count=len(raw_validation_rows),
        rejected_row_count=len(raw_validation_rows) - len(valid_validation_rows),
    )
    limitations = _packet_limitations(validation_summary)
    if len(valid_rows) < min_samples:
        limitations.add("insufficient_calibration_samples")
        return {
            "schema": CALIBRATION_SCHEMA,
            "available": False,
            "dataset_name": dataset_name,
            "generated_at": _now_iso(),
            "sample_count": len(valid_rows),
            "total_row_count": len(raw_rows),
            "rejected_row_count": len(raw_rows) - len(valid_rows),
            "limitations": sorted(limitations),
            "sources": [str(source) for source in sources],
            "validation": validation_summary,
            "validation_sources": [str(source) for source in validation_sources],
        }

    fit = _fit_rows(valid_rows)
    validation_summary = _validation_summary(
        valid_validation_rows,
        coefficients=fit["coefficients"],
        min_samples=min_validation_samples,
        sources=validation_sources,
        total_row_count=len(raw_validation_rows),
        rejected_row_count=len(raw_validation_rows) - len(valid_validation_rows),
    )
    limitations = _packet_limitations(validation_summary)
    validation_groups = _group_rows(valid_validation_rows)
    coefficient_sets = []
    for identity, group_rows in sorted(_group_rows(valid_rows).items()):
        if len(group_rows) < min_group_samples:
            continue
        group_fit = _fit_rows(group_rows)
        group_validation = _validation_summary(
            validation_groups.get(identity, []),
            coefficients=group_fit["coefficients"],
            min_samples=min_group_validation_samples,
            sources=validation_sources,
            total_row_count=len(raw_validation_rows),
            rejected_row_count=len(raw_validation_rows) - len(valid_validation_rows),
        )
        coefficient_sets.append(
            {
                **dict(identity),
                "sample_count": len(group_rows),
                "coefficients": group_fit["coefficients"],
                "fit": group_fit["fit"],
                "validation": group_validation,
                "limitations": sorted(_packet_limitations(group_validation)),
            }
        )

    return {
        "schema": CALIBRATION_SCHEMA,
        "available": True,
        "dataset_name": dataset_name,
        "generated_at": _now_iso(),
        "sample_count": len(valid_rows),
        "total_row_count": len(raw_rows),
        "rejected_row_count": len(raw_rows) - len(valid_rows),
        "limitations": sorted(limitations),
        "coefficients": fit["coefficients"],
        "coefficient_sets": coefficient_sets,
        "fit": fit["fit"],
        "sources": [str(source) for source in sources],
        "validation": validation_summary,
        "validation_sources": [str(source) for source in validation_sources],
    }


def _metrics_path(path: Path) -> Path:
    return path / "model_call_metrics.jsonl" if path.is_dir() else path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return read_jsonl_objects(path, label="model-call metrics")


def _model_row(row: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    if row.get("schema") != MODEL_CALL_METRIC_SCHEMA:
        return None
    if str(row.get("status") or "success") != "success":
        return None
    duration = _float_or_none(row.get("duration_s"))
    if duration is None or duration < 0:
        return None
    required = {
        "uncached_input_tokens": _float_or_none(row.get("uncached_input_tokens")),
        "cached_input_tokens": _float_or_none(row.get("cached_input_tokens")),
        "output_tokens": _float_or_none(row.get("output_tokens")),
        "reasoning_tokens": _float_or_none(row.get("reasoning_tokens")),
    }
    if any(value is None for value in required.values()):
        return None
    image_pixels = _float_or_none(row.get("image_input_pixels")) or 0.0
    image_count = _float_or_none(row.get("image_input_count")) or 0.0
    return {
        "duration_s": duration,
        "intercept": 1.0,
        **required,
        "image_units": image_pixels if image_pixels > 0 else image_count,
        "identity": {
            "agent_engine": str(row.get("agent_engine") or ""),
            "provider_profile": str(row.get("provider_profile") or ""),
            "model": str(row.get("model") or ""),
            "wire_api": str(row.get("wire_api") or ""),
        },
        "source": source,
    }


def _fit_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [name for name, _ in FEATURES if name == "intercept_s" or _has_signal(rows, name)]
    removed: list[str] = []
    coefficients = {name: 0.0 for name, _ in FEATURES}
    for _ in range(len(FEATURES) + 1):
        fitted = _least_squares(rows, active)
        if fitted is None:
            removed.extend(active)
            active = []
            break
        negative = [item for item in fitted.items() if item[1] < -1e-12]
        if not negative:
            coefficients.update({key: max(0.0, value) for key, value in fitted.items()})
            break
        worst_key, _ = min(negative, key=lambda item: item[1])
        active.remove(worst_key)
        removed.append(worst_key)
    predictions = [_predict(row, coefficients) for row in rows]
    actuals = [float(row["duration_s"]) for row in rows]
    fit = {
        "method": "ordinary_least_squares_nonnegative_active_set_v1",
        "feature_names": [name for name, _ in FEATURES],
        "active_features": active,
        "removed_features": removed,
        "error_stats": _error_stats(actuals, predictions),
    }
    return {
        "coefficients": {key: _round(value, digits=9) for key, value in coefficients.items()},
        "fit": fit,
    }


def _validation_summary(
    rows: list[dict[str, Any]],
    *,
    coefficients: dict[str, float] | None,
    min_samples: int,
    sources: list[Path],
    total_row_count: int,
    rejected_row_count: int,
) -> dict[str, Any]:
    base = {
        "mode": "holdout_paths" if sources else "not_requested",
        "available": False,
        "sample_count": len(rows),
        "total_row_count": total_row_count,
        "rejected_row_count": rejected_row_count,
        "min_samples": min_samples,
        "sources": [str(source) for source in sources],
    }
    if not sources:
        return {
            **base,
            "limitations": ["holdout_validation_not_requested"],
        }
    if len(rows) < min_samples:
        return {
            **base,
            "limitations": ["insufficient_holdout_validation_samples"],
        }
    if not coefficients:
        return {
            **base,
            "limitations": ["calibration_coefficients_unavailable"],
        }
    predictions = [_predict(row, coefficients) for row in rows]
    actuals = [float(row["duration_s"]) for row in rows]
    return {
        **base,
        "available": True,
        "error_stats": _error_stats(actuals, predictions),
        "limitations": [],
    }


def _packet_limitations(validation_summary: dict[str, Any]) -> set[str]:
    limitations = {"not_repo_default_calibration"}
    if validation_summary.get("available") is not True:
        limitations.add("diagnostic_same_dataset_fit_not_holdout_validated")
        limitations.update(
            str(item) for item in validation_summary.get("limitations") or [] if str(item)
        )
        return limitations
    error_stats = validation_summary.get("error_stats")
    validation_r2 = _float_or_none(error_stats.get("r2") if isinstance(error_stats, dict) else None)
    if validation_r2 is None or validation_r2 < MIN_HOLDOUT_R2_FOR_STRONG_NORMALIZED_CLAIM:
        limitations.add("holdout_validation_low_explanatory_power")
    return limitations


def _has_signal(rows: list[dict[str, Any]], coefficient_name: str) -> bool:
    feature_name = dict(FEATURES)[coefficient_name]
    return any(abs(float(row.get(feature_name) or 0.0)) > 0 for row in rows)


def _least_squares(rows: list[dict[str, Any]], active: list[str]) -> dict[str, float] | None:
    if not active:
        return {}
    scales = {
        key: max(1.0, max(abs(float(row.get(dict(FEATURES)[key]) or 0.0)) for row in rows))
        for key in active
    }
    matrix = [[0.0 for _ in active] for _ in active]
    rhs = [0.0 for _ in active]
    for row in rows:
        x = [float(row.get(dict(FEATURES)[key]) or 0.0) / scales[key] for key in active]
        y = float(row["duration_s"])
        for i, left in enumerate(x):
            rhs[i] += left * y
            for j, right in enumerate(x):
                matrix[i][j] += left * right
    for i in range(len(active)):
        matrix[i][i] += 1e-9
    solution = _solve_linear_system(matrix, rhs)
    if solution is None:
        return None
    return {key: solution[index] / scales[key] for index, key in enumerate(active)}


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    size = len(rhs)
    augmented = [row[:] + [rhs[index]] for index, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            return None
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        pivot_value = augmented[col][col]
        for item in range(col, size + 1):
            augmented[col][item] /= pivot_value
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0:
                continue
            for item in range(col, size + 1):
                augmented[row][item] -= factor * augmented[col][item]
    return [augmented[row][size] for row in range(size)]


def _predict(row: dict[str, Any], coefficients: dict[str, float]) -> float:
    total = 0.0
    for coefficient_name, feature_name in FEATURES:
        total += coefficients.get(coefficient_name, 0.0) * float(row.get(feature_name) or 0.0)
    return max(0.0, total)


def _error_stats(actuals: list[float], predictions: list[float]) -> dict[str, Any]:
    errors = [prediction - actual for actual, prediction in zip(actuals, predictions, strict=True)]
    absolute = [abs(error) for error in errors]
    squared = [error * error for error in errors]
    nonzero_actual = [abs(actual) for actual in actuals if actual != 0]
    percentage = [
        abs(error) / abs(actual)
        for actual, error in zip(actuals, errors, strict=True)
        if actual != 0
    ]
    mean_actual = sum(actuals) / len(actuals) if actuals else 0.0
    total_var = sum((actual - mean_actual) ** 2 for actual in actuals)
    residual_var = sum(squared)
    return {
        "sample_count": len(actuals),
        "mae_s": _round(sum(absolute) / len(absolute)),
        "rmse_s": _round(math.sqrt(sum(squared) / len(squared))),
        "mean_error_s": _round(sum(errors) / len(errors)),
        "median_abs_error_s": _round(median(absolute)),
        "p90_abs_error_s": _round(_percentile(absolute, 0.90)),
        "p95_abs_error_s": _round(_percentile(absolute, 0.95)),
        "max_abs_error_s": _round(max(absolute)),
        "mape": _round(sum(percentage) / len(percentage)) if nonzero_actual else None,
        "r2": _round(1.0 - residual_var / total_var) if total_var else None,
        "residual_p05_s": _round(_percentile(errors, 0.05)),
        "residual_p50_s": _round(_percentile(errors, 0.50)),
        "residual_p95_s": _round(_percentile(errors, 0.95)),
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = quantile * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _group_rows(
    rows: list[dict[str, Any]],
) -> dict[tuple[tuple[str, str], ...], list[dict[str, Any]]]:
    groups: dict[tuple[tuple[str, str], ...], list[dict[str, Any]]] = {}
    for row in rows:
        identity = tuple(sorted(dict(row["identity"]).items()))
        groups.setdefault(identity, []).append(row)
    return groups


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float, *, digits: int = 6) -> float:
    return round(float(value), digits)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
