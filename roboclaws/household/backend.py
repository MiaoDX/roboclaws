from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from roboclaws.core.backend_catalog import SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND
from roboclaws.household.household_backend_port import HouseholdRuntimeEvidence
from roboclaws.household.manipulation_contract import (
    API_SEMANTIC_PROVENANCE,
)
from roboclaws.household.scoring import score_cleanup
from roboclaws.household.semantic_acceptability import (
    annotate_score_with_semantic_acceptability,
)
from roboclaws.household.types import CleanupScenario

HELD_LOCATION_ID = "held_by_agent"
SYNTHETIC_BACKEND = SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND


class ApiSemanticCleanupBackend:
    """Small semantic cleanup backend with MolmoSpaces-shaped object effects."""

    def __init__(self, scenario: CleanupScenario):
        self.scenario = scenario
        self.scenario_source = ""
        self.receptacle_index: dict[str, Any] = {}
        self._locations = scenario.object_locations()
        self._known_objects = {obj.object_id: obj for obj in scenario.objects}
        self._known_receptacles = {item.receptacle_id: item for item in scenario.receptacles}
        self._held_object_id: str | None = None
        self._current_receptacle_id = "floor_01"
        self._heading_deg = 0.0
        self._open_receptacle_ids: set[str] = set()
        self._containment: dict[str, dict[str, str]] = {}
        self.tool_event_counts: Counter[str] = Counter()

    @property
    def held_object_id(self) -> str | None:
        return self._held_object_id

    @property
    def current_receptacle_id(self) -> str:
        return self._current_receptacle_id

    def backend_name(self) -> str:
        return SYNTHETIC_BACKEND

    def supports_visual_snapshots(self) -> bool:
        return False

    def supports_robot_views(self) -> bool:
        return False

    def requested_mess_count(self) -> int | None:
        return None

    def location_relation(self, object_id: str) -> str:
        return str(self._containment.get(object_id, {}).get("location_relation") or "on")

    def scene_index_source(self) -> str:
        return self.scenario_source

    def scene_index_fixture_pose(self, fixture_id: str) -> list[float] | None:
        entry = self.receptacle_index.get(fixture_id)
        if not isinstance(entry, dict):
            return None
        for candidate in (
            (entry.get("support_pose") or {}).get("position"),
            (entry.get("usd_world_bounds") or {}).get("center"),
        ):
            if isinstance(candidate, (list, tuple)) and len(candidate) >= 3:
                try:
                    return [float(candidate[0]), float(candidate[1]), float(candidate[2])]
                except (TypeError, ValueError):
                    pass
        return None

    def planner_scene(self) -> dict[str, Any]:
        return {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": False,
            "scene_xml": "",
            "backend": self.backend_name(),
        }

    def write_snapshot(self, output_path: Path, *, title: str) -> None:
        return None

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "blocked_capability",
            "error_reason": "robot_views_unavailable",
        }

    def runtime_evidence(self) -> HouseholdRuntimeEvidence:
        return {
            "python_executable": "",
            "runtime": {},
            "model_stats": {},
            "scene_xml": "",
            "metadata_object_count": None,
            "scenario_source": "",
            "scene_usd": "",
            "scene_index": None,
            "object_index": {},
            "receptacle_index": {},
            "scene_index_diagnostics": {},
            "scene_binding_diagnostics": {},
            "segmentation": {},
            "scene_load": {},
            "mapping_gaps": [],
            "snapshot_artifacts": [],
            "semantic_pose_state": {},
            "semantic_pose_view_capture": {},
            "robot": None,
            "robot_import": {},
            "requested_generated_mess_count": None,
            "generated_mess_count": None,
            "mess_placement_diagnostics": [],
            "placement_diagnostics": [],
            "scene_index_artifact": {},
        }

    def close(self) -> None:
        return None

    def object_locations(self) -> dict[str, str]:
        return dict(self._locations)

    def observe(self) -> dict[str, Any]:
        self._count("observe")
        return self._ok(
            "observe",
            scenario=self._public_state(),
            current_receptacle_id=self._current_receptacle_id,
            held_object_id=self._held_object_id,
        )

    def planner_task_binding(self, object_id: str, receptacle_id: str) -> dict[str, Any]:
        from roboclaws.household.planner_observed_binding import (
            backend_planner_task_binding,
        )

        obj = self._known_objects.get(object_id)
        receptacle = self._known_receptacles.get(receptacle_id)
        if obj is None or receptacle is None:
            blockers = []
            if obj is None:
                blockers.append(
                    {
                        "code": "planner_binding_object_missing",
                        "message": f"Object {object_id} is not present in backend state.",
                    }
                )
            if receptacle is None:
                blockers.append(
                    {
                        "code": "planner_binding_receptacle_missing",
                        "message": (f"Receptacle {receptacle_id} is not present in backend state."),
                    }
                )
            return {
                "schema": "backend_planner_task_binding_v1",
                "ok": False,
                "status": "blocked_capability",
                "object_id": object_id,
                "target_receptacle_id": receptacle_id,
                "blockers": blockers,
            }
        return backend_planner_task_binding(
            object_id=object_id,
            target_receptacle_id=receptacle_id,
            source_receptacle_id=str(self._locations.get(object_id) or ""),
            pickup_obj_name=obj.object_id,
            place_receptacle_name=receptacle.receptacle_id,
        )

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        self._count("navigate_to_object")
        obj = self._known_objects.get(object_id)
        if obj is None:
            return self._stale_reference("navigate_to_object", object_id=object_id)
        location_id = self._locations.get(object_id)
        if location_id in {None, HELD_LOCATION_ID}:
            return self._error(
                "navigate_to_object",
                "object_not_at_public_location",
                object_id=object_id,
            )
        previous = self._current_receptacle_id
        self._current_receptacle_id = str(location_id)
        return self._ok(
            "navigate_to_object",
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            object_id=object_id,
            source_receptacle_id=str(location_id),
            previous_receptacle_id=previous,
            location_id=str(location_id),
        )

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        self._count("navigate_to_receptacle")
        return self._navigate_to_receptacle("navigate_to_receptacle", receptacle_id)

    def navigate_to_waypoint(self, *, waypoint: dict[str, Any]) -> dict[str, Any]:
        fixture_ids = waypoint.get("fixture_ids") or []
        fixture_id = str(fixture_ids[0]) if fixture_ids else ""
        if not fixture_id:
            return {
                "ok": True,
                "tool": "navigate_to_waypoint",
                "status": "ok",
                "state_mutation": "agent_pose_semantic",
                "backend_pose_mutation_available": False,
            }
        navigation = dict(self.navigate_to_receptacle(receptacle_id=fixture_id))
        navigation["tool"] = "navigate_to_waypoint"
        navigation["waypoint_id"] = str(waypoint.get("waypoint_id") or "")
        navigation["fallback_receptacle_id"] = fixture_id
        navigation["backend_pose_mutation_available"] = True
        return navigation

    def navigate_to_relative_pose(
        self,
        *,
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict[str, Any]:
        self._count("navigate_to_relative_pose")
        previous_heading_deg = self._heading_deg
        self._heading_deg = (self._heading_deg + float(yaw_delta_deg)) % 360.0
        return self._ok(
            "navigate_to_relative_pose",
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            state_mutation="agent_pose_semantic",
            backend_pose_mutation_available=True,
            applied_forward_m=float(forward_m),
            applied_lateral_m=float(lateral_m),
            applied_yaw_delta_deg=float(yaw_delta_deg),
            previous_heading_deg=previous_heading_deg,
            heading_deg=self._heading_deg,
            clamped=False,
        )

    def _navigate_to_receptacle(self, tool: str, receptacle_id: str) -> dict[str, Any]:
        if receptacle_id not in self._known_receptacles:
            return self._stale_reference(tool, receptacle_id=receptacle_id)
        previous = self._current_receptacle_id
        self._current_receptacle_id = receptacle_id
        return self._ok(
            tool,
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            receptacle_id=receptacle_id,
            previous_receptacle_id=previous,
        )

    def pick(self, object_id: str) -> dict[str, Any]:
        self._count("pick")
        obj = self._known_objects.get(object_id)
        if obj is None:
            return self._stale_reference("pick", object_id=object_id)
        if not obj.pickupable:
            return self._error("pick", "not_pickupable", object_id=object_id)
        if self._held_object_id is not None:
            return self._error("pick", "already_holding", held_object_id=self._held_object_id)
        previous_location_id = self._locations[object_id]
        self._held_object_id = object_id
        self._locations[object_id] = HELD_LOCATION_ID
        return self._ok(
            "pick",
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            object_id=object_id,
            previous_location_id=previous_location_id,
            location_id=HELD_LOCATION_ID,
        )

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        self._count("open_receptacle")
        receptacle = self._known_receptacles.get(receptacle_id)
        if receptacle is None:
            return self._stale_reference("open_receptacle", receptacle_id=receptacle_id)
        opened = "fridge" in receptacle.name.lower() or "refrigerator" in receptacle.name.lower()
        if opened:
            self._open_receptacle_ids.add(receptacle_id)
        return self._ok(
            "open_receptacle",
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            receptacle_id=receptacle_id,
            opened=opened,
            state_mutation="semantic_open_state",
        )

    def close_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        self._count("close_receptacle")
        receptacle = self._known_receptacles.get(receptacle_id)
        if receptacle is None:
            return self._stale_reference("close_receptacle", receptacle_id=receptacle_id)
        was_open = receptacle_id in self._open_receptacle_ids
        self._open_receptacle_ids.discard(receptacle_id)
        return self._ok(
            "close_receptacle",
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            receptacle_id=receptacle_id,
            closed=was_open,
            state_mutation="semantic_open_state",
        )

    def place(self, receptacle_id: str) -> dict[str, Any]:
        self._count("place")
        return self._place_at_receptacle("place", receptacle_id, relation="on")

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        self._count("place_inside")
        return self._place_at_receptacle("place_inside", receptacle_id, relation="inside")

    def _place_at_receptacle(
        self,
        tool: str,
        receptacle_id: str,
        *,
        relation: str,
    ) -> dict[str, Any]:
        if receptacle_id not in self._known_receptacles:
            return self._stale_reference(tool, receptacle_id=receptacle_id)
        if self._held_object_id is None:
            return self._error(tool, "not_holding")
        object_id = self._held_object_id
        self._locations[object_id] = receptacle_id
        self._held_object_id = None
        self._current_receptacle_id = receptacle_id
        self._containment[object_id] = {
            "contained_in": receptacle_id if relation == "inside" else "",
            "location_relation": relation,
        }
        diagnostic = _semantic_placement_diagnostic(
            object_id=object_id,
            object_category=self._known_objects[object_id].category,
            receptacle_id=receptacle_id,
            receptacle_category=self._known_receptacles[receptacle_id].category
            or self._known_receptacles[receptacle_id].name,
            relation=relation,
        )
        return self._ok(
            tool,
            primitive_provenance=API_SEMANTIC_PROVENANCE,
            object_id=object_id,
            receptacle_id=receptacle_id,
            location_id=receptacle_id,
            contained_in=receptacle_id if relation == "inside" else None,
            location_relation=relation,
            placement_diagnostic=diagnostic,
        )

    def done(self, reason: str = "") -> dict[str, Any]:
        self._count("done")
        score = score_cleanup(self._locations, self.scenario.private_manifest)
        annotated_score = annotate_score_with_semantic_acceptability(
            score.to_dict(),
            self.scenario,
        )
        return self._ok(
            "done",
            reason=reason,
            cleanup_status=score.status,
            score=annotated_score,
            final_locations=self.object_locations(),
            final_containment=dict(self._containment),
            tool_event_counts=dict(self.tool_event_counts),
        )

    def _public_state(self) -> dict[str, Any]:
        state = self.scenario.public_payload()
        by_id = {obj["object_id"]: obj for obj in state["objects"]}
        for object_id, location_id in self._locations.items():
            by_id[object_id]["location_id"] = location_id
            containment = self._containment.get(object_id)
            if containment is not None:
                by_id[object_id].update(containment)
        return state

    def _count(self, tool: str) -> None:
        self.tool_event_counts[f"{tool}:request"] += 1

    @staticmethod
    def _ok(tool: str, **payload: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": tool,
            "status": "ok",
            **payload,
        }

    @staticmethod
    def _error(tool: str, error_reason: str, **payload: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool,
            "status": "error",
            "error_reason": error_reason,
            **payload,
        }

    def _stale_reference(self, tool: str, **payload: Any) -> dict[str, Any]:
        return self._error(tool, "stale_reference", **payload)


def _semantic_placement_diagnostic(
    *,
    object_id: str,
    object_category: str,
    receptacle_id: str,
    receptacle_category: str,
    relation: str,
) -> dict[str, Any]:
    support_status = (
        "semantic_contained_in_receptacle" if relation == "inside" else "semantic_on_receptacle"
    )
    return {
        "schema": "molmospaces_semantic_placement_diagnostic_v1",
        "status": support_status,
        "object_id": object_id,
        "object_category": object_category,
        "receptacle_id": receptacle_id,
        "receptacle_category": receptacle_category,
        "relation": relation,
        "support_status": support_status,
        "contact_proof": "not_measured_api_semantic",
        "diagnostic_source": "api_semantic_contract_state",
    }
