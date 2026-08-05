"""Thin blocked-by-default command dispatcher for Eval Evolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.evals.candidate_isolation_probe import load_isolation_attestation
from roboclaws.evals.evolution_contracts import (
    Campaign,
    load_campaign,
    load_promotion_manifest,
    load_selection_report,
)


def run_evolution_command(mode: str, overrides: dict[str, str]) -> dict[str, Any]:
    values = dict(overrides)
    live_execution = values.pop("live_execution", "blocked")
    if live_execution not in {"blocked", "run"}:
        raise ValueError("live_execution must be blocked or run")
    if mode == "evolve":
        return _run_evolve(values, live_execution=live_execution)
    if mode == "evolve-promote":
        report_ref = values.pop("report", "")
        manifest_ref = values.pop("manifest", "")
        _reject_overrides(values, mode)
        if not report_ref or not manifest_ref:
            raise ValueError("evolve-promote requires report=<path> and manifest=<path>")
        report = load_selection_report(Path(report_ref))
        manifest = load_promotion_manifest(Path(manifest_ref))
        manifest.validate_for_report(report)
        if live_execution == "run":
            from roboclaws.evals.evolution_promotion import apply_evolution_promotion

            return apply_evolution_promotion(
                report_path=Path(report_ref),
                manifest_path=Path(manifest_ref),
                repo_root=Path.cwd(),
            )
        return {
            "schema": "eval_evolution_promotion_preflight_v1",
            "mode": mode,
            "campaign_id": report.campaign_id,
            "live_execution": live_execution,
            "status": "blocked",
            "reason": "promotion_requires_explicit_live_execution",
        }
    raise ValueError(f"unsupported evolution mode: {mode}")


def _run_evolve(values: dict[str, str], *, live_execution: str) -> dict[str, Any]:
    campaign_ref = values.pop("campaign", "")
    output_root = Path(values.pop("output_dir", "output/eval-evolution"))
    attestation_ref = values.pop("isolation_attestation", "")
    _reject_overrides(values, "evolve")
    if not campaign_ref:
        raise ValueError("evolve requires campaign=<path>")
    campaign = load_campaign(Path(campaign_ref))
    if campaign.target["kind"] == "mcp-behavior":
        return _run_behavior_preflight(
            campaign,
            live_execution=live_execution,
            attestation_ref=attestation_ref,
        )
    if attestation_ref:
        raise ValueError("isolation_attestation is valid only for mcp-behavior campaigns")
    if campaign.target["kind"] == "mcp-description":
        return {
            "schema": "eval_evolution_preflight_v1",
            "mode": "evolve",
            "campaign_id": campaign.campaign_id,
            "live_execution": live_execution,
            "status": "blocked",
            "reason": "description_campaign_requires_candidate_artifact",
        }
    if live_execution == "run":
        from roboclaws.evals.evolution_campaign import run_skill_campaign

        return run_skill_campaign(
            campaign,
            repo_root=Path.cwd(),
            output_root=output_root,
        )
    return {
        "schema": "eval_evolution_preflight_v1",
        "mode": "evolve",
        "campaign_id": campaign.campaign_id,
        "live_execution": live_execution,
        "status": "blocked",
        "reason": "live_execution_requires_explicit_run",
    }


def _reject_overrides(values: dict[str, str], mode: str) -> None:
    if values:
        raise ValueError(f"unsupported {mode} override(s): {', '.join(sorted(values))}")


def _run_behavior_preflight(
    campaign: Campaign, *, live_execution: str, attestation_ref: str
) -> dict[str, Any]:
    result = {
        "schema": "eval_evolution_preflight_v1",
        "mode": "evolve",
        "campaign_id": campaign.campaign_id,
        "live_execution": live_execution,
        "status": "blocked",
    }
    if live_execution != "run":
        return {**result, "reason": "live_execution_requires_explicit_run"}
    expected = campaign.identity.get("candidate_isolation_attestation_sha256")
    if not attestation_ref or not isinstance(expected, str):
        return {**result, "reason": "blocked_by_candidate_isolation"}
    attestation = load_isolation_attestation(Path(attestation_ref), expected_sha256=expected)
    summary = attestation.summary()
    if summary["placement"] != campaign.identity.get("execution_placement"):
        raise ValueError("candidate isolation attestation placement does not match campaign")
    return {
        **result,
        "reason": "behavior_campaign_requires_candidate_artifact",
        "candidate_isolation": summary,
    }
