from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from tests.contract.dev_tools.task_agent_just_recipes_support import (
    HOUSEHOLD_AGENT_SERVER_MODULE,
    HOUSEHOLD_LIVE_DRIVER,
    LIVE_OPENAI_AGENTS_RUNNER,
    MOLMO_JUST,
    REPO_ROOT,
    agibot_dependency_overrides,
    assert_household_map_build_run_fails,
    just_bin,
    trace_household_cleanup_run,
    trace_household_map_build_run,
)


def test_map_build_routes_agibot_backend_to_physical_pilot_cli(tmp_path: Path) -> None:
    route = trace_household_map_build_run(
        "direct",
        "camera-grounded-labels",
        "camera_labeler=grounding-dino",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
        "context_json=tests/fixtures/agibot_map_context.completed.json",
        "waypoint_id=wp_sofa_front",
        "output_dir=output/agibot/map-build",
    )

    assert route[:8] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        "output/agibot/map-build",
        "--context-json",
        "tests/fixtures/agibot_map_context.completed.json",
    ]
    assert "--waypoint-id" in route
    assert "wp_sofa_front" in route
    assert "agibot-g2-cleanup" not in " ".join(route)


def test_map_build_sdk_routes_agibot_backend_to_live_runner(tmp_path: Path) -> None:
    route = trace_household_map_build_run(
        "openai-agents-sdk",
        "camera-grounded-labels",
        "provider_profile=kimi-openai-chat",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
        "context_json=tests/fixtures/agibot_map_context.completed.json",
        "run_dir=output/agibot/map-build-sdk/test-run",
        "policy=openai_agents_agibot_map_build",
        "camera_labeler=grounding-dino",
        "visual_grounding_timeout_s=12.5",
    )

    assert route[:4] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.agents.household_live_runner",
    ]
    assert "--repo-root" in route
    assert str(REPO_ROOT) in route
    assert "--run-dir" in route
    assert "output/agibot/map-build-sdk/test-run" in route
    assert "--server-arg=--context-json" in route
    assert "--server-arg=tests/fixtures/agibot_map_context.completed.json" in route
    assert "--server-arg=--evidence-lane" in route
    assert "--server-arg=camera-grounded-labels" in route
    assert "--server-arg=--visual-grounding" in route
    assert "--server-arg=grounding-dino" in route
    assert "--server-arg=--visual-grounding-timeout-s" in route
    assert "--server-arg=12.5" in route
    assert "--backend" in route
    assert "agibot_gdk" in route
    assert "--policy" in route
    assert "openai_agents_agibot_map_build" in route
    assert "molmo::cleanup" not in route


def test_b1_runtime_bundle_branch_exports_canonical_runtime_prior_artifacts() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    b1_branch = molmo_text.split('if [[ "$backend" == "isaaclab_subprocess"', 1)[1].split(
        "    fi\n    map_bundle_args=()",
        1,
    )[0]

    assert "roboclaws.maps.b1_base_metric_map" in b1_branch
    assert "roboclaws.backends.isaaclab.b1_base_metric_augmentation" in b1_branch
    assert "compile_b1_map12_runtime_bundle.py" not in b1_branch
    assert "convert_nav2_cleanup_bundle.py" in b1_branch
    assert "b1_robot_consumption_manifest.json" in b1_branch
    assert "--base-map-bundle" in b1_branch
    assert "--alignment-artifact" in b1_branch
    assert "--navigation-artifact" in b1_branch
    assert "--semantic-projection-artifact" not in b1_branch
    assert '--output "${output_dir}/runtime_map_prior_snapshot.json"' in b1_branch
    assert '--summary-json "${output_dir}/runtime_map_prior_targets.json"' in b1_branch
    assert 'map_bundle_dir="$b1_runtime_map_bundle_dir"' in b1_branch


def test_b1_runs_copy_robot_consumption_artifacts_to_each_seed_run_dir() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    copy_helper = molmo_text.split("    copy_b1_run_artifacts_to_seed_dir() {", 1)[1].split(
        "\n    }",
        1,
    )[0]
    live_run_setup = molmo_text.split('run_dir="${run_root}/seed-${seed}"', 1)[1].split(
        'policy="${driver%-live}_agent"',
        1,
    )[0]
    direct_run_setup = molmo_text.split("    for seed in $seeds; do", 1)[1].split(
        '      case "$driver" in',
        1,
    )[0]

    assert 'launch_world_id" != "b1-map12"' in copy_helper
    assert "b1_robot_consumption_manifest.json" in copy_helper
    assert "runtime_map_prior_snapshot.json" in copy_helper
    assert "runtime_map_prior_targets.json" in copy_helper
    assert 'cp "${output_dir}/${b1_run_artifact}"' in copy_helper
    assert '"${artifact_run_dir}/${b1_run_artifact}"' in copy_helper
    assert 'copy_b1_run_artifacts_to_seed_dir "$run_dir"' in live_run_setup
    assert 'copy_b1_run_artifacts_to_seed_dir "$run_dir"' in direct_run_setup


def test_b1_isaac_route_uses_b1_robot_consumption_checker_gate() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    isaac_branch = molmo_text.split(
        'if [[ "$backend" == "isaaclab_subprocess" && "$launch_world_id" == "b1-map12" ]]',
        1,
    )[1].split('    if [[ "$cleanup_routine"', 1)[0]

    assert "--require-b1-robot-consumption-proof" in isaac_branch
    assert "--require-real-robot-alignment" not in isaac_branch
    assert "output/b1-map12/alignment/alignment_residuals.json" not in isaac_branch
    assert "output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json" not in (
        isaac_branch
    )


def test_b1_isaac_camera_grounded_uses_isaac_backend_and_real_grounding_gate() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    camera_branch = re.search(
        r"camera-grounded-labels\)\n(?P<body>.*?)\n\s+;;",
        molmo_text,
        re.DOTALL,
    )
    assert camera_branch is not None
    isaac_branch = molmo_text.split(
        'if [[ "$backend" == "isaaclab_subprocess" && "$launch_world_id" == "b1-map12" ]]',
        1,
    )[1].split('    if [[ "$cleanup_routine"', 1)[0]

    assert 'if [[ "$launch_world_id" == "b1-map12" ]]' in camera_branch.group("body")
    assert 'backend="isaaclab_subprocess"' in camera_branch.group("body")
    assert "--require-camera-model-policy" in isaac_branch
    assert "--expect-visual-grounding-pipeline" in isaac_branch
    assert "--require-b1-robot-consumption-proof" in isaac_branch
    assert "--require-waypoint-honesty" in isaac_branch
    assert "--require-robot-views" in isaac_branch


def test_b1_isaac_route_consumes_injected_robot_consumption_artifacts() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    b1_compile_branch = molmo_text.split(
        'if [[ "$backend" == "isaaclab_subprocess" && "$launch_world_id" == "b1-map12" ]]',
        1,
    )[1].split("    fi\n    map_bundle_args=()", 1)[0]

    assert "fit_b1_map12_scene_alignment.py" not in b1_compile_branch
    assert "check_b1_map12_readiness.py" not in b1_compile_branch
    assert "run_b1_map12_navigation_smoke.py" not in b1_compile_branch
    assert "requires explicit ${required_input}" in b1_compile_branch
    assert "received invalid ${required_file}" in b1_compile_branch
    assert "output/b1-map12/alignment/alignment_residuals.json" not in b1_compile_branch
    assert "output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json" not in (
        b1_compile_branch
    )


def test_household_cleanup_routes_agibot_backend_to_physical_pilot_cli(tmp_path: Path) -> None:
    route = trace_household_cleanup_run(
        "direct",
        "world-public-labels",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
    )

    assert route[:6] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        "output/household/household-world/cleanup/direct-world-public-labels",
    ]
    assert "--runner-python" in route
    assert "--runner-script" in route
    assert "--agibot-map-artifact-dir" in route


def test_household_cleanup_routes_agibot_backend_override_to_cleanup_pilot_cli(
    tmp_path: Path,
) -> None:
    route = trace_household_cleanup_run(
        "direct",
        "world-public-labels",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
        "context_json=tests/fixtures/agibot_map_context.completed.json",
        "waypoint_id=wp_sofa_front",
        "output_dir=output/agibot/cleanup",
    )

    assert route[:10] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        "output/agibot/cleanup",
        "--context-json",
        "tests/fixtures/agibot_map_context.completed.json",
        "--waypoint-id",
        "wp_sofa_front",
    ]
    assert "--runner-python" in route
    assert "--runner-script" in route
    assert "--agibot-map-artifact-dir" in route
    assert str(tmp_path / "agibot_map") in route


def test_live_cleanup_server_entrypoint_accepts_agibot_shared_mcp_backend() -> None:
    result = subprocess.run(
        [
            os.environ.get("ROBOCLAWS_DEVTOOLS_PYTHON") or sys.executable,
            "-m",
            HOUSEHOLD_AGENT_SERVER_MODULE,
            "household-world",
            "--help",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "agibot_gdk" in result.stdout
    assert "--context-json" in result.stdout
    assert "--real-movement-enabled" in result.stdout


def test_agibot_sdk_map_build_route_requires_context_json(tmp_path: Path) -> None:
    stderr = assert_household_map_build_run_fails(
        "openai-agents-sdk",
        "camera-grounded-labels",
        "provider_profile=kimi-openai-chat",
        "backend=agibot_gdk",
        "camera_labeler=grounding-dino",
        *agibot_dependency_overrides(tmp_path),
    )

    assert (
        "backend=agibot_gdk surface=household-world task_intent=map-build "
        "openai-agents-sdk requires context_json" in stderr
    )


def test_molmo_camera_labels_fake_http_uses_contract_not_cleanup_quality_gate() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")
    match = re.search(r"camera-grounded-labels\)\n(?P<body>.*?)\n\s+;;", text, re.DOTALL)
    assert match is not None
    body = match.group("body")

    assert "--expect-visual-grounding-pipeline" in body
    assert "--allow-partial-cleanup" in body
    assert "--min-sweep-coverage 1.0" in body


def test_molmo_apple2apple_grid_recipe_strips_key_value_prefixes(tmp_path: Path) -> None:
    output_dir = tmp_path / "apple2apple-grid"
    result = subprocess.run(
        [
            just_bin(),
            "molmo::apple2apple-grid",
            "dry-run",
            f"output_dir={output_dir}",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (output_dir / "apple2apple_test_grid.json").is_file()
    assert (output_dir / "apple2apple_test_grid.html").is_file()
    assert f"apple-to-apple grid manifest: {output_dir / 'apple2apple_test_grid.json'}" in (
        result.stdout
    )


def test_molmo_world_labels_checker_matches_official_acceptance_gate() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")
    match = re.search(r"world-public-labels\)\n(?P<body>.*?)\n\s+;;", text, re.DOTALL)
    assert match is not None
    body = match.group("body")

    assert "--require-waypoint-honesty" in body
    assert "--require-real-robot-alignment" in body
    assert "--min-semantic-accepted-count 5" in body
    assert "--min-sweep-coverage 1.0" in body


def test_molmo_map_build_strips_cleanup_quality_gate() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert (
        'if [[ "$map_build_enabled" == "true" && "$driver" == "openai-agents-live" ]]; then' in text
    )
    assert "checker_map_build_args=(--require-runtime-metric-map)" in text
    assert 'elif [[ "$map_build_enabled" == "true" ]]; then' in text
    assert (
        "--min-semantic-accepted-count|--min-model-declared-observations|--min-model-declared-actions"
        in text
    )
    assert "--require-model-declared-observations)" in text
    assert "filtered_checker_visual_args" in text
    assert 'checker_visual_args=("${filtered_checker_visual_args[@]}")' in text


def test_molmo_camera_raw_live_gate_uses_generated_mess_success_threshold() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")
    match = re.search(r"camera-raw-fpv\)\n(?P<body>.*?)\n\s+;;", text, re.DOTALL)
    assert match is not None
    body = match.group("body")

    assert "generated_mess_success_threshold=$(( (generated_mess_count * 7 + 9) / 10 ))" in text
    assert 'raw_fpv_required_cleanup_count="$generated_mess_success_threshold"' in body
    assert '--min-model-declared-observations "$raw_fpv_required_cleanup_count"' in body
    assert '--min-model-declared-actions "$raw_fpv_required_cleanup_count"' in body
    assert '--min-semantic-accepted-count "$raw_fpv_required_cleanup_count"' in body


def test_molmo_just_openai_agents_forwards_camera_grounded_history_compaction() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_COMPACTION" in text
    assert "--camera-grounded-history-compaction" in text
    assert "--no-camera-grounded-history-compaction" in text
    assert "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_RETAIN" in text
    assert "--camera-grounded-history-retain" in text


def test_molmo_camera_grounded_product_runs_autostart_real_sidecar() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_AUTOSTART_VISUAL_GROUNDING_SIDECAR" in text
    assert "ensure_visual_grounding_sidecar_for_run" in text
    assert '[[ "$reason" != "connection_error" ]]' in text
    assert "--pipeline real-router" in text
    assert "--adapter-mode real" in text
    assert ".venv-visual-grounding/bin/python" in text
    assert "stop_managed_visual_grounding_sidecar" in text
    assert 'exec "${runner_args[@]}"' not in text


def test_molmo_isaac_live_runs_default_to_longer_mcp_client_timeout() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    timeout_default = (
        "openai_agents_mcp_client_session_timeout_s="
        '"${ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S:-30}"'
    )
    timeout_condition = (
        '[[ -z "${ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S:-}" '
        '&& "$backend" == "isaaclab_subprocess" ]]'
    )

    assert timeout_default in text
    assert timeout_condition in text
    assert 'openai_agents_mcp_client_session_timeout_s="120"' in text
    assert '--mcp-client-session-timeout-s "$openai_agents_mcp_client_session_timeout_s"' in text


def test_molmo_live_dispatch_is_sdk_only_and_probeable() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    runner_text = LIVE_OPENAI_AGENTS_RUNNER.read_text(encoding="utf-8")
    household_live_text = HOUSEHOLD_LIVE_DRIVER.read_text(encoding="utf-8")

    assert "live_drivers=(openai-agents-live)" in molmo_text
    assert "codex-live" not in molmo_text
    assert "claude-live" not in molmo_text
    assert "run_live_codex.sh" not in molmo_text
    assert "scripts/molmo_cleanup/run_live_codex_cleanup.py" not in molmo_text
    assert "scripts/molmo_cleanup/run_live_claude_cleanup.py" not in molmo_text
    assert "another interactive Codex Molmo cleanup session appears to be active" not in molmo_text
    assert (
        'if [[ "$backend" == "molmospaces_subprocess" && "$interactive_visual_cap" == "1" ]]'
        not in molmo_text
    )
    assert "active MCP servers:" not in molmo_text
    assert "ROBOCLAWS_MOLMO_ALLOW_BATCH_VISUAL_BACKENDS" in molmo_text
    assert "ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS" in molmo_text
    assert "refusing to choose another port" in molmo_text
    assert "live_status.json" in molmo_text
    assert "tmux_session.txt" not in molmo_text
    assert "roboclaws.agents.household_live_runner" in molmo_text
    assert "acquire_household_live_run_lease" in runner_text
    assert "acquire_visual_backend_slot" in household_live_text
    assert "no MolmoSpaces visual backend slot is available" in household_live_text
    assert "is already in use before server start" in runner_text
    assert re.search(r'^status path=""', molmo_text, re.MULTILINE)
    assert "scripts/molmo_cleanup/summarize_live_run.py" in molmo_text
    assert 'live_lock_backend="${backend//[^A-Za-z0-9_.-]/-}"' in molmo_text
    assert '--lock-path "$openai_agents_lock_path"' in molmo_text
