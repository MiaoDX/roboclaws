from __future__ import annotations

import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from roboclaws.launch import resolve_surface_launch
from roboclaws.launch.catalog import LaunchError
from tests.contract.dev_tools.task_agent_just_recipes_support import (
    AGENT_JUST,
    HOUSEHOLD_LIVE_DRIVER,
    JUST_DIR,
    JUSTFILE,
    LIVE_OPENAI_AGENTS_LIFECYCLE,
    LIVE_OPENAI_AGENTS_RUNNER,
    MOLMO_JUST,
    REPO_ROOT,
    assert_agent_mcp_fails,
    assert_household_cleanup_run_fails,
    assert_surface_run_fails,
    just_bin,
    just_summary,
    trace_agent_harness,
    trace_agent_mcp,
    trace_agent_verify,
)


def test_public_just_summary_is_small_facade() -> None:
    summary = just_summary()

    assert summary == {
        "run::surface",
        "agent::verify",
        "agent::harness",
        "agent::mcp",
        "agent::eval",
        "console::run",
    }

    hidden_recipes = {
        "vlm::run",
        "molmo::cleanup",
        "harness::household-world",
        "verify::mock",
        "code::codex",
        "task::territory",
        "agent::codex-nav",
    }
    assert summary.isdisjoint(hidden_recipes)


def test_agent_harness_rejects_removed_agent_validation_target() -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "agent::harness", "agent-validation", "recommend"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "unsupported harness target 'agent-validation'" in result.stderr


def test_justfile_marks_implementation_modules_private() -> None:
    text = JUSTFILE.read_text(encoding="utf-8")

    for module in (
        "dev",
        "mcp",
        "harness",
        "verify",
        "molmo",
    ):
        assert re.search(
            rf"^\[private\]\nmod {module}\s+'just/{module}\.just'$",
            text,
            re.MULTILINE,
        )

    assert "mod code" not in text
    assert re.search(r"^mod agent\s+'just/agent\.just'$", text, re.MULTILINE)
    assert re.search(r"^mod run\s+'just/run\.just'$", text, re.MULTILINE)


def test_agent_verify_routes_required_ci_gate_to_verify_module() -> None:
    route = trace_agent_verify("ci-required", "output_dir=output/custom-demo", "steps=3")

    assert route == [
        "just",
        "verify::ci-required",
        "output_dir=output/custom-demo",
        "steps=3",
    ]


def test_agent_harness_no_longer_exposes_molmo_codex_perf_target() -> None:
    agent_text = AGENT_JUST.read_text(encoding="utf-8")
    harness_text = (JUST_DIR / "harness.just").read_text(encoding="utf-8")

    assert "molmo-cleanup-codex-perf" not in agent_text
    assert "molmo-cleanup-codex-perf" not in harness_text


def test_agent_harness_allows_molmo_visual_grounding_benchmark_target() -> None:
    agent_text = AGENT_JUST.read_text(encoding="utf-8")
    harness_text = (JUST_DIR / "harness.just").read_text(encoding="utf-8")

    assert "molmo-visual-grounding-benchmark" not in agent_text
    assert re.search(r"^molmo-visual-grounding-benchmark \*overrides:", harness_text, re.MULTILINE)
    assert "run_visual_grounding_benchmark.py" in harness_text
    assert "check_visual_grounding_benchmark_result.py" in harness_text

    route = trace_agent_harness(
        "molmo-visual-grounding-benchmark",
        "pipeline=grounding-dino",
        "output_dir=/tmp/roboclaws-vg",
    )
    assert route == [
        "just",
        "harness::molmo-visual-grounding-benchmark",
        "pipeline=grounding-dino",
        "output_dir=/tmp/roboclaws-vg",
    ]


def test_task_module_is_removed_from_public_facade() -> None:
    summary = just_summary()
    assert "run::surface" in summary
    assert "task::run" not in summary
    assert "task::navigate" not in summary
    assert "task::cleanup-report" not in summary
    assert not (JUST_DIR / "task.just").exists()


def test_run_module_exposes_surface_publicly() -> None:
    text = (JUST_DIR / "run.just").read_text(encoding="utf-8")

    assert re.search(r"^surface \*overrides:", text, re.MULTILINE)
    assert "-m roboclaws.cli.main run surface" in text


def test_agent_mcp_accepts_household_world_dispatch_target() -> None:
    route = trace_agent_mcp(
        "up",
        "household-world",
        "127.0.0.1",
        "18788",
        "output/debug/household-mcp",
    )

    assert route == [
        "just",
        "mcp::up",
        "household-world",
        "127.0.0.1",
        "18788",
        "output/debug/household-mcp",
    ]


def test_agent_mcp_rejects_task_named_household_dispatch_targets() -> None:
    assert_agent_mcp_fails("up", "household-world.cleanup")
    stderr = assert_agent_mcp_fails("up", "household-world.map-build")

    body = (JUST_DIR / "mcp.just").read_text(encoding="utf-8")
    assert "(expected household-world)" in stderr
    assert '"household-world"' in body
    assert '"household-world.cleanup"' not in body
    assert '"household-world.map-build"' not in body
    assert '"household-cleanup"' not in body
    assert '"semantic-map-build"' not in body


def test_surface_launch_rejects_retired_ai2thor_surface() -> None:
    with pytest.raises(LaunchError, match="unsupported surface 'ai2thor-world'") as exc:
        resolve_surface_launch(
            (
                "surface=ai2thor-world",
                "agent_engine=openclaw-gateway",
                "intent=navigate",
            )
        )

    assert exc.value.hint == "expected household-world|planner-proof"


@pytest.mark.parametrize(
    "surface", ("molmospace-cleanup", "molmospaces-cleanup", "cleanup-report", "household-cleanup")
)
def test_surface_router_rejects_removed_compatibility_aliases(surface: str) -> None:
    stderr = assert_surface_run_fails(f"surface={surface}", "agent_engine=openai-agents-sdk")

    assert f"unsupported surface '{surface}'" in stderr


def test_surface_launch_rejects_retired_vlm_policy_engine() -> None:
    with pytest.raises(LaunchError, match="unsupported agent_engine 'vlm-policy'") as exc:
        resolve_surface_launch(
            (
                "surface=household-world",
                "agent_engine=vlm-policy",
                "preset=cleanup",
                "evidence_lane=world-public-labels",
            )
        )

    assert "expected direct-runner|openai-agents-sdk" in exc.value.hint
    assert "codex-cli" not in exc.value.hint
    assert "claude-code" not in exc.value.hint


def test_public_engine_docs_list_only_current_engines() -> None:
    readme = (JUST_DIR / "README.md").read_text(encoding="utf-8")
    engine_section = readme.split("Agent engines:", 1)[1].split("Provider profiles", 1)[0]
    taxonomy = (REPO_ROOT / "docs" / "human" / "agent-task-command-taxonomy.md").read_text(
        encoding="utf-8"
    )
    assert "openclaw-gateway" not in engine_section
    assert "openclaw-gateway" not in readme
    assert "openclaw-gateway" not in taxonomy


def test_human_docs_do_not_surface_legacy_cleanup_commands_as_current() -> None:
    settings = (REPO_ROOT / "docs" / "human" / "molmospaces-settings.md").read_text(
        encoding="utf-8"
    )
    legacy_arch = (
        REPO_ROOT / "docs" / "human" / "molmospaces-cleanup-mode-architecture.md"
    ).read_text(encoding="utf-8")
    assert "just task::run" not in legacy_arch
    assert "profile=world-labels" not in legacy_arch
    assert "profile=world-labels-sanitized" not in legacy_arch
    assert "profile=camera-raw" not in legacy_arch
    assert "profile=camera-labels" not in legacy_arch
    assert "openclaw-smoke-report" not in settings
    assert "just molmo::openclaw-report" not in settings
    assert "just run::surface surface=household-world" in settings


def test_prompt_mapping_rejects_retired_ai2thor_nav_task() -> None:
    stderr = assert_surface_run_fails("surface=ai2thor-nav", "agent_engine=openclaw-gateway")

    assert "unsupported surface 'ai2thor-nav'" in stderr
    assert "expected household-world|planner-proof" in stderr


@pytest.mark.parametrize(
    "target",
    ("navigator", "regression", "sim", "agent-validation"),
)
def test_agent_harness_rejects_retired_targets(target: str) -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "agent::harness", target],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"unsupported harness target '{target}'" in result.stderr


def test_household_cleanup_rejects_public_legacy_rich_map_mode() -> None:
    stderr = assert_household_cleanup_run_fails(
        "direct",
        "world-public-labels",
        "map_mode=rich",
    )

    assert "map_mode= is no longer a public run::surface argument" in stderr


def test_live_agent_server_routes_use_cli_modules_not_examples() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    sdk_runner_text = LIVE_OPENAI_AGENTS_RUNNER.read_text(encoding="utf-8")
    sdk_lifecycle_text = LIVE_OPENAI_AGENTS_LIFECYCLE.read_text(encoding="utf-8")
    household_live_text = HOUSEHOLD_LIVE_DRIVER.read_text(encoding="utf-8")

    assert "roboclaws.agents.household_live_runner" in molmo_text
    assert "roboclaws.cli.agent_server household-cleanup" not in molmo_text
    assert "examples/molmo_cleanup/molmo_realworld_cleanup_agent_server.py" not in molmo_text
    assert "examples/molmo_cleanup/molmo_realworld_cleanup_agent_server.py" not in sdk_runner_text
    assert "household_server_argv" in sdk_lifecycle_text
    assert "household_server_argv" in household_live_text


def test_agent_server_cli_accepts_canonical_household_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roboclaws.cli import agent_server

    calls: list[tuple[str, list[str]]] = []

    def fake_main(name: str):
        def _main(args: list[str]) -> int:
            calls.append((name, list(args)))
            return 0

        return _main

    monkeypatch.setitem(
        sys.modules,
        "roboclaws.cli.household_agent_server",
        types.SimpleNamespace(main=fake_main("cleanup")),
    )
    assert agent_server.main(["household-world", "--host", "127.0.0.1"]) == 0
    assert agent_server.main(["household-world", "--policy", "codex_agent"]) == 0
    assert calls == [
        ("cleanup", ["--host", "127.0.0.1"]),
        ("cleanup", ["--policy", "codex_agent"]),
    ]


def test_agent_server_cli_rejects_legacy_household_targets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from roboclaws.cli import agent_server

    def fail_if_called(_args: list[str]) -> int:
        raise AssertionError("legacy server target should not import a concrete server")

    monkeypatch.setitem(
        sys.modules,
        "roboclaws.cli.household_agent_server",
        types.SimpleNamespace(main=fail_if_called),
    )
    assert agent_server.main(["household-cleanup"]) == 2
    assert agent_server.main(["semantic-map-build"]) == 2

    stderr = capsys.readouterr().err
    assert "unsupported server 'household-cleanup'" in stderr
    assert "unsupported server 'semantic-map-build'" in stderr
    assert "expected household-world" in stderr


def test_agent_server_cli_errors_use_canonical_targets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from roboclaws.cli import agent_server

    assert agent_server.main(["semantic-map"]) == 2

    stderr = capsys.readouterr().err
    assert "expected household-world" in stderr
    assert "household-cleanup" not in stderr
    assert "semantic-map-build" not in stderr


def test_ci_does_not_define_codex_live_proof() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "molmo_official_codex" not in workflow
    assert "molmo-official-codex" not in workflow
    assert "report-molmo-official-codex" not in workflow
    assert "codex-provider-smoke" not in workflow
    assert ".tmp/coding-agent-bin/codex" not in workflow


def test_ci_no_longer_defines_retired_openclaw_game_smokes() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'ROBOCLAWS_MCP_ENABLED: "0"' not in workflow
    for retired_name in (
        "territory-openclaw-smoke",
        "coverage-openclaw-smoke",
        "openclaw-smoke",
        "photo-task-smoke",
        "real-model-smoke",
    ):
        assert retired_name not in workflow


def test_lower_level_just_modules_do_not_call_task_or_agent_facades() -> None:
    for path in JUST_DIR.glob("*.just"):
        if path.name in {"task.just", "agent.just"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "just task::" not in text, path
        assert "just agent::" not in text, path
