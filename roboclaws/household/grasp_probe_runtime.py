from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

PROBE_SCRIPT = r"""
from __future__ import annotations

import argparse
import json
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation as R

from molmo_spaces.molmo_spaces_constants import (
    ABS_PATH_OF_TOP_LEVEL_MOLMO_SPACES_DIR,
    ASSETS_DIR,
)


def parse_csv_floats(value: str) -> list[float]:
    return [float(item) for item in value.split(",") if item]


def parse_csv_ints(value: str) -> list[int]:
    return [int(item) for item in value.split(",") if item]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-name", required=True)
    parser.add_argument("--object-xml", required=True)
    parser.add_argument("--candidate-grasps", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-output")
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--approach-signs", default="-1,1")
    parser.add_argument("--approach-distances", default="0.1,0.2,0.3,0.5,0.8")
    parser.add_argument("--settle-steps", default="1,50,500")
    parser.add_argument("--approach-steps", type=int, default=30)
    parser.add_argument("--post-approach-steps", type=int, default=300)
    parser.add_argument("--close-steps", type=int, default=300)
    return parser.parse_args()


def merge_xml_contents(base_xml_content: str, additional_xml_content: str) -> str:
    base_root = ET.fromstring(base_xml_content)
    additional_root = ET.fromstring(additional_xml_content)
    if base_root.tag != "mujoco" or additional_root.tag != "mujoco":
        raise ValueError("Both XML contents must have 'mujoco' as the root element")
    processed_sections = {}
    for additional_child in additional_root:
        tag_name = additional_child.tag
        base_section = base_root.find(tag_name)
        if base_section is not None:
            if tag_name in processed_sections:
                continue
            for element in additional_child:
                is_duplicate = False
                for existing in base_section:
                    same_attrs = all(
                        attr in existing.attrib and existing.attrib[attr] == val
                        for attr, val in element.attrib.items()
                        if attr != "name"
                    )
                    same_name = (
                        "name" not in element.attrib
                        or "name" not in existing.attrib
                        or element.attrib["name"] == existing.attrib["name"]
                    )
                    if element.tag == existing.tag and same_attrs and same_name:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    base_section.append(element)
            processed_sections[tag_name] = True
        else:
            base_root.append(additional_child)
            processed_sections[tag_name] = True
    return ET.tostring(base_root, encoding="unicode")


def base_scene_xml(object_xml: str) -> str:
    scene_path = (
        Path(ABS_PATH_OF_TOP_LEVEL_MOLMO_SPACES_DIR)
        / "molmo_spaces/grasp_generation/main_scene.xml"
    )
    tree = ET.parse(scene_path)
    root = tree.getroot()
    root.append(ET.Element("include", {"file": object_xml}))
    xml_content = ET.tostring(root, encoding="unicode")
    gripper_xml_path = ASSETS_DIR / "robots/floating_robotiq/model_rigid.xml"
    additional_xml_content = gripper_xml_path.read_text(encoding="utf-8")
    return merge_xml_contents(xml_content, additional_xml_content)


def model_for_grasp(xml_content: str, transform: np.ndarray, sign: int, distance: float):
    pos = transform[:3, 3]
    quat = R.from_matrix(transform[:3, :3]).as_quat(scalar_first=True)
    approach_pos = pos + sign * transform[:3, 2] * distance
    root = ET.fromstring(xml_content)
    for body in root.findall(".//body"):
        if body.get("name") in {"base", "target_ee_pose"}:
            body.set("pos", f"{approach_pos[0]} {approach_pos[1]} {approach_pos[2]}")
            body.set("quat", f"{quat[0]} {quat[1]} {quat[2]} {quat[3]}")
    for geom in root.findall(".//geom"):
        if geom.get("name") == "test_sphere":
            geom.set("pos", f"{pos[0]} {pos[1]} {pos[2]}")
            geom.set("quat", f"{quat[0]} {quat[1]} {quat[2]} {quat[3]}")
            break
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    data = mujoco.MjData(model)
    return model, data, pos, quat, approach_pos


def contact_sides(model, data, object_name: str) -> tuple[set[str], list[list[str]]]:
    sides: set[str] = set()
    pairs: list[list[str]] = []
    left_patterns = ("left_finger", "finger_l", "gripper_finger_left", "left")
    right_patterns = ("right_finger", "finger_r", "gripper_finger_right", "right")
    object_lower = object_name.lower()
    for i in range(data.ncon):
        contact = data.contact[i]
        geom1 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom1) or ""
        geom2 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom2) or ""
        if not geom1 or not geom2:
            continue
        is_object_contact = (
            object_lower in geom1.lower()
            or object_lower in geom2.lower()
            or "collider" in geom1.lower()
            or "collider" in geom2.lower()
        )
        if is_object_contact:
            other = geom2 if object_lower in geom1.lower() or "collider" in geom1.lower() else geom1
            other_lower = other.lower()
            if any(pattern in other_lower for pattern in left_patterns):
                sides.add("left")
            if any(pattern in other_lower for pattern in right_patterns):
                sides.add("right")
            pairs.append([geom1, geom2])
    return sides, pairs


def evaluate_variant(
    xml_content: str,
    transforms: np.ndarray,
    args: argparse.Namespace,
    sign: int,
    distance: float,
    settle_steps: int,
    include_successful_transforms: bool = False,
) -> dict:
    rows = []
    successful_transforms = []
    for index, transform in enumerate(transforms):
        model, data, pos, quat, approach_pos = model_for_grasp(
            xml_content,
            transform,
            sign,
            distance,
        )
        initial_object_pos = data.body(args.object_name).xpos.copy()
        data.ctrl[model.actuator("fingers_actuator").id] = 0.0
        mujoco.mj_step(model, data, nstep=settle_steps)
        settled_object_pos = data.body(args.object_name).xpos.copy()
        initial_sides, initial_pairs = contact_sides(model, data, args.object_name)
        initial_displacement = float(np.linalg.norm(settled_object_pos - initial_object_pos))

        mocap_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "target_ee_pose")
        for step in range(args.approach_steps):
            alpha = step / max(args.approach_steps, 1)
            current_target_pos = approach_pos + alpha * (pos - approach_pos)
            if mocap_id >= 0:
                data.mocap_pos[0] = current_target_pos
                data.mocap_quat[0] = quat
            mujoco.mj_step(model, data)
        if mocap_id >= 0:
            data.mocap_pos[0] = pos
        mujoco.mj_step(model, data, nstep=args.post_approach_steps)
        data.ctrl[model.actuator("fingers_actuator").id] = 255.0
        mujoco.mj_step(model, data, nstep=args.close_steps)
        final_object_pos = data.body(args.object_name).xpos.copy()
        final_sides, final_pairs = contact_sides(model, data, args.object_name)
        success = "left" in final_sides and "right" in final_sides
        if success and include_successful_transforms:
            tcp_pose = np.eye(4)
            tcp_pose[:3, 3] = data.site("grasp_site").xpos
            tcp_pose[:3, :3] = data.site("grasp_site").xmat.reshape(3, 3)
            object_pose = np.eye(4)
            object_pose[:3, :3] = data.body(args.object_name).xmat.reshape(3, 3)
            object_pose[:3, 3] = data.body(args.object_name).xpos
            successful_transforms.append((np.linalg.inv(object_pose) @ tcp_pose).tolist())
        rows.append(
            {
                "candidate_index": index,
                "success": success,
                "initial_contact_side_count": len(initial_sides),
                "initial_contact_sides": sorted(initial_sides),
                "initial_contact_pair_count": len(initial_pairs),
                "initial_contact_pairs": initial_pairs[:8],
                "initial_displacement_m": initial_displacement,
                "final_contact_sides": sorted(final_sides),
                "final_contact_pair_count": len(final_pairs),
                "final_contact_pairs": final_pairs[:8],
                "final_displacement_m": float(
                    np.linalg.norm(final_object_pos - initial_object_pos)
                ),
            }
        )
    success_count = sum(1 for row in rows if row["success"])
    initial_contact_count = sum(1 for row in rows if row["initial_contact_pair_count"] > 0)
    displaced_count = sum(1 for row in rows if row["initial_displacement_m"] > 0.01)
    return {
        "name": f"sign_{sign}_dist_{distance:g}_settle_{settle_steps}",
        "approach_sign": sign,
        "approach_distance": distance,
        "settle_steps": settle_steps,
        "candidate_count": len(rows),
        "success_count": success_count,
        "initial_contact_count": initial_contact_count,
        "initial_displaced_count": displaced_count,
        "avg_initial_displacement_m": (
            float(np.mean([row["initial_displacement_m"] for row in rows])) if rows else 0.0
        ),
        "max_initial_displacement_m": (
            float(np.max([row["initial_displacement_m"] for row in rows])) if rows else 0.0
        ),
        "sample_rows": rows[:5],
        "successful_candidate_indices": [
            row["candidate_index"] for row in rows if row["success"]
        ][:20],
        "classification": "nonzero_success" if success_count else "zero_success",
        "successful_transforms": successful_transforms,
    }


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        grasp_data = json.loads(Path(args.candidate_grasps).read_text(encoding="utf-8"))
        transforms = np.array(grasp_data.get("transforms") or [], dtype=float)
        if args.max_candidates > 0:
            transforms = transforms[: args.max_candidates]
        xml_content = base_scene_xml(args.object_xml)
        variants = []
        cache_transforms = []
        for sign in parse_csv_ints(args.approach_signs):
            for distance in parse_csv_floats(args.approach_distances):
                for settle_steps in parse_csv_ints(args.settle_steps):
                    variant = evaluate_variant(
                        xml_content,
                        transforms,
                        args,
                        sign,
                        distance,
                        settle_steps,
                        include_successful_transforms=bool(args.cache_output),
                    )
                    cache_transforms.extend(variant.pop("successful_transforms", []))
                    variants.append(variant)
        if args.cache_output:
            cache_output = Path(args.cache_output)
            cache_output.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                cache_output,
                transforms=np.array(cache_transforms, dtype=np.float16),
            )
            for variant in variants:
                variant["cache_output_path"] = str(cache_output)
                variant["cache_transform_count"] = len(cache_transforms)
        payload = {
            "status": "ready",
            "candidate_count": int(len(transforms)),
            "variants": variants,
        }
    except Exception as exc:
        payload = {
            "status": "blocked",
            "candidate_count": 0,
            "variants": [],
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def run_molmospaces_probe_command(
    command: list[str],
    *,
    cwd: Path,
    molmospaces_python: Path,
    timeout_s: float,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["PATH"] = str(molmospaces_python.parent) + os.pathsep + env.get("PATH", "")
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "blocked",
            "returncode": "",
            "stdout": str(exc.stdout or "").strip(),
            "stderr": str(exc.stderr or "").strip(),
            "code": "command_timeout",
            "message": f"Command exceeded {timeout_s:.1f}s.",
        }
    except OSError as exc:
        return {
            "status": "blocked",
            "returncode": "",
            "stdout": "",
            "stderr": str(exc),
            "code": "command_os_error",
            "message": str(exc),
        }
    return {
        "status": "ready" if completed.returncode == 0 else "blocked",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
