"""Isaac Lab backend runtime support."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.backends.isaaclab.isaac_support_surface_geometry import (
    usd_receptacle_support_surfaces,
)
from roboclaws.household.types import CleanupScenario


@dataclass(frozen=True)
class IsaacUsdSceneIndexHooks:
    annotate_usd_index_geometry: Callable[..., None]
    authored_reference_asset_paths: Callable[..., list[str]]
    dict_value: Callable[..., dict[str, Any]]
    iter_usd_prim_range: Callable[..., Any]
    is_object_prim_path: Callable[..., bool]
    is_receptacle_prim_path: Callable[..., bool]
    local_reference_asset_missing: Callable[..., bool]
    merge_molmospaces_metadata_index: Callable[..., None]
    pose_near: Callable[..., dict[str, Any]]
    room_outline_from_usd_prim: Callable[..., dict[str, Any] | None]
    round_vec3: Callable[..., list[float]]
    support_pose_from_support_surface: Callable[..., dict[str, Any] | None]
    support_pose_from_usd_bounds: Callable[..., dict[str, Any] | None]
    usd_handle_from_prim: Callable[..., str]
    usd_index_entry: Callable[..., dict[str, Any]]
    usd_receptacle_support_surfaces: Callable[..., list[dict[str, Any]]]
    usd_world_bounds: Callable[..., dict[str, Any] | None]
    usd_world_root_position: Callable[..., list[float] | None]


def inspect_usd_scene_index(
    usd_path: Path,
    *,
    hooks: IsaacUsdSceneIndexHooks,
) -> dict[str, Any]:
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(usd_path))
    if stage is None:
        raise RuntimeError(f"Isaac USD stage could not be opened for indexing: {usd_path}")

    object_index: dict[str, dict[str, Any]] = {}
    receptacle_index: dict[str, dict[str, Any]] = {}
    room_outlines: list[dict[str, Any]] = []
    prim_paths_by_name: dict[str, list[str]] = {}
    stage_prim_count = 0
    for prim in stage.Traverse():
        stage_prim_count += 1
        prim_path = str(prim.GetPath())
        prim_paths_by_name.setdefault(prim.GetName(), []).append(prim_path)
        handle = hooks.usd_handle_from_prim(prim_path, object_index, receptacle_index)
        room_outline = hooks.room_outline_from_usd_prim(
            prim_path,
            prim,
            usd_geom=UsdGeom,
        )
        if room_outline is not None:
            room_outlines.append(room_outline)
        if hooks.is_object_prim_path(prim_path):
            object_index[handle] = hooks.usd_index_entry(prim_path, prim.GetName(), "object")
        elif hooks.is_receptacle_prim_path(prim_path):
            receptacle_index[handle] = {
                **hooks.usd_index_entry(prim_path, prim.GetName(), "receptacle"),
                "support_pose": hooks.pose_near(handle),
            }
    hooks.merge_molmospaces_metadata_index(
        usd_path=usd_path,
        prim_paths_by_name=prim_paths_by_name,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )
    hooks.annotate_usd_index_geometry(
        usd_path=usd_path,
        stage=stage,
        object_index=object_index,
        receptacle_index=receptacle_index,
        usd_geom=UsdGeom,
    )

    blockers = []
    if not object_index:
        blockers.append("No movable-object USD prim candidates matched current path heuristics.")
    if not receptacle_index:
        blockers.append(
            "No receptacle/support USD prim candidates matched current path heuristics."
        )
    return {
        "schema": "isaac_usd_scene_index_v1",
        "status": "indexed" if not blockers else "partial",
        "source": str(usd_path),
        "stage_prim_count": stage_prim_count,
        "object_candidate_count": len(object_index),
        "receptacle_candidate_count": len(receptacle_index),
        "room_outline_count": len(room_outlines),
        "room_outlines": sorted(room_outlines, key=lambda item: str(item.get("room_id") or "")),
        "object_index": object_index,
        "receptacle_index": receptacle_index,
        "blockers": blockers,
    }


def annotate_usd_index_geometry(
    *,
    usd_path: Path,
    stage: Any,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
    usd_geom: Any,
    hooks: IsaacUsdSceneIndexHooks,
) -> None:
    for index in (object_index, receptacle_index):
        for entry in index.values():
            prim_path = str(entry.get("usd_prim_path") or "")
            if not prim_path:
                entry.update(
                    {
                        "prim_type": "",
                        "valid_stage_prim": False,
                        "has_renderable_geometry": False,
                        "renderable_descendant_count": 0,
                        "mesh_descendant_count": 0,
                        "authored_reference_count": 0,
                        "missing_referenced_asset_count": 0,
                        "missing_referenced_assets": [],
                        "geometry_status": "missing_prim_path",
                    }
                )
                continue
            prim = stage.GetPrimAtPath(prim_path)
            diagnostics = usd_prim_geometry_diagnostics(
                usd_path=usd_path,
                prim=prim,
                usd_geom=usd_geom,
                hooks=hooks,
            )
            entry.update(diagnostics)
            if str(entry.get("kind") or "") == "receptacle" or isinstance(
                entry.get("support_pose"), dict
            ):
                support_surfaces = hooks.usd_receptacle_support_surfaces(
                    prim=prim, usd_geom=usd_geom
                )
                if support_surfaces:
                    entry["support_surfaces"] = support_surfaces
                support_pose = hooks.support_pose_from_usd_bounds(
                    entry.get("usd_world_bounds"),
                    fallback=hooks.dict_value(entry.get("support_pose")),
                )
                if support_surfaces:
                    support_pose = hooks.support_pose_from_support_surface(
                        support_surfaces[0],
                        fallback=support_pose,
                    )
                if support_pose is not None:
                    entry["support_pose"] = support_pose


def usd_prim_geometry_diagnostics(
    *,
    usd_path: Path,
    prim: Any,
    usd_geom: Any,
    hooks: IsaacUsdSceneIndexHooks,
) -> dict[str, Any]:
    if not prim or not prim.IsValid():
        return {
            "prim_type": "",
            "valid_stage_prim": False,
            "has_renderable_geometry": False,
            "renderable_descendant_count": 0,
            "mesh_descendant_count": 0,
            "authored_reference_count": 0,
            "missing_referenced_asset_count": 0,
            "missing_referenced_assets": [],
            "geometry_status": "missing_stage_prim",
        }
    gprim_type = getattr(usd_geom, "Gprim", None)
    renderable_descendant_count = 0
    mesh_descendant_count = 0
    for descendant in hooks.iter_usd_prim_range(prim):
        if gprim_type is not None and descendant.IsA(gprim_type):
            renderable_descendant_count += 1
        if str(descendant.GetTypeName() or "") == "Mesh":
            mesh_descendant_count += 1
    reference_assets = hooks.authored_reference_asset_paths(usd_path=usd_path, prim=prim)
    missing_assets = [
        asset for asset in reference_assets if hooks.local_reference_asset_missing(asset)
    ]
    has_renderable_geometry = renderable_descendant_count > 0
    if has_renderable_geometry:
        geometry_status = "renderable"
    elif missing_assets:
        geometry_status = "missing_referenced_geometry"
    else:
        geometry_status = "no_renderable_descendants"
    world_bounds = hooks.usd_world_bounds(prim, usd_geom=usd_geom)
    world_root_position = hooks.usd_world_root_position(prim, usd_geom=usd_geom)
    return {
        "prim_type": str(prim.GetTypeName() or ""),
        "valid_stage_prim": True,
        "has_renderable_geometry": has_renderable_geometry,
        "renderable_descendant_count": renderable_descendant_count,
        "mesh_descendant_count": mesh_descendant_count,
        "authored_reference_count": len(reference_assets),
        "missing_referenced_asset_count": len(missing_assets),
        "missing_referenced_assets": missing_assets[:5],
        "geometry_status": geometry_status,
        "is_instanceable": bool(prim.IsInstanceable()),
        "is_instance": bool(prim.IsInstance()),
        "usd_world_bounds": world_bounds,
        "usd_world_root_position": world_root_position,
    }


def usd_world_bounds(
    prim: Any,
    *,
    usd_geom: Any,
    round_vec3: Callable[[list[float]], list[float]],
) -> dict[str, Any] | None:
    from pxr import Usd

    bbox_cache = usd_geom.BBoxCache(
        Usd.TimeCode.Default(),
        [usd_geom.Tokens.default_, usd_geom.Tokens.render, usd_geom.Tokens.proxy],
    )
    bbox = bbox_cache.ComputeWorldBound(prim).ComputeAlignedBox()
    min_point = [float(value) for value in bbox.GetMin()]
    max_point = [float(value) for value in bbox.GetMax()]
    size = [max_v - min_v for min_v, max_v in zip(min_point, max_point, strict=True)]
    if any(not math.isfinite(value) for value in [*min_point, *max_point, *size]):
        return None
    if max(size) <= 0:
        return None
    center = [(min_v + max_v) / 2.0 for min_v, max_v in zip(min_point, max_point, strict=True)]
    return {
        "min": round_vec3(min_point),
        "max": round_vec3(max_point),
        "center": round_vec3(center),
        "size": round_vec3(size),
    }


def usd_world_root_position(
    prim: Any,
    *,
    usd_geom: Any,
    round_vec3: Callable[[list[float]], list[float]],
) -> list[float] | None:
    try:
        transform = usd_geom.Xformable(prim).ComputeLocalToWorldTransform(0.0)
        position = transform.Transform((0.0, 0.0, 0.0))
    except Exception:
        return None
    values = [float(value) for value in position]
    if any(not math.isfinite(value) for value in values):
        return None
    return round_vec3(values)


def receptacle_support_surfaces(
    *,
    prim: Any,
    usd_geom: Any,
    world_bounds: Callable[..., dict[str, Any] | None],
    iter_prim_range: Callable[..., Any],
) -> list[dict[str, Any]]:
    return usd_receptacle_support_surfaces(
        prim=prim,
        usd_geom=usd_geom,
        world_bounds=world_bounds,
        iter_prim_range=iter_prim_range,
    )


def iter_usd_prim_range(prim: Any) -> Any:
    from pxr import Usd

    return Usd.PrimRange(prim)


def room_outline_from_usd_prim(
    prim_path: str,
    prim: Any,
    *,
    usd_geom: Any,
    world_bounds: Callable[..., dict[str, Any] | None],
) -> dict[str, Any] | None:
    match = re.search(r"/(room_\d+)_visual(?:_\d+)?$", prim_path)
    if match is None:
        return None
    bounds = world_bounds(prim, usd_geom=usd_geom)
    if bounds is None:
        return None
    center = _vec3(bounds.get("center"))
    size = _vec3(bounds.get("size"))
    if center is None or size is None:
        return None
    half_extents = [abs(size[0]) / 2.0, abs(size[1]) / 2.0]
    if min(half_extents) < 0.25:
        return None
    room_id = match.group(1)
    return {
        "room_id": room_id,
        "label": room_id.replace("_", " ").title(),
        "center": [round(center[0], 6), round(center[1], 6)],
        "half_extents": [round(half_extents[0], 6), round(half_extents[1], 6)],
        "provenance": "isaac_usd_room_mesh_world_bounds",
        "usd_prim_path": prim_path,
    }


def room_outlines_from_scene_index_diagnostics(
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    return [dict(item) for item in diagnostics.get("room_outlines") or [] if isinstance(item, dict)]


def fallback_room_outlines_from_indices(
    *,
    scenario: CleanupScenario,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[list[float]]] = {}
    room_by_receptacle = {
        item.receptacle_id: str(item.room_area or "isaac_scene") for item in scenario.receptacles
    }
    for receptacle in scenario.receptacles:
        position = _support_pose_position(
            _dict(_dict(receptacle_index.get(receptacle.receptacle_id)).get("support_pose"))
        )
        if position is None:
            position = _vec3(
                _dict(
                    _dict(receptacle_index.get(receptacle.receptacle_id)).get("usd_world_bounds")
                ).get("center")
            )
        if position is None:
            continue
        grouped.setdefault(room_by_receptacle[receptacle.receptacle_id], []).append(position)
    for obj in scenario.objects:
        position = _vec3(
            _dict(_dict(object_index.get(obj.object_id)).get("usd_world_bounds")).get("center")
        )
        if position is None:
            continue
        grouped.setdefault(room_by_receptacle.get(obj.location_id, "isaac_scene"), []).append(
            position
        )
    outlines = []
    for room_id, points in grouped.items():
        if not points:
            continue
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        center = [round((min(xs) + max(xs)) / 2.0, 6), round((min(ys) + max(ys)) / 2.0, 6)]
        half_extents = [
            round(max((max(xs) - min(xs)) / 2.0, 0.8), 6),
            round(max((max(ys) - min(ys)) / 2.0, 0.8), 6),
        ]
        outlines.append(
            {
                "room_id": room_id,
                "label": room_id.replace("_", " ").title(),
                "center": center,
                "half_extents": half_extents,
                "provenance": "scenario_fixture_room_bounds",
            }
        )
    return sorted(outlines, key=lambda item: str(item.get("room_id") or ""))


def round_vec3(values: list[float] | tuple[float, ...]) -> list[float]:
    return [round(float(value), 6) for value in values[:3]]


def authored_reference_asset_paths(*, usd_path: Path, prim: Any) -> list[str]:
    assets: list[str] = []
    for spec in prim.GetPrimStack():
        reference_list = getattr(spec, "referenceList", None)
        for reference in usd_list_op_items(reference_list):
            asset_path = str(getattr(reference, "assetPath", "") or "")
            if not asset_path:
                continue
            layer_path = Path(str(getattr(spec.layer, "realPath", "") or usd_path))
            if not is_local_reference_asset_path(asset_path):
                assets.append(asset_path)
            else:
                assets.append(str((layer_path.parent / asset_path).resolve()))
    return sorted(dict.fromkeys(assets))


def usd_list_op_items(list_op: Any) -> list[Any]:
    items: list[Any] = []
    for attr in ("prependedItems", "addedItems", "appendedItems", "explicitItems"):
        values = getattr(list_op, attr, None)
        if values:
            items.extend(list(values))
    return items


def is_local_reference_asset_path(asset_path: str) -> bool:
    return "://" not in asset_path and not asset_path.startswith("@")


def local_reference_asset_missing(asset_path: str) -> bool:
    return is_local_reference_asset_path(asset_path) and not Path(asset_path).exists()


def _support_pose_position(pose: dict[str, Any]) -> list[float] | None:
    try:
        return [float(pose["x"]), float(pose["y"]), float(pose.get("z", 0.0))]
    except (KeyError, TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _vec3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None
