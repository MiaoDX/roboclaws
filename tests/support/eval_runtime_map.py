from __future__ import annotations

from typing import Any


def quality_public_anchors() -> list[dict[str, Any]]:
    stable_fixtures = (
        ("armchair", "room_3", "room_3_inspection"),
        ("bookshelf", "room_3", "room_3_inspection"),
        ("coffee table", "room_3", "room_3_inspection"),
        ("desk", "room_4", "room_4_inspection"),
        ("floor", "room_3", "room_3_inspection"),
        ("fridge", "room_2", "room_2_inspection"),
        ("laundry hamper", "room_6", "room_6_inspection"),
        ("kitchen sink", "room_2", "room_2_inspection"),
        ("sofa", "room_3", "room_3_inspection"),
        ("toy bin", "room_3", "room_3_inspection"),
    )
    stable = [
        {
            "anchor_id": f"anchor_fixture_{index:03d}",
            "anchor_type": "receptacle" if index % 2 else "surface",
            "category": category,
            "label": category,
            "room_id": room_id,
            "waypoint_id": waypoint_id,
            "pose": {"x": float(index), "y": float(index), "yaw": 0.0},
            "pose_source": "inspection_waypoint",
            "pose_role": "best_view_pose",
            "localization_status": "viewpoint_only",
            "source_observation_id": f"world_label_fpv_{index:03d}",
            "evidence": {"visited": True},
        }
        for index, (category, room_id, waypoint_id) in enumerate(stable_fixtures, start=1)
    ]
    waypoints = [
        {
            "anchor_id": f"anchor_waypoint_extra_{index:03d}",
            "anchor_type": "observation_waypoint",
            "category": "observation_waypoint",
            "label": f"Observation waypoint {index}",
            "room_id": f"room_{index}",
            "waypoint_id": f"generated_exploration_{index:03d}",
            "pose": {"x": float(index), "y": float(index), "yaw": 0.0},
            "pose_source": "inspection_waypoint",
            "pose_role": "inspection_waypoint",
            "localization_status": "viewpoint_only",
            "source_observation_id": f"waypoint_observation:generated_exploration_{index:03d}",
            "evidence": {"visited": True},
        }
        for index in range(1, 10)
    ]
    return stable + waypoints


def quality_target_candidates() -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": f"target_candidate_{index:03d}",
            "candidate_type": "public_semantic_anchor" if index <= 8 else "inspection_area",
            "category": "fixture" if index <= 8 else "inspection_area",
            "label": f"candidate {index}",
            "waypoint_id": "room_8_inspection",
            "localization_status": "viewpoint_only",
            "pose_source": "inspection_waypoint",
            "pose_role": "best_view_pose",
        }
        for index in range(1, 21)
    ]


def quality_observed_objects() -> list[dict[str, Any]]:
    return [
        {
            "object_id": "observed_001",
            "category": "bread",
            "waypoint_id": "room_8_inspection",
            "localization_status": "viewpoint_only",
        }
    ]
