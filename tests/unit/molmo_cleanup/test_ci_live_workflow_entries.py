from __future__ import annotations

import re
from pathlib import Path

from roboclaws.household.ci_live_reports import MODEL_ENTRIES

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_live_workflow_entries_match_report_registry() -> None:
    workflow_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    expected = [entry.name for entry in MODEL_ENTRIES]

    assert _workflow_model_entries(workflow_text) == expected
    assert _workflow_download_entries(workflow_text) == expected


def _workflow_model_entries(workflow_text: str) -> list[str]:
    match = re.search(r"\n\s+model_entry:\n(?P<body>(?:\s+- .+\n)+)", workflow_text)
    assert match is not None, "missing molmo-live-cleanup model_entry matrix"
    return [
        line.strip().removeprefix("- ")
        for line in match.group("body").splitlines()
        if line.strip().startswith("- ")
    ]


def _workflow_download_entries(workflow_text: str) -> list[str]:
    return re.findall(r"name: report-molmo-live-([A-Za-z0-9_.-]+)", workflow_text)
