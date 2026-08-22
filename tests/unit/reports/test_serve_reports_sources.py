from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVE_REPORTS_SCRIPT = REPO_ROOT / "scripts" / "reports" / "serve_reports.py"


def _load_serve_reports_script():
    spec = importlib.util.spec_from_file_location(
        "serve_reports_sources",
        SERVE_REPORTS_SCRIPT,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_report_server_run_summary_missing_source_stays_empty(tmp_path: Path) -> None:
    serve_reports = _load_serve_reports_script()

    assert serve_reports._run_summary(tmp_path / "missing_run_result.json") == {}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"report server run result source must contain valid JSON object: .*run_result\.json",
        ),
        (
            "[]\n",
            r"report server run result source must contain a JSON object: .*run_result\.json",
        ),
    ],
)
def test_report_server_run_summary_rejects_bad_present_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    serve_reports = _load_serve_reports_script()
    run_result = tmp_path / "run_result.json"
    run_result.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        serve_reports._run_summary(run_result)


def _write_completed_eval_run(
    serve_reports: object, root: Path, run_id: str, *, finalized_at: str
) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    report = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "profile": "baseline-refresh",
        "observability_decision_report": {
            "state": "ready_with_limitations",
            "harness_health": {"passed": 1, "failed": 0, "blocked": 0},
        },
    }
    files = {
        "eval_harness.json": json.dumps(report, sort_keys=True) + "\n",
        "eval_harness.md": "# Eval Harness\n",
        "eval_harness.html": "<!doctype html><title>Eval Harness</title>\n",
    }
    for filename, content in files.items():
        (run_dir / filename).write_text(content, encoding="utf-8")
    marker = {
        "schema": serve_reports.EVAL_COMPLETION_SCHEMA,
        "run_id": run_id,
        "finalized_at": finalized_at,
        "artifacts": {
            filename: hashlib.sha256(content.encode()).hexdigest()
            for filename, content in files.items()
        },
    }
    (run_dir / serve_reports.EVAL_COMPLETION_MARKER).write_text(
        json.dumps(marker), encoding="utf-8"
    )
    return run_dir


def test_completed_eval_runs_require_marker_and_matching_hashes(tmp_path: Path) -> None:
    serve_reports = _load_serve_reports_script()
    run_dir = _write_completed_eval_run(
        serve_reports, tmp_path, "run-1", finalized_at="2026-08-22T01:00:00Z"
    )

    runs = serve_reports._find_completed_eval_harness_runs(tmp_path, max_reports=0)
    assert [item["run_id"] for item in runs] == ["run-1"]

    (run_dir / "eval_harness.html").write_text("changed", encoding="utf-8")
    assert serve_reports._find_completed_eval_harness_runs(tmp_path, max_reports=0) == []


def test_completed_eval_runs_are_ordered_by_finalized_time(tmp_path: Path) -> None:
    serve_reports = _load_serve_reports_script()
    _write_completed_eval_run(serve_reports, tmp_path, "older", finalized_at="2026-08-22T01:00:00Z")
    _write_completed_eval_run(serve_reports, tmp_path, "newer", finalized_at="2026-08-22T02:00:00Z")

    runs = serve_reports._find_completed_eval_harness_runs(tmp_path, max_reports=0)
    assert [item["run_id"] for item in runs] == ["newer", "older"]


def test_completed_eval_runs_only_scan_direct_run_directories(tmp_path: Path) -> None:
    serve_reports = _load_serve_reports_script()
    nested = tmp_path / "nested" / "run-1"
    _write_completed_eval_run(
        serve_reports, nested.parent, "run-1", finalized_at="2026-08-22T01:00:00Z"
    )

    assert serve_reports._find_completed_eval_harness_runs(tmp_path, max_reports=0) == []


def test_eval_harness_root_index_omits_nested_trial_reports(tmp_path: Path) -> None:
    serve_reports = _load_serve_reports_script()
    root = tmp_path / "eval-harness"
    _write_completed_eval_run(serve_reports, root, "run-1", finalized_at="2026-08-22T01:00:00Z")
    nested_report = root / "run-1" / "rows" / "trial" / "report.html"
    nested_report.parent.mkdir(parents=True)
    nested_report.write_text("trial", encoding="utf-8")
    handler = object.__new__(serve_reports.ReportRequestHandler)
    handler.report_root = root.resolve()
    handler.index_title = "Eval Observability"
    handler.max_reports = 100

    rendered = handler._index_html()

    assert "run-1" in rendered
    assert "rows/trial/report.html" not in rendered
