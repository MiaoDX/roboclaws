from __future__ import annotations

import json

from roboclaws.agents.drivers.openai_agents_compaction import _compact_model_input_items
from roboclaws.agents.drivers.openai_agents_event_projection import _model_input_shape_summary


def test_model_input_shape_summary_is_aggregate_only() -> None:
    summary = _model_input_shape_summary(
        [
            {"role": "user", "content": "secret prompt body"},
            {
                "type": "mcp_call",
                "id": "mcp_secret",
                "name": "roboclaws__observe_camera_grounded_candidates",
                "server_label": "roboclaws",
                "arguments": '{"secret": true}',
                "output": "large private tool output body",
                "status": "completed",
            },
            {
                "type": "function_call_output",
                "call_id": "call_metric_map",
                "output": "metric map body",
            },
        ]
    )

    assert summary["schema"] == "openai_agents_model_input_shape_summary_v1"
    assert summary["input_item_count"] == 3
    assert summary["type_counts"] == {
        "<missing>": 1,
        "function_call_output": 1,
        "mcp_call": 1,
    }
    assert summary["tool_field_counts"] == {
        "call_id": 1,
        "id": 1,
        "name": 1,
    }
    assert summary["output_field_counts"] == {"content": 1, "output": 2}
    encoded = json.dumps(summary)
    assert "secret prompt body" not in encoded
    assert "large private tool output body" not in encoded
    assert "roboclaws__observe_camera_grounded_candidates" not in encoded
    assert "metric map body" not in encoded


def test_model_input_compaction_summarizes_repeated_metric_map_outputs() -> None:
    first_map = {
        "ok": True,
        "tool": "metric_map",
        "map_id": "home",
        "map_version": "v1",
        "base_metric_map": {"enabled": True},
        "inspection_waypoints": [
            {
                "waypoint_id": f"wp_{idx}",
                "room": "kitchen",
                "navigation_note": "large public map waypoint payload",
            }
            for idx in range(80)
        ],
        "runtime_metric_map": {
            "observed_objects": [{"object_id": "cup_1"}],
            "target_candidates": [{"object_id": "cup_1"}],
        },
    }
    second_map = {
        **first_map,
        "runtime_metric_map": {
            "observed_objects": [{"object_id": "cup_1"}, {"object_id": "book_1"}],
            "target_candidates": [{"object_id": "cup_1"}, {"object_id": "book_1"}],
        },
    }
    items = [
        {
            "type": "function_call_output",
            "call_id": "call_metric_map_first",
            "output": json.dumps(first_map),
        },
        {
            "type": "function_call_output",
            "call_id": "call_metric_map_second",
            "output": json.dumps(second_map),
        },
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=999_999)

    assert filtered[0] == items[0]
    replacement = json.loads(filtered[1]["output"])
    assert replacement["schema"] == "roboclaws_repeated_metric_map_delta_summary_v1"
    assert replacement["map_id"] == "home"
    assert replacement["inspection_waypoint_count"] == 80
    assert replacement["runtime_observed_object_count"] == 2
    assert "book_1" not in json.dumps(filtered[1])
    assert metrics["metric_map_output_count"] == 2
    assert metrics["repeated_metric_map_output_count"] == 1
    assert metrics["metric_map_delta_compacted_count"] == 1
    assert metrics["metric_map_bytes_after"] < metrics["metric_map_bytes_before"]
    assert metrics["metric_map_bytes_reduced"] > 0


def test_model_input_compaction_keeps_first_metric_map_output_with_opaque_call_ids() -> None:
    first_map = {
        "ok": True,
        "tool": "metric_map",
        "map_id": "home",
        "map_version": "v1",
        "inspection_waypoints": [
            {
                "waypoint_id": f"room_{idx}_inspection",
                "room_id": f"room_{idx}",
                "label": "inspection waypoint",
            }
            for idx in range(80)
        ],
    }
    second_map = {
        **first_map,
        "map_version": "v2",
        "runtime_metric_map": {"observed_objects": [{"object_id": "book_1"}]},
    }
    items = [
        {"type": "function_call", "call_id": "call_opaque_1", "name": "metric_map"},
        {
            "type": "function_call_output",
            "call_id": "call_opaque_1",
            "output": json.dumps(first_map),
        },
        {"type": "function_call", "call_id": "call_opaque_2", "name": "metric_map"},
        {
            "type": "function_call_output",
            "call_id": "call_opaque_2",
            "output": json.dumps(second_map),
        },
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=1200)

    assert filtered[1] == items[1]
    replacement = json.loads(filtered[3]["output"])
    assert replacement["schema"] == "roboclaws_repeated_metric_map_delta_summary_v1"
    assert replacement["map_version"] == "v2"
    assert replacement["inspection_waypoint_count"] == 80
    assert "room_79_inspection" in filtered[1]["output"]
    assert "room_79_inspection" not in filtered[3]["output"]
    assert metrics["metric_map_output_count"] == 2
    assert metrics["repeated_metric_map_output_count"] == 1
    assert metrics["metric_map_delta_compacted_count"] == 1
    assert metrics["metric_map_bytes_before"] > metrics["metric_map_bytes_after"]


def test_model_input_compaction_projects_oversized_first_metric_map() -> None:
    metric_map = {
        "ok": True,
        "tool": "metric_map",
        "map_id": "home",
        "inspection_waypoints": [{"waypoint_id": "room_2_inspection", "room_id": "room_2"}],
        "runtime_metric_map": {
            "public_semantic_anchors": [
                {
                    "anchor_id": "anchor_fixture_001",
                    "category": "sink",
                    "waypoint_id": "room_2_inspection",
                }
            ],
            "target_candidates": [
                {
                    "candidate_id": "candidate_001",
                    "category": "plate",
                    "target_actionability_status": "navigation_authorized",
                    "required_tool": "navigate_to_object",
                    "destination_options": [
                        {
                            "candidate_fixture_id": "anchor_fixture_001",
                            "recommended_tool": "place",
                        }
                    ],
                }
            ],
            "cleanup_worklist_summary": {"pending_count": 1},
            "target_query_recovery": {"repeated_prose": "x" * 160_000},
        },
    }
    items = [
        {
            "type": "function_call_output",
            "call_id": "call_metric_map_first",
            "output": json.dumps(metric_map),
        }
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=1200)

    projection = json.loads(filtered[0]["output"])
    assert projection["schema"] == "roboclaws_oversized_metric_map_snapshot_v1"
    assert projection["inspection_waypoints"][0]["waypoint_id"] == "room_2_inspection"
    assert projection["public_semantic_anchors"][0]["anchor_id"] == "anchor_fixture_001"
    assert projection["target_candidates"][0]["candidate_id"] == "candidate_001"
    assert (
        projection["target_candidates"][0]["target_actionability_status"] == "navigation_authorized"
    )
    assert projection["target_candidates"][0]["destination_options"][0] == {
        "candidate_fixture_id": "anchor_fixture_001",
        "recommended_tool": "place",
    }
    assert "repeated_prose" not in filtered[0]["output"]
    assert projection["cleanup_worklist_summary"] == {"pending_count": 1}
    assert metrics["oversized_metric_map_compacted_count"] == 1
    assert metrics["metric_map_bytes_after"] < metrics["metric_map_bytes_before"] / 4
