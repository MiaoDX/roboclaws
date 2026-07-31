"""Align scene-sampler runner evidence with the generated next-flow worklist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

WORKLIST_SCHEMA = "molmospaces_scene_sampler_next_flow_worklist_v1"


def load_next_flow_worklist(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = read_json_object(path, label="scene sampler next-flow worklist")
    if payload.get("schema") != WORKLIST_SCHEMA:
        raise ValueError(f"next-flow worklist schema mismatch: {payload.get('schema')!r}")
    return payload


def align_rows_to_worklist(
    worklist: dict[str, Any] | None,
    *,
    runner: str,
    rows: list[dict[str, Any]],
    sources: tuple[str, ...] = (),
    worlds: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return non-failing alignment evidence between a runner and the worklist."""

    if worklist is None:
        return {}
    expected_action = _expected_action(runner)
    worklist_sources = worklist.get("sources") if isinstance(worklist.get("sources"), dict) else {}
    source_names = _selected_source_names(
        worklist_sources=worklist_sources,
        rows=rows,
        sources=sources,
        worlds=worlds,
    )
    source_alignments = {
        source: _source_alignment(
            source=source,
            source_payload=worklist_sources.get(source),
            runner=runner,
            expected_action=expected_action,
            rows=[row for row in rows if row.get("scene_source") == source],
            world_filter=set(worlds),
        )
        for source in source_names
    }
    return {
        "schema": "molmospaces_scene_sampler_runner_worklist_alignment_v1",
        "worklist_path": str(worklist.get("worklist_path") or ""),
        "runner": runner,
        "expected_action": expected_action,
        "status": _overall_status(source_alignments),
        "source_count": len(source_alignments),
        "expected_world_count": sum(
            int(item.get("expected_world_count") or 0) for item in source_alignments.values()
        ),
        "run_world_count": sum(
            int(item.get("run_world_count") or 0) for item in source_alignments.values()
        ),
        "missing_expected_world_count": sum(
            int(item.get("missing_expected_world_count") or 0)
            for item in source_alignments.values()
        ),
        "sources": source_alignments,
    }


def _expected_action(runner: str) -> str:
    if runner == "source_prep":
        return "run_manual_source_prep"
    if runner == "scanner":
        return "run_scanner_plan_for_ready_candidates"
    raise ValueError(f"unsupported scene sampler runner for worklist alignment: {runner!r}")


def _selected_source_names(
    *,
    worklist_sources: dict[str, Any],
    rows: list[dict[str, Any]],
    sources: tuple[str, ...],
    worlds: tuple[str, ...],
) -> list[str]:
    if sources:
        return sorted(set(sources))
    row_sources = {str(row.get("scene_source") or "") for row in rows if row.get("scene_source")}
    if worlds:
        worklist_world_sources = {
            source
            for source, payload in worklist_sources.items()
            if isinstance(payload, dict)
            and any(
                world_id in set(worlds) for world_id in _source_world_ids(payload, "source_prep")
            )
        }
        return sorted(row_sources | worklist_world_sources)
    return sorted(row_sources or set(worklist_sources))


def _source_alignment(
    *,
    source: str,
    source_payload: Any,
    runner: str,
    expected_action: str,
    rows: list[dict[str, Any]],
    world_filter: set[str],
) -> dict[str, Any]:
    run_world_ids = _dedupe(str(row.get("world_id") or "") for row in rows if row.get("world_id"))
    if not isinstance(source_payload, dict):
        return {
            "scene_source": source,
            "status": "unknown_source",
            "worklist_next_action": "",
            "expected_world_ids": [],
            "run_world_ids": run_world_ids,
            "missing_expected_world_ids": [],
            "extra_run_world_ids": run_world_ids,
            "expected_world_count": 0,
            "run_world_count": len(run_world_ids),
            "missing_expected_world_count": 0,
        }
    expected_world_ids = _source_world_ids(source_payload, runner)
    if world_filter:
        expected_world_ids = [
            world_id for world_id in expected_world_ids if world_id in world_filter
        ]
    missing = [world_id for world_id in expected_world_ids if world_id not in run_world_ids]
    extra = [world_id for world_id in run_world_ids if world_id not in expected_world_ids]
    worklist_action = str(source_payload.get("next_action") or "")
    status = _source_alignment_status(
        worklist_action=worklist_action,
        expected_action=expected_action,
        expected_world_ids=expected_world_ids,
        run_world_ids=run_world_ids,
        missing_expected_world_ids=missing,
    )
    return {
        "scene_source": source,
        "status": status,
        "worklist_next_action": worklist_action,
        "expected_world_ids": expected_world_ids,
        "run_world_ids": run_world_ids,
        "missing_expected_world_ids": missing,
        "extra_run_world_ids": extra,
        "expected_world_count": len(expected_world_ids),
        "run_world_count": len(run_world_ids),
        "missing_expected_world_count": len(missing),
    }


def _source_world_ids(source_payload: dict[str, Any], runner: str) -> list[str]:
    if runner == "scanner":
        return _dedupe(
            str(world_id or "") for world_id in source_payload.get("scanner_ready_world_ids") or []
        )
    return _dedupe(
        str(world_id or "") for world_id in source_payload.get("next_scan_world_ids") or []
    )


def _source_alignment_status(
    *,
    worklist_action: str,
    expected_action: str,
    expected_world_ids: list[str],
    run_world_ids: list[str],
    missing_expected_world_ids: list[str],
) -> str:
    if worklist_action != expected_action:
        return "ran_before_worklist_action" if run_world_ids else "not_applicable"
    if missing_expected_world_ids:
        return "partial"
    if expected_world_ids:
        return "aligned"
    return "no_expected_worlds"


def _overall_status(source_alignments: dict[str, dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "") for item in source_alignments.values()}
    if not statuses:
        return "not_applicable"
    if "unknown_source" in statuses:
        return "unknown_source"
    if "partial" in statuses:
        return "partial"
    if "ran_before_worklist_action" in statuses:
        return "ran_before_worklist_action"
    if statuses == {"not_applicable"}:
        return "not_applicable"
    if statuses <= {"aligned", "no_expected_worlds", "not_applicable"}:
        return "aligned"
    return "mixed"


def _dedupe(values: Any) -> list[str]:
    deduped: list[str] = []
    for value in values:
        raw_value = str(value or "")
        if raw_value and raw_value not in deduped:
            deduped.append(raw_value)
    return deduped
