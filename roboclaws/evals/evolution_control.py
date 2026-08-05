"""Thin blocked-by-default command dispatcher for Eval Evolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.evals.evolution_contracts import (
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
        campaign_ref = values.pop("campaign", "")
        _reject_overrides(values, mode)
        if not campaign_ref:
            raise ValueError("evolve requires campaign=<path>")
        campaign = load_campaign(Path(campaign_ref))
        return {
            "schema": "eval_evolution_preflight_v1",
            "mode": mode,
            "campaign_id": campaign.campaign_id,
            "live_execution": live_execution,
            "status": "blocked",
            "reason": "phase_0_contract_only",
        }
    if mode == "evolve-promote":
        report_ref = values.pop("report", "")
        manifest_ref = values.pop("manifest", "")
        _reject_overrides(values, mode)
        if not report_ref or not manifest_ref:
            raise ValueError("evolve-promote requires report=<path> and manifest=<path>")
        report = load_selection_report(Path(report_ref))
        manifest = load_promotion_manifest(Path(manifest_ref))
        manifest.validate_for_report(report)
        return {
            "schema": "eval_evolution_promotion_preflight_v1",
            "mode": mode,
            "campaign_id": report.campaign_id,
            "live_execution": live_execution,
            "status": "blocked",
            "reason": "promotion_not_implemented_until_phase_1",
        }
    raise ValueError(f"unsupported evolution mode: {mode}")


def _reject_overrides(values: dict[str, str], mode: str) -> None:
    if values:
        raise ValueError(f"unsupported {mode} override(s): {', '.join(sorted(values))}")
