from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.household.isaac_lab_backend import ISAACLAB_SUBPROCESS_BACKEND
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE


@dataclass(frozen=True)
class IsaacInitHooks:
    dict_value: Callable[..., dict[str, Any]]
    effective_scene_index: Callable[..., int]
    fallback_room_outlines_from_indices: Callable[..., list[dict[str, Any]]]
    first_target_object_location: Callable[..., str]
    index_or_default: Callable[..., dict[str, Any]]
    initial_receptacle_id: Callable[..., str]
    initial_semantic_pose_state_from_state: Callable[..., dict[str, Any]]
    load_generated_mess_manifest: Callable[..., dict[str, Any]]
    mapping_gap_diagnostics: Callable[..., dict[str, Any]]
    object_index: Callable[..., dict[str, dict[str, Any]]]
    rby1m_robot_import_plan: Callable[..., dict[str, Any]]
    real_runtime_smoke: Callable[..., dict[str, Any]]
    real_smoke_robot_view_images: Callable[..., dict[str, str]]
    receptacle_index: Callable[..., dict[str, dict[str, Any]]]
    robot_payload: Callable[..., dict[str, Any]]
    robot_view_provenance: Callable[..., dict[str, Any]]
    room_outlines_from_scene_index_diagnostics: Callable[..., list[dict[str, Any]]]
    runtime_diagnostics: Callable[..., dict[str, Any]]
    scenario_for_init: Callable[..., Any]
    scenario_source: Callable[..., str]
    scene_binding_diagnostics: Callable[..., dict[str, Any]]
    scene_load_diagnostics: Callable[..., dict[str, Any]]
    scene_specific_scenario_if_needed: Callable[..., Any]
    seed_generated_mess_placements: Callable[..., None]
    segmentation_diagnostics: Callable[..., dict[str, Any]]
    write_placeholder_image: Callable[..., None]
    write_state: Callable[..., None]


def init_state(
    args: Any,
    *,
    hooks: IsaacInitHooks,
    state_schema: str,
    default_width: int,
    default_height: int,
) -> dict[str, Any]:
    args.scene_index = hooks.effective_scene_index(args)
    generated_mess_manifest = hooks.load_generated_mess_manifest(args.generated_mess_manifest_path)
    scenario = hooks.scenario_for_init(
        args,
        generated_mess_manifest=generated_mess_manifest,
    )
    scenario_source = hooks.scenario_source(args)
    real_smoke = _real_runtime_smoke_for_init(args, scenario, hooks=hooks)
    runtime = hooks.runtime_diagnostics(args.runtime_mode, real_smoke=real_smoke)
    scene_load = hooks.scene_load_diagnostics(
        args.runtime_mode,
        args.scene_source,
        args.scene_index,
        real_smoke=real_smoke,
    )
    scene_usd = str(scene_load["scene_usd"])
    object_index = hooks.object_index(scenario)
    receptacle_index = hooks.receptacle_index(scenario)
    scene_index_diagnostics: dict[str, Any] = {
        "status": "placeholder_mapping",
        "source": "scenario_fixture",
        "object_candidate_count": len(object_index),
        "receptacle_candidate_count": len(receptacle_index),
        "blockers": ["Object and receptacle USD prim paths are deterministic placeholders."],
    }
    if real_smoke is not None:
        scene_index_diagnostics = hooks.dict_value(real_smoke.get("scene_index_diagnostics"))
        object_index = hooks.index_or_default(real_smoke.get("object_index"), object_index)
        receptacle_index = hooks.index_or_default(
            real_smoke.get("receptacle_index"), receptacle_index
        )
    room_outlines = hooks.room_outlines_from_scene_index_diagnostics(scene_index_diagnostics)
    if not room_outlines:
        room_outlines = hooks.fallback_room_outlines_from_indices(
            scenario=scenario,
            object_index=object_index,
            receptacle_index=receptacle_index,
        )
        scene_index_diagnostics["room_outline_count"] = len(room_outlines)
        scene_index_diagnostics["room_outlines"] = room_outlines
    scene_binding_diagnostics = hooks.scene_binding_diagnostics(
        runtime_mode=args.runtime_mode,
        scenario=scenario,
        object_index=object_index,
        receptacle_index=receptacle_index,
        real_smoke=real_smoke,
    )
    scene_specific_scenario = hooks.scene_specific_scenario_if_needed(
        args=args,
        generated_mess_manifest=generated_mess_manifest,
        scene_binding_diagnostics=scene_binding_diagnostics,
        object_index=object_index,
        receptacle_index=receptacle_index,
        real_smoke=real_smoke,
    )
    if scene_specific_scenario is not None:
        scenario = scene_specific_scenario
        scenario_source = "isaac_scene_index"
        scene_binding_diagnostics = hooks.scene_binding_diagnostics(
            runtime_mode=args.runtime_mode,
            scenario=scenario,
            object_index=object_index,
            receptacle_index=receptacle_index,
            real_smoke=real_smoke,
        )
    segmentation = hooks.segmentation_diagnostics(
        runtime_mode=args.runtime_mode,
        real_smoke=real_smoke,
        scene_binding_diagnostics=scene_binding_diagnostics,
    )
    mapping_gaps = hooks.mapping_gap_diagnostics(
        runtime_mode=args.runtime_mode,
        map_bundle_dir=args.map_bundle_dir,
        real_smoke=real_smoke,
        scene_binding_diagnostics=scene_binding_diagnostics,
        segmentation=segmentation,
    )
    runtime["scenario_source"] = scenario_source
    initial_receptacle_id = hooks.initial_receptacle_id(scenario)
    before_path = args.run_dir / "isaac_runtime_smoke.png"
    if real_smoke is not None:
        before_path = Path(str(real_smoke["image_path"]))
        if not before_path.is_file():
            raise RuntimeError(f"real Isaac smoke image is missing: {before_path}")
    state = _initial_state_payload(
        args=args,
        state_schema=state_schema,
        runtime=runtime,
        scene_load=scene_load,
        scene_usd=scene_usd,
        scenario=scenario,
        scenario_source=scenario_source,
        generated_mess_manifest=generated_mess_manifest,
        real_smoke=real_smoke,
        initial_receptacle_id=initial_receptacle_id,
        mapping_gaps=mapping_gaps,
        object_index=object_index,
        receptacle_index=receptacle_index,
        room_outlines=room_outlines,
        scene_index_diagnostics=scene_index_diagnostics,
        scene_binding_diagnostics=scene_binding_diagnostics,
        segmentation=segmentation,
        hooks=hooks,
    )
    hooks.seed_generated_mess_placements(state)
    state["current_receptacle_id"] = (
        hooks.first_target_object_location(state) or initial_receptacle_id
    )
    state["semantic_pose_state"] = hooks.initial_semantic_pose_state_from_state(state)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    hooks.write_state(args.state_path, state)
    if real_smoke is None:
        hooks.write_placeholder_image(
            before_path,
            title="Isaac Lab runtime smoke",
            subtitle=runtime["renderer_mode"],
            state=state,
            width=default_width,
            height=default_height,
        )
    return _init_response(
        args=args,
        state=state,
        runtime=runtime,
        scene_load=scene_load,
        scene_index_diagnostics=scene_index_diagnostics,
        scene_binding_diagnostics=scene_binding_diagnostics,
        mapping_gaps=mapping_gaps,
        before_path=before_path,
        scenario_source=scenario_source,
    )


def _real_runtime_smoke_for_init(
    args: Any,
    scenario: Any,
    *,
    hooks: IsaacInitHooks,
) -> dict[str, Any] | None:
    if args.runtime_mode != "real":
        return None
    try:
        return hooks.real_runtime_smoke(args, scenario)
    except Exception as exc:
        raise RuntimeError(
            "Real Isaac runtime smoke failed before backend init could prove "
            "renderer/USD evidence. Run `just agent::harness "
            "molmo-isaac-runtime-preflight` first and keep CI-only protocol "
            "tests on ROBOCLAWS_ISAACLAB_RUNTIME_MODE=fake."
        ) from exc


def _initial_state_payload(
    *,
    args: Any,
    state_schema: str,
    runtime: dict[str, Any],
    scene_load: dict[str, Any],
    scene_usd: str,
    scenario: Any,
    scenario_source: str,
    generated_mess_manifest: dict[str, Any],
    real_smoke: dict[str, Any] | None,
    initial_receptacle_id: str,
    mapping_gaps: dict[str, Any],
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
    room_outlines: list[dict[str, Any]],
    scene_index_diagnostics: dict[str, Any],
    scene_binding_diagnostics: dict[str, Any],
    segmentation: dict[str, Any],
    hooks: IsaacInitHooks,
) -> dict[str, Any]:
    return {
        "schema": state_schema,
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "runtime": runtime,
        "scene_load": scene_load,
        "scene_source": args.scene_source,
        "scene_index": args.scene_index,
        "scene_usd": scene_usd,
        "scenario_source": scenario_source,
        "real_runtime_smoke": real_smoke,
        "requested_generated_mess_count": args.generated_mess_count,
        "scenario": scenario.public_payload(),
        "private_manifest": scenario.private_manifest.to_private_dict(),
        "generated_mess_manifest": generated_mess_manifest,
        "locations": scenario.object_locations(),
        "held_object_id": None,
        "current_receptacle_id": initial_receptacle_id,
        "open_receptacle_ids": [],
        "containment": {},
        "object_pose_overrides": {},
        "mess_placement_diagnostics": [],
        "tool_event_counts": {},
        "placement_diagnostics": [],
        "mapping_gaps": mapping_gaps,
        "object_index": object_index,
        "receptacle_index": receptacle_index,
        "room_outlines": room_outlines,
        "scene_index_diagnostics": scene_index_diagnostics,
        "scene_binding_diagnostics": scene_binding_diagnostics,
        "robot_view_images": hooks.real_smoke_robot_view_images(real_smoke),
        "robot_view_provenance": hooks.robot_view_provenance(args.runtime_mode, real_smoke),
        "native_render_diagnostics": hooks.dict_value(
            hooks.dict_value(runtime.get("rendering")).get("native_render_diagnostics")
        ),
        "segmentation": segmentation,
        "robot": hooks.robot_payload(args.robot_name) if args.include_robot else None,
        "robot_import": (
            hooks.rby1m_robot_import_plan(args.robot_name) if args.include_robot else None
        ),
    }


def _init_response(
    *,
    args: Any,
    state: dict[str, Any],
    runtime: dict[str, Any],
    scene_load: dict[str, Any],
    scene_index_diagnostics: dict[str, Any],
    scene_binding_diagnostics: dict[str, Any],
    mapping_gaps: dict[str, Any],
    before_path: Path,
    scenario_source: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": "init",
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "scenario": state["scenario"],
        "private_manifest": state["private_manifest"],
        "generated_mess_manifest": state.get("generated_mess_manifest") or None,
        "runtime": runtime,
        "scene_usd": state["scene_usd"],
        "scene_load": scene_load,
        "scene_index": args.scene_index,
        "scenario_source": scenario_source,
        "scene_index_diagnostics": scene_index_diagnostics,
        "scene_binding_diagnostics": scene_binding_diagnostics,
        "object_index": state["object_index"],
        "receptacle_index": state["receptacle_index"],
        "mapping_gaps": mapping_gaps,
        "segmentation": state["segmentation"],
        "native_render_diagnostics": state["native_render_diagnostics"],
        "requested_generated_mess_count": args.generated_mess_count,
        "generated_mess_count": len(state["private_manifest"]["targets"]),
        "robot": state["robot"],
        "robot_import": state["robot_import"],
        "artifacts": {
            "runtime_smoke_image": str(before_path),
            "robot_view_images": state["robot_view_images"],
        },
    }
