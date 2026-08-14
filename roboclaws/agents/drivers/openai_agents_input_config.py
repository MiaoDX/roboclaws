"""Model-input run configuration for the OpenAI Agents runtime."""

from __future__ import annotations

from typing import Any

from roboclaws.agents.drivers.openai_agents_grounded_history import _camera_grounded_history_policy
from roboclaws.agents.drivers.openai_agents_image_memory import _raw_fpv_image_memory_policy
from roboclaws.agents.drivers.openai_agents_setting_values import (
    _bool_setting,
    _nonnegative_int,
    _positive_int_from_value_or_env,
)
from roboclaws.agents.live_runtime import LiveAgentRequest

DEFAULT_MODEL_INPUT_COMPACTION_MIN_CHARS = 1200
MODEL_INPUT_COMPACTION_MIN_CHARS_ENV = "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS"


def _input_compaction_config(request: LiveAgentRequest) -> dict[str, Any]:
    metadata = dict(request.metadata)
    profile = metadata.get("agent_sdk_perf_profile")
    config = profile.get("model_input_compaction") if isinstance(profile, dict) else None
    if not isinstance(config, dict):
        config = metadata.get("model_input_compaction")
    if not isinstance(config, dict):
        config = {}
    enabled = _bool_setting(config.get("enabled"), "model_input_compaction.enabled", default=False)
    mode = str(config.get("mode") or ("public_tool_result_summary_v1" if enabled else "off"))
    min_chars = _positive_int_from_value_or_env(
        config.get("min_chars"),
        env_name=MODEL_INPUT_COMPACTION_MIN_CHARS_ENV,
        default=DEFAULT_MODEL_INPUT_COMPACTION_MIN_CHARS,
        setting_name="model_input_compaction.min_chars",
    )
    payload = {
        "schema": "agent_sdk_model_input_compaction_v1",
        "enabled": enabled,
        "mode": mode,
        "min_chars": min_chars,
        "private_artifact_policy": (
            "filter is model-facing only; MCP traces, reports, and run artifacts remain complete"
        ),
    }
    history_limit = _nonnegative_int(
        config.get("completed_tool_history_limit"),
        default=0,
        setting_name="model_input_compaction.completed_tool_history_limit",
    )
    payload["completed_tool_history_limit"] = history_limit
    raw_fpv_image_memory = config.get("raw_fpv_image_memory")
    if isinstance(raw_fpv_image_memory, dict):
        payload["raw_fpv_image_memory"] = _raw_fpv_image_memory_policy(raw_fpv_image_memory)
    camera_grounded_history = config.get("camera_grounded_history")
    if isinstance(camera_grounded_history, dict):
        payload["camera_grounded_history"] = _camera_grounded_history_policy(
            camera_grounded_history
        )
    return payload
