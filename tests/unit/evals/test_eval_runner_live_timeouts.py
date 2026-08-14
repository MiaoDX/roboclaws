from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _completed_process,
    _live_surface_kwargs,
    _patch_live_surface_popen,
    _run_result,
    _write_product_artifacts,
)


def test_live_surface_product_uses_default_live_budgets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        assert "timeout" not in kwargs
        output_arg = next(item for item in command if item.startswith("output_dir="))
        run_dir = Path(output_arg.removeprefix("output_dir=")) / "0615_0310" / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text(
            json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
        )
        (run_dir / "live_status.json").write_text('{"phase": "finished", "exit_status": 0}\n')
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)

    live_exec.run_live_surface_product(**_live_surface_kwargs(tmp_path / "trial-0000"))

    command_record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert command_record["wall_clock_budget_s"] == 1500.0
    assert command_record["stall_timeout_s"] == 180.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "soon"])
def test_live_surface_timeout_rejects_invalid_config(value: str) -> None:
    import roboclaws.evals.live_runtime as live_runtime

    kwargs = _live_surface_kwargs(Path("trial-0000"), live_timeout_s=value)  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match=r"live_timeout_s must be a positive finite number of seconds",
    ):
        live_runtime.live_wall_clock_budget_s(kwargs)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "soon"])
def test_live_stall_timeout_rejects_invalid_config(value: str) -> None:
    import roboclaws.evals.live_runtime as live_runtime

    kwargs = _live_surface_kwargs(
        Path("trial-0000"),
        live_stall_timeout_s=value,  # type: ignore[arg-type]
    )

    with pytest.raises(
        ValueError,
        match=r"live_stall_timeout_s must be a positive finite number of seconds",
    ):
        live_runtime.live_stall_timeout_s(kwargs)


def test_live_surface_timeout_accessors_use_split_defaults_and_overrides() -> None:
    import roboclaws.evals.live_runtime as live_runtime

    defaults = _live_surface_kwargs(Path("trial-0000"))
    assert live_runtime.live_wall_clock_budget_s(defaults) == 1500.0
    assert live_runtime.live_stall_timeout_s(defaults) == 180.0

    explicit = _live_surface_kwargs(
        Path("trial-0000"),
        live_timeout_s=300.0,
        live_stall_timeout_s=7.5,
    )
    assert live_runtime.live_wall_clock_budget_s(explicit) == 300.0
    assert live_runtime.live_stall_timeout_s(explicit) == 7.5


def test_live_surface_product_does_not_wait_after_sdk_process_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

    sleep_count = {"value": 0}

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0312" / "seed-7"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "live_status.json").write_text('{"phase": "running-sdk"}\n')
        return _completed_process(returncode=0)

    def fake_sleep(seconds: float) -> None:
        sleep_count["value"] += 1

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    monkeypatch.setattr(live_exec.time, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="live surface run finished without"):
        live_exec.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=1.0)
        )

    assert sleep_count["value"] == 0


@pytest.mark.parametrize(
    "reason",
    [
        "observe_budget_exhausted",
        "agent_sdk_turn_budget_exceeded",
        "provider_context_budget_exceeded",
    ],
)
def test_live_eval_classifies_budget_runtime_failure(tmp_path: Path, reason: str) -> None:
    def live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(f"OpenAI Agents SDK runtime failed: {reason}")

    run = run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="live-open-ended-observe-budget",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]

    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["failure_classes"] == {"budget_exhausted": 3}
    assert result["status"] == "failed"
    assert result["failure_class"] == "budget_exhausted"
    assert result["limitations"] == ["product_run_failed_before_grading"]
