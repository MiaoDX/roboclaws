from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_CHECKER_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_planner_proof_bundle_runner_result.py"
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    message: str,
) -> None:
    checker = _load_module(
        BUNDLE_CHECKER_PATH,
        "check_molmo_planner_proof_bundle_runner_result_sources",
    )
    manifest = tmp_path / "proof_bundle_run_manifest.json"
    manifest.write_text(source, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_molmo_planner_proof_bundle_runner_result.py", str(tmp_path)],
    )

    with pytest.raises(ValueError, match=message):
        checker.main()


def test_planner_proof_bundle_runner_checker_rejects_missing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_module(
        BUNDLE_CHECKER_PATH,
        "check_molmo_planner_proof_bundle_runner_result_missing_source",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_molmo_planner_proof_bundle_runner_result.py", str(tmp_path)],
    )

    with pytest.raises(
        FileNotFoundError,
        match=(
            r"planner proof bundle runner manifest source is missing: "
            r".*proof_bundle_run_manifest\.json"
        ),
    ):
        checker.main()
