from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents.live_timeout_debug import timeout_debug_snapshot


def test_timeout_debug_snapshot_marks_model_call_in_flight(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "trace.jsonl",
        [
            {"event": "request", "tool": "observe", "wallclock_elapsed": 1.0},
            {"event": "response", "tool": "observe", "wallclock_elapsed": 2.0},
        ],
    )
    _write_jsonl(
        run_dir / "openai-agents-events.jsonl",
        [
            {"event": "model_service_attempt", "ts_epoch": 90.0},
            {"event": "model_racing_arm_start", "ts_epoch": 95.0},
        ],
    )

    snapshot = timeout_debug_snapshot(
        run_dir,
        started_at_epoch=0.0,
        captured_at_epoch=100.0,
    )

    assert snapshot["timeout_signal"] == "model_call_in_flight"
    assert snapshot["progress"]["observe"] == 1
    assert snapshot["progress"]["done"] == 0
    assert snapshot["model_service_attempt_count"] == 1
    assert snapshot["model_racing_arm_start_count"] == 1
    assert snapshot["last_openai_agents_event_age_s"] == 5.0


def test_timeout_debug_snapshot_marks_provider_failures(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "openai-agents-events.jsonl",
        [
            {"event": "model_service_attempt", "ts_epoch": 10.0},
            {"event": "model_service_failure", "ts_epoch": 11.0},
        ],
    )

    snapshot = timeout_debug_snapshot(
        run_dir,
        started_at_epoch=0.0,
        captured_at_epoch=15.0,
    )

    assert snapshot["timeout_signal"] == "provider_failures_seen"
    assert snapshot["model_service_failure_count"] == 1
    assert snapshot["last_openai_agents_event"] == "model_service_failure"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
