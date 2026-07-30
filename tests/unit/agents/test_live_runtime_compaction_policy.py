from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.agents.drivers.openai_agents_compaction import _compact_model_input_items
from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    resolve_agent_sdk_perf_profile as _resolve_agent_sdk_perf_profile,
)
from roboclaws.agents.household_live_runner import (
    _model_input_filter_metrics,
)
from roboclaws.agents.live_runtime import (
    LiveAgentMCPServer,
    LiveAgentRequest,
)
from tests.unit.agents.live_runtime_support import (
    FakeModelSettings,
    FakeRunConfig,
    _expected_raw_fpv_image_memory_policy,
    _openai_agents_perf_profile_base_args,
)


def test_openai_agents_runtime_configures_model_input_compaction_filter(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    monkeypatch.setenv("MM_BASE_URL", "https://minimax.example.test/v1")
    monkeypatch.setenv("MM_API_KEY", "fake-minimax-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        lambda *_args, **_kwargs: SimpleNamespace(final_output="done"),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: (
                    captured.setdefault("runner_kwargs", kwargs) or SimpleNamespace()
                )
            ),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: (
                captured.setdefault("mcp_server_kwargs", kwargs) or SimpleNamespace(kwargs=kwargs)
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="minimax-responses",
        metadata={
            "agent_sdk_perf_profile": {
                "profile_id": "custom",
                "provider_profile": "minimax-responses",
                "wire_api": "responses",
                "model_input_compaction": {
                    "enabled": True,
                    "mode": "public_tool_result_summary_v1+camera_grounded_history_v1",
                    "min_chars": 80,
                    "camera_grounded_history": {
                        "schema": "agent_sdk_camera_grounded_history_policy_v1",
                        "enabled": True,
                        "mode": "retain_latest_actionable_outputs",
                        "retained_recent_outputs": 2,
                        "candidate_ids": ["AC"],
                    },
                },
            }
        },
    )

    OpenAIAgentsLiveRuntime().run(request)

    run_config = captured["runner_kwargs"]["run_config"]
    assert callable(run_config.call_model_input_filter)
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["model_input_compaction"]["enabled"] is True
    assert (
        events[0]["model_input_compaction"]["mode"]
        == "public_tool_result_summary_v1+camera_grounded_history_v1"
    )
    assert events[0]["model_input_compaction"]["camera_grounded_history"] == {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": True,
        "mode": "retain_latest_actionable_outputs",
        "retained_recent_outputs": 2,
        "summary_kind": "roboclaws_camera_grounded_history_summary_v1",
        "candidate_ids": ["AC"],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }
    assert "call_model_input_filter" not in events[0]["sdk_run_config"]


def test_openai_agents_compaction_filter_warns_before_model_call_on_observe_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model

    class FakeAsyncOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            pass

    def fake_run_with_async_mcp_server(_server, _agent, request, _events_path, *, run_config):
        data = SimpleNamespace(
            model_data=SimpleNamespace(
                input=[{"role": "user", "content": "continue map build"}],
                instructions="inspect the next waypoint",
            )
        )
        (request.run_dir / "trace.jsonl").write_text(
            "\n".join(
                json.dumps(item)
                for item in [
                    {
                        "event": "response",
                        "tool": "observe",
                        "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
                    },
                    {
                        "event": "response",
                        "tool": "observe",
                        "response": {"ok": True, "waypoint_id": "generated_exploration_001"},
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        captured["filtered_model_data"] = asyncio.run(run_config.call_model_input_filter(data))
        return SimpleNamespace(final_output="continued after observation advisory")

    monkeypatch.setenv("MM_BASE_URL", "https://minimax.example.test/v1")
    monkeypatch.setenv("MM_API_KEY", "fake-minimax-key")
    monkeypatch.setattr(
        "roboclaws.agents.drivers.openai_agents_live._run_with_async_mcp_server",
        fake_run_with_async_mcp_server,
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents",
        SimpleNamespace(
            Agent=lambda **kwargs: captured.setdefault("agent_kwargs", kwargs),
            Runner=SimpleNamespace(
                run_sync=lambda *_args, **kwargs: captured.setdefault("runner_kwargs", kwargs)
            ),
            ModelSettings=FakeModelSettings,
            RunConfig=FakeRunConfig,
            OpenAIResponsesModel=FakeOpenAIResponsesModel,
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agents.mcp",
        SimpleNamespace(
            MCPServerStreamableHttp=lambda **kwargs: SimpleNamespace(
                __aenter__=lambda: None,
                kwargs=kwargs,
            )
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
    )
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-map-build",
        kickoff_prompt="build a map",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        provider_profile="minimax-responses",
        metadata={
            "provider_profile": "minimax-responses",
            "evidence_lane": "camera-grounded-labels",
            "agent_sdk_perf_profile": {
                "profile_id": "context_managed_v1",
                "provider_profile": "minimax-responses",
                "wire_api": "responses",
                "context_hard_limit_tokens": None,
                "max_observe_per_waypoint": 1,
                "raw_fpv_candidate_budget": None,
                "raw_fpv_repeated_failure_limit": None,
                "model_input_compaction": {"enabled": False, "mode": "off"},
            },
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.exit_status == 0
    assert result.phase == "agent-turn-complete"
    filtered_model_data = captured["filtered_model_data"]
    assert "Observation cadence advisory" in filtered_model_data.instructions
    assert "generated_exploration_001" in filtered_model_data.instructions
    assert "preferred limit of 1" in filtered_model_data.instructions
    events = [
        json.loads(line)
        for line in (tmp_path / "run" / "openai-agents-events.jsonl").read_text().splitlines()
    ]
    assert events[0]["model_input_compaction"]["enabled"] is False
    assert not any(item.get("event") == "model_input_budget_guard" for item in events)
    advisory_event = next(
        item for item in events if item.get("event") == "model_input_budget_advisory"
    )
    assert advisory_event["reason"] == "observe_budget_exceeded"
    assert advisory_event["detail_schema"] == "agent_sdk_observe_budget_advisory_v1"
    assert advisory_event["detail_summary"]["observe_over_budget_by_waypoint"] == {
        "generated_exploration_001": 2
    }


def test_model_input_compaction_reduces_oversized_public_tool_outputs() -> None:
    large_output = json.dumps(
        {
            "tool": "inspect_visible_object",
            "object_id": "object_1",
            "public_observations": [
                {"note": f"large public observation payload {idx}", "objects": ["cup", "plate"]}
                for idx in range(20)
            ],
        }
    )
    items = [
        {"role": "user", "content": "clean the room"},
        {
            "type": "function_call_output",
            "call_id": "call_old_inspect_visible_object",
            "output": large_output,
        },
        {
            "type": "function_call_output",
            "call_id": "call_latest_inspect_visible_object",
            "output": large_output.replace("object_1", "object_2"),
        },
        {
            "type": "function_call_output",
            "call_id": "call_operator_checkpoint",
            "output": '{"ok":true,"pending_operator_message_count":0}',
        },
    ]

    filtered, metrics = _compact_model_input_items(items, min_chars=80)

    assert metrics["input_item_count"] == 4
    assert metrics["compacted_item_count"] == 1
    assert metrics["input_bytes_after"] < metrics["input_bytes_before"]
    assert filtered[0] == items[0]
    assert filtered[1]["call_id"] == "call_old_inspect_visible_object"
    replacement = json.loads(filtered[1]["output"])
    assert replacement["schema"] == "roboclaws_public_tool_output_summary_v1"
    assert replacement["original_chars"] == len(large_output)
    assert filtered[2] == items[2]
    assert "large public observation payload 19" in filtered[2]["output"]
    assert filtered[3] == items[3]


def test_model_input_compaction_rejects_invalid_min_chars_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS", "many")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={"model_input_compaction": {"enabled": True}},
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert "ROBOCLAWS_OPENAI_AGENTS_INPUT_COMPACTION_MIN_CHARS" in payload["detail"]
    assert "must be a positive integer" in payload["detail"]


@pytest.mark.parametrize(
    ("metadata", "setting_name"),
    [
        (
            {"model_input_compaction": {"enabled": "sometimes"}},
            "model_input_compaction.enabled",
        ),
        (
            {
                "model_input_compaction": {
                    "enabled": True,
                    "raw_fpv_image_memory": {"enabled": "sometimes"},
                }
            },
            "raw_fpv_image_memory.enabled",
        ),
        (
            {
                "model_input_compaction": {
                    "enabled": True,
                    "camera_grounded_history": {"enabled": "sometimes"},
                }
            },
            "camera_grounded_history.enabled",
        ),
    ],
)
def test_model_input_compaction_rejects_invalid_boolean_settings(
    tmp_path: Path,
    monkeypatch,
    metadata: dict[str, object],
    setting_name: str,
) -> None:
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata=metadata,
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert setting_name in payload["detail"]
    assert "must be true or false" in payload["detail"]


def test_model_input_compaction_rejects_invalid_direct_policy_limits(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example.test/v1")
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    request = LiveAgentRequest(
        run_id="household-world",
        skill_name="household-world",
        kickoff_prompt="clean the room",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://127.0.0.1:18788/mcp"),
        run_dir=tmp_path / "run",
        metadata={
            "model_input_compaction": {
                "enabled": True,
                "raw_fpv_image_memory": {
                    "enabled": True,
                    "retained_full_frame_limit": "latest",
                },
            }
        },
    )

    result = OpenAIAgentsLiveRuntime().run(request)

    assert result.phase == "failed"
    assert result.reason == "provider_config_failure"
    payload = json.loads((tmp_path / "run" / "live_status.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "provider_config_failure"
    assert (
        "OpenAI Agents SDK setting raw_fpv_image_memory.retained_full_frame_limit"
        in payload["detail"]
    )
    assert "must be a positive integer, got 'latest'" in payload["detail"]


def test_openai_agents_perf_profile_resolves_custom_compaction(monkeypatch) -> None:
    monkeypatch.delenv("ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE", raising=False)
    compaction = _resolve_agent_sdk_perf_profile(
        _openai_agents_perf_profile_base_args(
            agent_sdk_perf_profile="context_managed_v1",
            profile="camera-raw-fpv",
            model_input_compaction=True,
            model_input_compaction_min_chars=80,
            raw_fpv_image_memory=True,
            raw_fpv_image_memory_retain=2,
            camera_grounded_history_compaction=True,
            camera_grounded_history_retain=3,
            camera_grounded_composite_tools=True,
        )
    )

    model_input = compaction["model_input_compaction"]
    assert model_input["schema"] == "agent_sdk_model_input_compaction_v1"
    assert model_input["enabled"] is True
    assert model_input["mode"] == (
        "public_tool_result_summary_v1+repeated_metric_map_delta_v1+raw_fpv_image_memory_v1+"
        "camera_grounded_history_v1"
    )
    assert model_input["min_chars"] == 80
    assert model_input["candidate_ids"] == ["I", "N", "AA", "AC"]
    assert model_input["completed_tool_history_limit"] == 0
    assert model_input["hook"] == "RunConfig.call_model_input_filter"
    assert model_input["repeated_metric_map_delta"] is True
    assert model_input["raw_fpv_image_memory"] == _expected_raw_fpv_image_memory_policy(2)
    assert model_input["camera_grounded_history"] == {
        "schema": "agent_sdk_camera_grounded_history_policy_v1",
        "enabled": True,
        "mode": "retain_latest_actionable_outputs",
        "retained_recent_outputs": 3,
        "candidate_ids": ["AC"],
        "private_artifact_policy": (
            "model-facing camera-grounded history compaction only; MCP traces, reports, "
            "and run artifacts remain complete"
        ),
    }
    assert model_input["private_artifact_policy"] == (
        "model-facing compaction only; MCP traces, reports, and run artifacts remain complete"
    )
    assert compaction["camera_grounded_composite_tools"] == {
        "schema": "agent_sdk_camera_grounded_composite_tools_v1",
        "enabled": True,
        "tool_names": ["observe_camera_grounded_candidates"],
        "candidate_ids": ["O"],
        "scope": "camera-grounded-labels only",
        "hook": "cleanup MCP server private extra tool",
        "private_artifact_policy": (
            "SDK-private MCP tool addition only; default public MCP/profile tools remain unchanged"
        ),
    }


def test_openai_agents_compaction_filter_metrics_are_aggregate_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "openai-agents-events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "openai_agents_model_input_filter_v1",
                        "event": "model_input_filter",
                        "provider_profile": "kimi-openai-chat",
                        "wire_api": "responses",
                        "model": "kimi-k2.7-code",
                        "config": {
                            "enabled": True,
                            "mode": "public_tool_result_summary_v1",
                        },
                        "metrics": {
                            "input_item_count": 3,
                            "compacted_item_count": 2,
                            "unchanged_item_count": 1,
                            "repeated_item_count": 1,
                            "input_bytes_before": 2000,
                            "input_bytes_after": 800,
                            "input_bytes_reduced": 1200,
                            "metric_map_output_count": 2,
                            "repeated_metric_map_output_count": 1,
                            "metric_map_delta_compacted_count": 1,
                            "metric_map_bytes_before": 1400,
                            "metric_map_bytes_after": 500,
                            "metric_map_bytes_reduced": 900,
                            "raw_fpv_image_memory_enabled": True,
                            "raw_fpv_image_memory_mode": "retain_latest_full_frame",
                            "raw_fpv_image_item_count": 2,
                            "raw_fpv_image_retained_count": 1,
                            "raw_fpv_image_evicted_count": 1,
                            "raw_fpv_image_bytes_before": 1000,
                            "raw_fpv_image_bytes_after": 350,
                            "raw_fpv_image_bytes_reduced": 650,
                        },
                    }
                ),
                json.dumps(
                    {
                        "schema": "openai_agents_model_input_filter_v1",
                        "event": "model_input_filter",
                        "provider_profile": "kimi-openai-chat",
                        "wire_api": "responses",
                        "model": "kimi-k2.7-code",
                        "config": {
                            "enabled": True,
                            "mode": "public_tool_result_summary_v1",
                        },
                        "metrics": {
                            "input_item_count": 2,
                            "compacted_item_count": 0,
                            "unchanged_item_count": 2,
                            "input_bytes_before": 500,
                            "input_bytes_after": 500,
                            "input_bytes_reduced": 0,
                            "metric_map_output_count": 1,
                            "metric_map_bytes_before": 300,
                            "metric_map_bytes_after": 300,
                            "metric_map_bytes_reduced": 0,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = _model_input_filter_metrics(run_dir)

    assert metrics["available"] is True
    assert metrics["source"] == "openai_agents_model_input_filter_events"
    assert metrics["event_count"] == 2
    assert metrics["enabled"] is True
    assert metrics["modes"] == ["public_tool_result_summary_v1"]
    assert metrics["attempted_provider_profiles"] == ["kimi-openai-chat"]
    assert metrics["attempted_wire_apis"] == ["responses"]
    assert metrics["compacted_item_count"] == 2
    assert metrics["unchanged_item_count"] == 3
    assert metrics["repeated_item_count"] == 1
    assert metrics["input_bytes_before"] == 2500
    assert metrics["input_bytes_after"] == 1300
    assert metrics["input_bytes_reduced"] == 1200
    assert metrics["input_byte_reduction_ratio"] == 0.48
    assert metrics["metric_map_output_count"] == 3
    assert metrics["repeated_metric_map_output_count"] == 1
    assert metrics["metric_map_delta_compacted_count"] == 1
    assert metrics["metric_map_bytes_before"] == 1700
    assert metrics["metric_map_bytes_after"] == 800
    assert metrics["metric_map_bytes_reduced"] == 900
    assert metrics["metric_map_byte_reduction_ratio"] == 0.529412
    assert metrics["raw_fpv_image_memory_enabled"] is True
    assert metrics["raw_fpv_image_memory_modes"] == ["retain_latest_full_frame"]
    assert metrics["raw_fpv_image_item_count"] == 2
    assert metrics["raw_fpv_image_retained_count"] == 1
    assert metrics["raw_fpv_image_evicted_count"] == 1
    assert metrics["raw_fpv_image_bytes_before"] == 1000
    assert metrics["raw_fpv_image_bytes_after"] == 350
    assert metrics["raw_fpv_image_bytes_reduced"] == 650
    assert metrics["raw_fpv_image_byte_reduction_ratio"] == 0.65
    assert "Raw prompts" in metrics["privacy_note"]
    assert "tool payload bodies" in metrics["privacy_note"]
