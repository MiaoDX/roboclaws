from __future__ import annotations

import json

from roboclaws.agents.drivers.openai_agents_compaction import _compact_model_input_items


def test_model_input_compaction_evicted_raw_fpv_images_keep_latest_frame() -> None:
    items = [
        {
            "type": "function_call_output",
            "call_id": "observe_raw_fpv_001",
            "output": json.dumps(
                {
                    "schema": "raw_fpv_mcp_observe_state_v1",
                    "raw_fpv_observation": {"observation_id": "raw_fpv_001"},
                }
            ),
        },
        {
            "type": "image",
            "_mime_type": "image/png",
            "_format": "png",
            "data": "raw_fpv_001:" + ("a" * 3_000),
        },
        {
            "type": "function_call_output",
            "call_id": "observe_raw_fpv_002",
            "output": json.dumps(
                {
                    "schema": "raw_fpv_mcp_observe_state_v1",
                    "raw_fpv_observation": {"observation_id": "raw_fpv_002"},
                }
            ),
        },
        {
            "type": "image",
            "_mime_type": "image/png",
            "_format": "png",
            "data": "raw_fpv_002:" + ("b" * 3_000),
        },
    ]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        raw_fpv_image_memory={
            "enabled": True,
            "mode": "retain_latest_full_frame",
            "retained_full_frame_limit": 1,
        },
    )

    assert filtered[0] == items[0]
    assert filtered[2] == items[2]
    evicted = filtered[1]
    assert evicted["schema"] == "raw_fpv_evicted_image_frame_summary_v1"
    assert evicted["observation_id"] == "raw_fpv_001"
    assert evicted["original_data_bytes"] > 0
    assert "a" * 20 not in json.dumps(evicted)
    assert filtered[3] == items[3]
    assert metrics["raw_fpv_image_memory_enabled"] is True
    assert metrics["raw_fpv_image_item_count"] == 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_evicted_count"] == 1
    assert metrics["raw_fpv_image_bytes_after"] < metrics["raw_fpv_image_bytes_before"]
    assert metrics["raw_fpv_image_bytes_reduced"] > 0


def test_model_input_compaction_handles_sdk_nested_raw_fpv_images() -> None:
    def observe_output(observation_id: str, image_byte: str) -> dict[str, object]:
        return {
            "type": "function_call_output",
            "call_id": f"observe_{observation_id}",
            "output": [
                {
                    "type": "input_text",
                    "text": json.dumps(
                        {
                            "schema": "raw_fpv_mcp_observe_state_v1",
                            "raw_fpv_observation": {"observation_id": observation_id},
                        }
                    ),
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{image_byte * 3_000}",
                },
            ],
        }

    items = [observe_output("raw_fpv_001", "a"), observe_output("raw_fpv_002", "b")]

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=1200,
        raw_fpv_image_memory={
            "enabled": True,
            "mode": "retain_latest_full_frame",
            "retained_full_frame_limit": 1,
        },
    )

    assert filtered[0]["output"][0] == items[0]["output"][0]
    evicted = filtered[0]["output"][1]
    assert evicted["type"] == "input_text"
    evicted_summary = json.loads(evicted["text"])
    assert evicted_summary["schema"] == "raw_fpv_evicted_image_frame_summary_v1"
    assert evicted_summary["observation_id"] == "raw_fpv_001"
    assert "a" * 20 not in json.dumps(filtered[0])
    assert filtered[1] == items[1]
    assert filtered[1]["output"][1]["type"] == "input_image"
    assert metrics["raw_fpv_image_item_count"] == 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_evicted_count"] == 1


def test_model_input_compaction_does_not_summarize_latest_sdk_raw_fpv_image() -> None:
    item = {
        "type": "function_call_output",
        "call_id": "observe_raw_fpv_001",
        "output": [
            {
                "type": "input_text",
                "text": json.dumps(
                    {
                        "schema": "raw_fpv_mcp_observe_state_v1",
                        "raw_fpv_observation": {"observation_id": "raw_fpv_001"},
                    }
                ),
            },
            {"type": "input_image", "image_url": "data:image/png;base64," + "a" * 3_000},
        ],
    }

    filtered, metrics = _compact_model_input_items(
        [item],
        min_chars=1200,
        public_tool_output_summary=True,
        raw_fpv_image_memory={
            "enabled": True,
            "mode": "retain_latest_full_frame",
            "retained_full_frame_limit": 1,
        },
    )

    assert filtered == [item]
    assert metrics["compacted_item_count"] == 0
    assert metrics["raw_fpv_image_item_count"] == 1
    assert metrics["raw_fpv_image_retained_count"] == 1
