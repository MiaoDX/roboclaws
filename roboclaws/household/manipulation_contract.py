from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

API_SEMANTIC_PROVENANCE = "api_semantic"
BLOCKED_CAPABILITY_PROVENANCE = "blocked_capability"
ISAAC_SEMANTIC_POSE_PROVENANCE = "isaac_semantic_pose"
PLANNER_BACKED_PROVENANCE = "planner_backed"

MANIPULATION_PROVENANCE_SCHEMA = "molmo_manipulation_provenance_v1"
MANIPULATION_PROBE_CONTRACT = "planner_backed_manipulation_probe_v1"
PLANNER_PRIMITIVE_EXECUTOR_SCHEMA = "planner_cleanup_primitive_executor_v1"
PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA = "planner_probe_cleanup_primitive_binding_v1"
PLANNER_PROOF_ATTACHMENT_SCHEMA = "planner_backed_cleanup_attachment_v1"

PLANNER_CLEANUP_PRIMITIVE_TOOLS = frozenset(
    {
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
)


@dataclass(frozen=True)
class CleanupPrimitiveRequest:
    tool: str
    object_id: str = ""
    target_receptacle_id: str = ""
    source_receptacle_id: str = ""
    phase_label: str = ""
    request: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "object_id": self.object_id,
            "target_receptacle_id": self.target_receptacle_id,
            "source_receptacle_id": self.source_receptacle_id,
            "phase_label": self.phase_label or self.tool,
            "request": dict(self.request),
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class CleanupPrimitiveResult:
    ok: bool
    primitive_provenance: str
    planner_backed: bool
    strict_proof_eligible: bool
    executor: str
    status: str = "ok"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    blockers: tuple[Mapping[str, Any], ...] = ()
    state_mutation: str | None = None
    tool: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "primitive_provenance": self.primitive_provenance,
            "planner_backed": self.planner_backed,
            "strict_proof_eligible": self.strict_proof_eligible,
            "executor": self.executor,
            "evidence": dict(self.evidence),
            "blockers": [dict(item) for item in self.blockers],
        }
        if self.state_mutation is not None:
            payload["state_mutation"] = self.state_mutation
        if self.tool:
            payload["tool"] = self.tool
        return payload


class CleanupPrimitiveBackend(Protocol):
    def __call__(
        self, request: CleanupPrimitiveRequest
    ) -> CleanupPrimitiveResult | Mapping[str, Any]: ...
