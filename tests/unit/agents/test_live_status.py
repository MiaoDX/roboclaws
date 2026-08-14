from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents import live_status_cli, live_status_summary


def test_open_ended_status_uses_claim_headline(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "seed-7"
    run_dir.mkdir()
    result = live_status_summary._result_summary(
        {
            "task_surface": "household-world",
            "task_intent": "open-ended",
            "cleanup_status": "failed",
            "completion_status": "failed",
            "sweep_coverage_rate": 0.875,
            "policy": "sdk_agent",
            "score": {"restored_count": 0, "total_targets": 5},
            "agent_completion_claim": {
                "schema": "roboclaws_agent_completion_claim_v1",
                "completion_summary": "Found an apple that satisfies the thirst goal.",
            },
        },
        run_dir,
    )
    summary = _empty_summary(run_dir)
    summary["result"] = result

    live_status_summary._print_summary(summary)

    output = capsys.readouterr().out
    assert "result: open-ended claim=present cleanup_score=failed" in output
    assert "claim: Found an apple that satisfies the thirst goal." in output
    assert "result: failed completion=failed" not in output


def test_status_cli_prints_current_sdk_run(tmp_path: Path, capsys) -> None:
    run_dir = _write_run(tmp_path / "seed-7")

    status = live_status_cli.main([str(run_dir)])

    assert status == 0
    output = capsys.readouterr().out
    assert "Molmo cleanup live run" in output
    assert "result: success completion=success restored=1/1" in output
    assert "openai-agents-events.jsonl" in output
    assert "codex-events.jsonl" not in output


def test_default_discovery_ignores_empty_newer_seed_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    search_root = tmp_path / "household-world"
    evidence_run = _write_run(search_root / "run-a" / "seed-7")
    empty_run = search_root / "run-b" / "seed-8"
    empty_run.mkdir(parents=True)
    evidence_run.touch()
    empty_run.touch()
    monkeypatch.setattr(live_status_summary, "DEFAULT_SEARCH_ROOT", search_root)

    assert live_status_summary._resolve_run_dir(None) == evidence_run


def test_parent_discovery_ignores_empty_newer_seed_dir(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    evidence_run = _write_run(run_root / "seed-7")
    empty_run = run_root / "seed-8"
    empty_run.mkdir()
    evidence_run.touch()
    empty_run.touch()

    assert live_status_summary._resolve_run_dir(run_root) == evidence_run


def test_status_cli_rejects_empty_explicit_run_dir(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "empty"
    run_dir.mkdir()

    status = live_status_cli.main([str(run_dir)])

    assert status == 1
    assert "run path has no live-run evidence" in capsys.readouterr().err


def test_status_cli_fails_aloud_on_malformed_live_timing(tmp_path: Path, capsys) -> None:
    run_dir = _write_run(tmp_path / "seed-7")
    (run_dir / "live_timing.json").write_text("{not-json", encoding="utf-8")

    status = live_status_cli.main([str(run_dir)])

    assert status == 1
    assert "live-run summary source must contain valid JSON object" in capsys.readouterr().err


def test_status_cli_fails_aloud_on_non_object_trace_row(tmp_path: Path, capsys) -> None:
    run_dir = _write_run(tmp_path / "seed-7")
    (run_dir / "trace.jsonl").write_text('["not", "an", "object"]\n', encoding="utf-8")

    status = live_status_cli.main([str(run_dir)])

    assert status == 1
    assert "live-run summary trace source row must contain a JSON object" in capsys.readouterr().err


def _write_run(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    (run_dir / "live_timing.json").write_text(
        json.dumps(
            {
                "runtime": "openai-agents-live",
                "provider_profile": "kimi-openai-chat",
                "openai_agents": {"model_api_time_s": 2.5},
                "runner_timing": {"total_elapsed_s": 10.0, "openai_agents_elapsed_s": 8.0},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event": "response", "tool": "done", "response": {"ok": True}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_surface": "household-world",
                "task_intent": "cleanup",
                "cleanup_status": "success",
                "completion_status": "success",
                "score": {"restored_count": 1, "total_targets": 1},
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _empty_summary(run_dir: Path) -> dict[str, object]:
    return {
        "run_dir": str(run_dir),
        "session": "",
        "tmux_state": "stopped",
        "runner": {
            "phase": "finished",
            "exit_status": 0,
            "elapsed_s": 1.0,
            "started_at": "unknown",
            "finished_at": "unknown",
            "debug_snapshot": {},
        },
        "trace": {
            "events": 0,
            "requests": 0,
            "responses": 0,
            "last_event": "none",
            "last_response": "none",
            "progress": {
                "observes": 0,
                "navigate_to_object": 0,
                "picks": 0,
                "navigate_to_receptacle": 0,
                "opens": 0,
                "places": 0,
                "place_inside": 0,
                "closes": 0,
                "done": 0,
            },
        },
        "timing": {"runner": {}, "mcp": {}},
        "result": {"state": "pending"},
        "artifacts": {},
        "driver_tail": "",
    }
