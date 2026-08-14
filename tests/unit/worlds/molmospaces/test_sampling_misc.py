from __future__ import annotations

import pytest

from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS, world_spec


def test_legacy_molmospaces_world_id_is_rejected_with_replacement() -> None:
    with pytest.raises(LaunchError, match="molmospaces/procthor-10k-val/0"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/val_0",
                "backend=mujoco",
                "preset=map-build",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
            ]
        )


def test_source_aware_candidate_worlds_are_launchable_but_not_default_visible() -> None:
    world_id = "molmospaces/ithor/1"

    spec = world_spec(world_id)
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            f"world={world_id}",
            "backend=mujoco",
            "preset=map-build",
            "agent_engine=direct-runner",
            "evidence_lane=world-public-labels",
        ]
    )

    assert world_id not in WORLD_SPECS
    assert world_id not in MOLMOSPACES_CONSOLE_WORLD_IDS
    assert spec.availability == "hidden"
    assert spec.sampler_metadata["selected_reason"] == "dynamic_source_aware_scanner_candidate"
    assert plan.world == world_id
    assert plan.adapter_options["scene_source"] == "ithor"
    assert plan.adapter_options["scene_index"] == "1"
    assert plan.adapter_options["map_bundle"] == "assets/maps/molmospaces/ithor/1"


def test_household_molmospaces_launch_rejects_disabled_map_bundle() -> None:
    with pytest.raises(LaunchError, match="cannot use map_bundle"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/ithor/1",
                "backend=mujoco",
                "preset=map-build",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
                "map_bundle=none",
            ]
        )
