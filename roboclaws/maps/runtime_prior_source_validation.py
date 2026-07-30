from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from roboclaws.maps.runtime_prior_contracts import PRIVATE_TRUTH_KEYS


def _source_navigation_map_reference(source: dict[str, Any]) -> dict[str, Any]:
    if not source:
        return {
            "schema": "source_navigation_map_reference_v1",
            "source_type": "runtime_metric_map_static_map",
        }
    return {
        "schema": "source_navigation_map_reference_v1",
        "source_type": "minimal_navigation_map_artifact",
        "map_id": str(source.get("map_id") or source.get("environment_id") or ""),
        "map_frame": _source_navigation_map_frame_id(source),
        "source_schema": str(source.get("schema") or ""),
        "source_map_mutated": False,
    }


def _runtime_metric_map_frame_id(runtime_metric_map: dict[str, Any]) -> str:
    static_map = (
        runtime_metric_map.get("static_map")
        if isinstance(runtime_metric_map.get("static_map"), dict)
        else {}
    )
    runtime_frame_id = str(
        runtime_metric_map.get("frame_id") or runtime_metric_map.get("map_frame") or ""
    )
    static_frame_id = str(static_map.get("frame_id") or static_map.get("map_frame") or "")
    if runtime_frame_id and static_frame_id and runtime_frame_id != static_frame_id:
        raise ValueError(
            "runtime metric map frame_id must match static_map frame, "
            f"got {runtime_frame_id!r} and {static_frame_id!r}"
        )
    return runtime_frame_id or static_frame_id or "map"


def _source_navigation_map_frame_id(source: dict[str, Any]) -> str:
    frame_id = str(source.get("frame_id") or source.get("map_frame") or "")
    return frame_id or "map"


def _reject_frame_drift(
    payload: dict[str, Any],
    *,
    expected_frame_id: str,
    label: str,
) -> None:
    frame_ids = _declared_frame_ids(payload)
    mismatches = sorted(frame_id for frame_id in frame_ids if frame_id != expected_frame_id)
    if mismatches:
        raise ValueError(
            f"{label} frame_id must match runtime metric map frame {expected_frame_id!r}, "
            f"got {mismatches[0]!r}"
        )


def _declared_frame_ids(payload: dict[str, Any]) -> set[str]:
    frame_ids = set()
    frame_id = str(payload.get("frame_id") or "")
    if frame_id:
        frame_ids.add(frame_id)
    pose = payload.get("pose") if isinstance(payload.get("pose"), dict) else {}
    pose_frame_id = str(pose.get("frame_id") or "")
    if pose_frame_id:
        frame_ids.add(pose_frame_id)
    return frame_ids


def _source_hashes(*paths: Path) -> dict[str, str]:
    hashes = {}
    for path in paths:
        if path.is_file():
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _artifact_paths(map_dir: Path) -> dict[str, str]:
    result = {
        "navigation_memory": "navigation_memory.json",
        "nav2_yaml": "agibot/nav2.yaml",
        "occupancy_grid": "agibot/occupancy.pgm",
        "source": "agibot/source.json",
    }
    if (map_dir / "agibot" / "raw_map.json.gz").is_file():
        result["raw_map"] = "agibot/raw_map.json.gz"
    return result


def _map_id(map_dir: Path, source: dict[str, Any]) -> str:
    return str(source.get("alias") or source.get("requested_map_id") or map_dir.name)


def _source_map_geometry(map_yaml: dict[str, Any], *, label: str) -> tuple[float, list[float]]:
    try:
        resolution = float(map_yaml.get("resolution"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} resolution must be a positive finite number") from exc
    if not math.isfinite(resolution) or resolution <= 0.0:
        raise ValueError(f"{label} resolution must be a positive finite number")
    origin = map_yaml.get("origin")
    if not isinstance(origin, list) or len(origin) != 3:
        raise ValueError(f"{label} origin must be a 3-item numeric list")
    try:
        parsed_origin = [float(item) for item in origin]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} origin must be a 3-item numeric list") from exc
    if any(not math.isfinite(item) for item in parsed_origin):
        raise ValueError(f"{label} origin must be a 3-item numeric list")
    return resolution, parsed_origin


def _safe_id(value: str) -> str:
    result = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in result:
        result = result.replace("__", "_")
    return result.strip("_") or "anchor"


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{_safe_id(value)}"


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)


def _assert_no_private_truth(value: Any) -> None:
    hits = sorted(_find_private_keys(value))
    if hits:
        raise ValueError(f"private truth keys present in runtime map prior snapshot: {hits}")


def _find_private_keys(value: Any) -> set[str]:
    hits: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in PRIVATE_TRUTH_KEYS:
                hits.add(str(key))
            hits.update(_find_private_keys(item))
    elif isinstance(value, list):
        for item in value:
            hits.update(_find_private_keys(item))
    return hits
