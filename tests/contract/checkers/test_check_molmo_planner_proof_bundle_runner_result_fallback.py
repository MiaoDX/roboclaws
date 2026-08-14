from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household import planner_proof_bundle_validation
from tests.contract.checkers.check_molmo_planner_proof_bundle_runner_result_support import (
    _runner_manifest,
    _write_manifest_and_report,
)


def test_checker_requires_cleanup_rerun_outputs_for_cleanup_rerun_status(
    tmp_path: Path,
) -> None:
    cleanup_dir = tmp_path / "cleanup_rerun"
    manifest = _runner_manifest(tmp_path)
    manifest["status"] = "cleanup_rerun"
    manifest["cleanup_command"] = [
        "python",
        "cleanup.py",
        "--output-dir",
        str(cleanup_dir),
    ]
    manifest["cleanup_rerun"] = {
        "output_dir": str(cleanup_dir),
        "run_result": str(cleanup_dir / "run_result.json"),
        "report": str(cleanup_dir / "report.html"),
    }
    _write_manifest_and_report(tmp_path, manifest)

    with pytest.raises(AssertionError):
        planner_proof_bundle_validation.assert_runner_result(manifest, tmp_path)

    cleanup_dir.mkdir()
    (cleanup_dir / "run_result.json").write_text("{}", encoding="utf-8")
    (cleanup_dir / "report.html").write_text("<h1>cleanup</h1>", encoding="utf-8")

    planner_proof_bundle_validation.assert_runner_result(manifest, tmp_path)
    planner_proof_bundle_validation.assert_runner_result(
        manifest,
        tmp_path,
        require_cleanup_rerun_output=True,
    )
