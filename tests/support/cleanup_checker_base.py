# ruff: noqa: F401, F821
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.backends.isaaclab.b1_base_metric_augmentation import augment_base_metric_map_bundle
from roboclaws.backends.isaaclab.b1_readiness import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    NAVIGATION_PROVENANCE,
)
from roboclaws.evals import cleanup_result_args as cleanup_validation_args
from roboclaws.evals.cleanup_result_grader import assert_advisory_scoring
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import cleanup_validation as cleanup_checker
from roboclaws.household.agibot_household_backend import AgibotHouseholdBackend
from roboclaws.household.cleanup_validation_planner import _assert_focused_robot_step
from roboclaws.household.cleanup_validation_waypoints import (
    post_place_observe_count_allowing_public_state_queries,
)
from roboclaws.household.household_mcp_server import make_household_world_mcp
from roboclaws.household.household_runtime_contract import (
    CAMERA_MODEL_POLICY_MODE,
    REALWORLD_CONTRACT,
    forbidden_agent_view_keys,
)
from roboclaws.household.manipulation_contract import (
    MANIPULATION_PROBE_CONTRACT,
    PLANNER_BACKED_PROVENANCE,
)
from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from roboclaws.household.nav2_map_bundle import attach_nav2_map_bundle_snapshot
from roboclaws.maps.b1_base_metric_map import build_base_metric_map_bundle
from roboclaws.mcp.profiles import HOUSEHOLD_EPISODE_PROFILE, HOUSEHOLD_WORLD_PROFILE

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PATH = REPO_ROOT / "examples" / "molmo_cleanup" / "molmospaces_realworld_cleanup.py"
SMOKE_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_realworld_agent_mcp_smoke.py"
AGIBOT_CONTEXT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "agibot_map_context.completed.json"
AGIBOT_SDK_RUNNER_PATH = REPO_ROOT / "vendors/agibot_sdk/tools/run_agibot_cleanup_backend.py"
B1_MAP12_BUNDLE = REPO_ROOT / "vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot"
B1_ROOM_SEMANTICS = REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"
B1_BASE_LABELS = REPO_ROOT / "assets" / "maps" / "b1-map12-base-metric-labels.json"
PREBUILT_BUNDLE = REPO_ROOT / "assets/maps/molmospaces/procthor-10k-val/0"
MOLMOSPACES_ROBOT_VIEW_VARIANT = "molmospaces-rby1m-fpv-topdown-chase-verify"
ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")


def _require_agibot_sdk_runner() -> None:
    if not AGIBOT_SDK_RUNNER_PATH.is_file():
        pytest.skip("Agibot SDK vendor runner is unavailable in this checkout")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    if path == DEMO_PATH:
        run_household_world_episode = module.run_household_world_episode

        def run_synthetic_realworld_cleanup(**kwargs):
            kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
            return run_household_world_episode(**kwargs)

        module.run_household_world_episode = run_synthetic_realworld_cleanup
    elif path == SMOKE_PATH:
        run_smoke = module.run_smoke

        def run_synthetic_smoke(**kwargs):
            kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
            return run_smoke(**kwargs)

        module.run_smoke = run_synthetic_smoke
    return module


def _external_visual_grounding_checker_result(*, overlay: str) -> dict[str, object]:
    pipeline = {
        "schema": "visual_grounding_pipeline_v1",
        "pipeline_id": "grounding-dino",
        "status": "ok",
        "stages": [
            {
                "stage": "proposer",
                "producer_id": "grounding-dino",
                "model_id": "fake",
                "status": "ok",
                "latency_ms": 1,
            }
        ],
        "candidate_count": 1,
        "unresolved_count": 0,
        "duplicate_rate": 0.0,
    }
    observation = {
        "schema": "model_declared_observation_v1",
        "declaration_id": "declared_001",
        "object_id": "observed_001",
        "source_observation_id": "raw_fpv_001",
        "waypoint_id": "wp_kitchen_01",
        "room_id": "kitchen",
        "category": "dish",
        "target_fixture_id": "sink_01",
        "target_fixture_category": "sink",
        "source_fixture_id": "counter_01",
        "evidence_note": "fake dish",
        "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
        "confidence": 0.8,
        "producer_type": "external_visual_grounding_service",
        "producer_id": "grounding-dino",
        "grounding_status": "resolved",
        "grounding_confidence": 0.8,
        "grounding_basis": "single public camera-context object matched",
        "recovery_hint": "",
        "target_plausibility": {"status": "plausible"},
        "actionability_status": "actionable",
        "private_truth_included": False,
        "visual_grounding_pipeline": pipeline,
        "visual_grounding_overlay": overlay,
    }
    event = {
        "schema": "model_declared_observations_v1",
        "perception_mode": CAMERA_MODEL_POLICY_MODE,
        "observation_id": "raw_fpv_001",
        "waypoint_id": "wp_kitchen_01",
        "room_id": "kitchen",
        "producer_type": "external_visual_grounding_service",
        "producer_id": "grounding-dino",
        "candidate_count": 1,
        "registered_observed_handles": ["observed_001"],
        "visual_grounding_pipeline": pipeline,
        "private_truth_included": False,
    }
    return {
        "perception_mode": CAMERA_MODEL_POLICY_MODE,
        "raw_fpv_observations": [
            {
                "observation_id": "raw_fpv_001",
                "waypoint_id": "wp_kitchen_01",
                "room_id": "kitchen",
                "image_artifacts": {"fpv": "robot_views/raw_fpv_001.jpg"},
            }
        ],
        "camera_model_policy_evidence": {
            "schema": "camera_model_policy_v1",
            "perception_mode": CAMERA_MODEL_POLICY_MODE,
            "enabled": True,
            "model_provenance": "external_visual_grounding_service",
            "visual_grounding_pipeline_id": "grounding-dino",
            "visual_grounding_pipeline_ids": ["grounding-dino"],
            "visual_grounding_failure_count": 0,
            "event_count": 1,
            "candidate_count": 1,
            "unresolved_count": 0,
            "duplicate_rate": 0.0,
            "events": [event],
            "private_truth_included": False,
        },
        "model_declared_observation_evidence": {
            "schema": "model_declared_observations_v1",
            "observation_count": 1,
            "resolved_count": 1,
            "acted_count": 0,
            "observations": [observation],
            "private_truth_included": False,
        },
        "model_declared_observations": [observation],
        "tool_event_counts": {"declare_visual_candidates:request": 1},
    }


def _write_agibot_map_build_fixture(tmp_path: Path) -> Path:
    _require_agibot_sdk_runner()
    run_dir = tmp_path / "agibot-map-build"
    server = _make_common_agibot_map_build_server(
        run_dir=run_dir,
        context_json=AGIBOT_CONTEXT_FIXTURE,
    )
    try:
        server.call_tool("metric_map")
        server.call_tool("navigate_to_waypoint", waypoint_id="wp_sofa_front")
        server.call_tool("observe")
        server.call_tool("done", reason="checker fixture complete")
    finally:
        server.close()
    return run_dir


def _make_common_agibot_map_build_server(*, run_dir: Path, context_json: Path):
    contract = AgibotHouseholdBackend(
        run_dir=run_dir,
        context_json=context_json,
        runner_script=AGIBOT_SDK_RUNNER_PATH,
        runner_python=sys.executable,
        agibot_map_artifact_dir=B1_MAP12_BUNDLE,
        visual_grounding_pipeline_id="grounding-dino",
    )
    return make_household_world_mcp(
        run_dir=run_dir,
        contract=contract,
        map_bundle_dir=PREBUILT_BUNDLE,
        task_intent="map-build",
        evidence_lane=None,
        required_capability_profiles=(HOUSEHOLD_WORLD_PROFILE, HOUSEHOLD_EPISODE_PROFILE),
    )


def _promote_agibot_fixture_to_hardware_shape(
    data: dict[str, object],
    run_dir: Path,
) -> None:
    pipeline = {
        "schema": "visual_grounding_pipeline_v1",
        "pipeline_id": "grounding-dino",
        "status": "ok",
        "stages": [
            {
                "stage": "grounding_dino",
                "producer_id": "grounding-dino",
                "model_id": "grounding-dino",
                "status": "ok",
                "latency_ms": 1,
            }
        ],
        "candidate_count": 1,
        "unresolved_count": 0,
        "duplicate_rate": 0.0,
        "auth_mode": "none",
    }
    image_rel = "subphases/02-observe/head_color.jpg"
    image_path = run_dir / image_rel
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), (240, 240, 240)).save(image_path)

    data["cleanup_status"] = "physical_agibot_map_build_complete"
    data["completion_status"] = "physical_agibot_map_build_complete"
    data["primitive_provenance"] = "agibot_gdk_normal_navi"
    data["sweep_coverage_rate"] = 1.0
    readiness = data["real_robot_readiness"]
    assert isinstance(readiness, dict)
    readiness.update(
        {
            "status": "physical_agibot_map_build_complete",
            "movement_enabled": True,
            "navigation_perception_ready": True,
            "human_takeover_stop": False,
            "inspection_waypoint_attempt_count": 1,
            "inspection_waypoint_total": 1,
            "reached_waypoint_count": 1,
            "observed_reached_waypoint_count": 1,
            "observed_reached_waypoint_rate": 1.0,
            "observed_waypoint_rate": 1.0,
        }
    )

    raw = data["raw_fpv_observations"]
    assert isinstance(raw, list)
    raw[0].update(
        {
            "ok": True,
            "status": "ok",
            "camera": "head_color",
            "primitive_provenance": "agibot_gdk_head_color_camera",
            "image_artifacts": {"fpv": image_rel},
        }
    )
    agent_view = data["agent_view"]
    assert isinstance(agent_view, dict)
    agent_view_module.active_perception(agent_view)["raw_fpv_observations"] = raw

    camera_policy = data["camera_model_policy_evidence"]
    assert isinstance(camera_policy, dict)
    camera_policy.update(
        {
            "event_count": 1,
            "candidate_count": 1,
            "visual_grounding_failure_count": 0,
            "events": [
                {
                    "observation_id": raw[0]["observation_id"],
                    "room_id": "",
                    "candidate_count": 1,
                    "registered_observed_handles": [],
                    "visual_grounding_pipeline": pipeline,
                }
            ],
        }
    )
    agent_view_module.active_perception(agent_view)["camera_model_policy_evidence"] = camera_policy

    trace = data["cleanup_policy_trace"]
    assert isinstance(trace, dict)
    events = trace["events"]
    assert isinstance(events, list)
    for event in events:
        if isinstance(event, dict) and event.get("decision") == "visit_public_waypoint":
            event["primitive_provenance"] = "agibot_gdk_normal_navi"
            event["status"] = "ok"
        if isinstance(event, dict) and event.get("decision") == "observe_head_color":
            event["primitive_provenance"] = "agibot_gdk_head_color_camera"
            event["status"] = "ok"


def _robot_step(action: str) -> dict[str, object]:
    return {
        "action": action,
        "room_outline_count": 1,
        "views": {
            "fpv": "robot_views/step.fpv.png",
            "chase": "robot_views/step.chase.png",
            "topdown": "robot_views/step.topdown.png",
            "verify": "robot_views/step.verify.png",
        },
        "focus": {
            "has_focus": True,
            "fpv_visibility": {"status": "ok"},
            "visibility": {"status": "ok"},
        },
    }


def _scene_context_robot_step(action: str) -> dict[str, object]:
    return {
        "action": action,
        "room_outline_count": 1,
        "views": {
            "fpv": "robot_views/scene.fpv.png",
            "chase": "robot_views/scene.chase.png",
            "topdown": "robot_views/scene.topdown.png",
            "verify": "robot_views/scene.verify.png",
        },
        "focus": {
            "has_focus": False,
            "fpv_visibility": {"status": "ok"},
            "visibility": {"status": "ok"},
        },
    }


def _add_molmospaces_robot_view_artifacts(
    result: dict[str, object],
    base: Path,
    *,
    prefix: str = "step",
) -> None:
    robot_views = base / "robot_views"
    robot_views.mkdir()
    for key in ROBOT_VIEW_KEYS:
        (robot_views / f"{prefix}.{key}.png").write_bytes(b"placeholder")
    _insert_robot_timeline_before_score(base / "report.html")
    result["view_variant"] = MOLMOSPACES_ROBOT_VIEW_VARIANT
    artifacts = result.setdefault("artifacts", {})
    assert isinstance(artifacts, dict)
    artifacts["robot_views"] = str(robot_views)


def _trace_response(tool: str, response: dict[str, object]) -> dict[str, object]:
    return {"event": "response", "tool": tool, "response": response}


def _write_trace(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _isaac_selected_scene_bindings() -> dict[str, object]:
    return {
        "schema": "isaac_public_scene_bindings_v1",
        "status": "selected_bound",
        "source": "usd_stage_traversal",
        "selected_object_count": 1,
        "selected_target_receptacle_count": 1,
        "selected_object_bound_count": 1,
        "selected_target_receptacle_bound_count": 1,
        "selected_object_bindings": {
            "mug_01": {
                "status": "bound",
                "usd_handle": "mug_01",
                "usd_prim_path": "/World/Objects/mug_01",
                "match_strategy": "exact_public_id",
                "index_source": "usd_stage_traversal",
            }
        },
        "selected_target_receptacle_bindings": {
            "sink_01": {
                "status": "bound",
                "usd_handle": "sink_01",
                "usd_prim_path": "/World/Receptacles/sink_01",
                "match_strategy": "exact_public_id",
                "index_source": "usd_stage_traversal",
            }
        },
        "blockers": [],
        "private_manifest_exposed_to_agent": False,
    }


def _isaac_runtime_result(
    base: Path,
    scene_bindings: dict[str, object],
    *,
    segmentation: dict[str, object] | None = None,
    semantic_pose_state: dict[str, object] | None = None,
) -> dict[str, object]:
    if segmentation is None:
        segmentation = {
            "status": "blocked_capability",
            "agent_facing": False,
            "no_simulator_label_fallback": True,
        }
    result: dict[str, object] = {
        "backend": "isaaclab_subprocess",
        "artifacts": {"isaac_scene_index": str(base / "isaac_scene_index.json")},
        "isaac_runtime": {
            "runtime": {"primitive_provenance": "isaac_semantic_pose"},
            "object_index": {"mug_01": {"usd_prim_path": "/World/Objects/mug_01"}},
            "object_index_count": 1,
            "receptacle_index": {
                "sink_01": {"usd_prim_path": "/World/Receptacles/sink_01"},
            },
            "receptacle_index_count": 1,
            "scene_binding_diagnostics": scene_bindings,
            "scene_index_artifact": str(base / "isaac_scene_index.json"),
            "segmentation": segmentation,
        },
    }
    if semantic_pose_state is not None:
        trace_path = base / "trace.jsonl"
        _write_trace(trace_path, _isaac_semantic_pose_trace_events(semantic_pose_state))
        result["artifacts"]["trace"] = str(trace_path)
        result["primitive_provenance"] = "isaac_semantic_pose"
        result["manipulation_evidence"] = {
            "primitive_provenance": "isaac_semantic_pose",
            "isaac_semantic_pose_edits": True,
            "planner_backed": False,
            "physical_robot": False,
        }
        result["semantic_substeps"] = [
            {
                "steps": [
                    {
                        "phase": "pick",
                        "status": "ok",
                        "primitive_provenance": "isaac_semantic_pose",
                        "planner_backed": False,
                        "physical_robot": False,
                    },
                    {
                        "phase": "place",
                        "status": "ok",
                        "primitive_provenance": "isaac_semantic_pose",
                        "planner_backed": False,
                        "physical_robot": False,
                    },
                ]
            }
        ]
        result["isaac_runtime"]["semantic_pose_state"] = semantic_pose_state
    return result


def _isaac_real_runtime_diagnostics() -> dict[str, object]:
    return {
        "runtime_mode": "real",
        "python_version": "3.12.3",
        "isaac_sim_version": "unit-isaacsim",
        "isaac_lab_version": "unit-isaaclab",
        "cuda_available": True,
        "gpu_name": "unit-gpu",
        "gpu_vram_mb": 16384,
        "renderer_mode": "isaac_lab_headless_rtx",
        "camera_resolution": [540, 360],
        "primitive_provenance": "isaac_semantic_pose",
        "rendering": {
            "status": "real_rendering_proven",
            "real_rendering_proven": True,
            "placeholder_visuals": False,
        },
    }


__all__ = [name for name in globals() if not name.startswith("__")]
