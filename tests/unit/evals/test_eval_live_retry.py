from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals import runner
from roboclaws.evals.live_retry import (
    LIVE_TRIAL_ATTEMPTS_FILENAME,
    is_retryable_model_call_stall,
    run_with_model_call_stall_retry,
)
from roboclaws.evals.live_timeout import LiveEvalTimeoutError
from tests.unit.evals.eval_runner_support import _run_result, _write_product_artifacts


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


def test_campaign_can_disable_automatic_retry(tmp_path: Path) -> None:
    run_dir = tmp_path / "trial-0000"
    run_dir.mkdir()
    seen: list[Path] = []

    def run_attempt(attempt_run_dir: Path) -> tuple[dict[str, object], Path]:
        seen.append(attempt_run_dir)
        raise _timeout(
            attempt_run_dir,
            timeout_kind="stall_timeout",
            timeout_signal="model_call_in_flight",
        )

    with pytest.raises(LiveEvalTimeoutError):
        run_with_model_call_stall_retry(
            run_dir=run_dir,
            run_attempt=run_attempt,
            max_retries=0,
        )

    assert seen == [run_dir]
    audit = json.loads((run_dir / LIVE_TRIAL_ATTEMPTS_FILENAME).read_text())
    assert audit["retry_policy"]["max_retries"] == 0


def test_eval_cli_disables_automatic_retry_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def capture_run(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runner, "run_eval_suite", capture_run)

    runner.run_eval_from_overrides({"suite": "open_ended_goals"})

    assert captured["live_retry_limit"] == 0


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


def test_retry_attempts_share_one_live_wall_clock_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"value": 0.0}
    seen_budgets: list[tuple[float, float]] = []
    attempt_count = 0
    monkeypatch.setattr(
        "roboclaws.evals.live_execution.time.monotonic",
        lambda: clock["value"],
    )

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        nonlocal attempt_count
        attempt_count += 1
        seen_budgets.append(
            (float(kwargs["live_timeout_s"]), float(kwargs["live_stall_timeout_s"]))
        )
        if attempt_count == 1:
            clock["value"] = 6.0
            raise _timeout(
                Path(kwargs["output_dir"]) / "surface-run" / "seed-7",
                timeout_kind="stall_timeout",
                timeout_signal="model_call_in_flight",
            )
        surface_run_dir = Path(kwargs["output_dir"]) / "surface-run" / f"seed-{kwargs['seed']}"
        _write_product_artifacts(surface_run_dir, completion_status="success")
        result = _run_result(surface_run_dir, completion_status="success")
        result["eval_effective_run_dir"] = str(surface_run_dir)
        return result

    run = runner.run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="shared-retry-deadline",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_timeout_s=10.0,
        live_stall_timeout_s=8.0,
        live_retry_limit=1,
        live_product_runner=live_product_runner,
    )

    assert run.bundle["aggregate"]["passed"] == 3
    assert seen_budgets[:2] == [(10.0, 8.0), (4.0, 4.0)]


def _timeout(
    run_dir: Path,
    *,
    timeout_kind: str,
    timeout_signal: str,
) -> LiveEvalTimeoutError:
    return LiveEvalTimeoutError(
        "live eval timeout",
        timeout_kind=timeout_kind,
        wall_clock_budget_s=1200.0,
        stall_timeout_s=180.0,
        effective_run_dir=run_dir,
        live_status={"phase": "running-sdk"},
        timeout_debug_snapshot={"timeout_signal": timeout_signal},
        command_record={},
    )
