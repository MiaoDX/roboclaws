from __future__ import annotations

import json
from dataclasses import replace
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
    runtime_skill_delivery_cell,
    validate_eval_skill_delivery_cell,
    validate_runtime_skill_delivery_cell,
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

## Long-Horizon Eval
long horizon

## Map-Build Preset
map

## Helpers
private helper
"""


def test_runtime_skill_delivery_accepts_only_static_product_path() -> None:
    assert validate_runtime_skill_delivery_cell(None) == "static-full"
    assert validate_runtime_skill_delivery_cell("static-full") == "static-full"
    for retired in ("no-skill", "dynamic-full", "dynamic-routed", "sandbox-skills"):
        with pytest.raises(ValueError, match="runtime skill_delivery_cell"):
            validate_runtime_skill_delivery_cell(retired)


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


def test_no_skill_contains_no_body_or_index() -> None:
    delivery = build_skill_delivery(
        "no-skill", full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
    )
    assert delivery.content == ""
    assert delivery.index_content == ""
    artifact = delivery.artifact()
    assert artifact["included_bytes"] == 0
    assert artifact["estimated_tokens"] == 0
    assert delivery.instructions() is None


def test_unconfigured_skill_context_keeps_kickoff_out_of_instructions(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        build_skill_delivery(
            "no-skill",
            full_content=SKILL,
            intent="cleanup",
            evidence_lane="world-public-labels",
        ),
    )
    request = replace(request, metadata={})

    instructions, summary = _instructions_with_skill_context(request)

    assert instructions is None
    assert summary["reason"] == "not_configured"


def test_skill_delivery_rejects_unknown_task_kind() -> None:
    with pytest.raises(ValueError, match="task_kind"):
        build_skill_delivery(
            "static-full",
            full_content=SKILL,
            intent="open-ended",
            evidence_lane="world-public-labels",
            task_kind="cleanup",
        )


def test_delivery_artifact_records_identity_and_tools(tmp_path: Path) -> None:
    delivery = build_skill_delivery(
        "static-full", full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
    )
    request = _request(tmp_path, delivery)
    instructions, summary = _instructions_with_skill_context(request)
    assert instructions and SKILL.strip() in instructions
    path = tmp_path / "openai-agents-skill-context.json"
    _write_skill_context_summary(path, summary, request=request)
    payload = json.loads(path.read_text())
    assert payload["requested_cell"] == "static-full"
    assert payload["content_sha256"]
    assert payload["index_sha256"]
    assert payload["included_bytes"] == len(SKILL.encode())
    assert not payload.get("events")
    assert payload["model_visible_tool_surface"] == ["metric_map", "done"]
    assert payload["sdk_version"]


def test_model_call_delivery_fields_capture_effective_instructions_and_tools() -> None:
    fields = _instruction_delivery_fields(
        "effective instructions",
        [{"type": "function", "function": {"name": "metric_map"}}],
    )
    assert fields["effective_instruction_sha256"]
    assert fields["effective_instruction_bytes"] == len(b"effective instructions")
    assert fields["model_visible_tool_surface"] == ["metric_map"]


@pytest.mark.parametrize("cell", ["dynamic-full", "dynamic-routed", "sandbox-skills"])
def test_retired_identity_is_readable_but_not_executable(cell):
    assert validate_skill_delivery_cell(cell) == cell
    with pytest.raises(ValueError, match="retired skill_delivery_cell"):
        validate_eval_skill_delivery_cell(cell)
    with pytest.raises(ValueError, match="retired skill_delivery_cell"):
        build_skill_delivery(
            cell, full_content=SKILL, intent="cleanup", evidence_lane="world-public-labels"
        )


def test_no_skill_requires_explicit_eval_control_environment():
    env = {"ROBOCLAWS_EVAL_SKILL_DELIVERY_CELL": "no-skill"}
    with pytest.raises(ValueError, match="runtime skill_delivery_cell"):
        runtime_skill_delivery_cell(env)
    env["ROBOCLAWS_EVAL_SKILL_CONTROL"] = "1"
    assert runtime_skill_delivery_cell(env) == "no-skill"
