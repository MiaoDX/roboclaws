from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_showcase_workflow_is_advisory_bounded_and_secret_guarded() -> None:
    workflow = (ROOT / ".github/workflows/showcase.yml").read_text(encoding="utf-8")
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 30" in workflow
    assert "continue-on-error: true" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "inputs.live_execution == 'run'" in workflow
    assert "KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}" in workflow
    assert "actions/deploy-pages@v4" in workflow


def test_showcase_manifest_routes_canonical_suites() -> None:
    manifest = (ROOT / "config/showcase-manifest.json").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/showcase.yml").read_text(encoding="utf-8")
    for suite in ("smoke_regression", "map_build_quality", "open_ended_goals"):
        assert f'"suite": "{suite}"' in manifest
        assert f"suite={suite}" in workflow
    assert "python -m roboclaws.evals.cli" in workflow
