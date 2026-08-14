"""Configuration and skill-context loading for household SDK runs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.agents.experiment_telemetry import PromptIdentity
from roboclaws.agents.skill_delivery import build_skill_delivery, validate_skill_delivery_cell

MAX_AGENT_SDK_SKILL_CONTEXT_BYTES = 24_000
EVAL_SKILL_SOURCE_ROOT_ENV = "ROBOCLAWS_EVAL_SKILL_SOURCE_ROOT"


def build_household_prompt_identity(
    *,
    repo_root: Path,
    prompt: str,
    prompt_source: str,
    intent: str,
    skill_context: dict[str, Any],
) -> PromptIdentity:
    if prompt_source in {"profile-rendered-lane-default", "provided-lane-default"}:
        template_name = {
            "cleanup": "household-cleanup-kickoff",
            "map-build": "household-map-build-kickoff",
            "open-ended": "household-open-ended-kickoff",
        }.get(intent)
        if template_name is None:
            raise ValueError(f"unsupported household prompt identity intent: {intent}")
        variable_schema = f"{template_name}-variables/v1"
    else:
        template_name = "household-provided-kickoff"
        variable_schema = "household-provided-kickoff-variables/v1"
    skill_sha256 = str(skill_context.get("sha256") or hashlib.sha256(b"").hexdigest())
    return PromptIdentity(
        template_name=template_name,
        template_version="v1",
        variable_schema=variable_schema,
        source_git_sha=_source_git_sha(repo_root),
        skill_sha256=skill_sha256,
        rendered_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


def _source_git_sha(repo_root: Path) -> str:
    checkout_root = Path(__file__).resolve().parents[2]
    for root in dict.fromkeys((repo_root, checkout_root)):
        if sha := _read_git_head(root):
            return sha
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().lower()


def _read_git_head(repo_root: Path) -> str:
    git_dir = _resolve_git_dir(repo_root)
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not head.startswith("ref: "):
        return head.lower()

    ref = head.removeprefix("ref: ").strip()
    roots = [git_dir]
    try:
        common_path = (git_dir / "commondir").read_text(encoding="utf-8").strip()
        common_dir = (git_dir / common_path).resolve()
    except OSError:
        common_dir = git_dir
    if common_dir != git_dir:
        roots.append(common_dir)

    for root in roots:
        if sha := _read_text(root / ref):
            return sha.lower()
    for root in roots:
        if sha := _read_packed_ref(root / "packed-refs", ref):
            return sha
    return ""


def _resolve_git_dir(repo_root: Path) -> Path:
    dot_git = repo_root / ".git"
    if not dot_git.is_file():
        return dot_git
    value = _read_text(dot_git)
    if not value.startswith("gitdir: "):
        return dot_git
    return (repo_root / value.removeprefix("gitdir: ").strip()).resolve()


def _read_packed_ref(path: Path, ref: str) -> str:
    for row in _read_text(path).splitlines():
        if row.startswith(("#", "^")):
            continue
        sha, separator, packed_ref = row.partition(" ")
        if separator and packed_ref == ref:
            return sha.lower()
    return ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _estimated_tokens_from_chars(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / 4))


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if (value := raw.strip().lower()) in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        return value in {"1", "true", "yes", "on"}
    raise ValueError(f"{name} must be true or false, got {raw!r}")


def _load_agent_sdk_skill_context(
    repo_root: Path,
    *,
    skill_name: str,
    delivery_cell: str = "static-full",
    intent: str = "cleanup",
    evidence_lane: str = "world-public-labels",
) -> dict[str, Any]:
    delivery_cell = validate_skill_delivery_cell(delivery_cell)
    relative_path = Path("skills") / skill_name / "SKILL.md"
    source_path = Path(repo_root) / relative_path
    base_payload: dict[str, Any] = {
        "schema": "agent_sdk_skill_context_v1",
        "skill_name": skill_name,
        "source_path": str(source_path),
        "relative_path": str(relative_path),
        "policy": "canonical_skill_markdown",
    }
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        return {
            **base_payload,
            "included": False,
            "reason": "source_unavailable",
            "error_type": exc.__class__.__name__,
        }
    truncated = raw[:MAX_AGENT_SDK_SKILL_CONTEXT_BYTES]
    text = truncated.decode("utf-8", errors="replace")
    delivery = build_skill_delivery(
        delivery_cell,
        full_content=text,
        intent=intent,
        evidence_lane=evidence_lane,
    )
    return {
        **base_payload,
        "included": bool(text),
        "reason": "included" if text else "empty",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "included_bytes": len(truncated),
        "truncated": len(raw) > len(truncated),
        "estimated_tokens": _estimated_tokens_from_chars(len(text)),
        "content": delivery.content,
        "delivery_content_sha256": hashlib.sha256(delivery.content.encode("utf-8")).hexdigest(),
        "delivery": delivery,
        "delivery_cell": delivery_cell,
    }


def eval_skill_source_root(default_repo_root: Path) -> Path:
    raw = os.environ.get(EVAL_SKILL_SOURCE_ROOT_ENV)
    if not raw:
        return Path(default_repo_root)
    root = Path(raw).resolve()
    record_path = root / "candidate.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("eval Skill source root requires a readable candidate.json") from exc
    if not isinstance(record, dict) or record.get("identity_frozen") is not True:
        raise ValueError("eval Skill source root requires frozen candidate identity")
    if record.get("target_kind") != "skill" or record.get("workspace") != str(root):
        raise ValueError("eval Skill source root candidate identity mismatch")
    return root


def _skill_context_timing_summary(skill_context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in skill_context.items()
        if key
        in {
            "schema",
            "skill_name",
            "source_path",
            "relative_path",
            "policy",
            "included",
            "reason",
            "sha256",
            "bytes",
            "included_bytes",
            "truncated",
            "estimated_tokens",
            "error_type",
            "delivery_cell",
            "delivery_content_sha256",
        }
    }


def _stable_prefix_packet(
    prompt: str,
    skill_context: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    skill_hash = str(skill_context.get("sha256") or "")
    prompt_prefix = str(prompt or "")[:2048]
    material = "\n".join(
        [
            str(skill_context.get("relative_path") or ""),
            skill_hash,
            str(profile.get("provider_profile") or ""),
            str(profile.get("wire_api") or ""),
            prompt_prefix,
        ]
    )
    return {
        "schema": "agent_sdk_stable_prefix_v1",
        "hash": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "material": "skill-path+skill-hash+provider-profile+wire-api+prompt-prefix",
        "skill_context_sha256": skill_hash,
        "prompt_prefix_chars": len(prompt_prefix),
        "prompt_cache_retention": (profile.get("sdk_model_settings") or {}).get(
            "prompt_cache_retention"
        )
        or "",
    }
