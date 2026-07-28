from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.live_retry import (
    LIVE_TRIAL_ATTEMPTS_FILENAME,
    is_retryable_model_call_stall,
    run_with_model_call_stall_retry,
)
from roboclaws.evals.live_timeout import LiveEvalTimeoutError


@pytest.mark.parametrize(
    ("timeout_kind", "timeout_signal", "expected"),
    [
        ("stall_timeout", "model_call_in_flight", True),
        ("wall_clock_budget_exhausted", "model_call_in_flight", False),
        ("stall_timeout", "task_progress_without_completion", False),
        ("stall_timeout", "provider_failures_seen", False),
    ],
)
def test_model_call_stall_retry_policy_is_exact(
    tmp_path: Path,
    timeout_kind: str,
    timeout_signal: str,
    expected: bool,
) -> None:
    assert (
        is_retryable_model_call_stall(
            _timeout(tmp_path, timeout_kind=timeout_kind, timeout_signal=timeout_signal)
        )
        is expected
    )


def test_model_call_stall_retries_in_fresh_audited_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "trial-0000"
    run_dir.mkdir()
    seen: list[Path] = []

    def run_attempt(attempt_run_dir: Path) -> tuple[dict[str, object], Path]:
        seen.append(attempt_run_dir)
        effective_run_dir = attempt_run_dir / "surface-run" / "seed-7"
        effective_run_dir.mkdir(parents=True)
        if len(seen) == 1:
            (effective_run_dir / "initial.marker").write_text("preserved\n")
            raise _timeout(
                effective_run_dir,
                timeout_kind="stall_timeout",
                timeout_signal="model_call_in_flight",
            )
        return {"eval_effective_run_dir": str(effective_run_dir)}, effective_run_dir

    run_result, effective_run_dir = run_with_model_call_stall_retry(
        run_dir=run_dir,
        run_attempt=run_attempt,
    )

    assert seen == [run_dir, run_dir / "retry-0001"]
    assert effective_run_dir == run_dir / "retry-0001" / "surface-run" / "seed-7"
    assert run_result["eval_effective_run_dir"] == str(effective_run_dir)
    assert (run_dir / "surface-run" / "seed-7" / "initial.marker").is_file()
    audit = json.loads((run_dir / LIVE_TRIAL_ATTEMPTS_FILENAME).read_text())
    assert audit["final_outcome"] == "passed"
    assert [item["status"] for item in audit["attempts"]] == ["stalled", "passed"]
    assert audit["attempts"][1]["attempt_role"] == "model_call_in_flight_stall_retry"


def test_model_call_stall_retries_only_once_and_attaches_audit(tmp_path: Path) -> None:
    run_dir = tmp_path / "trial-0000"
    run_dir.mkdir()
    seen: list[Path] = []

    def run_attempt(attempt_run_dir: Path) -> tuple[dict[str, object], Path]:
        seen.append(attempt_run_dir)
        effective_run_dir = attempt_run_dir / "surface-run" / "seed-7"
        effective_run_dir.mkdir(parents=True)
        raise _timeout(
            effective_run_dir,
            timeout_kind="stall_timeout",
            timeout_signal="model_call_in_flight",
        )

    with pytest.raises(LiveEvalTimeoutError) as exc_info:
        run_with_model_call_stall_retry(run_dir=run_dir, run_attempt=run_attempt)

    assert seen == [run_dir, run_dir / "retry-0001"]
    assert [item["status"] for item in exc_info.value.live_trial_attempts] == [
        "stalled",
        "stalled",
    ]
    audit_path = Path(exc_info.value.live_trial_attempts_path)
    assert audit_path == run_dir / LIVE_TRIAL_ATTEMPTS_FILENAME
    assert json.loads(audit_path.read_text())["final_outcome"] == "failed"


def test_non_model_stall_is_not_retried_or_audited(tmp_path: Path) -> None:
    run_dir = tmp_path / "trial-0000"
    run_dir.mkdir()
    call_count = 0

    def run_attempt(attempt_run_dir: Path) -> tuple[dict[str, object], Path]:
        nonlocal call_count
        call_count += 1
        raise _timeout(
            attempt_run_dir,
            timeout_kind="wall_clock_budget_exhausted",
            timeout_signal="model_call_in_flight",
        )

    with pytest.raises(LiveEvalTimeoutError):
        run_with_model_call_stall_retry(run_dir=run_dir, run_attempt=run_attempt)

    assert call_count == 1
    assert not (run_dir / LIVE_TRIAL_ATTEMPTS_FILENAME).exists()


def _timeout(
    run_dir: Path,
    *,
    timeout_kind: str,
    timeout_signal: str,
) -> LiveEvalTimeoutError:
    return LiveEvalTimeoutError(
        "live eval timeout",
        timeout_s=1200.0,
        timeout_kind=timeout_kind,
        wall_clock_budget_s=1200.0,
        stall_timeout_s=180.0,
        effective_run_dir=run_dir,
        live_status={"phase": "running-sdk"},
        timeout_debug_snapshot={"timeout_signal": timeout_signal},
        command_record={},
    )
