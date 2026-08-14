from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import planner_proof_bundle_validation
from tests.contract.checkers.check_molmo_planner_proof_bundle_runner_result_support import (
    _runner_manifest,
    _write_manifest_and_report,
    _write_runner_artifact,
)


def test_checker_rejects_missing_report(tmp_path: Path) -> None:
    manifest = _write_runner_artifact(tmp_path)
    (tmp_path / "report.html").unlink()

    with pytest.raises(AssertionError):
        planner_proof_bundle_validation.assert_runner_result(manifest, tmp_path)


def test_checker_rejects_report_without_bundle_marker(tmp_path: Path) -> None:
    manifest = _write_runner_artifact(tmp_path)
    (tmp_path / "report.html").write_text("<h1>unrelated report</h1>", encoding="utf-8")

    with pytest.raises(AssertionError):
        planner_proof_bundle_validation.assert_runner_result(manifest, tmp_path)


def test_checker_rejects_missing_command_report_path(tmp_path: Path) -> None:
    manifest = _runner_manifest(tmp_path)
    del manifest["commands"][0]["report"]
    _write_manifest_and_report(tmp_path, manifest)

    with pytest.raises(AssertionError):
        planner_proof_bundle_validation.assert_runner_result(manifest, tmp_path)


def test_checker_accepts_timeout_stage_evidence_from_artifact(tmp_path: Path) -> None:
    manifest = _runner_manifest(tmp_path)
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "planner_probe_stdout.txt").write_text("stdout", encoding="utf-8")
    (proof_dir / "planner_probe_stderr.txt").write_text("stderr", encoding="utf-8")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "artifacts": {
                    "stdout": "planner_probe_stdout.txt",
                    "stderr": "planner_probe_stderr.txt",
                },
                "manipulation_evidence": {
                    "execution_attempted": False,
                    "blockers": [{"code": "timeout", "message": "Probe exceeded 1.0s"}],
                    "last_worker_stage": "rby1m_config_import",
                    "worker_stage_events": [
                        {"elapsed_s": 0.1, "event": "worker_start", "stage": "worker_start"},
                        {
                            "elapsed_s": 3.2,
                            "event": "rby1m_config_import_start",
                            "stage": "rby1m_config_import",
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    _write_manifest_and_report(tmp_path, manifest)

    planner_proof_bundle_validation.assert_runner_result(
        manifest, tmp_path, require_proof_outputs=True
    )
