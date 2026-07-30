from __future__ import annotations

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import cleanup_validation as result_checker
from roboclaws.household.cleanup_validation_base_map import (
    assert_base_metric_map,
)
from roboclaws.maps.base_waypoints import (
    BASE_WAYPOINT_GENERATION_POLICY,
    BASE_WAYPOINT_PURPOSE,
    BASE_WAYPOINT_SOURCE,
)


def test_checker_accepts_canonical_base_area_inspection_waypoints() -> None:
    agent_view = _agent_view_with_waypoint(_canonical_base_waypoint())
    data = {"runtime_metric_map": agent_view_module.runtime_metric_map(agent_view)}

    assert_base_metric_map(data, agent_view)


def test_checker_rejects_fixture_fields_on_canonical_base_waypoints() -> None:
    waypoint = _canonical_base_waypoint()
    waypoint["fixture_id"] = "private_fixture"
    agent_view = _agent_view_with_waypoint(waypoint)
    data = {"runtime_metric_map": agent_view_module.runtime_metric_map(agent_view)}

    with pytest.raises(AssertionError):
        assert_base_metric_map(data, agent_view)


def test_semantic_success_gate_uses_score_acceptability_not_substep_count() -> None:
    opts = result_checker._result_assert_options(
        {
            "min_generated_mess_count": 5,
            "min_semantic_accepted_count": 5,
        }
    )
    data = {
        "generated_mess_count": 5,
        "sweep_coverage_rate": 1.0,
        "disturbance_count": 0,
        "private_evaluation": {
            "generated_mess_count": 5,
            "acceptable_destination_sets": {"obj": ["sink"]},
        },
        "score": {
            "semantic_acceptability": {
                "status": "success",
                "accepted_count": 5,
                "accepted_levels": ["preferred", "acceptable"],
            }
        },
        "semantic_substeps": [
            {"steps": [{"phase": "navigate_to_object", "ok": True}]},
        ],
    }

    result_checker._assert_core_cleanup_success(data, opts, semantic_success_gate=True)
    result_checker._assert_core_thresholds(data, opts)
    result_checker._assert_private_evaluation_and_semantic_success(
        data,
        opts,
        enforce_success=True,
        semantic_success_gate=True,
    )


def _canonical_base_waypoint() -> dict[str, object]:
    return {
        "waypoint_id": "room_2_inspection",
        "waypoint_source": BASE_WAYPOINT_SOURCE,
        "purpose": BASE_WAYPOINT_PURPOSE,
        "generation_policy": BASE_WAYPOINT_GENERATION_POLICY,
        "navigation_area_id": "room_2",
        "frame_id": "map",
        "x": 6.4,
        "y": 7.5,
        "yaw": 0.0,
        "room_id": "room_2",
        "room_label": "Kitchen",
        "label": "Kitchen",
        "sweep_index": 1,
    }


def _agent_view_with_waypoint(waypoint: dict[str, object]) -> dict[str, object]:
    room = {
        "room_id": "room_2",
        "room_label": "Kitchen",
        "navigation_area_id": "room_2",
    }
    runtime_map = {
        "schema": "runtime_metric_map_v1",
        "source_map_mutated": False,
        "static_map": {
            "rooms": [dict(room)],
            "fixtures": [],
            "driveable_ways": [],
        },
        "generated_exploration_candidates": [dict(waypoint)],
        "generated_target_inspection_candidates": [],
        "public_semantic_anchors": [
            {
                "anchor_id": "anchor_waypoint_room_2_inspection",
                "anchor_type": "observation_waypoint",
                "waypoint_id": "room_2_inspection",
            }
        ],
    }
    metric_map = {
        "base_metric_map": {"enabled": True},
        "rooms": [room],
        "driveable_ways": [],
        "room_category_hints": [
            {
                "anchor_id": "anchor_room_2",
                "anchor_type": "room_area",
                "room_id": "room_2",
            }
        ],
        "inspection_waypoints": [dict(waypoint)],
    }
    return agent_view_module.build_agent_view(
        contract="realworld_cleanup_v1",
        perception_mode="visible_object_detections",
        detection_exposure_policy="world_public_labels",
        structured_detections_available=True,
        base_metric_map=metric_map,
        runtime_metric_map=runtime_map,
        observed_objects=[],
        raw_fpv_observations=[],
        camera_model_policy_evidence={},
        model_declared_observations=[],
        model_declared_observation_evidence={},
        policy_view={
            "schema": "realworld_cleanup_policy_view_v1",
            "excluded_report_only_views": [],
            "chase_camera_policy_input": False,
        },
        cleanup_worklist={"schema": "cleanup_worklist_v1", "objects": [], "waypoints": []},
        observed_waypoint_ids=[],
        public_tool_names=["metric_map"],
        forbidden_keys=frozenset(),
    )
