"""Explicit human-only application of an accepted Eval Evolution patch."""

from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from roboclaws.evals.evolution_contracts import (
    load_promotion_manifest,
    load_selection_report,
)


def apply_evolution_promotion(
    *,
    report_path: Path,
    manifest_path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    report = load_selection_report(Path(report_path))
    manifest = load_promotion_manifest(Path(manifest_path))
    manifest.validate_for_report(report)
    bindings = manifest.payload["bindings"]
    if not isinstance(bindings, dict):
        raise ValueError("promotion bindings must be an object")
    _verify_binding(bindings, "selection_report_sha256", _file_digest(Path(report_path)))
    _verify_binding(bindings, "patch_sha256", str(report.payload["digests"]["patch_sha256"]))
    _verify_binding(
        bindings,
        "materialized_sha256",
        str(report.payload["digests"]["materialized_sha256"]),
    )
    baseline = report.payload["baseline_identity"]
    head = _git_text(Path(repo_root), "rev-parse", "HEAD")
    if head != baseline.get("commit"):
        raise ValueError("promotion baseline commit is stale")
    target_path = _single_mutable_path(bindings)
    target = Path(repo_root) / target_path
    if _file_digest(target) != baseline.get("target_sha256"):
        raise ValueError("promotion target digest changed after evaluation")
    _require_clean_target(Path(repo_root), target_path)
    candidate_root = (
        Path(report_path).parent
        / "candidates"
        / "by-sha256"
        / str(report.payload["digests"]["patch_sha256"])
    )
    record = _load_candidate_record(candidate_root / "candidate.json")
    if record.get("materialized_sha256") != report.payload["digests"]["materialized_sha256"]:
        raise ValueError("promotion materialized candidate digest mismatch")
    patch = str(record.get("patch") or "")
    if sha256(patch.encode("utf-8")).hexdigest() != report.payload["digests"]["patch_sha256"]:
        raise ValueError("promotion patch digest mismatch")
    subprocess.run(
        ["git", "apply", "--check", "--whitespace=error-all"],
        cwd=repo_root,
        input=patch.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "apply", "--whitespace=error-all"],
        cwd=repo_root,
        input=patch.encode("utf-8"),
        check=True,
        capture_output=True,
    )
    return {
        "schema": "eval_evolution_promotion_result_v1",
        "campaign_id": report.campaign_id,
        "candidate_id": report.payload["candidate_id"],
        "status": "applied",
        "mutable_paths": [target_path],
        "committed": False,
        "defaults_changed": False,
        "baseline_published": False,
    }


def _verify_binding(bindings: dict[str, Any], key: str, expected: str) -> None:
    if bindings.get(key) != expected:
        raise ValueError(f"promotion binding mismatch: {key}")


def _single_mutable_path(bindings: dict[str, Any]) -> str:
    paths = bindings.get("mutable_paths")
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise ValueError("promotion requires exactly one bound mutable path")
    return paths[0]


def _require_clean_target(repo_root: Path, target_path: str) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--", target_path],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("promotion target file is dirty or mixed")


def _git_text(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_candidate_record(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("promotion candidate record is missing or invalid") from exc
    if not isinstance(payload, dict) or payload.get("identity_frozen") is not True:
        raise ValueError("promotion candidate record is not frozen")
    return payload
