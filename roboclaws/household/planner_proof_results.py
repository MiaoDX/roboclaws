from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_value
from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_RESULT_SUMMARY_SCHEMA
from roboclaws.household.planner_proof_fallbacks import (
    prior_fallback_candidate_filters_by_source_request,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    planner_proof_quality_summary,
)
from roboclaws.household.planner_task_feasibility import (
    grasp_feasibility_signature,
    grasp_feasibility_signature_counts,
    task_feasibility_blocker_kind,
    task_feasibility_blocker_summary,
)

_prior_fallback_candidate_filters_by_source_request = (
    prior_fallback_candidate_filters_by_source_request
)
_FALLBACK_REQUEST_ID_MARKER = "_fallback_"
_RUNTIME_ALIAS_RE = re.compile(r"^(?P<prefix>.+)_(?P<group>\d+)_(?P<variant>\d+)_(?P<room>\d+)$")


def proof_result_summary_from_commands(commands: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize generated proof outputs without replacing strict proof validation."""
    results = [_proof_result_from_command(item) for item in commands]
    proof_quality_summary = planner_proof_quality_summary(
        item for item in results if item.get("run_result_exists")
    )
    return {
        "schema": PLANNER_PROOF_RESULT_SUMMARY_SCHEMA,
        "expected_count": len(commands),
        "result_count": sum(1 for item in results if item["run_result_exists"]),
        "planner_backed_count": sum(1 for item in results if item["planner_backed"]),
        "blocked_count": sum(1 for item in results if item["status"] == "blocked_capability"),
        "timeout_count": sum(1 for item in results if _has_blocker_code(item, "timeout")),
        "rby1m_config_import_timeout_count": sum(
            1
            for item in results
            if _has_blocker_code(item, "timeout")
            and item.get("last_worker_stage") == "rby1m_config_import"
        ),
        "missing_result_count": sum(1 for item in results if not item["run_result_exists"]),
        "cleanup_binding_promoted_count": sum(
            1 for item in results if item["cleanup_binding_promoted"]
        ),
        "execution_attempted_count": sum(1 for item in results if item["execution_attempted"]),
        "task_feasibility_blocked_count": sum(
            1 for item in results if item["task_feasibility_status"] == "blocked"
        ),
        "grasp_feasibility_blocked_count": sum(
            1
            for item in results
            if item.get("task_feasibility_blocker_kind") == "grasp_feasibility"
        ),
        "grasp_feasibility_signature_count": len(grasp_feasibility_signature_counts(results)),
        "grasp_feasibility_signature_counts": grasp_feasibility_signature_counts(results),
        "worker_stage_event_count": sum(
            int(item.get("worker_stage_event_count") or 0) for item in results
        ),
        "last_worker_stage_counts": _last_worker_stage_counts(results),
        "view_artifact_count": sum(len(item.get("views") or []) for item in results),
        "proof_quality_summary": proof_quality_summary,
        "results": results,
        "evidence_note": (
            "Bundle-level summary of generated proof artifacts. Strict per-proof "
            "checkers still decide whether a proof is planner-backed."
        ),
    }


def _proof_result_from_command(item: dict[str, Any]) -> dict[str, Any]:
    run_result_path = Path(str(item.get("run_result") or ""))
    proof_report_path = Path(str(item.get("report") or ""))
    base = run_result_path.parent if str(run_result_path) else Path(".")
    result = {
        "request_id": str(item.get("request_id") or ""),
        "object_id": str(item.get("object_id") or ""),
        "target_receptacle_id": str(item.get("target_receptacle_id") or ""),
        "run_result": str(run_result_path),
        "report": str(proof_report_path),
        "run_result_exists": run_result_path.is_file(),
        "report_exists": proof_report_path.is_file(),
        "status": "not_run",
        "planner_backed": False,
        "cleanup_binding_promoted": False,
        "execution_attempted": False,
        "task_feasibility_status": "not_run",
        "visual_status": "not_run",
        "blockers": [],
        "cleanup_binding_blockers": [],
        "last_worker_stage": "",
        "worker_stage_event_count": 0,
        "worker_stage_events": [],
        "steps_executed": 0,
        "max_abs_qpos_delta": 0.0,
        "proof_quality": {},
        "stdout": "",
        "stderr": "",
        "views": [],
    }
    if not run_result_path.is_file():
        return result
    try:
        data = read_json_value(run_result_path, label="planner proof run result")
    except ValueError as exc:
        result.update(_unreadable_proof_result_payload(_proof_run_result_source_error(exc)))
        return result
    except OSError as exc:
        result.update(_unreadable_proof_result_payload(f"{type(exc).__name__}: {exc}"))
        return result
    if not isinstance(data, dict):
        result.update(_unreadable_proof_result_payload(f"non-object JSON: {type(data).__name__}"))
        return result
    evidence = data.get("manipulation_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    artifacts = data.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    blockers = normalized_blockers(evidence.get("blockers") or [])
    cleanup_binding_blockers = normalized_blockers(
        evidence.get("cleanup_primitive_binding_blockers") or []
    )
    cleanup_task_config = evidence.get("cleanup_task_config") or {}
    task_sampler_robot_placement_profile = (
        evidence.get("task_sampler_robot_placement_profile") or {}
    )
    cleanup_task_sampler_adapter = evidence.get("cleanup_task_sampler_adapter") or {}
    task_sampler_failure_diagnostics = evidence.get("task_sampler_failure_diagnostics") or {}
    blocker_kind = task_feasibility_blocker_kind(
        blockers,
        task_sampler_failure_diagnostics,
    )
    grasp_signature = grasp_feasibility_signature(task_sampler_failure_diagnostics)
    requested_binding = evidence.get("requested_cleanup_primitive_binding") or {}
    sampled_binding = evidence.get("sampled_task_binding") or {}
    cleanup_binding = evidence.get("cleanup_primitive_binding") or {}
    planner_backed = data.get("status") == "planner_backed"
    views = _proof_views(base, evidence)
    worker_stage_events = _compact_worker_stage_events(evidence.get("worker_stage_events") or [])
    proof_quality = planner_proof_quality_evidence(evidence)
    result.update(
        {
            "status": str(data.get("status") or "unknown"),
            "planner_backed": planner_backed,
            "cleanup_binding_promoted": bool(cleanup_binding),
            "execution_attempted": bool(evidence.get("execution_attempted")),
            "task_feasibility_status": _task_feasibility_status(
                status=str(data.get("status") or ""),
                planner_backed=planner_backed,
                cleanup_binding_promoted=bool(cleanup_binding),
                blockers=blockers,
                cleanup_binding_blockers=cleanup_binding_blockers,
                execution_attempted=bool(evidence.get("execution_attempted")),
            ),
            "task_feasibility_blocker_kind": blocker_kind,
            "task_feasibility_blocker_summary": task_feasibility_blocker_summary(
                blocker_kind,
                task_sampler_failure_diagnostics,
            ),
            "grasp_feasibility_signature": grasp_signature,
            "visual_status": "views_recorded" if views else "no_views_recorded",
            "blockers": blockers,
            "cleanup_binding_blockers": cleanup_binding_blockers,
            "last_worker_stage": str(evidence.get("last_worker_stage") or ""),
            "worker_stage_event_count": len(worker_stage_events),
            "worker_stage_events": worker_stage_events,
            "steps_executed": int(proof_quality.get("steps_executed") or 0),
            "max_abs_qpos_delta": float(proof_quality.get("max_abs_qpos_delta") or 0.0),
            "proof_quality": proof_quality,
            "stdout": _proof_artifact_path(base, artifacts, "stdout"),
            "stderr": _proof_artifact_path(base, artifacts, "stderr"),
            "cleanup_task_config": cleanup_task_config,
            "task_sampler_robot_placement_profile": task_sampler_robot_placement_profile,
            "cleanup_task_sampler_adapter": cleanup_task_sampler_adapter,
            "task_sampler_failure_diagnostics": task_sampler_failure_diagnostics,
            "requested_cleanup_primitive_binding": requested_binding,
            "sampled_task_binding": sampled_binding,
            "cleanup_primitive_binding": cleanup_binding,
            "views": views,
        }
    )
    return result


def _unreadable_proof_result_payload(message: str) -> dict[str, Any]:
    return {
        "status": "unreadable",
        "task_feasibility_status": "unknown",
        "visual_status": "unknown",
        "blockers": [
            {
                "code": "proof_run_result_unreadable",
                "message": message,
            }
        ],
    }


def _proof_run_result_source_error(exc: ValueError) -> str:
    cause = exc.__cause__
    if isinstance(cause, json.JSONDecodeError):
        return f"{type(cause).__name__}: {cause}"
    return f"{type(exc).__name__}: {exc}"


def _has_blocker_code(result: dict[str, Any], code: str) -> bool:
    blockers = [*(result.get("blockers") or []), *(result.get("cleanup_binding_blockers") or [])]
    return any(isinstance(item, dict) and str(item.get("code") or "") == code for item in blockers)


def _last_worker_stage_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        stage = str(item.get("last_worker_stage") or "")
        if stage:
            counts[stage] = counts.get(stage, 0) + 1
    return counts


def _compact_worker_stage_events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    events = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        compact = {}
        for key in ("elapsed_s", "event", "stage", "embodiment", "probe_mode"):
            value = item.get(key)
            if value not in (None, "", []):
                compact[key] = value
        if compact:
            events.append(compact)
    return events


def _proof_artifact_path(base: Path, artifacts: dict[str, Any], key: str) -> str:
    value = artifacts.get(key)
    if not value:
        return ""
    path = Path(str(value))
    return str(path if path.is_absolute() else base / path)


def _task_feasibility_status(
    *,
    status: str,
    planner_backed: bool,
    cleanup_binding_promoted: bool,
    blockers: list[dict[str, Any]],
    cleanup_binding_blockers: list[dict[str, Any]],
    execution_attempted: bool,
) -> str:
    codes = {str(item.get("code") or "") for item in blockers}
    messages = " ".join(str(item.get("message") or "") for item in blockers).lower()
    if "HouseInvalidForTask" in codes or "robot placement" in messages:
        return "blocked"
    if cleanup_binding_promoted:
        return "ready"
    if planner_backed:
        return "binding_not_promoted" if cleanup_binding_blockers else "ready"
    if not execution_attempted:
        return "not_reached"
    if status == "blocked_capability":
        return "blocked"
    return "unknown"


def _proof_views(base: Path, evidence: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = evidence.get("image_artifacts") or {}
    if not isinstance(artifacts, dict):
        return []
    views = []
    for label, value in sorted(artifacts.items()):
        if not value:
            continue
        path = Path(str(value))
        views.append(
            {
                "label": str(label),
                "path": str(path if path.is_absolute() else base / path),
            }
        )
    return views


def normalized_blockers(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        return [dict(raw)]
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]
