from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import mujoco

from roboclaws.household.generated_mess import (
    generated_mess_public_cleanup_start_pool,
    valid_generated_mess_placement_index,
    valid_generated_mess_relation,
)

HELD_LOCATION_ID = "held_by_agent"


@dataclass(frozen=True)
class MolmoScenarioHooks:
    primary_body_name: Callable[..., str]
    friendly_name: Callable[..., str]
    xyz: Callable[..., list[float]]
    receptacle_support_surfaces: Callable[..., list[dict[str, Any]]]
    support_top_z: Callable[..., float | None]
    receptacle_requires_open: Callable[..., bool]
    receptacle_prefers_inside: Callable[..., bool]
    resolve_placement: Callable[..., dict[str, Any]]
    set_free_body_position: Callable[..., None]
    refresh_object_positions: Callable[..., None]
    placement_diagnostic: Callable[..., dict[str, Any]]
    load_model_data_for_state: Callable[..., tuple[mujoco.MjModel, mujoco.MjData]]
    apply_qpos: Callable[..., None]


def collect_dynamic_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    metadata: dict[str, Any],
    *,
    hooks: MolmoScenarioHooks,
) -> list[dict[str, Any]]:
    items = []
    for name, info in metadata.get("objects", {}).items():
        body_name = hooks.primary_body_name(info, fallback=name)
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
        if body_id < 0 or int(model.body_jntnum[body_id]) == 0:
            continue
        joint_id = int(model.body_jntadr[body_id])
        if int(model.jnt_type[joint_id]) != int(mujoco.mjtJoint.mjJNT_FREE):
            continue
        category = str(info.get("category", "Object"))
        items.append(
            {
                "object_id": name,
                "name": hooks.friendly_name(category, info.get("object_id", name)),
                "category": category,
                "location_id": "",
                "pickupable": True,
                "body_name": body_name,
                "upstream_object_id": info.get("object_id", name),
                "position": hooks.xyz(data.xpos[body_id]),
            }
        )
    return sorted(items, key=lambda item: (item["category"], item["object_id"]))


def collect_receptacles(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    metadata: dict[str, Any],
    *,
    hooks: MolmoScenarioHooks,
) -> list[dict[str, Any]]:
    wanted = {
        "Sink",
        "ShelvingUnit",
        "Desk",
        "Fridge",
        "TVStand",
        "Bed",
        "Sofa",
        "DiningTable",
        "CounterTop",
    }
    items = []
    for name, info in metadata.get("objects", {}).items():
        category = str(info.get("category", ""))
        if category not in wanted:
            continue
        body_name = hooks.primary_body_name(info, fallback=name)
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
        if body_id < 0:
            continue
        support_surfaces = hooks.receptacle_support_surfaces(model, data, body_name)
        items.append(
            {
                "receptacle_id": name,
                "name": hooks.friendly_name(category, info.get("object_id", name)),
                "category": category,
                "room_area": f"room_{info.get('room_id', 'unknown')}",
                "kind": "receptacle",
                "body_name": body_name,
                "upstream_object_id": info.get("object_id", name),
                "position": hooks.xyz(data.xpos[body_id]),
                "support_surfaces": support_surfaces,
                "support_top_z": hooks.support_top_z(support_surfaces),
            }
        )
    return sorted(items, key=lambda item: (item["category"], item["receptacle_id"]))


def seed_misplaced_objects(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    state: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    hooks: MolmoScenarioHooks,
) -> None:
    manifest_targets = manifest_target_by_object_id(state)
    target_receptacle_ids = {
        target_receptacle_id(target, manifest_targets.get(str(target["object_id"])))
        for target in targets
    }
    for index, target in enumerate(targets):
        manifest_target = manifest_targets.get(str(target["object_id"]))
        target_id = target_receptacle_id(target, manifest_target)
        placement_index = target_placement_index(index, manifest_target)
        start_pool = (
            list(state["receptacles"].values())
            if manifest_target
            else generated_mess_public_cleanup_start_pool(
                target,
                list(state["receptacles"].values()),
                excluded_receptacle_ids=target_receptacle_ids,
            )
        )
        wrong = target_start_receptacle(state, target, start_pool, index, manifest_target)
        state["objects"][target["object_id"]]["target_receptacle_id"] = target_id
        state["objects"][target["object_id"]]["seeded_start_receptacle_id"] = wrong["receptacle_id"]
        relation = target_relation(wrong, manifest_target, hooks=hooks)
        state["objects"][target["object_id"]]["contained_in"] = (
            wrong["receptacle_id"] if relation == "inside" else None
        )
        state["objects"][target["object_id"]]["location_relation"] = relation
        placement_resolution = hooks.resolve_placement(
            model,
            data,
            state=state,
            object_id=target["object_id"],
            receptacle_id=wrong["receptacle_id"],
            index=placement_index,
            relation=relation,
        )
        placement_position = placement_resolution["position"]
        hooks.set_free_body_position(
            model,
            data,
            target["body_name"],
            placement_position,
        )
        mujoco.mj_forward(model, data)
        hooks.refresh_object_positions(model, data, state)
        diagnostic = hooks.placement_diagnostic(
            state=state,
            object_id=target["object_id"],
            receptacle_id=wrong["receptacle_id"],
            relation=relation,
            requested_position=placement_position,
            source="canonical_mess_manifest" if manifest_target else "mess_seed",
            placement_index=placement_index,
            placement_resolution=placement_resolution,
        )
        state.setdefault("mess_placement_diagnostics", []).append(diagnostic)
    mujoco.mj_forward(model, data)


def manifest_target_by_object_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = state.get("generated_mess_manifest")
    if not isinstance(manifest, dict):
        return {}
    targets: dict[str, dict[str, Any]] = {}
    for raw_target in manifest.get("targets", []):
        if not isinstance(raw_target, dict):
            continue
        object_id = str(raw_target.get("object_id") or "")
        if object_id:
            targets[object_id] = dict(raw_target)
    return targets


def target_receptacle_id(
    target: dict[str, Any],
    manifest_target: dict[str, Any] | None,
) -> str:
    if manifest_target:
        valid_ids = [
            str(item)
            for item in (
                manifest_target.get("valid_receptacle_ids")
                or [manifest_target.get("target_receptacle_id")]
            )
            if str(item)
        ]
        if valid_ids:
            return valid_ids[0]
    return str(target["target_receptacle_id"])


def target_start_receptacle(
    state: dict[str, Any],
    target: dict[str, Any],
    wrong_pool: list[dict[str, Any]],
    index: int,
    manifest_target: dict[str, Any] | None,
) -> dict[str, Any]:
    if manifest_target:
        start_receptacle_id = str(manifest_target.get("start_receptacle_id") or "")
        if start_receptacle_id:
            receptacle = state["receptacles"].get(start_receptacle_id)
            if receptacle is None:
                raise ValueError(
                    "generated mess manifest start receptacle id is unavailable: "
                    f"{target['object_id']} -> {start_receptacle_id}"
                )
            return receptacle
    wrong = wrong_pool[index % len(wrong_pool)]
    if wrong["receptacle_id"] == target["target_receptacle_id"]:
        wrong = wrong_pool[(index + 1) % len(wrong_pool)]
    return wrong


def target_start_receptacle_id(state: dict[str, Any], target: dict[str, Any]) -> str:
    manifest_target = manifest_target_by_object_id(state).get(str(target["object_id"]))
    if manifest_target:
        start_receptacle_id = str(manifest_target.get("start_receptacle_id") or "")
        if start_receptacle_id:
            return start_receptacle_id
    seeded_start_receptacle_id = str(
        (state.get("objects", {}).get(str(target.get("object_id") or ""), {}) or {}).get(
            "seeded_start_receptacle_id"
        )
        or ""
    )
    if seeded_start_receptacle_id:
        return seeded_start_receptacle_id
    return first_wrong_receptacle(state, target)


def target_relation(
    receptacle: dict[str, Any],
    manifest_target: dict[str, Any] | None,
    *,
    hooks: MolmoScenarioHooks,
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


def public_scenario(
    state: dict[str, Any],
    *,
    read_locations: Callable[[dict[str, Any]], dict[str, str]],
    backend: str,
) -> dict[str, Any]:
    locations = read_locations(state)
    selected_ids = set(state["selected_object_ids"])
    selected = []
    distractors = []
    for obj in state["objects"].values():
        public = {
            "object_id": obj["object_id"],
            "name": obj["name"],
            "category": obj["category"],
            "location_id": locations.get(obj["object_id"], ""),
            "pickupable": obj.get("pickupable", True),
            "upstream_object_id": obj.get("upstream_object_id"),
            "contained_in": obj.get("contained_in"),
            "location_relation": obj.get("location_relation", "on"),
        }
        if obj["object_id"] in selected_ids:
            selected.append(public)
        elif obj["category"] not in {"Cup", "Mug", "Plate", "Bowl", "Book", "Apple"}:
            distractors.append(public)
    objects = selected + distractors[:8]
    return {
        "scenario_id": state["private_manifest"]["scenario_id"]
        if "private_manifest" in state
        else f"molmospaces-procthor-val-{state['scene_index']}-{state['seed']}",
        "task": "Clean up this real MolmoSpaces room by putting misplaced objects away.",
        "seed": state["seed"],
        "backend": backend,
        "scene_source": state["scene_source"],
        "scene_index": state["scene_index"],
        "scene_xml": state["scene_xml"],
        "inventory_source": "molmospaces_metadata+mujoco_state",
        "metadata_object_count": state["metadata_object_count"],
        "objects": objects,
        "receptacles": [
            {
                "receptacle_id": item["receptacle_id"],
                "name": item["name"],
                "category": item["category"],
                "room_area": item["room_area"],
                "kind": item["kind"],
                "upstream_object_id": item["upstream_object_id"],
            }
            for item in state["receptacles"].values()
        ],
    }


def read_locations(
    state: dict[str, Any],
    *,
    hooks: MolmoScenarioHooks,
) -> dict[str, str]:
    model, data = hooks.load_model_data_for_state(state)
    hooks.apply_qpos(data, state["qpos"])
    mujoco.mj_forward(model, data)
    receptacles = list(state["receptacles"].values())
    locations = {}
    for object_id, obj in state["objects"].items():
        if not bool(obj.get("pickupable", True)):
            continue
        if object_id == state.get("held_object_id"):
            locations[object_id] = HELD_LOCATION_ID
            continue
        if obj.get("contained_in"):
            locations[object_id] = str(obj["contained_in"])
            continue
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, obj["body_name"])
        if body_id < 0:
            continue
        locations[object_id] = nearest_receptacle(hooks.xyz(data.xpos[body_id]), receptacles)
    return locations


def read_containment(state: dict[str, Any]) -> dict[str, dict[str, str]]:
    containment = {}
    for object_id, obj in state.get("objects", {}).items():
        if not bool(obj.get("pickupable", True)):
            continue
        if obj.get("contained_in") or obj.get("location_relation"):
            containment[object_id] = {
                "contained_in": obj.get("contained_in"),
                "location_relation": obj.get("location_relation", "on"),
            }
    return containment


def score(final_locations: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    restored = []
    missed = []
    object_results = []
    for target in manifest["targets"]:
        object_id = target["object_id"]
        actual = final_locations.get(object_id)
        is_restored = actual in set(target["valid_receptacle_ids"])
        if is_restored:
            restored.append(object_id)
        else:
            missed.append(object_id)
        object_results.append(
            {
                "object_id": object_id,
                "actual_location_id": actual,
                "restored": is_restored,
            }
        )
    status = (
        "success"
        if not manifest["targets"] or len(restored) >= manifest["success_threshold"]
        else "failed"
    )
    if status == "failed" and restored:
        status = "partial_success"
    return {
        "status": status,
        "restored_count": len(restored),
        "total_targets": len(manifest["targets"]),
        "success_threshold": manifest["success_threshold"],
        "restored_object_ids": restored,
        "missed_object_ids": missed,
        "object_results": object_results,
    }


def nearest_receptacle(position: list[float], receptacles: list[dict[str, Any]]) -> str:
    return min(
        receptacles,
        key=lambda item: math.dist(position[:2], item["position"][:2]),
    )["receptacle_id"]


def first_wrong_receptacle(state: dict[str, Any], target: dict[str, Any]) -> str:
    for receptacle_id in state["receptacles"]:
        if receptacle_id != target["target_receptacle_id"]:
            return receptacle_id
    return target["target_receptacle_id"]


def first_receptacle_id(state: dict[str, Any]) -> str | None:
    first = next(iter(state["receptacles"].values()), None)
    if first is None:
        return None
    return str(first["receptacle_id"])
