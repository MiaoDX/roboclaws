from __future__ import annotations

import json
from pathlib import Path

from roboclaws.agents.household_live_timeout_artifacts import (
    finalize_terminal_incomplete_bundle,
)


def test_timeout_finalization_writes_replayable_canonical_bundle(tmp_path: Path) -> None:
    run_dir = tmp_path / "attempt-001"
    views = run_dir / "robot_views" / "step-001"
    views.mkdir(parents=True)
    (views / "fpv.png").write_bytes(b"frame")
    agent_view = {"schema": "household_agent_view_v2", "public": {"room": "kitchen"}}
    runtime_map = {"schema": "runtime_metric_map_v1", "observed_objects": []}
    (run_dir / "agent_view.json").write_text(json.dumps(agent_view), encoding="utf-8")
    (run_dir / "runtime_metric_map.json").write_text(json.dumps(runtime_map), encoding="utf-8")
    private_evaluation = {"schema": "private_evaluation_v1", "score": {"restored": 2}}
    (run_dir / "private_evaluation.json").write_text(
        json.dumps(private_evaluation), encoding="utf-8"
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"event": "request", "tool": "observe", "request": {"secret": 1}}),
                json.dumps({"event": "response", "tool": "observe", "response": {"ok": True}}),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    first = finalize_terminal_incomplete_bundle(run_dir, reason="stall_timeout")
    second = finalize_terminal_incomplete_bundle(run_dir, reason="stall_timeout")

    assert first == second
    assert first["final_status"] == "terminal_incomplete"
    assert first["capability_status"] == "terminal_incomplete"
    assert first["artifact_status"] == "ready"
    assert first["diagnostics"] == {
        "reason": "stall_timeout",
        "last_tool": "observe",
        "progress_counters": {
            "trace_events": 2,
            "tool_responses": 1,
            "tool_response_counts": {"observe": 1},
            "captured_frames": 1,
        },
    }
    for name in (
        "run_result.json",
        "report.html",
        "trace.jsonl",
        "agent_view.json",
        "runtime_metric_map.json",
        "private_evaluation.json",
    ):
        assert (run_dir / name).is_file()
    assert json.loads((run_dir / "agent_view.json").read_text()) == agent_view
    assert json.loads((run_dir / "runtime_metric_map.json").read_text()) == runtime_map
    assert json.loads((run_dir / "private_evaluation.json").read_text()) == private_evaluation
    report = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "terminal_incomplete" in report
    assert "secret" not in report
    assert "room" not in report


def test_timeout_finalization_escapes_public_diagnostic_reason(tmp_path: Path) -> None:
    finalize_terminal_incomplete_bundle(tmp_path, reason='<script>alert("x")</script>')

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    private = json.loads((tmp_path / "private_evaluation.json").read_text())
    assert private["capability_success"] is False
