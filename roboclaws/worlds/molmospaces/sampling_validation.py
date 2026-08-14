"""Validation for the canonical MolmoSpaces sampler manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.worlds.molmospaces.contracts import (
    EVAL_STRESS_LANE,
    READINESS_BLOCKED,
    READINESS_READY,
    READINESS_REJECTED,
    UI_LANE,
)
from roboclaws.worlds.molmospaces.sampling import (
    EVAL_TARGET_PER_SCENE_SOURCE,
    SAMPLER_LABEL_MANIFEST_SCHEMA,
    SAMPLER_MANIFEST_SCHEMA,
    SUPPORTED_SCENE_SOURCES,
    UI_TARGET_PER_SCENE_SOURCE,
    sampler_manifest,
)

_LABEL_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "molmospaces" / "scene_sampler_room_labels.json"
)


def load_room_label_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load the prepared room-category label manifest used for admission."""

    manifest_path = path or _LABEL_MANIFEST_PATH
    try:
        payload = read_json_object(manifest_path, label="room label manifest")
    except FileNotFoundError as exc:
        raise ValueError(f"room label manifest missing: {manifest_path}") from exc
    if payload.get("schema") != SAMPLER_LABEL_MANIFEST_SCHEMA:
        raise ValueError(
            "room label manifest must use schema "
            f"{SAMPLER_LABEL_MANIFEST_SCHEMA}, got {payload.get('schema')!r}"
        )
    return payload


def validate_sampler_manifest(manifest: dict[str, Any] | None = None) -> None:
    """Validate sampler rows against source-count and provenance gates."""

    payload = manifest or sampler_manifest()
    rows = _manifest_rows(payload)
    label_manifest = load_room_label_manifest()
    _validate_label_manifest(label_manifest)
    by_source: dict[str, list[dict[str, Any]]] = {source: [] for source in SUPPORTED_SCENE_SOURCES}
    for row in rows:
        source = _validate_sampler_row(row, label_manifest=label_manifest)
        by_source[source].append(row)

    for source, source_rows in by_source.items():
        _validate_source_lane_counts(source=source, source_rows=source_rows)


def _manifest_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != SAMPLER_MANIFEST_SCHEMA:
        raise ValueError("invalid sampler manifest schema")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("sampler manifest rows must be a list")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("sampler row must be an object")
    return rows


def _validate_sampler_row(
    row: dict[str, Any],
    *,
    label_manifest: dict[str, Any],
) -> str:
    source = str(row.get("scene_source") or "")
    if source not in SUPPORTED_SCENE_SOURCES:
        raise ValueError(f"unsupported scene_source {source!r}")
    status = str(row.get("readiness_status") or "")
    if status == READINESS_READY:
        _validate_ready_row(row, label_manifest=label_manifest)
    elif status == READINESS_BLOCKED:
        _validate_blocked_row(row, source=source)
    elif status != READINESS_REJECTED:
        raise ValueError(f"unknown readiness_status {status!r}")
    return source


def _validate_blocked_row(row: dict[str, Any], *, source: str) -> None:
    if not row.get("blocked_reason") or not row.get("failure_class"):
        raise ValueError(f"blocked sampler row for {source} needs reason and failure_class")


def _validate_source_lane_counts(
    *,
    source: str,
    source_rows: list[dict[str, Any]],
) -> None:
    ui_ready = _rows_in_lane(source_rows, lane=UI_LANE)
    if 0 < len(ui_ready) < 3:
        raise ValueError(f"scene_source {source} exposes fewer than three UI-ready samples")
    if len(ui_ready) > UI_TARGET_PER_SCENE_SOURCE:
        raise ValueError(
            f"scene_source {source} exposes more than {UI_TARGET_PER_SCENE_SOURCE} UI samples"
        )
    eval_ready = _rows_in_lane(source_rows, lane=EVAL_STRESS_LANE)
    if len(eval_ready) > EVAL_TARGET_PER_SCENE_SOURCE:
        raise ValueError(
            f"scene_source {source} exposes more than "
            f"{EVAL_TARGET_PER_SCENE_SOURCE} eval-stress samples"
        )


def _rows_in_lane(source_rows: list[dict[str, Any]], *, lane: str) -> list[dict[str, Any]]:
    return [
        row
        for row in source_rows
        if row.get("readiness_status") == READINESS_READY and lane in row.get("lanes", [])
    ]


def _validate_ready_row(row: dict[str, Any], *, label_manifest: dict[str, Any]) -> None:
    source = str(row.get("scene_source") or "")
    index = row.get("scene_index")
    if not isinstance(index, int):
        raise ValueError(f"ready sampler row for {source} needs integer scene_index")
    if int(row.get("room_count") or 0) < 3:
        raise ValueError(f"{source}/{index} has fewer than three public rooms")
    if int(row.get("waypoint_count") or 0) < int(row.get("room_count") or 0):
        raise ValueError(f"{source}/{index} lacks one waypoint per public room")
    if str(row.get("category_provenance") or "") not in {
        "source_metadata",
        "prepared_visual_label_manifest",
    }:
        raise ValueError(f"{source}/{index} lacks trusted room-category provenance")
    _validate_no_heuristic_category_provenance(row)
    if not _labels_for_scene(label_manifest, source=source, scene_index=index):
        raise ValueError(f"{source}/{index} lacks prepared room labels")
    views = {item.get("view"): item.get("path") for item in row.get("preview_assets") or []}
    if not views.get("map"):
        raise ValueError(f"{source}/{index} lacks Base Metric Map preview path")


def _validate_no_heuristic_category_provenance(row: dict[str, Any]) -> None:
    forbidden = {"heuristic_room_label", "heuristic_room_count", "room_area_fallback"}
    provenance = str(row.get("category_provenance") or "")
    if provenance in forbidden:
        raise ValueError("heuristic room-category provenance cannot satisfy sampler admission")


def _validate_label_manifest(payload: dict[str, Any]) -> None:
    rows = payload.get("labels")
    if not isinstance(rows, list):
        raise ValueError("room label manifest labels must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("room label rows must be objects")
        _validate_no_heuristic_category_provenance(row)
        provenance = str(row.get("category_provenance") or "")
        if provenance not in {"prepared_visual_label_manifest", "source_metadata"}:
            raise ValueError("room label row must use trusted provenance")


def _labels_for_scene(
    payload: dict[str, Any],
    *,
    source: str,
    scene_index: int,
) -> list[dict[str, Any]]:
    return [
        row
        for row in payload.get("labels") or []
        if isinstance(row, dict)
        and row.get("scene_source") == source
        and row.get("scene_index") == scene_index
    ]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
