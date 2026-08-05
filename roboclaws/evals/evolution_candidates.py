"""Trusted candidate materialization for Eval Evolution."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from roboclaws.evals.evolution_contracts import Campaign, validate_candidate_authority
from roboclaws.evals.evolution_mcp_description import (
    MCPDescriptionSnapshot,
    validate_description_candidate,
)
from roboclaws.household.realworld_contract_payloads import contract_profile


class CandidateValidationError(ValueError):
    """A proposed candidate failed deterministic host validation."""


def materialize_skill_candidate(
    campaign: Campaign,
    *,
    patch: str,
    output_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    if campaign.target["kind"] != "skill":
        raise ValueError("materialize_skill_candidate requires target.kind=skill")
    return _materialize_patch_candidate(
        campaign,
        patch=patch,
        output_root=output_root,
        repo_root=repo_root,
    )


def materialize_mcp_behavior_candidate(
    campaign: Campaign,
    *,
    patch: str,
    output_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    if campaign.target["kind"] != "mcp-behavior":
        raise ValueError("MCP behavior materialization requires target.kind=mcp-behavior")
    return _materialize_patch_candidate(
        campaign,
        patch=patch,
        output_root=output_root,
        repo_root=repo_root,
    )


def _materialize_patch_candidate(
    campaign: Campaign,
    *,
    patch: str,
    output_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    patch_bytes = patch.encode("utf-8")
    limits = campaign.candidate_limits
    max_bytes = limits.get("max_patch_bytes")
    if not isinstance(max_bytes, int) or len(patch_bytes) > max_bytes:
        raise ValueError("candidate patch exceeds max_patch_bytes")
    if b"\x00" in patch_bytes:
        raise ValueError("candidate patch must not contain binary data")
    _verify_baseline_target(campaign, repo_root=Path(repo_root))
    patch_digest = sha256(patch_bytes).hexdigest()
    workspace = (
        Path(output_root).resolve()
        / campaign.campaign_id
        / "candidates"
        / "by-sha256"
        / patch_digest
    )
    if workspace.exists():
        return _load_existing_candidate(workspace, patch_digest=patch_digest)
    workspace.mkdir(parents=True)
    _extract_baseline_snapshot(
        repo_root=Path(repo_root),
        commit=str(campaign.target["baseline_commit"]),
        workspace=workspace,
    )
    try:
        changed_paths = _patch_changed_paths(patch_bytes, workspace=workspace)
        validate_candidate_authority(
            workspace,
            changed_paths,
            tuple(str(path) for path in campaign.target["mutable_paths"]),
        )
        max_paths = limits.get("max_changed_paths")
        if not isinstance(max_paths, int) or len(changed_paths) > max_paths:
            raise ValueError("candidate paths exceed max_changed_paths")
        _apply_patch(patch_bytes, workspace=workspace)
    except (ValueError, subprocess.CalledProcessError) as exc:
        detail = _validation_error_detail(exc)
        raise CandidateValidationError(detail) from exc
    materialized_digest = _tree_digest(workspace)
    record = {
        "schema": "eval_evolution_materialized_candidate_v1",
        "campaign_id": campaign.campaign_id,
        "target_kind": campaign.target["kind"],
        "parent_commit": campaign.target["baseline_commit"],
        "parent_target_sha256": campaign.target["target_sha256"],
        "patch": patch,
        "patch_sha256": patch_digest,
        "mutable_paths": list(changed_paths),
        "workspace": str(workspace),
        "materialized_sha256": materialized_digest,
        "identity_frozen": True,
        "terminal_status": "gated",
    }
    _write_json(workspace / "candidate.json", record)
    return record


def materialize_mcp_description_candidate(
    campaign: Campaign,
    *,
    candidate: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Freeze a validated public MCP description candidate without code execution."""
    if campaign.target["kind"] != "mcp-description":
        raise ValueError("MCP description materialization requires target.kind=mcp-description")
    profile_id = str(candidate.get("profile_id") or campaign.target["id"])
    baseline = MCPDescriptionSnapshot.from_profile(contract_profile(profile_id))
    if baseline.sha256 != campaign.target["target_sha256"]:
        raise ValueError("campaign target digest does not match current MCP profile")
    validation = validate_description_candidate(baseline, candidate)
    root = Path(output_root) / campaign.campaign_id / "candidates" / "by-sha256"
    workspace = root / validation["candidate_sha256"]
    workspace.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "eval_evolution_materialized_candidate_v1",
        "campaign_id": campaign.campaign_id,
        "target_kind": "mcp-description",
        "parent_target_sha256": baseline.sha256,
        "patch": json.dumps(candidate, sort_keys=True, separators=(",", ":")),
        "patch_sha256": sha256(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "materialized_sha256": validation["candidate_sha256"],
        "mutable_paths": list(campaign.target["mutable_paths"]),
        "changed_tools": validation["changed_tools"],
        "identity_frozen": True,
        "terminal_status": "gated",
    }
    record_path = workspace / "candidate.json"
    if record_path.exists() and json.loads(record_path.read_text(encoding="utf-8")) != record:
        raise ValueError("existing MCP description candidate identity changed")
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**record, "workspace": str(workspace), "validation": validation}


def _extract_baseline_snapshot(*, repo_root: Path, commit: str, workspace: Path) -> None:
    result = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"baseline archive contains unsafe path: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise ValueError(
                    f"baseline archive contains unsupported link or type: {member.name}"
                )
        archive.extractall(workspace, filter="data")


def _verify_baseline_target(campaign: Campaign, *, repo_root: Path) -> None:
    mutable_paths = tuple(str(path) for path in campaign.target["mutable_paths"])
    if len(mutable_paths) != 1:
        raise ValueError("patch candidate baseline requires exactly one mutable path")
    result = subprocess.run(
        ["git", "show", f"{campaign.target['baseline_commit']}:{mutable_paths[0]}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    if sha256(result.stdout).hexdigest() != campaign.target["target_sha256"]:
        raise ValueError("campaign target digest does not match baseline commit")


def _patch_changed_paths(patch: bytes, *, workspace: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "apply", "--no-index", "--numstat", "-z", "--whitespace=error-all"],
        cwd=workspace,
        env=_isolated_git_env(workspace),
        input=patch,
        check=True,
        capture_output=True,
    )
    fields = result.stdout.split(b"\x00")
    paths: list[str] = []
    for field in fields:
        if not field:
            continue
        columns = field.decode("utf-8").split("\t", 2)
        if len(columns) != 3:
            raise ValueError("candidate patch produced malformed numstat output")
        added, removed, path = columns
        if added == "-" or removed == "-":
            raise ValueError("candidate patch must not contain binary changes")
        paths.append(path)
    if not paths:
        raise ValueError("candidate patch must change one authorized file")
    return tuple(paths)


def _apply_patch(patch: bytes, *, workspace: Path) -> None:
    subprocess.run(
        ["git", "apply", "--no-index", "--whitespace=error-all"],
        cwd=workspace,
        env=_isolated_git_env(workspace),
        input=patch,
        check=True,
        capture_output=True,
    )


def _isolated_git_env(workspace: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(workspace.resolve().parent)
    return env


def _validation_error_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        return stderr or "candidate patch failed git validation"
    return str(exc)


def _tree_digest(workspace: Path) -> str:
    digest = sha256()
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if relative == "candidate.json":
            continue
        if path.is_symlink():
            raise ValueError(f"candidate workspace contains symlink: {relative}")
        if path.is_file():
            digest.update(relative.encode("utf-8") + b"\x00")
            digest.update(path.read_bytes())
            digest.update(b"\x00")
    return digest.hexdigest()


def _load_existing_candidate(workspace: Path, *, patch_digest: str) -> dict[str, Any]:
    record_path = workspace / "candidate.json"
    if not record_path.is_file():
        raise ValueError(f"candidate workspace already exists without frozen identity: {workspace}")
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("patch_sha256") != patch_digest:
        raise ValueError("existing candidate identity does not match requested patch")
    if payload.get("materialized_sha256") != _tree_digest(workspace):
        raise ValueError("existing candidate workspace changed after identity freeze")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
