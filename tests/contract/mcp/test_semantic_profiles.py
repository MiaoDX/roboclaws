from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

import roboclaws.mcp.entrypoint as entrypoint_module
from roboclaws.mcp.entrypoint import (
    MCPProfileRouter,
    load_contract_profile,
    register_profile_tools,
)
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
    ContractProfile,
    ToolDescriptor,
    assert_public_profile_metadata_safe,
    contract_profile,
    contract_profile_names,
    validate_contract_profile,
)


class FakeFastMCP:
    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}

    def tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        **_: Any,
    ):
        def decorator(func: Any) -> Any:
            self.tools[name or func.__name__] = {"description": description, "func": func}
            return func

        return decorator


def _handlers(profile_id: str) -> dict[str, Any]:
    return {
        name: (lambda **_: {"ok": True})
        for name in contract_profile(profile_id).public_tool_names()
    }


def _composed_handlers(profile_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        name: (lambda **_: {"ok": True})
        for profile_id in profile_ids
        for name in contract_profile(profile_id).public_tool_names()
    }


def test_contract_profile_registry_contains_only_task_neutral_capability_profiles() -> None:
    assert contract_profile_names() == (
        HOUSEHOLD_WORLD_PROFILE,
        HOUSEHOLD_MANIPULATION_PROFILE,
        HOUSEHOLD_EPISODE_PROFILE,
    )


@pytest.mark.parametrize("profile_id", ("molmospaces_cleanup_v1", "real_robot_cleanup_v1"))
def test_cleanup_shaped_profiles_are_removed(profile_id: str) -> None:
    with pytest.raises(ValueError, match="unsupported MCP contract profile"):
        contract_profile(profile_id)


def test_household_world_profile_is_task_neutral_and_world_only() -> None:
    profile = contract_profile(HOUSEHOLD_WORLD_PROFILE)
    metadata = profile.metadata()
    payload = json.dumps(metadata, sort_keys=True).lower()

    for forbidden in profile.privacy_exclusions:
        assert forbidden not in payload
    assert "scene_objects" not in payload
    assert metadata["backend"] == "multi_backend"
    assert metadata["backend_variants"] == [
        "api_semantic_synthetic",
        "molmospaces_subprocess",
        "agibot_gdk",
    ]
    assert set(metadata["capability_families"]).isdisjoint({"manipulation", "episode"})
    public_names = {tool["name"] for tool in metadata["public_tools"]}
    assert public_names >= {
        "metric_map",
        "observe",
        "adjust_camera",
        "declare_visual_candidates",
        "navigate_to_waypoint",
        "navigate_to_relative_pose",
    }
    assert public_names.isdisjoint(
        {
            "pick",
            "place",
            "place_inside",
            "open_receptacle",
            "close_receptacle",
            "check_operator_messages",
            "done",
        }
    )


def test_household_cleanup_skill_capabilities_are_composed_not_copied() -> None:
    world = contract_profile(HOUSEHOLD_WORLD_PROFILE)
    manipulation = contract_profile(HOUSEHOLD_MANIPULATION_PROFILE)
    lifecycle = contract_profile(HOUSEHOLD_EPISODE_PROFILE)

    assert "metric_map" in world.public_tool_names()
    assert "pick" not in world.public_tool_names()
    assert {"pick", "place", "navigate_to_receptacle"} <= set(manipulation.public_tool_names())
    assert lifecycle.public_tool_names() == ("check_operator_messages", "done")


def test_profile_validation_rejects_privileged_public_tool() -> None:
    profile = ContractProfile(
        profile_id="bad_profile_v1",
        version=1,
        backend="test",
        domain="test",
        capability_families=("navigation",),
        public_tools=(
            ToolDescriptor(
                name="goto",
                semantic_name="navigation.teleport_to_object",
                family="navigation",
                classification="privileged_tool",
                provenance=("simulator_metadata",),
                summary="bad public privileged tool",
            ),
        ),
        privileged_tools=(),
    )

    with pytest.raises(ValueError, match="public tool 'goto' is classified as privileged_tool"):
        validate_contract_profile(profile)


def test_public_profile_safety_rejects_private_terms_in_serialized_metadata() -> None:
    profile = contract_profile(HOUSEHOLD_WORLD_PROFILE)
    unsafe_metadata = profile.metadata() | {"debug": "generated_mess_set"}

    with pytest.raises(ValueError, match="private exclusion terms"):
        assert_public_profile_metadata_safe(unsafe_metadata, profile)


def test_router_registers_only_selected_profile_public_tools() -> None:
    fake_mcp = FakeFastMCP()
    router = MCPProfileRouter(HOUSEHOLD_WORLD_PROFILE, _handlers(HOUSEHOLD_WORLD_PROFILE))

    registered = router.register_tools(fake_mcp)

    assert set(registered) == set(contract_profile(HOUSEHOLD_WORLD_PROFILE).public_tool_names())
    assert set(fake_mcp.tools) == set(registered)
    assert "pick" not in fake_mcp.tools
    assert "done" not in fake_mcp.tools


@pytest.mark.parametrize(
    ("profile_ids", "excluded"),
    (
        ((HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE), {"pick", "place"}),
        (
            (
                HOUSEHOLD_WORLD_PROFILE,
                HOUSEHOLD_MANIPULATION_PROFILE,
                HOUSEHOLD_EPISODE_PROFILE,
            ),
            set(),
        ),
    ),
)
def test_router_composes_ordered_profile_tool_union(
    profile_ids: tuple[str, ...],
    excluded: set[str],
) -> None:
    router = MCPProfileRouter(profile_ids, _composed_handlers(profile_ids))
    expected = tuple(
        name
        for profile_id in profile_ids
        for name in contract_profile(profile_id).public_tool_names()
    )

    assert router.public_tool_names() == expected
    assert excluded.isdisjoint(router.public_tool_names())


def test_router_rejects_duplicate_profiles() -> None:
    with pytest.raises(ValueError, match="duplicate MCP contract profiles: household_world"):
        MCPProfileRouter(
            (HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_WORLD_PROFILE),
            _handlers(HOUSEHOLD_WORLD_PROFILE),
        )


def test_router_rejects_conflicting_tool_descriptors(monkeypatch: pytest.MonkeyPatch) -> None:
    world = contract_profile(HOUSEHOLD_WORLD_PROFILE)
    conflict = replace(
        world,
        profile_id="conflict",
        public_tools=(replace(world.public_tools[0], summary="conflicting summary"),),
    )
    profiles = {world.profile_id: world, conflict.profile_id: conflict}
    monkeypatch.setattr(entrypoint_module, "load_contract_profile", profiles.__getitem__)

    with pytest.raises(ValueError, match="conflicting public tool descriptor 'metric_map'"):
        MCPProfileRouter(
            (world.profile_id, conflict.profile_id),
            {"metric_map": lambda: {"ok": True}},
            allow_extra_handlers=True,
        )


def test_register_profile_tools_helper_registers_selected_public_tools() -> None:
    fake_mcp = FakeFastMCP()

    registered = register_profile_tools(
        fake_mcp,
        profile_id=HOUSEHOLD_EPISODE_PROFILE,
        handlers=_handlers(HOUSEHOLD_EPISODE_PROFILE),
    )

    assert set(registered) == set(contract_profile(HOUSEHOLD_EPISODE_PROFILE).public_tool_names())
    assert set(fake_mcp.tools) == set(registered)


def test_router_rejects_unknown_profile_with_allowed_ids() -> None:
    with pytest.raises(
        ValueError,
        match="allowed profiles: household_world, household_manipulation, household_episode",
    ):
        load_contract_profile("missing_profile")


def test_router_rejects_handlers_not_in_public_profile() -> None:
    handlers = _handlers(HOUSEHOLD_WORLD_PROFILE)
    handlers["pick"] = lambda **_: {"ok": True}

    with pytest.raises(ValueError, match="handlers outside public profile: pick"):
        MCPProfileRouter(HOUSEHOLD_WORLD_PROFILE, handlers)
