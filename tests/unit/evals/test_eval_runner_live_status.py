from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.agent_identity import agent_engine_spec
from roboclaws.evals.live_runtime import live_surface_env
from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _completed_process,
    _live_surface_kwargs,
    _passing_product_runner,
    _patch_live_surface_popen,
    _run_result,
    _write_product_artifacts,
)


@pytest.mark.parametrize("agent_engine", ("codex-cli", "claude-code", "future-engine"))
def test_eval_identity_uses_canonical_unsupported_engine_error(agent_engine: str) -> None:
    with pytest.raises(
        ValueError,
        match=(
            rf"unsupported agent_engine '{agent_engine}'; "
            r"expected direct-runner\|openai-agents-sdk"
        ),
    ):
        agent_engine_spec(agent_engine)


def test_eval_runner_records_live_agent_blocked_identity(tmp_path: Path) -> None:
    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-blocked",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        product_runner=_passing_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["total"] == 3
    assert payload["aggregate"]["blocked"] == 3
    assert payload["aggregate"]["pass_at_k"] == {"1": 0.0, "2": 0.0, "3": 0.0}
    assert payload["aggregate"]["pass_caret_k"] == {"1": 0.0, "2": 0.0, "3": 0.0}
    assert payload["aggregate"]["failure_classes"] == {"model_or_provider_unavailable": 3}
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "model_or_provider_unavailable"
    assert result["identity"]["agent_engine"] == "openai-agents-sdk"
    assert result["identity"]["runner_class"] == "live-agent"
    assert result["identity"]["provider_profile"] == "kimi-openai-chat"
    assert result["grader_outputs"]["runner"]["error_type"] == "LiveAgentEvalNotExecuted"
    preflight = result["grader_outputs"]["runner"]["preflight"]
    assert preflight["schema"] == "roboclaws_live_eval_preflight_v1"
    assert preflight["provider_readiness"]["provider_profile"] == "kimi-openai-chat"
    assert preflight["provider_readiness"]["required_env"] == [
        "KIMI_OPENAI_BASE_URL",
        "KIMI_API_KEY",
    ]
    assert preflight["runtime_readiness"]["required_runtime"] == (
        "OpenAI Agents SDK household runner"
    )
    assert preflight["blocker"] == "live_execution_not_requested"
    assert preflight["runtime_readiness"]["repo_native_live_eval_runner"] == (
        "opt_in_via_live_execution_run"
    )
    assert "live_agent_eval_execution_not_requested" in result["limitations"]


def test_eval_runner_classifies_live_provider_failures_as_blocked(tmp_path: Path) -> None:
    def live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "OpenAI Agents SDK runtime failed: provider_transient_failure; "
            "Error code: 502 - bad_response_status_code"
        )

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-provider-blocked",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["blocked"] == 3
    assert payload["aggregate"]["failed"] == 0
    assert payload["aggregate"]["failure_classes"] == {"model_or_provider_unavailable": 3}
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "model_or_provider_unavailable"
    assert result["grader_outputs"]["runner"]["status"] == "blocked"


def test_eval_runner_classifies_live_tool_argument_failures_as_agent_failures(
    tmp_path: Path,
) -> None:
    def live_product_runner(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(
            "OpenAI Agents SDK runtime failed: agent_cli_failure; "
            "Error code: 400 - {'error': {'message': "
            "'invalid params, invalid function arguments json string, "
            "tool_call_id: call_function_1 (2013)', 'code': 'invalid_prompt'}}"
        )

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-tool-argument-invalid",
        agent_engine="openai-agents-sdk",
        provider_profile="minimax-responses",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["blocked"] == 0
    assert payload["aggregate"]["failure_classes"] == {"tool_argument_invalid": 3}
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "tool_argument_invalid"
    assert result["grader_outputs"]["runner"]["status"] == "failed"


def test_live_surface_product_accepts_sdk_run_result_without_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

    sleeps: list[float] = []

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0313" / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text(
            json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
        )
        (run_dir / "live_status.json").write_text('{"phase": "finishing-sdk"}\n')
        return _completed_process(returncode=0)

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)
    monkeypatch.setattr(live_exec.time, "sleep", fake_sleep)

    result = live_exec.run_live_surface_product(
        **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=1.0)
    )

    assert sleeps == []
    assert result["eval_effective_run_dir"].endswith("surface-run/0615_0313/seed-7")


def test_live_surface_product_rejects_failed_live_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import roboclaws.evals.live_execution as live_exec

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0314" / "seed-7"
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / "run_result.json").write_text(
            json.dumps(_run_result(run_dir, completion_status="success")) + "\n"
        )
        (run_dir / "live_status.json").write_text(
            '{"phase": "failed", "exit_status": 1, "reason": "provider failure"}\n'
        )
        return _completed_process(returncode=0)

    _patch_live_surface_popen(monkeypatch, live_exec, fake_run)

    with pytest.raises(RuntimeError, match="live surface run reported failed status 1"):
        live_exec.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=1.0)
        )


def test_live_surface_env_sets_provider_and_model_keys(tmp_path: Path) -> None:
    kwargs: dict[str, Any] = {
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "kimi-openai-chat",
        "model": "kimi-k2.7-code",
    }

    env = live_surface_env(kwargs, base_env={"PATH": "/bin"})

    assert env["PATH"] == "/bin"
    assert env["ROBOCLAWS_PROVIDER_PROFILE"] == "kimi-openai-chat"
    assert env["ROBOCLAWS_OPENAI_AGENTS_MODEL"] == "kimi-k2.7-code"
