"""Surface spec declarations used by the launch catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPresetSpec:
    """Optional compressed task configuration layered over one surface."""

    preset_id: str
    intent_id: str
    skill_name: str
    required_capabilities: tuple[str, ...]
    default_scenario_setup: str


@dataclass(frozen=True)
class TaskSurfaceSpec:
    """Declarative execution-surface metadata.

    Specs describe runnable environments and capability surfaces. They do not
    import runner implementations, backend adapters, or MCP server code.
    """

    surface_id: str
    domain: str
    supported_dispatch_runners: tuple[str, ...]
    supported_intents: tuple[str, ...]
    default_intent: str
    supported_reports: tuple[str, ...]
    default_report: str | None
    default_profile: str | None
    supported_profiles: tuple[str, ...]
    default_backend: str
    required_capabilities: tuple[str, ...]
    supported_presets: tuple[str, ...] = ()
    default_preset: str | None = None
