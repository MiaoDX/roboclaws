"""Isaac Lab backend runtime support."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roboclaws.household.types import CleanupScenario

SCENE_BINDING_SCHEMA = "isaac_public_scene_bindings_v1"

_GENERIC_CLEANUP_OBJECT_CATEGORY_NORMS = {
    # These are public cleanup buckets, not Isaac USD object categories.
    "book",
    "dish",
    "electronics",
    "food",
    "linen",
    "toy",
}


def scene_binding_diagnostics(
    *,
    runtime_mode: str,
    scenario: CleanupScenario,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
    real_smoke: dict[str, Any] | None,
) -> dict[str, Any]:
    object_bindings = {
        item.object_id: bind_public_scene_item(
            public_id=item.object_id,
            public_label=item.name,
            category=item.category,
            index=object_index,
            kind="object",
        )
        for item in scenario.objects
    }
    receptacle_bindings = {
        item.receptacle_id: bind_public_scene_item(
            public_id=item.receptacle_id,
            public_label=item.name,
            category=item.category or item.kind,
            index=receptacle_index,
            kind="receptacle",
        )
        for item in scenario.receptacles
    }
    selected_object_ids = _selected_cleanup_object_ids(scenario)
    selected_receptacle_ids = _selected_cleanup_receptacle_ids(scenario)
    selected_object_bindings = {
        object_id: object_bindings.get(object_id) or _unbound_scene_item(object_id, "object")
        for object_id in selected_object_ids
    }
    selected_receptacle_bindings = {
        receptacle_id: receptacle_bindings.get(receptacle_id)
        or _unbound_scene_item(receptacle_id, "receptacle")
        for receptacle_id in selected_receptacle_ids
    }
    selected_object_bound_count = _bound_count(selected_object_bindings)
    selected_receptacle_bound_count = _bound_count(selected_receptacle_bindings)
    blockers = _binding_blockers(
        selected_object_bindings,
        selected_receptacle_bindings,
    )
    if real_smoke is None:
        status = "placeholder_mapping"
        source = "scenario_fixture"
    elif blockers:
        status = "partial"
        source = "usd_stage_traversal"
    else:
        status = "selected_bound"
        source = "usd_stage_traversal"
    return {
        "schema": SCENE_BINDING_SCHEMA,
        "status": status,
        "source": source,
        "runtime_mode": runtime_mode,
        "public_object_count": len(object_bindings),
        "public_receptacle_count": len(receptacle_bindings),
        "public_object_bound_count": _bound_count(object_bindings),
        "public_receptacle_bound_count": _bound_count(receptacle_bindings),
        "selected_object_count": len(selected_object_bindings),
        "selected_target_receptacle_count": len(selected_receptacle_bindings),
        "selected_object_bound_count": selected_object_bound_count,
        "selected_target_receptacle_bound_count": selected_receptacle_bound_count,
        "object_bindings": object_bindings,
        "receptacle_bindings": receptacle_bindings,
        "selected_object_bindings": selected_object_bindings,
        "selected_target_receptacle_bindings": selected_receptacle_bindings,
        "blockers": blockers,
        "private_manifest_exposed_to_agent": False,
    }


def bind_public_scene_item(
    *,
    public_id: str,
    public_label: str,
    category: str | None,
    index: dict[str, dict[str, Any]],
    kind: str,
) -> dict[str, Any]:
    match = scene_index_match(
        public_id=public_id,
        public_label=public_label,
        category=category,
        index=index,
        kind=kind,
    )
    if match is None:
        return _unbound_scene_item(public_id, kind)
    handle, entry, strategy = match
    return {
        "status": "bound",
        "kind": kind,
        "public_id": public_id,
        "usd_handle": handle,
        "usd_prim_path": str(entry.get("usd_prim_path") or ""),
        "public_label": public_label,
        "category": category or "",
        "usd_public_label": str(entry.get("public_label") or ""),
        "usd_category": str(entry.get("category") or ""),
        "match_strategy": strategy,
        "index_source": str(entry.get("index_source") or ""),
        "has_renderable_geometry": entry.get("has_renderable_geometry"),
        "renderable_descendant_count": int(entry.get("renderable_descendant_count") or 0),
        "mesh_descendant_count": int(entry.get("mesh_descendant_count") or 0),
        "authored_reference_count": int(entry.get("authored_reference_count") or 0),
        "missing_referenced_asset_count": int(entry.get("missing_referenced_asset_count") or 0),
        "missing_referenced_assets": list(entry.get("missing_referenced_assets") or [])[:5],
        "geometry_status": str(entry.get("geometry_status") or ""),
    }


def scene_index_match(
    *,
    public_id: str,
    public_label: str,
    category: str | None,
    index: dict[str, dict[str, Any]],
    kind: str,
) -> tuple[str, dict[str, Any], str] | None:
    if public_id in index:
        return public_id, index[public_id], "exact_public_id"
    public_norm = _norm(public_id)
    label_norm = _norm(public_label)
    for handle, entry in index.items():
        handle_norm = _norm(handle)
        prim_name_norm = _norm(Path(str(entry.get("usd_prim_path") or "")).name)
        entry_label_norm = _norm(entry.get("public_label"))
        if public_norm and public_norm in {handle_norm, prim_name_norm, entry_label_norm}:
            return handle, entry, "normalized_public_id"
        if label_norm and label_norm in {handle_norm, prim_name_norm, entry_label_norm}:
            return handle, entry, "normalized_public_label"

    prefix_match = _first_semantic_index_match(
        public_id=public_id,
        public_label=public_label,
        category=category,
        index=index,
        kind=kind,
    )
    if prefix_match is not None:
        return prefix_match

    category_norm = _norm(category)
    if not category_norm or not _allow_category_fallback(kind, category_norm):
        return None
    category_matches = [
        (handle, entry)
        for handle, entry in index.items()
        if _norm(entry.get("category")) == category_norm
        or category_norm in _norm(entry.get("public_label"))
    ]
    if len(category_matches) == 1:
        handle, entry = category_matches[0]
        return handle, entry, "unique_category"
    return None


def _first_semantic_index_match(
    *,
    public_id: str,
    public_label: str,
    category: str | None,
    index: dict[str, dict[str, Any]],
    kind: str,
) -> tuple[str, dict[str, Any], str] | None:
    public_prefix = _public_handle_prefix(public_id)
    if public_prefix:
        matches = _semantic_index_matches((public_prefix,), index)
        if matches:
            handle, entry = matches[0]
            return handle, entry, "public_id_prefix_first"

    label_tokens = _scene_match_tokens(public_label)
    if label_tokens:
        matches = _semantic_index_matches(tuple(sorted(label_tokens)), index)
        if matches:
            handle, entry = matches[0]
            return handle, entry, "semantic_label_token_first"

    category_norm = _norm(category)
    if category_norm and _allow_category_fallback(kind, category_norm):
        category_tokens = _scene_match_tokens(category)
        matches = _semantic_index_matches(tuple(sorted(category_tokens)), index)
        if len(matches) == 1:
            handle, entry = matches[0]
            return handle, entry, "semantic_category_token_unique"
    return None


def _semantic_index_matches(
    tokens: tuple[str, ...],
    index: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    matches: list[tuple[str, dict[str, Any]]] = []
    for handle, entry in sorted(index.items()):
        entry_text = _norm(
            " ".join(
                str(entry.get(key) or "")
                for key in (
                    "metadata_handle",
                    "public_label",
                    "category",
                    "metadata_object_id",
                    "asset_id",
                )
            )
        )
        handle_norm = _norm(handle)
        if any(
            token and (handle_norm.startswith(token) or token in entry_text) for token in tokens
        ):
            matches.append((handle, entry))
    return matches


def _public_handle_prefix(public_id: str) -> str:
    prefix = str(public_id or "").split("_", 1)[0]
    normalized = _norm(prefix)
    return normalized if len(normalized) >= 3 else ""


def _allow_category_fallback(kind: str, category_norm: str) -> bool:
    if not category_norm:
        return False
    if kind == "object" and category_norm in _GENERIC_CLEANUP_OBJECT_CATEGORY_NORMS:
        return False
    return True


def _scene_match_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = str(value or "")
        for token in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", text):
            normalized = _norm(token)
            if len(normalized) >= 3:
                tokens.add(normalized)
        normalized = _norm(text)
        if len(normalized) >= 3:
            tokens.add(normalized)
    for token, aliases in {
        "remotecontrol": ("remote",),
        "cellphone": ("phone", "cellulartelephone"),
        "cellulartelephone": ("phone", "cellphone"),
        "tvstand": ("stand",),
    }.items():
        if token in tokens:
            tokens.update(aliases)
    return tokens


def _unbound_scene_item(public_id: str, kind: str) -> dict[str, Any]:
    return {
        "status": "unresolved",
        "kind": kind,
        "public_id": public_id,
        "usd_handle": "",
        "usd_prim_path": "",
        "match_strategy": "none",
        "blocker": "No stable USD prim candidate matched this public cleanup handle.",
    }


def _binding_blockers(
    selected_object_bindings: dict[str, dict[str, Any]],
    selected_receptacle_bindings: dict[str, dict[str, Any]],
) -> list[str]:
    blockers = []
    for object_id, binding in selected_object_bindings.items():
        if binding.get("status") != "bound":
            blockers.append(f"Selected cleanup object has no USD binding: {object_id}")
    for receptacle_id, binding in selected_receptacle_bindings.items():
        if binding.get("status") != "bound":
            blockers.append(f"Selected target receptacle has no USD binding: {receptacle_id}")
    return blockers


def _bound_count(bindings: dict[str, dict[str, Any]]) -> int:
    return sum(1 for item in bindings.values() if item.get("status") == "bound")


def _selected_cleanup_object_ids(scenario: CleanupScenario) -> list[str]:
    return _dedupe(target.object_id for target in scenario.private_manifest.targets)


def _selected_cleanup_receptacle_ids(scenario: CleanupScenario) -> list[str]:
    return _dedupe(
        receptacle_id
        for target in scenario.private_manifest.targets
        for receptacle_id in target.valid_receptacle_ids
    )


def _dedupe(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
