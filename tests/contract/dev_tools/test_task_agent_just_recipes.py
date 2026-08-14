from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from roboclaws.core.evaluation import checker_flags_for_household_intent
from roboclaws.launch import resolve_surface_launch
from roboclaws.launch.catalog import LaunchError
from roboclaws.launch.runners import export_env_from_plan

REPO_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE = REPO_ROOT / "justfile"
JUST_DIR = REPO_ROOT / "just"
AGENT_JUST = JUST_DIR / "agent.just"
MOLMO_JUST = JUST_DIR / "molmo.just"
CODING_AGENT_ENV = REPO_ROOT / "scripts" / "dev" / "coding_agent_env.sh"
LIVE_OPENAI_AGENTS_RUNNER = REPO_ROOT / "roboclaws/agents/household_live_runner.py"
HOUSEHOLD_LIVE_DRIVER = REPO_ROOT / "roboclaws" / "agents" / "drivers" / "household_live.py"
HOUSEHOLD_AGENT_SERVER_MODULE = "roboclaws.cli.agent_server"
CODE_AGENT_ENV_VARS = (
    "ROBOCLAWS_PROVIDER_PROFILE",
    "ROBOCLAWS_CODE_AGENT_MODEL",
    "KIMI_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_RESPONSES_BASE_URL",
    "CODEX_RESPONSES_API_KEY",
    "CODEX_RESPONSES_MODEL",
    "MIMO_RESPONSES_BASE_URL",
    "MIMO_RESPONSES_API_KEY",
    "MIMO_RESPONSES_MODEL",
    "KIMI_OPENAI_BASE_URL",
    "MM_BASE_URL",
    "MM_API_KEY",
)

_TEST_DIR = Path(__file__).resolve().parent
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from household_surface_trace import household_cleanup_args, household_map_build_args  # noqa: E402


def just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def just_summary() -> set[str]:
    result = subprocess.run(
        [just_bin(), "--summary"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.split())


def trace_household_cleanup_run(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> list[str]:
    return trace_surface_run(*household_cleanup_args(agent_engine, evidence_lane, *overrides))


def trace_household_map_build_run(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> list[str]:
    return trace_surface_run(*household_map_build_args(agent_engine, evidence_lane, *overrides))


def trace_household_cleanup_run_with_plan(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> tuple[list[str], list[str]]:
    return trace_surface_run_with_plan(
        *household_cleanup_args(agent_engine, evidence_lane, *overrides)
    )


def agibot_dependency_overrides(tmp_path: Path) -> tuple[str, ...]:
    runner_script = tmp_path / "agibot_runner.py"
    runner_script.write_text("# synthetic optional-world runner\n", encoding="utf-8")
    map_dir = tmp_path / "agibot_map"
    map_dir.mkdir()
    return (
        f"runner_script={runner_script}",
        f"runner_python={sys.executable}",
        f"agibot_map_artifact_dir={map_dir}",
    )


def _run_just(recipe: str, *args: str) -> subprocess.CompletedProcess[str]:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [binary, recipe, *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def trace_just(recipe: str, *args: str) -> list[str]:
    return _run_just(recipe, *args).stdout.strip().split("\t")


def trace_surface_run(*args: str) -> list[str]:
    return trace_just("run::surface", *args)


def trace_surface_run_with_plan(*args: str) -> tuple[list[str], list[str]]:
    result = _run_just("run::surface", *args)
    return result.stdout.strip().split("\t"), result.stderr.strip().split("\t")


def _b1_dependency_args(tmp_path: Path) -> tuple[str, ...]:
    map_bundle = tmp_path / "private-b1-map-canary"
    map_bundle.mkdir()
    values = {"isaac_scene_usd_path": tmp_path / "private-b1-scene-canary.usd"}
    values["b1_alignment_artifact"] = tmp_path / "private-b1-alignment-canary.json"
    values["b1_navigation_artifact"] = tmp_path / "private-b1-navigation-canary.json"
    for path in values.values():
        path.write_text("{}\n", encoding="utf-8")
    return (
        f"map_bundle={map_bundle}",
        *(f"{key}={path}" for key, path in values.items()),
    )


def trace_agent_harness(*args: str) -> list[str]:
    return trace_just("agent::harness", *args)


def trace_agent_verify(*args: str) -> list[str]:
    return trace_just("agent::verify", *args)


def trace_agent_mcp(*args: str) -> list[str]:
    return trace_just("agent::mcp", *args)


def assert_agent_mcp_fails(*args: str) -> str:
    binary = just_bin()
    env = os.environ.copy()
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "agent::mcp", *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    return result.stderr


def assert_household_cleanup_run_fails(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> str:
    return assert_surface_run_fails(
        *household_cleanup_args(agent_engine, evidence_lane, *overrides)
    )


def assert_household_map_build_run_fails(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> str:
    return assert_surface_run_fails(
        *household_map_build_args(agent_engine, evidence_lane, *overrides)
    )


def assert_surface_run_fails(*args: str) -> str:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "run::surface", *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    return result.stderr


def clean_code_agent_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in CODE_AGENT_ENV_VARS:
        env.pop(key, None)
    return env


def load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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


def test_agent_eval_recommend_writes_eval_harness_manifest(tmp_path: Path) -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    output_dir = tmp_path / "eval-harness"
    result = subprocess.run(
        [
            binary,
            "agent::eval",
            "recommend",
            f"output_dir={output_dir}",
            "changed_file=roboclaws/agents/drivers/openai_agents_live.py",
            "budget=focused",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"eval harness manifest: {output_dir / 'eval_harness.json'}" in result.stdout
    manifest = json.loads((output_dir / "eval_harness.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "roboclaws_eval_harness_manifest_v1"
    selected_row_ids = {row["row_id"] for row in manifest["rows"] if row["selected"]}
    assert "openai-agents-sdk-open-task-live-eval" in selected_row_ids
    assert (output_dir / "eval_harness.md").exists()
    assert (output_dir / "eval_harness.html").exists()


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


def test_old_codex_cleanup_harness_routes_are_unsupported() -> None:
    binary = just_bin()
    env = os.environ.copy()
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"

    agent_result = subprocess.run(
        [binary, "agent::harness", "codex-cleanup-harness8", "dry-run"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    molmo_result = subprocess.run(
        [binary, "molmo::codex-harness8", "dry-run"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert agent_result.returncode != 0
    assert "unsupported harness target 'codex-cleanup-harness8'" in agent_result.stderr
    assert molmo_result.returncode != 0


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


def test_agent_harness_no_longer_advertises_agent_validation() -> None:
    agent_text = AGENT_JUST.read_text(encoding="utf-8")
    harness_text = (JUST_DIR / "harness.just").read_text(encoding="utf-8")
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "agent-validation" not in agent_text
    assert "agent-validation" not in harness_text
    assert re.search(r"^eval \*overrides:", agent_text, re.MULTILINE)
    assert "codex-cleanup-harness8" not in agent_text
    assert "codex-cleanup-harness8" not in harness_text
    assert "codex-harness8" not in molmo_text


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


def test_surface_open_ended_supports_mcp_smoke_for_local_gate() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=direct-runner",
            "run_preset=smoke",
            "evidence_lane=world-public-labels",
            "prompt=我渴了，帮我找些解渴的东西",
        )
    )
    env = export_env_from_plan(plan)

    assert plan.surface == "household-world"
    assert plan.intent == "open-ended"
    assert plan.preset is None
    assert plan.skill_name == "household-world"
    assert plan.agent_engine == "direct-runner"
    assert plan.dispatch_runner == "mcp-smoke"
    assert plan.internal_runner_class == "smoke"
    assert plan.goal_contract.goal_scope == "agent-declared"
    assert env["ROBOCLAWS_TASK_INTENT"] == "open-ended"
    assert "ROBOCLAWS_TASK_PRESET" not in env
    assert env["ROBOCLAWS_TASK_SKILL"] == "household-world"
    assert json.loads(env["ROBOCLAWS_GOAL_CONTRACT_JSON"])["intent"] == "open-ended"


def test_surface_launch_rejects_smoke_as_public_evidence_lane() -> None:
    with pytest.raises(LaunchError, match="smoke is not an evidence lane") as exc:
        resolve_surface_launch(
            (
                "surface=household-world",
                "agent_engine=direct-runner",
                "preset=cleanup",
                "evidence_lane=smoke",
            )
        )

    assert exc.value.hint == "use run_preset=smoke with evidence_lane=world-public-labels"


def test_surface_launch_rejects_public_profile_alias() -> None:
    with pytest.raises(
        LaunchError,
        match="profile= is no longer a public run::surface argument",
    ) as exc:
        resolve_surface_launch(
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "profile=world-public-labels",
            )
        )

    assert "use evidence_lane=" in str(exc.value.hint)


def test_surface_launch_rejects_public_visual_grounding_axis() -> None:
    with pytest.raises(
        LaunchError,
        match="visual_grounding is no longer a public task axis",
    ) as exc:
        resolve_surface_launch(
            (
                "surface=household-world",
                "agent_engine=direct-runner",
                "preset=cleanup",
                "evidence_lane=camera-grounded-labels",
                "camera_labeler=grounding-dino",
                "visual_grounding=grounding-dino",
            )
        )

    assert exc.value.hint == (
        "use camera_labeler=<labeler> with evidence_lane=camera-grounded-labels"
    )


def test_surface_launch_rejects_public_map_mode_axis() -> None:
    with pytest.raises(
        LaunchError,
        match="map_mode= is no longer a public run::surface argument",
    ) as exc:
        resolve_surface_launch(
            (
                "surface=household-world",
                "agent_engine=direct-runner",
                "preset=cleanup",
                "map_mode=minimal",
            )
        )

    assert "Base Metric Map" in str(exc.value.hint)
    assert "runtime_map_prior=" in str(exc.value.hint)


def test_surface_cleanup_prompt_stays_cleanup_intent_when_explicit() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=cleanup",
            "prompt=只收拾桌面上的杯子",
        )
    )

    assert plan.surface == "household-world"
    assert plan.intent == "cleanup"
    assert plan.preset == "cleanup"
    assert plan.skill_name == "household-world"
    assert plan.prompt_id == "household_cleanup"
    assert plan.checker_id == "cleanup_report"
    assert plan.goal_contract.goal_scope == "prompt-scoped"
    assert plan.goal_contract.raw_prompt == "只收拾桌面上的杯子"
    assert "user-scoped request" in plan.goal_contract.normalized_goal


def test_surface_launch_plan_exposes_typed_goal_contract() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=map-build",
        )
    )

    assert plan.surface == "household-world"
    assert plan.world == "molmospaces/procthor-10k-val/0"
    assert plan.backend == "mujoco"
    assert plan.implementation_backend == "molmospaces_subprocess"
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.provider_profile == "kimi-openai-chat"
    assert plan.intent == "map-build"
    assert plan.preset == "map-build"
    assert plan.evidence_mode == "camera-grounded-labels"
    assert "camera_labeler=grounding-dino" in plan.overrides
    assert plan.skill_name == "household-world"
    assert plan.dispatch_target == "household-world"
    assert plan.goal_contract.schema == "roboclaws_goal_contract_v1"
    assert plan.goal_contract.surface == "household-world"
    assert plan.goal_contract.intent == "map-build"
    assert plan.goal_contract.goal_scope == "whole-room"
    assert json.loads(export_env_from_plan(plan)["ROBOCLAWS_GOAL_CONTRACT_JSON"])["intent"] == (
        "map-build"
    )
    assert not any(item.startswith("goal_contract_json=") for item in plan.overrides)


def test_surface_map_build_defaults_to_openai_agents_sdk_camera_grounded_dino() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=map-build",
        )
    )

    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.dispatch_runner == "openai-agents-live"
    assert plan.provider_profile == "kimi-openai-chat"
    assert plan.evidence_mode == "camera-grounded-labels"
    assert plan.profile == "camera-grounded-labels"
    assert "camera_labeler=grounding-dino" in plan.overrides
    assert plan.implementation_backend == "molmospaces_subprocess"


def test_surface_launch_exports_goal_contract_to_lower_recipe_environment() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=direct-runner",
            "preset=cleanup",
            "run_preset=smoke",
            "evidence_lane=world-public-labels",
        )
    )
    env = export_env_from_plan(plan)

    assert env["ROBOCLAWS_TASK_SURFACE"] == "household-world"
    assert env["ROBOCLAWS_TASK_INTENT"] == "cleanup"
    assert env["ROBOCLAWS_TASK_PRESET"] == "cleanup"
    assert env["ROBOCLAWS_TASK_SKILL"] == "household-world"
    assert json.loads(env["ROBOCLAWS_GOAL_CONTRACT_JSON"])["intent"] == "cleanup"


def test_surface_launch_exports_operator_session_context_to_lower_recipe_environment() -> None:
    context = json.dumps(
        {
            "schema": "operator_console_next_goal_packet_v1",
            "operator_session_id": "session-test",
            "parent_run_id": "parent-run",
        },
        sort_keys=True,
    )
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "prompt=next task",
            "evidence_lane=world-public-labels",
            f"operator_session_context_json={context}",
        )
    )
    env = export_env_from_plan(plan)

    assert env["ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON"] == context
    assert f"operator_session_context_json={context}" in plan.overrides
    assert json.loads(env["ROBOCLAWS_GOAL_CONTRACT_JSON"])["normalized_goal"] == "next task"


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


def test_household_checker_flags_are_generated_from_intent_policy() -> None:
    cleanup_flags = checker_flags_for_household_intent(
        intent_id="cleanup",
        profile="world-public-labels",
        min_generated_mess_count="5",
    )
    open_flags = checker_flags_for_household_intent(
        intent_id="open-ended",
        profile="world-public-labels",
        min_generated_mess_count="5",
    )
    map_flags = checker_flags_for_household_intent(
        intent_id="map-build",
        profile="world-public-labels",
        min_generated_mess_count="5",
    )

    for flags in (cleanup_flags, open_flags, map_flags):
        assert "--require-goal-contract" in flags
        assert "--require-completion-claim" in flags
    assert "--require-clean-agent-run" in cleanup_flags
    assert "--allow-partial-cleanup" not in cleanup_flags
    assert "--require-clean-agent-run" not in open_flags
    assert "--allow-partial-cleanup" not in open_flags
    assert "--require-runtime-metric-map" in map_flags
    assert "--allow-partial-cleanup" in map_flags


def test_openai_agents_runner_script_uses_runtime_contract_and_checker() -> None:
    runner_text = LIVE_OPENAI_AGENTS_RUNNER.read_text(encoding="utf-8")

    assert "OpenAIAgentsLiveRuntime" in runner_text
    assert "LiveAgentRequest" in runner_text
    assert "household_server_argv" in runner_text
    assert 'CHECKER_MODULE = "roboclaws.household.cleanup_validation_cli"' in runner_text
    assert "CHECKER_SCRIPT" not in runner_text


@pytest.mark.parametrize(
    "surface", ("molmospace-cleanup", "molmospaces-cleanup", "cleanup-report", "household-cleanup")
)
def test_surface_router_rejects_removed_compatibility_aliases(surface: str) -> None:
    stderr = assert_surface_run_fails(f"surface={surface}", "agent_engine=openai-agents-sdk")

    assert f"unsupported surface '{surface}'" in stderr


@pytest.mark.parametrize(
    ("surface_args", "expected"),
    (
        (
            ("surface=household-world", "agent_engine=openai-agents-live", "preset=cleanup"),
            "unsupported agent_engine 'openai-agents-live'",
        ),
        (
            ("surface=household-world", "agent_engine=claude-live", "preset=cleanup"),
            "unsupported agent_engine 'claude-live'",
        ),
        (
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "evidence_lane=world-public-labels-perf",
            ),
            "unsupported household-world evidence_lane",
        ),
        (
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "evidence_lane=minimal",
            ),
            "unsupported household-world evidence_lane",
        ),
        (
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "evidence_lane=visual",
            ),
            "unsupported household-world evidence_lane",
        ),
        (
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "evidence_lane=world-public-labels",
                "cleanup_routine=mcp",
            ),
            "unsupported cleanup_routine",
        ),
        (
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "evidence_lane=world-public-labels",
                "generated_mess_count=5",
            ),
            "generated_mess_count is no longer",
        ),
    ),
)
def test_surface_router_rejects_invalid_current_axis_values(
    surface_args: tuple[str, ...], expected: str
) -> None:
    stderr = assert_surface_run_fails(*surface_args)

    assert expected in stderr


def test_surface_router_is_importable_source_of_truth() -> None:
    resolved = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=cleanup",
            "run_preset=smoke",
            "evidence_lane=world-public-labels",
            "output_dir=output/custom",
        )
    )

    assert "output_dir=output/custom" in resolved.overrides
    assert resolved.scenario_setup == "relocate-cleanup-related-objects"
    assert resolved.relocation_count == 5
    assert resolved.world == "molmospaces/procthor-10k-val/0"
    assert resolved.backend == "mujoco"
    assert resolved.agent_engine == "openai-agents-sdk"
    assert resolved.provider_profile == "kimi-openai-chat"
    assert resolved.evidence_mode == "smoke"

    with pytest.raises(LaunchError, match="unsupported surface 'molmospace-cleanup'"):
        resolve_surface_launch(("surface=molmospace-cleanup", "agent_engine=openai-agents-sdk"))


def test_surface_launch_plan_exposes_domain_metadata_before_dispatch() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "world=agibot-g2/map-12",
            "backend=agibot-gdk",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=cleanup",
            "run_preset=smoke",
            "evidence_lane=world-public-labels",
        )
    )

    assert plan.scenario_setup == "relocate-cleanup-related-objects"
    assert plan.relocation_count == 5
    assert plan.implementation_backend == "agibot_gdk"
    assert plan.dispatch_target == "household-world"
    assert plan.preset == "cleanup"
    assert plan.skill_name == "household-world"
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.dispatch_runner == "openai-agents-live"
    assert plan.profile == "smoke"
    assert plan.report is None
    assert plan.world == "agibot-g2/map-12"
    assert plan.backend == "agibot-gdk"
    assert plan.implementation_backend == "agibot_gdk"
    assert plan.prompt_id == "household_cleanup"
    assert plan.checker_id == "cleanup_report"
    assert plan.required_capabilities == (
        "household_world",
        "household_manipulation",
        "household_episode",
    )


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


def test_python_launch_plan_accepts_world_labels_sanitized_lane() -> None:
    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=cleanup",
            "evidence_lane=world-public-labels",
        )
    )

    assert plan.evidence_mode == "world-public-labels"
    assert plan.profile == "world-public-labels"
    assert plan.scenario_setup == "relocate-cleanup-related-objects"
    assert plan.relocation_count == 5
    assert plan.implementation_backend == "molmospaces_subprocess"


def test_prompt_mapping_rejects_retired_ai2thor_nav_task() -> None:
    stderr = assert_surface_run_fails("surface=ai2thor-nav", "agent_engine=openclaw-gateway")

    assert "unsupported surface 'ai2thor-nav'" in stderr
    assert "expected household-world|planner-proof" in stderr


def test_planner_proof_surface_route_passes_default_map_bundle() -> None:
    route = trace_surface_run(
        "surface=planner-proof",
        "agent_engine=direct-runner",
        "output_dir=output/custom-planner-proof",
    )

    assert route == [
        "just",
        "harness::molmo-planner-proof-bundle-runner",
        "output/custom-planner-proof",
        "7",
        "帮我收拾这个房间",
        "10",
        "assets/maps/molmospaces/procthor-10k-val/0",
    ]


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


def test_map_build_rejects_public_map_mode_axis() -> None:
    stderr = assert_household_map_build_run_fails(
        "direct",
        "world-public-labels",
        "map_mode=minimal",
        "output_dir=output/custom-map",
    )

    assert "map_mode= is no longer a public run::surface argument" in stderr


def test_household_cleanup_rejects_public_legacy_rich_map_mode() -> None:
    stderr = assert_household_cleanup_run_fails(
        "direct",
        "world-public-labels",
        "map_mode=rich",
    )

    assert "map_mode= is no longer a public run::surface argument" in stderr


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


def test_b1_public_launch_rejects_stale_semantic_projection_artifact_axis() -> None:
    with pytest.raises(subprocess.CalledProcessError) as exc:
        trace_surface_run_with_plan(
            "surface=household-world",
            "world=b1-map12",
            "backend=isaaclab",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "prompt=inspect the digital twin",
            "evidence_lane=world-public-labels",
            "b1_semantic_projection_artifact=output/b1-map12/semantic-projection/semantic_projection.json",
        )
    assert "b1_semantic_projection_artifact= is no longer" in exc.value.stderr


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


def test_molmo_camera_raw_prompt_contains_run_constraints_not_generic_strategy() -> None:
    prompt = render_kickoff_prompt("camera-raw-fpv")

    assert "cleanup MCP tool entries exactly as exposed by Codex" in prompt
    assert "namespace cleanup" in prompt
    assert "server named cleanup" not in prompt
    assert "never mcp__cleanup__" in prompt
    assert "Per-waypoint observation budget=4" in prompt
    assert "Evidence lane=camera-raw-fpv" in prompt
    assert "Raw-FPV candidate-attempt budget=24" in prompt
    assert "Cleanup target cap=7" in prompt
    assert "Done retry budget=1" in prompt
    assert "navigate_to_relative_pose" not in prompt
    assert "overlap probe" not in prompt
    assert "Required closeout artifacts" in prompt
    assert "place/place_inside" not in prompt


def test_molmo_camera_raw_prompt_scales_to_requested_cleanup_count() -> None:
    prompt = render_kickoff_prompt("camera-raw-fpv", target_cleanup_count=5)

    assert "Cleanup target cap=5" in prompt
    assert "at least seven grounded cleanup chains have succeeded" not in prompt


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


def test_molmo_live_kickoff_prompt_receives_success_threshold_for_camera_raw() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert 'prompt_cleanup_count="$generated_mess_count"' in text
    assert 'prompt_cleanup_count="$generated_mess_success_threshold"' in text
    assert '--target-cleanup-count "$prompt_cleanup_count"' in text
    assert "--task-intent-mode" not in text


def test_openai_agents_cleanup_checker_policy_uses_checker_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script_module(
        LIVE_OPENAI_AGENTS_RUNNER,
        "household_live_runner_checker_profile_test",
    )
    run_dir = tmp_path / "openai-agents"
    run_dir.mkdir()
    (run_dir / "run_result.json").write_text("{}\n", encoding="utf-8")
    captured_commands: list[list[str]] = []

    def fake_run_and_tee(command, *, cwd, stdout_path, stderr_path, env, **_kwargs):
        captured_commands.append(command)
        stdout_path.write_text("checker ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(module.household_live_driver, "run_and_tee", fake_run_and_tee)
    args = SimpleNamespace(
        run_dir=run_dir,
        repo_root=REPO_ROOT,
        status_path=run_dir / "live_status.json",
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "openai-agents.lock",
        server_startup_timeout_s=1.0,
        kickoff_prompt="custom prompt",
        backend="molmospaces_subprocess",
        run_id="household-world",
        intent="cleanup",
        policy="openai_agents_agent",
        task="帮我收拾这个房间",
        min_generated_mess_count="5",
        profile="smoke",
        checker_profile="world-public-labels",
        server_arg=[],
        checker_visual_arg=[],
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        max_turns=128,
        incomplete_turn_continuation_attempts=0,
        cache_tools_list=True,
    )

    runner = module.LiveOpenAIAgentsHouseholdRunner(args)
    runner._check_result()

    assert captured_commands
    checker_command = captured_commands[0]
    assert checker_command[checker_command.index("--expect-profile") + 1] == ("world-public-labels")
    assert "--require-clean-agent-run" in checker_command
    assert "--require-waypoint-honesty" in checker_command
    assert "--require-real-robot-alignment" in checker_command
    assert checker_command[checker_command.index("--min-semantic-accepted-count") + 1] == "5"
    assert checker_command[checker_command.index("--min-sweep-coverage") + 1] == "1.0"


def test_molmo_world_labels_prompt_requires_nav2_bundle_checklist() -> None:
    prompt = render_kickoff_prompt("world-public-labels")

    assert "This run is surface=household-world intent=cleanup" in prompt
    assert "User task: clean up this room" in prompt
    assert "Evidence lane=world-public-labels" in prompt
    assert "visible_object_detections" in prompt
    assert "private destination truth" in prompt
    assert "cleanup MCP tool entries exactly as exposed by Codex" in prompt
    assert "namespace cleanup" in prompt
    assert "server named cleanup" not in prompt
    assert "never mcp__cleanup__" in prompt
    assert "roboclaws__" in prompt
    assert "Required closeout artifacts" in prompt
    assert "navigate_to_waypoint" not in prompt


def test_molmo_cleanup_live_prompt_includes_open_ended_user_task() -> None:
    prompt = render_kickoff_prompt(
        "world-public-labels",
        task="我渴了，帮我找些解渴的东西",
        intent="open-ended",
    )

    assert "This run is surface=household-world with no task preset" in prompt
    assert "custom operator task" not in prompt
    assert "The following operator task is authoritative" in prompt
    assert "我渴了，帮我找些解渴的东西" in prompt
    assert "Evidence lane=world-public-labels" in prompt
    assert "Use the MCP tools as a bounded household robot capability surface" in prompt
    assert "Use the household MCP tool entries exactly as exposed by Codex" in prompt
    assert "Use the bundled household-world skill instructions" in prompt
    assert "cleanup MCP tool entries exactly as exposed by Codex" not in prompt
    assert "room-cleanup routine" not in prompt
    assert "visual-scan prerequisite" not in prompt
    assert "unrelated pending cleanup candidates" not in prompt
    assert "cleanup goals from cleanup implementation details" not in prompt
    assert "build an exact waypoint checklist" not in prompt
    assert "sweep every waypoint" not in prompt
    assert "fresh same-handle source FPV observation" not in prompt
    assert "cleaned every public recommended candidate" not in prompt
    assert "call done only after every metric_map.inspection_waypoints" not in prompt


def test_molmo_open_ended_camera_grounded_prompt_requires_label_declaration() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        task=(
            "巡检 B1 / Map 12 digital twin，使用相机 grounded label "
            "证据报告你看到的至少一个公开候选目标，并在证据足够后调用 done。"
        ),
        intent="open-ended",
    )

    assert "This run is surface=household-world with no task preset" in prompt
    assert "Camera-grounded observation mode=observe plus" in prompt
    assert "declare_visual_candidates with observation_id only" in prompt
    assert "configured camera labeler labels the frame" not in prompt
    assert "Required closeout artifacts" in prompt


def test_molmo_open_ended_camera_grounded_prompt_can_use_composite_tool() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        task="inspect B1 camera grounded candidates",
        intent="open-ended",
        camera_grounded_composite_tools=True,
    )

    assert "Camera-grounded observation mode=composite" in prompt
    assert "observe_camera_grounded_candidates" in prompt
    assert "configured camera labeler labels the current FPV frame" not in prompt


def test_molmo_cleanup_live_prompt_uses_cleanup_intent_without_open_ended_intent() -> None:
    prompt = render_kickoff_prompt(
        "world-public-labels",
        task="我渴了，帮我找些解渴的东西",
    )

    assert "This run is surface=household-world intent=cleanup" in prompt
    assert "This run is surface=household-world with no task preset" not in prompt
    assert "The operator task is the only goal" not in prompt
    assert "Use the bundled household-world skill instructions" in prompt


def test_molmo_world_labels_prompt_uses_single_lane_default() -> None:
    prompt = render_kickoff_prompt("world-public-labels")

    assert "Evidence lane=world-public-labels" in prompt
    assert "visible_object_detections" in prompt
    assert "navigate_to_waypoint then observe" not in prompt
    assert "pending_cleanup_candidates" not in prompt
    assert "cleanup_recommended" not in prompt
    assert "first complete an anchor discovery sweep" not in prompt


def test_molmo_label_prompts_keep_public_done_boundary() -> None:
    world_prompt = render_kickoff_prompt("world-public-labels")
    camera_prompt = render_kickoff_prompt("camera-grounded-labels")

    assert "Evidence lane=world-public-labels" in world_prompt
    assert "observe -> candidate decision" not in world_prompt
    assert "pending_cleanup_candidates" not in world_prompt
    assert "only the MCP done response creates the authoritative run result" in world_prompt
    assert "Evidence lane=camera-grounded-labels" in camera_prompt
    assert "declare_visual_candidates with observation_id only" in camera_prompt
    assert "only the MCP done response creates the authoritative run result" in camera_prompt


def test_molmo_compact_camera_prompt_can_prefer_composite_observe_tool() -> None:
    prompt = render_kickoff_prompt(
        "camera-grounded-labels",
        camera_grounded_composite_tools=True,
    )

    assert "Camera-grounded observation mode=composite" in prompt
    assert "observe_camera_grounded_candidates" in prompt
    assert "response already includes the server-side declaration" in prompt
    assert (
        "do not call declare_visual_candidates again for the same source_observation_id" in prompt
    )
    assert "only the MCP done response creates the authoritative run result" in prompt


def test_molmo_just_openai_agents_composite_env_forwards_prompt_flag() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS" in text
    assert "prompt_args+=(--camera-grounded-composite-tools)" in text
    assert (
        '[[ "$driver" == "openai-agents-live" && "$profile" == "camera-grounded-labels" ]]' in text
    )


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


def test_molmo_raw_fpv_compact_prompt_includes_budget_contract() -> None:
    prompt = render_kickoff_prompt(
        "camera-raw-fpv",
        target_cleanup_count=5,
        raw_fpv_candidate_budget=3,
        max_observe_per_waypoint=2,
        done_retry_budget=1,
    )

    assert "Evidence lane=camera-raw-fpv" in prompt
    assert "Raw-FPV candidate-attempt budget=3" in prompt
    assert "Per-waypoint observation budget=2" in prompt
    assert "Done retry budget=1" in prompt
    assert "adjust_camera" not in prompt
    assert "distinct robot-body heading" not in prompt
    assert "only the MCP done response creates the authoritative run result" in prompt


def test_molmo_live_openai_agents_uses_single_lane_default_prompt() -> None:
    text = MOLMO_JUST.read_text(encoding="utf-8")

    assert "ROBOCLAWS_OPENAI_AGENTS_PROMPT_MODE" not in text
    assert "--prompt-mode" not in text
    assert '--raw-fpv-candidate-budget "$prompt_raw_fpv_candidate_budget"' in text
    assert '--max-observe-per-waypoint "$prompt_max_observe_per_waypoint"' in text
    assert 'prompt_max_observe_per_waypoint="4"' in text
    assert '--done-retry-budget "$prompt_done_retry_budget"' in text
    assert 'runner_args+=(--max-turns "${ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS}")' in text
    assert '--max-turns "${ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS:-128}"' not in text


def test_map_build_live_prompt_disables_cleanup_actions() -> None:
    prompt = render_map_build_prompt(
        "camera-grounded-labels",
        "帮我建立这个房间的 Runtime Metric Map",
    )

    assert "This run is surface=household-world intent=map-build" in prompt
    assert "User task: 帮我建立这个房间的 Runtime Metric Map" in prompt
    assert "Use the bundled household-world skill instructions" in prompt
    assert "Manipulation tools are not entitled for this run" in prompt
    assert "Evidence lane=camera-grounded-labels" in prompt
    assert "Waypoint observation tool=observe" in prompt
    assert "scan_profile=fixture-focused" in prompt
    assert "body-turn count per waypoint=4" in prompt
    assert "body-turn yaw delta deg=90" in prompt
    assert "profile observe cadence=5 per waypoint" in prompt
    assert "effective observe cadence=5 per waypoint" in prompt
    assert "max_observe_per_waypoint override=false" in prompt
    assert "profile body-turn cadence overridden=false" in prompt
    assert "stable-anchor priority=true" in prompt
    assert "fixtures, surfaces, receptacles" in prompt
    assert "movable-prior policy=" in prompt
    assert "navigate_to_relative_pose" not in prompt
    assert "runtime_metric_map.json" in prompt


def test_live_agent_server_routes_use_cli_modules_not_examples() -> None:
    molmo_text = MOLMO_JUST.read_text(encoding="utf-8")
    sdk_runner_text = LIVE_OPENAI_AGENTS_RUNNER.read_text(encoding="utf-8")
    household_live_text = HOUSEHOLD_LIVE_DRIVER.read_text(encoding="utf-8")

    assert "roboclaws.agents.household_live_runner" in molmo_text
    assert "roboclaws.cli.agent_server household-cleanup" not in molmo_text
    assert "examples/molmo_cleanup/molmo_realworld_cleanup_agent_server.py" not in molmo_text
    assert "examples/molmo_cleanup/molmo_realworld_cleanup_agent_server.py" not in sdk_runner_text
    assert "household_server_argv" in sdk_runner_text
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


def test_coding_agent_env_shell_profile_facts_match_python_registry() -> None:
    env = clean_code_agent_env()
    env["ROBOCLAWS_HELPER"] = str(CODING_AGENT_ENV)
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -euo pipefail
            source "$ROBOCLAWS_HELPER"
            roboclaws_code_agent_profile_default_model minimax-responses
            roboclaws_code_agent_profile_wire_api kimi-openai-chat
            roboclaws_code_agent_profile_key_env codex-responses
            roboclaws_code_agent_profile_key_env mimo-responses
            """,
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    python_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "roboclaws.agents.provider_registry",
            "default-model",
            "minimax-responses",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        python_result.stdout.strip(),
        "chat-completions",
        "CODEX_RESPONSES_API_KEY",
        "MIMO_RESPONSES_API_KEY",
    ]


def test_openai_agents_launcher_applies_provider_overrides_per_invocation() -> None:
    helper_text = CODING_AGENT_ENV.read_text(encoding="utf-8")

    plan = resolve_surface_launch(
        (
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "preset=cleanup",
            "evidence_lane=world-public-labels",
        )
    )
    exported_env = export_env_from_plan(plan)

    assert plan.provider_profile == "kimi-openai-chat"
    assert exported_env["ROBOCLAWS_PROVIDER_PROFILE"] == "kimi-openai-chat"
    assert not any(item.startswith("provider_profile=") for item in plan.overrides)

    assert "MM_API_KEY" in helper_text
    assert "MM_BASE_URL" in helper_text
    assert "KIMI_API_KEY" in helper_text
    assert "CODEX_RESPONSES_API_KEY" in helper_text
    assert "MIMO_RESPONSES_API_KEY" in helper_text


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


def test_lower_level_just_modules_do_not_call_task_or_agent_facades() -> None:
    for path in JUST_DIR.glob("*.just"):
        if path.name in {"task.just", "agent.just"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "just task::" not in text, path
        assert "just agent::" not in text, path
