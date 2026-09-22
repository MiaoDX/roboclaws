from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_showcase_workflow_is_advisory_bounded_and_secret_guarded() -> None:
    workflow = (ROOT / ".github/workflows/showcase.yml").read_text(encoding="utf-8")
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 60" in workflow
    assert "timeout-minutes: 10" in workflow
    assert "continue-on-error: true" in workflow
    assert (
        "if: github.event_name == 'workflow_dispatch' && inputs.live_execution != 'run'" in workflow
    )
    assert "inputs.live_execution == 'run'" in workflow
    assert "secrets.KIMI_API_KEY" in workflow
    assert "secrets.MIMO_TP_KEY" in workflow
    assert "secrets.MIMO_OPENAI_BASE_URL" in workflow
    assert "secrets.MIMO_RESPONSES_API_KEY" not in workflow
    assert "secrets.MM_API_KEY" in workflow
    assert "max-parallel: 3" in workflow
    assert "Install headless MuJoCo rendering runtime" in workflow
    assert "libegl1 libgl1 libgles2 libegl-mesa0" in workflow
    assert "ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY: action_timeline" in workflow
    assert 'ROBOCLAWS_MOLMO_LIVE_SERVER_STARTUP_TIMEOUT_S: "300"' in workflow
    assert "repair_molmospaces_resource_cache.py" in workflow
    assert (
        workflow.index("repair_molmospaces_resource_cache.py")
        < workflow.index("python -m molmo_spaces.molmo_spaces_constants")
        < workflow.index("Run ${{ matrix.provider }} showcase shard")
    )
    assert "needs: provider-showcase" in workflow
    assert "showcase-kimi-${{ github.sha }}" in workflow
    assert "kimi_pid=$!" not in workflow
    assert "mimo_pid=$!" not in workflow
    assert "minimax_pid=$!" not in workflow
    assert "Require model-backed showcase success" in workflow
    assert 'row["status"] != "passed"' in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "Publish report drilldowns" in workflow
    assert "publish_report_bundle" in workflow
    assert 'Path("output/showcase/site/reports") / shard / "evals"' in workflow
    assert "Verify published report drilldowns" in workflow
    assert "published report links are missing" in workflow
    assert "shutil.copytree" not in workflow
    assert workflow.count("github-pages-${{ github.run_attempt }}") == 2
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


def test_showcase_manifest_has_separate_startup_and_completion_budgets() -> None:
    manifest = (ROOT / "config/showcase-manifest.json").read_text(encoding="utf-8")
    assert '"timeout_s": 1800, "decision_call_budget": 100, "stall_timeout_s": 600' in manifest
    assert '"timeout_s": 1800, "decision_call_budget": 16, "stall_timeout_s": 120' in manifest
    assert '"timeout_s": 3600, "decision_call_budget": 100' in manifest
