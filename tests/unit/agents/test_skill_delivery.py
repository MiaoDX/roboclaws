from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.drivers.openai_agents_retry_model import _instruction_delivery_fields
from roboclaws.agents.drivers.openai_agents_run_config import (
    _instructions_with_skill_context,
    _write_skill_context_summary,
)
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest
from roboclaws.agents.skill_delivery import (
    SKILL_DELIVERY_CELLS,
    build_skill_delivery,
    sandbox_readiness,
    validate_skill_delivery_cell,
)

SKILL = """# Household World
shared

## Intent Routing
route

## Shared Loop
loop

## Cleanup Preset
cleanup

## Map-Build Preset
map

## Helpers
private helper
"""


def _request(tmp_path: Path, delivery: object) -> LiveAgentRequest:
    return LiveAgentRequest(
        run_id="run",
        skill_name="household-world",
        kickoff_prompt="kickoff",
        mcp_server=LiveAgentMCPServer(name="cleanup", url="http://localhost"),
        run_dir=tmp_path,
        metadata={
            "skill_context": {
                "content": getattr(delivery, "content"),
                "delivery": delivery,
                "skill_name": "household-world",
            },
            "model_visible_tool_surface": ["metric_map", "done"],
        },
    )


def test_delivery_cells_are_closed() -> None:
    assert SKILL_DELIVERY_CELLS == (
        "no-skill",
        "static-full",
        "dynamic-full",
        "dynamic-routed",
        "sandbox-skills",
    )
    with pytest.raises(ValueError, match="must be one of"):
        validate_skill_delivery_cell("broader-shell")


def test_non_sandbox_delivery_does_not_probe_sandbox_runtime(monkeypatch) -> None:
    probes: list[bool] = []

    def readiness(*, probe_runtime: bool = True) -> dict[str, object]:
        probes.append(probe_runtime)
        return {"network": "disabled", "status": "not_requested"}

    monkeypatch.setattr("roboclaws.agents.skill_delivery.sandbox_readiness", readiness)
    build_skill_delivery(
        "static-full",
        full_content=SKILL,
        intent="cleanup",
        evidence_lane="world-public-labels",
    )

    assert probes == [False]


def test_dynamic_full_is_byte_identical_to_static_full(tmp_path: Path) -> None:
    static = build_skill_delivery(
        "static-full", full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
    )
    dynamic = build_skill_delivery(
        "dynamic-full", full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
    )
    static_instructions, _ = _instructions_with_skill_context(_request(tmp_path, static))
    dynamic_callback, _ = _instructions_with_skill_context(_request(tmp_path, dynamic))
    assert callable(dynamic_callback)
    assert dynamic_callback(None, None) == static_instructions
    assert dynamic.artifact()["events"][0]["effective_instruction_sha256"]


def test_no_skill_contains_no_body_or_index() -> None:
    delivery = build_skill_delivery(
        "no-skill", full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
    )
    assert delivery.content == ""
    assert delivery.index_content == ""
    artifact = delivery.artifact()
    assert artifact["included_bytes"] == 0
    assert artifact["estimated_tokens"] == 0


def test_routed_content_contains_only_frozen_selected_sections() -> None:
    routed = build_skill_delivery(
        "dynamic-routed",
        full_content=SKILL,
        intent="cleanup",
        evidence_lane="camera-grounded-labels",
    )
    assert "# Household World" in routed.content
    assert "## Intent Routing" in routed.content
    assert "## Shared Loop" in routed.content
    assert "## Cleanup Preset" in routed.content
    assert "camera-grounded-labels" in routed.content
    assert "Map-Build Preset" not in routed.content
    assert "private helper" not in routed.content


def test_delivery_artifact_records_identity_events_tools_and_sandbox(tmp_path: Path) -> None:
    delivery = build_skill_delivery(
        "dynamic-full", full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
    )
    request = _request(tmp_path, delivery)
    callback, summary = _instructions_with_skill_context(request)
    callback(None, None)
    path = tmp_path / "openai-agents-skill-context.json"
    _write_skill_context_summary(path, summary, request=request)
    payload = json.loads(path.read_text())
    assert payload["requested_cell"] == "dynamic-full"
    assert payload["content_sha256"]
    assert payload["index_sha256"]
    assert payload["included_bytes"] == len(SKILL.encode())
    assert payload["events"][0]["call_index"] == 0
    assert payload["model_visible_tool_surface"] == ["metric_map", "done"]
    assert payload["sdk_version"]
    assert payload["sandbox_posture"]["network"] == "disabled"


def test_installed_sdk_sandbox_uses_official_imports_and_fails_closed() -> None:
    posture = sandbox_readiness()
    assert posture["imports"] == {
        "agents.sandbox.SandboxAgent": True,
        "agents.sandbox.capabilities.Skills": True,
    }
    assert posture["sdk_version"] == "0.19.2"
    assert posture["status"] in {"ready", "blocked"}
    assert posture["reason"] in {
        "supported_exact_contract",
        "sdk_missing_docker_extra",
        "docker_daemon_unavailable",
        "sandbox_image_unavailable",
    }
    assert posture["shell"] == "disabled"
    assert posture["default_capabilities"] == "disabled"
    assert posture["mounts"] == []
    if posture["status"] == "ready":
        assert posture["workspace_entries"] == [".agents/household-world"]
    assert {"repository", "run_outputs", "credentials"} <= set(posture["forbidden_access"])


def test_sandbox_delivery_keeps_body_out_of_agent_instructions() -> None:
    delivery = build_skill_delivery(
        "sandbox-skills",
        full_content=SKILL,
        intent="cleanup",
        evidence_lane="world-public-labels",
    )
    assert delivery.content == SKILL
    assert delivery.instructions("kickoff") == "kickoff"
    artifact = delivery.artifact(tool_surface=["metric_map", "done"])
    assert artifact["delivery"] == "sandbox_skills"
    assert artifact["included_bytes"] == len(SKILL.encode())
    assert artifact["model_visible_tool_surface"] == [
        "metric_map",
        "done",
        "read_selected_skill",
    ]
    assert artifact["events"] == [
        {
            "event": "sandbox_skill_bundle_configured",
            "skill": "household-world",
            "content_sha256": artifact["content_sha256"],
        }
    ]


def test_model_call_delivery_fields_capture_effective_instructions_and_tools() -> None:
    fields = _instruction_delivery_fields(
        "effective instructions",
        [{"type": "function", "function": {"name": "metric_map"}}],
    )
    assert fields["effective_instruction_sha256"]
    assert fields["effective_instruction_bytes"] == len(b"effective instructions")
    assert fields["model_visible_tool_surface"] == ["metric_map"]
