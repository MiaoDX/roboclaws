from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

from roboclaws.household.semantic_acceptability import public_source_requires_cleanup

GENERATED_MESS_MANIFEST_SCHEMA = "roboclaws_generated_mess_manifest_v1"
GENERATED_MESS_MANIFEST_PROVENANCE = "backend_neutral_generated_mess"
GENERATED_MESS_START_SEMANTICS = "public_cleanup_required_v1"

TARGET_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("Cup", "Mug", "Plate", "Bowl"), ("Sink",)),
    (("Book", "Newspaper"), ("ShelvingUnit", "Desk")),
    (("Apple", "Bread", "Egg", "Potato", "Lettuce"), ("Fridge",)),
    (("RemoteControl",), ("TVStand",)),
    (("Pillow", "TeddyBear"), ("Bed", "Sofa")),
)

GeneratedMessRule = tuple[list[dict[str, Any]], dict[str, Any]]


def select_generated_mess_targets(
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    *,
    target_count: int,
    seed: int | None = None,
    object_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Select a diverse hidden Generated Mess Set from public scene metadata."""
    if target_count < 1:
        raise ValueError("target_count must be >= 1")
    if object_ids is not None:
        return select_explicit_generated_mess_targets(
            objects,
            receptacles,
            object_ids=object_ids,
            target_count=target_count,
        )

    eligible_rules = _eligible_generated_mess_rules(
        objects,
        receptacles,
        rng=random.Random(seed) if seed is not None else None,
    )
    return _select_targets_from_rules(eligible_rules, target_count=target_count)


def _eligible_generated_mess_rules(
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    *,
    rng: random.Random | None,
) -> list[GeneratedMessRule]:
    eligible_rules: list[GeneratedMessRule] = []
    for object_categories, receptacle_categories in TARGET_RULES:
        receptacle = first_receptacle_for_categories(receptacles, receptacle_categories)
        if receptacle is None:
            continue
        rule_objects = [item for item in objects if item["category"] in object_categories]
        if rng is not None:
            rule_objects = sorted(rule_objects, key=lambda item: str(item["object_id"]))
            rng.shuffle(rule_objects)
        if rule_objects:
            eligible_rules.append((rule_objects, receptacle))
    return eligible_rules


def _select_targets_from_rules(
    eligible_rules: list[GeneratedMessRule],
    *,
    target_count: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    while len(selected) < target_count:
        selected_count = len(selected)
        _append_round_robin_rule_targets(
            selected,
            used=used,
            eligible_rules=eligible_rules,
            target_count=target_count,
        )
        if len(selected) == selected_count:
            break
    return selected


def _append_round_robin_rule_targets(
    selected: list[dict[str, Any]],
    *,
    used: set[str],
    eligible_rules: list[GeneratedMessRule],
    target_count: int,
) -> None:
    for rule_objects, receptacle in eligible_rules:
        obj = next((item for item in rule_objects if item["object_id"] not in used), None)
        if obj is None:
            continue
        selected_obj = dict(obj)
        selected_obj["target_receptacle_id"] = receptacle["receptacle_id"]
        selected.append(selected_obj)
        used.add(selected_obj["object_id"])
        if len(selected) >= target_count:
            return


def build_generated_mess_manifest(
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    *,
    target_count: int,
    seed: int | None = None,
    object_ids: Sequence[str] | None = None,
    scene_source: str = "",
    scene_index: int | None = None,
    scene_metadata_source: str = "canonical_scene_metadata",
    provenance: str = GENERATED_MESS_MANIFEST_PROVENANCE,
) -> dict[str, Any]:
    """Build a backend-neutral generated-mess run-control manifest."""
    targets = select_generated_mess_targets(
        objects,
        receptacles,
        target_count=target_count,
        seed=seed,
        object_ids=object_ids,
    )
    return generated_mess_manifest_from_targets(
        targets,
        receptacles,
        requested_generated_mess_count=target_count,
        seed=seed,
        scene_source=scene_source,
        scene_index=scene_index,
        scene_metadata_source=scene_metadata_source,
        provenance=provenance,
    )


def generated_mess_manifest_from_targets(
    targets: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    *,
    requested_generated_mess_count: int,
    seed: int | None = None,
    scene_source: str = "",
    scene_index: int | None = None,
    scene_metadata_source: str = "canonical_scene_metadata",
    provenance: str = GENERATED_MESS_MANIFEST_PROVENANCE,
) -> dict[str, Any]:
    target_receptacle_ids = {
        str(target.get("target_receptacle_id") or "")
        for target in targets
        if str(target.get("target_receptacle_id") or "")
    }
    manifest_targets: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        target_receptacle_id = str(target.get("target_receptacle_id") or "")
        start_pool = generated_mess_public_cleanup_start_pool(
            target,
            receptacles,
            excluded_receptacle_ids=target_receptacle_ids,
        )
        start_receptacle = start_pool[index % len(start_pool)]
        start_receptacle_id = str(start_receptacle.get("receptacle_id") or target_receptacle_id)
        relation = "inside" if receptacle_prefers_inside(start_receptacle) else "on"
        manifest_targets.append(
            {
                "object_id": str(target["object_id"]),
                "category": str(target.get("category") or ""),
                "target_receptacle_id": target_receptacle_id,
                "valid_receptacle_ids": [target_receptacle_id],
                "start_receptacle_id": start_receptacle_id,
                "relation": relation,
                "placement_index": index,
            }
        )
    generated_count = len(manifest_targets)
    return {
        "schema": GENERATED_MESS_MANIFEST_SCHEMA,
        "provenance": provenance,
        "scene": {
            "scene_source": scene_source,
            "scene_index": scene_index,
            "scene_metadata_source": scene_metadata_source,
        },
        "selection": {
            "selector": "roboclaws.household.generated_mess.select_generated_mess_targets",
            "seed": seed,
            "requested_generated_mess_count": requested_generated_mess_count,
            "start_semantics": GENERATED_MESS_START_SEMANTICS,
        },
        "requested_generated_mess_count": requested_generated_mess_count,
        "generated_mess_count": generated_count,
        "success_threshold": generated_mess_success_threshold(generated_count)
        if generated_count
        else 0,
        "targets": manifest_targets,
    }


def targets_from_generated_mess_manifest(
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    target_count: int | None = None,
) -> list[dict[str, Any]]:
    """Validate and materialize selected targets from a generated-mess manifest."""
    manifest_targets = _validated_manifest_targets(manifest, target_count=target_count)
    object_by_id = {str(item["object_id"]): item for item in objects}
    receptacle_by_id = {str(item["receptacle_id"]): item for item in receptacles}
    return [
        _materialize_manifest_target(
            raw_target,
            index=index,
            object_by_id=object_by_id,
            receptacle_by_id=receptacle_by_id,
        )
        for index, raw_target in enumerate(manifest_targets)
    ]


def _validated_manifest_targets(
    manifest: dict[str, Any],
    *,
    target_count: int | None,
) -> list[dict[str, Any]]:
    if manifest.get("schema") != GENERATED_MESS_MANIFEST_SCHEMA:
        raise ValueError(
            "generated mess manifest schema mismatch: "
            f"{manifest.get('schema')} != {GENERATED_MESS_MANIFEST_SCHEMA}"
        )
    manifest_targets = [_dict(item) for item in manifest.get("targets", [])]
    if target_count is not None and len(manifest_targets) != int(target_count):
        raise ValueError(
            "generated mess manifest target count must match generated_mess_count "
            f"({len(manifest_targets)} != {target_count})"
        )
    return manifest_targets


def _materialize_manifest_target(
    raw_target: dict[str, Any],
    *,
    index: int,
    object_by_id: dict[str, dict[str, Any]],
    receptacle_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    object_id = str(raw_target.get("object_id") or "")
    if not object_id:
        raise ValueError(f"generated mess manifest target {index} is missing object_id")
    obj = object_by_id.get(object_id)
    if obj is None:
        raise ValueError(f"generated mess manifest object id is unavailable: {object_id}")
    valid_receptacle_ids = _valid_manifest_receptacle_ids(
        raw_target,
        object_id=object_id,
        receptacle_by_id=receptacle_by_id,
    )
    selected_obj = dict(obj)
    selected_obj["target_receptacle_id"] = valid_receptacle_ids[0]
    selected_obj["valid_receptacle_ids"] = valid_receptacle_ids
    selected_obj["start_receptacle_id"] = _valid_manifest_start_receptacle_id(
        raw_target,
        object_id=object_id,
        receptacle_by_id=receptacle_by_id,
    )
    selected_obj["relation"] = valid_generated_mess_relation(raw_target, object_id=object_id)
    selected_obj["placement_index"] = valid_generated_mess_placement_index(
        raw_target,
        object_id=object_id,
    )
    return selected_obj


def _valid_manifest_receptacle_ids(
    raw_target: dict[str, Any],
    *,
    object_id: str,
    receptacle_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    valid_receptacle_ids = [
        str(item)
        for item in (
            raw_target.get("valid_receptacle_ids") or [raw_target.get("target_receptacle_id")]
        )
        if str(item)
    ]
    if not valid_receptacle_ids:
        raise ValueError(f"generated mess manifest target has no valid receptacle ids: {object_id}")
    for receptacle_id in valid_receptacle_ids:
        if receptacle_id not in receptacle_by_id:
            raise ValueError(
                "generated mess manifest target receptacle id is unavailable: "
                f"{object_id} -> {receptacle_id}"
            )
    return valid_receptacle_ids


def _valid_manifest_start_receptacle_id(
    raw_target: dict[str, Any],
    *,
    object_id: str,
    receptacle_by_id: dict[str, dict[str, Any]],
) -> str:
    start_receptacle_id = str(raw_target.get("start_receptacle_id") or "")
    if start_receptacle_id and start_receptacle_id not in receptacle_by_id:
        raise ValueError(
            "generated mess manifest start receptacle id is unavailable: "
            f"{object_id} -> {start_receptacle_id}"
        )
    return start_receptacle_id


def valid_generated_mess_relation(raw_target: dict[str, Any], *, object_id: str) -> str:
    relation = str(raw_target.get("relation") or "")
    if relation not in {"on", "inside"}:
        raise ValueError(
            "generated mess manifest relation must be 'on' or 'inside': "
            f"{object_id} -> {relation or '<missing>'}"
        )
    return relation


def valid_generated_mess_placement_index(raw_target: dict[str, Any], *, object_id: str) -> int:
    placement_index = raw_target.get("placement_index")
    if isinstance(placement_index, bool) or not isinstance(placement_index, int):
        raise ValueError(
            "generated mess manifest placement_index must be an integer: "
            f"{object_id} -> {placement_index!r}"
        )
    return placement_index


def generated_mess_manifest_object_ids(manifest: dict[str, Any]) -> list[str]:
    return [
        str(_dict(target).get("object_id") or "")
        for target in manifest.get("targets", [])
        if str(_dict(target).get("object_id") or "")
    ]


def generated_mess_public_cleanup_start_pool(
    target: dict[str, Any],
    receptacles: list[dict[str, Any]],
    *,
    excluded_receptacle_ids: set[str],
) -> list[dict[str, Any]]:
    object_category = str(target.get("category") or "")
    candidates = [
        item
        for item in receptacles
        if str(item.get("receptacle_id") or "") not in excluded_receptacle_ids
        and public_source_requires_cleanup(
            object_category,
            item.get("category") or item.get("name") or item.get("kind"),
        )
    ]
    preferred = [item for item in candidates if not receptacle_requires_open(item)]
    if preferred:
        return preferred
    if candidates:
        return candidates
    object_id = str(target.get("object_id") or "<unknown>")
    raise ValueError(
        "generated mess target has no public cleanup-required start receptacle: "
        f"{object_id} ({object_category or '<unknown>'})"
    )


def receptacle_requires_open(receptacle: dict[str, Any]) -> bool:
    text = receptacle_text(receptacle)
    return "fridge" in text or "refrigerator" in text


def receptacle_prefers_inside(receptacle: dict[str, Any]) -> bool:
    return receptacle_requires_open(receptacle) or receptacle_is_open_container(receptacle)


def receptacle_is_open_container(receptacle: dict[str, Any]) -> bool:
    text = receptacle_text(receptacle)
    return any(term in text for term in ("shelvingunit", "bookshelf", "bookcase", "shelf"))


def receptacle_text(receptacle: dict[str, Any]) -> str:
    parts = (
        receptacle.get("receptacle_id", ""),
        receptacle.get("name", ""),
        receptacle.get("category", ""),
        receptacle.get("kind", ""),
    )
    return " ".join(str(part) for part in parts).lower()


def select_explicit_generated_mess_targets(
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    *,
    object_ids: Sequence[str],
    target_count: int,
) -> list[dict[str, Any]]:
    """Select an exact hidden Generated Mess Set by object id."""
    requested_ids = tuple(str(object_id) for object_id in object_ids if str(object_id))
    if len(requested_ids) != target_count:
        raise ValueError(
            "explicit generated mess object id count must match target_count "
            f"({len(requested_ids)} != {target_count})"
        )
    object_by_id = {str(item["object_id"]): item for item in objects}
    selected: list[dict[str, Any]] = []
    for object_id in requested_ids:
        obj = object_by_id.get(object_id)
        if obj is None:
            raise ValueError(f"explicit generated mess object id is unavailable: {object_id}")
        receptacle = target_receptacle_for_object(obj, receptacles)
        if receptacle is None:
            category = str(obj.get("category") or "")
            raise ValueError(
                "explicit generated mess object id has no cleanup target receptacle: "
                f"{object_id} ({category})"
            )
        selected_obj = dict(obj)
        selected_obj["target_receptacle_id"] = receptacle["receptacle_id"]
        selected.append(selected_obj)
    return selected


def target_receptacle_for_object(
    obj: dict[str, Any],
    receptacles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    category = str(obj.get("category") or "")
    for object_categories, receptacle_categories in TARGET_RULES:
        if category not in object_categories:
            continue
        return first_receptacle_for_categories(receptacles, receptacle_categories)
    return None


def first_receptacle_for_categories(
    receptacles: list[dict[str, Any]],
    categories: tuple[str, ...],
) -> dict[str, Any] | None:
    for category in categories:
        for receptacle in receptacles:
            if receptacle["category"] == category:
                return receptacle
    return None


def generated_mess_success_threshold(target_count: int) -> int:
    return max(1, math.ceil(target_count * 0.70))


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
