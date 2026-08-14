#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from roboclaws.backends.isaaclab.molmospaces_rendering_parity import (
    _apply_distant_light_orientation_candidate,
    _apply_material_texture_scale_candidate,
    _default_rendering_path_status,
    _rendering_parity_preset,
)
from roboclaws.backends.isaaclab.molmospaces_semantic_labels import (
    LABEL_INSTANCES,
    _author_semantic_labels,
    _copy_metadata_next_to_output,
    _load_molmospaces_scene_metadata,
    _metadata_entries,
    _prim_paths_by_name,
)
from roboclaws.backends.isaaclab.molmospaces_visual_physics import (
    _freeze_visual_physics,
    _visual_physics_not_frozen,
)

SCHEMA = "roboclaws_molmospaces_flattened_semantic_usd_v1"
DEFAULT_RENDERING_PARITY_PRESET = "combined-material-light"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compose a MolmoSpaces scene USD, flatten it, and author Isaac 5 semantic "
            "LabelsAPI metadata directly on renderable Mesh/Gprim targets."
        )
    )
    parser.add_argument("--scene-usd-path", type=Path, required=True)
    parser.add_argument(
        "--mujoco-scene-xml-path",
        type=Path,
        help=(
            "Optional source MuJoCo scene XML. When provided, articulated visual "
            "box/flap Xforms in the prepared USD are baked to the MJCF joint ref "
            "endpoint before physics state is stripped."
        ),
    )
    parser.add_argument("--output-usd-path", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument(
        "--label-containers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also label the metadata root prims, not only renderable descendants.",
    )
    parser.add_argument(
        "--rendering-parity-preset",
        choices=("combined-material-light", "source-preserving"),
        default=DEFAULT_RENDERING_PARITY_PRESET,
        help=(
            "Prepared-USD rendering preset. The default applies the validated "
            "DistantLight rotateX=+25 while preserving source USD material texture "
            "scale/fallback values; 'source-preserving' keeps source USD material "
            "and light settings."
        ),
    )
    parser.add_argument(
        "--material-texture-scale-mode",
        choices=("none", "identity", "square"),
        default=None,
        help=(
            "Optional override for UsdUVTexture scale/fallback inputs. Omit this to use "
            "the selected rendering parity preset."
        ),
    )
    parser.add_argument(
        "--freeze-visual-physics",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Strip physics APIs/joints from the flattened report USD after visual xforms "
            "are baked. This keeps Isaac capture from re-solving THOR articulated assets "
            "such as Box flaps away from the MuJoCo visual pose."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = prepare_flattened_semantic_usd(
        scene_usd_path=args.scene_usd_path,
        mujoco_scene_xml_path=args.mujoco_scene_xml_path,
        output_usd_path=args.output_usd_path,
        summary_output=args.summary_output,
        label_containers=args.label_containers,
        rendering_parity_preset=args.rendering_parity_preset,
        material_texture_scale_mode=args.material_texture_scale_mode,
        freeze_visual_physics=args.freeze_visual_physics,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] in {"ready", "partial"} else 2


def prepare_flattened_semantic_usd(
    *,
    scene_usd_path: Path,
    mujoco_scene_xml_path: Path | None = None,
    output_usd_path: Path,
    summary_output: Path | None = None,
    label_containers: bool = True,
    rendering_parity_preset: str = DEFAULT_RENDERING_PARITY_PRESET,
    material_texture_scale_mode: str | None = None,
    freeze_visual_physics: bool = True,
) -> dict[str, Any]:
    from pxr import Sdf, Usd, UsdGeom

    stage = Usd.Stage.Open(str(scene_usd_path))
    if stage is None:
        raise RuntimeError(f"Could not open scene USD: {scene_usd_path}")
    stage.Load()

    flattened_layer = stage.Flatten()
    output_usd_path.parent.mkdir(parents=True, exist_ok=True)
    if output_usd_path.exists():
        output_usd_path.unlink()
    output_layer = Sdf.Layer.CreateNew(str(output_usd_path))
    output_layer.ImportFromString(flattened_layer.ExportToString())
    output_layer.Save()
    metadata_copied = _copy_metadata_next_to_output(
        scene_usd_path=scene_usd_path,
        output_usd_path=output_usd_path,
    )

    flat_stage = Usd.Stage.Open(str(output_usd_path))
    if flat_stage is None:
        raise RuntimeError(f"Could not open flattened USD: {output_usd_path}")

    metadata = _load_molmospaces_scene_metadata(scene_usd_path)
    prim_paths_by_name = _prim_paths_by_name(flat_stage)
    entries = _metadata_entries(metadata=metadata, prim_paths_by_name=prim_paths_by_name)
    label_summary = _author_semantic_labels(
        stage=flat_stage,
        entries=entries,
        usd_geom=UsdGeom,
        label_containers=label_containers,
    )
    visual_joint_endpoint_pose_summary = _apply_mujoco_visual_joint_endpoint_pose(
        stage=flat_stage,
        mujoco_scene_xml_path=mujoco_scene_xml_path,
    )
    visual_physics_summary = (
        _freeze_visual_physics(flat_stage)
        if freeze_visual_physics
        else _visual_physics_not_frozen()
    )
    flat_stage.GetRootLayer().Save()
    preset = _rendering_parity_preset(rendering_parity_preset)
    effective_material_texture_scale_mode = (
        material_texture_scale_mode
        if material_texture_scale_mode is not None
        else str(preset["material_texture_scale_mode"])
    )
    material_conversion_summary = _apply_material_texture_scale_candidate(
        output_usd_path=output_usd_path,
        mode=effective_material_texture_scale_mode,
    )
    light_conversion_summary = _apply_distant_light_orientation_candidate(
        output_usd_path=output_usd_path,
        rotate_x=preset["distant_light_rotate_x"],
    )
    default_rendering_path_status = _default_rendering_path_status(
        rendering_parity_preset=rendering_parity_preset,
        material_conversion_summary=material_conversion_summary,
        light_conversion_summary=light_conversion_summary,
    )

    blockers = []
    if not entries:
        blockers.append("No MolmoSpaces scene_metadata objects matched flattened USD prim names.")
    if not label_summary["renderable_labeled_prim_count"]:
        blockers.append("No renderable Mesh/Gprim semantic label targets were authored.")
    if _mujoco_visual_joint_endpoint_pose_blocking(visual_joint_endpoint_pose_summary):
        blockers.append(
            "Requested MuJoCo visual joint endpoint pose baking did not update every "
            "matched articulated visual target."
        )
    status = (
        "ready"
        if not blockers
        else "partial"
        if label_summary["labeled_entry_count"]
        else "blocked"
    )
    summary = {
        "schema": SCHEMA,
        "status": status,
        "source_scene_usd_path": str(scene_usd_path),
        "output_usd_path": str(output_usd_path),
        "source_stage_prim_count": sum(1 for _ in stage.Traverse()),
        "flattened_stage_prim_count": sum(1 for _ in flat_stage.Traverse()),
        "metadata_entry_count": len(metadata),
        "matched_entry_count": len(entries),
        "label_instances": list(LABEL_INSTANCES),
        "label_containers": bool(label_containers),
        "rendering_parity_preset": rendering_parity_preset,
        "material_texture_scale_mode": effective_material_texture_scale_mode,
        "material_texture_scale_rewrite_count": material_conversion_summary[
            "texture_scale_rewrite_count"
        ],
        "material_texture_scale_default_candidate": material_conversion_summary[
            "default_candidate"
        ],
        "distant_light_rotate_x": light_conversion_summary["rotate_x"],
        "distant_light_rotate_x_rewrite_count": light_conversion_summary["rewrite_count"],
        "distant_light_rotate_x_insert_count": light_conversion_summary["insert_count"],
        "distant_light_rotate_x_default_candidate": light_conversion_summary["default_candidate"],
        "default_rendering_path_status": default_rendering_path_status,
        "default_rendering_path_uses_combined_material_light": (
            default_rendering_path_status == "default_rendering_path_uses_combined_material_light"
        ),
        "visual_physics_freeze_enabled": bool(freeze_visual_physics),
        **visual_joint_endpoint_pose_summary,
        **visual_physics_summary,
        "scene_metadata_copied": metadata_copied,
        "blockers": blockers,
        **label_summary,
    }
    if summary_output is not None:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return summary


def _apply_mujoco_visual_joint_endpoint_pose(
    *,
    stage: Any,
    mujoco_scene_xml_path: Path | None,
) -> dict[str, Any]:
    if mujoco_scene_xml_path is None:
        return {
            "mujoco_visual_joint_endpoint_pose_status": "not_requested",
            "mujoco_visual_joint_endpoint_pose_source": None,
            "mujoco_visual_joint_endpoint_pose_target_count": 0,
            "mujoco_visual_joint_endpoint_pose_corrected_count": 0,
            "mujoco_visual_joint_endpoint_pose_missing_count": 0,
            "mujoco_visual_joint_endpoint_pose_samples": [],
            "mujoco_visual_joint_endpoint_pose_missing_samples": [],
        }
    if not mujoco_scene_xml_path.is_file():
        return {
            "mujoco_visual_joint_endpoint_pose_status": "missing_mujoco_scene_xml",
            "mujoco_visual_joint_endpoint_pose_source": str(mujoco_scene_xml_path),
            "mujoco_visual_joint_endpoint_pose_target_count": 0,
            "mujoco_visual_joint_endpoint_pose_corrected_count": 0,
            "mujoco_visual_joint_endpoint_pose_missing_count": 0,
            "mujoco_visual_joint_endpoint_pose_samples": [],
            "mujoco_visual_joint_endpoint_pose_missing_samples": [],
        }

    entries = _mujoco_flap_visual_joint_endpoint_entries(mujoco_scene_xml_path)
    paths_by_name = _prim_paths_by_name(stage)
    corrected: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for entry in entries:
        prim_path = _resolve_mujoco_visual_joint_prim_path(
            paths_by_name=paths_by_name,
            mesh_name=str(entry["mesh_name"]),
            ancestor_names=[str(value) for value in entry.get("ancestor_names") or []],
        )
        if prim_path is None:
            missing.append(
                {
                    "mesh_name": entry["mesh_name"],
                    "joint_name": entry["joint_name"],
                    "body_name": entry["body_name"],
                }
            )
            continue
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            missing.append(
                {
                    "mesh_name": entry["mesh_name"],
                    "joint_name": entry["joint_name"],
                    "body_name": entry["body_name"],
                    "usd_prim_path": prim_path,
                }
            )
            continue
        endpoint_quat = _mujoco_body_endpoint_quat(
            body_quat=[float(value) for value in entry["body_quat"]],
        )
        if not _set_usd_xform_orient(prim=prim, quat=endpoint_quat):
            missing.append(
                {
                    "mesh_name": entry["mesh_name"],
                    "joint_name": entry["joint_name"],
                    "body_name": entry["body_name"],
                    "usd_prim_path": prim_path,
                    "reason": "missing_or_invalid_xform_orient",
                }
            )
            continue
        corrected.append(
            {
                "mesh_name": entry["mesh_name"],
                "joint_name": entry["joint_name"],
                "body_name": entry["body_name"],
                "usd_prim_path": prim_path,
                "axis": entry["axis"],
                "ref": entry["ref"],
                "endpoint_quat": endpoint_quat,
            }
        )
    status = (
        "mujoco_visual_joint_endpoint_pose_applied"
        if corrected and not missing
        else "mujoco_visual_joint_endpoint_pose_partial"
        if corrected
        else "mujoco_visual_joint_endpoint_pose_no_targets"
    )
    return {
        "mujoco_visual_joint_endpoint_pose_status": status,
        "mujoco_visual_joint_endpoint_pose_source": str(mujoco_scene_xml_path),
        "mujoco_visual_joint_endpoint_pose_target_count": len(entries),
        "mujoco_visual_joint_endpoint_pose_corrected_count": len(corrected),
        "mujoco_visual_joint_endpoint_pose_missing_count": len(missing),
        "mujoco_visual_joint_endpoint_pose_samples": corrected[:25],
        "mujoco_visual_joint_endpoint_pose_missing_samples": missing[:25],
    }


def _mujoco_visual_joint_endpoint_pose_blocking(summary: dict[str, Any]) -> bool:
    status = str(summary.get("mujoco_visual_joint_endpoint_pose_status") or "")
    if status in {"not_requested", "mujoco_visual_joint_endpoint_pose_applied"}:
        return False
    target_count = int(summary.get("mujoco_visual_joint_endpoint_pose_target_count") or 0)
    missing_count = int(summary.get("mujoco_visual_joint_endpoint_pose_missing_count") or 0)
    return status == "missing_mujoco_scene_xml" or (target_count > 0 and missing_count > 0)


def _mujoco_flap_visual_joint_endpoint_entries(
    mujoco_scene_xml_path: Path,
) -> list[dict[str, Any]]:
    try:
        root = ElementTree.parse(mujoco_scene_xml_path).getroot()
    except ElementTree.ParseError:
        return []
    worldbody = root.find("worldbody")
    if worldbody is None:
        return []
    entries: list[dict[str, Any]] = []

    def visit(body: ElementTree.Element, ancestors: list[str]) -> None:
        body_name = str(body.attrib.get("name") or "")
        next_ancestors = [*ancestors, body_name] if body_name else list(ancestors)
        joint = _single_visual_flap_joint(body)
        if joint is not None:
            mesh_names = [
                str(geom.attrib.get("mesh") or "")
                for geom in body.findall("geom")
                if str(geom.attrib.get("mesh") or "")
            ]
            for mesh_name in mesh_names:
                if "flap" not in mesh_name.lower():
                    continue
                axis = _float_list(joint.attrib.get("axis"), default=[1.0, 0.0, 0.0])
                ref = _float_or_none(joint.attrib.get("ref"))
                if ref is None or len(axis) < 3:
                    continue
                entries.append(
                    {
                        "body_name": body_name,
                        "ancestor_names": next_ancestors,
                        "joint_name": str(joint.attrib.get("name") or ""),
                        "mesh_name": mesh_name,
                        "axis": axis[:3],
                        "ref": ref,
                        "body_quat": _float_list(
                            body.attrib.get("quat"),
                            default=[1.0, 0.0, 0.0, 0.0],
                        )[:4],
                    }
                )
        for child in body.findall("body"):
            visit(child, next_ancestors)

    for body in worldbody.findall("body"):
        visit(body, [])
    return entries


def _single_visual_flap_joint(body: ElementTree.Element) -> ElementTree.Element | None:
    joints = list(body.findall("joint"))
    if len(joints) != 1:
        return None
    joint = joints[0]
    joint_name = str(joint.attrib.get("name") or "").lower()
    joint_type = str(joint.attrib.get("type") or "hinge").lower()
    if joint_type != "hinge":
        return None
    if "flap" not in joint_name:
        return None
    return joint


def _resolve_mujoco_visual_joint_prim_path(
    *,
    paths_by_name: dict[str, list[str]],
    mesh_name: str,
    ancestor_names: list[str],
) -> str | None:
    candidates = list(paths_by_name.get(mesh_name) or [])
    if not candidates:
        return None
    ancestor_set = {name for name in ancestor_names if name}

    def rank(path: str) -> tuple[int, int, str]:
        normalized = f"/{path.strip('/')}/"
        has_geometry = "/geometry/" in normalized.lower()
        ancestor_hits = sum(1 for name in ancestor_set if f"/{name}/" in normalized)
        return (0 if has_geometry else 1, -ancestor_hits, normalized.count("/"), path)

    return sorted(candidates, key=rank)[0]


def _mujoco_body_endpoint_quat(
    *,
    body_quat: list[float],
) -> list[float]:
    # In MJCF, a hinge joint's `ref` is the qpos value represented by the XML body
    # pose. For these MolmoSpaces flap assets, qpos is at ref/range endpoint, so
    # the MuJoCo visual ref pose is the authored body quat, not body_quat * ref.
    quat = _normalize_quat(body_quat)
    if quat[0] < 0:
        quat = [-value for value in quat]
    return [_round_float(value) for value in quat]


def _normalize_quat(values: list[float]) -> list[float]:
    padded = [float(value) for value in values[:4]]
    while len(padded) < 4:
        padded.append(0.0)
    length = math.sqrt(sum(value * value for value in padded))
    if length <= 0:
        return [1.0, 0.0, 0.0, 0.0]
    return [value / length for value in padded]


def _set_usd_xform_orient(*, prim: Any, quat: list[float]) -> bool:
    from pxr import Gf, Sdf, Vt

    attr = prim.GetAttribute("xformOp:orient")
    if not attr or not attr.IsValid():
        return False
    type_name = attr.GetTypeName()
    if type_name == Sdf.ValueTypeNames.Quatd:
        attr.Set(Gf.Quatd(quat[0], Gf.Vec3d(*quat[1:4])))
    else:
        attr.Set(Gf.Quatf(quat[0], Gf.Vec3f(*quat[1:4])))
    order_attr = prim.GetAttribute("xformOpOrder")
    if order_attr and order_attr.IsValid():
        current = [str(value) for value in list(order_attr.Get() or [])]
        if "xformOp:orient" not in current:
            current.append("xformOp:orient")
            order_attr.Set(Vt.TokenArray(current))
    return True


def _float_list(raw: str | None, *, default: list[float]) -> list[float]:
    if raw is None:
        return list(default)
    values: list[float] = []
    for part in raw.split():
        try:
            values.append(float(part))
        except ValueError:
            return list(default)
    return values or list(default)


def _float_or_none(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _round_float(value: float) -> float:
    rounded = round(float(value), 8)
    return 0.0 if rounded == -0.0 else rounded


if __name__ == "__main__":
    raise SystemExit(main())
