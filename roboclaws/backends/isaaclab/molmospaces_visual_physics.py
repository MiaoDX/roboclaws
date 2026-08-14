from __future__ import annotations

from typing import Any

PHYSICS_API_SCHEMA_NAMES = {
    "PhysicsArticulationRootAPI",
    "PhysicsCollisionAPI",
    "PhysicsFilteredPairsAPI",
    "PhysicsMassAPI",
    "PhysicsRigidBodyAPI",
}
PHYSICS_PRIM_TYPE_NAMES = {"PhysicsFixedJoint", "PhysicsPrismaticJoint", "PhysicsRevoluteJoint"}
PHYSICS_PROPERTY_PREFIXES = ("physics:", "physx")


def _freeze_visual_physics(stage: Any) -> dict[str, Any]:
    removed_joint_paths: list[str] = []
    removed_api_schema_count = 0
    removed_property_count = 0
    for prim in list(stage.Traverse()):
        type_name = str(prim.GetTypeName() or "")
        if type_name in PHYSICS_PRIM_TYPE_NAMES:
            removed_joint_paths.append(str(prim.GetPath()))
            stage.RemovePrim(prim.GetPath())
            continue
        removed_api_schema_count += _remove_physics_api_schemas(prim)
        for prop_name in list(prim.GetPropertyNames()):
            if _is_physics_property_name(str(prop_name)):
                prim.RemoveProperty(prop_name)
                removed_property_count += 1
    return {
        "visual_physics_status": "frozen_static_visual_usd",
        "visual_physics_joint_removed_count": len(removed_joint_paths),
        "visual_physics_api_schema_removed_count": removed_api_schema_count,
        "visual_physics_property_removed_count": removed_property_count,
        "visual_physics_removed_joint_samples": removed_joint_paths[:25],
        "visual_physics_freeze_reason": (
            "Flattened USD already contains the visual xforms from the MolmoSpaces "
            "conversion. Removing physics schemas and joints prevents Isaac report "
            "capture from re-solving articulated THOR assets away from the MuJoCo "
            "visual/rest pose."
        ),
    }


def _visual_physics_not_frozen() -> dict[str, Any]:
    return {
        "visual_physics_status": "source_physics_preserved",
        "visual_physics_joint_removed_count": 0,
        "visual_physics_api_schema_removed_count": 0,
        "visual_physics_property_removed_count": 0,
        "visual_physics_removed_joint_samples": [],
        "visual_physics_freeze_reason": (
            "Physics schemas and joints were preserved by caller request."
        ),
    }


def _remove_physics_api_schemas(prim: Any) -> int:
    from pxr import Sdf, Vt

    removed = _remove_physics_api_schema_metadata(prim)
    attr = prim.GetAttribute("apiSchemas")
    if not attr or not attr.IsValid():
        return removed
    current = [str(value) for value in list(attr.Get() or [])]
    kept = [value for value in current if value not in PHYSICS_API_SCHEMA_NAMES]
    attr_removed = len(current) - len(kept)
    if not attr_removed:
        return removed
    attr.Set(Vt.TokenArray(kept))
    if not kept:
        prim.RemoveProperty("apiSchemas")
    elif attr.GetTypeName() != Sdf.ValueTypeNames.TokenArray:
        attr.Set(Vt.TokenArray(kept))
    return removed + attr_removed


def _remove_physics_api_schema_metadata(prim: Any) -> int:
    from pxr import Sdf

    api_schemas = prim.GetMetadata("apiSchemas")
    if api_schemas is None:
        return 0
    if isinstance(api_schemas, Sdf.TokenListOp):
        explicit = _filter_physics_api_schemas(api_schemas.explicitItems)
        prepended = _filter_physics_api_schemas(api_schemas.prependedItems)
        appended = _filter_physics_api_schemas(api_schemas.appendedItems)
        deleted = list(api_schemas.deletedItems or [])
        ordered = _filter_physics_api_schemas(api_schemas.orderedItems)
        removed = (
            len(api_schemas.explicitItems or [])
            + len(api_schemas.prependedItems or [])
            + len(api_schemas.appendedItems or [])
            + len(api_schemas.orderedItems or [])
            - len(explicit)
            - len(prepended)
            - len(appended)
            - len(ordered)
        )
        if not removed:
            return 0
        replacement = Sdf.TokenListOp()
        replacement.explicitItems = explicit
        replacement.prependedItems = prepended
        replacement.appendedItems = appended
        replacement.deletedItems = deleted
        replacement.orderedItems = ordered
        if explicit or prepended or appended or deleted or ordered:
            prim.SetMetadata("apiSchemas", replacement)
        else:
            prim.ClearMetadata("apiSchemas")
        return removed
    if isinstance(api_schemas, (list, tuple)):
        current = [str(value) for value in api_schemas]
        kept = _filter_physics_api_schemas(current)
        removed = len(current) - len(kept)
        if not removed:
            return 0
        if kept:
            prim.SetMetadata("apiSchemas", kept)
        else:
            prim.ClearMetadata("apiSchemas")
        return removed
    return 0


def _filter_physics_api_schemas(values: Any) -> list[str]:
    return [str(value) for value in values or [] if str(value) not in PHYSICS_API_SCHEMA_NAMES]


def _is_physics_property_name(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix) for prefix in PHYSICS_PROPERTY_PREFIXES)
