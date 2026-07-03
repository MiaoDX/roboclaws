from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "household-world"
    / "scripts"
    / "target_query_recovery.py"
)


def _run_target_query(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_target_query_script_rejects_malformed_runtime_map_source(tmp_path: Path) -> None:
    runtime_map = tmp_path / "runtime_metric_map.json"
    runtime_map.write_text("{bad json\n", encoding="utf-8")

    completed = _run_target_query(str(runtime_map), "sink_01")

    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "runtime_metric_map source must contain valid JSON object" in completed.stderr
    assert str(runtime_map) in completed.stderr


def test_target_query_script_rejects_non_object_runtime_map_source(tmp_path: Path) -> None:
    runtime_map = tmp_path / "runtime_metric_map.json"
    runtime_map.write_text("[]\n", encoding="utf-8")

    completed = _run_target_query(str(runtime_map), "sink_01")

    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "runtime_metric_map source must contain a JSON object" in completed.stderr
    assert str(runtime_map) in completed.stderr


def test_target_query_script_resolves_valid_runtime_map_source(tmp_path: Path) -> None:
    runtime_map = tmp_path / "runtime_metric_map.json"
    runtime_map.write_text(json.dumps(_runtime_map_payload()) + "\n", encoding="utf-8")

    completed = _run_target_query(
        str(runtime_map),
        "sink_01",
        "--operation",
        "destination",
        "--max-results",
        "1",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "matched"
    assert payload["match_count"] == 1
    assert payload["best_match"]["candidate_fixture_id"] == "sink_01"
    assert payload["private_truth_included"] is False


def _runtime_map_payload() -> dict[str, object]:
    return {
        "target_candidates": [
            {
                "candidate_id": "candidate_sink",
                "candidate_type": "destination",
                "query": "sink_01",
                "label": "Kitchen sink",
                "category": "sink",
                "target_actionability_status": "actionable",
                "candidate_fixture_id": "sink_01",
                "waypoint_id": "waypoint_sink",
                "confidence": 0.9,
            }
        ],
        "target_search_summary": {
            "viewpoint_budget": {
                "unvisited_waypoint_count": 0,
            },
            "inspection_observations": [{}],
        },
    }
