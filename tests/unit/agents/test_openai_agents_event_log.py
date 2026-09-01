from __future__ import annotations

from roboclaws.agents.drivers.openai_agents_event_log import _append_model_input_filter_event


def test_model_input_telemetry_excludes_forbidden_sentinel_values(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    sentinels = {
        "private_score": "PRIVATE-SCORING-TRUTH",
        "credential": "CREDENTIAL-SECRET",
        "raw_prompt": "RAW-PROMPT-SECRET",
        "payload": "FULL-PAYLOAD-SECRET",
    }
    _append_model_input_filter_event(
        path,
        runtime_config={"runtime": "test"},
        config={"enabled": True},
        metrics={"filtered": 1},
        input_items=[{"type": "function_call_output", "output": sentinels}],
    )
    persisted = path.read_text(encoding="utf-8")
    assert all(value not in persisted for value in sentinels.values())
    assert "function_call_output" in persisted
