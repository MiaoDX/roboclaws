from __future__ import annotations

from roboclaws.launch.catalog import resolve_surface_launch
from roboclaws.worlds.molmospaces.sampling import (
    sampler_rows,
)


def test_source_aware_molmospaces_sampler_worlds_are_launchable() -> None:
    for row in sampler_rows():
        if row.scene_index is None:
            continue
        world_id = row.world_id
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
        assert plan.world == world_id
        assert f"scene_source={row.scene_source}" in plan.overrides
