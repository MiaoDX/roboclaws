from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.runtime_prior_contracts import (
    RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA,
    RUNTIME_METRIC_MAP_SCHEMA,
)


def runtime_metric_map_from_prior_artifact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept either raw runtime_metric_map.json or the canonical snapshot wrapper."""

    if payload is None:
        return None
    schema = payload.get("schema")
    if schema == RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA:
        runtime_metric_map = payload.get("runtime_metric_map")
        if not isinstance(runtime_metric_map, dict):
            raise ValueError("runtime map prior snapshot lacks runtime_metric_map")
        if runtime_metric_map.get("schema") != RUNTIME_METRIC_MAP_SCHEMA:
            raise ValueError(
                "runtime map prior snapshot runtime_metric_map must use schema "
                f"{RUNTIME_METRIC_MAP_SCHEMA}, got {runtime_metric_map.get('schema')!r}"
            )
        return copy.deepcopy(runtime_metric_map)
    if schema != RUNTIME_METRIC_MAP_SCHEMA:
        raise ValueError(
            "runtime map prior artifact must be raw "
            f"{RUNTIME_METRIC_MAP_SCHEMA} or {RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA}, got {schema!r}"
        )
    return copy.deepcopy(payload)


def read_runtime_map_prior_artifact(path: str | Path | None) -> dict[str, Any] | None:
    """Read a runtime-map-prior artifact from an explicit source path."""

    if path is None or str(path) == "":
        return None
    payload = read_json_object(Path(path), label="runtime map prior")
    return runtime_metric_map_from_prior_artifact(payload)
