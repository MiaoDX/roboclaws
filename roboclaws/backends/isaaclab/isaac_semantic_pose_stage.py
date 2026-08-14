"""Isaac Lab backend runtime support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class IsaacSemanticPoseStageHooks:
    dict_value: Callable[..., Any]
    set_usd_xform_translate: Callable[..., Any]
    semantic_pose_target_position: Callable[..., Any]
    vec3: Callable[..., Any]
    world_position_to_parent_local_translate: Callable[..., Any]


def apply_semantic_pose_state_to_stage(
    *,
    stage_utils: Any,
    semantic_pose_state: dict[str, Any] | None,
    hooks: IsaacSemanticPoseStageHooks,
) -> dict[str, Any]:
    pose_state = hooks.dict_value(semantic_pose_state)
    if not pose_state:
        return {
            "schema": "isaac_semantic_pose_stage_application_v1",
            "status": "not_requested",
            "applied_object_count": 0,
            "failed_object_count": 0,
            "rendered_to_usd": False,
        }
    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        raise RuntimeError("Isaac stage utils do not expose get_current_stage")
    stage = get_current_stage()
    if stage is None:
        raise RuntimeError("Isaac semantic-pose rerender has no current USD stage")
    from pxr import Gf, UsdGeom

    object_poses = hooks.dict_value(pose_state.get("object_poses"))
    receptacle_index = hooks.dict_value(pose_state.get("receptacle_index"))
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for object_id, raw_pose in object_poses.items():
        _apply_object_semantic_pose(
            stage=stage,
            UsdGeom=UsdGeom,
            Gf=Gf,
            object_id=str(object_id),
            raw_pose=raw_pose,
            receptacle_index=receptacle_index,
            applied=applied,
            failed=failed,
            hooks=hooks,
        )
    return {
        "schema": "isaac_semantic_pose_stage_application_v1",
        "status": "applied" if applied and not failed else ("partial" if applied else "blocked"),
        "applied_object_count": len(applied),
        "failed_object_count": len(failed),
        "applied_objects": applied,
        "failed_objects": failed,
        "rendered_to_usd": bool(applied) and not failed,
    }


def _apply_object_semantic_pose(
    *,
    stage: Any,
    UsdGeom: Any,
    Gf: Any,
    object_id: str,
    raw_pose: Any,
    receptacle_index: dict[str, Any],
    applied: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    hooks: IsaacSemanticPoseStageHooks,
) -> None:
    pose = hooks.dict_value(raw_pose)
    object_prim_path = str(pose.get("usd_prim_path") or "")
    support_id = str(pose.get("support_receptacle_id") or "")
    if not object_prim_path or pose.get("attached_to_robot") is True:
        return
    object_prim = stage.GetPrimAtPath(object_prim_path)
    if not object_prim or not object_prim.IsValid():
        failed.append({"object_id": object_id, "reason": "missing_object_prim"})
        return
    target = hooks.semantic_pose_target_position(
        support_id=support_id,
        receptacle_index=receptacle_index,
        fallback_pose=pose,
    )
    if target is None:
        failed.append({"object_id": object_id, "reason": "missing_target_pose"})
        return
    _apply_object_translate(
        UsdGeom=UsdGeom,
        Gf=Gf,
        object_id=object_id,
        object_prim=object_prim,
        object_prim_path=object_prim_path,
        support_id=support_id,
        target=target,
        applied=applied,
        failed=failed,
        hooks=hooks,
    )


def _apply_object_translate(
    *,
    UsdGeom: Any,
    Gf: Any,
    object_id: str,
    object_prim: Any,
    object_prim_path: str,
    support_id: str,
    target: tuple[float, float, float],
    applied: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    hooks: IsaacSemanticPoseStageHooks,
) -> None:
    try:
        local_translate = hooks.world_position_to_parent_local_translate(
            UsdGeom=UsdGeom,
            prim=object_prim,
            world_position=target,
        )
    except RuntimeError as exc:
        failed.append(
            {
                "object_id": object_id,
                "reason": "parent_local_transform_failed",
                "detail": str(exc),
            }
        )
        return
    try:
        translate_application = hooks.set_usd_xform_translate(
            UsdGeom=UsdGeom,
            Gf=Gf,
            prim=object_prim,
            translate=local_translate,
        )
    except RuntimeError as exc:
        failed.append(
            {
                "object_id": object_id,
                "reason": "translate_authoring_failed",
                "detail": str(exc),
            }
        )
        return
    applied.append(
        {
            "object_id": object_id,
            "object_usd_prim_path": object_prim_path,
            "support_receptacle_id": support_id,
            "target_position": list(target),
            "authored_translate": list(local_translate),
            "authored_translate_frame": "parent_local",
            "translate_application_method": translate_application.get("method"),
            "authored_xform_op": translate_application.get("xform_op"),
        }
    )


def world_position_to_parent_local_translate(
    *,
    UsdGeom: Any,
    prim: Any,
    world_position: tuple[float, float, float],
) -> tuple[float, float, float]:
    parent = prim.GetParent() if hasattr(prim, "GetParent") else None
    if parent is None or not parent:
        return tuple(float(value) for value in world_position)
    try:
        parent_world = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(0.0)
        world_to_parent = parent_world.GetInverse()
        local = world_to_parent.Transform(tuple(float(value) for value in world_position))
        return (float(local[0]), float(local[1]), float(local[2]))
    except Exception as exc:
        raise RuntimeError(
            "could not convert world semantic pose into parent-local USD frame"
        ) from exc


def semantic_pose_target_position(
    *,
    support_id: str,
    receptacle_index: dict[str, Any],
    fallback_pose: dict[str, Any],
    dict_value: Callable[..., Any],
    vec3: Callable[..., Any],
) -> tuple[float, float, float] | None:
    exact_position = vec3(fallback_pose.get("position"))
    if exact_position is not None:
        return (exact_position[0], exact_position[1], exact_position[2])
    support = dict_value(receptacle_index.get(support_id))
    pose = dict_value(support.get("support_pose")) or fallback_pose
    try:
        x = float(pose.get("x"))
        y = float(pose.get("y"))
    except (TypeError, ValueError):
        return None
    try:
        z = float(pose.get("z") or 0.0)
    except (TypeError, ValueError):
        z = 0.0
    return (x, y, z + 0.18)
