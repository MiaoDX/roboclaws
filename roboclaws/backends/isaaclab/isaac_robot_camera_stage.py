"""Isaac Lab backend runtime support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.backends.isaaclab.isaac_camera_geometry import (
    ISAAC_RBY1M_HEAD_CAMERA_PRIM,
    RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM,
    RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG,
    RBY1M_HEAD_CAMERA_ZERO_POSITION_M,
    RBY1M_HEAD_PITCH_PIVOT_M,
)


@dataclass(frozen=True)
class IsaacRobotCameraStageHooks:
    dict_value: Callable[..., dict[str, Any]]
    has_xy: Callable[..., bool]
    horizontal_aperture_from_lens: Callable[..., float]
    matrix4d_rowmajor: Callable[..., list[float]]
    optional_float: Callable[..., float | None]
    robot_pose_yaw_deg: Callable[..., float | None]
    static_head_camera_pose_for_pitch: Callable[..., tuple[Any, Any]]
    tensor_first_vec3: Callable[..., list[float]]
    usd_attr_float: Callable[..., float | None]
    usd_camera_fov_metadata: Callable[..., dict[str, float]]
    usd_vec: Callable[..., list[float] | None]


def ensure_rby1m_robot_on_stage(
    *,
    stage_utils: Any,
    robot_import: dict[str, Any],
) -> dict[str, Any]:
    if robot_import.get("status") != "imported":
        return {
            "schema": "isaac_rby1m_robot_stage_reference_v1",
            "status": "not_available",
            "head_camera_prim_exists": False,
            "reason": robot_import.get("status") or "robot_not_requested",
        }
    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        raise RuntimeError("Isaac stage utils do not expose get_current_stage")
    stage = get_current_stage()
    if stage is None:
        raise RuntimeError("Isaac robot import has no current USD stage")
    from pxr import UsdGeom

    robot_prim_path = str(robot_import.get("stage_prim_path") or "/World/robot_0")
    head_camera_prim_path = str(
        robot_import.get("head_camera_prim_path") or ISAAC_RBY1M_HEAD_CAMERA_PRIM
    )
    robot_usd_path = Path(str(robot_import.get("usd_path") or ""))
    if not robot_usd_path.is_file():
        return {
            "schema": "isaac_rby1m_robot_stage_reference_v1",
            "status": "blocked",
            "head_camera_prim_exists": False,
            "robot_prim_path": robot_prim_path,
            "head_camera_prim_path": head_camera_prim_path,
            "reason": f"missing imported robot USD: {robot_usd_path}",
        }
    robot_prim = stage.GetPrimAtPath(robot_prim_path)
    if not robot_prim or not robot_prim.IsValid():
        robot_prim = UsdGeom.Xform.Define(stage, robot_prim_path).GetPrim()
        robot_prim.GetReferences().AddReference(str(robot_usd_path))
    head_camera_prim = stage.GetPrimAtPath(head_camera_prim_path)
    return {
        "schema": "isaac_rby1m_robot_stage_reference_v1",
        "status": "referenced",
        "robot_prim_path": robot_prim_path,
        "head_camera_prim_path": head_camera_prim_path,
        "robot_usd_path": str(robot_usd_path),
        "head_camera_prim_exists": bool(head_camera_prim and head_camera_prim.IsValid()),
    }


def position_robot_for_head_camera_view(
    *,
    stage_utils: Any,
    scene_bounds: dict[str, list[float]] | None,
    semantic_pose_state: dict[str, Any] | None = None,
    hooks: IsaacRobotCameraStageHooks,
) -> dict[str, Any]:
    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    if not callable(get_current_stage):
        return {
            "schema": "isaac_robot_head_camera_pose_application_v1",
            "status": "missing_stage_api",
        }
    stage = get_current_stage()
    if stage is None:
        return {"schema": "isaac_robot_head_camera_pose_application_v1", "status": "missing_stage"}
    robot_prim = stage.GetPrimAtPath("/World/robot_0")
    if not robot_prim or not robot_prim.IsValid():
        return {
            "schema": "isaac_robot_head_camera_pose_application_v1",
            "status": "missing_robot_prim",
            "robot_prim_path": "/World/robot_0",
        }
    from pxr import Gf, UsdGeom

    pose = hooks.dict_value(hooks.dict_value(semantic_pose_state).get("robot_pose"))
    pose_source = str(pose.get("pose_source") or "")
    if hooks.has_xy(pose):
        position = (
            float(pose["x"]),
            float(pose["y"]),
            float(pose.get("z", 0.0)),
        )
        position_source = "semantic_pose_state.robot_pose"
    elif scene_bounds:
        center = scene_bounds["center"]
        size = scene_bounds["size"]
        span_x = max(float(size[0]), 1.5)
        span_y = max(float(size[1]), 1.5)
        floor_z = float(scene_bounds["min"][2])
        position = (float(center[0]) - span_x * 0.35, float(center[1]) - span_y * 0.55, floor_z)
        position_source = "scene_bounds_fallback"
    else:
        position = (1.35, -1.35, 0.0)
        position_source = "static_fallback"
    xform = UsdGeom.XformCommonAPI(robot_prim)
    xform.SetTranslate(Gf.Vec3d(*position))
    yaw_deg = hooks.robot_pose_yaw_deg(pose)
    if yaw_deg is not None:
        xform.SetRotate(Gf.Vec3f(0.0, 0.0, yaw_deg))
    head_pitch = hooks.optional_float(pose.get("head_pitch"))
    head_pitch_application = apply_static_head_camera_pitch(
        stage=stage,
        head_pitch=head_pitch,
        hooks=hooks,
    )
    return {
        "schema": "isaac_robot_head_camera_pose_application_v1",
        "status": "applied",
        "robot_prim_path": "/World/robot_0",
        "position": [float(value) for value in position],
        "position_source": position_source,
        "pose_source": pose_source,
        "yaw_deg": yaw_deg,
        "yaw_source": "semantic_pose_state.robot_pose.theta_or_yaw_deg"
        if yaw_deg is not None
        else "not_available",
        "head_pitch": head_pitch,
        "head_pitch_source": str(pose.get("head_pitch_source") or ""),
        "head_pitch_applied": head_pitch_application.get("status") == "applied",
        "head_pitch_application": head_pitch_application,
        "head_pitch_note": static_head_pitch_note(head_pitch_application),
    }


def apply_static_head_camera_pitch(
    *,
    stage: Any,
    head_pitch: float | None,
    hooks: IsaacRobotCameraStageHooks,
) -> dict[str, Any]:
    if head_pitch is None:
        return {
            "schema": "isaac_static_head_camera_pitch_application_v1",
            "status": "not_requested",
            "head_camera_prim_path": ISAAC_RBY1M_HEAD_CAMERA_PRIM,
        }
    head_camera_prim = stage.GetPrimAtPath(ISAAC_RBY1M_HEAD_CAMERA_PRIM)
    if not head_camera_prim or not head_camera_prim.IsValid():
        return {
            "schema": "isaac_static_head_camera_pitch_application_v1",
            "status": "missing_head_camera_prim",
            "head_camera_prim_path": ISAAC_RBY1M_HEAD_CAMERA_PRIM,
            "head_pitch_rad": float(head_pitch),
        }
    from pxr import Gf, UsdGeom

    position, quat = hooks.static_head_camera_pose_for_pitch(float(head_pitch))
    xform = UsdGeom.Xformable(head_camera_prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    xform.AddOrientOp().Set(Gf.Quatf(quat[0], Gf.Vec3f(*quat[1:])))
    xform.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))
    return {
        "schema": "isaac_static_head_camera_pitch_application_v1",
        "status": "applied",
        "head_camera_prim_path": ISAAC_RBY1M_HEAD_CAMERA_PRIM,
        "head_pitch_rad": round(float(head_pitch), 6),
        "head_pitch_axis": [0.0, 1.0, 0.0],
        "head_pitch_joint": "head_1",
        "head_pitch_pivot_m": [round(float(value), 6) for value in RBY1M_HEAD_PITCH_PIVOT_M],
        "zero_position_m": [round(float(value), 6) for value in RBY1M_HEAD_CAMERA_ZERO_POSITION_M],
        "applied_position_m": [round(float(value), 6) for value in position],
        "applied_quat_wxyz": [round(float(value), 6) for value in quat],
        "pose_source": "static_usd_head_camera_local_transform_with_mujoco_head_1_pitch",
    }


def static_head_pitch_note(head_pitch_application: dict[str, Any]) -> str:
    if head_pitch_application.get("status") == "applied":
        return (
            "Isaac currently uses a static visual robot USD, so it cannot drive the "
            "articulated head_1 joint. For robot-view parity it rewrites the mounted "
            "head_camera prim local transform with the same Y-axis head pitch used by "
            "MuJoCo before FPV capture."
        )
    return (
        "The current static Isaac robot USD has a mounted head_camera prim but could not "
        "apply a static head pitch correction for this capture; inspect "
        "head_pitch_application before treating FPV as articulated parity."
    )


def usd_camera_diagnostics(
    *,
    stage_utils: Any,
    prim_path: str,
    view_name: str,
    width: int,
    height: int,
    robot_pose_application: dict[str, Any] | None = None,
    lens_application: dict[str, Any] | None = None,
    hooks: IsaacRobotCameraStageHooks,
) -> dict[str, Any]:
    try:
        stage = stage_utils.get_current_stage()
        prim = stage.GetPrimAtPath(prim_path) if stage is not None else None
        if not prim or not prim.IsValid():
            return {
                "schema": "isaac_usd_camera_diagnostics_v1",
                "status": "missing_camera_prim",
                "view_name": view_name,
                "prim_path": prim_path,
            }
        from pxr import UsdGeom

        camera = UsdGeom.Camera(prim)
        xform = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0.0)
        focal_length = hooks.usd_attr_float(camera.GetFocalLengthAttr())
        horizontal_aperture = hooks.usd_attr_float(camera.GetHorizontalApertureAttr())
        fov = hooks.usd_camera_fov_metadata(
            focal_length=focal_length,
            horizontal_aperture=horizontal_aperture,
            width=width,
            height=height,
        )
        return {
            "schema": "isaac_usd_camera_diagnostics_v1",
            "status": "ready",
            "view_name": view_name,
            "camera_type": "usd_camera_prim",
            "prim_path": prim_path,
            "world_matrix_rowmajor": hooks.matrix4d_rowmajor(xform),
            "focal_length_mm": focal_length,
            "horizontal_aperture_mm": horizontal_aperture,
            **fov,
            "clipping_range": hooks.usd_vec(camera.GetClippingRangeAttr()),
            "render_resolution": {"width": width, "height": height},
            "robot_pose_stage_application": hooks.dict_value(robot_pose_application),
            "lens_application": hooks.dict_value(lens_application),
        }
    except Exception as exc:
        return {
            "schema": "isaac_usd_camera_diagnostics_v1",
            "status": "unavailable",
            "view_name": view_name,
            "prim_path": prim_path,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def isaac_eye_target_camera_diagnostics(
    *,
    view_name: str,
    positions: Any,
    targets: Any,
    width: int,
    height: int,
    camera_basis: str = "scene_bounds_eye_target",
    hooks: IsaacRobotCameraStageHooks,
) -> dict[str, Any]:
    focal_length = RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM
    horizontal_aperture = hooks.horizontal_aperture_from_lens(
        {"vertical_fov_deg": RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG},
        width=width,
        height=height,
        focal_length=focal_length,
    )
    fov = hooks.usd_camera_fov_metadata(
        focal_length=focal_length,
        horizontal_aperture=horizontal_aperture,
        width=width,
        height=height,
    )
    return {
        "schema": "isaac_eye_target_camera_diagnostics_v1",
        "status": "ready",
        "view_name": view_name,
        "camera_type": "eye_target_scene_camera",
        "camera_basis": camera_basis,
        "eye": hooks.tensor_first_vec3(positions),
        "target": hooks.tensor_first_vec3(targets),
        "focal_length_mm": focal_length,
        "horizontal_aperture_mm": horizontal_aperture,
        **fov,
        "render_resolution": {"width": width, "height": height},
    }


def configure_rby1m_head_camera_lens(
    *,
    stage_utils: Any,
    width: int,
    height: int,
    hooks: IsaacRobotCameraStageHooks,
) -> dict[str, Any]:
    try:
        from pxr import UsdGeom

        stage = stage_utils.get_current_stage()
        prim = stage.GetPrimAtPath(ISAAC_RBY1M_HEAD_CAMERA_PRIM) if stage is not None else None
        if not prim or not prim.IsValid():
            return {
                "schema": "isaac_rby1m_head_camera_lens_application_v1",
                "status": "missing_head_camera_prim",
                "head_camera_prim_path": ISAAC_RBY1M_HEAD_CAMERA_PRIM,
            }
        focal_length = RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM
        horizontal_aperture = hooks.horizontal_aperture_from_lens(
            {"vertical_fov_deg": RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG},
            width=width,
            height=height,
            focal_length=focal_length,
        )
        camera = UsdGeom.Camera(prim)
        camera.CreateFocalLengthAttr(focal_length).Set(focal_length)
        camera.CreateHorizontalApertureAttr(horizontal_aperture).Set(horizontal_aperture)
        return {
            "schema": "isaac_rby1m_head_camera_lens_application_v1",
            "status": "applied",
            "head_camera_prim_path": ISAAC_RBY1M_HEAD_CAMERA_PRIM,
            "source_camera_name": "robot_0/head_camera",
            "source_vertical_fov_deg": RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG,
            "focal_length_mm": round(focal_length, 6),
            "horizontal_aperture_mm": round(horizontal_aperture, 6),
            "render_resolution": {"width": int(width), "height": int(height)},
        }
    except Exception as exc:
        return {
            "schema": "isaac_rby1m_head_camera_lens_application_v1",
            "status": "unavailable",
            "head_camera_prim_path": ISAAC_RBY1M_HEAD_CAMERA_PRIM,
            "reason": f"{type(exc).__name__}: {exc}",
        }
