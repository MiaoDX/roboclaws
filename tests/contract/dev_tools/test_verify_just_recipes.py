from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT_HOOK = REPO_ROOT / ".githooks" / "pre-commit"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
STANDALONE_PYTEST = REPO_ROOT / "scripts" / "dev" / "run_pytest_standalone.sh"


def test_ci_uses_the_canonical_required_gate() -> None:
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert workflow_text.count("run: just agent::verify") == 1


def test_standalone_pytest_uses_repo_python_and_can_clear_provider_env() -> None:
    script_text = STANDALONE_PYTEST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV" in script_text
    assert 'ROBOCLAWS_PYTHON="${ROBOCLAWS_PYTHON:-$REPO_ROOT/.venv/bin/python}"' in script_text
    assert "command -v pytest" not in script_text
    assert "run 'uv sync --extra dev' in this checkout" in script_text
    for provider_variable in (
        "KIMI_API_KEY",
        "CODEX_RESPONSES_API_KEY",
        "MIMO_RESPONSES_API_KEY",
        "MM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        assert f'{provider_variable}=""' in script_text
        assert f'{provider_variable}="${{{provider_variable}-}}"' in script_text


def test_pre_commit_keeps_current_scoped_and_full_fast_behavior() -> None:
    hook_text = PRE_COMMIT_HOOK.read_text(encoding="utf-8")

    for behavior in (
        "infer_tests_for_path",
        "roboclaws/operator_console/*)",
        'add_test_target "tests/unit/operator_console"',
        "python scripts/dev/check_python_quality_ratchet.py",
        "run_full_fast_tests",
        "FORCE_TESTS=1 set",
        "pytest scoped targets: ${TEST_TARGETS[*]}",
        "./scripts/dev/run_pytest_standalone.sh",
    ):
        assert behavior in hook_text
    for retired_domain in (
        "roboclaws/ai2thor",
        "roboclaws/games",
        "roboclaws/openclaw",
        "tests/unit/games",
    ):
        assert retired_domain not in hook_text
