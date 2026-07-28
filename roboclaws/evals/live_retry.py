"""Bounded, auditable retry policy for live eval product attempts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from roboclaws.evals.live_timeout import LiveEvalTimeoutError

LIVE_MODEL_CALL_STALL_RETRY_LIMIT = 1
LIVE_TRIAL_ATTEMPTS_FILENAME = "live_trial_attempts.json"
LiveAttempt = Callable[[Path], tuple[dict[str, Any], Path]]


def run_with_model_call_stall_retry(
    *,
    run_dir: Path,
    run_attempt: LiveAttempt,
) -> tuple[dict[str, Any], Path]:
    """Retry one in-flight model stall in a fresh child directory."""

    attempts: list[dict[str, Any]] = []
    audit_path = run_dir / LIVE_TRIAL_ATTEMPTS_FILENAME
    for attempt_index in range(LIVE_MODEL_CALL_STALL_RETRY_LIMIT + 1):
        attempt_run_dir = run_dir if attempt_index == 0 else run_dir / f"retry-{attempt_index:04d}"
        try:
            result = run_attempt(attempt_run_dir)
        except Exception as exc:  # noqa: BLE001 - policy must inspect all attempt failures.
            retryable = is_retryable_model_call_stall(exc)
            attempts.append(
                _attempt_record(
                    attempt_index=attempt_index,
                    run_dir=attempt_run_dir,
                    status="stalled" if retryable else "failed",
                    exc=exc,
                )
            )
            if retryable and attempt_index < LIVE_MODEL_CALL_STALL_RETRY_LIMIT:
                _write_attempts(audit_path, attempts, final_outcome="retrying")
                continue
            if attempts[0]["status"] == "stalled":
                _write_attempts(audit_path, attempts, final_outcome="failed")
                setattr(exc, "live_trial_attempts", attempts)
                setattr(exc, "live_trial_attempts_path", str(audit_path))
            raise
        run_result, effective_run_dir = result
        attempts.append(
            _attempt_record(
                attempt_index=attempt_index,
                run_dir=attempt_run_dir,
                status="passed",
                effective_run_dir=effective_run_dir,
            )
        )
        if attempt_index:
            _write_attempts(audit_path, attempts, final_outcome="passed")
        return run_result, effective_run_dir
    raise AssertionError("live trial retry loop exhausted without a result")


def is_retryable_model_call_stall(exc: Exception) -> bool:
    if not isinstance(exc, LiveEvalTimeoutError) or exc.timeout_kind != "stall_timeout":
        return False
    snapshot = exc.timeout_debug_snapshot
    return isinstance(snapshot, dict) and snapshot.get("timeout_signal") == "model_call_in_flight"


def _attempt_record(
    *,
    attempt_index: int,
    run_dir: Path,
    status: str,
    exc: Exception | None = None,
    effective_run_dir: Path | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "attempt_index": attempt_index,
        "attempt_role": "initial" if attempt_index == 0 else "model_call_in_flight_stall_retry",
        "run_dir": str(run_dir),
        "status": status,
    }
    if effective_run_dir is not None:
        record["effective_run_dir"] = str(effective_run_dir)
    if exc is not None:
        record["error_type"] = type(exc).__name__
        record["timeout_kind"] = str(getattr(exc, "timeout_kind", "") or "")
        snapshot = getattr(exc, "timeout_debug_snapshot", None)
        if isinstance(snapshot, dict):
            record["timeout_signal"] = str(snapshot.get("timeout_signal") or "")
        failed_run_dir = str(getattr(exc, "effective_run_dir", "") or "")
        if failed_run_dir:
            record["effective_run_dir"] = failed_run_dir
    return record


def _write_attempts(path: Path, attempts: list[dict[str, Any]], *, final_outcome: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_live_trial_attempts_v1",
                "retry_policy": {
                    "max_retries": LIVE_MODEL_CALL_STALL_RETRY_LIMIT,
                    "timeout_kind": "stall_timeout",
                    "timeout_signal": "model_call_in_flight",
                },
                "final_outcome": final_outcome,
                "attempts": attempts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
