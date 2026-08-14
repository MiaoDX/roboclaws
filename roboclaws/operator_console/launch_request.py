"""Typed operator-console launch request contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.routes import selection_task_selector


@dataclass(frozen=True)
class LaunchRequest:
    world_id: str = ""
    backend_id: str = ""
    intent_id: str = ""
    agent_engine_id: str = ""
    provider_profile: str = ""
    evidence_lane: str = ""
    scenario_setup: str = ""
    prompt: str = ""
    overrides: dict[str, str] | None = None
    env_overrides: dict[str, str] | None = None
    gates: dict[str, bool] | None = None
    operator_session_id: str = ""
    parent_run_id: str = ""
    next_goal_packet: dict[str, Any] | None = None
    selection_id_override: str = ""
    workflow_id: str = ""

    @property
    def selection_id(self) -> str:
        if self.world_id and self.backend_id and self.intent_id and self.agent_engine_id:
            lane = self.evidence_lane or "world-public-labels"
            return "::".join(
                (
                    self.world_id,
                    self.backend_id,
                    selection_task_selector(self.intent_id),
                    self.agent_engine_id,
                    lane,
                )
            )
        if not self.selection_id_override:
            raise ConsoleLaunchError(
                "launch requires world/backend/intent/agent_engine/evidence_lane or selection_id"
            )
        return self.selection_id_override
