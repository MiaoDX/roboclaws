from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from roboclaws.agents.evolution_optimizer import (
    OPTIMIZER_TOOL_NAMES,
    _sdk_turn_budget,
    build_optimizer_tools,
    optimizer_tool_surface_digest,
)
from roboclaws.evals.evolution_contracts import Feedback


@dataclass
class _Tool:
    name: str
    description: str
    params_json_schema: dict[str, Any]
    on_invoke_tool: Any
    strict_json_schema: bool


def _feedback() -> Feedback:
    return Feedback.from_mapping(
        {
            "schema": "eval_evolution_feedback_v1",
            "campaign_id": "campaign-1",
            "target": {"kind": "skill", "id": "example"},
            "public_context": {},
            "failure": {"class": "partial_progress_only"},
            "quality": {"status": "failed"},
            "work": {},
            "prior_candidate": None,
            "remaining_budget": {"candidates": 1},
        }
    )


def test_optimizer_exposes_exactly_three_narrow_tools() -> None:
    submitted: list[tuple[str, str]] = []
    tools = build_optimizer_tools(
        target={
            "kind": "skill",
            "id": "example",
            "relative_path": "skills/example/SKILL.md",
            "content": "# Example\n",
        },
        feedback=_feedback(),
        submit=lambda hypothesis, patch: submitted.append((hypothesis, patch)),
        function_tool_cls=_Tool,
    )
    assert tuple(tool.name for tool in tools) == OPTIMIZER_TOOL_NAMES
    assert optimizer_tool_surface_digest()
    assert all(tool.strict_json_schema for tool in tools)
    forbidden = {"shell", "filesystem", "git", "network", "eval", "commit", "publish"}
    assert not forbidden.intersection(tool.name for tool in tools)

    response = asyncio.run(
        tools[2].on_invoke_tool(
            None,
            json.dumps(
                {
                    "hypothesis": "Clarify order.",
                    "patch": (
                        "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
                        "--- a/skills/example/SKILL.md\n"
                        "+++ b/skills/example/SKILL.md\n"
                        "@@ -1 +1,2 @@\n"
                        " # Example\n"
                        "+Follow the declared order.\n"
                    ),
                }
            ),
        )
    )
    assert response["accepted_for_host_validation"] is True
    assert submitted == [
        (
            "Clarify order.",
            "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
            "--- a/skills/example/SKILL.md\n"
            "+++ b/skills/example/SKILL.md\n"
            "@@ -1 +1,2 @@\n"
            " # Example\n"
            "+Follow the declared order.\n",
        )
    ]


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        (
            "```diff\ndiff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n```\n",
            "raw unified git diff",
        ),
        (
            "diff --git a/other b/other\n--- a/other\n+++ b/other\n@@ -1 +1 @@\n-old\n+new\n",
            "raw unified git diff",
        ),
        (
            "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
            "--- a/skills/example/SKILL.md\n+++ b/skills/example/SKILL.md\n"
            "@@ -1 +1 @@\n-old\n+new\n"
            "diff --git a/other b/other\n--- a/other\n+++ b/other\n@@ -1 +1 @@\n-old\n+new\n",
            "authorized relative_path",
        ),
        (
            "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
            "--- a/skills/example/SKILL.md\n+++ b/skills/example/SKILL.md\n",
            "hunk",
        ),
        (
            "diff --git a/skills/example/SKILL.md b/skills/example/SKILL.md\n"
            "--- a/skills/example/SKILL.md\n+++ b/skills/example/SKILL.md\n"
            "@@ -1 +1,2 @@\n # Example\n",
            "does not apply",
        ),
    ],
)
def test_optimizer_rejects_malformed_or_unauthorized_patch(patch: str, message: str) -> None:
    tools = build_optimizer_tools(
        target={"kind": "skill", "id": "example", "relative_path": "skills/example/SKILL.md"},
        feedback=_feedback(),
        submit=lambda *_: None,
        function_tool_cls=_Tool,
    )
    response = asyncio.run(
        tools[2].on_invoke_tool(None, json.dumps({"hypothesis": "Change it.", "patch": patch}))
    )
    assert response["accepted_for_host_validation"] is False
    assert message in response["error"]


def test_optimizer_tools_reject_paths_and_extra_arguments() -> None:
    tools = build_optimizer_tools(
        target={"kind": "skill", "id": "example"},
        feedback=_feedback(),
        submit=lambda *_: None,
        function_tool_cls=_Tool,
    )
    with pytest.raises(Exception, match="path"):
        asyncio.run(tools[0].on_invoke_tool(None, '{"path":"/tmp/secret"}'))


def test_optimizer_tools_reject_private_feedback_before_agent_construction() -> None:
    feedback = _feedback()
    feedback.payload["private_truth"] = {"target": "hidden"}
    with pytest.raises(ValueError, match="forbidden key"):
        build_optimizer_tools(
            target={"kind": "skill", "id": "example"},
            feedback=feedback,
            submit=lambda *_: None,
            function_tool_cls=_Tool,
        )


def test_sdk_transport_budget_preserves_campaign_revision_turns() -> None:
    campaign = SimpleNamespace(budgets={"optimizer_turns": 2})
    assert _sdk_turn_budget(campaign) == 12
