"""Closed eval-only Skill delivery contract for OpenAI Agents SDK runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from typing import Any, Callable

SKILL_DELIVERY_ENV = "ROBOCLAWS_EVAL_SKILL_DELIVERY_CELL"
SKILL_DELIVERY_CELLS = (
    "no-skill",
    "static-full",
    "dynamic-full",
    "dynamic-routed",
    "sandbox-skills",
)
DEFAULT_SKILL_DELIVERY_CELL = "static-full"


def validate_skill_delivery_cell(value: str | None) -> str:
    cell = str(value or DEFAULT_SKILL_DELIVERY_CELL).strip()
    if cell not in SKILL_DELIVERY_CELLS:
        raise ValueError("skill_delivery_cell must be one of " + ", ".join(SKILL_DELIVERY_CELLS))
    return cell


def sdk_version() -> str:
    try:
        return importlib.metadata.version("openai-agents")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def sandbox_readiness() -> dict[str, Any]:
    version = sdk_version()
    try:
        import agents  # type: ignore[import-not-found]
    except ImportError:
        agents = None
    exports = {
        name: bool(agents is not None and getattr(agents, name, None) is not None)
        for name in ("SandboxAgent", "Skills")
    }
    supported = all(exports.values())
    return {
        "schema": "agent_sdk_sandbox_posture_v1",
        "status": "ready" if supported else "blocked",
        "reason": "supported_exact_contract"
        if supported
        else "sdk_missing_sandbox_agent_or_skills",
        "sdk_version": version,
        "exports": exports,
        "network": "disabled",
        "capabilities": ["skills.read_selected_bundle"] if supported else [],
        "shell": "disabled",
        "default_capabilities": "disabled",
        "mounts": ["selected_skill_bundle"] if supported else [],
        "forbidden_access": [
            "credentials",
            "host_files",
            "private_evaluation",
            "repository",
            "run_outputs",
        ],
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _routed_content(full_content: str, *, intent: str, evidence_lane: str) -> str:
    sections = _markdown_sections(full_content)
    intent_heading = {
        "cleanup": "Cleanup Preset",
        "map-build": "Map-Build Preset",
        "open-ended": "Open-Ended Goals",
    }.get(intent, "Open-Ended Goals")
    selected = [
        sections[name]
        for name in ("Household World", "Intent Routing", "Shared Loop", intent_heading)
        if name in sections
    ]
    lane_note = (
        "Frozen evidence-lane selection: "
        f"{evidence_lane}. Follow only the guidance for this lane in the selected intent section."
    )
    return "\n\n".join([*selected, lane_note]).rstrip() + "\n"


def _markdown_sections(content: str) -> dict[str, str]:
    lines = content.splitlines(keepends=True)
    sections: dict[str, str] = {}
    heading = ""
    start = 0
    for index, line in enumerate(lines):
        if line.startswith("# ") or line.startswith("## "):
            if heading:
                sections[heading] = "".join(lines[start:index]).rstrip()
            heading = line.lstrip("#").strip()
            start = index
    if heading:
        sections[heading] = "".join(lines[start:]).rstrip()
    return sections


@dataclass
class SkillDelivery:
    cell: str
    content: str
    index_content: str
    dynamic: bool
    events: list[dict[str, Any]]
    sandbox_posture: dict[str, Any]

    def instructions(self, kickoff_prompt: str) -> str | Callable[..., str]:
        rendered = render_instructions(self.content, kickoff_prompt)
        if not self.dynamic:
            return rendered

        def callback(*_args: Any, **_kwargs: Any) -> str:
            self.events.append(
                {
                    "event": "instructions_callback",
                    "call_index": len(self.events),
                    "effective_instruction_sha256": _sha256(rendered),
                }
            )
            return rendered

        return callback

    def artifact(self, *, tool_surface: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
        rendered_bytes = len(self.content.encode("utf-8"))
        return {
            "schema": "openai_agents_skill_delivery_v1",
            "requested_cell": self.cell,
            "delivery": "dynamic_callback" if self.dynamic else "static_string",
            "content_sha256": _sha256(self.content),
            "index_sha256": _sha256(self.index_content),
            "included_bytes": rendered_bytes,
            "estimated_tokens": max(1, round(len(self.content) / 4)) if self.content else 0,
            "events": list(self.events),
            "model_visible_tool_surface": list(tool_surface),
            "sdk_version": sdk_version(),
            "sandbox_posture": self.sandbox_posture,
        }


def build_skill_delivery(
    cell: str,
    *,
    full_content: str,
    intent: str,
    evidence_lane: str,
) -> SkillDelivery:
    cell = validate_skill_delivery_cell(cell)
    posture = sandbox_readiness()
    if cell == "sandbox-skills":
        return SkillDelivery(cell, "", "", False, [], posture)
    if cell == "no-skill":
        return SkillDelivery(cell, "", "", False, [], posture)
    content = (
        _routed_content(full_content, intent=intent, evidence_lane=evidence_lane)
        if cell == "dynamic-routed"
        else full_content
    )
    index = json.dumps(
        {"skill": "household-world", "content_sha256": _sha256(content)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return SkillDelivery(cell, content, index, cell.startswith("dynamic-"), [], posture)


def render_instructions(content: str, kickoff_prompt: str) -> str:
    if not content:
        return kickoff_prompt
    return (
        "Canonical skill context for this private OpenAI Agents SDK run:\n\n"
        f"{content.rstrip()}\n\n"
        "Run-specific context supplies the operator goal, selected lane, budgets, artifacts, "
        "and episode facts. The operator goal and public safety or required-tool responses are "
        "authoritative; otherwise the canonical Skill owns task strategy:\n\n"
        f"{kickoff_prompt}"
    )
