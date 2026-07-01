from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import mujoco

from roboclaws.household.generated_mess import (
    generated_mess_success_threshold,
    select_generated_mess_targets,
    targets_from_generated_mess_manifest,
)


@dataclass(frozen=True)
class MolmoInitHooks:
    backend: str
    collect_dynamic_objects: Callable[..., list[dict[str, Any]]]
    collect_receptacles: Callable[..., list[dict[str, Any]]]
    collect_room_outlines: Callable[..., list[dict[str, Any]]]
    first_receptacle_id: Callable[..., str | None]
    load_generated_mess_manifest: Callable[..., dict[str, Any]]
    load_model_data: Callable[..., tuple[Any, Any]]
    load_robot_model_data: Callable[..., tuple[Any, Any]]
    ok: Callable[..., dict[str, Any]]
    prepare_molmospaces_scene: Callable[..., tuple[Path, dict[str, Any]]]
    public_scenario: Callable[..., dict[str, Any]]
    refresh_object_positions: Callable[..., None]
    robot_camera_names: Callable[..., list[str]]
    robot_pose_near_receptacle: Callable[..., dict[str, Any]]
    robot_result_payload: Callable[..., dict[str, Any]]
    robot_xml_name: Callable[..., str]
    scenario_id: Callable[..., str]
    seed_misplaced_objects: Callable[..., None]
    set_robot_pose: Callable[..., None]
    source_room_labels: Callable[..., dict[str, dict[str, str]]]
    target_start_receptacle_id: Callable[..., str]
    write_state: Callable[..., None]


def init_state(
    *,
    state_path: Path,
    seed: int,
    scene_source: str,
    scene_index: int,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    generated_mess_count: int = 5,
    generated_mess_object_ids: tuple[str, ...] = (),
    generated_mess_manifest_path: Path | None = None,
    hooks: MolmoInitHooks,
) -> dict[str, Any]:
    from molmo_spaces.molmo_spaces_constants import get_robot_path, get_scenes, get_scenes_root
    from molmo_spaces.utils.lazy_loading_utils import (
        install_scene_with_objects_and_grasps_from_path,
    )
    from molmo_spaces.utils.scene_metadata_utils import get_scene_metadata

    scene_xml, scene_resolution = hooks.prepare_molmospaces_scene(
        scene_source=scene_source,
        scene_index=scene_index,
        get_scenes=get_scenes,
        get_scenes_root=get_scenes_root,
        install_scene_with_objects_and_grasps_from_path=(
            install_scene_with_objects_and_grasps_from_path
        ),
    )
    if not scene_xml.is_file():
        raise FileNotFoundError(scene_xml)

    robot_xml: Path | None = None
    if include_robot:
        robot_xml = get_robot_path(robot_name) / hooks.robot_xml_name(robot_name)
        if not robot_xml.is_file():
            raise FileNotFoundError(robot_xml)
        model, data = hooks.load_robot_model_data(scene_xml, robot_xml)
    else:
        model, data = hooks.load_model_data(scene_xml)
    metadata = get_scene_metadata(scene_xml)
    if metadata is None:
        raise RuntimeError(f"missing scene metadata for {scene_xml}")
    source_room_labels = hooks.source_room_labels(scene_xml)

    receptacles = hooks.collect_receptacles(model, data, metadata)
    objects = hooks.collect_dynamic_objects(model, data, metadata)
    if generated_mess_count < 0:
        raise ValueError("generated_mess_count must be >= 0")
    generated_mess_manifest = hooks.load_generated_mess_manifest(generated_mess_manifest_path)
    targets = _generated_mess_targets(
        objects=objects,
        receptacles=receptacles,
        generated_mess_count=generated_mess_count,
        generated_mess_object_ids=generated_mess_object_ids,
        generated_mess_manifest=generated_mess_manifest,
        seed=seed,
    )

    state = _initial_state_payload(
        backend=hooks.backend,
        data=data,
        generated_mess_count=generated_mess_count,
        generated_mess_manifest=generated_mess_manifest,
        include_robot=include_robot,
        metadata=metadata,
        model=model,
        objects=objects,
        receptacles=receptacles,
        robot_name=robot_name,
        robot_xml=robot_xml,
        scene_index=scene_index,
        scene_resolution=scene_resolution,
        scene_source=scene_source,
        scene_xml=scene_xml,
        seed=seed,
        source_room_labels=source_room_labels,
        targets=targets,
    )
    hooks.seed_misplaced_objects(model, data, state, targets)
    hooks.refresh_object_positions(model, data, state)
    state["room_outlines"] = hooks.collect_room_outlines(model, data, state)
    initial_receptacle_id = (
        hooks.target_start_receptacle_id(state, targets[0])
        if targets
        else hooks.first_receptacle_id(state)
    )
    state["current_receptacle_id"] = initial_receptacle_id
    if include_robot and initial_receptacle_id:
        _initialize_robot_state(model, data, state, initial_receptacle_id, hooks=hooks)
    state["qpos"] = [float(value) for value in data.qpos]
    state["private_manifest"] = _private_manifest(
        scene_source=scene_source,
        scene_index=scene_index,
        seed=seed,
        targets=targets,
        hooks=hooks,
    )
    state["scenario_public"] = hooks.public_scenario(state)
    hooks.write_state(state_path, state)
    return hooks.ok(
        "init",
        backend=hooks.backend,
        scenario=state["scenario_public"],
        private_manifest=state["private_manifest"],
        generated_mess_manifest=state.get("generated_mess_manifest") or None,
        requested_generated_mess_count=state["requested_generated_mess_count"],
        generated_mess_count=state["generated_mess_count"],
        scene_xml=state["scene_xml"],
        scene_resolution=state["scene_resolution"],
        runtime=state["runtime"],
        model_stats=state["model_stats"],
        metadata_object_count=state["metadata_object_count"],
        robot=hooks.robot_result_payload(state, model) if include_robot else None,
    )


def _generated_mess_targets(
    *,
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    generated_mess_count: int,
    generated_mess_object_ids: tuple[str, ...],
    generated_mess_manifest: dict[str, Any],
    seed: int,
) -> list[dict[str, Any]]:
    if generated_mess_manifest:
        targets = targets_from_generated_mess_manifest(
            objects,
            receptacles,
            generated_mess_manifest,
            target_count=generated_mess_count,
        )
    elif generated_mess_count > 0:
        targets = select_generated_mess_targets(
            objects,
            receptacles,
            target_count=generated_mess_count,
            seed=seed,
            object_ids=generated_mess_object_ids or None,
        )
    else:
        targets = []
    if len(targets) < generated_mess_count:
        raise RuntimeError(
            f"expected at least {generated_mess_count} cleanup targets, found {len(targets)}"
        )
    return targets


def _initial_state_payload(
    *,
    backend: str,
    data: Any,
    generated_mess_count: int,
    generated_mess_manifest: dict[str, Any],
    include_robot: bool,
    metadata: dict[str, Any],
    model: Any,
    objects: list[dict[str, Any]],
    receptacles: list[dict[str, Any]],
    robot_name: str,
    robot_xml: Path | None,
    scene_index: int,
    scene_resolution: dict[str, Any],
    scene_source: str,
    scene_xml: Path,
    seed: int,
    source_room_labels: dict[str, dict[str, str]],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "backend": backend,
        "seed": seed,
        "scene_source": scene_source,
        "scene_index": scene_index,
        "scene_xml": str(scene_xml),
        "scene_resolution": scene_resolution,
        "source_room_labels": source_room_labels,
        "robot_included": include_robot,
        "robot_name": robot_name if include_robot else None,
        "robot_xml": str(robot_xml) if robot_xml is not None else None,
        "python_executable": sys.executable,
        "runtime": {
            "python_version": sys.version.split()[0],
            "mujoco_version": mujoco.__version__,
            "mujoco_renderer_runtime": "standard-mujoco",
        },
        "model_stats": {
            "nbody": int(model.nbody),
            "ngeom": int(model.ngeom),
            "njnt": int(model.njnt),
            "nq": int(model.nq),
        },
        "metadata_object_count": len(metadata.get("objects", {})),
        "objects": {item["object_id"]: item for item in objects},
        "receptacles": {item["receptacle_id"]: item for item in receptacles},
        "selected_object_ids": [target["object_id"] for target in targets],
        "generated_mess_manifest": generated_mess_manifest,
        "requested_generated_mess_count": generated_mess_count,
        "generated_mess_count": len(targets),
        "qpos": [float(value) for value in data.qpos],
        "held_object_id": None,
        "current_receptacle_id": None,
        "open_receptacle_ids": [],
        "mess_placement_diagnostics": [],
        "placement_diagnostics": [],
        "tool_event_counts": {},
    }


def _initialize_robot_state(
    model: Any,
    data: Any,
    state: dict[str, Any],
    initial_receptacle_id: str,
    *,
    hooks: MolmoInitHooks,
) -> None:
    initial_receptacle = state["receptacles"][initial_receptacle_id]
    robot_pose = hooks.robot_pose_near_receptacle(state, initial_receptacle)
    hooks.set_robot_pose(model, data, robot_pose)
    state["robot_pose"] = robot_pose
    state["robot_trajectory"] = [robot_pose]
    state["robot_camera_names"] = hooks.robot_camera_names(model)
    state["robot_body_name"] = "robot_0/base"
    state["robot_control_provenance"] = "semantic_robot_base_and_head_qpos"
    state["robot_view_provenance"] = {
        "fpv": "rby1m_head_camera_target_framed",
        "chase": "rby1m_follower_camera",
        "map": "public_sim_state_report",
        "verify": "public_sim_state_report_focus_camera",
    }


def _private_manifest(
    *,
    scene_source: str,
    scene_index: int,
    seed: int,
    targets: list[dict[str, Any]],
    hooks: MolmoInitHooks,
) -> dict[str, Any]:
    return {
        "scenario_id": hooks.scenario_id(
            scene_source=scene_source,
            scene_index=scene_index,
            seed=seed,
        ),
        "success_threshold": generated_mess_success_threshold(len(targets)),
        "targets": [
            {
                "object_id": target["object_id"],
                "valid_receptacle_ids": list(
                    target.get("valid_receptacle_ids") or [target["target_receptacle_id"]]
                ),
            }
            for target in targets
        ],
    }
