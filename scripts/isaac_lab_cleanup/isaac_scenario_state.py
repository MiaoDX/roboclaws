from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from roboclaws.household.generated_mess import (
    generated_mess_public_distractor_settlement_plan,
    valid_generated_mess_placement_index,
    valid_generated_mess_relation,
)
from scripts.isaac_lab_cleanup.isaac_placement_resolution import (
    ISAAC_PLACEMENT_RESOLVER_SOURCE,
)


@dataclass(frozen=True)
class IsaacScenarioStateHooks:
    dict_value: Callable[..., dict[str, Any]]
    isaac_placement_diagnostic: Callable[..., dict[str, Any]]
    receptacle_prefers_inside: Callable[..., bool]
    receptacle_requires_open: Callable[..., bool]
    receptacles_by_id: Callable[..., dict[str, dict[str, Any]]]
    resolve_isaac_placement: Callable[..., dict[str, Any]]
    round_vec3: Callable[..., Any]
    vec3: Callable[..., list[float] | None]


def seed_generated_mess_placements(
    state: dict[str, Any],
    *,
    hooks: IsaacScenarioStateHooks,
) -> None:
    targets = [
        hooks.dict_value(item)
        for item in hooks.dict_value(state.get("private_manifest")).get("targets", [])
    ]
    if not targets:
        return
    manifest_targets = manifest_target_by_object_id(state, hooks=hooks)
    target_receptacle_ids = {
        receptacle_id
        for target in targets
        for receptacle_id in target.get("valid_receptacle_ids", [])
        if str(receptacle_id)
    }
    wrong_pool = mess_wrong_receptacle_pool(state, target_receptacle_ids, hooks=hooks)
    if not wrong_pool:
        return
    diagnostics = [
        dict(item) for item in state.get("mess_placement_diagnostics", []) if isinstance(item, dict)
    ]
    raw_objects = state.get("objects")
    objects = list(raw_objects.values()) if isinstance(raw_objects, dict) else []
    receptacles = list(hooks.receptacles_by_id(state).values())
    target_object_ids = {
        str(target.get("object_id") or "")
        for target in targets
        if str(target.get("object_id") or "")
    }
    settlement_plan = generated_mess_public_distractor_settlement_plan(
        objects,
        receptacles,
        excluded_object_ids=target_object_ids,
    )
    for index, settlement in enumerate(settlement_plan):
        object_id = settlement["object_id"]
        receptacle_id = settlement["target_receptacle_id"]
        receptacle = hooks.receptacles_by_id(state)[receptacle_id]
        relation = "inside" if hooks.receptacle_prefers_inside(receptacle) else "on"
        placement_index = len(targets) + index
        placement_resolution = apply_object_location(
            state,
            object_id=object_id,
            receptacle_id=receptacle_id,
            relation=relation,
            placement_index=placement_index,
            source="public_cleanup_background_settlement",
            hooks=hooks,
        )
        diagnostics.append(
            hooks.isaac_placement_diagnostic(
                state=state,
                object_id=object_id,
                receptacle_id=receptacle_id,
                relation=relation,
                source="public_cleanup_background_settlement",
                placement_index=placement_index,
                placement_resolution=placement_resolution,
            )
        )
    for index, target in enumerate(targets):
        object_id = str(target.get("object_id") or "")
        if not object_id:
            continue
        target_ids = {str(item) for item in target.get("valid_receptacle_ids", []) if str(item)}
        manifest_target = manifest_targets.get(object_id)
        wrong = target_start_receptacle(
            state,
            wrong_pool,
            index,
            target_ids,
            manifest_target,
            hooks=hooks,
        )
        receptacle_id = str(wrong.get("receptacle_id") or "")
        if not receptacle_id:
            continue
        relation = target_relation(wrong, manifest_target, hooks=hooks)
        placement_index = target_placement_index(index, manifest_target)
        source = "canonical_mess_manifest" if manifest_target else "mess_seed"
        placement_resolution = apply_object_location(
            state,
            object_id=object_id,
            receptacle_id=receptacle_id,
            relation=relation,
            placement_index=placement_index,
            source=source,
            hooks=hooks,
        )
        diagnostic = hooks.isaac_placement_diagnostic(
            state=state,
            object_id=object_id,
            receptacle_id=receptacle_id,
            relation=relation,
            source=source,
            placement_index=placement_index,
            placement_resolution=placement_resolution,
        )
        diagnostics.append(diagnostic)
    state["mess_placement_diagnostics"] = diagnostics


def manifest_target_by_object_id(
    state: dict[str, Any],
    *,
    hooks: IsaacScenarioStateHooks,
) -> dict[str, dict[str, Any]]:
    manifest = hooks.dict_value(state.get("generated_mess_manifest"))
    targets: dict[str, dict[str, Any]] = {}
    for raw_target in manifest.get("targets", []):
        target = hooks.dict_value(raw_target)
        object_id = str(target.get("object_id") or "")
        if object_id:
            targets[object_id] = target
    return targets


def target_start_receptacle(
    state: dict[str, Any],
    wrong_pool: list[dict[str, Any]],
    index: int,
    target_ids: set[str],
    manifest_target: dict[str, Any] | None,
    *,
    hooks: IsaacScenarioStateHooks,
) -> dict[str, Any]:
    if manifest_target:
        start_receptacle_id = str(manifest_target.get("start_receptacle_id") or "")
        if start_receptacle_id:
            receptacle = hooks.receptacles_by_id(state).get(start_receptacle_id)
            if receptacle is None:
                raise ValueError(
                    "generated mess manifest start receptacle id is unavailable: "
                    f"{manifest_target.get('object_id')} -> {start_receptacle_id}"
                )
            return receptacle
    wrong = wrong_pool[index % len(wrong_pool)]
    if len(wrong_pool) > 1 and str(wrong.get("receptacle_id") or "") in target_ids:
        wrong = wrong_pool[(index + 1) % len(wrong_pool)]
    return wrong


def target_relation(
    receptacle: dict[str, Any],
    manifest_target: dict[str, Any] | None,
    *,
    hooks: IsaacScenarioStateHooks,
) -> str:
    if manifest_target:
        object_id = str(manifest_target.get("object_id") or "")
        return valid_generated_mess_relation(manifest_target, object_id=object_id)
    return "inside" if hooks.receptacle_prefers_inside(receptacle) else "on"


def target_placement_index(index: int, manifest_target: dict[str, Any] | None) -> int:
    if not manifest_target:
        return index
    object_id = str(manifest_target.get("object_id") or "")
    return valid_generated_mess_placement_index(manifest_target, object_id=object_id)


def mess_wrong_receptacle_pool(
    state: dict[str, Any],
    target_receptacle_ids: set[str],
    *,
    hooks: IsaacScenarioStateHooks,
) -> list[dict[str, Any]]:
    receptacles = list(hooks.receptacles_by_id(state).values())
    wrong_pool = [
        item
        for item in receptacles
        if str(item.get("receptacle_id") or "") not in target_receptacle_ids
        and not hooks.receptacle_requires_open(item)
    ]
    if not wrong_pool:
        wrong_pool = [
            item
            for item in receptacles
            if str(item.get("receptacle_id") or "") not in target_receptacle_ids
        ]
    return wrong_pool or receptacles


def apply_object_location(
    state: dict[str, Any],
    *,
    object_id: str,
    receptacle_id: str,
    relation: str,
    placement_index: int,
    source: str,
    hooks: IsaacScenarioStateHooks,
) -> dict[str, Any]:
    resolution = hooks.resolve_isaac_placement(
        state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        index=placement_index,
        relation=relation,
        source=source,
    )
    state.setdefault("locations", {})[object_id] = receptacle_id
    containment = dict(state.get("containment") or {})
    containment[object_id] = {
        "contained_in": receptacle_id if relation == "inside" else "",
        "location_relation": relation,
    }
    state["containment"] = containment
    overrides = dict(state.get("object_pose_overrides") or {})
    position = hooks.vec3(resolution.get("position"))
    if position is not None:
        overrides[object_id] = {
            "position": hooks.round_vec3(position),
            "position_source": ISAAC_PLACEMENT_RESOLVER_SOURCE,
            "support_receptacle_id": receptacle_id,
            "relation": relation,
            "support_status": resolution.get("support_status"),
            "contact_proof": resolution.get("contact_proof"),
            "resolution_source": resolution.get("resolution_source"),
            "source": source,
        }
    else:
        overrides.pop(object_id, None)
    state["object_pose_overrides"] = overrides
    set_public_scenario_object_location(
        state,
        object_id=object_id,
        receptacle_id=receptacle_id,
        relation=relation,
        hooks=hooks,
    )
    return resolution


def set_public_scenario_object_location(
    state: dict[str, Any],
    *,
    object_id: str,
    receptacle_id: str,
    relation: str,
    hooks: IsaacScenarioStateHooks,
) -> None:
    scenario = hooks.dict_value(state.get("scenario"))
    for item in scenario.get("objects", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("object_id") or "") != object_id:
            continue
        item["location_id"] = receptacle_id
        item["contained_in"] = receptacle_id if relation == "inside" else ""
        item["location_relation"] = relation
        break


def first_target_object_location(
    state: dict[str, Any],
    *,
    hooks: IsaacScenarioStateHooks,
) -> str:
    for target in hooks.dict_value(state.get("private_manifest")).get("targets", []):
        object_id = str(hooks.dict_value(target).get("object_id") or "")
        location_id = str(hooks.dict_value(state.get("locations")).get(object_id) or "")
        if location_id:
            return location_id
    return ""
