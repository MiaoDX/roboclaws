"""Static-only validation for isolated MCP behavior evolution candidates."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from roboclaws.evals.evolution_candidates import materialize_mcp_behavior_candidate
from roboclaws.evals.evolution_contracts import Campaign

PROPOSAL_SCHEMA = "eval_evolution_mcp_behavior_proposal_v1"
_FORBIDDEN_CALLS = frozenset({"__import__", "compile", "eval", "exec", "open"})
_FORBIDDEN_LITERAL_PARTS = (
    "../",
    "/proc",
    "/home/",
    "/root/",
    "api_key",
    "credential",
    "holdout",
    "private_truth",
)


@dataclass(frozen=True)
class BehaviorProposal:
    campaign_id: str
    parent_sha256: str
    hypothesis: str
    patch: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "BehaviorProposal":
        required = {"schema", "campaign_id", "parent_sha256", "hypothesis", "patch"}
        if set(payload) != required:
            raise ValueError("MCP behavior proposal fields must be exact")
        if payload.get("schema") != PROPOSAL_SCHEMA:
            raise ValueError(f"MCP behavior proposal schema must be {PROPOSAL_SCHEMA}")
        values = [
            payload.get(name) for name in ("campaign_id", "parent_sha256", "hypothesis", "patch")
        ]
        if not all(isinstance(value, str) and value for value in values):
            raise ValueError("MCP behavior proposal strings must be non-empty")
        parent_sha256 = str(payload["parent_sha256"])
        if len(parent_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in parent_sha256
        ):
            raise ValueError("MCP behavior proposal parent_sha256 must be a digest")
        return cls(
            campaign_id=str(payload["campaign_id"]),
            parent_sha256=parent_sha256,
            hypothesis=str(payload["hypothesis"]),
            patch=str(payload["patch"]),
        )

    def validate_for_campaign(self, campaign: Campaign) -> None:
        if campaign.target["kind"] != "mcp-behavior":
            raise ValueError("MCP behavior proposal requires target.kind=mcp-behavior")
        if self.campaign_id != campaign.campaign_id:
            raise ValueError("MCP behavior proposal campaign identity mismatch")
        if self.parent_sha256 != campaign.target["target_sha256"]:
            raise ValueError("MCP behavior proposal has stale parent identity")


def run_mcp_behavior_deterministic_gate(
    campaign: Campaign,
    *,
    proposal: BehaviorProposal,
    output_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    proposal.validate_for_campaign(campaign)
    record = materialize_mcp_behavior_candidate(
        campaign,
        patch=proposal.patch,
        output_root=output_root,
        repo_root=repo_root,
    )
    mutable_path = str(campaign.target["mutable_paths"][0])
    baseline_source = _baseline_source(campaign, repo_root=repo_root, path=mutable_path)
    candidate_source = Path(record["workspace"], mutable_path).read_text(encoding="utf-8")
    validation = validate_behavior_source_delta(baseline_source, candidate_source)
    return {
        "schema": "eval_evolution_mcp_behavior_deterministic_gate_v1",
        "campaign_id": campaign.campaign_id,
        "status": "gated",
        "live_execution": "blocked",
        "reason": "behavior_candidate_requires_isolated_live_eval",
        "proposal_sha256": sha256(
            json.dumps(
                {
                    "campaign_id": proposal.campaign_id,
                    "parent_sha256": proposal.parent_sha256,
                    "hypothesis": proposal.hypothesis,
                    "patch": proposal.patch,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "candidate": record,
        "validation": validation,
    }


def validate_behavior_source_delta(baseline_source: str, candidate_source: str) -> dict[str, Any]:
    baseline = ast.parse(baseline_source)
    candidate = ast.parse(candidate_source)
    if ast.dump(baseline, include_attributes=False) == ast.dump(
        candidate, include_attributes=False
    ):
        raise ValueError("MCP behavior candidate must change executable source")
    if _imports(baseline) != _imports(candidate):
        raise ValueError("MCP behavior candidate must preserve imports exactly")
    if _definitions(baseline) != _definitions(candidate):
        raise ValueError("MCP behavior candidate must preserve function and class definitions")
    forbidden_calls = sorted(
        name
        for name in _called_names(candidate)
        if name in _FORBIDDEN_CALLS and name not in _called_names(baseline)
    )
    if forbidden_calls:
        raise ValueError(f"MCP behavior candidate added forbidden calls: {forbidden_calls}")
    forbidden_literals = sorted(
        value
        for value in _string_literals(candidate) - _string_literals(baseline)
        if any(part in value.lower() for part in _FORBIDDEN_LITERAL_PARTS)
    )
    if forbidden_literals:
        raise ValueError("MCP behavior candidate added forbidden private/path literals")
    return {
        "schema": "eval_evolution_mcp_behavior_static_validation_v1",
        "imports_preserved": True,
        "definitions_preserved": True,
        "forbidden_calls_added": [],
        "forbidden_literals_added": [],
        "candidate_ast_sha256": sha256(
            ast.dump(candidate, include_attributes=False).encode("utf-8")
        ).hexdigest(),
    }


def _imports(tree: ast.AST) -> tuple[str, ...]:
    return tuple(
        ast.dump(node, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )


def _definitions(tree: ast.AST) -> tuple[tuple[str, str], ...]:
    return tuple(
        (type(node).__name__, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef))
    )


def _called_names(tree: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _baseline_source(campaign: Campaign, *, repo_root: Path, path: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "show", f"{campaign.target['baseline_commit']}:{path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
