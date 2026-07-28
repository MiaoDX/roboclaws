from __future__ import annotations

import base64
import io
import json
import random

from PIL import Image

from roboclaws.agents.drivers.openai_agents_model_input import (
    _compact_model_input_items,
)


def test_retained_raw_fpv_frame_uses_smaller_same_size_jpeg() -> None:
    width, height = 540, 360
    pixels = random.Random(7).randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), pixels)
    png_buffer = io.BytesIO()
    image.save(png_buffer, format="PNG")
    png = png_buffer.getvalue()
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
            {
                "type": "input_image",
                "image_url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            },
        ],
    }

    filtered, metrics = _compact_model_input_items(
        [item],
        min_chars=1200,
        raw_fpv_image_memory={
            "enabled": True,
            "retained_full_frame_limit": 1,
        },
    )

    image_url = filtered[0]["output"][1]["image_url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    jpeg = base64.b64decode(image_url.split(",", 1)[1])
    with Image.open(io.BytesIO(jpeg)) as retained:
        assert retained.size == (width, height)
    assert len(jpeg) < len(png) / 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_transcoded_count"] == 1
    assert metrics["raw_fpv_image_bytes_reduced"] > 0


def test_completed_tool_history_window_keeps_pairs_and_recent_state() -> None:
    items: list[dict[str, object]] = [
        {"role": "user", "content": "continue the public household task"},
        {
            "type": "function_call",
            "call_id": "metric_map_call",
            "name": "metric_map",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "metric_map_call",
            "output": '{"inspection_waypoints":["room_2_inspection"]}',
        },
    ]
    for index in range(64):
        call_id = f"observe_call_{index:02d}"
        items.extend(
            [
                {
                    "type": "reasoning",
                    "id": f"reasoning_{index:02d}",
                    "encrypted_content": "opaque-reasoning-state-" + ("x" * 200),
                    "summary": [],
                },
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": "observe",
                    "arguments": "{}",
                },
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(
                        {
                            "observation_id": f"raw_fpv_{index:03d}",
                            "agent_facing_compact_state": {"step": index},
                        }
                    ),
                },
            ]
        )

    filtered, metrics = _compact_model_input_items(
        items,
        min_chars=999_999,
        public_tool_output_summary=False,
        repeated_metric_map_delta=False,
        completed_tool_history_limit=8,
    )

    call_ids = {str(item["call_id"]) for item in filtered if item.get("type") == "function_call"}
    output_ids = {
        str(item["call_id"]) for item in filtered if item.get("type") == "function_call_output"
    }
    assert call_ids == output_ids
    assert "metric_map_call" in call_ids
    assert "observe_call_63" in call_ids
    assert "observe_call_00" not in call_ids
    assert filtered[0]["role"] == "user"
    assert any(item.get("id") == "reasoning_56" for item in filtered)
    assert metrics["completed_tool_history_bundle_count"] == 65
    assert metrics["completed_tool_history_retained_count"] == 9
    assert metrics["completed_tool_history_evicted_count"] == 56
    assert metrics["completed_tool_history_item_count_after"] < len(items) / 2
    assert metrics["completed_tool_history_bytes_reduced"] > 0
