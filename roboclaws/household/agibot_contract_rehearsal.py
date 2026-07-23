from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import roboclaws.household.task_intent as intent_helpers
from roboclaws.core.json_sources import read_json_object
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_contract_rehearsal_evidence import (
    blocked_manipulation_evidence as _blocked_manipulation_evidence,
)
from roboclaws.household.agibot_contract_rehearsal_evidence import (
    cleanup_action_manipulation_evidence as _cleanup_action_manipulation_evidence,
)
from roboclaws.household.agibot_contract_rehearsal_evidence import (
    private_evaluation as _private_evaluation,
)
from roboclaws.household.agibot_contract_rehearsal_evidence import (
    readiness_payload as _readiness_payload,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    AGIBOT_SHAPED_SIM_BACKEND,
    EXECUTION_BACKEND,
    NAVIGATION_BACKEND,
    NAVIGATION_PROVENANCE,
    OBSERVATION_PROVENANCE,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    relpath as _relpath,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    simulated_navigation as _simulated_navigation,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    simulated_observation as _simulated_observation,
)
from roboclaws.household.agibot_sdk_runner import BLOCKED_MANIPULATION_TOOLS
from roboclaws.household.backend import API_SEMANTIC_PROVENANCE
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    CLEANUP_WORKLIST_SCHEMA,
    RAW_FPV_ONLY_MODE,
    REALWORLD_CONTRACT,
    RUNTIME_METRIC_MAP_SCHEMA,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    HouseholdRuntimeContract,
    forbidden_agent_view_keys,
)
from roboclaws.household.household_world_episode import (
    SYNTHETIC_BACKEND,
    run_household_world_episode,
)
from roboclaws.household.manipulation_provenance import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.report import (
    write_state_snapshot,
)
from roboclaws.household.semantic_cleanup_loop import (
    SemanticCleanupLoopResult,
    run_semantic_cleanup_loop,
)
from roboclaws.household.semantic_timeline import (
    ROBOT_VIEW_VARIANT,
    record_robot_view_step,
    robot_view_capture_for_tool,
)
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend
from roboclaws.household.types import CleanupScenario
from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_path
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)

REHEARSAL_SCHEMA = "molmospaces_agibot_contract_rehearsal_v1"
CONFIDENCE_LAYER = "MolmoSpaces Agibot Contract Rehearsal"
CLEANUP_ACTION_CONFIDENCE_LAYER = "MolmoSpaces Agibot Cleanup Action Rehearsal"
RUNTIME_FIXTURE = "fixture"
RUNTIME_MOLMOSPACES_SUBPROCESS = "molmospaces-subprocess"
REHEARSAL_MODE_CONTRACT = "contract"
REHEARSAL_MODE_CLEANUP_ACTIONS = "cleanup-actions"
PRE_HARDWARE_CONFIDENCE_LAYER = "Agibot MolmoSpaces Base Metric Map Pre-Hardware Rehearsal"


def run_molmospaces_agibot_contract_rehearsal(
    *,
    run_dir: Path,
    seed: int = 7,
    generated_mess_count: int = 5,
    runtime: str = RUNTIME_FIXTURE,
    waypoint_id: str | None = None,
    molmospaces_python: Path | None = None,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    rehearsal_mode: str = REHEARSAL_MODE_CONTRACT,
    cleanup_object_count: int = 2,
    record_robot_views: bool = False,
    context_json: Path | None = None,
    agibot_map_artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the Agibot-shaped cleanup contract against simulated MolmoSpaces semantics."""

    from roboclaws.household.agibot_contract_rehearsal_stages import (
        _ContractRehearsalOptions,
        run_contract_rehearsal,
    )

    return run_contract_rehearsal(
        run_dir=run_dir,
        options=_ContractRehearsalOptions(
            seed=seed,
            generated_mess_count=generated_mess_count,
            runtime=runtime,
            waypoint_id=waypoint_id,
            molmospaces_python=molmospaces_python,
            include_robot=include_robot,
            robot_name=robot_name,
            rehearsal_mode=rehearsal_mode,
            cleanup_object_count=cleanup_object_count,
            record_robot_views=record_robot_views,
            context_json=context_json,
            agibot_map_artifact_dir=agibot_map_artifact_dir,
        ),
    )


def run_molmospaces_agibot_prehardware_rehearsal(
    *,
    run_dir: Path,
    intent: str,
    profile: str,
    task_prompt: str | None = None,
    seed: int = 7,
    generated_mess_count: int = 5,
    runtime: str = RUNTIME_FIXTURE,
    molmospaces_python: Path | None = None,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    record_robot_views: bool = False,
    cleanup_object_count: int = 2,
    context_json: Path | None = None,
    agibot_map_artifact_dir: Path | None = None,
    camera_labeler: str | None = None,
    visual_grounding: str = "grounding-dino",
    visual_grounding_base_url: str | None = None,
    visual_grounding_timeout_s: float | None = None,
    map_bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the Agibot/MolmoSpaces local rehearsal as a robot-like Base Metric Map flow."""

    intent = intent_helpers.normalize_household_intent(intent)
    if runtime not in {RUNTIME_FIXTURE, RUNTIME_MOLMOSPACES_SUBPROCESS}:
        expected = f"{RUNTIME_FIXTURE}|{RUNTIME_MOLMOSPACES_SUBPROCESS}"
        raise ValueError(f"unsupported rehearsal runtime {runtime!r} (expected {expected})")
    if cleanup_object_count < 1:
        raise ValueError("cleanup_object_count must be >= 1")

    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    task_identity = intent_helpers.household_task_identity(intent=intent)
    is_map_build = intent == intent_helpers.HOUSEHOLD_INTENT_MAP_BUILD
    default_task_prompt = (
        "帮我建立这个房间的 Runtime Metric Map" if is_map_build else "帮我收拾这个房间"
    )
    selected_task_prompt = str(task_prompt or default_task_prompt)
    perception_mode = _prehardware_perception_mode(profile)
    backend = SYNTHETIC_BACKEND if runtime == RUNTIME_FIXTURE else "molmospaces_subprocess"
    if runtime == RUNTIME_MOLMOSPACES_SUBPROCESS and not include_robot:
        include_robot = True
    if runtime == RUNTIME_MOLMOSPACES_SUBPROCESS and profile in {
        "camera-raw-fpv",
        "camera-grounded-labels",
    }:
        record_robot_views = True if record_robot_views is False else record_robot_views

    preflight_dir = run_dir / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    agibot_map_reference = _agibot_map_reference(
        context_json=context_json,
        agibot_map_artifact_dir=agibot_map_artifact_dir,
    )
    agibot_map_reference_path = preflight_dir / "agibot_map_reference.json"
    agibot_map_reference_path.write_text(
        json.dumps(agibot_map_reference, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    metadata_overrides = _prehardware_metadata_overrides(
        task_identity=task_identity,
        profile=profile,
        runtime=runtime,
        visual_grounding=visual_grounding,
        camera_labeler=camera_labeler,
        agibot_map_reference=agibot_map_reference,
        cleanup_actions_disabled=is_map_build,
    )
    result = run_household_world_episode(
        output_dir=run_dir,
        seed=seed,
        task_prompt=selected_task_prompt,
        backend=backend,
        static_fixture_projection_mode="room_only",
        perception_mode=perception_mode,
        include_robot=include_robot,
        robot_name=robot_name,
        molmospaces_python=molmospaces_python,
        record_robot_views=record_robot_views,
        generated_mess_count=generated_mess_count,
        map_bundle_dir=map_bundle_dir
        or molmospaces_nav2_map_bundle_path(scene_source="procthor-10k-val", scene_index=0),
        evidence_lane=profile if runtime == RUNTIME_MOLMOSPACES_SUBPROCESS else None,
        intent=("map-build" if is_map_build else "cleanup"),
        visual_grounding=visual_grounding,
        visual_grounding_base_url=visual_grounding_base_url,
        visual_grounding_timeout_s=visual_grounding_timeout_s,
        run_metadata_overrides=metadata_overrides,
    )
    _write_prehardware_runtime_export(
        run_dir=run_dir,
        result=result,
        task_identity=task_identity,
        task_prompt=selected_task_prompt,
        runtime=runtime,
        profile=profile,
        camera_labeler=camera_labeler,
        visual_grounding=visual_grounding,
        agibot_map_reference_path=agibot_map_reference_path,
        cleanup_object_count=cleanup_object_count,
    )
    return result


def _agibot_shaped_metric_map(metric_map: dict[str, Any], *, seed: int) -> dict[str, Any]:
    payload = copy.deepcopy(metric_map)
    payload["map_id"] = f"molmospaces-agibot-contract-rehearsal-{seed}"
    payload["map_version"] = "molmospaces-sim-agibot-shaped-v1"
    payload["execution_backend"] = EXECUTION_BACKEND
    payload["simulated"] = True
    payload["physical_robot"] = False
    payload["public_contract_note"] = (
        "Agibot-shaped preflight metric_map generated from a MolmoSpaces cleanup "
        "scene. This is simulated contract-shape evidence, not a real Agibot map "
        "fetch or GDK current-map export."
    )
    for waypoint in payload.get("inspection_waypoints") or []:
        waypoint["reachability_status"] = "verified"
        waypoint["waypoint_source"] = "molmospaces_sim_agibot_shaped_preflight"
        waypoint["verification"] = {
            "schema": "agibot_shaped_molmospaces_waypoint_verification_v1",
            "reachability_status": "verified",
            "navigation_backend": NAVIGATION_BACKEND,
            "primitive_provenance": NAVIGATION_PROVENANCE,
            "simulated": True,
            "physical_robot": False,
        }
    return payload


def _prehardware_perception_mode(profile: str) -> str:
    if profile == "camera-raw-fpv":
        return RAW_FPV_ONLY_MODE
    if profile == "camera-grounded-labels":
        return CAMERA_MODEL_POLICY_MODE
    if profile == "world-public-labels":
        return VISIBLE_OBJECT_DETECTIONS_MODE
    raise ValueError(
        f"unsupported Agibot MolmoSpaces pre-hardware lane {profile!r} "
        "(expected world-public-labels|camera-raw-fpv|camera-grounded-labels)"
    )


def _prehardware_metadata_overrides(
    *,
    task_identity: dict[str, str],
    profile: str,
    runtime: str,
    visual_grounding: str,
    camera_labeler: str | None,
    agibot_map_reference: dict[str, Any],
    cleanup_actions_disabled: bool,
) -> dict[str, Any]:
    intent = task_identity["task_intent"]
    return {
        "schema": REHEARSAL_SCHEMA,
        "report_eyebrow": "Agibot-shaped pre-hardware rehearsal",
        "report_title": (
            "Agibot MolmoSpaces Map-Build Rehearsal"
            if intent == intent_helpers.HOUSEHOLD_INTENT_MAP_BUILD
            else "Agibot MolmoSpaces Cleanup Rehearsal"
        ),
        "confidence_layer": PRE_HARDWARE_CONFIDENCE_LAYER,
        "confidence_layer_summary": (
            "Runs the shared MolmoSpaces cleanup harness as an Agibot-shaped "
            "pre-hardware rehearsal: Base Metric Map first, generated exploration "
            "candidates, online observations, Runtime Metric Map output, and "
            "RAW_FPV/camera-grounded-labels perception evidence. It is simulated and not "
            "Agibot GDK hardware proof."
        ),
        "next_confidence_layer": "Real Agibot G2 intent=map-build hardware run",
        "backend": AGIBOT_SHAPED_SIM_BACKEND,
        "backend_variant": EXECUTION_BACKEND,
        "execution_backend": EXECUTION_BACKEND,
        "navigation_backend": NAVIGATION_BACKEND,
        "runtime": runtime,
        "evidence_lane": profile,
        "camera_labeler": camera_labeler or "",
        "mcp_server": "roboclaws_household_agibot_molmospaces_prehardware",
        **task_identity,
        "agibot_molmospaces_prehardware_rehearsal": {
            "schema": "agibot_molmospaces_base_metric_map_prehardware_rehearsal_v1",
            **task_identity,
            "confidence_layer": PRE_HARDWARE_CONFIDENCE_LAYER,
            "runtime": runtime,
            "profile": profile,
            "evidence_lane": profile,
            "camera_labeler": camera_labeler or "",
            "input_lane_note": (
                "fixture runtime uses synthetic rendering for fast local rehearsal; "
                "select runtime=molmospaces-subprocess for real MolmoSpaces RAW_FPV/"
                "camera-label image artifacts."
                if runtime == RUNTIME_FIXTURE
                else "MolmoSpaces subprocess runtime supplies local simulator camera evidence."
            ),
            "visual_grounding_pipeline_id": visual_grounding,
            "base_metric_map_start": True,
            "online_map_build": True,
            "cleanup_actions_included": intent == intent_helpers.HOUSEHOLD_INTENT_CLEANUP,
            "cleanup_actions_disabled": cleanup_actions_disabled,
            "source_map_mutation_allowed": False,
            "simulated": True,
            "physical_robot": False,
            "execution_backend": EXECUTION_BACKEND,
            "navigation_backend": NAVIGATION_BACKEND,
            "agibot_map_reference": "preflight/agibot_map_reference.json",
            "agibot_map_reference_summary": {
                "status": agibot_map_reference.get("status", ""),
                "used_as_scene_source": False,
                "used_for_navigation_execution": False,
            },
            "acceptance_gates": [
                "runtime_metric_map.json exists",
                "metric_map.base_metric_map.enabled=true",
                "generated exploration candidates are visited or reported unvisited",
                "agent view does not contain private truth",
                "RAW_FPV/camera-grounded-labels observations create public runtime evidence",
            ],
            "public_contract_note": (
                "This is the local pre-hardware flow Roboclaws can run before a G2 "
                "session. MolmoSpaces supplies simulated world and camera evidence; "
                "Agibot map artifacts, when supplied, are reference-only."
            ),
        },
        "agibot_map_reference": agibot_map_reference,
        "simulated": True,
        "physical_robot": False,
    }


def _write_prehardware_runtime_export(
    *,
    run_dir: Path,
    result: dict[str, Any],
    task_identity: dict[str, str],
    task_prompt: str,
    runtime: str,
    profile: str,
    camera_labeler: str | None,
    visual_grounding: str,
    agibot_map_reference_path: Path,
    cleanup_object_count: int,
) -> None:
    runtime_dir = run_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    agent_view = result.get("agent_view") or {}
    runtime_metric_map = result.get("runtime_metric_map") or agent_view_module.runtime_metric_map(
        agent_view
    )
    metric_map = agent_view_module.base_metric_map(agent_view)
    payload = {
        "schema": "agibot_molmospaces_base_metric_map_prehardware_runtime_export_v1",
        **task_identity,
        "task_prompt": task_prompt,
        "runtime": runtime,
        "profile": profile,
        "evidence_lane": profile,
        "camera_labeler": camera_labeler or "",
        "visual_grounding_pipeline_id": visual_grounding,
        "base_metric_map_start": True,
        "online_map_build": True,
        "cleanup_actions_included": task_identity["task_intent"]
        == intent_helpers.HOUSEHOLD_INTENT_CLEANUP,
        "cleanup_object_count_limit": cleanup_object_count,
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "navigation_backend": NAVIGATION_BACKEND,
        "runtime_metric_map": "runtime_metric_map.json",
        "agent_view": "agent_view.json",
        "agibot_map_reference": _relpath(agibot_map_reference_path, run_dir),
        "runtime_metric_map_summary": {
            "schema": runtime_metric_map.get("schema", ""),
            "base_metric_map_enabled": bool(
                (metric_map.get("base_metric_map") or {}).get("enabled")
            ),
            "source_map_mutated": runtime_metric_map.get("source_map_mutated"),
            "observed_object_count": len(runtime_metric_map.get("observed_objects") or []),
            "public_semantic_anchor_count": len(
                runtime_metric_map.get("public_semantic_anchors") or []
            ),
            "generated_exploration_candidate_count": len(
                runtime_metric_map.get("generated_exploration_candidates") or []
            ),
        },
        "raw_fpv_observation_count": len(result.get("raw_fpv_observations") or []),
        "model_declared_observation_count": len(result.get("model_declared_observations") or []),
        "semantic_substep_count": len(result.get("semantic_substeps") or []),
    }
    (runtime_dir / "runtime_export.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _agibot_shaped_static_fixture_projection(
    static_fixture_projection: dict[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(static_fixture_projection)
    payload["static_fixture_projection_mode"] = "molmospaces_sim_static_fixture_map"
    payload["execution_backend"] = EXECUTION_BACKEND
    payload["simulated"] = True
    payload["physical_robot"] = False
    payload["public_contract_note"] = (
        "Agibot-shaped static_fixture_projection generated from public MolmoSpaces static "
        "fixture semantics. No private cleanup target truth or real GDK map state "
        "is exposed."
    )
    return payload


def _write_preflight_artifacts(
    *,
    run_dir: Path,
    scenario: CleanupScenario,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    runtime: str,
    seed: int,
    generated_mess_count: int,
    backend_instance: MolmoSpacesSubprocessBackend | None,
    context_json: Path | None,
    agibot_map_artifact_dir: Path | None,
) -> dict[str, Path]:
    preflight_dir = run_dir / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    scene_identity = _scene_identity(
        scenario=scenario,
        runtime=runtime,
        seed=seed,
        generated_mess_count=generated_mess_count,
        backend_instance=backend_instance,
    )
    agibot_map_reference = _agibot_map_reference(
        context_json=context_json,
        agibot_map_artifact_dir=agibot_map_artifact_dir,
    )
    map_preview = _write_metric_map_preview(
        output_path=preflight_dir / "molmospaces_metric_map.png",
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        scene_identity=scene_identity,
    )
    agent_view = _agibot_shaped_agent_view(
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        observed_objects=[],
        raw_fpv_observations=[],
        perception_mode="robot_policy_camera",
        structured_detections_available=False,
    )
    waypoint_sequence = {
        "schema": "agibot_shaped_waypoint_sequence_v1",
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "waypoints": [
            {
                "waypoint_id": str(item.get("waypoint_id") or ""),
                "room_id": str(item.get("room_id") or ""),
                "fixture_id": str(item.get("fixture_id") or ""),
                "purpose": str(item.get("purpose") or ""),
                "navigation_backend": NAVIGATION_BACKEND,
                "primitive_provenance": NAVIGATION_PROVENANCE,
            }
            for item in metric_map.get("inspection_waypoints") or []
        ],
    }
    runner_task_input = {
        "schema": "agibot_shaped_cleanup_runner_task_input_v1",
        "contract": REALWORLD_CONTRACT,
        "task_prompt": scenario.task,
        "seed": seed,
        "requested_generated_mess_count": generated_mess_count,
        "runtime": runtime,
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "public_tool_sequence": [
            "metric_map",
            "observe",
            "navigate_to_waypoint",
            *BLOCKED_MANIPULATION_TOOLS,
        ],
        "stage_mapping": {
            "agent_view_export": ["metric_map"],
            "observe": ["observe"],
            "navigate_waypoint": ["navigate_to_waypoint"],
            "blocked_manipulation": list(BLOCKED_MANIPULATION_TOOLS),
        },
        "evidence_note": (
            "This input is Agibot-shaped for runner-contract rehearsal, but it is "
            "not a real Agibot SDK task input and does not enable GDK movement."
        ),
        "agibot_map_reference": agibot_map_reference,
    }
    paths = {
        "metric_map": preflight_dir / "metric_map.json",
        "static_fixture_projection": preflight_dir / "static_fixture_projection.json",
        "agent_view": preflight_dir / "agent_view.json",
        "scene_identity": preflight_dir / "scene_identity.json",
        "map_preview": map_preview,
        "waypoint_sequence": preflight_dir / "waypoint_sequence.json",
        "runner_task_input": preflight_dir / "runner_task_input.json",
        "agibot_map_reference": preflight_dir / "agibot_map_reference.json",
    }
    values = {
        "metric_map": metric_map,
        "static_fixture_projection": static_fixture_projection,
        "agent_view": agent_view,
        "scene_identity": scene_identity,
        "waypoint_sequence": waypoint_sequence,
        "runner_task_input": runner_task_input,
        "agibot_map_reference": agibot_map_reference,
    }
    for key, path in paths.items():
        if key == "map_preview":
            continue
        path.write_text(json.dumps(values[key], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return paths


def _agibot_map_reference(
    *,
    context_json: Path | None,
    agibot_map_artifact_dir: Path | None,
) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "schema": "agibot_map_reference_for_molmospaces_sim_v1",
        "status": "not_supplied" if context_json is None else "referenced_for_contract_only",
        "used_as_scene_source": False,
        "used_for_navigation_execution": False,
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "public_contract_note": (
            "MolmoSpaces remains the simulated scene/backend. Any Agibot context "
            "or map artifact is recorded only as reference evidence for comparing "
            "public contract shape; it is not used as a MolmoSpaces digital twin."
        ),
    }
    if context_json is None:
        return reference

    context_path = Path(context_json)
    context = _load_json(context_path)
    reference.update(
        {
            "context_json": str(context_path),
            "context_schema": str(context.get("schema") or ""),
            "environment_id": str(context.get("environment_id") or ""),
            "map_version": str(context.get("map_version") or ""),
            "frame_id": str(context.get("frame_id") or ""),
            "room_count": len(context.get("rooms") or []),
            "fixture_count": len(context.get("fixtures") or []),
            "inspection_waypoint_count": len(context.get("inspection_waypoints") or []),
        }
    )
    map_source = context.get("map_source") or {}
    if isinstance(map_source, dict):
        reference["map_source"] = {
            "type": str(map_source.get("type") or ""),
            "id": str(map_source.get("id") or ""),
            "name": str(map_source.get("name") or ""),
        }
    if agibot_map_artifact_dir is not None:
        artifact_dir = Path(agibot_map_artifact_dir)
        reference["agibot_map_artifact_dir"] = str(artifact_dir)
        reference["agibot_map_artifact_present"] = artifact_dir.exists()
    return reference


def _scene_identity(
    *,
    scenario: CleanupScenario,
    runtime: str,
    seed: int,
    generated_mess_count: int,
    backend_instance: MolmoSpacesSubprocessBackend | None,
) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "schema": "molmospaces_agibot_rehearsal_scene_identity_v1",
        "scenario_id": scenario.scenario_id,
        "task_prompt": scenario.task,
        "seed": seed,
        "requested_generated_mess_count": generated_mess_count,
        "runtime": runtime,
        "execution_backend": EXECUTION_BACKEND,
        "navigation_backend": NAVIGATION_BACKEND,
        "simulated": True,
        "physical_robot": False,
        "scene_source": "deterministic_fixture_projection"
        if runtime == RUNTIME_FIXTURE
        else "molmospaces_subprocess",
        "scene_source_note": (
            "CI-safe fixture projection of the MolmoSpaces cleanup contract. "
            "No MuJoCo scene_xml was loaded in this run."
            if runtime == RUNTIME_FIXTURE
            else "Live MolmoSpaces subprocess scene evidence from the optional runtime."
        ),
        "object_count": len(scenario.objects),
        "fixture_count": len(scenario.receptacles),
    }
    if backend_instance is not None:
        identity.update(
            {
                "scene_xml": backend_instance.scene_xml,
                "molmospaces_runtime": backend_instance.runtime,
                "model_stats": backend_instance.model_stats,
                "metadata_object_count": backend_instance.metadata_object_count,
                "actual_generated_mess_count": backend_instance.generated_mess_count,
                "robot": backend_instance.robot,
            }
        )
    return identity


def _write_metric_map_preview(
    *,
    output_path: Path,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    scene_identity: dict[str, Any],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1080, 620
    margin = 58
    image = Image.new("RGB", (width, height), (246, 248, 251))
    draw = ImageDraw.Draw(image)
    rooms = [room for room in metric_map.get("rooms") or [] if isinstance(room, dict)]
    fixtures = _fixtures(static_fixture_projection)
    waypoints = [item for item in metric_map.get("inspection_waypoints") or []]
    bounds = _map_bounds(rooms=rooms, fixtures=fixtures, waypoints=waypoints)

    def xy(x_value: Any, y_value: Any) -> tuple[float, float]:
        x = float(x_value)
        y = float(y_value)
        span_x = max(bounds["max_x"] - bounds["min_x"], 1.0)
        span_y = max(bounds["max_y"] - bounds["min_y"], 1.0)
        px = margin + ((x - bounds["min_x"]) / span_x) * (width - margin * 2)
        py = height - margin - ((y - bounds["min_y"]) / span_y) * (height - margin * 2)
        return px, py

    draw.text((24, 20), "MolmoSpaces Agibot Contract Rehearsal Map", fill=(26, 36, 54))
    subtitle = (
        f"runtime={scene_identity.get('runtime')} | scenario={scene_identity.get('scenario_id')} | "
        f"source={scene_identity.get('scene_source')}"
    )
    draw.text((24, 42), subtitle, fill=(84, 96, 116))

    palette = [
        (222, 237, 253),
        (227, 242, 230),
        (250, 238, 218),
        (238, 231, 248),
        (244, 229, 232),
    ]
    for index, room in enumerate(rooms):
        polygon = room.get("polygon") or []
        points = [xy(point["x"], point["y"]) for point in polygon if {"x", "y"} <= set(point)]
        if len(points) < 3:
            continue
        fill = palette[index % len(palette)]
        draw.polygon(points, fill=fill, outline=(112, 128, 149))
        label_x = sum(point[0] for point in points) / len(points)
        label_y = sum(point[1] for point in points) / len(points)
        draw.text(
            (label_x - 36, label_y - 8),
            str(room.get("room_label") or room.get("room_id") or "room"),
            fill=(39, 52, 74),
        )

    for fixture in fixtures:
        pose = fixture.get("pose") or {}
        if "x" not in pose or "y" not in pose:
            continue
        x, y = xy(pose["x"], pose["y"])
        draw.rounded_rectangle((x - 8, y - 8, x + 8, y + 8), radius=3, fill=(48, 86, 154))
        draw.text(
            (x + 10, y - 7),
            str(fixture.get("name") or fixture.get("fixture_id")),
            fill=(29, 44, 68),
        )

    for waypoint in waypoints:
        if "x" not in waypoint or "y" not in waypoint:
            continue
        x, y = xy(waypoint["x"], waypoint["y"])
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(210, 90, 55))
        draw.text((x + 8, y + 4), str(waypoint.get("waypoint_id") or ""), fill=(110, 57, 42))

    legend_y = height - 34
    draw.rounded_rectangle((24, legend_y - 8, 40, legend_y + 8), radius=3, fill=(48, 86, 154))
    draw.text((48, legend_y - 8), "fixture", fill=(65, 76, 96))
    draw.ellipse((126, legend_y - 8, 142, legend_y + 8), fill=(210, 90, 55))
    draw.text((150, legend_y - 8), "inspection waypoint", fill=(65, 76, 96))
    image.save(output_path, format="PNG")
    return output_path


def _map_bounds(
    *,
    rooms: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    waypoints: list[dict[str, Any]],
) -> dict[str, float]:
    xs: list[float] = []
    ys: list[float] = []
    for room in rooms:
        for point in room.get("polygon") or []:
            if "x" in point and "y" in point:
                xs.append(float(point["x"]))
                ys.append(float(point["y"]))
    for fixture in fixtures:
        pose = fixture.get("pose") or {}
        if "x" in pose and "y" in pose:
            xs.append(float(pose["x"]))
            ys.append(float(pose["y"]))
    for waypoint in waypoints:
        if "x" in waypoint and "y" in waypoint:
            xs.append(float(waypoint["x"]))
            ys.append(float(waypoint["y"]))
    if not xs or not ys:
        return {"min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0}
    pad_x = max((max(xs) - min(xs)) * 0.08, 0.5)
    pad_y = max((max(ys) - min(ys)) * 0.18, 0.5)
    return {
        "min_x": min(xs) - pad_x,
        "max_x": max(xs) + pad_x,
        "min_y": min(ys) - pad_y,
        "max_y": max(ys) + pad_y,
    }


def _agent_view_with_runtime_observation(
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    detections = [
        {
            "object_id": str(item.get("object_id") or ""),
            "category": str(item.get("category") or ""),
            "current_room_id": str(item.get("room_id") or observation.get("room_id") or ""),
            "support_estimate": item.get("support_estimate") or {},
            "source_observation_id": observation.get("observation_id", ""),
        }
        for item in observation.get("visible_object_detections") or []
    ]
    return {
        **_agibot_shaped_agent_view(
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
            observed_objects=detections,
            raw_fpv_observations=[observation["raw_fpv_observation"]],
            perception_mode="robot_policy_camera",
            structured_detections_available=True,
        ),
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
    }


def _agent_view_with_cleanup_actions(
    payload: dict[str, Any],
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    fallback_observation: dict[str, Any],
) -> dict[str, Any]:
    agent_view = copy.deepcopy(payload)
    raw_observations = agent_view_module.raw_fpv_observations(agent_view)
    if not raw_observations and fallback_observation.get("raw_fpv_observation"):
        raw_observations = [fallback_observation["raw_fpv_observation"]]
    agent_view = _agibot_shaped_agent_view(
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        observed_objects=agent_view_module.observed_objects(agent_view),
        raw_fpv_observations=raw_observations,
        perception_mode=agent_view_module.perception_mode(agent_view),
        structured_detections_available=agent_view_module.structured_detections_available(
            agent_view
        ),
        camera_model_policy_evidence=agent_view_module.camera_model_policy_evidence(agent_view),
        model_declared_observation_evidence=(
            agent_view_module.model_declared_observation_evidence(agent_view)
        ),
    )
    agent_view["simulated"] = True
    agent_view["physical_robot"] = False
    agent_view["execution_backend"] = EXECUTION_BACKEND
    agent_view["cleanup_action_rehearsal"] = True
    return agent_view


def _agibot_shaped_agent_view(
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    observed_objects: list[dict[str, Any]],
    raw_fpv_observations: list[dict[str, Any]],
    perception_mode: str,
    structured_detections_available: bool,
    camera_model_policy_evidence: dict[str, Any] | None = None,
    model_declared_observation_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_metric_map = _agibot_shaped_runtime_metric_map(
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        observed_objects=observed_objects,
    )
    model_declared = model_declared_observation_evidence or {
        "schema": "model_declared_observations_v1",
        "perception_mode": perception_mode,
        "observation_count": 0,
        "resolved_count": 0,
        "acted_count": 0,
        "observations": [],
        "private_truth_included": False,
    }
    return agent_view_module.build_agent_view(
        contract=REALWORLD_CONTRACT,
        perception_mode=perception_mode,
        detection_exposure_policy="agibot_shaped_molmospaces_sim_policy_camera",
        structured_detections_available=structured_detections_available,
        base_metric_map=metric_map,
        runtime_metric_map=runtime_metric_map,
        observed_objects=observed_objects,
        raw_fpv_observations=raw_fpv_observations,
        camera_model_policy_evidence=camera_model_policy_evidence
        or {
            "schema": "camera_model_policy_v1",
            "perception_mode": perception_mode,
            "enabled": False,
            "private_truth_included": False,
        },
        model_declared_observations=list(model_declared.get("observations") or []),
        model_declared_observation_evidence=model_declared,
        policy_view={
            "schema": "realworld_cleanup_policy_view_v1",
            "policy_observation_camera": "molmospaces_sim_policy_camera",
            "allowed_inputs": [
                "base_metric_map",
                "runtime_metric_map",
                "raw_fpv_observations",
                "navigation_status",
            ],
            "excluded_report_only_views": ["private_evaluation"],
            "chase_camera_policy_input": False,
        },
        cleanup_worklist={
            "schema": CLEANUP_WORKLIST_SCHEMA,
            "waypoint_source": "agibot_shaped_molmospaces_sim_preflight",
            "held_object_id": None,
            "objects": [],
            "waypoints": [
                {
                    "waypoint_id": str(item.get("waypoint_id") or ""),
                    "room_id": str(item.get("room_id") or ""),
                    "state": "unvisited",
                    "purpose": str(item.get("purpose") or ""),
                    "waypoint_source": str(item.get("waypoint_source") or ""),
                }
                for item in metric_map.get("inspection_waypoints") or []
            ],
            "rooms": [],
        },
        observed_waypoint_ids=[],
        public_tool_names=[
            "metric_map",
            "observe",
            "navigate_to_waypoint",
            *BLOCKED_MANIPULATION_TOOLS,
        ],
        blocked_capabilities=BLOCKED_MANIPULATION_TOOLS,
        capability_profiles=(
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ),
        forbidden_keys=forbidden_agent_view_keys(),
    )


def _agibot_shaped_runtime_metric_map(
    *,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    observed_objects: list[dict[str, Any]],
) -> dict[str, Any]:
    fixtures = [
        dict(fixture)
        for room in static_fixture_projection.get("rooms") or []
        for fixture in room.get("fixtures") or []
        if isinstance(fixture, dict)
    ]
    return {
        "schema": RUNTIME_METRIC_MAP_SCHEMA,
        "contract": REALWORLD_CONTRACT,
        "freshness": "current_run",
        "source_map_mutated": False,
        "private_truth_included": False,
        "static_map": {
            "rooms": [dict(item) for item in metric_map.get("rooms") or []],
            "fixtures": fixtures,
            "inspection_waypoints": [
                dict(item) for item in metric_map.get("inspection_waypoints") or []
            ],
            "driveable_ways": [dict(item) for item in metric_map.get("driveable_ways") or []],
            "map_bundle": dict(metric_map.get("map_bundle") or {}),
            "contains_runtime_observations": False,
        },
        "public_semantic_anchors": [],
        "observed_objects": [dict(item) for item in observed_objects],
        "target_candidates": [],
        "map_update_candidates": [],
        "generated_exploration_candidates": [
            dict(item) for item in metric_map.get("inspection_waypoints") or []
        ],
        "cleanup_worklist_summary": {
            "schema": CLEANUP_WORKLIST_SCHEMA,
            "object_count": 0,
            "pending_count": 0,
            "held_object_id": None,
            "prior_count": 0,
        },
        "producer_summary": {
            "observed_object_count": len(observed_objects),
            "public_semantic_anchor_count": 0,
            "map_update_candidate_count": 0,
        },
    }


def _empty_cleanup_actions_result() -> dict[str, Any]:
    return {
        "schema": "molmospaces_agibot_cleanup_action_rehearsal_v1",
        "rehearsal_mode": REHEARSAL_MODE_CONTRACT,
        "attempted_object_count": 0,
        "completed_object_count": 0,
        "failed_objects": [],
        "selected_targets": [],
        "final_object_locations": {},
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "manipulation_provenance": BLOCKED_CAPABILITY_PROVENANCE,
    }


@dataclass(frozen=True)
class _CleanupActionSelection:
    selected_targets: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    navigation_attempts: list[dict[str, Any]]


def _run_cleanup_action_rehearsal(
    *,
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    trace_events: list[dict[str, Any]],
    policy_events: list[dict[str, Any]],
    started_at: float,
    runtime: str,
    run_dir: Path,
    robot_view_steps: list[dict[str, Any]],
    robot_view_index_ref: list[int],
    record_robot_views: bool,
    cleanup_object_count: int,
) -> dict[str, Any]:
    selection = _select_cleanup_action_targets(
        contract=contract,
        base_contract=base_contract,
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        trace_events=trace_events,
        policy_events=policy_events,
        started_at=started_at,
        runtime=runtime,
        run_dir=run_dir,
        robot_view_steps=robot_view_steps,
        robot_view_index_ref=robot_view_index_ref,
        record_robot_views=record_robot_views,
        cleanup_object_count=cleanup_object_count,
    )

    loop_result = run_semantic_cleanup_loop(
        targets=selection.selected_targets,
        contract=contract,
        call_tool=lambda tool, request, fn: _call_cleanup_action_tool(
            trace_events=trace_events,
            policy_events=policy_events,
            started_at=started_at,
            runtime=runtime,
            tool=tool,
            request=request,
            fn=fn,
        ),
        record_tool_view=(
            lambda tool, request, response: _record_cleanup_action_robot_view(
                contract=contract,
                backend=base_contract.backend,
                run_dir=run_dir,
                robot_view_steps=robot_view_steps,
                trace_events=trace_events,
                started_at=started_at,
                index_ref=robot_view_index_ref,
                tool=tool,
                request=request,
                response=response,
                record_robot_views=record_robot_views,
            )
        ),
        target_request_key="fixture_id",
        include_object_id_in_receptacle_request=False,
        include_object_id_in_target_requests=False,
    )
    return _cleanup_actions_payload(
        loop_result=loop_result,
        selected_targets=selection.selected_targets,
        observations=selection.observations,
        navigation_attempts=selection.navigation_attempts,
        robot_view_index=robot_view_index_ref[0],
    )


def _select_cleanup_action_targets(
    *,
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    trace_events: list[dict[str, Any]],
    policy_events: list[dict[str, Any]],
    started_at: float,
    runtime: str,
    run_dir: Path,
    robot_view_steps: list[dict[str, Any]],
    robot_view_index_ref: list[int],
    record_robot_views: bool,
    cleanup_object_count: int,
) -> _CleanupActionSelection:
    selected_targets: list[dict[str, Any]] = []
    seen_handles: set[str] = set()
    observations: list[dict[str, Any]] = []
    navigation_attempts: list[dict[str, Any]] = []
    for waypoint in metric_map.get("inspection_waypoints") or []:
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id:
            continue
        nav = _record_cleanup_sweep_navigation(
            contract=contract,
            base_contract=base_contract,
            metric_map=metric_map,
            trace_events=trace_events,
            policy_events=policy_events,
            started_at=started_at,
            runtime=runtime,
            run_dir=run_dir,
            robot_view_steps=robot_view_steps,
            robot_view_index_ref=robot_view_index_ref,
            record_robot_views=record_robot_views,
            waypoint_id=waypoint_id,
        )
        navigation_attempts.append(nav)
        obs = _record_cleanup_sweep_observation(
            contract=contract,
            base_contract=base_contract,
            metric_map=metric_map,
            trace_events=trace_events,
            policy_events=policy_events,
            started_at=started_at,
            runtime=runtime,
            run_dir=run_dir,
            robot_view_steps=robot_view_steps,
            robot_view_index_ref=robot_view_index_ref,
            record_robot_views=record_robot_views,
            waypoint_id=waypoint_id,
        )
        observations.append(obs)
        _append_cleanup_action_targets(
            contract=contract,
            static_fixture_projection=static_fixture_projection,
            selected_targets=selected_targets,
            seen_handles=seen_handles,
            observation=obs,
            waypoint_id=waypoint_id,
            cleanup_object_count=cleanup_object_count,
        )
        if len(selected_targets) >= cleanup_object_count:
            break
    return _CleanupActionSelection(
        selected_targets=selected_targets,
        observations=observations,
        navigation_attempts=navigation_attempts,
    )


def _record_cleanup_sweep_navigation(
    *,
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
    metric_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    policy_events: list[dict[str, Any]],
    started_at: float,
    runtime: str,
    run_dir: Path,
    robot_view_steps: list[dict[str, Any]],
    robot_view_index_ref: list[int],
    record_robot_views: bool,
    waypoint_id: str,
) -> dict[str, Any]:
    nav = _simulated_navigation(
        contract.navigate_to_waypoint(waypoint_id),
        metric_map=metric_map,
        waypoint_id=waypoint_id,
        runtime=runtime,
    )
    _record(trace_events, started_at, "navigate_to_waypoint", {"waypoint_id": waypoint_id}, nav)
    policy_events.append(_policy_event(len(policy_events), nav, "cleanup_sweep_nav"))
    if record_robot_views and nav.get("ok"):
        robot_view_index_ref[0] = _record_robot_view(
            robot_view_steps=robot_view_steps,
            trace_events=trace_events,
            started_at=started_at,
            backend=base_contract.backend,
            run_dir=run_dir,
            index=robot_view_index_ref[0],
            action=f"navigate_to_waypoint {waypoint_id}",
            label_suffix=f"cleanup_waypoint_{waypoint_id}",
        )
    return nav


def _record_cleanup_sweep_observation(
    *,
    contract: HouseholdRuntimeContract,
    base_contract: HouseholdBackendSession,
    metric_map: dict[str, Any],
    trace_events: list[dict[str, Any]],
    policy_events: list[dict[str, Any]],
    started_at: float,
    runtime: str,
    run_dir: Path,
    robot_view_steps: list[dict[str, Any]],
    robot_view_index_ref: list[int],
    record_robot_views: bool,
    waypoint_id: str,
) -> dict[str, Any]:
    observation_image = _write_snapshot(
        runtime=runtime,
        contract=base_contract,
        scenario=contract.scenario,
        output_path=run_dir / "runtime" / f"policy_observation_{waypoint_id}.png",
        title=f"Simulated policy observation at {waypoint_id}",
    )
    obs = _simulated_observation(
        contract.observe(),
        observation_image=observation_image,
        run_dir=run_dir,
        runtime=runtime,
        metric_map=metric_map,
        waypoint_id=waypoint_id,
    )
    _record(trace_events, started_at, "observe", {"waypoint_id": waypoint_id}, obs)
    policy_events.append(_policy_event(len(policy_events), obs, "cleanup_sweep_observe"))
    if record_robot_views and obs.get("ok"):
        robot_view_index_ref[0] = _record_tool_robot_view(
            contract=contract,
            backend=base_contract.backend,
            run_dir=run_dir,
            robot_view_steps=robot_view_steps,
            trace_events=trace_events,
            started_at=started_at,
            index=robot_view_index_ref[0],
            tool="observe",
            request={"waypoint_id": waypoint_id},
            response=obs,
        )
    return obs


def _append_cleanup_action_targets(
    *,
    contract: HouseholdRuntimeContract,
    static_fixture_projection: dict[str, Any],
    selected_targets: list[dict[str, Any]],
    seen_handles: set[str],
    observation: dict[str, Any],
    waypoint_id: str,
    cleanup_object_count: int,
) -> None:
    for detection in observation.get("visible_object_detections") or []:
        handle = str(detection.get("object_id") or "")
        if not handle or handle in seen_handles:
            continue
        target = _cleanup_action_target(
            contract=contract,
            static_fixture_projection=static_fixture_projection,
            detection=detection,
            observation=observation,
            waypoint_id=waypoint_id,
        )
        if target is None:
            continue
        selected_targets.append(target)
        seen_handles.add(handle)
        if len(selected_targets) >= cleanup_object_count:
            return


def _cleanup_action_target(
    *,
    contract: HouseholdRuntimeContract,
    static_fixture_projection: dict[str, Any],
    detection: dict[str, Any],
    observation: dict[str, Any],
    waypoint_id: str,
) -> dict[str, Any] | None:
    handle = str(detection.get("object_id") or "")
    target_fixture = contract.target_fixture_for_detection(
        detection,
        static_fixture_projection,
        include_runtime_backend_fixtures=True,
    )
    if target_fixture is None:
        return None
    target_fixture_id = str(target_fixture.get("fixture_id") or "")
    source_fixture_id = str((detection.get("support_estimate") or {}).get("fixture_id") or "")
    if not target_fixture_id or target_fixture_id == source_fixture_id:
        return None
    return {
        "object_id": handle,
        "internal_object_id": str(contract._internal_object_id(handle) or ""),
        "category": str(detection.get("category") or ""),
        "source_receptacle_id": source_fixture_id,
        "target_receptacle_id": target_fixture_id,
        "target_receptacle": target_fixture,
        "recommended_tool": str(detection.get("recommended_tool") or "auto"),
        "source_observation_id": str(observation.get("observation_id") or ""),
        "waypoint_id": waypoint_id,
    }


def _call_cleanup_action_tool(
    *,
    trace_events: list[dict[str, Any]],
    policy_events: list[dict[str, Any]],
    started_at: float,
    runtime: str,
    tool: str,
    request: dict[str, Any],
    fn: Any,
) -> dict[str, Any]:
    response = _simulated_cleanup_action_response(fn(), runtime=runtime)
    _record(trace_events, started_at, tool, request, response)
    policy_events.append(_policy_event(len(policy_events), response, "cleanup_action"))
    return response


def _simulated_cleanup_action_response(response: dict[str, Any], *, runtime: str) -> dict[str, Any]:
    payload = dict(response)
    payload.setdefault("primitive_provenance", API_SEMANTIC_PROVENANCE)
    payload["execution_backend"] = EXECUTION_BACKEND
    payload["simulated"] = True
    payload["physical_robot"] = False
    payload["runtime"] = runtime
    payload["planner_backed"] = False
    payload["strict_proof_eligible"] = False
    payload.setdefault(
        "public_contract_note",
        "Simulated cleanup-action rehearsal state update; not Agibot GDK manipulation.",
    )
    return payload


def _cleanup_actions_payload(
    *,
    loop_result: SemanticCleanupLoopResult,
    selected_targets: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    navigation_attempts: list[dict[str, Any]],
    robot_view_index: int,
) -> dict[str, Any]:
    return {
        "schema": "molmospaces_agibot_cleanup_action_rehearsal_v1",
        "confidence_layer": CLEANUP_ACTION_CONFIDENCE_LAYER,
        "rehearsal_mode": REHEARSAL_MODE_CLEANUP_ACTIONS,
        "attempted_object_count": loop_result.attempted_objects,
        "completed_object_count": loop_result.completed_objects,
        "failed_objects": list(loop_result.failed_objects),
        "selected_targets": [
            {
                "object_id": str(item.get("object_id") or ""),
                "internal_object_id": str(item.get("internal_object_id") or ""),
                "category": str(item.get("category") or ""),
                "source_receptacle_id": str(item.get("source_receptacle_id") or ""),
                "target_receptacle_id": str(item.get("target_receptacle_id") or ""),
                "recommended_tool": str(item.get("recommended_tool") or "auto"),
                "source_observation_id": str(item.get("source_observation_id") or ""),
                "waypoint_id": str(item.get("waypoint_id") or ""),
            }
            for item in selected_targets
        ],
        "observation_count": len(observations),
        "navigation_attempt_count": len(navigation_attempts),
        "final_object_locations": {},
        "robot_view_index": robot_view_index,
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "manipulation_provenance": API_SEMANTIC_PROVENANCE,
        "planner_backed": False,
        "agibot_gdk_execution": False,
        "public_contract_note": (
            "Cleanup actions are simulated MolmoSpaces state updates selected from "
            "public observations and static fixture projection."
        ),
    }


def _record_action_done(
    *,
    contract: HouseholdBackendSession,
    trace_events: list[dict[str, Any]],
    started_at: float,
    runtime: str,
) -> dict[str, Any]:
    response = contract.done("molmospaces_agibot_cleanup_action_rehearsal complete")
    response = _simulated_cleanup_action_response(response, runtime=runtime)
    _record(
        trace_events,
        started_at,
        "done",
        {"reason": "molmospaces_agibot_cleanup_action_rehearsal complete"},
        response,
    )
    return response


def _record_cleanup_action_robot_view(
    *,
    contract: HouseholdRuntimeContract,
    backend: Any,
    run_dir: Path,
    robot_view_steps: list[dict[str, Any]],
    trace_events: list[dict[str, Any]],
    started_at: float,
    index_ref: list[int],
    tool: str,
    request: dict[str, Any],
    response: dict[str, Any],
    record_robot_views: bool,
) -> None:
    if not record_robot_views or not response.get("ok"):
        return
    index_ref[0] = _record_tool_robot_view(
        contract=contract,
        backend=backend,
        run_dir=run_dir,
        robot_view_steps=robot_view_steps,
        trace_events=trace_events,
        started_at=started_at,
        index=index_ref[0],
        tool=tool,
        request=request,
        response=response,
    )


def _record_tool_robot_view(
    *,
    contract: HouseholdRuntimeContract,
    backend: Any,
    run_dir: Path,
    robot_view_steps: list[dict[str, Any]],
    trace_events: list[dict[str, Any]],
    started_at: float,
    index: int,
    tool: str,
    request: dict[str, Any],
    response: dict[str, Any],
) -> int:
    capture = robot_view_capture_for_tool(
        tool,
        request,
        response,
        object_id_transform=lambda value: (
            contract._internal_object_id(value) if value is not None else None
        ),
    )
    if capture is None:
        return index
    return _record_robot_view(
        robot_view_steps=robot_view_steps,
        trace_events=trace_events,
        started_at=started_at,
        backend=backend,
        run_dir=run_dir,
        index=index,
        action=str(capture["action"]),
        label_suffix=str(capture["label_suffix"]),
        focus_object_id=capture.get("focus_object_id"),
        focus_receptacle_id=capture.get("focus_receptacle_id"),
        semantic_phase=capture.get("semantic_phase"),
        action_evidence=capture.get("action_evidence"),
    )


def _record_robot_view(
    *,
    robot_view_steps: list[dict[str, Any]],
    trace_events: list[dict[str, Any]],
    started_at: float,
    backend: Any,
    run_dir: Path,
    index: int,
    action: str,
    label_suffix: str,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    semantic_phase: str | None = None,
    action_evidence: dict[str, Any] | None = None,
) -> int:
    capture_started = time.monotonic()
    next_index = record_robot_view_step(
        steps=robot_view_steps,
        backend=backend,
        output_dir=run_dir,
        index=index,
        action=action,
        label_suffix=label_suffix,
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        semantic_phase=semantic_phase,
        action_evidence=action_evidence,
    )
    elapsed_s = round(time.monotonic() - capture_started, 6)
    if robot_view_steps:
        robot_view_steps[-1]["capture_elapsed_s"] = elapsed_s
    trace_events.append(
        {
            "tool": "<runtime>",
            "event": "robot_view_capture",
            "action": action,
            "label": robot_view_steps[-1].get("label", "") if robot_view_steps else "",
            "wallclock_elapsed": time.time() - started_at,
            "elapsed_s": elapsed_s,
        }
    )
    return next_index


def _runtime_export(
    *,
    observation: dict[str, Any],
    navigation: dict[str, Any],
    manipulation_results: list[dict[str, Any]],
    subphase_reports: list[dict[str, Any]],
    runtime: str,
    rehearsal_mode: str,
    cleanup_actions: dict[str, Any],
    semantic_substeps: list[dict[str, Any]],
    final_locations: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    stages = ["agent_view_export", "observe", "navigate_waypoint"]
    if rehearsal_mode == REHEARSAL_MODE_CLEANUP_ACTIONS:
        stages.append("cleanup_actions")
    else:
        stages.append("blocked_manipulation")
    return {
        "schema": "agibot_shaped_runtime_export_v1",
        "confidence_layer": (
            CLEANUP_ACTION_CONFIDENCE_LAYER
            if rehearsal_mode == REHEARSAL_MODE_CLEANUP_ACTIONS
            else CONFIDENCE_LAYER
        ),
        "rehearsal_mode": rehearsal_mode,
        "runtime": runtime,
        "simulated": True,
        "physical_robot": False,
        "execution_backend": EXECUTION_BACKEND,
        "navigation_backend": NAVIGATION_BACKEND,
        "stages": stages,
        "observation": observation,
        "navigation": navigation,
        "blocked_manipulation_results": manipulation_results,
        "cleanup_actions": cleanup_actions,
        "semantic_substeps": semantic_substeps,
        "attempted_object_count": int(cleanup_actions.get("attempted_object_count") or 0),
        "completed_object_count": int(cleanup_actions.get("completed_object_count") or 0),
        "final_object_locations": final_locations,
        "robot_view_step_count": len(robot_view_steps),
        "subphase_reports": subphase_reports,
        "gdk_imported_by_roboclaws": False,
    }


def _run_result(
    *,
    run_dir: Path,
    scenario: CleanupScenario,
    runtime: str,
    seed: int,
    generated_mess_count: int,
    started_at: float,
    metric_map: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    observation: dict[str, Any],
    navigation: dict[str, Any],
    manipulation_results: list[dict[str, Any]],
    cleanup_actions: dict[str, Any],
    agent_view: dict[str, Any],
    runtime_export: dict[str, Any],
    subphase_reports: list[dict[str, Any]],
    trace_path: Path,
    before_snapshot: Path,
    after_snapshot: Path,
    policy_events: list[dict[str, Any]],
    semantic_substeps: list[dict[str, Any]],
    cleanup_primitive_evidence: dict[str, Any],
    final_locations: dict[str, Any],
    done_response: dict[str, Any] | None,
    robot_view_steps: list[dict[str, Any]],
    backend_instance: MolmoSpacesSubprocessBackend | None,
    scene_identity_path: Path,
    map_preview_path: Path,
    agibot_map_reference_path: Path,
    rehearsal_mode: str,
    record_robot_views: bool,
) -> dict[str, Any]:
    cleanup_actions_enabled = rehearsal_mode == REHEARSAL_MODE_CLEANUP_ACTIONS
    report_title = CLEANUP_ACTION_CONFIDENCE_LAYER if cleanup_actions_enabled else CONFIDENCE_LAYER
    score = (
        dict(done_response.get("score") or _empty_score())
        if done_response is not None
        else _empty_score()
    )
    private_evaluation = _private_evaluation(
        scenario=scenario,
        score=score,
        cleanup_actions_enabled=cleanup_actions_enabled,
    )
    readiness = _readiness_payload(
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        observation=observation,
        navigation=navigation,
        manipulation_results=manipulation_results,
        runtime=runtime,
        rehearsal_mode=rehearsal_mode,
        cleanup_actions=cleanup_actions,
        robot_view_steps=robot_view_steps,
    )
    manipulation_evidence = (
        _cleanup_action_manipulation_evidence(cleanup_primitive_evidence)
        if cleanup_actions_enabled
        else _blocked_manipulation_evidence(manipulation_results)
    )
    cleanup_status = (
        "molmospaces_agibot_cleanup_action_rehearsal_complete"
        if cleanup_actions_enabled
        else "molmospaces_agibot_contract_rehearsal_complete"
    )
    run_result: dict[str, Any] = {
        "schema": REHEARSAL_SCHEMA,
        "report_eyebrow": "Agibot-shaped simulated evidence",
        "report_title": report_title,
        "confidence_layer": report_title,
        "rehearsal_mode": rehearsal_mode,
        "confidence_layer_summary": (
            (
                "Exercises simulated cleanup actions after Agibot-shaped observe and "
                "waypoint navigation. Pick/place effects are api_semantic MolmoSpaces "
                "state updates, not Agibot GDK manipulation or planner-backed proof."
            )
            if cleanup_actions_enabled
            else (
                "Validates task-neutral household public tool sequencing and report "
                "evidence plumbing through a simulated "
                "MolmoSpaces backend. It is not Agibot Map Visual Dry Run, not Agibot "
                "SDK Dry Run, not semantic cleanup mock evidence, and not real Agibot "
                "GDK execution."
            )
        ),
        "next_confidence_layer": "Optional real Agibot G2 validation",
        "contract": REALWORLD_CONTRACT,
        "backend": AGIBOT_SHAPED_SIM_BACKEND,
        "backend_variant": EXECUTION_BACKEND,
        "execution_backend": EXECUTION_BACKEND,
        "navigation_backend": NAVIGATION_BACKEND,
        "runtime": runtime,
        "evidence_lane": "world-public-labels",
        "simulated": True,
        "physical_robot": False,
        "agent_driven": False,
        "mcp_server": "roboclaws_household_agibot_shaped_sim",
        "scenario_id": scenario.scenario_id,
        "task_prompt": scenario.task,
        "seed": seed,
        "cleanup_status": cleanup_status,
        "final_status": cleanup_status,
        "terminate_reason": (
            "cleanup action rehearsal complete"
            if cleanup_actions_enabled
            else "contract rehearsal complete"
        ),
        "primitive_provenance": (
            API_SEMANTIC_PROVENANCE if cleanup_actions_enabled else NAVIGATION_PROVENANCE
        ),
        "generated_mess_count": private_evaluation["generated_mess_count"],
        "requested_generated_mess_count": generated_mess_count,
        "sweep_coverage_rate": private_evaluation["sweep_coverage_rate"],
        "disturbance_count": private_evaluation["disturbance_count"],
        "score": score,
        "private_evaluation": private_evaluation,
        "final_locations": final_locations,
        "agent_view": agent_view,
        "raw_fpv_observations": agent_view_module.raw_fpv_observations(agent_view),
        "cleanup_policy_trace": {
            "schema": "cleanup_policy_trace_v1",
            "waypoint_source": "agibot_shaped_molmospaces_sim_preflight",
            "loop_style": (
                "molmospaces_agibot_cleanup_action_rehearsal"
                if cleanup_actions_enabled
                else "molmospaces_agibot_contract_rehearsal"
            ),
            "total_waypoints": len(metric_map.get("inspection_waypoints") or []),
            "observed_waypoint_count": max(
                1 if observation.get("ok") else 0,
                int(cleanup_actions.get("observation_count") or 0),
            ),
            "scan_observe_count": max(1, int(cleanup_actions.get("observation_count") or 0)),
            "cleanup_action_count": int(cleanup_actions.get("attempted_object_count") or 0),
            "placed_object_count": int(cleanup_actions.get("completed_object_count") or 0),
            "post_place_observe_count": 0,
            "post_place_observe_complete": True,
            "first_cleanup_before_full_survey": False,
            "events": policy_events,
            "public_contract_note": (
                (
                    "This trace includes opt-in simulated cleanup actions. "
                    "Manipulation remains api_semantic state-edit evidence only."
                )
                if cleanup_actions_enabled
                else (
                    "This trace validates observe and waypoint navigation sequencing only. "
                    "Manipulation tools remain blocked_capability."
                )
            ),
        },
        "semantic_substeps": semantic_substeps,
        "cleanup_primitive_evidence": cleanup_primitive_evidence,
        "real_robot_readiness": readiness,
        "agibot_sdk_runner": {
            "schema": "agibot_shaped_sim_runner_boundary_v1",
            "rehearsal_kind": "molmospaces_agibot_contract_rehearsal",
            "rehearsal_mode": rehearsal_mode,
            "backend_variant": EXECUTION_BACKEND,
            "runtime": runtime,
            "simulated": True,
            "physical_robot": False,
            "execution_backend": EXECUTION_BACKEND,
            "navigation_backend": NAVIGATION_BACKEND,
            "real_movement_enabled": False,
            "next_confidence_layer": "Optional real Agibot G2 validation",
            "subphase_reports": subphase_reports,
            "gdk_imported_by_roboclaws": False,
            "public_tool_boundary": [
                "metric_map",
                "static_fixture_projection",
                "observe",
                "navigate_to_waypoint",
                *BLOCKED_MANIPULATION_TOOLS,
                "done",
            ],
        },
        "molmospaces_agibot_contract_rehearsal": {
            "schema": REHEARSAL_SCHEMA,
            "confidence_layer": report_title,
            "rehearsal_mode": rehearsal_mode,
            "runtime": runtime,
            "evidence_lane": "world-public-labels",
            "simulated": True,
            "physical_robot": False,
            "execution_backend": EXECUTION_BACKEND,
            "navigation_backend": NAVIGATION_BACKEND,
            "navigation_primitive_provenance": NAVIGATION_PROVENANCE,
            "observation_primitive_provenance": OBSERVATION_PROVENANCE,
            "agent_view_preflight": "preflight/agent_view.json",
            "scene_identity": _relpath(scene_identity_path, run_dir),
            "map_preview": _relpath(map_preview_path, run_dir),
            "agibot_map_reference": _relpath(agibot_map_reference_path, run_dir),
            "waypoint_sequence": "preflight/waypoint_sequence.json",
            "runner_task_input": "preflight/runner_task_input.json",
            "runtime_export": "runtime/runtime_export.json",
            "blocked_manipulation_tools": list(BLOCKED_MANIPULATION_TOOLS),
            "cleanup_actions": cleanup_actions,
            "attempted_object_count": int(cleanup_actions.get("attempted_object_count") or 0),
            "completed_object_count": int(cleanup_actions.get("completed_object_count") or 0),
            "final_object_locations": final_locations,
            "layer_distinction": [
                "not Agibot Map Visual Dry Run",
                "not Agibot SDK Dry Run",
                "not semantic cleanup mock evidence",
                "not real Agibot GDK execution",
            ],
        },
        "manipulation_evidence": manipulation_evidence,
        "artifacts": {
            "run_result": "run_result.json",
            "trace": _relpath(trace_path, run_dir),
            "before_snapshot": _relpath(before_snapshot, run_dir),
            "after_snapshot": _relpath(after_snapshot, run_dir),
            "agent_view": "agent_view.json",
            "preflight": "preflight",
            "molmospaces_scene_identity": _relpath(scene_identity_path, run_dir),
            "molmospaces_metric_map_preview": _relpath(map_preview_path, run_dir),
            "agibot_map_reference": _relpath(agibot_map_reference_path, run_dir),
            "runtime_export": "runtime/runtime_export.json",
            "agibot_shaped_subphases": "subphases",
            "report": "report.html",
        },
        "runtime_timing": {
            "total_elapsed_s": time.time() - started_at,
            "tool_handler_s": 0.0,
            "robot_view_capture_s": 0.0,
            "between_tool_gap_s": 0.0,
            "tool_call_count": len(trace_path.read_text(encoding="utf-8").splitlines()) // 2
            if trace_path.is_file()
            else 0,
        },
    }
    if robot_view_steps:
        run_result["view_variant"] = ROBOT_VIEW_VARIANT
        run_result["robot_view_steps"] = robot_view_steps
        run_result["artifacts"]["robot_views"] = "robot_views"
    if record_robot_views:
        run_result["record_robot_views"] = True
    run_result["molmospaces_scene"] = _load_json(scene_identity_path)
    run_result["agibot_map_reference"] = _load_json(agibot_map_reference_path)
    if backend_instance is not None:
        run_result["molmospaces_runtime"] = {
            "python_executable": str(backend_instance.python_executable),
            "runtime": backend_instance.runtime,
            "model_stats": backend_instance.model_stats,
            "scene_xml": backend_instance.scene_xml,
            "metadata_object_count": backend_instance.metadata_object_count,
            "requested_generated_mess_count": backend_instance.requested_generated_mess_count,
            "generated_mess_count": backend_instance.generated_mess_count,
        }
        if getattr(backend_instance, "robot", None) is not None:
            run_result["robot"] = backend_instance.robot
            run_result["robot_name"] = backend_instance.robot.get("robot_name")
            run_result["include_robot"] = True
    return run_result


def _write_snapshot(
    *,
    runtime: str,
    contract: HouseholdBackendSession,
    scenario: CleanupScenario,
    output_path: Path,
    title: str,
) -> Path:
    if runtime == RUNTIME_MOLMOSPACES_SUBPROCESS:
        return contract.backend.write_snapshot(output_path, title=title)
    return write_state_snapshot(
        scenario,
        contract.backend.object_locations(),
        output_path,
        title=title,
    )


def _record(
    trace_events: list[dict[str, Any]],
    started_at: float,
    tool: str,
    arguments: dict[str, Any],
    response: dict[str, Any],
) -> None:
    trace_events.append(
        {
            "tool": tool,
            "event": "request",
            "arguments": arguments,
            "wallclock_elapsed": time.time() - started_at,
        }
    )
    trace_events.append(
        {
            "tool": tool,
            "event": "response",
            "response": response,
            "wallclock_elapsed": time.time() - started_at,
        }
    )


def _policy_event(index: int, response: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "index": index + 1,
        "tool": response.get("tool", ""),
        "role": role,
        "waypoint_id": response.get("waypoint_id", ""),
        "fixture_id": response.get("fixture_id", ""),
        "navigation_backend": response.get("navigation_backend", ""),
        "status": response.get("status") or response.get("navigation_status", ""),
    }


def _fixtures(static_fixture_projection: dict[str, Any]) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for room in static_fixture_projection.get("rooms") or []:
        for fixture in room.get("fixtures") or []:
            if isinstance(fixture, dict):
                fixtures.append(fixture)
    return fixtures


def _first_waypoint_id_from_sequence(waypoint_sequence: dict[str, Any]) -> str:
    waypoints = waypoint_sequence.get("waypoints") or []
    if not waypoints:
        raise ValueError("MolmoSpaces Agibot rehearsal waypoint_sequence has no waypoints")
    return str(waypoints[0].get("waypoint_id") or "")


def _empty_score() -> dict[str, Any]:
    return {
        "restored_count": 0,
        "total_targets": 0,
        "object_results": [],
        "semantic_acceptability": {
            "accepted_count": 0,
            "total_targets": 0,
            "acceptance_rate": 0.0,
            "counts": {},
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="MolmoSpaces Agibot contract rehearsal artifact")
