from __future__ import annotations

import json
import signal
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
    popen_kwargs: dict[str, Any] = {}
    sleeps: list[float] = []
    clock = {"now": 0.0}

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    def fake_monotonic() -> float:
        return clock["now"]

    class FakePopen:
        pid = 4321

        def __init__(
            self,
            plan: Any,
            *,
            stdout: Any = None,
            stderr: Any = None,
            **_kwargs: Any,
        ) -> None:
            popen_kwargs.update(_kwargs)
            output_arg = next(item for item in plan.overrides if item.startswith("output_dir="))
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
            if stdout is not None:
                stdout.write(f"Artifacts: {run_dir}\n")
            if stderr is not None:
                stderr.write("still running")
            nonlocal timeout_run_dir
            timeout_run_dir = run_dir
            self.terminated = False
            self.killed = False

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float | None = None) -> int:
            return 143

    monkeypatch.setattr(live_runtime, "spawn_launch_plan", FakePopen)
    monkeypatch.setattr(live_runtime.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(live_runtime.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(live_runtime.time, "sleep", fake_sleep)

    with pytest.raises(LiveEvalTimeoutError) as exc_info:
        live_runtime.run_live_surface_product(
            **_live_surface_kwargs(
                tmp_path / "trial-0000",
                live_timeout_s=50.0,
                live_stall_timeout_s=5.0,
            )
        )

    assert str(exc_info.value) == "live eval trial stalled after 5s without progress"
    assert exc_info.value.timeout_kind == "stall_timeout"
    assert exc_info.value.wall_clock_budget_s == 50.0
    assert exc_info.value.stall_timeout_s == 5.0
    assert exc_info.value.timeout_debug_snapshot["progress"]["observe"] == 3
    assert exc_info.value.live_status["phase"] == "running-sdk"
    assert sleeps == [1.0, 1.0, 1.0, 1.0, 1.0]
    assert timeout_run_dir is not None
    assert popen_kwargs["cwd"] == live_runtime.REPO_ROOT
    record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert record["returncode"] == "stall_timeout"
    assert record["timeout_kind"] == "stall_timeout"
    assert record["timeout_s"] == 50.0
    assert record["wall_clock_budget_s"] == 50.0
    assert record["stall_timeout_s"] == 5.0
    assert record["timeout_completion_grace_s"] == 30.0
    assert record["timeout_child_cleanup"]["status"] == "server_pid_unavailable"
    assert record["timeout_debug_snapshot"]["timeout_kind"] == "stall_timeout"
    assert record["timeout_debug_snapshot"]["eval_wall_clock_budget_s"] == 50.0
    assert record["timeout_debug_snapshot"]["eval_stall_timeout_s"] == 5.0
    assert record["timeout_debug_snapshot"]["last_trace_event"] == "observe:response"
    assert record["timeout_debug_snapshot"]["effective_run_dir"].endswith(
        "surface-run/0615_0311/seed-7"
    )


def test_live_surface_timeout_terminates_the_entire_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, signal.Signals]] = []

    class FakeProcess:
        pid = 4321

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 5.0
            return 143

    monkeypatch.setattr(
        live_runtime.os,
        "killpg",
        lambda process_group_id, sig: signals.append((process_group_id, sig)),
    )

    live_runtime._terminate_live_surface_process(FakeProcess())  # type: ignore[arg-type]

    assert signals == [
        (4321, signal.SIGTERM),
        (4321, signal.SIGKILL),
    ]


def test_live_eval_wall_clock_budget_timeout_reaches_failed_result(
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
            timeout_kind="wall_clock_budget_exhausted",
            wall_clock_budget_s=300.0,
            stall_timeout_s=120.0,
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
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_timeout_s=300.0,
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 3
    assert payload["aggregate"]["blocked"] == 0
    result = payload["results"][0]
    runner = result["grader_outputs"]["runner"]
    assert runner["status"] == "failed"
    assert result["failure_class"] == "budget_exhausted"
    assert runner["error_type"] == "LiveEvalTimeoutError"
    assert runner["live_status_phase"] == "running-sdk"
    assert runner["timeout_kind"] == "wall_clock_budget_exhausted"
    assert runner["wall_clock_budget_s"] == 300.0
    assert runner["stall_timeout_s"] == 120.0
    assert runner["effective_run_dir"].endswith("surface-run/seed-7")
    assert runner["timeout_debug_snapshot"]["last_trace_event"] == "metric_map:response"


def test_live_surface_product_records_wall_clock_budget_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = {"now": 0.0}
    progress_count = {"value": 0}

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    class FakePopen:
        pid = 4322

        def __init__(
            self,
            plan: Any,
            *,
            stdout: Any = None,
            **_kwargs: Any,
        ) -> None:
            output_arg = next(item for item in plan.overrides if item.startswith("output_dir="))
            output_dir = Path(output_arg.removeprefix("output_dir="))
            self.run_dir = output_dir / "0615_0312" / "seed-7"
            self.run_dir.mkdir(parents=True, exist_ok=True)
            if stdout is not None:
                stdout.write(f"Artifacts: {self.run_dir}\n")
            self.terminated = False

        def poll(self) -> int | None:
            progress_count["value"] += 1
            (self.run_dir / "live_status.json").write_text(
                json.dumps(
                    {
                        "phase": "running-sdk",
                        "debug_snapshot": {
                            "schema": "molmo_live_timeout_debug_snapshot_v1",
                            "trace_event_count": progress_count["value"],
                            "last_trace_event": f"observe:{progress_count['value']}",
                            "progress": {"observe": progress_count["value"], "done": 0},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return None

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 143

    monkeypatch.setattr(live_runtime, "spawn_launch_plan", FakePopen)
    monkeypatch.setattr(live_runtime.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(live_runtime.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(live_runtime.time, "sleep", fake_sleep)

    with pytest.raises(LiveEvalTimeoutError) as exc_info:
        live_runtime.run_live_surface_product(
            **_live_surface_kwargs(
                tmp_path / "trial-0000",
                live_timeout_s=5.0,
                live_stall_timeout_s=30.0,
            )
        )

    assert str(exc_info.value) == "live eval trial exceeded wall-clock budget after 5s"
    assert exc_info.value.timeout_kind == "wall_clock_budget_exhausted"
    record = json.loads((tmp_path / "trial-0000" / "live_eval_command.json").read_text())
    assert record["returncode"] == "wall_clock_budget_exhausted"
    assert record["timeout_kind"] == "wall_clock_budget_exhausted"
    assert record["wall_clock_budget_s"] == 5.0
    assert record["stall_timeout_s"] == 30.0
    assert record["timeout_debug_snapshot"]["timeout_kind"] == "wall_clock_budget_exhausted"
    assert record["timeout_debug_snapshot"]["progress"]["observe"] > 1


def _live_surface_kwargs(
    run_dir: Path,
    *,
    live_timeout_s: float | None = None,
    live_stall_timeout_s: float | None = None,
) -> dict[str, Any]:
    return {
        "output_dir": run_dir,
        "seed": 7,
        "task_prompt": "帮我收拾这个房间",
        "backend": "api_semantic_synthetic",
        "cleanup_profile": "smoke",
        "scene_source": "procthor-10k-val",
        "scene_index": 0,
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "kimi-openai-chat",
        "model": None,
        "live_timeout_s": live_timeout_s,
        "live_stall_timeout_s": live_stall_timeout_s,
    }
