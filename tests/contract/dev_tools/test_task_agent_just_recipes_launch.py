from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from roboclaws.launch import resolve_surface_launch
from roboclaws.launch.catalog import LaunchError
from roboclaws.launch.runners import export_env_from_plan
from tests.contract.dev_tools.task_agent_just_recipes_support import (
    CODING_AGENT_ENV,
    assert_household_map_build_run_fails,
    assert_surface_run_fails,
    trace_surface_run,
    trace_surface_run_with_plan,
)

REPO_PYTHON = str(Path(__file__).resolve().parents[3] / ".venv/bin/python")


def _option_value(args: list[str], option: str) -> str:
    return args[args.index(option) + 1]


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


@pytest.mark.parametrize(
    "override",
    (
        "profile=world-public-labels",
        "visual_grounding=grounding-dino",
        "map_mode=minimal",
    ),
)
def test_surface_launch_rejects_removed_axes_as_unknown(override: str) -> None:
    key = override.partition("=")[0]
    with pytest.raises(LaunchError, match=rf"unsupported launch override '{key}'"):
        resolve_surface_launch(
            (
                "surface=household-world",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "preset=cleanup",
                "evidence_lane=camera-grounded-labels",
                "camera_labeler=grounding-dino",
                override,
            )
        )


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
    assert plan.adapter_options["camera_labeler"] == "grounding-dino"
    assert plan.skill_name == "household-world"
    assert plan.dispatch_target == "household-world"
    assert plan.goal_contract.schema == "roboclaws_goal_contract_v1"
    assert plan.goal_contract.surface == "household-world"
    assert plan.goal_contract.intent == "map-build"
    assert plan.goal_contract.goal_scope == "whole-room"
    assert json.loads(export_env_from_plan(plan)["ROBOCLAWS_GOAL_CONTRACT_JSON"])["intent"] == (
        "map-build"
    )
    assert "goal_contract_json" not in plan.adapter_options


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
    assert plan.adapter_options["camera_labeler"] == "grounding-dino"
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
    assert plan.adapter_options["operator_session_context_json"] == context
    assert json.loads(env["ROBOCLAWS_GOAL_CONTRACT_JSON"])["normalized_goal"] == "next task"


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
            "unsupported launch override 'cleanup_routine'",
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
            "unsupported launch override 'generated_mess_count'",
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

    assert resolved.adapter_options["output_dir"] == "output/custom"
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


def test_planner_proof_surface_route_passes_default_map_bundle() -> None:
    route = trace_surface_run(
        "surface=planner-proof",
        "agent_engine=direct-runner",
        "output_dir=output/custom-planner-proof",
    )

    assert route[:4] == [
        "cmd",
        REPO_PYTHON,
        "-m",
        "roboclaws.household.planner_proof_execution",
    ]
    assert _option_value(route, "--output-dir") == "output/custom-planner-proof"
    assert _option_value(route, "--mode") == "dry-run"
    assert _option_value(route, "--seed") == "7"
    assert _option_value(route, "--task") == "帮我收拾这个房间"
    assert _option_value(route, "--generated-mess-count") == "10"
    assert _option_value(route, "--map-bundle-dir") == (
        "assets/maps/molmospaces/procthor-10k-val/0"
    )


def test_map_build_rejects_public_map_mode_axis() -> None:
    stderr = assert_household_map_build_run_fails(
        "direct",
        "world-public-labels",
        "map_mode=minimal",
        "output_dir=output/custom-map",
    )

    assert "unsupported launch override 'map_mode'" in stderr


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
    assert "unsupported launch override 'b1_semantic_projection_artifact'" in exc.value.stderr


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
    assert "provider_profile" not in plan.adapter_options

    assert "MM_API_KEY" in helper_text
    assert "MM_BASE_URL" in helper_text
    assert "KIMI_API_KEY" in helper_text
    assert "CODEX_RESPONSES_API_KEY" in helper_text
    assert "MIMO_RESPONSES_API_KEY" in helper_text
