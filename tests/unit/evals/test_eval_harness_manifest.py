from __future__ import annotations

import hashlib
import json
from pathlib import Path

from roboclaws.evals.harness import runner
from roboclaws.evals.harness.publication import (
    COMPLETION_MARKER_NAME,
    COMPLETION_MARKER_SCHEMA,
    REPORT_FILENAMES,
)


def test_eval_harness_manifest_redacts_private_truth(tmp_path: Path) -> None:
    manifest = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "recommend",
        "budget": "focused",
        "signals": [],
        "summary": {"selected_row_count": 1},
        "private_evaluation": {"acceptable_destinations": ["sink"]},
        "rows": [
            {
                "schema": "roboclaws_eval_harness_row_v1",
                "row_id": "cleanup-capability-eval-suite",
                "row_kind": "eval_suite",
                "selected": True,
                "status": "not_run",
                "command_display": (
                    ".venv/bin/python -m roboclaws.evals.cli suite=cleanup_capability"
                ),
                "reason_selected": "cleanup changed",
                "skip_reason": "",
                "blocker_category": "",
                "private_goal_reference": {"hidden_targets": ["cup"]},
                "output_artifacts": [
                    "output/evals/cleanup_capability/demo/eval_results.json",
                ],
            }
        ],
    }

    runner._write_outputs(manifest, tmp_path)

    payload = json.loads((tmp_path / "eval_harness.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "roboclaws_eval_harness_manifest_v1"
    serialized = json.dumps(payload, sort_keys=True)
    assert "private_goal_reference" not in serialized
    assert "private_evaluation" not in serialized
    assert "acceptable_destinations" not in serialized
    assert "hidden_targets" not in serialized
    assert "cleanup-capability-eval-suite" in (tmp_path / "eval_harness.md").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "eval_harness.html").exists()
    assert not (tmp_path / COMPLETION_MARKER_NAME).exists()


def test_terminal_eval_harness_publishes_completion_marker_last(tmp_path: Path) -> None:
    manifest = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "budget": "focused",
        "profile": "baseline-refresh",
        "signals": [],
        "summary": {"selected_row_count": 1},
        "rows": [
            {
                "schema": "roboclaws_eval_harness_row_v1",
                "row_id": "terminal",
                "row_kind": "test_gate",
                "selected": True,
                "status": "ran",
                "outcome": "passed",
                "command_display": "true",
                "reason_selected": "unit test",
                "skip_reason": "",
                "blocker_category": "",
            }
        ],
    }

    runner._write_outputs(manifest, tmp_path)

    marker = json.loads((tmp_path / COMPLETION_MARKER_NAME).read_text())
    assert marker["schema"] == COMPLETION_MARKER_SCHEMA
    assert marker["run_id"] == tmp_path.name
    assert marker["finalized_at"].endswith("Z")
    assert set(marker["artifacts"]) == set(REPORT_FILENAMES)
    for filename, digest in marker["artifacts"].items():
        assert hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest() == digest


def test_rewriting_nonterminal_harness_removes_stale_completion_marker(tmp_path: Path) -> None:
    (tmp_path / COMPLETION_MARKER_NAME).write_text("{}\n", encoding="utf-8")
    manifest = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "recommend",
        "budget": "focused",
        "signals": [],
        "summary": {"selected_row_count": 0},
        "rows": [],
    }

    runner._write_outputs(manifest, tmp_path)

    assert not (tmp_path / COMPLETION_MARKER_NAME).exists()


def test_eval_harness_row_reflects_failed_eval_aggregate(tmp_path: Path) -> None:
    results_dir = tmp_path / "evals" / "household_world_cleanup_capability" / "live"
    results_dir.mkdir(parents=True)
    (results_dir / "eval_results.json").write_text(
        json.dumps(
            {
                "aggregate": {
                    "total": 3,
                    "passed": 0,
                    "failed": 3,
                    "blocked": 0,
                    "failure_classes": {"harness_bug_unclassified": 3},
                }
            }
        ),
        encoding="utf-8",
    )
    row = {
        "row_kind": "live_agent_eval",
        "status": "ran",
        "outcome": "passed",
        "output_artifacts": [str(results_dir / "eval_results.json")],
    }

    runner._classify_eval_result_row(row)

    assert row["outcome"] == "failed"
    assert row["failure_class"] == "harness_bug_unclassified"
    assert row["eval_aggregate"] == {
        "total": 3,
        "passed": 0,
        "failed": 3,
        "blocked": 0,
        "failure_classes": {"harness_bug_unclassified": 3},
    }


def test_eval_harness_attaches_and_reports_phoenix_projection(tmp_path: Path) -> None:
    output_root = tmp_path / "evals"
    output_dir = output_root / "household_world_smoke_regression" / "unit"
    output_dir.mkdir(parents=True)
    (output_dir / "eval_results.json").write_text("{}\n", encoding="utf-8")
    (output_dir / "eval_report.html").write_text("<html></html>\n", encoding="utf-8")
    (output_dir / "phoenix_projection.json").write_text(
        json.dumps(
            {
                "schema": "roboclaws_phoenix_eval_projection_v3",
                "state": "unavailable",
                "reason": "phoenix_connection_failed",
            }
        ),
        encoding="utf-8",
    )
    row = {
        "row_id": "smoke",
        "row_kind": "eval_suite",
        "selected": True,
        "status": "ran",
        "command": [f"output_dir={output_root}", "stamp=unit"],
        "command_display": "eval smoke",
    }

    runner._attach_eval_outputs(row)

    assert row["phoenix_projection"] == {
        "state": "unavailable",
        "reason": "phoenix_connection_failed",
        "mapping": str(output_dir / "phoenix_projection.json"),
    }
    assert any(path.endswith("phoenix_projection.json") for path in row["output_artifacts"])
    manifest = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "budget": "smoke",
        "signals": [],
        "summary": {"selected_row_count": 1},
        "rows": [row],
    }
    harness_dir = tmp_path / "harness"
    harness_dir.mkdir()
    runner._write_outputs(manifest, harness_dir)
    assert "Phoenix projection: `unavailable`" in (
        tmp_path / "harness" / "eval_harness.md"
    ).read_text(encoding="utf-8")
    assert "unavailable (phoenix_connection_failed)" in (
        tmp_path / "harness" / "eval_harness.html"
    ).read_text(encoding="utf-8")


def test_eval_harness_row_fails_aloud_for_malformed_eval_results_json(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "eval_results.json"
    results_path.write_text("{not json", encoding="utf-8")
    row = {
        "row_kind": "eval_suite",
        "status": "ran",
        "outcome": "passed",
        "output_artifacts": [str(results_path)],
    }

    runner._classify_eval_result_row(row)

    assert row["outcome"] == "failed"
    assert row["failure_class"] == "harness_bug_unclassified"
    assert "eval_results.json source must contain valid JSON object" in row["eval_results_error"]


def test_eval_harness_row_fails_aloud_for_non_object_eval_results_json(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "eval_results.json"
    results_path.write_text("[]\n", encoding="utf-8")
    row = {
        "row_kind": "eval_suite",
        "status": "ran",
        "outcome": "passed",
        "output_artifacts": [str(results_path)],
    }

    runner._classify_eval_result_row(row)

    assert row["outcome"] == "failed"
    assert row["failure_class"] == "harness_bug_unclassified"
    assert "eval_results.json source must contain a JSON object" in row["eval_results_error"]


def test_eval_harness_exit_fails_for_failed_eval_outcome() -> None:
    manifest = {
        "rows": [
            {
                "selected": True,
                "status": "ran",
                "exit_code": 0,
                "outcome": "failed",
                "failure_class": "harness_bug_unclassified",
            }
        ]
    }

    assert runner._exit_status(manifest) == 1


def test_eval_harness_reports_show_outcome_and_failure_class(tmp_path: Path) -> None:
    manifest = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "budget": "focused",
        "signals": [],
        "summary": {"selected_row_count": 1},
        "rows": [
            {
                "schema": "roboclaws_eval_harness_row_v1",
                "row_id": "codex-cleanup-live-eval",
                "row_kind": "live_agent_eval",
                "selected": True,
                "status": "ran",
                "outcome": "failed",
                "failure_class": "harness_bug_unclassified",
                "command_display": (
                    ".venv/bin/python -m roboclaws.evals.cli suite=cleanup_capability"
                ),
                "reason_selected": "cleanup changed",
                "skip_reason": "",
                "blocker_category": "",
            }
        ],
    }

    runner._write_outputs(manifest, tmp_path)

    markdown = (tmp_path / "eval_harness.md").read_text(encoding="utf-8")
    html = (tmp_path / "eval_harness.html").read_text(encoding="utf-8")
    assert "- Outcome: `failed`" in markdown
    assert "- Failure class: `harness_bug_unclassified`" in markdown
    assert "<th>Outcome</th>" in html
    assert "harness_bug_unclassified" in html
