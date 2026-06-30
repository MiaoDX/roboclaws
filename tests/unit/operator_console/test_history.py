from __future__ import annotations

import json
import os
from pathlib import Path

from roboclaws.operator_console.history import latest_run_payload
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection

from tests.unit.operator_console.conftest import MUJOCO_OPENAI_AGENTS_OPEN_TASK  # noqa: F401  re-exported for tests


def test_latest_run_payload_scans_runs_and_nested_attempt_artifacts(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = (
        "20260609-102534-molmospaces-procthor-objaverse-val-0-mujoco-open-task-"
        "openai-agents-sdk-world-public-labels"
    )
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0609_1025" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "failed", "exit_status": 1}),
        encoding="utf-8",
    )
    report = attempt_dir / "report.html"
    report.write_text("<html>report</html>", encoding="utf-8")
    os.utime(report, (20, 20))

    payload = latest_run_payload(tmp_path)

    assert payload["run_id"] == run_id
    assert payload["selection_id"] == route.id
    assert payload["launch_label"] == route.label
    assert payload["display_run_id"] == "0609_1025/seed-7"
    assert payload["display_run_dir"] == str(attempt_dir.resolve())
    assert payload["phase"] == "failed"


def test_latest_run_payload_falls_back_to_scanning_runs_directory(tmp_path: Path) -> None:
    run_dir = console_output_root(tmp_path) / "runs" / "manual-run"
    run_dir.mkdir(parents=True)
    (run_dir / "trace.jsonl").write_text("{}\n", encoding="utf-8")

    payload = latest_run_payload(tmp_path)

    assert payload["run_id"] == "manual-run"
    assert payload["run_dir"] == str(run_dir.resolve())


def test_latest_run_payload_surfaces_malformed_run_sidecar(tmp_path: Path) -> None:
    run_dir = console_output_root(tmp_path) / "runs" / "bad-sidecar"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text("{bad-state", encoding="utf-8")
    (run_dir / "trace.jsonl").write_text("{}\n", encoding="utf-8")

    payload = latest_run_payload(tmp_path)

    assert payload["run_id"] == "bad-sidecar"
    assert payload["phase"] == "failed"
    assert payload["status"] == "source_error"
    assert payload["error"] == "operator history source error: Operator State"
    assert payload["source_errors"] == [
        {
            "label": "Operator State",
            "path": str((run_dir / "operator_state.json").resolve()),
            "reason": "invalid JSON at line 1 column 2",
        }
    ]
