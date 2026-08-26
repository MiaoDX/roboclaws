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
    assert "actions/configure-pages@v5" in workflow
    assert "environment:\n      name: github-pages" in workflow
    assert "if: always() && github.ref == 'refs/heads/main'" in workflow
    assert "needs: showcase" in workflow
    assert "cleanup_capability" in (ROOT / "config/showcase-manifest.json").read_text()
    assert "seed=7" not in workflow


def test_showcase_manifest_routes_canonical_suites() -> None:
    manifest = (ROOT / "config/showcase-manifest.json").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/showcase.yml").read_text(encoding="utf-8")
    for suite in (
        "smoke_regression",
        "map_build_quality",
        "cleanup_capability",
        "open_ended_goals",
    ):
        assert f'"suite": "{suite}"' in manifest
    assert "python -m roboclaws.evals.showcase" in workflow
    assert "--execute" in workflow
