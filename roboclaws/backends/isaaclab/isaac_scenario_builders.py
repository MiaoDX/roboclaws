"""Isaac Lab backend runtime support."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab.isaac_scene_bindings import _scene_match_tokens
from roboclaws.core.generated_mess import generated_mess_success_threshold
from roboclaws.core.json_sources import read_json_object
from roboclaws.household.generated_mess import (
    GENERATED_MESS_MANIFEST_SCHEMA,
    select_generated_mess_targets,
    targets_from_generated_mess_manifest,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
    TargetRule,
)

MOLMOSPACES_CLEANUP_RECEPTACLE_CATEGORY_NORMS = {
    "sink",
    "shelvingunit",
    "desk",
    "fridge",
    "tvstand",
    "bed",
    "sofa",
    "diningtable",
    "countertop",
}

SCENE_CLEANUP_TARGET_ALIASES = (
    (
        ("dish", "cup", "mug", "plate", "bowl", "utensil", "fork", "knife", "spoon"),
        ("sink", "countertop"),
    ),
    (
        ("book", "newspaper", "notebook", "paper", "magazine"),
        ("shelvingunit", "bookshelf", "shelf", "desk"),
    ),
    (
        ("food", "apple", "bread", "egg", "potato", "lettuce", "tomato", "banana", "orange"),
        ("fridge", "refrigerator"),
    ),
    (
        ("remotecontrol", "remote", "phone", "cellphone", "laptop", "tablet", "alarmclock"),
        ("tvstand", "televisionstand"),
    ),
    (("pillow", "teddybear", "cushion"), ("bed", "sofa")),
    (("linen", "towel", "cloth", "blanket", "shirt", "clothing"), ("laundryhamper", "hamper")),
    (("toy", "toycar", "ball", "basketball", "soccer"), ("toybin",)),
)

SCENE_STRICT_CLEANUP_TARGET_ALIASES = (
    (("cup", "mug", "plate", "bowl"), ("sink",)),
    (("book", "newspaper"), ("shelvingunit", "desk")),
    (("apple", "bread", "egg", "potato", "lettuce"), ("fridge", "refrigerator")),
    (("remotecontrol",), ("tvstand", "televisionstand")),
    (("pillow", "teddybear"), ("bed", "sofa")),
)

CANONICAL_CLEANUP_CATEGORY_ALIASES = (
    ("Plate", ("dish", "plate", "bowl", "cup", "mug", "utensil", "fork", "knife", "spoon")),
    ("Book", ("book", "newspaper", "notebook", "paper", "magazine")),
    (
        "Potato",
        ("food", "apple", "bread", "egg", "potato", "lettuce", "tomato", "banana", "orange"),
    ),
    (
        "RemoteControl",
        ("remotecontrol", "remote", "phone", "cellphone", "laptop", "tablet", "alarmclock"),
    ),
    ("TeddyBear", ("teddybear", "teddy", "plush")),
    ("Pillow", ("pillow", "cushion")),
    ("Towel", ("linen", "towel", "cloth", "blanket", "shirt", "clothing")),
    ("ToyCar", ("toy", "toycar", "ball", "basketball", "soccer")),
)


def scenario_from_state(state: dict[str, Any]) -> CleanupScenario:
    private = PrivateScoringManifest.from_dict(state["private_manifest"])
    public = state["scenario"]
    objects = tuple(
        CleanupObject(
            object_id=str(item["object_id"]),
            name=str(item["name"]),
            category=str(item["category"]),
            location_id=str(item["location_id"]),
            pickupable=bool(item.get("pickupable", True)),
        )
        for item in public.get("objects", [])
    )
    receptacles = tuple(
        CleanupReceptacle(
            receptacle_id=str(item["receptacle_id"]),
            name=str(item["name"]),
            room_area=str(item.get("room_area") or "unknown"),
            kind=str(item.get("kind") or "receptacle"),
            category=str(item["category"]) if item.get("category") is not None else None,
        )
        for item in public.get("receptacles", [])
    )
    return CleanupScenario(
        scenario_id=str(public["scenario_id"]),
        task=str(public["task"]),
        seed=int(public["seed"]),
        objects=objects,
        receptacles=receptacles,
        private_manifest=private,
    )


def load_generated_mess_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    manifest = read_json_object(path, label="generated mess manifest")
    if manifest.get("schema") != GENERATED_MESS_MANIFEST_SCHEMA:
        raise ValueError(
            "generated mess manifest schema mismatch: "
            f"{manifest.get('schema')} != {GENERATED_MESS_MANIFEST_SCHEMA}"
        )
    return manifest


def scenario_for_init(
    args: argparse.Namespace,
    *,
    generated_mess_manifest: dict[str, Any] | None = None,
) -> CleanupScenario:
    if args.scene_usd_path is not None:
        generated_mess_manifest = None
    if args.map_bundle_dir is None:
        return scenario_from_generated_mess_manifest_or_limit(
            build_cleanup_scenario(seed=args.seed),
            generated_mess_count=args.generated_mess_count,
            generated_mess_manifest=generated_mess_manifest,
        )
    return scenario_from_generated_mess_manifest_or_limit(
        scenario_from_map_bundle(
            args.map_bundle_dir,
            seed=args.seed,
            generated_mess_count=args.generated_mess_count,
        ),
        generated_mess_count=args.generated_mess_count,
        generated_mess_manifest=generated_mess_manifest,
    )


def scenario_source(args: argparse.Namespace) -> str:
    return "nav2_map_bundle" if args.map_bundle_dir is not None else "default_cleanup_scenario"


def effective_scene_index(args: argparse.Namespace) -> int:
    scene_usd_path = getattr(args, "scene_usd_path", None)
    inferred = scene_index_from_usd_path(scene_usd_path)
    if inferred is not None:
        return inferred
    return int(getattr(args, "scene_index", 0) or 0)


def scene_index_from_usd_path(path: Any) -> int | None:
    if path is None:
        return None
    for part in reversed(Path(path).parts):
        match = re.search(r"(?:^|_)val_?(\d+)(?:_|$)", part)
        if match:
            return int(match.group(1))
    return None


def scene_specific_scenario_if_needed(
    *,
    args: argparse.Namespace,
    generated_mess_manifest: dict[str, Any] | None,
    scene_binding_diagnostics: dict[str, Any],
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
    real_smoke: dict[str, Any] | None,
) -> CleanupScenario | None:
    if real_smoke is None or args.scene_usd_path is None:
        return None
    if not generated_mess_manifest and scene_binding_diagnostics.get("status") == "selected_bound":
        return None
    return scenario_from_scene_index(
        scene_source=args.scene_source,
        scene_index=args.scene_index,
        seed=args.seed,
        generated_mess_count=args.generated_mess_count,
        generated_mess_object_ids=tuple(getattr(args, "generated_mess_object_id", None) or ()),
        generated_mess_manifest=generated_mess_manifest,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )


def scenario_from_scene_index(
    *,
    scene_source: str,
    scene_index: int,
    seed: int,
    generated_mess_count: int,
    generated_mess_object_ids: tuple[str, ...] = (),
    generated_mess_manifest: dict[str, Any] | None = None,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
) -> CleanupScenario | None:
    cleanup_receptacle_index = cleanup_receptacle_index_for_mess_generation(receptacle_index)
    receptacles = tuple(
        cleanup_receptacle_from_scene_index(handle, entry)
        for handle, entry in sorted(cleanup_receptacle_index.items())
    )
    if not receptacles:
        return None

    selectable_objects: list[dict[str, Any]] = []
    for handle, entry in sorted(object_index.items()):
        target_id = scene_target_receptacle_id(entry, cleanup_receptacle_index)
        if not target_id:
            continue
        source_id = scene_source_receptacle_id(
            entry,
            cleanup_receptacle_index,
            target_id=target_id,
        )
        selectable_objects.append(
            {
                "object_id": handle,
                "name": scene_object_name(handle, entry),
                "category": scene_cleanup_object_category(entry),
                "location_id": source_id,
            }
        )

    receptacle_payloads = [receptacle.to_public_dict() for receptacle in receptacles]
    if generated_mess_count < 0:
        raise ValueError("generated_mess_count must be >= 0")
    if generated_mess_count == 0:
        selected = []
    elif generated_mess_manifest:
        selected = targets_from_generated_mess_manifest(
            selectable_objects,
            receptacle_payloads,
            generated_mess_manifest,
            target_count=int(generated_mess_count),
        )
    else:
        selected = select_generated_mess_targets(
            selectable_objects,
            receptacle_payloads,
            target_count=int(generated_mess_count),
            seed=seed,
            object_ids=generated_mess_object_ids or None,
        )

    objects = tuple(
        CleanupObject(
            object_id=str(item["object_id"]),
            name=str(item["name"]),
            category=str(item["category"]),
            location_id=str(item.get("start_receptacle_id") or item["location_id"]),
        )
        for item in selected
    )
    targets = tuple(
        TargetRule(
            object_id=str(item["object_id"]),
            valid_receptacle_ids=(str(item["target_receptacle_id"]),),
        )
        for item in selected
    )

    scenario_id = f"isaac-scene-index-{scene_source}-{scene_index}-{seed}-{len(targets)}"
    return CleanupScenario(
        scenario_id=scenario_id,
        task="Clean up this Isaac-loaded MolmoSpaces scene using scene-indexed objects.",
        seed=seed,
        objects=tuple(objects),
        receptacles=receptacles,
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=targets,
            success_threshold=generated_mess_success_threshold(len(targets)),
        ),
    )


def cleanup_receptacle_index_for_mess_generation(
    receptacle_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    cleanup = {
        handle: entry
        for handle, entry in receptacle_index.items()
        if norm(scene_object_category(entry)) in MOLMOSPACES_CLEANUP_RECEPTACLE_CATEGORY_NORMS
    }
    return cleanup or receptacle_index


def cleanup_receptacle_from_scene_index(
    handle: str,
    entry: dict[str, Any],
) -> CleanupReceptacle:
    category = scene_object_category(entry)
    return CleanupReceptacle(
        receptacle_id=handle,
        name=str(entry.get("public_label") or category or handle),
        room_area="isaac_scene",
        kind=str(entry.get("kind") or "receptacle"),
        category=category,
    )


def scene_object_name(handle: str, entry: dict[str, Any]) -> str:
    category = scene_object_category(entry)
    asset_id = str(entry.get("asset_id") or "").strip()
    if category and asset_id:
        return f"{category} ({asset_id})"
    return str(entry.get("public_label") or category or handle)


def scene_object_category(entry: dict[str, Any]) -> str:
    return str(entry.get("category") or entry.get("asset_id") or "object")


def scene_cleanup_object_category(entry: dict[str, Any]) -> str:
    category = scene_object_category(entry)
    tokens = scene_entry_tokens("", entry)
    for category_aliases, _target_aliases in SCENE_STRICT_CLEANUP_TARGET_ALIASES:
        matched_aliases = tuple(alias for alias in category_aliases if alias in tokens)
        if matched_aliases:
            return canonical_cleanup_category(category, matched_aliases)
    return category


def canonical_cleanup_category(category: str, aliases: tuple[str, ...]) -> str:
    category_norm = norm(category)
    for canonical, accepted in CANONICAL_CLEANUP_CATEGORY_ALIASES:
        accepted_norms = {norm(item) for item in accepted}
        alias_matches = any(norm(alias) in accepted_norms for alias in aliases)
        if category_norm in accepted_norms or alias_matches:
            return canonical
    return category


def scene_target_receptacle_id(
    entry: dict[str, Any],
    receptacle_index: dict[str, dict[str, Any]],
) -> str:
    entry_tokens = scene_entry_tokens("", entry)
    for category_aliases, target_aliases in SCENE_STRICT_CLEANUP_TARGET_ALIASES:
        if any(alias in entry_tokens for alias in category_aliases):
            target_id = first_receptacle_matching_aliases(receptacle_index, target_aliases)
            if target_id:
                return target_id
    return ""


def first_receptacle_matching_aliases(
    receptacle_index: dict[str, dict[str, Any]],
    aliases: tuple[str, ...],
) -> str:
    for handle, entry in sorted(receptacle_index.items()):
        tokens = scene_entry_tokens(handle, entry)
        if any(alias in tokens for alias in aliases):
            return handle
    return ""


def scene_source_receptacle_id(
    entry: dict[str, Any],
    receptacle_index: dict[str, dict[str, Any]],
    *,
    target_id: str,
) -> str:
    parent = str(entry.get("parent") or "")
    if parent and parent in receptacle_index and parent != target_id:
        return parent
    for handle in sorted(receptacle_index):
        if handle != target_id:
            return handle
    return target_id


def scene_entry_tokens(handle: str, entry: dict[str, Any]) -> set[str]:
    return _scene_match_tokens(
        handle,
        entry.get("metadata_handle"),
        entry.get("public_label"),
        entry.get("category"),
        entry.get("metadata_object_id"),
        entry.get("asset_id"),
    )


def scenario_from_generated_mess_manifest_or_limit(
    scenario: CleanupScenario,
    *,
    generated_mess_count: int,
    generated_mess_manifest: dict[str, Any] | None = None,
) -> CleanupScenario:
    if not generated_mess_manifest:
        return limit_scenario_to_generated_mess_count(
            scenario,
            generated_mess_count=generated_mess_count,
        )
    if generated_mess_count < 0:
        raise ValueError("generated_mess_count must be >= 0")
    if generated_mess_count == 0:
        return scenario_without_private_targets(
            scenario,
            scenario_id=f"{scenario.scenario_id}-canonical-mess-0",
            objects=(),
        )
    objects = [item.to_public_dict() for item in scenario.objects]
    receptacles = [item.to_public_dict() for item in scenario.receptacles]
    selected = targets_from_generated_mess_manifest(
        objects,
        receptacles,
        generated_mess_manifest,
        target_count=int(generated_mess_count),
    )
    target_ids = {str(item["object_id"]) for item in selected}
    source_objects = {item.object_id: item for item in scenario.objects}
    selected_objects = []
    for target in selected:
        object_id = str(target["object_id"])
        source = source_objects[object_id]
        selected_objects.append(
            CleanupObject(
                object_id=source.object_id,
                name=source.name,
                category=source.category,
                location_id=str(target.get("start_receptacle_id") or source.location_id),
                pickupable=source.pickupable,
            )
        )
    targets = tuple(
        TargetRule(
            object_id=str(item["object_id"]),
            valid_receptacle_ids=tuple(str(value) for value in item["valid_receptacle_ids"]),
        )
        for item in selected
    )
    scenario_id = f"{scenario.scenario_id}-canonical-mess-{len(targets)}"
    return CleanupScenario(
        scenario_id=scenario_id,
        task=scenario.task,
        seed=scenario.seed,
        objects=tuple(item for item in selected_objects if item.object_id in target_ids),
        receptacles=scenario.receptacles,
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=targets,
            success_threshold=generated_mess_success_threshold(len(targets)),
        ),
    )


def limit_scenario_to_generated_mess_count(
    scenario: CleanupScenario,
    *,
    generated_mess_count: int,
) -> CleanupScenario:
    count = int(generated_mess_count)
    if count < 0:
        raise ValueError("generated_mess_count must be >= 0")
    if count == 0:
        return scenario_without_private_targets(
            scenario,
            scenario_id=f"{scenario.scenario_id}-isaac-0",
            objects=(),
        )
    targets = tuple(scenario.private_manifest.targets[:count])
    if not targets:
        return scenario
    target_object_ids = {target.object_id for target in targets}
    objects = tuple(item for item in scenario.objects if item.object_id in target_object_ids)
    if not objects:
        return scenario
    scenario_id = f"{scenario.scenario_id}-isaac-{len(targets)}"
    return CleanupScenario(
        scenario_id=scenario_id,
        task=scenario.task,
        seed=scenario.seed,
        objects=objects,
        receptacles=scenario.receptacles,
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=targets,
            success_threshold=len(targets),
        ),
    )


def scenario_without_private_targets(
    scenario: CleanupScenario,
    *,
    scenario_id: str,
    objects: tuple[CleanupObject, ...],
) -> CleanupScenario:
    return CleanupScenario(
        scenario_id=scenario_id,
        task=scenario.task,
        seed=scenario.seed,
        objects=objects,
        receptacles=scenario.receptacles,
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=(),
            success_threshold=0,
        ),
    )


def scenario_from_map_bundle(
    bundle_dir: Path,
    *,
    seed: int,
    generated_mess_count: int,
) -> CleanupScenario:
    semantics = read_json_object(bundle_dir / "semantics.json", label="Isaac map bundle semantics")
    raw_fixtures = [dict(item) for item in semantics.get("static_landmarks") or []]
    if not raw_fixtures:
        return build_cleanup_scenario(seed=seed)

    receptacles = tuple(cleanup_receptacle_from_fixture(item) for item in raw_fixtures)
    target_specs = map_aligned_target_specs(raw_fixtures)
    if not target_specs:
        return build_cleanup_scenario(seed=seed)

    count = max(1, int(generated_mess_count))
    objects: list[CleanupObject] = []
    targets: list[TargetRule] = []
    for index in range(count):
        spec = target_specs[index % len(target_specs)]
        cycle = index // len(target_specs) + 1
        object_id = spec["object_id"] if cycle == 1 else f"{spec['object_id']}_{cycle}"
        source_id = str(spec["source_fixture_id"])
        target_id = str(spec["target_fixture_id"])
        objects.append(
            CleanupObject(
                object_id=object_id,
                name=str(spec["name"]),
                category=str(spec["category"]),
                location_id=source_id,
            )
        )
        targets.append(TargetRule(object_id=object_id, valid_receptacle_ids=(target_id,)))

    scenario_id = f"isaac-map-aligned-{bundle_dir.name}-{seed}"
    return CleanupScenario(
        scenario_id=scenario_id,
        task="Clean up this room by putting misplaced objects in appropriate places.",
        seed=seed,
        objects=tuple(objects),
        receptacles=receptacles,
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=tuple(targets),
            success_threshold=len(targets),
        ),
    )


def initial_receptacle_id(scenario: CleanupScenario) -> str:
    if scenario.objects:
        return scenario.objects[0].location_id
    if scenario.receptacles:
        return scenario.receptacles[0].receptacle_id
    return "floor_01"


def cleanup_receptacle_from_fixture(fixture: dict[str, Any]) -> CleanupReceptacle:
    fixture_id = str(fixture.get("fixture_id") or fixture.get("receptacle_id") or "")
    category = str(fixture.get("category") or fixture.get("name") or fixture_id)
    return CleanupReceptacle(
        receptacle_id=fixture_id,
        name=str(fixture.get("name") or fixture_id),
        room_area=str(fixture.get("room_id") or fixture.get("room_area") or "unknown"),
        kind="receptacle",
        category=category,
    )


def map_aligned_target_specs(fixtures: list[dict[str, Any]]) -> list[dict[str, str]]:
    candidates = [
        {
            "object_id": "mug_01",
            "name": "ceramic mug",
            "category": "dish",
            "target_aliases": ("sink", "countertop"),
            "source_aliases": ("sofa", "diningtable", "desk", "bed"),
        },
        {
            "object_id": "plate_01",
            "name": "dinner plate",
            "category": "dish",
            "target_aliases": ("sink", "countertop"),
            "source_aliases": ("diningtable", "sofa", "desk", "bed"),
        },
        {
            "object_id": "book_01",
            "name": "paperback book",
            "category": "book",
            "target_aliases": ("shelvingunit", "bookshelf", "shelf", "desk"),
            "source_aliases": ("sofa", "diningtable", "bed"),
        },
        {
            "object_id": "apple_01",
            "name": "apple",
            "category": "food",
            "target_aliases": ("fridge", "refrigerator"),
            "source_aliases": ("desk", "diningtable", "countertop"),
        },
        {
            "object_id": "remote_01",
            "name": "TV remote",
            "category": "electronics",
            "target_aliases": ("tvstand", "tv stand", "stand"),
            "source_aliases": ("bed", "desk", "diningtable", "sofa"),
        },
    ]
    specs = []
    for candidate in candidates:
        target = first_fixture_matching(fixtures, candidate["target_aliases"])
        source = first_fixture_matching(
            fixtures,
            candidate["source_aliases"],
            exclude_fixture_id=str(target.get("fixture_id") or "") if target else "",
        )
        if target is None or source is None:
            continue
        specs.append(
            {
                "object_id": str(candidate["object_id"]),
                "name": str(candidate["name"]),
                "category": str(candidate["category"]),
                "source_fixture_id": str(source["fixture_id"]),
                "target_fixture_id": str(target["fixture_id"]),
            }
        )
    return specs


def first_fixture_matching(
    fixtures: list[dict[str, Any]],
    aliases: tuple[str, ...],
    *,
    exclude_fixture_id: str = "",
) -> dict[str, Any] | None:
    for alias in aliases:
        alias_norm = norm(alias)
        for fixture in fixtures:
            fixture_id = str(fixture.get("fixture_id") or "")
            if fixture_id == exclude_fixture_id:
                continue
            text = norm(
                " ".join(str(fixture.get(key, "")) for key in ("fixture_id", "category", "name"))
            )
            if alias_norm and alias_norm in text:
                return fixture
    return None


def norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
