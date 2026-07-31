#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from roboclaws.core import nvidia_eula as eula

SCHEMA = "isaac_rby1m_robot_usd_import_v1"
DEFAULT_OUTPUT_USD_PATH = Path("output/isaaclab/robots/rby1m/rby1m_holobase_isaac.usda")
DEFAULT_RAW_USD_NAME = "rby1m_holobase_isaac_raw.usd"
DEFAULT_SUMMARY_NAME = "rby1m_holobase_isaac.import_summary.json"
ROBOT_PRIM_PATH = "/robot_0"
HEAD_LINK_NAME = "link_head_2"
STAGE_ROBOT_PRIM_PATH = "/World/robot_0"
STAGE_HEAD_CAMERA_PRIM_PATH = "/World/robot_0/head_camera"
ASSET_HEAD_CAMERA_PRIM_PATH = "/robot_0/head_camera"
HEAD_CAMERA_POSITION_M = (0.05, 0.0, 0.05)
HEAD_CAMERA_QUAT_WXYZ = (0.5, 0.5, -0.5, -0.5)
HEAD_CAMERA_FOCAL_LENGTH_MM = 24.0
HEAD_CAMERA_VERTICAL_FOV_DEG = 45.0
HEAD_CAMERA_RENDER_ASPECT = 540.0 / 360.0
HEAD_CAMERA_HORIZONTAL_APERTURE_MM = (
    2.0
    * HEAD_CAMERA_FOCAL_LENGTH_MM
    * math.tan(math.radians(HEAD_CAMERA_VERTICAL_FOV_DEG) / 2.0)
    * HEAD_CAMERA_RENDER_ASPECT
)


@dataclass(frozen=True)
class Rby1mRobotUsdRequest:
    urdf_path: Path | None = None
    output_usd_path: Path = DEFAULT_OUTPUT_USD_PATH
    raw_usd_path: Path | None = None
    summary_output: Path | None = None
    robot_name: str = "rby1m"
    head_link_name: str = HEAD_LINK_NAME
    static_only: bool = False
    force: bool = False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    static_only = "--static-only" in argv
    if not static_only and not eula.accepted():
        parser.error(eula.required_message("Isaac robot USD import", supports_flag=False))
    if not static_only:
        from isaaclab.app import AppLauncher

        AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args(argv)
    if not static_only and hasattr(args, "headless") and args.headless is False:
        args.headless = True

    if not static_only:
        AppLauncher(args)
    try:
        summary = import_rby1m_robot_usd(_request_from_cli_args(args))
        print(json.dumps(summary, sort_keys=True), flush=True)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0 if summary["status"] == "ready" else 2)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "ready" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert the MolmoSpaces RBY1M Isaac URDF into a wrapped USD robot asset."
    )
    parser.add_argument("--urdf-path", type=Path)
    parser.add_argument("--output-usd-path", type=Path, default=DEFAULT_OUTPUT_USD_PATH)
    parser.add_argument("--raw-usd-path", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--robot-name", default="rby1m")
    parser.add_argument("--head-link-name", default=HEAD_LINK_NAME)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help=(
            "Author the visual USD fallback without launching Isaac Sim/Lab. "
            "This requires pxr but not AppLauncher or the Isaac URDF importer plugin."
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser


def _request_from_cli_args(args: argparse.Namespace) -> Rby1mRobotUsdRequest:
    return Rby1mRobotUsdRequest(
        urdf_path=args.urdf_path,
        output_usd_path=args.output_usd_path,
        raw_usd_path=args.raw_usd_path,
        summary_output=args.summary_output,
        robot_name=args.robot_name,
        head_link_name=args.head_link_name,
        static_only=args.static_only,
        force=args.force,
    )


def import_rby1m_robot_usd(request: Rby1mRobotUsdRequest) -> dict[str, Any]:
    output_usd_path = _resolve_repo_path(request.output_usd_path)
    raw_usd_path = _resolve_repo_path(
        request.raw_usd_path or output_usd_path.with_name(DEFAULT_RAW_USD_NAME)
    )
    summary_path = _resolve_repo_path(
        request.summary_output or output_usd_path.with_name(DEFAULT_SUMMARY_NAME)
    )
    urdf_path = (
        _resolve_repo_path(request.urdf_path) if request.urdf_path else _find_rby1m_isaac_urdf()
    )
    if urdf_path is None or not urdf_path.is_file():
        summary = _base_summary(
            status="blocked",
            urdf_path=urdf_path,
            output_usd_path=output_usd_path,
            raw_usd_path=raw_usd_path,
            summary_path=summary_path,
            blockers=["RBY1M Isaac URDF not found."],
            request=request,
        )
        _write_summary(summary_path, summary)
        return summary

    output_usd_path.parent.mkdir(parents=True, exist_ok=True)
    raw_usd_path.parent.mkdir(parents=True, exist_ok=True)
    converter_status: dict[str, Any]
    if request.static_only:
        converter_status = {
            "schema": "isaac_rby1m_urdf_converter_attempt_v1",
            "status": "skipped",
            "converter": "isaaclab.sim.converters.UrdfConverter",
            "raw_usd_path": str(raw_usd_path),
            "blockers": [],
            "reason": "--static-only requested; AppLauncher and URDF converter were not used.",
        }
        static_status = _write_static_visual_robot_usd(
            urdf_path=urdf_path,
            output_usd_path=raw_usd_path,
        )
        converter_status["fallback"] = static_status
        import_method = "urdf_visual_static_usd_fallback"
    else:
        converter_status = _try_isaac_urdf_converter(
            urdf_path=urdf_path,
            raw_usd_path=raw_usd_path,
            force=request.force,
        )
        if converter_status["status"] == "ready":
            raw_usd_path = Path(str(converter_status["raw_usd_path"]))
            import_method = "isaaclab_urdf_converter"
        else:
            static_status = _write_static_visual_robot_usd(
                urdf_path=urdf_path,
                output_usd_path=raw_usd_path,
            )
            converter_status["fallback"] = static_status
            import_method = "urdf_visual_static_usd_fallback"
    wrapper_info = _write_wrapped_robot_stage(
        raw_usd_path=raw_usd_path,
        output_usd_path=output_usd_path,
        head_link_name=request.head_link_name,
        urdf_path=urdf_path,
    )
    urdf_info = _inspect_urdf(urdf_path, required_joints=_required_joints())
    blockers: list[str] = []
    if not raw_usd_path.is_file():
        blockers.append(f"raw converted USD is missing: {raw_usd_path}")
    if not output_usd_path.is_file():
        blockers.append(f"wrapped robot USD is missing: {output_usd_path}")
    if not wrapper_info["head_camera_prim_exists"]:
        blockers.append(f"head camera prim is missing: {ASSET_HEAD_CAMERA_PRIM_PATH}")
    missing_joints = urdf_info.get("missing_required_joints") or []
    if missing_joints:
        blockers.append(f"URDF missing required joints: {', '.join(missing_joints)}")

    summary = {
        **_base_summary(
            status="ready" if not blockers else "blocked",
            urdf_path=urdf_path,
            output_usd_path=output_usd_path,
            raw_usd_path=raw_usd_path,
            summary_path=summary_path,
            blockers=blockers,
            request=request,
        ),
        "import_method": import_method,
        "converter": converter_status,
        "urdf": urdf_info,
        "wrapper_stage": wrapper_info,
        "head_camera": _head_camera_summary(),
    }
    _write_summary(summary_path, summary)
    return summary


def _base_summary(
    *,
    status: str,
    urdf_path: Path | None,
    output_usd_path: Path,
    raw_usd_path: Path,
    summary_path: Path,
    blockers: list[str],
    request: Rby1mRobotUsdRequest,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": status,
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "robot_name": request.robot_name,
        "importer": "isaaclab.sim.converters.UrdfConverter_or_static_urdf_visual_fallback",
        "source_urdf": str(urdf_path) if urdf_path else "",
        "raw_usd_path": str(raw_usd_path),
        "output_usd_path": str(output_usd_path),
        "summary_path": str(summary_path),
        "asset_robot_prim_path": ROBOT_PRIM_PATH,
        "stage_robot_prim_path": STAGE_ROBOT_PRIM_PATH,
        "asset_head_camera_prim_path": ASSET_HEAD_CAMERA_PRIM_PATH,
        "stage_head_camera_prim_path": STAGE_HEAD_CAMERA_PRIM_PATH,
        "head_link_name": request.head_link_name,
        "static_only": request.static_only,
        "blockers": blockers,
    }


def _try_isaac_urdf_converter(
    *,
    urdf_path: Path,
    raw_usd_path: Path,
    force: bool,
) -> dict[str, Any]:
    try:
        from isaaclab.sim.converters import UrdfConverter, UrdfConverterCfg

        converter_cfg = UrdfConverterCfg(
            asset_path=str(urdf_path),
            usd_dir=str(raw_usd_path.parent),
            usd_file_name=raw_usd_path.name,
            fix_base=False,
            merge_fixed_joints=False,
            force_usd_conversion=bool(force or not raw_usd_path.is_file()),
            joint_drive=UrdfConverterCfg.JointDriveCfg(
                gains=UrdfConverterCfg.JointDriveCfg.PDGainsCfg(stiffness=100.0, damping=1.0),
                target_type="position",
            ),
        )
        converter = UrdfConverter(converter_cfg)
        converted_path = Path(str(converter.usd_path))
        return {
            "schema": "isaac_rby1m_urdf_converter_attempt_v1",
            "status": "ready" if converted_path.is_file() else "blocked",
            "converter": "isaaclab.sim.converters.UrdfConverter",
            "raw_usd_path": str(converted_path),
            "blockers": [] if converted_path.is_file() else [f"missing USD: {converted_path}"],
        }
    except Exception as exc:
        return {
            "schema": "isaac_rby1m_urdf_converter_attempt_v1",
            "status": "blocked",
            "converter": "isaaclab.sim.converters.UrdfConverter",
            "raw_usd_path": str(raw_usd_path),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "blockers": [f"Isaac URDF converter failed: {type(exc).__name__}: {exc}"],
        }


def _write_static_visual_robot_usd(
    *,
    urdf_path: Path,
    output_usd_path: Path,
) -> dict[str, Any]:
    from pxr import Usd, UsdGeom

    robot = _parse_urdf_tree(urdf_path)
    stage = Usd.Stage.CreateNew(str(output_usd_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(stage, ROBOT_PRIM_PATH)
    stage.SetDefaultPrim(root.GetPrim())
    mesh_count = 0
    missing_meshes: list[str] = []
    unsupported_meshes: list[str] = []
    for link_name, transform in robot["link_transforms"].items():
        link = UsdGeom.Xform.Define(stage, f"{ROBOT_PRIM_PATH}/links/{_usd_safe_name(link_name)}")
        _set_xform_matrix(link.GetPrim(), transform)
        for index, visual in enumerate(robot["visuals"].get(link_name, []), start=1):
            mesh_path = Path(str(visual.get("mesh_path") or ""))
            if not mesh_path.is_file():
                missing_meshes.append(str(mesh_path))
                continue
            if mesh_path.suffix.lower() != ".obj":
                unsupported_meshes.append(str(mesh_path))
                continue
            mesh_xform = UsdGeom.Xform.Define(
                stage,
                f"{ROBOT_PRIM_PATH}/links/{_usd_safe_name(link_name)}/visual_{index:02d}",
            )
            _set_xform_matrix(mesh_xform.GetPrim(), visual["origin_matrix"])
            _define_obj_mesh(
                stage=stage,
                mesh_path=mesh_path,
                prim_path=(
                    f"{ROBOT_PRIM_PATH}/links/{_usd_safe_name(link_name)}/visual_{index:02d}/mesh"
                ),
            )
            mesh_count += 1
    stage.GetRootLayer().Save()
    return {
        "schema": "isaac_rby1m_static_visual_usd_import_v1",
        "status": "ready" if output_usd_path.is_file() and mesh_count else "blocked",
        "output_usd_path": str(output_usd_path),
        "mesh_reference_count": mesh_count,
        "missing_mesh_count": len(missing_meshes),
        "missing_meshes": missing_meshes[:20],
        "unsupported_mesh_count": len(unsupported_meshes),
        "unsupported_meshes": unsupported_meshes[:20],
        "note": (
            "Fallback authored a static visual USD from URDF links and mesh references "
            "because the Isaac URDF converter plugin was unavailable. This still imports "
            "the real RBY1M visual asset and mounted head_camera, but does not claim "
            "articulation or physics parity."
        ),
    }


def _write_wrapped_robot_stage(
    *,
    raw_usd_path: Path,
    output_usd_path: Path,
    head_link_name: str,
    urdf_path: Path,
) -> dict[str, Any]:
    from pxr import Gf, Sdf, Usd, UsdGeom

    stage = Usd.Stage.CreateNew(str(output_usd_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    robot = UsdGeom.Xform.Define(stage, ROBOT_PRIM_PATH)
    stage.SetDefaultPrim(robot.GetPrim())

    model = UsdGeom.Xform.Define(stage, f"{ROBOT_PRIM_PATH}/model")
    model.GetPrim().GetReferences().AddReference(_reference_path(raw_usd_path, output_usd_path))

    camera = UsdGeom.Camera.Define(stage, ASSET_HEAD_CAMERA_PRIM_PATH)
    camera.CreateFocalLengthAttr(HEAD_CAMERA_FOCAL_LENGTH_MM)
    camera.CreateHorizontalApertureAttr(HEAD_CAMERA_HORIZONTAL_APERTURE_MM)
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.05, 100.0))
    camera_position, camera_quat = _head_camera_pose_from_urdf(urdf_path, head_link_name)
    _set_xform_quat(
        camera.GetPrim(),
        position=camera_position,
        quat_wxyz=camera_quat,
    )
    camera.GetPrim().CreateAttribute("roboclaws:mountLinkName", Sdf.ValueTypeNames.String).Set(
        head_link_name
    )
    camera.GetPrim().CreateAttribute("roboclaws:sourceCameraName", Sdf.ValueTypeNames.String).Set(
        "robot_0/head_camera"
    )
    camera.GetPrim().CreateAttribute("roboclaws:sourceSimulator", Sdf.ValueTypeNames.String).Set(
        "mujoco"
    )

    stage.GetRootLayer().Save()
    verify_stage = Usd.Stage.Open(str(output_usd_path))
    head_camera_prim = verify_stage.GetPrimAtPath(ASSET_HEAD_CAMERA_PRIM_PATH)
    head_link_candidates = _find_prim_name_candidates(raw_usd_path, head_link_name)
    return {
        "schema": "isaac_rby1m_robot_usd_wrapper_stage_v1",
        "output_usd_path": str(output_usd_path),
        "raw_usd_path": str(raw_usd_path),
        "default_prim": ROBOT_PRIM_PATH,
        "head_camera_prim_exists": bool(head_camera_prim and head_camera_prim.IsValid()),
        "head_camera_prim_path": ASSET_HEAD_CAMERA_PRIM_PATH,
        "stage_head_camera_prim_path": STAGE_HEAD_CAMERA_PRIM_PATH,
        "head_link_name": head_link_name,
        "raw_head_link_prim_candidates": head_link_candidates,
        "raw_head_link_candidate_count": len(head_link_candidates),
        "head_camera_pose_source": "urdf_default_head_link_pose_plus_mujoco_head_camera_local",
        "head_camera_position_m": list(camera_position),
        "head_camera_quat_wxyz": list(camera_quat),
    }


def _set_xform_quat(
    prim: Any,
    *,
    position: tuple[float, float, float],
    quat_wxyz: tuple[float, float, float, float],
) -> None:
    from pxr import Gf, UsdGeom

    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*position))
    xform.AddOrientOp().Set(Gf.Quatf(quat_wxyz[0], Gf.Vec3f(*quat_wxyz[1:])))
    xform.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))


def _set_xform_matrix(prim: Any, matrix: list[list[float]]) -> None:
    from pxr import Gf, UsdGeom

    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    usd_matrix = Gf.Matrix4d(1.0)
    for row in range(4):
        for column in range(4):
            usd_matrix[row][column] = float(matrix[row][column])
    xform.AddTransformOp().Set(usd_matrix)


def _define_obj_mesh(*, stage: Any, mesh_path: Path, prim_path: str) -> None:
    from pxr import Gf, UsdGeom

    vertices: list[tuple[float, float, float]] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    for raw_line in mesh_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif line.startswith("f "):
            indices: list[int] = []
            for item in line.split()[1:]:
                index_text = item.split("/", 1)[0]
                if not index_text:
                    continue
                index = int(index_text)
                if index < 0:
                    index = len(vertices) + index
                else:
                    index -= 1
                indices.append(index)
            if len(indices) >= 3:
                face_vertex_counts.append(len(indices))
                face_vertex_indices.extend(indices)
    mesh = UsdGeom.Mesh.Define(stage, prim_path)
    mesh.CreatePointsAttr([Gf.Vec3f(*item) for item in vertices])
    mesh.CreateFaceVertexCountsAttr(face_vertex_counts)
    mesh.CreateFaceVertexIndicesAttr(face_vertex_indices)


def _parse_urdf_tree(urdf_path: Path) -> dict[str, Any]:
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    link_names = _urdf_link_names(root)
    child_to_parent = _urdf_child_to_parent(root)
    return {
        "link_transforms": _urdf_link_transforms(link_names, child_to_parent),
        "visuals": _urdf_visuals_by_link(root, urdf_path=urdf_path, link_names=link_names),
        "child_to_parent": child_to_parent,
    }


def _urdf_link_names(root: ET.Element) -> list[str]:
    return [str(item.attrib.get("name") or "") for item in root.findall("link")]


def _urdf_visuals_by_link(
    root: ET.Element,
    *,
    urdf_path: Path,
    link_names: list[str],
) -> dict[str, list[dict[str, Any]]]:
    visuals: dict[str, list[dict[str, Any]]] = {name: [] for name in link_names if name}
    for link in root.findall("link"):
        link_name = str(link.attrib.get("name") or "")
        for visual in link.findall("visual"):
            mesh = visual.find("geometry/mesh")
            if mesh is None:
                continue
            filename = str(mesh.attrib.get("filename") or "")
            if not filename:
                continue
            origin = visual.find("origin")
            visuals.setdefault(link_name, []).append(
                {
                    "mesh_path": (urdf_path.parent / filename).resolve(),
                    "origin_matrix": _origin_matrix(origin),
                }
            )
    return visuals


def _urdf_child_to_parent(root: ET.Element) -> dict[str, tuple[str, list[list[float]]]]:
    child_to_parent: dict[str, tuple[str, list[list[float]]]] = {}
    for joint in root.findall("joint"):
        parent = joint.find("parent")
        child = joint.find("child")
        if parent is None or child is None:
            continue
        parent_name = str(parent.attrib.get("link") or "")
        child_name = str(child.attrib.get("link") or "")
        if not parent_name or not child_name:
            continue
        child_to_parent[child_name] = (parent_name, _origin_matrix(joint.find("origin")))
    return child_to_parent


def _urdf_link_transforms(
    link_names: list[str],
    child_to_parent: dict[str, tuple[str, list[list[float]]]],
) -> dict[str, list[list[float]]]:
    transforms: dict[str, list[list[float]]] = {}

    def link_transform(link_name: str) -> list[list[float]]:
        if link_name in transforms:
            return transforms[link_name]
        parent = child_to_parent.get(link_name)
        if parent is None:
            transforms[link_name] = _identity_matrix()
            return transforms[link_name]
        parent_name, origin = parent
        transforms[link_name] = _matrix_multiply(link_transform(parent_name), origin)
        return transforms[link_name]

    for link_name in link_names:
        if link_name:
            link_transform(link_name)
    return transforms


def _head_camera_pose_from_urdf(
    urdf_path: Path,
    head_link_name: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    robot = _parse_urdf_tree(urdf_path)
    head_matrix = robot["link_transforms"].get(head_link_name) or _identity_matrix()
    camera_matrix = _matrix_multiply(
        head_matrix,
        _matrix_from_translation_quat(HEAD_CAMERA_POSITION_M, HEAD_CAMERA_QUAT_WXYZ),
    )
    return _translation_quat_from_matrix(camera_matrix)


def _origin_matrix(origin: ET.Element | None) -> list[list[float]]:
    if origin is None:
        return _identity_matrix()
    xyz = _float_triplet(str(origin.attrib.get("xyz") or "0 0 0"))
    rpy = _float_triplet(str(origin.attrib.get("rpy") or "0 0 0"))
    return _matrix_from_xyz_rpy(xyz, rpy)


def _matrix_from_xyz_rpy(
    xyz: tuple[float, float, float],
    rpy: tuple[float, float, float],
) -> list[list[float]]:
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rotation = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    return [
        [rotation[0][0], rotation[0][1], rotation[0][2], xyz[0]],
        [rotation[1][0], rotation[1][1], rotation[1][2], xyz[1]],
        [rotation[2][0], rotation[2][1], rotation[2][2], xyz[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _matrix_from_translation_quat(
    position: tuple[float, float, float],
    quat_wxyz: tuple[float, float, float, float],
) -> list[list[float]]:
    w, x, y, z = quat_wxyz
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), position[0]],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), position[1]],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), position[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _translation_quat_from_matrix(
    matrix: list[list[float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    m = matrix
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    return (
        (float(m[0][3]), float(m[1][3]), float(m[2][3])),
        _normalize_quat((w, x, y, z)),
    )


def _normalize_quat(
    quat: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    norm = math.sqrt(sum(value * value for value in quat))
    if norm <= 0.0:
        return (1.0, 0.0, 0.0, 0.0)
    return tuple(float(value / norm) for value in quat)  # type: ignore[return-value]


def _matrix_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [sum(a[row][k] * b[k][column] for k in range(4)) for column in range(4)] for row in range(4)
    ]


def _identity_matrix() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _float_triplet(value: str) -> tuple[float, float, float]:
    parts = [float(item) for item in value.split()]
    while len(parts) < 3:
        parts.append(0.0)
    return (parts[0], parts[1], parts[2])


def _usd_safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
    if not cleaned:
        return "unnamed"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _find_prim_name_candidates(usd_path: Path, name: str) -> list[str]:
    from pxr import Usd

    stage = Usd.Stage.Open(str(usd_path))
    if stage is None:
        return []
    return [str(prim.GetPath()) for prim in stage.Traverse() if prim.GetName() == name]


def _inspect_urdf(urdf_path: Path, *, required_joints: tuple[str, ...]) -> dict[str, Any]:
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    links = [str(item.attrib.get("name") or "") for item in root.findall("link")]
    joints = [str(item.attrib.get("name") or "") for item in root.findall("joint")]
    return {
        "robot_xml_name": str(root.attrib.get("name") or ""),
        "link_count": len([item for item in links if item]),
        "joint_count": len([item for item in joints if item]),
        "head_links": [item for item in links if item.startswith("link_head_")],
        "required_joints": list(required_joints),
        "missing_required_joints": [item for item in required_joints if item not in joints],
    }


def _head_camera_summary() -> dict[str, Any]:
    return {
        "schema": "rby1m_mujoco_head_camera_mount_v1",
        "source_camera_name": "robot_0/head_camera",
        "source_xml_camera_pos": list(HEAD_CAMERA_POSITION_M),
        "source_xml_camera_quat_wxyz": list(HEAD_CAMERA_QUAT_WXYZ),
        "focal_length_mm": HEAD_CAMERA_FOCAL_LENGTH_MM,
        "vertical_fov_deg": HEAD_CAMERA_VERTICAL_FOV_DEG,
        "horizontal_aperture_mm": HEAD_CAMERA_HORIZONTAL_APERTURE_MM,
        "note": (
            "The USD camera is authored from the MuJoCo robot_0/head_camera local "
            "pose and vertical FOV so Isaac FPV uses the same robot-head camera "
            "contract."
        ),
    }


def _required_joints() -> tuple[str, ...]:
    return ("base_x", "base_y", "base_theta", "head_0", "head_1")


def _reference_path(raw_usd_path: Path, output_usd_path: Path) -> str:
    try:
        return os.path.relpath(raw_usd_path, output_usd_path.parent)
    except ValueError:
        return str(raw_usd_path)


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_repo_path(path: Path | None) -> Path:
    if path is None:
        raise ValueError("path is required")
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path(__file__).resolve().parents[3] / expanded


def _find_rby1m_isaac_urdf() -> Path | None:
    candidates: list[Path] = []
    env_root = os.environ.get("MLSPACES_ASSETS_DIR")
    if env_root:
        candidates.append(
            Path(env_root).expanduser()
            / "robots"
            / "rby1m"
            / "curobo_config"
            / "urdf"
            / "model_holobase_isaac"
            / "model_holobase_isaac.urdf"
        )
    candidates.extend(
        (Path.home() / ".cache" / "molmospaces" / "assets").glob(
            "*/robots/rby1m/curobo_config/urdf/model_holobase_isaac/model_holobase_isaac.urdf"
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
