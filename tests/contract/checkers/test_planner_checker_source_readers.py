from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household import planner_proof_bundle_validation as checker


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            (
                r"planner proof bundle runner manifest source must contain valid JSON object: "
                r".*proof_bundle_run_manifest\.json"
            ),
        ),
        (
            "[]\n",
            (
                r"planner proof bundle runner manifest source must contain a JSON object: "
                r".*proof_bundle_run_manifest\.json"
            ),
        ),
    ],
)
def test_planner_proof_bundle_runner_checker_rejects_bad_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    manifest = tmp_path / "proof_bundle_run_manifest.json"
    manifest.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        checker.main([str(tmp_path)])


def test_planner_proof_bundle_runner_checker_rejects_missing_source(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        FileNotFoundError,
        match=(
            r"planner proof bundle runner manifest source is missing: "
            r".*proof_bundle_run_manifest\.json"
        ),
    ):
        checker.main([str(tmp_path)])
