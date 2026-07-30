from __future__ import annotations

from types import SimpleNamespace

from roboclaws.household.planner_observed_binding import (
    OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
)


class _BindingContract:
    backend = SimpleNamespace(
        backend="molmospaces_subprocess",
        scene_xml="/tmp/molmospaces-scene.xml",
    )

    def planner_observed_handle_binding(
        self,
        object_id: str,
        target_receptacle_id: str,
        *,
        source_receptacle_id: str = "",
        tools: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
            "ok": True,
            "status": "ok",
            "object_id": object_id,
            "target_receptacle_id": target_receptacle_id,
            "source_receptacle_id": source_receptacle_id,
            "planner_object_id": "pickup/body",
            "planner_target_receptacle_id": "sink/body",
            "tools": list(tools or []),
            "planner_probe_args": {
                "--cleanup-object-id": object_id,
                "--cleanup-target-receptacle-id": target_receptacle_id,
                "--cleanup-source-receptacle-id": source_receptacle_id,
                "--cleanup-tools": ",".join(tools or []),
                "--cleanup-planner-object-id": "pickup/body",
                "--cleanup-planner-target-receptacle-id": "sink/body",
            },
            "blockers": [],
        }
