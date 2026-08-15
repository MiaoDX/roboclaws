"""Restricted SandboxAgent support for the eval-only Skills delivery cell."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

SANDBOX_SKILL_IMAGE_ENV = "ROBOCLAWS_SANDBOX_SKILL_IMAGE"
DEFAULT_SANDBOX_SKILL_IMAGE = "python:3.12-slim"
SANDBOX_SKILLS_PATH = ".agents"
READ_SELECTED_SKILL_TOOL = "read_selected_skill"
SANDBOX_SKILL_BASE_INSTRUCTIONS = (
    "You are a household robot agent operating through bounded MCP robot tools. "
    "Before taking robot action, call `read_selected_skill` for the only indexed Skill and "
    "follow its instructions. You have no shell, patch, generic filesystem, network, or host "
    "access. Treat the sandbox workspace as a read-only Skill delivery boundary."
)


def is_sandbox_skills_request(request: Any) -> bool:
    context = request.metadata.get("skill_context") if isinstance(request.metadata, dict) else None
    return bool(isinstance(context, dict) and context.get("delivery_cell") == "sandbox-skills")


def sandbox_skill_image() -> str:
    return os.environ.get(SANDBOX_SKILL_IMAGE_ENV) or DEFAULT_SANDBOX_SKILL_IMAGE


def sandbox_model_visible_tools(tool_surface: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys([*tool_surface, READ_SELECTED_SKILL_TOOL]))


class _ReadSelectedSkillArgs(BaseModel):
    skill_name: str


def _selected_skill_reader_capability(
    *,
    skill_name: str,
    expected_sha256: str,
) -> Any:
    from agents.sandbox.capabilities import Capability
    from agents.tool import FunctionTool

    class SelectedSkillReader(Capability):
        type: Literal["selected_skill_reader"] = "selected_skill_reader"
        selected_skill_name: str
        selected_skill_sha256: str

        async def instructions(self, _manifest: Any) -> str:
            return (
                f"Call `{READ_SELECTED_SKILL_TOOL}` with skill_name="
                f"`{self.selected_skill_name}` before using robot tools. This tool can read only "
                "that Skill's SKILL.md; it accepts no filesystem path."
            )

        def tools(self) -> list[Any]:
            if self.session is None:
                raise ValueError("SelectedSkillReader is not bound to a SandboxSession")

            async def invoke(_context: Any, raw_input: str) -> dict[str, Any]:
                args = _ReadSelectedSkillArgs.model_validate_json(raw_input)
                if args.skill_name != self.selected_skill_name:
                    raise ValueError(
                        f"only selected skill {self.selected_skill_name!r} may be read"
                    )
                path = (
                    Path(self.session.state.manifest.root)
                    / SANDBOX_SKILLS_PATH
                    / self.selected_skill_name
                    / "SKILL.md"
                )
                handle = await self.session.read(path, user=self.run_as)
                try:
                    raw = handle.read()
                finally:
                    handle.close()
                content = raw if isinstance(raw, str) else bytes(raw).decode("utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if digest != self.selected_skill_sha256:
                    raise ValueError("selected Skill digest changed after materialization")
                return {
                    "skill_name": self.selected_skill_name,
                    "sha256": digest,
                    "bytes": len(content.encode("utf-8")),
                    "content": content,
                }

            return [
                FunctionTool(
                    name=READ_SELECTED_SKILL_TOOL,
                    description=(
                        "Read the complete SKILL.md for the one selected Skill bundle. "
                        "No caller-provided path or other Skill is accepted."
                    ),
                    params_json_schema=_ReadSelectedSkillArgs.model_json_schema(),
                    on_invoke_tool=invoke,
                    strict_json_schema=False,
                )
            ]

    return SelectedSkillReader(
        selected_skill_name=skill_name,
        selected_skill_sha256=expected_sha256,
    )


def _skill_description(content: str, skill_name: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.startswith("description:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    return f"Canonical strategy for the {skill_name} household robot surface."


def sandbox_agent_kwargs(request: Any) -> dict[str, Any]:
    from agents.sandbox import Manifest
    from agents.sandbox.capabilities import Skill, Skills

    context = request.metadata.get("skill_context") if isinstance(request.metadata, dict) else None
    if not isinstance(context, dict):
        raise ValueError("sandbox-skills requires skill_context metadata")
    delivery = context.get("delivery")
    content = str(getattr(delivery, "content", "") or "")
    skill_name = str(context.get("skill_name") or request.skill_name)
    if not content:
        raise ValueError("sandbox-skills requires a non-empty selected Skill body")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    expected = str(context.get("delivery_content_sha256") or context.get("sha256") or "")
    if expected and digest != expected:
        raise ValueError("selected Skill body does not match source digest")

    return {
        "base_instructions": SANDBOX_SKILL_BASE_INSTRUCTIONS,
        "default_manifest": Manifest(),
        "capabilities": [
            Skills(
                skills=[
                    Skill(
                        name=skill_name,
                        description=_skill_description(content, skill_name),
                        content=content,
                    )
                ],
                skills_path=SANDBOX_SKILLS_PATH,
            ),
            _selected_skill_reader_capability(
                skill_name=skill_name,
                expected_sha256=digest,
            ),
        ],
    }


class _NetworkDisabledContainers:
    def __init__(self, containers: Any) -> None:
        self._containers = containers

    def create(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("mounts"):
            raise RuntimeError("sandbox-skills forbids Docker mounts")
        kwargs["network_disabled"] = True
        kwargs["network_mode"] = "none"
        return self._containers.create(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._containers, name)


class _NetworkDisabledDockerClient:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.containers = _NetworkDisabledContainers(client.containers)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def sandbox_run_config() -> Any:
    from agents.sandbox import SandboxRunConfig
    from agents.sandbox.sandboxes.docker import (
        DockerSandboxClient,
        DockerSandboxClientOptions,
    )

    import docker

    docker_client = _NetworkDisabledDockerClient(docker.from_env())
    return SandboxRunConfig(
        client=DockerSandboxClient(docker_client),
        options=DockerSandboxClientOptions(image=sandbox_skill_image()),
    )


@dataclass(frozen=True)
class SandboxIsolationProbe:
    payload: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.payload.get("ok"))


async def run_sandbox_isolation_probe(*, skill_name: str, content: str) -> SandboxIsolationProbe:
    from agents.sandbox import Manifest
    from agents.sandbox.capabilities import Skill, Skills
    from agents.sandbox.sandboxes.docker import DockerSandboxClientOptions

    import docker

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    skills = Skills(
        skills=[
            Skill(
                name=skill_name,
                description=_skill_description(content, skill_name),
                content=content,
            )
        ],
        skills_path=SANDBOX_SKILLS_PATH,
    )
    reader = _selected_skill_reader_capability(
        skill_name=skill_name,
        expected_sha256=digest,
    )
    capabilities = [skills, reader]
    manifest = Manifest()
    for capability in capabilities:
        manifest = capability.process_manifest(manifest)

    run_config = sandbox_run_config()
    client = run_config.client
    options = run_config.options
    if client is None or not isinstance(options, DockerSandboxClientOptions):
        raise RuntimeError("sandbox probe requires Docker client and options")
    session = await client.create(manifest=manifest, options=options)
    try:
        async with session:
            for capability in capabilities:
                capability.bind(session)
            tools = [tool for capability in capabilities for tool in capability.tools()]
            reader_tool = next(tool for tool in tools if tool.name == READ_SELECTED_SKILL_TOOL)
            selected = await reader_tool.on_invoke_tool(
                None,
                json.dumps({"skill_name": skill_name}),
            )
            wrong_skill_denied = False
            try:
                await reader_tool.on_invoke_tool(
                    None,
                    json.dumps({"skill_name": "../not-selected"}),
                )
            except ValueError:
                wrong_skill_denied = True

            network_check = await session.exec(
                "python3 -c \"import socket; socket.create_connection(('1.1.1.1',53),2)\"",
                shell=True,
            )
            raw_container = docker.from_env().containers.get(session.state.container_id)
            raw_container.reload()
            attrs = raw_container.attrs
            config = attrs.get("Config", {})
            host_config = attrs.get("HostConfig", {})
            network_settings = attrs.get("NetworkSettings", {})
            environment_keys = sorted(
                entry.split("=", 1)[0] for entry in (config.get("Env") or []) if "=" in entry
            )
            sensitive_environment_keys = [
                key
                for key in environment_keys
                if any(token in key.upper() for token in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
            ]
            tool_names = [tool.name for tool in tools]
            checks = {
                "network_disabled": bool(config.get("NetworkDisabled"))
                or host_config.get("NetworkMode") == "none",
                "network_connect_denied": network_check.exit_code != 0,
                "no_mounts": not attrs.get("Mounts"),
                "no_sensitive_environment": not sensitive_environment_keys,
                "no_path_grants": not manifest.extra_path_grants,
                "only_selected_skill_materialized": sorted(
                    path.as_posix() for path in manifest.validated_entries()
                )
                == [f"{SANDBOX_SKILLS_PATH}/{skill_name}"],
                "restricted_tool_surface": tool_names == [READ_SELECTED_SKILL_TOOL],
                "selected_skill_digest_matches": selected.get("sha256") == digest,
                "wrong_skill_denied": wrong_skill_denied,
            }
            image = raw_container.image
            payload = {
                "schema": "sandbox_skill_isolation_probe_v1",
                "ok": all(checks.values()),
                "backend": "docker_network_disabled_adapter",
                "image": sandbox_skill_image(),
                "image_id": image.id,
                "skill_name": skill_name,
                "skill_sha256": digest,
                "skill_bytes": len(content.encode("utf-8")),
                "capabilities": [capability.type for capability in capabilities],
                "model_visible_tools": tool_names,
                "shell_capability": False,
                "default_capabilities": False,
                "manifest_entries": sorted(
                    path.as_posix() for path in manifest.validated_entries()
                ),
                "environment_keys": environment_keys,
                "sensitive_environment_keys": sensitive_environment_keys,
                "network_mode": host_config.get("NetworkMode"),
                "network_attachments": sorted((network_settings.get("Networks") or {}).keys()),
                "mounts": attrs.get("Mounts") or [],
                "checks": checks,
            }
            return SandboxIsolationProbe(payload=payload)
    finally:
        await client.delete(session)


def write_probe_payload(path: Path, probe: SandboxIsolationProbe) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(probe.payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
