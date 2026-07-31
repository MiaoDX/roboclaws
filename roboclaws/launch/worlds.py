"""Operator-facing launch world and scene metadata."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from roboclaws.worlds.contracts import WorldSpec
from roboclaws.worlds.molmospaces.contracts import READINESS_READY
from roboclaws.worlds.molmospaces.map_bundles import molmospaces_nav2_map_bundle_arg
from roboclaws.worlds.molmospaces.sampling import (
    sampler_rows,
    ui_molmospaces_world_ids,
)
from roboclaws.worlds.molmospaces.world_ids import parse_molmospaces_world_id

MOLMOSPACES_CONSOLE_WORLD_IDS: tuple[str, ...] = ui_molmospaces_world_ids()


def _molmospaces_world_spec(row) -> WorldSpec:
    scene_index = row.scene_index
    if scene_index is None:
        raise ValueError("blocked sampler rows do not create launch worlds")
    tags = (
        "household",
        "molmospaces",
        "source-aware-sampler",
        "sampler-ui" if row.ui_ready else "sampler-candidate",
        "curated-default" if scene_index == 0 else "curated-source",
    )
    return WorldSpec(
        id=row.world_id,
        label=f"MolmoSpaces {row.scene_source} #{scene_index}",
        surface_id="household-world",
        available_backends=("mujoco",),
        scene_source=row.scene_source,
        tags=tags,
        default_backend="mujoco",
        resource_kind="simulator",
        availability="enabled" if row.ui_ready else "hidden",
        default_overrides=row.default_overrides,
        preview_assets=row.preview_assets,
        sampler_metadata={
            "schema": "molmospaces_scene_sampler_world_metadata_v1",
            "scene_family": row.scene_family,
            "scene_split": row.scene_split,
            "scene_source": row.scene_source,
            "scene_index": row.scene_index,
            "room_count": row.room_count,
            "waypoint_count": row.waypoint_count,
            "category_provenance": row.category_provenance,
            "selected_reason": row.selected_reason,
            "lanes": list(row.lanes),
            "generator_version": row.to_dict()["generator_version"],
        },
    )


WORLD_SPECS: dict[str, WorldSpec] = {
    **{
        row.world_id: _molmospaces_world_spec(row)
        for row in sampler_rows()
        if row.scene_index is not None and row.readiness_status == READINESS_READY
    },
    "agibot-g2/map-12": WorldSpec(
        id="agibot-g2/map-12",
        label="Agibot G2 Map 12",
        surface_id="household-world",
        available_backends=("agibot-gdk",),
        scene_source="operator-map",
        tags=("household", "physical-robot", "map-build"),
        default_backend="agibot-gdk",
        resource_kind="physical_robot",
        availability="validation-required",
        optional_validation=True,
    ),
    "b1-map12": WorldSpec(
        id="b1-map12",
        label="B1 / Map 12 Digital Twin",
        surface_id="household-world",
        available_backends=("isaaclab",),
        scene_source="b1-gaussian-digital-twin",
        tags=("household", "digital-twin", "experimental"),
        default_backend="isaaclab",
        resource_kind="gpu",
        availability="validation-required",
        optional_validation=True,
        default_overrides=("robot_views=on",),
    ),
    "planner-proof/default": WorldSpec(
        id="planner-proof/default",
        label="MolmoSpaces Planner Proof",
        surface_id="planner-proof",
        available_backends=("mujoco",),
        scene_source="molmospaces",
        tags=("household", "planner-proof"),
        default_backend="mujoco",
        resource_kind="simulator",
        preview_assets=(("map", "/previews/molmospaces-val_0-map.png"),),
    ),
}


DEFAULT_WORLD_BY_SURFACE: dict[str, str] = {
    "household-world": "molmospaces/procthor-10k-val/0",
    "planner-proof": "planner-proof/default",
}

OPTIONAL_WORLD_DEPENDENCY_SPECS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "agibot-g2/map-12": (
        ("runner_script", "ROBOCLAWS_AGIBOT_RUNNER_SCRIPT", "file"),
        ("runner_python", "ROBOCLAWS_AGIBOT_RUNNER_PYTHON", "executable"),
        ("agibot_map_artifact_dir", "ROBOCLAWS_AGIBOT_MAP_ARTIFACT_DIR", "directory"),
    ),
    "b1-map12": (
        ("map_bundle", "ROBOCLAWS_B1_MAP_BUNDLE", "directory"),
        ("isaac_scene_usd_path", "ROBOCLAWS_B1_SCENE_USD_PATH", "file"),
    ),
}


def resolve_optional_world_dependencies(
    world_id: str,
    *,
    overrides: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    """Resolve and validate private paths only after explicit optional-world selection."""

    status = optional_world_dependency_status(
        world_id,
        overrides=overrides,
        env=env,
        root=root,
    )
    if not status["ok"]:
        raise ValueError(str(status["message"]))
    return dict(status["values"])


def optional_world_dependency_status(
    world_id: str,
    *,
    overrides: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    specs = OPTIONAL_WORLD_DEPENDENCY_SPECS.get(world_id, ())
    override_map = overrides or {}
    env_map = os.environ if env is None else env
    repo_root = Path.cwd() if root is None else Path(root)
    values: dict[str, str] = {}
    missing: list[str] = []
    invalid: list[str] = []
    required = []
    for key, env_key, kind in specs:
        required.append({"input": key, "env": env_key})
        value = str(override_map.get(key) or env_map.get(env_key) or "").strip()
        if not value:
            missing.append(key)
            continue
        if not _optional_dependency_exists(value, kind=kind, root=repo_root):
            invalid.append(key)
            continue
        values[key] = value
    problems = [
        *(f"missing {key}" for key in missing),
        *(f"invalid {key}" for key in invalid),
    ]
    env_hint = ", ".join(item["env"] for item in required)
    message = ""
    if problems:
        message = (
            f"optional validation world {world_id!r} dependency check failed: "
            f"{', '.join(problems)}; pass the named route inputs or set {env_hint}"
        )
    return {
        "ok": not problems,
        "required": required,
        "missing": missing,
        "invalid": invalid,
        "values": values,
        "message": message,
    }


def _optional_dependency_exists(value: str, *, kind: str, root: Path) -> bool:
    if kind == "executable" and shutil.which(value):
        return True
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if kind == "directory":
        return candidate.is_dir()
    if kind == "executable":
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return candidate.is_file()


def world_spec(world_id: str) -> WorldSpec:
    """Return a world spec by id."""

    spec = WORLD_SPECS.get(world_id)
    if spec is not None:
        return spec
    return _source_aware_molmospaces_candidate_world_spec(world_id)


def _source_aware_molmospaces_candidate_world_spec(world_id: str) -> WorldSpec:
    scene_ref = parse_molmospaces_world_id(world_id)
    return WorldSpec(
        id=world_id,
        label=f"MolmoSpaces {scene_ref.scene_source} #{scene_ref.scene_index}",
        surface_id="household-world",
        available_backends=("mujoco",),
        scene_source=scene_ref.scene_source,
        tags=("household", "molmospaces", "source-aware-sampler", "scanner-candidate"),
        default_backend="mujoco",
        resource_kind="simulator",
        availability="hidden",
        default_overrides=(
            f"scene_source={scene_ref.scene_source}",
            f"scene_index={scene_ref.scene_index}",
            molmospaces_nav2_map_bundle_arg(
                scene_source=scene_ref.scene_source,
                scene_index=scene_ref.scene_index,
            ),
        ),
        sampler_metadata={
            "schema": "molmospaces_scene_sampler_world_metadata_v1",
            "scene_source": scene_ref.scene_source,
            "scene_index": scene_ref.scene_index,
            "lanes": [],
            "selected_reason": "dynamic_source_aware_scanner_candidate",
        },
    )
