from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from roboclaws.household.manipulation_contract import (
    BLOCKED_CAPABILITY_PROVENANCE,
    PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
)
from roboclaws.household.semantic_timeline import canonical_cleanup_tool_sequence

OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA = "observed_handle_planner_binding_v1"
BACKEND_PLANNER_TASK_BINDING_SCHEMA = "backend_planner_task_binding_v1"
DEFAULT_CLEANUP_BINDING_TOOLS = (
    "navigate_to_object",
    "pick",
    "navigate_to_receptacle",
    "open_receptacle",
    "place",
    "place_inside",
    "close_receptacle",
)


def observed_handle_planner_binding(
    contract: Any,
    *,
    object_id: str,
    target_receptacle_id: str,
    source_receptacle_id: str = "",
    tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    observed_handle = str(object_id or "")
    target_id = str(target_receptacle_id or "")
    normalized_tools = _normalize_tools(tools or DEFAULT_CLEANUP_BINDING_TOOLS)
    blockers = []
    internal_object_id = _internal_object_id(contract, observed_handle)
    if not internal_object_id:
        blockers.append(
            {
                "code": "observed_handle_not_registered",
                "message": (
                    f"Observed handle {observed_handle} is not registered; observe the object "
                    "before building planner binding."
                ),
            }
        )
    backend_binding: dict[str, Any] = {}
    if internal_object_id:
        backend_binding = dict(contract.backend_planner_task_binding(internal_object_id, target_id))
        if backend_binding.get("ok") is not True:
            blockers.extend(_backend_blockers(backend_binding))
    source_id = (
        str(source_receptacle_id or "")
        or str(backend_binding.get("source_receptacle_id") or "")
        or contract.backend_current_location(internal_object_id or "")
    )
    planner_object_id = str(backend_binding.get("pickup_obj_name") or internal_object_id or "")
    planner_target_id = str(backend_binding.get("place_receptacle_name") or target_id)
    requested = {
        "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
        "requested": True,
        "object_id": observed_handle,
        "target_receptacle_id": target_id,
        "source_receptacle_id": source_id,
        "tools": normalized_tools,
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_id,
    }
    status = "ok" if not blockers else BLOCKED_CAPABILITY_PROVENANCE
    return {
        "schema": OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
        "ok": not blockers,
        "status": status,
        "object_id": observed_handle,
        "target_receptacle_id": target_id,
        "source_receptacle_id": source_id,
        "internal_object_id": internal_object_id or "",
        "internal_target_receptacle_id": target_id,
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_id,
        "candidate_pickup_names": list(backend_binding.get("candidate_pickup_names") or []),
        "candidate_place_receptacle_names": list(
            backend_binding.get("candidate_place_receptacle_names") or []
        ),
        "tools": normalized_tools,
        "requested_cleanup_primitive_binding": requested,
        "planner_probe_args": _planner_probe_args(requested),
        "backend_planner_task_binding": backend_binding,
        "agent_view_exposed": False,
        "blockers": blockers,
        "evidence_note": (
            "Private binding between ADR-0003 observed handle cleanup IDs and "
            "planner-facing sampled task names."
        ),
    }


def backend_planner_task_binding(
    *,
    object_id: str,
    target_receptacle_id: str,
    source_receptacle_id: str = "",
    pickup_obj_name: str = "",
    place_receptacle_name: str = "",
    upstream_object_id: str = "",
    upstream_receptacle_id: str = "",
) -> dict[str, Any]:
    pickup_names = _unique_nonempty(
        pickup_obj_name,
        upstream_object_id,
        object_id,
    )
    place_names = _unique_nonempty(
        place_receptacle_name,
        upstream_receptacle_id,
        target_receptacle_id,
    )
    return {
        "schema": BACKEND_PLANNER_TASK_BINDING_SCHEMA,
        "ok": True,
        "status": "ok",
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "source_receptacle_id": source_receptacle_id,
        "pickup_obj_name": pickup_names[0] if pickup_names else object_id,
        "place_receptacle_name": place_names[0] if place_names else target_receptacle_id,
        "candidate_pickup_names": pickup_names,
        "candidate_place_receptacle_names": place_names,
    }


def backend_planner_task_binding_from_state(
    state: Mapping[str, Any],
    *,
    object_id: str,
    target_receptacle_id: str,
) -> dict[str, Any]:
    objects = state.get("objects") if isinstance(state.get("objects"), Mapping) else {}
    receptacles = state.get("receptacles") if isinstance(state.get("receptacles"), Mapping) else {}
    obj = objects.get(object_id) if isinstance(objects, Mapping) else None
    receptacle = receptacles.get(target_receptacle_id) if isinstance(receptacles, Mapping) else None
    blockers = []
    if not isinstance(obj, Mapping):
        blockers.append(
            {
                "code": "planner_binding_object_missing",
                "message": f"Object {object_id} is not present in backend state.",
            }
        )
    if not isinstance(receptacle, Mapping):
        blockers.append(
            {
                "code": "planner_binding_receptacle_missing",
                "message": f"Receptacle {target_receptacle_id} is not present in backend state.",
            }
        )
    if blockers:
        return {
            "schema": BACKEND_PLANNER_TASK_BINDING_SCHEMA,
            "ok": False,
            "status": BLOCKED_CAPABILITY_PROVENANCE,
            "object_id": object_id,
            "target_receptacle_id": target_receptacle_id,
            "blockers": blockers,
        }
    locations = (
        state.get("object_locations") if isinstance(state.get("object_locations"), Mapping) else {}
    )
    return backend_planner_task_binding(
        object_id=object_id,
        target_receptacle_id=target_receptacle_id,
        source_receptacle_id=str(locations.get(object_id) or ""),
        pickup_obj_name=str(obj.get("body_name") or ""),
        place_receptacle_name=str(receptacle.get("body_name") or ""),
        upstream_object_id=str(obj.get("upstream_object_id") or ""),
        upstream_receptacle_id=str(receptacle.get("upstream_object_id") or ""),
    )


def _internal_object_id(contract: Any, observed_handle: str) -> str | None:
    resolver = getattr(contract, "_internal_object_id", None)
    if callable(resolver):
        return resolver(observed_handle)
    return observed_handle or None


def _planner_probe_args(requested: Mapping[str, Any]) -> dict[str, str]:
    args = {
        "--cleanup-object-id": str(requested.get("object_id") or ""),
        "--cleanup-target-receptacle-id": str(requested.get("target_receptacle_id") or ""),
        "--cleanup-source-receptacle-id": str(requested.get("source_receptacle_id") or ""),
        "--cleanup-tools": ",".join(str(item) for item in requested.get("tools") or []),
        "--cleanup-planner-object-id": str(requested.get("planner_object_id") or ""),
        "--cleanup-planner-target-receptacle-id": str(
            requested.get("planner_target_receptacle_id") or ""
        ),
    }
    return {key: value for key, value in args.items() if value}


def _backend_blockers(binding: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = binding.get("blockers") or []
    blockers = [dict(item) for item in raw if isinstance(item, Mapping)]
    if blockers:
        return blockers
    return [
        {
            "code": "planner_binding_backend_blocked",
            "message": "Backend could not build planner task binding.",
        }
    ]


def _normalize_tools(tools: Sequence[str]) -> list[str]:
    return canonical_cleanup_tool_sequence(tools)


def _unique_nonempty(*values: str) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
