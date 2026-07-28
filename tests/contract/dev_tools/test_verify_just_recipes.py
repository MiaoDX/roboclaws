from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE = REPO_ROOT / "justfile"
JUST_DIR = REPO_ROOT / "just"
VERIFY_JUST = JUST_DIR / "verify.just"
HARNESS_JUST = JUST_DIR / "harness.just"
MOLMO_JUST = JUST_DIR / "molmo.just"
PRE_COMMIT_HOOK = REPO_ROOT / ".githooks" / "pre-commit"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
ROOT_MOLMO_SCRIPT_COMPAT_SHIMS = (
    "check_molmo_planner_manipulation_probe.py",
    "check_molmo_planner_proof_bundle_runner_result.py",
    "check_molmo_realworld_cleanup_result.py",
    "molmospaces_subprocess_worker.py",
    "prepare_molmospaces_room.py",
    "run_molmo_planner_manipulation_probe.py",
    "run_molmo_planner_proof_bundle_from_requests.py",
    "run_molmo_realworld_agent_mcp_smoke.py",
    "run_molmospaces_grasp_cache_generation.py",
    "run_molmospaces_grasp_filter_diagnostics.py",
    "run_molmospaces_grasp_initial_contact_diagnostics.py",
    "run_molmospaces_grasp_pose_policy_cache_generation.py",
    "setup_molmospaces_grasp_generation.py",
)


def test_verify_module_is_registered() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")

    assert re.search(r"^mod verify\s+'just/verify\.just'$", text, re.MULTILINE)


def test_molmo_module_is_registered() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")

    assert re.search(r"^mod molmo\s+'just/molmo\.just'$", text, re.MULTILINE)


def test_root_molmo_script_compat_shims_stay_removed() -> None:
    for script_name in ROOT_MOLMO_SCRIPT_COMPAT_SHIMS:
        assert not (REPO_ROOT / "scripts" / script_name).exists(), script_name


def test_verify_layer_keeps_static_checks_out_of_harness_namespace() -> None:
    verify_text = VERIFY_JUST.read_text(encoding="utf-8")
    harness_text = HARNESS_JUST.read_text(encoding="utf-8")

    assert '"$ruff_bin" check .' in verify_text
    assert '"$ruff_bin" format --check .' in verify_text
    assert "python scripts/dev/check_python_quality_ratchet.py" in verify_text
    assert "git diff --check" in verify_text
    assert "ruff_bin" not in harness_text
    assert "check_python_quality_ratchet.py" not in harness_text
    assert "git diff --check" not in harness_text


def test_required_ci_gate_has_one_local_verify_facade() -> None:
    verify_text = VERIFY_JUST.read_text(encoding="utf-8")
    agent_text = (JUST_DIR / "agent.just").read_text(encoding="utf-8")
    workflow_text = CI_WORKFLOW.read_text(encoding="utf-8")

    assert re.search(r"^ci-required output_dir=\"output/demo\":", verify_text, re.MULTILINE)
    ci_gate = re.search(
        r"^ci-required output_dir=\"output/demo\":[\s\S]*?(?=^# |^[a-zA-Z0-9_-]+|\Z)",
        verify_text,
        re.MULTILINE,
    )
    assert ci_gate is not None
    body = ci_gate.group(0)
    assert "just verify::mock" in body
    assert "scripts/reports/generate_demo_report.py" not in body
    assert 'mkdir -p "$output_dir"' in body

    assert "static|mock|ci-required|contract" in agent_text
    assert "run: just agent::verify ci-required" in workflow_text


def test_fast_dev_tests_clear_provider_env_for_deterministic_mock_gate() -> None:
    script_text = (REPO_ROOT / "scripts" / "dev" / "run_pytest_standalone.sh").read_text(
        encoding="utf-8"
    )
    dev_text = (JUST_DIR / "dev.just").read_text(encoding="utf-8")

    assert "ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV" in script_text
    assert "PYTEST_BIN_DIR" in script_text
    assert 'ROBOCLAWS_PYTHON="${ROBOCLAWS_PYTHON:-$REPO_ROOT/.venv/bin/python}"' in (script_text)
    assert "command -v pytest" not in script_text
    assert "run 'uv sync --extra dev' in this checkout" in script_text
    assert 'KIMI_API_KEY=""' in script_text
    assert 'MIMO_TP_KEY=""' in script_text
    assert "ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV=1" in dev_text


def test_worktree_preflight_fails_loudly_for_missing_env_and_assets() -> None:
    script_text = (REPO_ROOT / "scripts" / "dev" / "check_worktree_readiness.py").read_text(
        encoding="utf-8"
    )
    bootstrap_text = (REPO_ROOT / "scripts" / "dev" / "bootstrap_worktree_env.sh").read_text(
        encoding="utf-8"
    )
    dev_text = (JUST_DIR / "dev.just").read_text(encoding="utf-8")

    assert "roboclaws_worktree_readiness_v1" in script_text
    assert "uv sync --extra dev" in script_text
    assert "git submodule update --init --recursive" in script_text
    assert "vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot/nav2.yaml" in script_text
    assert "ROBOCLAWS_BASELINE_REPO" in bootstrap_text
    assert 'rm -rf -- "$target_venv"' in bootstrap_text
    assert 'ln -s "$baseline_venv" "$target_venv"' in bootstrap_text
    assert 'git -C "$baseline_submodule" cat-file -e' in bootstrap_text
    assert 'git -C "$repo_root" config "submodule.$submodule_name.url" "$baseline_submodule"' in (
        bootstrap_text
    )
    assert "protocol.file.allow=always" in bootstrap_text
    assert 'git -C "$repo_root" submodule update --init --recursive' in bootstrap_text
    assert "worktree-preflight" in dev_text
    assert "worktree-bootstrap" in dev_text


def test_pre_commit_runs_scoped_tests_by_default_with_full_fast_opt_in() -> None:
    hook_text = PRE_COMMIT_HOOK.read_text(encoding="utf-8")
    dev_text = (JUST_DIR / "dev.just").read_text(encoding="utf-8")

    assert "infer_tests_for_path" in hook_text
    assert "roboclaws/operator_console/*)" in hook_text
    assert 'add_test_target "tests/unit/operator_console"' in hook_text
    assert "python scripts/dev/check_python_quality_ratchet.py" in hook_text
    assert "FORCE_TESTS=1 set" in hook_text
    assert "run_full_fast_tests" in hook_text
    assert "pytest scoped targets: ${TEST_TARGETS[*]}" in hook_text
    assert "FORCE_TESTS=1 for full fast pytest" in dev_text


def test_pre_commit_no_longer_infers_retired_domains() -> None:
    hook_text = PRE_COMMIT_HOOK.read_text(encoding="utf-8")

    assert "roboclaws/ai2thor" not in hook_text
    assert "roboclaws/games" not in hook_text
    assert "roboclaws/openclaw" not in hook_text
    assert "tests/unit/games" not in hook_text


def test_verify_delegates_scenario_gates_to_harness() -> None:
    text = VERIFY_JUST.read_text(encoding="utf-8")

    expected_calls = (
        "just harness::molmo-realworld-cleanup",
        "just harness::molmo-realworld-agent-mcp",
        "just harness::molmo-realworld-agent-dogfood-kit",
        "just harness::molmo-realworld-openclaw-dogfood-kit",
        "just harness::molmo-realworld-openclaw-visual-dogfood-kit",
        "just harness::molmo-realworld-raw-fpv",
        "just harness::molmo-planner-proof-bundle-runner",
        "just harness::molmo-planner-proof-bundle-execute-rerun",
        "just harness::molmo-planner-manipulation-probe",
    )
    for call in expected_calls:
        assert call in text


def test_harness_exposes_named_execution_rigs() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    expected_headers = (
        r"^molmo-realworld-cleanup seeds=\"1 2 3\"",
        r"^molmo-realworld-agent-mcp seeds=\"1\"",
        r"^molmo-realworld-agent-dogfood-kit seed=\"7\"",
        r"^molmo-realworld-openclaw-dogfood-kit seed=\"7\"",
        r"^molmo-realworld-openclaw-visual-dogfood-kit seed=\"7\"",
        r"^molmo-realworld-raw-fpv seed=\"7\"",
        (
            r"^molmo-planner-proof-bundle-runner "
            r"output_dir=\"output/molmo-planner-proof-bundle-runner-harness\""
        ),
        (
            r"^molmo-planner-proof-bundle-execute-rerun "
            r"output_dir=\"output/molmo-planner-proof-bundle-execute-rerun\""
        ),
        (
            r"^molmo-planner-manipulation-probe "
            r"output_dir=\"output/molmo-planner-manipulation-probe-harness\""
        ),
    )
    for header in expected_headers:
        assert re.search(header, text, re.MULTILINE), f"missing recipe header: {header}"


def test_molmo_operator_surface_exposes_axis_runner_and_aliases() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    expected_headers = (
        r"^household-world-impl driver=\"mcp-smoke\" profile=\"smoke\"",
        r"^quick-check driver=\"mcp-smoke\" profile=\"smoke\"",
        r"^review-report seeds=\"1 2 3\"",
        r"^mcp-smoke-report seed=\"7\"",
        r"^camera-raw-fpv-report seed=\"7\"",
        r"^openclaw-smoke-report seed=\"7\"",
        r"^openclaw-report seed=\"7\"",
    )
    for header in expected_headers:
        assert re.search(header, text, re.MULTILINE), f"missing recipe header: {header}"
    assert "codex-report" not in text
    assert "claude-report" not in text


def test_molmo_operator_aliases_map_to_truthful_axes() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    expected_calls = (
        'just molmo::household-world-impl "{{driver}}" "{{profile}}"',
        "just molmo::household-world-impl direct world-public-labels",
        "just molmo::household-world-impl mcp-smoke world-public-labels",
        "just molmo::household-world-impl direct camera-raw-fpv",
        'just molmo::household-world-impl openclaw-live "{{profile}}"',
    )
    for call in expected_calls:
        assert call in text

    assert "just molmo::cleanup" not in text
    assert "agent-report" not in text
    assert "codex-live" not in text
    assert "claude-live" not in text
    assert "openclaw_agent" in text
    assert "realworld_contract_smoke_agent" in text


def test_molmo_axis_runner_distinguishes_smoke_from_current_live_agents() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    for expected in (
        'driver="${driver#driver=}"',
        'profile="${profile#profile=}"',
        "unsupported cleanup lane",
        "--evidence-lane",
        "--expect-profile",
        "mcp-smoke/openclaw-smoke for deterministic substitutes",
        'SKILLS_DIR="$PWD/skills/molmo-realworld-cleanup"',
        "just chat::run",
        'bash scripts/dev/network_status.sh --assert-off-work "OpenClaw Molmo cleanup live report"',
        (
            'roboclaws_assert_openai_agents_network_allowed "OpenAI Agents SDK Molmo cleanup '
            'live report"'
        ),
    ):
        assert expected in text

    assert "source scripts/dev/coding_agent_env.sh" in text
    assert "scripts/dev/coding_agent_docker.sh ensure" not in text
    assert 'scripts/dev/coding_agent_docker.sh install-wrappers "$docker_shim_dir"' not in text


def test_molmo_visual_reports_require_robot_timeline_and_real_robot_checks() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    for expected in (
        "--include-robot",
        "--robot-name rby1m",
        "--record-robot-views",
        "--require-robot-views",
        "--require-waypoint-honesty",
        "--require-real-robot-alignment",
        'perception_mode="raw_fpv_only"',
        'perception_mode="camera_model_policy"',
        "--require-raw-fpv-observations",
        "--require-camera-model-policy",
    ):
        assert expected in text


def test_molmo_harness_output_roots_keep_timestamped_runs() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    assert 'timestamp_cmd := "TZ=Asia/Shanghai date +%m%d_%H%M"' in text
    recipe_names = (
        "molmo-realworld-cleanup",
        "molmo-realworld-agent-mcp",
        "molmo-realworld-agent-dogfood-kit",
        "molmo-realworld-openclaw-dogfood-kit",
        "molmo-realworld-openclaw-visual-dogfood-kit",
        "molmo-realworld-raw-fpv",
        "molmo-planner-proof-bundle-runner",
        "molmo-planner-proof-bundle-execute-rerun",
        "molmo-planner-manipulation-probe",
    )
    for recipe_name in recipe_names:
        recipe = re.search(
            rf"^{recipe_name}[\s\S]*?(?=^# |\Z)",
            text,
            re.MULTILINE,
        )
        assert recipe is not None, recipe_name
        body = recipe.group(0)
        assert re.search(r'stamp="\$\(\{\{\s*timestamp_cmd\s*\}\}\)"', body), recipe_name
        assert 'rm -rf "{{output_dir}}"' not in body, recipe_name


def test_openclaw_visual_kit_uses_real_visual_backend_and_checker() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    recipe = re.search(
        r"^molmo-realworld-openclaw-visual-dogfood-kit[\s\S]*?(?=^# |\Z)",
        text,
        re.MULTILINE,
    )
    assert recipe is not None
    body = recipe.group(0)
    for expected in (
        "--backend molmospaces_subprocess",
        "--policy openclaw_agent",
        "--include-robot",
        "--record-robot-views",
        "--require-openclaw-minimum",
        "--require-clean-agent-run",
        "--require-robot-views",
        "--require-advisory-scoring",
    ):
        assert expected in body


def test_realworld_gates_require_advisory_scoring() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    for recipe_name in (
        "molmo-realworld-cleanup",
        "molmo-realworld-agent-mcp",
        "molmo-realworld-agent-dogfood-kit",
        "molmo-realworld-openclaw-dogfood-kit",
        "molmo-realworld-openclaw-visual-dogfood-kit",
        "molmo-realworld-raw-fpv",
    ):
        recipe = re.search(
            rf"^{recipe_name}[\s\S]*?(?=^# |\Z)",
            text,
            re.MULTILINE,
        )
        assert recipe is not None, recipe_name
        assert "--require-advisory-scoring" in recipe.group(0), recipe_name


def test_raw_fpv_harness_uses_raw_mode_and_checker() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    recipe = re.search(
        r"^molmo-realworld-raw-fpv[\s\S]*?(?=^# |\Z)",
        text,
        re.MULTILINE,
    )
    assert recipe is not None
    body = recipe.group(0)
    for expected in (
        "--backend molmospaces_subprocess",
        "--perception-mode raw_fpv_only",
        "--include-robot",
        "--record-robot-views",
        "--require-robot-views",
        "--require-raw-fpv-observations",
    ):
        assert expected in body


def test_planner_manipulation_probe_accepts_only_explicit_blocked_gate() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    recipe = re.search(
        r"^molmo-planner-manipulation-probe[\s\S]*?(?=^# |\Z)",
        text,
        re.MULTILINE,
    )
    assert recipe is not None
    body = recipe.group(0)
    for expected in (
        "scripts/molmo_cleanup/run_molmo_planner_manipulation_probe.py",
        "--probe-mode",
        "scripts/molmo_cleanup/check_molmo_planner_manipulation_probe.py",
        "--accept-blocked-capability",
    ):
        assert expected in body


def test_planner_proof_bundle_runner_harness_stays_dry_run() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    recipe = re.search(
        r"^molmo-planner-proof-bundle-runner[\s\S]*?(?=^# ADR-0044)",
        text,
        re.MULTILINE,
    )
    assert recipe is not None
    body = recipe.group(0)
    for expected in (
        "roboclaws.household.realworld_cleanup",
        "scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py",
        "scripts/molmo_cleanup/run_molmo_planner_proof_bundle_from_requests.py",
        "scripts/molmo_cleanup/check_molmo_planner_proof_bundle_runner_result.py",
        "--backend api_semantic_synthetic",
        "--probe-mode execute",
    ):
        assert expected in body
    assert "--execute-probes" not in body


def test_planner_proof_bundle_execute_rerun_gate_is_strict_and_local() -> None:
    text = HARNESS_JUST.read_text(encoding="utf-8")

    recipe = re.search(
        r"^molmo-planner-proof-bundle-execute-rerun[\s\S]*?(?=^# ADR-0014)",
        text,
        re.MULTILINE,
    )
    assert recipe is not None
    body = recipe.group(0)
    for expected in (
        "roboclaws.household.realworld_cleanup",
        "--backend molmospaces_subprocess",
        "--include-robot",
        "--record-robot-views",
        "scripts/molmo_cleanup/run_molmo_planner_proof_bundle_from_requests.py",
        "--torch-extensions-dir",
        "--execute-probes",
        "--rerun-cleanup",
        "--cleanup-output-dir",
        "--require-proof-outputs",
        "--require-cleanup-rerun-output",
        "--require-robot-views",
        "--require-planner-proof-attachment",
        "--require-planner-backed-cleanup-primitives",
        "--require-planner-cleanup-bridge-ready",
    ):
        assert expected in body
