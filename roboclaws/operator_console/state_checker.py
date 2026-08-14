"""Checker-state normalization for operator console run summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.operator_console.state_summary import is_active_run_phase, run_result_success


def checker_status(
    *,
    checker_log: Path,
    report: Path,
    run_result: dict[str, Any],
    phase: str,
    launch_failure_reason: str = "",
) -> dict[str, Any]:
    normalized_phase = phase.lower()
    failure_reason = checker_failure_reason(run_result, checker_log)
    if normalized_phase in {"failed", "error", "terminated"}:
        reason = launch_failure_reason or failure_reason
        message = (
            f"Launch failed: {reason}"
            if launch_failure_reason
            else _checker_failure_message(checker_log, reason, "Run failed.")
        )
        return {
            "status": "failed",
            "report_exists": report.exists(),
            "checker_log": str(checker_log) if checker_log.exists() else "",
            "reason": reason,
            "message": message,
        }
    if run_result_success(run_result) and report.exists():
        return {
            "status": "passed",
            "report_exists": True,
            "checker_log": str(checker_log) if checker_log.exists() else "",
            "reason": "",
            "message": "Checker passed.",
        }
    if run_result:
        return {
            "status": "failed",
            "report_exists": report.exists(),
            "checker_log": str(checker_log) if checker_log.exists() else "",
            "reason": failure_reason,
            "message": _checker_failure_message(
                checker_log, failure_reason, "Run result is present."
            ),
        }
    if normalized_phase == "checking-result":
        return {
            "status": "running",
            "report_exists": report.exists(),
            "checker_log": str(checker_log) if checker_log.exists() else "",
            "reason": "",
            "message": "Checker is running.",
        }
    if is_active_run_phase(normalized_phase):
        return {
            "status": "waiting",
            "report_exists": False,
            "checker_log": "",
            "reason": "",
            "message": "Checker will run when the live agent hands off to result checking.",
        }
    return {
        "status": "pending",
        "report_exists": False,
        "checker_log": str(checker_log) if checker_log.exists() else "",
        "reason": "",
        "message": "Checker has not run yet.",
    }


def checker_failure_reason(run_result: dict[str, Any], checker_log: Path) -> str:
    reason = _structured_checker_failure_reason(run_result)
    if reason:
        return reason
    return _checker_log_failure_reason(checker_log)


def _checker_failure_message(checker_log: Path, reason: str, fallback: str) -> str:
    if reason:
        return f"Checker failed: {reason}"
    if checker_log.exists():
        return "Checker failed. Open Checker Output for details."
    return fallback


def _structured_checker_failure_reason(run_result: dict[str, Any]) -> str:
    diagnostics = run_result.get("agent_diagnostics") or {}
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    if diagnostics.get("fridge_inside_sequence_ok") is False:
        return (
            "fridge cleanup sequence incomplete; call close_receptacle with the same "
            "fridge fixture_id after place_inside before moving on or done."
        )
    stale_reference_errors = int(diagnostics.get("stale_reference_errors") or 0)
    if stale_reference_errors > 0:
        return (
            f"{stale_reference_errors} stale reference error(s); use object and fixture ids "
            "from the latest observe response."
        )
    semantic_order_errors = int(
        diagnostics.get("semantic_order_unrecovered_errors")
        or diagnostics.get("semantic_order_errors")
        or 0
    )
    if semantic_order_errors > 0:
        return (
            f"{semantic_order_errors} semantic order error(s); call the required_tool from "
            "the failed MCP response before trying another cleanup tool."
        )
    duplicate_navigation_count = int(diagnostics.get("duplicate_post_place_navigation_count") or 0)
    if duplicate_navigation_count > 0:
        return (
            f"{duplicate_navigation_count} duplicate post-place navigation event(s); after "
            "placing an object, observe before choosing the next object or waypoint."
        )
    if diagnostics.get("premature_done") is True:
        source = diagnostics.get("premature_done_source")
        suffix = f" ({source})" if source else ""
        return f"done was called before cleanup was complete{suffix}."
    return ""


def _checker_log_failure_reason(checker_log: Path) -> str:
    if not checker_log.exists():
        return ""
    try:
        text = checker_log.read_text(encoding="utf-8", errors="replace")[:80_000]
    except OSError:
        return ""
    if "fridge_inside_sequence_ok" in text:
        return (
            "fridge cleanup sequence incomplete; call close_receptacle with the same "
            "fridge fixture_id after place_inside before moving on or done."
        )
    if "stale_reference_errors" in text:
        return (
            "stale reference errors; use object and fixture ids from the latest observe response."
        )
    if "semantic_order" in text:
        return (
            "semantic cleanup order failed; call the required_tool from the failed MCP "
            "response before trying another cleanup tool."
        )
    return ""
