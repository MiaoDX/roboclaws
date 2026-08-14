from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_RESULT_SUMMARY_SCHEMA,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    validate_planner_proof_quality_evidence,
)
from roboclaws.household.planner_task_feasibility import grasp_feasibility_signature_counts


def assert_proof_result_summary(
    summary: dict[str, Any],
    commands: list[dict[str, Any]],
    base: Path,
    *,
    require_outputs: bool,
    require_quality: bool = False,
    planner_backed_min_steps: int | None = None,
) -> None:
    assert summary.get("schema") == PLANNER_PROOF_RESULT_SUMMARY_SCHEMA, summary
    assert int(summary.get("expected_count") or 0) == len(commands), summary
    results = summary.get("results") or []
    assert len(results) == len(commands), summary
    if require_outputs:
        assert int(summary.get("result_count") or 0) == len(commands), summary
    _assert_timeout_counts(summary, results)
    assert_grasp_signature_counts(summary, results)
    if require_quality or planner_backed_min_steps is not None:
        _assert_proof_quality_summary(
            summary,
            results,
            planner_backed_min_steps=planner_backed_min_steps,
        )
    for item in results:
        _assert_proof_result_item(item, base)


def assert_prior_proof_result_summary(
    summary: dict[str, Any],
    base: Path,
) -> None:
    schema = str(summary.get("schema") or "")
    assert schema, summary
    results = summary.get("results") or []
    assert isinstance(results, list), summary
    assert_grasp_signature_counts(summary, results)
    for item in results:
        assert isinstance(item, dict), summary
        for view in item.get("views") or []:
            _assert_view_artifact(view, base)


def assert_grasp_signature_counts(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    grasp_signature_counts = summary.get("grasp_feasibility_signature_counts") or []
    if grasp_signature_counts:
        assert int(summary.get("grasp_feasibility_signature_count") or 0) == len(
            grasp_signature_counts
        ), summary
    else:
        grasp_signature_counts = grasp_feasibility_signature_counts(results)
    if not grasp_signature_counts:
        return
    for signature in grasp_signature_counts:
        assert signature.get("pattern_key"), signature
        assert int(signature.get("count") or 0) > 0, signature


def _assert_timeout_counts(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    timeout_count = sum(1 for item in results if _has_blocker_code(item, "timeout"))
    assert int(summary.get("timeout_count") or 0) == timeout_count, summary
    rby1m_config_import_timeout_count = sum(
        1
        for item in results
        if _has_blocker_code(item, "timeout")
        and item.get("last_worker_stage") == "rby1m_config_import"
    )
    assert (
        int(summary.get("rby1m_config_import_timeout_count") or 0)
        == rby1m_config_import_timeout_count
    ), summary


def _assert_proof_result_item(item: dict[str, Any], base: Path) -> None:
    for key in ("request_id", "status", "task_feasibility_status", "run_result", "report"):
        assert item.get(key), item
    assert item.get("task_feasibility_status") in {
        "not_run",
        "not_reached",
        "ready",
        "binding_not_promoted",
        "blocked",
        "unknown",
    }, item
    for view in item.get("views") or []:
        _assert_view_artifact(view, base)
    _assert_worker_stage_events(item)


def _assert_worker_stage_events(item: dict[str, Any]) -> None:
    worker_stage_events = item.get("worker_stage_events") or []
    assert int(item.get("worker_stage_event_count") or 0) == len(worker_stage_events), item
    for event in worker_stage_events:
        assert isinstance(event, dict), item


def _assert_proof_quality_summary(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    planner_backed_min_steps: int | None,
) -> None:
    proof_quality_summary = summary.get("proof_quality_summary") or {}
    assert proof_quality_summary.get("schema") == "planner_proof_quality_summary_v1", summary
    for item in results:
        if not item.get("run_result_exists"):
            continue
        quality = planner_proof_quality_evidence(item)
        assert quality.get("schema") == "planner_proof_quality_v1", item
        if planner_backed_min_steps is not None and item.get("planner_backed"):
            validate_planner_proof_quality_evidence(
                quality,
                min_steps_executed=planner_backed_min_steps,
            )


def _assert_view_artifact(view: dict[str, Any], base: Path) -> None:
    path_text = str(view.get("path") or "")
    assert path_text, view
    resolved = _resolve_path(base, path_text)
    if resolved.exists():
        assert resolved.is_file(), resolved


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    return base / path


def _has_blocker_code(item: dict[str, Any], code: str) -> bool:
    blockers = [*(item.get("blockers") or []), *(item.get("cleanup_binding_blockers") or [])]
    return any(
        isinstance(blocker, dict) and str(blocker.get("code") or "") == code for blocker in blockers
    )
