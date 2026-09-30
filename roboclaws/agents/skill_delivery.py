"""Closed eval-only Skill delivery contract for OpenAI Agents SDK runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from typing import Any

SKILL_DELIVERY_ENV = "ROBOCLAWS_EVAL_SKILL_DELIVERY_CELL"
SKILL_DELIVERY_CELLS = (
    "no-skill",
    "static-full",
    "dynamic-full",
    "dynamic-routed",
    "sandbox-skills",
)
ACTIVE_SKILL_DELIVERY_CELLS = ("static-full",)
DEFAULT_SKILL_DELIVERY_CELL = "static-full"


def validate_skill_delivery_cell(value: str | None) -> str:
    cell = str(value or DEFAULT_SKILL_DELIVERY_CELL).strip()
    if cell not in SKILL_DELIVERY_CELLS:
        raise ValueError("skill_delivery_cell must be one of " + ", ".join(SKILL_DELIVERY_CELLS))
    return cell


def validate_runtime_skill_delivery_cell(value: str | None) -> str:
    """Validate the sole product Skill path; eval controls use the broad parser."""
    cell = validate_skill_delivery_cell(value)
    if cell not in ACTIVE_SKILL_DELIVERY_CELLS:
        raise ValueError(
            "runtime skill_delivery_cell must be one of " + ", ".join(ACTIVE_SKILL_DELIVERY_CELLS)
        )
    return cell


def validate_eval_skill_delivery_cell(value: str | None) -> str:
    """Execution accepts the product path and the explicit eval control only."""
    cell = validate_skill_delivery_cell(value)
    if cell not in {"static-full", "no-skill"}:
        raise ValueError(f"retired skill_delivery_cell {cell!r}; use static-full or no-skill")
    return cell


def runtime_skill_delivery_cell(env: dict[str, str]) -> str:
    validator = (
        validate_eval_skill_delivery_cell
        if env.get("ROBOCLAWS_EVAL_SKILL_CONTROL") == "1"
        else validate_runtime_skill_delivery_cell
    )
    return validator(env.get(SKILL_DELIVERY_ENV))


def sdk_version() -> str:
    try:
        return importlib.metadata.version("openai-agents")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class SkillDelivery:
    cell: str
    content: str
    index_content: str

    def instructions(self) -> str | None:
        return render_instructions(self.content)

    def artifact(self, *, tool_surface: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
        rendered_bytes = len(self.content.encode("utf-8"))
        visible_tools = list(tool_surface)
        return {
            "schema": "openai_agents_skill_delivery_v1",
            "requested_cell": self.cell,
            "delivery": "static_string",
            "content_sha256": _sha256(self.content),
            "index_sha256": _sha256(self.index_content),
            "included_bytes": rendered_bytes,
            "estimated_tokens": max(1, round(len(self.content) / 4)) if self.content else 0,
            "events": [],
            "model_visible_tool_surface": list(dict.fromkeys(visible_tools)),
            "sdk_version": sdk_version(),
        }


def build_skill_delivery(
    cell: str,
    *,
    full_content: str,
    intent: str,
    evidence_lane: str,
    task_kind: str = "",
) -> SkillDelivery:
    if task_kind not in {"", "long-horizon"}:
        raise ValueError("task_kind must be empty or long-horizon")
    cell = validate_eval_skill_delivery_cell(cell)
    if cell == "no-skill":
        return SkillDelivery(cell, "", "")
    content = full_content
    index = json.dumps(
        {"skill": "household-world", "content_sha256": _sha256(content)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return SkillDelivery(cell, content, index)


def render_instructions(content: str) -> str | None:
    if not content:
        return None
    return (
        "Canonical skill context for this private OpenAI Agents SDK run:\n\n"
        f"{content.rstrip()}\n\n"
        "Run-specific user input supplies the operator goal, selected lane, budgets, artifacts, "
        "and episode facts. The operator goal and public safety or required-tool responses are "
        "authoritative; otherwise the canonical Skill owns task strategy."
    )
