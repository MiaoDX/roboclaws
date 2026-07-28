"""Generic MCP entrypoint/router helpers for selected contract profiles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from roboclaws.mcp.profiles import (
    ContractProfile,
    ToolDescriptor,
    contract_profile,
    contract_profile_names,
)

ToolHandler = Callable[..., Any]


class MCPProfileRouter:
    """Compose and register an immutable ordered contract-profile tool surface."""

    def __init__(
        self,
        profile_ids: str | tuple[str, ...],
        handlers: Mapping[str, ToolHandler],
        *,
        allow_extra_handlers: bool = False,
    ) -> None:
        ids = (profile_ids,) if isinstance(profile_ids, str) else tuple(profile_ids)
        if not ids:
            raise ValueError("at least one MCP contract profile is required")
        normalized = tuple(load_contract_profile(profile_id).profile_id for profile_id in ids)
        duplicates = _duplicates(normalized)
        if duplicates:
            raise ValueError(f"duplicate MCP contract profiles: {', '.join(duplicates)}")
        self.profiles = tuple(load_contract_profile(profile_id) for profile_id in normalized)
        self.public_tools = self._compose_public_tools()
        self.handlers = dict(handlers)
        self.allow_extra_handlers = allow_extra_handlers
        self._validate_handlers()

    def public_tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.public_tools)

    def register_tools(self, mcp: Any) -> tuple[str, ...]:
        registered: list[str] = []
        for tool in self.public_tools:
            handler = self.handlers[tool.name]
            mcp.tool(name=tool.name, description=tool.summary)(handler)
            registered.append(tool.name)
        return tuple(registered)

    def _validate_handlers(self) -> None:
        expected = set(self.public_tool_names())
        provided = set(self.handlers)
        missing = sorted(expected - provided)
        if missing:
            raise ValueError(f"composed profiles missing handlers for: {', '.join(missing)}")
        extras = sorted(provided - expected)
        if extras and not self.allow_extra_handlers:
            raise ValueError(
                f"composed profiles got handlers outside public profile: {', '.join(extras)}"
            )

    def _compose_public_tools(self) -> tuple[ToolDescriptor, ...]:
        tools: list[ToolDescriptor] = []
        by_name: dict[str, ToolDescriptor] = {}
        for profile in self.profiles:
            for tool in profile.public_tools:
                previous = by_name.get(tool.name)
                if previous is not None:
                    kind = "duplicate" if previous == tool else "conflicting"
                    raise ValueError(f"{kind} public tool descriptor {tool.name!r}")
                by_name[tool.name] = tool
                tools.append(tool)
        return tuple(tools)


def load_contract_profile(profile_id: str) -> ContractProfile:
    try:
        return contract_profile(profile_id)
    except ValueError as exc:
        expected = ", ".join(contract_profile_names())
        raise ValueError(
            f"unknown MCP contract profile {profile_id!r}; allowed profiles: {expected}"
        ) from exc


def register_profile_tools(
    mcp: Any,
    *,
    profile_id: str | tuple[str, ...],
    handlers: Mapping[str, ToolHandler],
    allow_extra_handlers: bool = False,
) -> tuple[str, ...]:
    router = MCPProfileRouter(
        profile_id,
        handlers,
        allow_extra_handlers=allow_extra_handlers,
    )
    return router.register_tools(mcp)


def _duplicates(values: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates
