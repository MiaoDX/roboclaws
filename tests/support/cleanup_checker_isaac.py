# ruff: noqa: F403, F405, F821
from tests.support.cleanup_checker_base import *


def _add_isaac_loaded_scene(
    data: dict[str, object],
    base: Path,
    *,
    manual_editor_steps_required: bool = False,
    loaded_asset_kind: str = "local_scene_usd",
) -> Path:
    scene_usd = base / "loaded_scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["scene_usd"] = str(scene_usd)
    isaac_runtime["scene_load"] = {
        "status": "loaded",
        "usd_stage_loaded": True,
        "scene_usd": str(scene_usd),
        "loaded_asset_kind": loaded_asset_kind,
        "manual_editor_steps_required": manual_editor_steps_required,
    }
    return scene_usd


def _minimal_agent_view(
    *,
    base_metric_map: dict[str, object] | None = None,
    runtime_metric_map: dict[str, object] | None = None,
    perception_mode: str = "visible_object_detections",
    structured_detections_available: bool = True,
    observed_objects: list[dict[str, object]] | None = None,
    raw_fpv_observations: list[dict[str, object]] | None = None,
    camera_model_policy_evidence: dict[str, object] | None = None,
    model_declared_observations: list[dict[str, object]] | None = None,
    model_declared_observation_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    base_metric_map = base_metric_map or _minimal_base_metric_map()
    runtime_metric_map = runtime_metric_map or {}
    return agent_view_module.build_agent_view(
        contract=REALWORLD_CONTRACT,
        perception_mode=perception_mode,
        detection_exposure_policy="sanitized_visible_object_detections",
        structured_detections_available=structured_detections_available,
        base_metric_map=base_metric_map,
        runtime_metric_map=runtime_metric_map,
        observed_objects=observed_objects or [],
        raw_fpv_observations=raw_fpv_observations or [],
        camera_model_policy_evidence=camera_model_policy_evidence or {},
        model_declared_observations=model_declared_observations or [],
        model_declared_observation_evidence=model_declared_observation_evidence or {},
        policy_view={
            "schema": "realworld_cleanup_policy_view_v1",
            "allowed_inputs": ["base_metric_map", "runtime_metric_map"],
            "chase_camera_policy_input": False,
            "excluded_report_only_views": ["chase_camera"],
        },
        cleanup_worklist={
            "schema": "cleanup_worklist_v1",
            "waypoint_source": "generated_exploration_candidate",
            "objects": [],
        },
        observed_waypoint_ids=[],
        public_tool_names=[],
        forbidden_keys=frozenset(forbidden_agent_view_keys()),
    )


def _minimal_base_metric_map() -> dict[str, object]:
    return {
        "schema": "real_robot_map_bundle_v1",
        "rooms": [{"room_id": "room_1", "label": "Room 1"}],
        "room_category_hints": [],
        "inspection_waypoints": [],
    }


def _add_isaac_scene_index_map_context(data: dict[str, object], base: Path) -> None:
    scenario_id = "isaac-scene-index-procthor-10k-val-1-7-1"
    map_id = f"{scenario_id}_base_metric_map"
    map_bundle = {
        "schema": "nav2_map_bundle_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "robot_profile_id": "rby1m",
        "parameter_hash": "unit-scene-index-map-context",
    }
    metric_map = {
        "schema": "real_robot_map_bundle_v1",
        "map_bundle": dict(map_bundle),
        "rooms": [_isaac_scene_index_room()],
    }
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "static_map": {
            "map_bundle": dict(map_bundle),
            "rooms": [_isaac_scene_index_room()],
            "scene_index_fixture_overlay": {
                "enabled": True,
                "source": "isaac_scene_index",
                "fixture_count": 1,
            },
        },
    }
    data["scenario_id"] = scenario_id
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["scenario_source"] = "isaac_scene_index"
    data["agent_view"] = _minimal_agent_view(
        base_metric_map=metric_map,
        runtime_metric_map=runtime_map,
    )
    data["runtime_metric_map"] = runtime_map
    semantics_path = base / "map_bundle" / "semantics.json"
    semantics_path.parent.mkdir(parents=True, exist_ok=True)
    semantics_path.write_text(
        json.dumps(
            {
                "schema": "nav2_cleanup_semantics_v1",
                "environment_id": scenario_id,
                "map_id": map_id,
                "map_version": "base-metric-map-v1",
                "rooms": [_isaac_scene_index_room()],
                "fixtures": [],
                "inspection_waypoints": [],
                "driveable_ways": [],
            }
        ),
        encoding="utf-8",
    )
    data["nav2_map_bundle"] = {
        "schema": "nav2_map_bundle_snapshot_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "snapshot_complete": True,
        "artifact_paths": {"semantics_json": "map_bundle/semantics.json"},
        "artifact_hashes": {"semantics_json": "0" * 64},
    }


def _add_isaac_scene_index_base_metric_map_context(data: dict[str, object], base: Path) -> None:
    scenario_id = "isaac-scene-index-procthor-10k-val-1-7-1"
    map_id = f"{scenario_id}_base_metric_map"
    public_room = _isaac_scene_index_room()
    room_category_hints = [_room_category_hint(public_room)]
    map_bundle = {
        "schema": "nav2_map_bundle_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "robot_profile_id": "rby1m",
        "parameter_hash": "unit-scene-index-base-metric-map-context",
    }
    candidates = [
        {
            "waypoint_id": "generated_exploration_001",
            "waypoint_source": "generated_exploration_candidate",
            "purpose": "base_metric_map_exploration",
            "x": 2.99,
            "y": 4.983,
            "room_id": "room_2",
            "room_label": "Room 2",
            "candidate_provenance": {
                "source": "public_occupancy_free_space",
                "source_room_hidden": False,
                "source_room_label_available": True,
                "source_fixtures_hidden": True,
                "source_waypoint_hidden": True,
            },
        },
        {
            "waypoint_id": "generated_exploration_002",
            "waypoint_source": "generated_exploration_candidate",
            "purpose": "base_metric_map_exploration",
            "x": 7.973,
            "y": 2.512,
            "room_id": "room_2",
            "room_label": "Room 2",
            "candidate_provenance": {
                "source": "public_occupancy_free_space",
                "source_room_hidden": False,
                "source_room_label_available": True,
                "source_fixtures_hidden": True,
                "source_waypoint_hidden": True,
            },
        },
    ]
    metric_map = {
        "schema": "real_robot_map_bundle_v1",
        "map_bundle": dict(map_bundle),
        "rooms": [public_room],
        "room_category_hints": room_category_hints,
        "driveable_ways": [],
        "base_metric_map": {"enabled": True},
        "inspection_waypoints": list(candidates),
        "generated_exploration_candidates": list(candidates),
    }
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "source_map_mutated": False,
        "static_map": {
            "map_bundle": dict(map_bundle),
            "rooms": [public_room],
            "fixtures": [],
            "driveable_ways": [],
            "generated_exploration_candidates": list(candidates),
            "inspection_waypoints": list(candidates),
        },
        "generated_exploration_candidates": list(candidates),
        "public_semantic_anchors": [
            {
                "anchor_id": "anchor_waypoint_generated_exploration_001",
                "anchor_type": "observation_waypoint",
                "waypoint_id": "generated_exploration_001",
            }
        ],
    }
    data["scenario_id"] = scenario_id
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["scenario_source"] = "isaac_scene_index"
    data["agent_view"] = _minimal_agent_view(
        base_metric_map=metric_map,
        runtime_metric_map=runtime_map,
    )
    data["runtime_metric_map"] = runtime_map
    semantics_path = base / "map_bundle" / "semantics.json"
    semantics_path.parent.mkdir(parents=True, exist_ok=True)
    semantics_path.write_text(
        json.dumps(
            {
                "schema": "nav2_cleanup_semantics_v1",
                "environment_id": scenario_id,
                "map_id": map_id,
                "map_version": "base-metric-map-v1",
                "rooms": [public_room],
                "fixtures": [],
                "inspection_waypoints": [],
                "driveable_ways": [],
            }
        ),
        encoding="utf-8",
    )
    data["nav2_map_bundle"] = {
        "schema": "nav2_map_bundle_snapshot_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
        "snapshot_complete": True,
        "artifact_paths": {"semantics_json": "map_bundle/semantics.json"},
        "artifact_hashes": {"semantics_json": "0" * 64},
    }


def _room_category_hint(room: dict[str, object]) -> dict[str, object]:
    return {
        "anchor_type": "room_area",
        "category": "room_area",
        "label": str(room["room_label"]),
        "room_id": str(room["room_id"]),
        "room_label": str(room["room_label"]),
        "waypoint_id": "generated_exploration_001",
        "affordances": ["navigate", "observe"],
        "classification_status": "map_prior",
        "confidence": 0.8,
        "aliases": [str(room["room_id"]), str(room["room_label"])],
        "producer_type": "base_metric_map",
    }


def _isaac_scene_index_room() -> dict[str, object]:
    return {
        "room_id": "room_2",
        "room_label": "Room 2",
        "fixture_count": 1,
        "polygon": [
            {"x": 0.0, "y": 0.0},
            {"x": 5.98, "y": 0.0},
            {"x": 5.98, "y": 9.966},
            {"x": 0.0, "y": 9.966},
        ],
        "scene_room_outline": {
            "room_id": "room_2",
            "center": [2.99, 4.983],
            "half_extents": [2.99, 4.983],
            "provenance": "isaac_usd_room_mesh_world_bounds",
            "usd_prim_path": "/val_1/Geometry/room_2_visual_0",
        },
    }


def _write_isaac_robot_view_images(
    base: Path,
    *,
    blank_key: str,
) -> tuple[Path, dict[str, str]]:
    view_dir = base / "isaac_robot_views"
    view_dir.mkdir(parents=True, exist_ok=True)
    views: dict[str, str] = {}
    for key in ("fpv", "chase", "topdown", "verify"):
        path = view_dir / f"step.{key}.png"
        if key == blank_key:
            _write_blank_png(path)
        else:
            _write_nonblank_png(path)
        views[key] = str(path.relative_to(base))
    return view_dir, views


def _ensure_isaac_robot_view_report(base: Path) -> Path:
    report = base / "report.html"
    if report.is_file():
        _insert_robot_timeline_before_score(report)
    else:
        report.write_text("<h2>Robot View Timeline</h2>", encoding="utf-8")
    return report


def _isaac_robot_view_pose() -> dict[str, object]:
    return {
        "schema": "cleanup_robot_pose_result_v1",
        "pose_source": "roboclaws_shared_scene_frame_support_pose",
        "x": 1.0,
        "y": 2.0,
        "z": 0.0,
        "theta": 0.0,
        "pose_request": {
            "schema": "cleanup_robot_pose_request_v1",
            "resolver": "roboclaws.cleanup_robot_pose.near_target_v1",
        },
    }


def _base_isaac_robot_view_steps(views: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "action": "observe mug_01",
            "room_outline_count": 1,
            "views": views,
        },
        {
            "action": "observe sink_01",
            "room_outline_count": 1,
            "views": views,
        },
    ]


__all__ = [name for name in globals() if not name.startswith("__")]
