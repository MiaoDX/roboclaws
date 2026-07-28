from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[3] / "skills" / "household-world" / "scripts" / "scratchpad.py"
)


def _run_scratchpad(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_scratchpad_script_rejects_malformed_present_source(tmp_path: Path) -> None:
    scratchpad = tmp_path / "cleanup_scratch.json"
    scratchpad.write_text("{bad json\n", encoding="utf-8")

    completed = _run_scratchpad("validate", "--path", str(scratchpad))

    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "skill scratchpad source must contain valid JSON object" in completed.stderr
    assert str(scratchpad) in completed.stderr


def test_scratchpad_script_rejects_non_object_result_json(tmp_path: Path) -> None:
    scratchpad = tmp_path / "cleanup_scratch.json"
    scratchpad.write_text(json.dumps(_scratchpad_payload()) + "\n", encoding="utf-8")

    completed = _run_scratchpad(
        "record-result",
        "--path",
        str(scratchpad),
        "--result-json",
        "[]",
    )

    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "routine result JSON source must contain a JSON object" in completed.stderr
    assert "--result-json" in completed.stderr


def test_scratchpad_script_records_valid_result_json(tmp_path: Path) -> None:
    scratchpad = tmp_path / "cleanup_scratch.json"
    scratchpad.write_text(json.dumps(_scratchpad_payload()) + "\n", encoding="utf-8")

    completed = _run_scratchpad(
        "record-result",
        "--path",
        str(scratchpad),
        "--result-json",
        json.dumps(
            {
                "object_id": "apple",
                "fixture_id": "table",
                "ok": False,
                "routine": "trace_preserving_cleanup",
                "failed_phase": "pick",
                "error_reason": "blocked",
            }
        ),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(scratchpad.read_text(encoding="utf-8"))
    assert payload["observed_handles"]["apple"]["fixture_id"] == "table"
    assert payload["failed_attempts"][0]["failed_phase"] == "pick"


def _scratchpad_payload() -> dict[str, object]:
    return {
        "schema": "molmo_cleanup_skill_scratchpad_v1",
        "authoritative": False,
        "observed_handles": {},
        "waypoints": {},
        "current_intent": None,
        "failed_attempts": [],
        "reconciliation_notes": [],
        "notes": [],
    }
