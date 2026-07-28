"""Recommended Runtime Map Prior Snapshot selection contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.map_build_reports import (
    discover_eval_results_paths,
    map_build_matrix_summary_from_bundles,
)
from roboclaws.evals.models import MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE
from roboclaws.maps.runtime_prior_snapshot import (
    PRIVATE_TRUTH_KEYS,
    RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
)

RUNTIME_PRIOR_SELECTION_MANIFEST_SCHEMA = "runtime_map_prior_selection_manifest_v1"
RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA = "runtime_map_prior_selection_report_v1"
RUNTIME_PRIOR_CATALOG_SCHEMA = "runtime_map_prior_catalog_v1"

COMPATIBLE = "compatible"
ADVISORY_REGRADE = "advisory_regrade"
STALE = "stale"
BLOCKING_STALE = "blocking_stale"
ACCEPTED_STALENESS = frozenset({COMPATIBLE, ADVISORY_REGRADE, STALE})

_DEFAULT_MIN_PUBLIC_SEMANTIC_ANCHORS = 1
_DEFAULT_MIN_STABLE_SEMANTIC_ANCHOR_CATEGORIES = 1


@dataclass(frozen=True)
class RuntimePriorCatalogKey:
    """Stable scene/map identity for reusable prior catalog entries."""

    world: str
    backend: str
    source_map_identity: str
    scene_identity: str

    @property
    def id(self) -> str:
        return "::".join((self.world, self.backend, self.source_map_identity, self.scene_identity))

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RuntimePriorCatalogKey":
        forbidden_keys = {
            "scenario_setup",
            "relocation_seed",
            "generated_mess_set",
            "relocated_object_ids",
            "hidden_target_list",
            "acceptable_destinations",
        }
        present = sorted(key for key in forbidden_keys if key in payload)
        if present:
            raise ValueError(
                f"runtime prior catalog key contains private cleanup fields: {present}"
            )
        return cls(
            world=_required_string(payload, "world"),
            backend=_required_string(payload, "backend"),
            source_map_identity=_required_string(payload, "source_map_identity"),
            scene_identity=_required_string(payload, "scene_identity"),
        )

    def to_payload(self) -> dict[str, str]:
        return asdict(self)


def write_runtime_prior_selection(
    *,
    manifest_path: Path,
    eval_results_paths: list[Path],
    output_dir: Path,
) -> dict[str, str]:
    """Select a recommended Runtime Map Prior from eval results and write artifacts."""

    manifest = load_runtime_prior_selection_manifest(manifest_path)
    bundles = [_load_eval_results_bundle(path) for path in eval_results_paths]
    summary = map_build_matrix_summary_from_bundles(bundles)
    report = select_recommended_runtime_prior(manifest=manifest, matrix_summary=summary)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "runtime_map_prior_selection_report.json"
    catalog_path = output_dir / "runtime_map_prior_catalog.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    catalog = runtime_prior_catalog_from_reports([report])
    catalog_path.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"report": str(report_path), "catalog": str(catalog_path)}


def select_recommended_runtime_prior(
    *,
    manifest: dict[str, Any],
    matrix_summary: dict[str, Any],
) -> dict[str, Any]:
    """Return a selector report for one manifest catalog key."""

    _require_schema(manifest, RUNTIME_PRIOR_SELECTION_MANIFEST_SCHEMA)
    catalog_key = RuntimePriorCatalogKey.from_mapping(_required_mapping(manifest, "catalog_key"))
    thresholds = _required_mapping(manifest, "hard_gate_thresholds")
    source_map_contract = _required_mapping(manifest, "source_map_contract")
    current_contract = _required_mapping(manifest, "current_contract")
    staleness = classify_runtime_prior_compatibility(
        entry_contract=source_map_contract,
        current_contract=current_contract,
        prior_path=str(manifest.get("expected_prior_path") or ""),
    )
    rows = [_candidate_row(manifest, row) for row in _quality_rows(matrix_summary)]
    downstream_rows = _downstream_rows(matrix_summary)
    candidate_reports = [
        _candidate_report(
            candidate,
            downstream_rows=downstream_rows,
            thresholds=thresholds,
            staleness=staleness,
        )
        for candidate in rows
    ]
    accepted = [candidate for candidate in candidate_reports if candidate["status"] == "accepted"]
    ranked = sorted(accepted, key=_ranking_key)
    selected = ranked[0] if ranked else None
    catalog_entry = (
        _catalog_entry_from_selected(
            selected,
            catalog_key=catalog_key,
            source_map_contract=source_map_contract,
            current_contract=current_contract,
            staleness=staleness,
        )
        if selected is not None
        else None
    )
    return {
        "schema": RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA,
        "catalog_key": catalog_key.to_payload(),
        "compatibility": staleness,
        "selected_candidate_id": str(selected.get("candidate_id") or "") if selected else "",
        "selected_prior_path": str(selected.get("runtime_map_prior") or "") if selected else "",
        "status": "accepted" if selected is not None else "no_accepted_candidate",
        "candidates": candidate_reports,
        "catalog_entry": catalog_entry,
    }


def runtime_prior_catalog_from_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a console-loadable catalog from selector reports."""

    entries = []
    for report in reports:
        _require_schema(report, RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA)
        entry = report.get("catalog_entry")
        if isinstance(entry, dict) and entry.get("status") == "accepted":
            entries.append(dict(entry))
    return {
        "schema": RUNTIME_PRIOR_CATALOG_SCHEMA,
        "entries": sorted(entries, key=lambda item: str(item.get("id") or "")),
    }


def load_runtime_prior_catalog(path: Path) -> tuple[dict[str, Any], ...]:
    """Read a recommended-prior catalog file."""

    payload = read_json_object(path, label="runtime prior catalog")
    _require_schema(payload, RUNTIME_PRIOR_CATALOG_SCHEMA)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("runtime prior catalog entries must be a list")
    normalized = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"runtime prior catalog entry {index} must be an object")
        normalized.append(_normalize_catalog_entry(entry))
    return tuple(normalized)


def load_runtime_prior_selection_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json_object(path, label="runtime prior selection manifest")
    _require_schema(manifest, RUNTIME_PRIOR_SELECTION_MANIFEST_SCHEMA)
    catalog_key = RuntimePriorCatalogKey.from_mapping(_required_mapping(manifest, "catalog_key"))
    manifest = dict(manifest)
    manifest["catalog_key"] = catalog_key.to_payload()
    _required_mapping(manifest, "source_map_contract")
    _required_mapping(manifest, "current_contract")
    _required_mapping(manifest, "hard_gate_thresholds")
    candidates = manifest.get("candidates")
    if candidates is not None:
        candidates_valid = isinstance(candidates, list) and all(
            isinstance(item, dict) for item in candidates
        )
        if not candidates_valid:
            raise ValueError(
                "runtime prior selection manifest candidates must be a list of objects"
            )
    return manifest


def discover_runtime_prior_eval_results(raw_refs: str) -> list[Path]:
    return discover_eval_results_paths(raw_refs)


def classify_runtime_prior_compatibility(
    *,
    entry_contract: dict[str, Any],
    current_contract: dict[str, Any],
    prior_path: str = "",
) -> str:
    """Classify catalog prior staleness against current scene/map contracts."""

    if prior_path and not Path(prior_path).is_file():
        return BLOCKING_STALE
    for key in ("world", "backend", "source_map_identity"):
        old = str(entry_contract.get(key) or "")
        new = str(current_contract.get(key) or "")
        if old and new and old != new:
            return BLOCKING_STALE
    for key in ("runtime_map_prior_schema", "public_map_contract_version"):
        old = str(entry_contract.get(key) or "")
        new = str(current_contract.get(key) or "")
        if old and new and old != new:
            return STALE
    old_grader = str(entry_contract.get("grader_version") or "")
    new_grader = str(current_contract.get("grader_version") or "")
    if old_grader and new_grader and old_grader != new_grader:
        return ADVISORY_REGRADE
    return COMPATIBLE


def catalog_entry_auto_enables(entry: dict[str, Any]) -> bool:
    """Return whether the operator console may default to this catalog entry."""

    status = str(entry.get("status") or "")
    staleness = str(entry.get("staleness") or entry.get("compatibility") or "")
    path = str(entry.get("path") or "")
    return status == "accepted" and staleness in ACCEPTED_STALENESS and bool(path)


def _candidate_row(manifest: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    profile_key = [str(item) for item in row.get("profile_key") or ()]
    manifest_candidate = _manifest_candidate_for(manifest, row)
    runtime_map_prior = str(
        manifest_candidate.get("runtime_map_prior")
        or manifest_candidate.get("runtime_map_prior_snapshot")
        or row.get("artifacts", {}).get("runtime_map_prior_snapshot")
        or row.get("artifacts", {}).get("runtime_map_prior")
        or row.get("artifacts", {}).get("runtime_metric_map")
        or ""
    )
    return {
        **row,
        "candidate_id": str(
            manifest_candidate.get("candidate_id")
            or manifest_candidate.get("id")
            or "|".join(profile_key)
        ),
        "runtime_map_prior": runtime_map_prior,
        "source_map_identity": str(
            manifest_candidate.get("source_map_identity")
            or manifest.get("catalog_key", {}).get("source_map_identity")
            or ""
        ),
        "producer": dict(manifest_candidate.get("producer") or {}),
        "run_id": str(manifest_candidate.get("run_id") or row.get("sample_id") or ""),
        "artifact_schema_versions": dict(manifest_candidate.get("artifact_schema_versions") or {}),
        "usage": dict(manifest_candidate.get("usage") or {}),
    }


def _candidate_report(
    candidate: dict[str, Any],
    *,
    downstream_rows: list[dict[str, Any]],
    thresholds: dict[str, Any],
    staleness: str,
) -> dict[str, Any]:
    gates = _hard_gates(candidate, thresholds=thresholds, staleness=staleness)
    profile_key = [str(item) for item in candidate.get("profile_key") or ()]
    downstream = [
        row
        for row in downstream_rows
        if [str(item) for item in row.get("profile_key") or ()] == profile_key
    ]
    regression_gates = _downstream_regression_gates(downstream)
    gates.extend(regression_gates)
    accepted = all(gate["status"] == "passed" for gate in gates)
    utility = _downstream_utility(downstream)
    return {
        "candidate_id": candidate["candidate_id"],
        "status": "accepted" if accepted else "rejected",
        "runtime_map_prior": candidate["runtime_map_prior"],
        "profile_key": profile_key,
        "product_route": {
            "agent_engine": candidate.get("agent_engine", MISSING_UNAVAILABLE),
            "provider_profile": candidate.get("provider_profile", MISSING_UNAVAILABLE),
            "model": candidate.get("model", MISSING_UNAVAILABLE),
        },
        "producer": candidate["producer"],
        "run_id": candidate["run_id"],
        "source_map_identity": candidate["source_map_identity"],
        "artifact_schema_versions": candidate["artifact_schema_versions"],
        "usage": candidate["usage"],
        "hard_gates": gates,
        "utility": utility,
        "quality": {
            "public_semantic_anchor_count": candidate.get("public_semantic_anchor_count", 0),
            "stable_semantic_anchor_category_count": candidate.get(
                "stable_semantic_anchor_category_count",
                0,
            ),
            "sim_truth_fixture_category_recall": candidate.get(
                "sim_truth_fixture_category_recall",
                MISSING_UNAVAILABLE,
            ),
            "sim_truth_fixture_category_precision": candidate.get(
                "sim_truth_fixture_category_precision",
                MISSING_UNAVAILABLE,
            ),
            "sim_truth_best_view_waypoint_accuracy": candidate.get(
                "sim_truth_best_view_waypoint_accuracy",
                MISSING_UNAVAILABLE,
            ),
        },
        "cost_latency": {
            "wall_time_s": candidate.get("wall_time_s", MISSING_UNAVAILABLE),
            "tool_call_count": candidate.get("tool_call_count", MISSING_UNAVAILABLE),
            "model_attempt_count": candidate.get("model_attempt_count", MISSING_UNAVAILABLE),
        },
    }


def _hard_gates(
    candidate: dict[str, Any],
    *,
    thresholds: dict[str, Any],
    staleness: str,
) -> list[dict[str, str]]:
    gates = [
        _gate(
            "runtime_map_prior_schema_valid",
            _runtime_prior_path_schema_valid(str(candidate.get("runtime_map_prior") or "")),
            "Runtime Map Prior Snapshot schema is valid.",
        ),
        _gate(
            "source_map_not_mutated",
            candidate.get("source_map_not_mutated") is True,
            "Source map/Base Metric Map artifacts are not mutated.",
        ),
        _gate(
            "private_boundary_safe",
            candidate.get("private_truth_absent") is True
            and not _artifact_has_private_truth(str(candidate.get("runtime_map_prior") or "")),
            "Private scoring truth is absent from public prior artifacts.",
        ),
        _gate(
            "public_semantic_anchor_threshold",
            _number(candidate.get("public_semantic_anchor_count"))
            >= _number(
                thresholds.get("min_public_semantic_anchors"),
                default=_DEFAULT_MIN_PUBLIC_SEMANTIC_ANCHORS,
            ),
            "Public semantic anchors meet accepted threshold.",
        ),
        _gate(
            "stable_semantic_anchor_threshold",
            _number(candidate.get("stable_semantic_anchor_category_count"))
            >= _number(
                thresholds.get("min_stable_semantic_anchor_categories"),
                default=_DEFAULT_MIN_STABLE_SEMANTIC_ANCHOR_CATEGORIES,
            ),
            "Stable semantic-anchor categories meet accepted threshold.",
        ),
        _gate(
            "sim_truth_fixture_recall",
            _threshold_passed(
                candidate.get("sim_truth_fixture_category_recall"),
                thresholds.get("min_sim_truth_fixture_category_recall"),
            ),
            "SimOracle/grader-only fixture category recall passed.",
        ),
        _gate(
            "sim_truth_fixture_precision",
            _threshold_passed(
                candidate.get("sim_truth_fixture_category_precision"),
                thresholds.get("min_sim_truth_fixture_category_precision"),
            ),
            "SimOracle/grader-only fixture category precision passed.",
        ),
        _gate(
            "best_view_waypoint_accuracy",
            _threshold_passed(
                candidate.get("sim_truth_best_view_waypoint_accuracy"),
                thresholds.get("min_sim_truth_best_view_waypoint_accuracy"),
            ),
            "Best-view waypoint correctness passed.",
        ),
        _gate(
            "rgb_only_observation_pose_claims_absent",
            _number(candidate.get("rgb_only_object_pose_claim_count")) == 0,
            "RGB-only observations do not claim trusted object map-frame poses.",
        ),
        _gate(
            "catalog_entry_not_blocking_stale",
            staleness != BLOCKING_STALE,
            "Catalog compatibility is not blocking stale.",
        ),
    ]
    return gates


def _downstream_regression_gates(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not rows:
        return [_gate("downstream_utility_regression_absent", False, "No downstream rows matched.")]
    return [
        _gate(
            f"downstream_{row.get('task_family', 'task')}_no_regression",
            str(row.get("comparison_label") or "") in {"improved", "no_regression"},
            str(row.get("reason") or "Downstream prior-vs-no-prior comparison did not regress."),
        )
        for row in rows
    ]


def _downstream_utility(rows: list[dict[str, Any]]) -> dict[str, Any]:
    improved_rows = [row for row in rows if str(row.get("comparison_label") or "") == "improved"]
    stable_anchor_used = [
        row
        for row in rows
        if str(
            (row.get("fixture_focused_prior") or {}).get("prior_use_verdict")
            if isinstance(row.get("fixture_focused_prior"), dict)
            else ""
        )
        == "stable_anchor_used"
    ]
    total_tool_call_delta = sum(
        _number(
            (row.get("tool_deltas") or {}).get("tool_call_count")
            if isinstance(row.get("tool_deltas"), dict)
            else MISSING_UNAVAILABLE
        )
        for row in rows
    )
    return {
        "downstream_row_count": len(rows),
        "improved_row_count": len(improved_rows),
        "stable_anchor_used_count": len(stable_anchor_used),
        "total_tool_call_delta": total_tool_call_delta,
    }


def _catalog_entry_from_selected(
    selected: dict[str, Any],
    *,
    catalog_key: RuntimePriorCatalogKey,
    source_map_contract: dict[str, Any],
    current_contract: dict[str, Any],
    staleness: str,
) -> dict[str, Any]:
    entry_id = f"{catalog_key.world}::{catalog_key.backend}"
    return {
        "id": entry_id,
        "world_id": catalog_key.world,
        "backend_id": catalog_key.backend,
        "catalog_key": catalog_key.to_payload(),
        "path": selected["runtime_map_prior"],
        "status": "accepted",
        "staleness": staleness,
        "source": "runtime_map_prior_selector",
        "selected_candidate_id": selected["candidate_id"],
        "run_id": selected["run_id"],
        "product_route": selected["product_route"],
        "producer": selected["producer"],
        "source_map_contract": dict(source_map_contract),
        "current_contract": dict(current_contract),
        "evidence": [
            "hard_gates_passed",
            "downstream_no_regression",
            f"compatibility:{staleness}",
        ],
    }


def _normalize_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    catalog_key = (
        RuntimePriorCatalogKey.from_mapping(entry["catalog_key"]).to_payload()
        if isinstance(entry.get("catalog_key"), dict)
        else {}
    )
    normalized = {
        "id": _required_string(entry, "id"),
        "world_id": _required_string(entry, "world_id"),
        "backend_id": _required_string(entry, "backend_id"),
        "path": _required_string(entry, "path"),
        "status": _required_string(entry, "status"),
        "staleness": _required_string(entry, "staleness"),
        "source": _required_string(entry, "source"),
        "catalog_key": catalog_key,
        "selected_candidate_id": str(entry.get("selected_candidate_id") or ""),
        "run_id": str(entry.get("run_id") or ""),
        "product_route": dict(entry.get("product_route") or {}),
        "producer": dict(entry.get("producer") or {}),
        "source_map_contract": dict(entry.get("source_map_contract") or {}),
        "current_contract": dict(entry.get("current_contract") or {}),
        "evidence": _string_tuple(entry.get("evidence") or ()),
    }
    return normalized


def _runtime_prior_path_schema_valid(path: str) -> bool:
    if not path:
        return False
    prior_path = Path(path)
    if not prior_path.is_file():
        return False
    try:
        payload = read_json_object(prior_path, label="runtime map prior")
    except (OSError, ValueError):
        return False
    return payload.get("schema") == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA


def _artifact_has_private_truth(path: str) -> bool:
    if not path or not Path(path).is_file():
        return True
    try:
        payload = read_json_object(Path(path), label="runtime map prior")
    except (OSError, ValueError):
        return True
    return _contains_private_truth_key(payload)


def _contains_private_truth_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in PRIVATE_TRUTH_KEYS:
                return True
            if _contains_private_truth_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_private_truth_key(item) for item in value)
    return False


def _ranking_key(candidate: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
    utility = candidate["utility"]
    quality = candidate["quality"]
    cost = candidate["cost_latency"]
    return (
        -_number(utility.get("improved_row_count")),
        -_number(utility.get("stable_anchor_used_count")),
        _number(utility.get("total_tool_call_delta")),
        -_number(quality.get("public_semantic_anchor_count")),
        _number(cost.get("wall_time_s"), default=999999.0),
        str(candidate.get("candidate_id") or ""),
    )


def _quality_rows(matrix_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = matrix_summary.get("map_build_rows")
    if not isinstance(rows, list):
        raise ValueError("map_build matrix summary must contain map_build_rows list")
    return [row for row in rows if isinstance(row, dict)]


def _downstream_rows(matrix_summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = matrix_summary.get("downstream_rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _manifest_candidate_for(manifest: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    candidates = manifest.get("candidates") if isinstance(manifest.get("candidates"), list) else []
    row_profile = [str(item) for item in row.get("profile_key") or ()]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_profile = [str(item) for item in candidate.get("profile_key") or ()]
        if candidate_profile and candidate_profile == row_profile:
            return candidate
        candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "")
        if candidate_id and candidate_id == str(row.get("candidate_id") or ""):
            return candidate
    return {}


def _load_eval_results_bundle(path: Path) -> dict[str, Any]:
    payload = read_json_object(path, label="eval results")
    payload["_source_path"] = str(path)
    return payload


def _gate(gate_id: str, passed: bool, reason: str) -> dict[str, str]:
    return {"id": gate_id, "status": "passed" if passed else "failed", "reason": reason}


def _threshold_passed(value: Any, threshold: Any) -> bool:
    if threshold in {None, "", MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE}:
        return True
    return _number(value, default=-1.0) >= _number(threshold)


def _number(value: Any, *, default: float = 0.0) -> float:
    if value in {None, "", MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of strings")
    result = tuple(str(item) for item in value)
    if any(not item for item in result):
        raise ValueError("expected a list of non-empty strings")
    return result


def _require_schema(payload: dict[str, Any], expected: str) -> None:
    if payload.get("schema") != expected:
        raise ValueError(f"expected schema {expected}, got {payload.get('schema')!r}")
