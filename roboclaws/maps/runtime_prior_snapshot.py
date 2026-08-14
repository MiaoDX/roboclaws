from __future__ import annotations

import copy
from typing import Any

from roboclaws.maps.runtime_prior_contracts import (
    RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA as _RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
)
from roboclaws.maps.runtime_prior_contracts import (
    RUNTIME_METRIC_MAP_SCHEMA as _RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.maps.runtime_prior_conversion_helpers import (
    _materialized_fixtures_from_runtime_map,
    _materialized_waypoints_from_runtime_map,
    _snapshot_summary,
)
from roboclaws.maps.runtime_prior_source_validation import (
    _assert_no_private_truth,
    _source_navigation_map_reference,
)


def runtime_prior_snapshot_from_runtime_metric_map(
    runtime_metric_map: dict[str, Any],
    *,
    source_navigation_map: dict[str, Any] | None = None,
    producer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap an online runtime map in the canonical downstream snapshot contract."""

    runtime_metric_map = copy.deepcopy(runtime_metric_map)
    if runtime_metric_map.get("schema") != _RUNTIME_METRIC_MAP_SCHEMA:
        raise ValueError(
            "runtime_metric_map must use schema "
            f"{_RUNTIME_METRIC_MAP_SCHEMA}, got {runtime_metric_map.get('schema')!r}"
        )
    snapshot = {
        "schema": _RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
        "source_navigation_map": _source_navigation_map_reference(
            source_navigation_map or runtime_metric_map.get("static_map") or {}
        ),
        "runtime_metric_map": runtime_metric_map,
        "public_semantic_anchors": copy.deepcopy(
            runtime_metric_map.get("public_semantic_anchors") or []
        ),
        "inspection_waypoints": _materialized_waypoints_from_runtime_map(runtime_metric_map),
        "fixture_candidates": _materialized_fixtures_from_runtime_map(runtime_metric_map),
        "producer": {
            "type": "online_map_build",
            "provenance": "map_build_runtime_metric_map",
            **dict(producer or {}),
        },
        "contract": {
            "schema": _RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
            "runtime_metric_map_schema": _RUNTIME_METRIC_MAP_SCHEMA,
            "online_offline_equivalent_shape": True,
            "private_truth_included": False,
            "source_map_mutated": False,
            "movable_object_priors_require_current_run_confirmation": True,
        },
    }
    snapshot["summary"] = _snapshot_summary(snapshot)
    _assert_no_private_truth(snapshot)
    return snapshot
