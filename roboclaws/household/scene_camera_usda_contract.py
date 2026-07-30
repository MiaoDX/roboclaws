from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.scene_camera_render_diagnostics import float_list

USD_PHYSICS_PRIM_TYPE_NAMES = (
    "PhysicsFixedJoint",
    "PhysicsPrismaticJoint",
    "PhysicsRevoluteJoint",
)
USD_PHYSICS_API_SCHEMA_NAMES = (
    "PhysicsArticulationRootAPI",
    "PhysicsCollisionAPI",
    "PhysicsFilteredPairsAPI",
    "PhysicsMassAPI",
    "PhysicsRigidBodyAPI",
)


def isaac_render_contract_from_usda(path_text: str | None) -> dict[str, Any]:
    path = Path(str(path_text or ""))
    if not path.is_file():
        return {"status": "missing_scene_usd", "path": str(path)}
    text = path.read_text(encoding="utf-8", errors="ignore")
    material_blocks = usda_material_blocks(text)
    prim_blocks = usda_prim_blocks(text)
    physics_contract = usda_visual_physics_contract(prim_blocks)
    material_bindings: dict[str, list[dict[str, Any]]] = {}
    shadow_disabled = []
    for prim_path, block in prim_blocks.items():
        direct_block = usda_direct_prim_block(block)
        binding_paths = re.findall(r"rel material:binding = <([^>]+)>", direct_block)
        if binding_paths:
            material_bindings[prim_path] = [
                {
                    "material_path": binding_path,
                    **material_blocks.get(binding_path, {}),
                }
                for binding_path in binding_paths
            ]
        if "primvars:doNotCastShadows" in direct_block and re.search(
            r"primvars:doNotCastShadows\s*=\s*(1|true)", direct_block
        ):
            shadow_disabled.append(prim_path)
    lights = usda_light_contracts(text)
    prepared_summary = prepared_scene_summary(path)
    return {
        "status": "parsed",
        "path": str(path),
        "material_count": len(material_blocks),
        "bound_prim_count": len(material_bindings),
        "light_count": len(lights),
        "shadow_disabled_prim_count": len(shadow_disabled),
        "materials": material_blocks,
        "material_bindings": material_bindings,
        "lights": lights,
        "shadow_disabled_prims": shadow_disabled,
        "prepared_summary_status": prepared_summary.get("status"),
        "mujoco_visual_joint_endpoint_pose_status": prepared_summary.get(
            "mujoco_visual_joint_endpoint_pose_status"
        ),
        "mujoco_visual_joint_endpoint_pose_corrected_count": prepared_summary.get(
            "mujoco_visual_joint_endpoint_pose_corrected_count"
        ),
        "mujoco_visual_joint_endpoint_pose_missing_count": prepared_summary.get(
            "mujoco_visual_joint_endpoint_pose_missing_count"
        ),
        "visual_physics_joint_removed_count": prepared_summary.get(
            "visual_physics_joint_removed_count"
        ),
        "visual_physics_api_schema_removed_count": prepared_summary.get(
            "visual_physics_api_schema_removed_count"
        ),
        "visual_physics_property_removed_count": prepared_summary.get(
            "visual_physics_property_removed_count"
        ),
        **physics_contract,
        "visual_physics_status": prepared_summary.get("visual_physics_status")
        or physics_contract.get("visual_physics_status"),
    }


def prepared_scene_summary(path: Path) -> dict[str, Any]:
    summary_path = path.parent / "summary.json"
    if not summary_path.is_file():
        return {}
    try:
        return read_json_object(summary_path, label="prepared scene summary")
    except (OSError, ValueError):
        return {}


def load_scene_metadata(scene_usd_path: Path) -> dict[str, dict[str, Any]]:
    metadata_path = scene_usd_path.parent / "scene_metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        payload = read_json_object(metadata_path, label="scene metadata JSON")
    except ValueError as exc:
        message = str(exc)
        if "source must contain valid JSON object" in message:
            raise RuntimeError(f"malformed scene metadata JSON: {metadata_path}") from exc
        if "source must contain a JSON object" in message:
            raise RuntimeError(
                f"scene metadata JSON must be a JSON object: {metadata_path}"
            ) from exc
        raise
    objects = payload.get("objects")
    if not isinstance(objects, dict):
        raise RuntimeError(f"scene metadata JSON objects must be a JSON object: {metadata_path}")
    invalid_object = next(
        (value for value in objects.values() if not isinstance(value, dict)),
        None,
    )
    if invalid_object is not None:
        raise RuntimeError(
            "scene metadata JSON objects values must be JSON objects: "
            f"{metadata_path} entry_type={type(invalid_object).__name__}"
        )
    return {str(key): dict(value) for key, value in objects.items()}


def load_local_isaac_scene_index(scene_usd_path: Path) -> dict[str, Any]:
    """Load the newest nearby Isaac scene index for USD prim path hints.

    Any support poses in this artifact are deliberately ignored by the camera
    comparison; Isaac targets are resolved from USD prim world bounds instead.
    """

    root = scene_usd_path.parents[2] if len(scene_usd_path.parents) > 2 else Path("output/isaaclab")
    candidates = sorted(
        root.glob("cleanup-smoke/*/isaac_scene_index.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        payload = _read_optional_scene_index(candidate)
        if not payload:
            continue
        if str(payload.get("scene_usd") or "") != str(scene_usd_path):
            continue
        return payload
    return {}


def _read_optional_scene_index(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label="local Isaac scene index")
    except (OSError, ValueError):
        return {}


def isaac_scene_index_entry(anchor_id: str, scene_index: dict[str, Any]) -> dict[str, Any]:
    receptacles = scene_index.get("receptacle_index") if isinstance(scene_index, dict) else None
    if not isinstance(receptacles, dict):
        return {}
    raw = receptacles.get(anchor_id)
    return dict(raw) if isinstance(raw, dict) else {}


def support_pose_position(value: Any) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return [
            float(value["x"]),
            float(value["y"]),
            float(value.get("z", 0.0)),
        ]
    except (KeyError, TypeError, ValueError):
        return None


def usda_visual_physics_contract(prim_blocks: dict[str, str]) -> dict[str, Any]:
    physics_joint_paths: list[str] = []
    physics_api_schema_prim_paths: list[str] = []
    physics_property_prim_paths: list[str] = []
    for prim_path, block in prim_blocks.items():
        first_line = block.splitlines()[0] if block else ""
        if any(f" {type_name} " in f" {first_line} " for type_name in USD_PHYSICS_PRIM_TYPE_NAMES):
            physics_joint_paths.append(prim_path)
            continue
        direct_block = usda_direct_prim_block(block)
        if any(schema in direct_block for schema in USD_PHYSICS_API_SCHEMA_NAMES):
            physics_api_schema_prim_paths.append(prim_path)
        if re.search(r"(?m)^\s+(?:custom\s+)?[\w:<>\[\]]*\s*physics:", direct_block) or re.search(
            r"(?m)^\s+(?:custom\s+)?[\w:<>\[\]]*\s*physx",
            direct_block,
        ):
            physics_property_prim_paths.append(prim_path)
    physics_joint_paths = sorted(set(physics_joint_paths))
    physics_api_schema_prim_paths = sorted(set(physics_api_schema_prim_paths))
    physics_property_prim_paths = sorted(set(physics_property_prim_paths))
    status = (
        "frozen_static_visual_usd"
        if not physics_joint_paths
        and not physics_api_schema_prim_paths
        and not physics_property_prim_paths
        else "physics_articulation_preserved"
    )
    return {
        "visual_physics_status": status,
        "physics_joint_count": len(physics_joint_paths),
        "physics_api_schema_prim_count": len(physics_api_schema_prim_paths),
        "physics_property_prim_count": len(physics_property_prim_paths),
        "physics_joint_paths": physics_joint_paths,
        "physics_api_schema_prim_paths": physics_api_schema_prim_paths,
        "physics_property_prim_paths": physics_property_prim_paths,
    }


def usda_material_blocks(text: str) -> dict[str, dict[str, Any]]:
    materials: dict[str, dict[str, Any]] = {}
    material_name_by_path = usda_named_prim_paths(text, "Material")
    for path, block_text in usda_named_prim_blocks(text, "Material").items():
        name = material_name_by_path.get(path) or Path(path).name
        parsed = parse_usda_material_block(name, block_text)
        materials[path] = parsed
        materials[f"/{name}"] = parsed
    return materials


def parse_usda_material_block(name: str, block_text: str) -> dict[str, Any]:
    texture_files = re.findall(r"asset inputs:file = @([^@]+)@", block_text)
    diffuse_match = re.search(r"color3f inputs:diffuseColor = \(([^)]+)\)", block_text)
    diffuse_connect_match = re.search(
        r"color3f inputs:diffuseColor\.connect = <([^>]+)>",
        block_text,
    )
    source_color_space_match = re.search(
        r'token inputs:sourceColorSpace = "([^"]+)"',
        block_text,
    )
    return {
        "material_name": name,
        "has_preview_surface": "UsdPreviewSurface" in block_text,
        "diffuse_color": float_list(diffuse_match.group(1).replace(",", " "))
        if diffuse_match
        else None,
        "diffuse_color_connect": diffuse_connect_match.group(1) if diffuse_connect_match else None,
        "diffuse_texture_files": texture_files,
        "texture_scale": parse_usda_float_input(block_text, "scale"),
        "texture_fallback": parse_usda_float_input(block_text, "fallback"),
        "texture_source_color_space": source_color_space_match.group(1)
        if source_color_space_match
        else None,
        "texture_wrap_s": parse_usda_token_input(block_text, "wrapS"),
        "texture_wrap_t": parse_usda_token_input(block_text, "wrapT"),
        "preview_surface_inputs": {
            "metallic": parse_usda_scalar_input(block_text, "metallic"),
            "opacity": parse_usda_scalar_input(block_text, "opacity"),
            "roughness": parse_usda_scalar_input(block_text, "roughness"),
            "specular": parse_usda_scalar_input(block_text, "specular"),
        },
        "has_diffuse_texture": bool(texture_files) or "inputs:diffuseColor.connect" in block_text,
    }


def parse_usda_scalar_input(block_text: str, name: str) -> float | None:
    match = re.search(rf"float inputs:{re.escape(name)} = ([^\s]+)", block_text)
    return _optional_float(match.group(1)) if match else None


def parse_usda_float_input(block_text: str, name: str) -> list[float] | None:
    match = re.search(rf"float[234]? inputs:{re.escape(name)} = \(([^)]+)\)", block_text)
    return float_list(match.group(1).replace(",", " ")) if match else None


def parse_usda_token_input(block_text: str, name: str) -> str | None:
    match = re.search(rf'token inputs:{re.escape(name)} = "([^"]+)"', block_text)
    return match.group(1) if match else None


def usda_prim_blocks(text: str) -> dict[str, str]:
    return usda_named_prim_blocks(text)


def usda_direct_prim_block(block: str) -> str:
    direct_lines = []
    skipping_child = False
    child_body_started = False
    child_depth = 0
    for index, line in enumerate(block.splitlines()):
        stripped = line.strip()
        if index > 0 and not skipping_child and re.match(r'(?:def|over)\s+\w+\s+"', stripped):
            skipping_child = True
            child_body_started = False
            child_depth = 0
            continue
        if skipping_child:
            if not child_body_started and stripped == "{":
                child_body_started = True
                child_depth = 1
                continue
            if child_body_started:
                child_depth += line.count("{") - line.count("}")
                if child_depth <= 0:
                    skipping_child = False
            continue
        direct_lines.append(line)
    return "\n".join(direct_lines)


def usda_named_prim_paths(text: str, type_name: str | None = None) -> dict[str, str]:
    names = {}
    for path, block in usda_named_prim_blocks(text, type_name).items():
        first_line = block.splitlines()[0] if block else ""
        match = re.search(r'(?:def|over)\s+\w+\s+"([^"]+)"', first_line.strip())
        if match:
            names[path] = match.group(1)
    return names


def usda_named_prim_blocks(text: str, type_name: str | None = None) -> dict[str, str]:
    blocks: dict[str, str] = {}
    lines = text.splitlines()
    active_stack: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    brace_depth = 0
    index = 0
    type_pattern = r"\w+" if type_name is None else re.escape(type_name)
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        prim_match = re.match(rf'(?:def|over)\s+{type_pattern}\s+"([^"]+)"', stripped)
        generic_match = re.match(r'(?:def|over)\s+(?P<type>\w+)\s+"(?P<name>[^"]+)"', stripped)
        if generic_match:
            name = generic_match.group("name")
            parent_path = str(active_stack[-1]["path"]) if active_stack else ""
            current_path = f"{parent_path}/{name}" if parent_path else f"/{name}"
            if prim_match:
                block_lines, _ = collect_usda_prim_block(lines, index)
                blocks[current_path] = "\n".join(block_lines)
            pending = {"path": current_path}
        if pending is not None and stripped == "{":
            active_stack.append({"path": pending["path"], "close_depth": brace_depth})
            pending = None
        brace_depth += line.count("{") - line.count("}")
        while active_stack and brace_depth <= int(active_stack[-1]["close_depth"]):
            active_stack.pop()
        index += 1
    return blocks


def collect_usda_prim_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    block = []
    body_started = False
    depth = 0
    for index in range(start_index, len(lines)):
        line = lines[index]
        block.append(line)
        if not body_started:
            if line.strip() != "{":
                continue
            body_started = True
        depth += line.count("{") - line.count("}")
        if body_started and depth <= 0:
            return block, index
    return block, len(lines) - 1


def usda_light_contracts(text: str) -> list[dict[str, Any]]:
    lights = []
    for match in re.finditer(
        r'def\s+(?P<type>DomeLight|DistantLight|RectLight|SphereLight|DiskLight)\s+"(?P<name>[^"]+)"(?P<body>.*?)(?=\n\s*def\s|\Z)',
        text,
        re.S,
    ):
        body = match.group("body")
        intensity_match = re.search(r"inputs:intensity = ([^\s]+)", body)
        color_match = re.search(r"inputs:color = \(([^)]+)\)", body)
        lights.append(
            {
                "name": match.group("name"),
                "type": match.group("type"),
                "intensity": _optional_float(intensity_match.group(1)) if intensity_match else None,
                "color": float_list(color_match.group(1).replace(",", " "))
                if color_match
                else None,
            }
        )
    return lights


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
