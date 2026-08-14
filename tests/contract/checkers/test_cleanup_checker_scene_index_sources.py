from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import cleanup_validation_evidence as checker_module


def _load_checker():
    return checker_module


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            (
                r"Isaac scene-index Nav2 semantics source must contain valid JSON object: "
                r".*semantics\.json"
            ),
        ),
        (
            "[]\n",
            (
                r"Isaac scene-index Nav2 semantics source must contain a JSON object: "
                r".*semantics\.json"
            ),
        ),
    ],
)
def test_checker_rejects_malformed_scene_index_semantics_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    checker = _load_checker()
    semantics_path = tmp_path / "map_bundle" / "semantics.json"
    semantics_path.parent.mkdir()
    semantics_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        checker._assert_isaac_scene_index_map_context(_scene_index_run_result(), tmp_path)


def test_checker_rejects_missing_scene_index_semantics_source(tmp_path: Path) -> None:
    checker = _load_checker()

    with pytest.raises(
        FileNotFoundError,
        match=(
            r"Isaac scene-index Nav2 semantics source is missing: "
            r".*map_bundle/semantics\.json"
        ),
    ):
        checker._assert_isaac_scene_index_map_context(_scene_index_run_result(), tmp_path)


def _scene_index_run_result() -> dict[str, object]:
    scenario_id = "isaac-scene-index-procthor-10k-val-1-7-1"
    map_id = f"{scenario_id}_base_metric_map"
    map_bundle = {
        "schema": "nav2_map_bundle_v1",
        "environment_id": scenario_id,
        "map_id": map_id,
        "map_version": "base-metric-map-v1",
        "source_provenance": "molmospaces_base_metric_map",
    }
    room = {
        "room_id": "living_room_01",
        "room_label": "Living Room",
        "category": "living_room",
        "centroid": [1.0, 2.0],
        "area_m2": 12.0,
    }
    candidates = [
        _generated_candidate("generated_exploration_001", 1.0, 1.0),
        _generated_candidate("generated_exploration_002", 5.0, 4.0),
    ]
    room_category_hints = [
        {
            "anchor_type": "room_area",
            "category": "room_area",
            "label": "Living Room",
            "room_id": "living_room_01",
            "room_label": "Living Room",
            "waypoint_id": "generated_exploration_001",
            "affordances": ["navigate", "observe"],
            "classification_status": "map_prior",
            "confidence": 0.8,
            "producer_type": "base_metric_map",
        }
    ]
    metric_map = {
        "schema": "real_robot_map_bundle_v1",
        "map_bundle": dict(map_bundle),
        "rooms": [room],
        "room_category_hints": room_category_hints,
        "base_metric_map": {"enabled": True},
        "inspection_waypoints": list(candidates),
        "generated_exploration_candidates": list(candidates),
    }
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "source_map_mutated": False,
        "static_map": {
            "map_bundle": dict(map_bundle),
            "rooms": [room],
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
    return {
        "scenario_id": scenario_id,
        "isaac_runtime": {"scenario_source": "isaac_scene_index"},
        "agent_view": agent_view_module.build_agent_view(
            contract="realworld_cleanup_v1",
            perception_mode="visible_object_detections",
            detection_exposure_policy="public_runtime_map",
            structured_detections_available=True,
            base_metric_map=metric_map,
            runtime_metric_map=runtime_map,
            observed_objects=[],
            raw_fpv_observations=[],
            camera_model_policy_evidence={},
            model_declared_observations=[],
            model_declared_observation_evidence={},
            policy_view={},
            cleanup_worklist={},
            observed_waypoint_ids=[],
            public_tool_names=[],
            forbidden_keys=frozenset(),
        ),
        "runtime_metric_map": runtime_map,
        "nav2_map_bundle": {
            "schema": "nav2_map_bundle_snapshot_v1",
            "environment_id": scenario_id,
            "map_id": map_id,
            "map_version": "base-metric-map-v1",
            "source_provenance": "molmospaces_base_metric_map",
            "artifact_paths": {"semantics_json": "map_bundle/semantics.json"},
        },
    }


def _generated_candidate(waypoint_id: str, x: float, y: float) -> dict[str, object]:
    return {
        "waypoint_id": waypoint_id,
        "waypoint_source": "generated_exploration_candidate",
        "purpose": "base_metric_map_exploration",
        "x": x,
        "y": y,
        "room_id": "living_room_01",
        "room_label": "Living Room",
        "candidate_provenance": {
            "source": "public_occupancy_free_space",
            "source_room_hidden": False,
            "source_room_label_available": True,
            "source_fixtures_hidden": True,
            "source_waypoint_hidden": True,
        },
    }
