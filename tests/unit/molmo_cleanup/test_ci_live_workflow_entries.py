from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_public_ci_contains_only_deterministic_repo_gates() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "lint-and-mock:" in workflow
    assert "just agent::verify ci-required" in workflow
    assert "detect-secrets scan" in workflow
    assert ".secrets.baseline" in workflow
    assert "molmo-live-cleanup" not in workflow
    assert "model-provider-health" not in workflow
    assert "${{ secrets." not in workflow
    assert "pages: write" not in workflow
    assert "id-token: write" not in workflow
