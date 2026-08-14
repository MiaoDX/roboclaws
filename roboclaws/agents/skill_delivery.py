"""Closed eval-only Skill delivery contract for OpenAI Agents SDK runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
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


def _docker_sandbox_runtime(image: str) -> tuple[bool, bool, bool]:
    try:
        import docker  # type: ignore[import-not-found]
    except ImportError:
        return False, False, False

    client = None
    try:
        client = docker.from_env()
        if not client.ping():
            return True, False, False
        try:
            client.images.get(image)
        except docker.errors.ImageNotFound:
            return True, True, False
        return True, True, True
    except Exception:
        return True, False, False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def sandbox_readiness(*, probe_runtime: bool = True) -> dict[str, Any]:
    version = sdk_version()
    if not probe_runtime:
        return {
            "schema": "agent_sdk_sandbox_posture_v1",
            "status": "not_requested",
            "reason": "delivery_cell_not_sandbox",
            "sdk_version": version,
            "imports": {},
            "backend": "docker_network_disabled_adapter",
            "image": "",
            "docker_dependency": False,
            "docker_daemon": False,
            "image_available": False,
            "network": "disabled",
            "capabilities": [],
            "shell": "disabled",
            "default_capabilities": "disabled",
            "mounts": [],
            "workspace_entries": [],
            "forbidden_access": [
                "credentials",
                "host_files",
                "private_evaluation",
                "repository",
                "run_outputs",
            ],
        }
    imports: dict[str, bool] = {}
    try:
        from agents.sandbox import SandboxAgent  # type: ignore[import-not-found]
        from agents.sandbox.capabilities import Skills  # type: ignore[import-not-found]
    except ImportError:
        SandboxAgent = None
        Skills = None
    imports["agents.sandbox.SandboxAgent"] = SandboxAgent is not None
    imports["agents.sandbox.capabilities.Skills"] = Skills is not None

    image = os.environ.get("ROBOCLAWS_SANDBOX_SKILL_IMAGE") or "python:3.12-slim"
    docker_dependency, docker_daemon, image_available = _docker_sandbox_runtime(image)

    supported = all(imports.values()) and docker_dependency and docker_daemon and image_available
    if not all(imports.values()):
        reason = "sdk_missing_sandbox_agent_or_skills"
    elif not docker_dependency:
        reason = "sdk_missing_docker_extra"
    elif not docker_daemon:
        reason = "docker_daemon_unavailable"
    elif not image_available:
        reason = "sandbox_image_unavailable"
    else:
        reason = "supported_exact_contract"
    return {
        "schema": "agent_sdk_sandbox_posture_v1",
        "status": "ready" if supported else "blocked",
        "reason": reason,
        "sdk_version": version,
        "imports": imports,
        "backend": "docker_network_disabled_adapter",
        "image": image,
        "docker_dependency": docker_dependency,
        "docker_daemon": docker_daemon,
        "image_available": image_available,
        "network": "disabled",
        "capabilities": ["skills", "skills.read_selected_bundle"] if supported else [],
        "shell": "disabled",
        "default_capabilities": "disabled",
        "mounts": [],
        "workspace_entries": [".agents/household-world"] if supported else [],
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

    def instructions(self) -> str | Callable[..., str] | None:
        if self.cell in {"no-skill", "sandbox-skills"}:
            return None
        rendered = render_instructions(self.content)
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
        visible_tools = list(tool_surface)
        if self.cell == "sandbox-skills":
            visible_tools.append("read_selected_skill")
        return {
            "schema": "openai_agents_skill_delivery_v1",
            "requested_cell": self.cell,
            "delivery": (
                "sandbox_skills"
                if self.cell == "sandbox-skills"
                else "dynamic_callback"
                if self.dynamic
                else "static_string"
            ),
            "content_sha256": _sha256(self.content),
            "index_sha256": _sha256(self.index_content),
            "included_bytes": rendered_bytes,
            "estimated_tokens": max(1, round(len(self.content) / 4)) if self.content else 0,
            "events": list(self.events),
            "model_visible_tool_surface": list(dict.fromkeys(visible_tools)),
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
    posture = sandbox_readiness(probe_runtime=cell == "sandbox-skills")
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
    events = (
        [
            {
                "event": "sandbox_skill_bundle_configured",
                "skill": "household-world",
                "content_sha256": _sha256(content),
            }
        ]
        if cell == "sandbox-skills"
        else []
    )
    return SkillDelivery(cell, content, index, cell.startswith("dynamic-"), events, posture)


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
