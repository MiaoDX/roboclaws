"""Isaac Lab backend runtime support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

MOLMOSPACES_SCENE_INDEX_RECEPTACLE_CATEGORY_NORMS = {
    "bed",
    "bookshelf",
    "chair",
    "countertop",
    "desk",
    "diningtable",
    "dresser",
    "fridge",
    "garbagecan",
    "shelf",
    "shelvingunit",
    "sink",
    "sofa",
    "stand",
    "toilet",
    "tvstand",
}


def merge_molmospaces_metadata_index(
    *,
    usd_path: Path,
    prim_paths_by_name: dict[str, list[str]],
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
) -> None:
    metadata = load_molmospaces_scene_metadata(usd_path)
    if not metadata:
        return

    for handle, raw_info in metadata.items():
        if not isinstance(raw_info, dict):
            continue
        prim_path = molmospaces_metadata_prim_path(handle, prim_paths_by_name)
        if prim_path is None:
            continue
        if is_molmospaces_receptacle_metadata(raw_info):
            receptacle_index.setdefault(
                handle,
                {
                    **usd_metadata_index_entry(prim_path, handle, raw_info, "receptacle"),
                    "support_pose": _pose_near(handle),
                },
            )
        elif is_molmospaces_object_metadata(raw_info):
            object_index.setdefault(
                handle,
                usd_metadata_index_entry(prim_path, handle, raw_info, "object"),
            )


def load_molmospaces_scene_metadata(usd_path: Path) -> dict[str, dict[str, Any]]:
    metadata_path = usd_path.parent / "scene_metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        payload = read_json_object(metadata_path, label="MolmoSpaces scene metadata")
    except (OSError, ValueError):
        return {}
    objects = payload.get("objects") if isinstance(payload, dict) else None
    if not isinstance(objects, dict):
        return {}
    return {
        str(handle): dict(info)
        for handle, info in objects.items()
        if isinstance(info, dict) and str(handle)
    }


def molmospaces_metadata_prim_path(
    handle: str,
    prim_paths_by_name: dict[str, list[str]],
) -> str | None:
    candidates = list(prim_paths_by_name.get(handle) or [])
    if not candidates:
        return None
    return sorted(candidates, key=molmospaces_prim_path_rank)[0]


def molmospaces_prim_path_rank(prim_path: str) -> tuple[int, int, str]:
    normalized = f"/{prim_path.strip('/')}/"
    is_top_level_geometry = "/geometry/" in normalized.lower() and normalized.count("/") <= 4
    return (0 if is_top_level_geometry else 1, normalized.count("/"), prim_path)


def usd_metadata_index_entry(
    prim_path: str,
    handle: str,
    metadata: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    category = str(metadata.get("category") or category_from_usd_name(handle))
    metadata_object_id = str(metadata.get("object_id") or "")
    asset_id = str(metadata.get("asset_id") or "")
    label_parts = [category, metadata_object_id, asset_id]
    public_label = " ".join(part for part in label_parts if part)
    return {
        "usd_prim_path": prim_path,
        "category": category,
        "public_label": public_label or handle,
        "index_source": "usd_stage_traversal",
        "kind": kind,
        "metadata_source": "molmospaces_scene_metadata",
        "metadata_handle": handle,
        "metadata_object_id": metadata_object_id,
        "asset_id": asset_id,
        "metadata_room_id": metadata_room_id(metadata),
        "parent": str(metadata.get("parent") or ""),
        "is_static": bool(metadata.get("is_static")),
    }


def metadata_room_id(metadata: dict[str, Any]) -> str:
    raw_room_id = metadata.get("room_id")
    if raw_room_id in {None, ""}:
        return ""
    room_id = str(raw_room_id)
    return room_id if room_id.startswith("room_") else f"room_{room_id}"


def is_molmospaces_object_metadata(metadata: dict[str, Any]) -> bool:
    return metadata.get("is_static") is False


def is_molmospaces_receptacle_metadata(metadata: dict[str, Any]) -> bool:
    category = _norm(metadata.get("category"))
    if not category:
        return False
    if category in MOLMOSPACES_SCENE_INDEX_RECEPTACLE_CATEGORY_NORMS:
        return True
    return bool(metadata.get("children")) and metadata.get("is_static") is True


def usd_index_entry(prim_path: str, prim_name: str, kind: str) -> dict[str, Any]:
    return {
        "usd_prim_path": prim_path,
        "category": category_from_usd_name(prim_name),
        "public_label": prim_name,
        "index_source": "usd_stage_traversal",
        "kind": kind,
    }


def usd_handle_from_prim(
    prim_path: str,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
) -> str:
    base = usd_safe_name(Path(prim_path).name)
    if base in {"World", "Objects", "Receptacles", "Fixtures", "Scene"}:
        base = usd_safe_name(prim_path.strip("/").replace("/", "_"))
    existing = set(object_index) | set(receptacle_index)
    if base not in existing:
        return base
    suffix = 2
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"


def is_object_prim_path(prim_path: str) -> bool:
    normalized = f"/{prim_path.strip('/').lower()}/"
    return any(
        contains_child_segment(normalized, segment) for segment in ("objects", "movable", "props")
    )


def is_receptacle_prim_path(prim_path: str) -> bool:
    normalized = f"/{prim_path.strip('/').lower()}/"
    return any(
        contains_child_segment(normalized, segment)
        for segment in ("receptacles", "fixtures", "surfaces", "support_surfaces")
    )


def contains_child_segment(normalized_path: str, segment: str) -> bool:
    token = f"/{segment}/"
    return token in normalized_path and not normalized_path.endswith(token)


def category_from_usd_name(value: str) -> str:
    normalized = _norm(value)
    if normalized:
        return normalized
    return "unknown"


def usd_safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
    if not cleaned:
        return "unnamed"
    if cleaned[0].isdigit():
        return f"_{cleaned}"
    return cleaned


def _pose_near(anchor_id: str) -> dict[str, float | str]:
    value = sum(ord(char) for char in anchor_id)
    return {
        "frame": "world",
        "x": round((value % 17) * 0.17, 3),
        "y": round(((value // 17) % 17) * 0.13, 3),
        "z": 0.0,
        "yaw_deg": float((value * 13) % 360),
    }


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
