from __future__ import annotations

import importlib.util
import json
import shlex
from typing import Any

import pytest

import roboclaws.launch.executor as executor_module
import roboclaws.launch.household as household_launch_module
import roboclaws.launch.household_execution as household_execution_module
from roboclaws.core.backend_catalog import (
    cleanup_implementation_backend_ids,
    normalize_cleanup_implementation_backend,
)
from roboclaws.core.environment_setup_metadata import ENVIRONMENT_SETUP_METADATA_ENV
from roboclaws.core.goals import normalize_goal_contract
from roboclaws.core.task_intents import TASK_INTENT_SPECS
from roboclaws.launch.catalog import SURFACE_SPECS, LaunchError, resolve_surface_launch
from roboclaws.launch.runners import export_env_from_plan


def test_launch_package_does_not_keep_unused_context_holder() -> None:
    assert importlib.util.find_spec("roboclaws.launch.context") is None


def test_launch_backend_catalog_exposes_private_cleanup_implementation_choices() -> None:
    assert cleanup_implementation_backend_ids() == (
        "api_semantic_synthetic",
        "molmospaces_subprocess",
        "isaaclab_subprocess",
    )


def test_launch_backend_catalog_normalizes_cleanup_command_backend_values() -> None:
    assert normalize_cleanup_implementation_backend("auto") is None
    assert normalize_cleanup_implementation_backend("") is None
    assert normalize_cleanup_implementation_backend("isaaclab_subprocess") == (
        "isaaclab_subprocess"
    )

    with pytest.raises(ValueError, match="unsupported backend 'agibot_gdk'"):
        normalize_cleanup_implementation_backend("agibot_gdk")


def test_molmospaces_worlds_expose_only_mujoco_while_b1_exposes_isaac() -> None:
    molmo = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=map-build",
            "agent_engine=direct-runner",
            "evidence_lane=world-public-labels",
        ]
    )
    b1 = resolve_surface_launch(
        [
            "surface=household-world",
            "world=b1-map12",
            "backend=isaaclab",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "prompt=inspect the digital twin",
            "evidence_lane=world-public-labels",
            "map_bundle=injected/map-bundle",
            "isaac_scene_usd_path=injected/scene.usd",
            "b1_alignment_artifact=injected/alignment.json",
            "b1_navigation_artifact=injected/navigation.json",
        ]
    )

    assert molmo.world == "molmospaces/procthor-10k-val/0"
    assert molmo.backend == "mujoco"
    assert molmo.implementation_backend == "molmospaces_subprocess"
    assert b1.world == "b1-map12"
    assert b1.backend == "isaaclab"
    assert b1.implementation_backend == "isaaclab_subprocess"
    assert b1.adapter_options["map_bundle"] == "injected/map-bundle"
    assert b1.adapter_options["isaac_scene_usd_path"] == "injected/scene.usd"
    assert b1.adapter_options["b1_alignment_artifact"] == "injected/alignment.json"
    assert b1.adapter_options["b1_navigation_artifact"] == "injected/navigation.json"
    assert "b1_semantic_projection_artifact" not in b1.adapter_options
    assert "world" not in b1.adapter_options


def test_b1_launch_accepts_explicit_robot_consumption_proof_artifacts() -> None:
    b1 = resolve_surface_launch(
        [
            "surface=household-world",
            "world=b1-map12",
            "backend=isaaclab",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "prompt=inspect the digital twin",
            "evidence_lane=world-public-labels",
            "map_bundle=injected/map-bundle",
            "isaac_scene_usd_path=injected/scene.usd",
            "b1_alignment_artifact=output/b1-map12/alignment/alignment_residuals.json",
            "b1_navigation_artifact=output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json",
        ]
    )

    assert b1.adapter_options["b1_alignment_artifact"] == (
        "output/b1-map12/alignment/alignment_residuals.json"
    )
    assert b1.adapter_options["b1_navigation_artifact"] == (
        "output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json"
    )


def test_b1_launch_rejects_stale_semantic_projection_artifact_axis() -> None:
    with pytest.raises(
        LaunchError,
        match="unsupported launch override 'b1_semantic_projection_artifact'",
    ):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=b1-map12",
                "backend=isaaclab",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "prompt=inspect the digital twin",
                "evidence_lane=world-public-labels",
                "b1_semantic_projection_artifact=output/b1-map12/semantic-projection/semantic_projection.json",
            ]
        )


def test_molmospaces_world_rejects_public_isaac_backend() -> None:
    with pytest.raises(
        LaunchError,
        match="backend 'isaaclab' cannot run world 'molmospaces/procthor-10k-val/0'",
    ) as exc:
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=isaaclab",
                "intent=map-build",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
            ]
        )

    assert exc.value.hint == "expected mujoco"


def test_cleanup_surface_exposes_setup_overrides_but_dispatches_private_count() -> None:
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=cleanup",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "evidence_lane=world-public-labels",
            "seed=7",
            "scenario_setup=relocate-cleanup-related-objects",
            "relocation_count=3",
        ]
    )

    assert plan.scenario_setup == "relocate-cleanup-related-objects"
    assert plan.relocation_count == 3
    assert "generated_mess_count" not in plan.adapter_options
    exported = export_env_from_plan(plan)
    assert exported[ENVIRONMENT_SETUP_METADATA_ENV] == (
        '{"feeds_cleanup_scoring":true,"mode":"relocate-cleanup-related-objects",'
        '"relocated_objects":[],"relocation_count":3,'
        '"relocation_policy":"cleanup-related-objects","seed":7}'
    )


def test_household_non_cleanup_intents_default_to_baseline_setup() -> None:
    map_build = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=map-build",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "evidence_lane=world-public-labels",
        ]
    )
    open_ended = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=open-ended",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "evidence_lane=world-public-labels",
            "prompt=帮我找遥控器",
        ]
    )

    for plan in (map_build, open_ended):
        assert plan.scenario_setup == "baseline"
        assert plan.relocation_count is None
        assert '"mode":"baseline"' in export_env_from_plan(plan)[ENVIRONMENT_SETUP_METADATA_ENV]

    assert map_build.required_capabilities == ("household_world", "household_episode")
    assert open_ended.required_capabilities == (
        "household_world",
        "household_manipulation",
        "household_episode",
    )
    assert map_build.goal_contract.required_capabilities == map_build.required_capabilities
    assert open_ended.goal_contract.required_capabilities == open_ended.required_capabilities
    assert export_env_from_plan(map_build)["ROBOCLAWS_REQUIRED_CAPABILITY_PROFILES"] == (
        "household_world,household_episode"
    )


def test_household_runner_passes_resolved_goal_contract_directly_to_package_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_exec(
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        trace_args: list[str] | None = None,
    ) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setenv("ROBOCLAWS_JUST_TRACE", "1")
    monkeypatch.setattr(household_launch_module, "_exec_or_trace", fake_exec)
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "intent=open-ended",
            "prompt=find something useful",
            "evidence_lane=world-public-labels",
        ]
    )
    result = executor_module.execute_launch_plan(plan)

    assert result == 0
    assert captured["argv"][:4] == [
        ".venv/bin/python",
        "-m",
        "roboclaws.agents.household_live_runner",
        "--repo-root",
    ]
    assert captured["argv"].count("--server-arg=--goal-contract-json") == 1
    goal_arg = next(
        item for item in captured["argv"] if item.startswith("--server-arg={")
    ).removeprefix("--server-arg=")
    assert json.loads(goal_arg)["required_capabilities"] == [
        "household_world",
        "household_manipulation",
        "household_episode",
    ]


def test_agibot_live_map_build_uses_typed_provider_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_exec(
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        trace_args: list[str] | None = None,
    ) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.delenv("ROBOCLAWS_PROVIDER_PROFILE", raising=False)
    monkeypatch.setattr(executor_module, "resolve_optional_world_dependencies", lambda *a, **k: {})
    monkeypatch.setattr(executor_module, "_exec_or_trace", fake_exec)
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "world=agibot-g2/map-12",
            "backend=agibot-gdk",
            "preset=map-build",
            "agent_engine=openai-agents-sdk",
            "provider_profile=minimax-responses",
            "evidence_lane=world-public-labels",
            "context_json={}",
        ]
    )

    assert executor_module.execute_launch_plan(plan) == 0
    provider_flag = captured["argv"].index("--provider-profile")
    assert captured["argv"][provider_flag + 1] == "minimax-responses"


def test_rerun_command_rebuilds_public_axes_from_typed_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBOCLAWS_REPORT_RERUN_COMMAND", raising=False)
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "preset=cleanup",
            "agent_engine=direct-runner",
            "evidence_lane=world-public-labels",
            "prompt=put away the cups",
            "scenario_setup=relocate-cleanup-related-objects",
            "relocation_count=3",
            "output_dir=output/custom",
        ]
    )

    executor_module._export_rerun_command(plan=plan, adapter_options=plan.adapter_options)
    command = shlex.split(executor_module.os.environ["ROBOCLAWS_REPORT_RERUN_COMMAND"])

    assert command[:2] == ["just", "run::surface"]
    for argument in (
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "preset=cleanup",
        "agent_engine=direct-runner",
        "evidence_lane=world-public-labels",
        "prompt=put away the cups",
        "scenario_setup=relocate-cleanup-related-objects",
        "relocation_count=3",
        "output_dir=output/custom",
    ):
        assert argument in command
    assert sum(argument.startswith("surface=") for argument in command) == 1


def test_household_execution_normalizes_explicit_auto_minimum() -> None:
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "preset=cleanup",
            "agent_engine=direct-runner",
            "evidence_lane=world-public-labels",
            "scenario_setup=relocate-cleanup-related-objects",
            "relocation_count=3",
        ]
    )

    execution = household_execution_module.resolve_household_execution(
        plan,
        kv={"min_generated_mess_count": "auto"},
    )

    assert execution.min_generated_mess_count == 3


def test_household_goal_contract_tool_plans_do_not_advertise_static_fixture_projection() -> None:
    surface = SURFACE_SPECS["household-world"]

    for intent_id in ("cleanup", "map-build", "open-ended"):
        contract = normalize_goal_contract(
            surface=surface,
            intent=TASK_INTENT_SPECS[intent_id],
            raw_prompt="find something useful to drink" if intent_id == "open-ended" else "",
        )

        tool_plan_text = " ".join(contract.tool_plan)
        assert "static_fixture_projection" not in tool_plan_text
        assert "metric_map" in tool_plan_text


def test_surface_rejects_unknown_override_without_retired_axis_handling() -> None:
    with pytest.raises(
        LaunchError,
        match="unsupported launch override 'generated_mess_count'",
    ):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "evidence_lane=world-public-labels",
                "generated_mess_count=3",
            ]
        )


@pytest.mark.parametrize("axis", ("cleanup_object_count", "rehearsal_mode"))
def test_surface_rejects_retired_agibot_rehearsal_overrides(axis: str) -> None:
    with pytest.raises(LaunchError, match=rf"unsupported launch override '{axis}'"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
                f"{axis}=retired",
            ]
        )


def test_openai_agents_sdk_accepts_chat_provider_profiles() -> None:
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=cleanup",
            "agent_engine=openai-agents-sdk",
            "provider_profile=kimi-openai-chat",
            "evidence_lane=world-public-labels",
        ]
    )

    assert plan.provider_profile == "kimi-openai-chat"
    assert "provider_profile" not in plan.adapter_options


@pytest.mark.parametrize(
    ("axis", "hint"),
    (
        ("world", "omit world= to use the default"),
        ("backend", "omit backend= to use the default"),
        ("intent", "omit intent= to use the default"),
        ("preset", "omit preset= to use the default"),
        (
            "provider_profile",
            "select one of codex-responses|mimo-responses|mimo-tp-openai-chat|"
            "minimax-responses|kimi-openai-chat",
        ),
    ),
)
def test_launch_rejects_explicit_blank_optional_axes(axis: str, hint: str) -> None:
    args = [
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=cleanup",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "evidence_lane=world-public-labels",
    ]
    args = [item for item in args if not item.startswith(f"{axis}=")]
    args.append(f"{axis}= ")

    with pytest.raises(LaunchError, match=rf"{axis}= must be non-empty") as exc:
        resolve_surface_launch(args)

    assert hint in exc.value.hint


@pytest.mark.parametrize(
    ("agent_engine", "provider_profile", "env_key"),
    (("openai-agents-sdk", "kimi-openai-chat", "ROBOCLAWS_PROVIDER_PROFILE"),),
)
def test_provider_profile_env_export_uses_agent_engine_catalog(
    agent_engine: str,
    provider_profile: str,
    env_key: str,
) -> None:
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=cleanup",
            f"agent_engine={agent_engine}",
            f"provider_profile={provider_profile}",
            "evidence_lane=world-public-labels",
        ]
    )

    exported = export_env_from_plan(plan)

    assert exported[env_key] == provider_profile


def test_openai_agents_sdk_accepts_minimax_provider_profile() -> None:
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            "world=molmospaces/procthor-10k-val/0",
            "backend=mujoco",
            "intent=cleanup",
            "agent_engine=openai-agents-sdk",
            "provider_profile=minimax-responses",
            "evidence_lane=world-public-labels",
        ]
    )

    assert plan.provider_profile == "minimax-responses"
    assert "provider_profile" not in plan.adapter_options


def test_raw_fpv_rejects_routes_without_verified_image_transport() -> None:
    with pytest.raises(LaunchError, match="image_transport=unknown"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=openai-agents-sdk",
                "provider_profile=minimax-responses",
                "evidence_lane=camera-raw-fpv",
            ]
        )


@pytest.mark.parametrize("agent_engine", ("codex-cli", "claude-code", "future-engine"))
def test_unsupported_engines_use_one_canonical_error(agent_engine: str) -> None:
    with pytest.raises(
        LaunchError,
        match=(
            rf"unsupported agent_engine '{agent_engine}'; "
            r"expected direct-runner\|openai-agents-sdk"
        ),
    ):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                f"agent_engine={agent_engine}",
                "provider_profile=kimi-openai-chat",
                "evidence_lane=world-public-labels",
            ]
        )


@pytest.mark.parametrize(
    "override",
    (
        "driver=codex",
        "environment_setup=baseline",
        "map_mode=minimal",
        "profile=world-public-labels",
        "visual_grounding=grounding-dino",
    ),
)
def test_removed_axes_are_ordinary_unsupported_overrides(override: str) -> None:
    key = override.partition("=")[0]
    with pytest.raises(LaunchError, match=rf"unsupported launch override '{key}'"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                override,
            ]
        )


@pytest.mark.parametrize("override", ("--surface=household-world", "agent-engine=direct-runner"))
def test_launch_arguments_require_exact_canonical_key_spelling(override: str) -> None:
    key = override.partition("=")[0]
    with pytest.raises(LaunchError, match=rf"unsupported launch override '{key}'"):
        resolve_surface_launch([override])


def test_baseline_rejects_active_relocation_count() -> None:
    with pytest.raises(LaunchError, match="relocation_count is only valid"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "evidence_lane=world-public-labels",
                "scenario_setup=baseline",
                "relocation_count=3",
            ]
        )


def test_invalid_relocation_count_is_rejected() -> None:
    with pytest.raises(LaunchError, match="relocation_count must be >= 0"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "evidence_lane=world-public-labels",
                "scenario_setup=relocate-cleanup-related-objects",
                "relocation_count=-1",
            ]
        )


def test_loose_object_relocation_setup_is_not_publicly_supported() -> None:
    with pytest.raises(LaunchError, match="unsupported scenario_setup"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/procthor-10k-val/0",
                "backend=mujoco",
                "intent=cleanup",
                "agent_engine=openai-agents-sdk",
                "provider_profile=kimi-openai-chat",
                "evidence_lane=world-public-labels",
                "scenario_setup=relocate-loose-objects",
            ]
        )
