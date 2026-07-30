from __future__ import annotations

import json
import subprocess

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

    assert route == [
        "just",
        "harness::molmo-planner-proof-bundle-runner",
        "output/custom-planner-proof",
        "7",
        "帮我收拾这个房间",
        "10",
        "assets/maps/molmospaces/procthor-10k-val/0",
    ]


def test_map_build_rejects_public_map_mode_axis() -> None:
    stderr = assert_household_map_build_run_fails(
        "direct",
        "world-public-labels",
        "map_mode=minimal",
        "output_dir=output/custom-map",
    )

    assert "map_mode= is no longer a public run::surface argument" in stderr


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
