from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

LABEL_INSTANCES = ("class", "kind", "usd_prim_path")
RENDERABLE_TYPE_NAMES = {"Mesh", "Cube", "Sphere", "Capsule", "Cone", "Cylinder"}
MOLMOSPACES_RECEPTACLE_CATEGORY_NORMS = {
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


def _load_molmospaces_scene_metadata(scene_usd_path: Path) -> dict[str, dict[str, Any]]:
    metadata_path = scene_usd_path.parent / "scene_metadata.json"
    if not metadata_path.is_file():
        return {}
    payload = read_json_object(metadata_path, label="MolmoSpaces scene metadata")
    objects = payload.get("objects") if isinstance(payload, dict) else None
    if not isinstance(objects, dict):
        return {}
    return {
        str(handle): dict(info)
        for handle, info in objects.items()
        if isinstance(info, dict) and str(handle)
    }


def _copy_metadata_next_to_output(*, scene_usd_path: Path, output_usd_path: Path) -> bool:
    metadata_path = scene_usd_path.parent / "scene_metadata.json"
    if not metadata_path.is_file():
        return False
    output_metadata_path = output_usd_path.parent / "scene_metadata.json"
    output_metadata_path.write_text(metadata_path.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _prim_paths_by_name(stage: Any) -> dict[str, list[str]]:
    paths_by_name: dict[str, list[str]] = {}
    for prim in stage.Traverse():
        paths_by_name.setdefault(prim.GetName(), []).append(str(prim.GetPath()))
    return paths_by_name


def _metadata_entries(
    *,
    metadata: dict[str, dict[str, Any]],
    prim_paths_by_name: dict[str, list[str]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for handle, raw_info in metadata.items():
        prim_path = _molmospaces_metadata_prim_path(handle, prim_paths_by_name)
        if prim_path is None:
            continue
        kind = "receptacle" if _is_molmospaces_receptacle_metadata(raw_info) else "object"
        category = str(raw_info.get("category") or _category_from_usd_name(handle))
        asset_id = str(raw_info.get("asset_id") or "")
        metadata_object_id = str(raw_info.get("object_id") or "")
        public_label = " ".join(part for part in (category, metadata_object_id, asset_id) if part)
        entries.append(
            {
                "metadata_handle": handle,
                "usd_prim_path": prim_path,
                "kind": kind,
                "category": category,
                "public_label": public_label or handle,
                "asset_id": asset_id,
                "metadata_object_id": metadata_object_id,
                "is_static": bool(raw_info.get("is_static")),
            }
        )
    return entries


def _molmospaces_metadata_prim_path(
    handle: str,
    prim_paths_by_name: dict[str, list[str]],
) -> str | None:
    candidates = list(prim_paths_by_name.get(handle) or [])
    if not candidates:
        return None
    return sorted(candidates, key=_molmospaces_prim_path_rank)[0]


def _molmospaces_prim_path_rank(prim_path: str) -> tuple[int, int, str]:
    normalized = f"/{prim_path.strip('/')}/"
    is_top_level_geometry = "/geometry/" in normalized.lower() and normalized.count("/") <= 4
    return (0 if is_top_level_geometry else 1, normalized.count("/"), prim_path)


def _is_molmospaces_receptacle_metadata(metadata: dict[str, Any]) -> bool:
    category = _norm(metadata.get("category"))
    if not category:
        return False
    if category in MOLMOSPACES_RECEPTACLE_CATEGORY_NORMS:
        return True
    return bool(metadata.get("children")) and metadata.get("is_static") is True


def _author_semantic_labels(
    *,
    stage: Any,
    entries: list[dict[str, Any]],
    usd_geom: Any,
    label_containers: bool,
) -> dict[str, Any]:
    requested = len(entries)
    labeled_entry_count = 0
    missing_prim_count = 0
    container_labeled_prim_count = 0
    renderable_labeled_prim_count = 0
    gprim_labeled_prim_count = 0
    mesh_labeled_prim_count = 0
    target_samples: list[dict[str, str]] = []
    missing_handles: list[str] = []

    for entry in entries:
        prim_path = str(entry["usd_prim_path"])
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            missing_prim_count += 1
            missing_handles.append(str(entry["metadata_handle"]))
            continue

        labels = _semantic_labels(entry=entry, prim_path=prim_path)
        targets = _semantic_label_targets(prim=prim, usd_geom=usd_geom)
        if label_containers:
            _set_semantic_labels(prim=prim, labels=labels)
            container_labeled_prim_count += 1
        for target in targets:
            _set_semantic_labels(prim=target, labels=labels)
            renderable_labeled_prim_count += 1
            classification = _target_classification(target, usd_geom=usd_geom)
            if classification["is_gprim"]:
                gprim_labeled_prim_count += 1
            if classification["type_name"] == "Mesh":
                mesh_labeled_prim_count += 1
            if len(target_samples) < 25:
                target_samples.append(
                    {
                        "metadata_handle": str(entry["metadata_handle"]),
                        "source_prim_path": prim_path,
                        "target_prim_path": classification["path"],
                        "target_type": classification["type_name"],
                        "target_kind": classification["kind"],
                    }
                )
        if targets or label_containers:
            labeled_entry_count += 1

    return {
        "requested_entry_count": requested,
        "labeled_entry_count": labeled_entry_count,
        "missing_prim_count": missing_prim_count,
        "container_labeled_prim_count": container_labeled_prim_count,
        "renderable_labeled_prim_count": renderable_labeled_prim_count,
        "gprim_labeled_prim_count": gprim_labeled_prim_count,
        "mesh_labeled_prim_count": mesh_labeled_prim_count,
        "missing_handles": missing_handles[:25],
        "target_samples": target_samples,
    }


def _semantic_label_targets(*, prim: Any, usd_geom: Any) -> list[Any]:
    from pxr import Usd

    targets: list[Any] = []
    for candidate in Usd.PrimRange(prim):
        if _prim_is_renderable(candidate, usd_geom=usd_geom):
            targets.append(candidate)
    return targets


def _prim_is_renderable(prim: Any, *, usd_geom: Any) -> bool:
    try:
        return bool(prim.IsA(usd_geom.Gprim))
    except Exception:
        return str(prim.GetTypeName() or "") in RENDERABLE_TYPE_NAMES


def _set_semantic_labels(*, prim: Any, labels: dict[str, str]) -> None:
    for instance_name, label in labels.items():
        _set_labels_api(prim=prim, instance_name=instance_name, labels=[label])


def _set_labels_api(*, prim: Any, instance_name: str, labels: list[str]) -> None:
    try:
        from pxr import UsdSemantics

        api = UsdSemantics.LabelsAPI.Apply(prim, instance_name)
        api.CreateLabelsAttr().Set(labels)
        return
    except Exception:
        pass

    attr = prim.CreateAttribute(f"semantics:labels:{instance_name}", _token_array_value_type())
    attr.Set(labels)
    _ensure_api_schema_token(prim=prim, schema=f"SemanticsLabelsAPI:{instance_name}")


def _token_array_value_type() -> Any:
    from pxr import Sdf

    return Sdf.ValueTypeNames.TokenArray


def _ensure_api_schema_token(*, prim: Any, schema: str) -> None:
    from pxr import Sdf, Vt

    attr = prim.GetAttribute("apiSchemas")
    current = list(attr.Get() or []) if attr and attr.IsValid() else []
    if schema in current:
        return
    current.append(schema)
    if not attr or not attr.IsValid():
        attr = prim.CreateAttribute("apiSchemas", Sdf.ValueTypeNames.TokenArray, custom=False)
    attr.Set(Vt.TokenArray(current))


def _semantic_labels(*, entry: dict[str, Any], prim_path: str) -> dict[str, str]:
    category = str(entry.get("category") or entry.get("public_label") or Path(prim_path).name)
    kind = str(entry.get("kind") or "scene_prim")
    return {
        "class": category,
        "kind": kind,
        "usd_prim_path": prim_path,
    }


def _target_classification(prim: Any, *, usd_geom: Any) -> dict[str, Any]:
    path = str(prim.GetPath())
    type_name = str(prim.GetTypeName() or "")
    is_gprim = _prim_is_renderable(prim, usd_geom=usd_geom)
    kind = "gprim" if is_gprim else "prim"
    if type_name:
        kind = f"{kind}:{type_name}"
    return {
        "path": path,
        "type_name": type_name,
        "kind": kind,
        "is_gprim": is_gprim,
    }


def _category_from_usd_name(value: str) -> str:
    normalized = _norm(value)
    return normalized or "unknown"


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
