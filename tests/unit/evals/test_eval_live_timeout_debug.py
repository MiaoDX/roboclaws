from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals import live_runtime
from roboclaws.evals.live_timeout import LiveEvalTimeoutError
from roboclaws.evals.runner import run_eval_suite


def test_live_surface_product_records_timeout_debug_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    timeout_run_dir: Path | None = None
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_run(command: list[str], **_kwargs: Any) -> Any:
        output_arg = next(item for item in command if item.startswith("output_dir="))
        output_dir = Path(output_arg.removeprefix("output_dir="))
        run_dir = output_dir / "0615_0311" / "seed-7"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "live_status.json").write_text(
            json.dumps(
                {
                    "phase": "running-sdk",
                    "debug_snapshot": {
                        "schema": "molmo_live_timeout_debug_snapshot_v1",
                        "elapsed_s": 299.0,
                        "run_result_present": False,
                        "report_present": False,
                        "last_trace_event": "observe:response",
                        "progress": {"observe": 3, "done": 0},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        nonlocal timeout_run_dir
        timeout_run_dir = run_dir
        raise live_runtime.subprocess.TimeoutExpired(
            cmd=command,
            timeout=5.0,
            output=f"Artifacts: {run_dir}\n".encode(),
            stderr=b"still running",
        )

    monkeypatch.setattr(live_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(live_runtime.time, "sleep", fake_sleep)

    with pytest.raises(LiveEvalTimeoutError) as exc_info:
        live_runtime.run_live_surface_product(
            **_live_surface_kwargs(tmp_path / "trial-0000", live_timeout_s=5.0)
        )

    assert str(exc_info.value) == "live eval trial timed out after 5s"
    assert exc_info.value.timeout_debug_snapshot["progress"]["observe"] == 3
    assert exc_info.value.live_status["phase"] == "running-sdk"
    assert sleeps == []
    assert timeout_run_dir is not None
    record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert record["returncode"] == "timeout"
    assert record["timeout_completion_grace_s"] == 30.0
    assert record["timeout_child_cleanup"]["status"] == "server_pid_unavailable"
    assert record["timeout_debug_snapshot"]["last_trace_event"] == "observe:response"
    assert record["timeout_debug_snapshot"]["effective_run_dir"].endswith(
        "surface-run/0615_0311/seed-7"
    )


def test_live_eval_timeout_snapshot_reaches_blocked_result(
    tmp_path: Path,
) -> None:
    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"]) / "surface-run" / "seed-7"
        run_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "schema": "molmo_live_timeout_debug_snapshot_v1",
            "elapsed_s": 300.0,
            "run_result_present": False,
            "report_present": False,
            "last_trace_event": "metric_map:response",
            "progress": {"metric_map": 1, "done": 0},
        }
        raise LiveEvalTimeoutError(
            "live eval trial timed out after 300s",
            timeout_s=300.0,
            effective_run_dir=run_dir,
            live_status={"phase": "running-sdk"},
            timeout_debug_snapshot=snapshot,
            command_record={},
        )

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-timeout-debug-snapshot",
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        live_execution="run",
        live_timeout_s=300.0,
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["blocked"] == 3
    result = payload["results"][0]
    runner = result["grader_outputs"]["runner"]
    assert runner["status"] == "blocked"
    assert runner["error_type"] == "LiveEvalTimeoutError"
    assert runner["live_status_phase"] == "running-sdk"
    assert runner["effective_run_dir"].endswith("surface-run/seed-7")
    assert runner["timeout_debug_snapshot"]["last_trace_event"] == "metric_map:response"


def _live_surface_kwargs(run_dir: Path, *, live_timeout_s: float | None = None) -> dict[str, Any]:
    return {
        "output_dir": run_dir,
        "seed": 7,
        "task_prompt": "帮我收拾这个房间",
        "backend": "api_semantic_synthetic",
        "cleanup_profile": "smoke",
        "scene_source": "procthor-10k-val",
        "scene_index": 0,
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "codex-router-responses",
        "model": None,
        "live_timeout_s": live_timeout_s,
    }
