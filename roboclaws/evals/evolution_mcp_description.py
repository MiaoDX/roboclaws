"""Deterministic validator for MCP description-only evolution candidates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from roboclaws.household.realworld_contract_payloads import ContractProfile, contract_profile

MCP_DESCRIPTION_TARGET_SCHEMA = "eval_evolution_mcp_description_target_v1"
_PRIVATE_TERMS = ("private", "secret", "grader", "fixture", "hidden", "holdout")


@dataclass(frozen=True)
class MCPDescriptionSnapshot:
    profile_id: str
    profile_version: int
    tools: dict[str, dict[str, Any]]
    sha256: str

    @classmethod
    def from_profile(cls, profile: ContractProfile) -> MCPDescriptionSnapshot:
        tools = {
            tool.name: {
                "semantic_name": tool.semantic_name,
                "family": tool.family,
                "classification": tool.classification,
                "provenance": list(tool.provenance),
                "summary": tool.summary,
            }
            for tool in profile.public_tools
        }
        payload = _canonical_payload(profile.profile_id, profile.version, tools)
        return cls(profile.profile_id, profile.version, tools, _digest(payload))

    def to_target(self) -> dict[str, Any]:
        return {
            "schema": MCP_DESCRIPTION_TARGET_SCHEMA,
            "kind": "mcp-description",
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "target_sha256": self.sha256,
            "tools": self.tools,
        }


def snapshot_public_mcp_profile(profile_id: str) -> MCPDescriptionSnapshot:
    return MCPDescriptionSnapshot.from_profile(contract_profile(profile_id))


def validate_description_candidate(
    baseline: MCPDescriptionSnapshot,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    _validate_candidate_identity(baseline, candidate)
    tools = candidate.get("tools")
    _validate_tool_set(baseline, tools)
    changed = _validate_tool_summaries(baseline.tools, tools)
    if not changed:
        raise ValueError("MCP description candidate must change at least one summary")
    payload = _canonical_payload(baseline.profile_id, baseline.profile_version, tools)
    return {
        "schema": "eval_evolution_mcp_description_candidate_v1",
        "profile_id": baseline.profile_id,
        "parent_sha256": baseline.sha256,
        "candidate_sha256": _digest(payload),
        "changed_tools": changed,
        "token_delta": _token_delta(baseline.tools, tools),
    }


def _validate_candidate_identity(
    baseline: MCPDescriptionSnapshot, candidate: dict[str, Any]
) -> None:
    if candidate.get("schema") != MCP_DESCRIPTION_TARGET_SCHEMA:
        raise ValueError("MCP description candidate schema mismatch")
    if candidate.get("profile_id") != baseline.profile_id:
        raise ValueError("MCP description profile identity mismatch")
    if candidate.get("profile_version") != baseline.profile_version:
        raise ValueError("MCP description profile version mismatch")
    if candidate.get("parent_sha256") != baseline.sha256:
        raise ValueError("MCP description candidate has stale parent identity")


def _validate_tool_set(baseline: MCPDescriptionSnapshot, tools: Any) -> None:
    if not isinstance(tools, dict) or set(tools) != set(baseline.tools):
        raise ValueError("MCP description candidate must preserve the public tool set")


def _validate_tool_summaries(
    baseline: dict[str, dict[str, Any]], tools: dict[str, Any]
) -> list[str]:
    changed: list[str] = []
    for name, before in baseline.items():
        after = tools[name]
        if not isinstance(after, dict):
            raise ValueError(f"MCP description for {name} must be an object")
        _validate_immutable_fields(name, before, after)
        summary = after.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"MCP description for {name} must have non-empty text")
        if summary != before["summary"]:
            if any(term in summary.lower() for term in _PRIVATE_TERMS):
                raise ValueError(
                    f"MCP description for {name} contains forbidden private terminology"
                )
            changed.append(name)
    return changed


def _validate_immutable_fields(name: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    for key in ("semantic_name", "family", "classification", "provenance"):
        if after.get(key) != before[key]:
            raise ValueError(f"MCP description candidate changed immutable field {name}.{key}")


def _canonical_payload(profile_id: str, version: int, tools: dict[str, Any]) -> str:
    return json.dumps(
        {"profile_id": profile_id, "profile_version": version, "tools": tools},
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()


def _token_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    def tokenize(value: str) -> list[str]:
        return re.findall(r"\w+|[^\w\s]", value)

    old = sum(len(tokenize(str(item["summary"]))) for item in before.values())
    new = sum(len(tokenize(str(item["summary"]))) for item in after.values())
    return {"before": old, "after": new, "delta": new - old}
