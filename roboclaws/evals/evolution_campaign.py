"""Skill campaign orchestration inside the canonical eval control plane."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from roboclaws.agents.evolution_optimizer import OptimizerOutcome, run_optimizer_agent
from roboclaws.evals.evolution_candidates import (
    CandidateValidationError,
    materialize_mcp_description_candidate,
    materialize_skill_candidate,
)
from roboclaws.evals.evolution_contracts import (
    Campaign,
    Candidate,
    Feedback,
    SelectionReport,
    validate_optimizer_visible_payload,
)
from roboclaws.evals.evolution_selection import run_sealed_holdout_once, select_training_winner
from roboclaws.evals.runner import run_eval_suite

OptimizerRunner = Callable[..., OptimizerOutcome]
MatrixRunner = Callable[[Campaign, Path | None, str], list[dict[str, Any]]]


def run_mcp_description_campaign(
    campaign: Campaign,
    *,
    candidate: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Run the no-behavior deterministic gate for an MCP description candidate."""
    if campaign.target["kind"] != "mcp-description":
        raise ValueError("description campaign requires target.kind=mcp-description")
    record = materialize_mcp_description_candidate(
        campaign, candidate=candidate, output_root=output_root
    )
    return {
        "schema": "eval_evolution_mcp_description_campaign_v1",
        "campaign_id": campaign.campaign_id,
        "status": "gated",
        "live_execution": "blocked",
        "reason": "description_only_deterministic_gate",
        "candidate": record,
    }


def run_skill_campaign(
    campaign: Campaign,
    *,
    repo_root: Path,
    output_root: Path,
    optimizer_runner: OptimizerRunner = run_optimizer_agent,
    matrix_runner: MatrixRunner | None = None,
) -> dict[str, Any]:
    if campaign.target["kind"] != "skill":
        raise ValueError("Phase 1 campaign runner supports target.kind=skill only")
    campaign_root = Path(output_root) / campaign.campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    _freeze_campaign(campaign_root, campaign)
    target_path = Path(repo_root) / str(campaign.target["mutable_paths"][0])
    target_content = target_path.read_text(encoding="utf-8")
    if sha256(target_content.encode("utf-8")).hexdigest() != campaign.target["target_sha256"]:
        raise ValueError("current target does not match frozen campaign digest")
    feedback = _initial_feedback(campaign)
    optimizer = optimizer_runner(
        campaign,
        target={
            "kind": "skill",
            "id": campaign.target["id"],
            "sha256": campaign.target["target_sha256"],
            "relative_path": campaign.target["mutable_paths"][0],
            "content": target_content,
        },
        feedback=feedback,
        run_dir=campaign_root / "optimizer",
    )
    _write_optimizer_proposal(campaign_root, campaign, optimizer)
    try:
        materialized = materialize_skill_candidate(
            campaign,
            patch=optimizer.patch,
            output_root=output_root,
            repo_root=repo_root,
        )
    except CandidateValidationError as exc:
        return _write_rejected_submission(campaign_root, campaign, optimizer, reason=str(exc))
    workspace = Path(materialized["workspace"])
    deterministic_gates = _skill_deterministic_gates(campaign, workspace=workspace)
    if not all(deterministic_gates.values()):
        return _write_terminal_campaign(
            campaign_root,
            campaign,
            status="rejected",
            optimizer=optimizer,
            materialized=materialized,
            deterministic_gates=deterministic_gates,
            training=None,
            sealed_confirmation=None,
        )
    run_matrix = matrix_runner or _run_training_matrix
    baseline_trials = run_matrix(campaign, None, "training-baseline")
    candidate_trials = run_matrix(campaign, workspace, "training-candidate")
    training = select_training_winner(
        campaign,
        baseline_trials=baseline_trials,
        candidate_trials={materialized["patch_sha256"]: candidate_trials},
    )
    sealed_confirmation = None
    if training["holdout_allowed"]:
        sealed_confirmation = run_sealed_holdout_once(
            campaign,
            training_selection=training,
            runner=lambda candidate_id, sealed_ref: _run_holdout_pair(
                campaign,
                candidate_id=candidate_id,
                sealed_ref=sealed_ref,
                workspace=workspace,
                matrix_runner=run_matrix,
            ),
        )
    status = (
        "accepted"
        if sealed_confirmation and sealed_confirmation["status"] == "accepted"
        else "no_improving_candidate"
        if training["status"] == "no_improving_candidate"
        else "rejected"
    )
    return _write_terminal_campaign(
        campaign_root,
        campaign,
        status=status,
        optimizer=optimizer,
        materialized=materialized,
        deterministic_gates=deterministic_gates,
        training=training,
        sealed_confirmation=sealed_confirmation,
    )


def _initial_feedback(campaign: Campaign) -> Feedback:
    return Feedback.from_mapping(
        {
            "schema": "eval_evolution_feedback_v1",
            "campaign_id": campaign.campaign_id,
            "target": {
                "kind": campaign.target["kind"],
                "id": campaign.target["id"],
                "sha256": campaign.target["target_sha256"],
            },
            "public_context": {"phase": "initial_candidate"},
            "failure": {"class": "not_applicable", "explanation": "Initial proposal turn."},
            "quality": {"status": "not_evaluated"},
            "work": {},
            "prior_candidate": None,
            "remaining_budget": {
                "optimizer_turns": campaign.budgets["optimizer_turns"],
                "candidates": campaign.budgets["candidates"],
                "tokens": campaign.budgets["tokens"],
                "cost_usd": campaign.budgets["cost_usd"],
                "wall_time_s": campaign.budgets["wall_time_s"],
            },
        }
    )


def _freeze_campaign(root: Path, campaign: Campaign) -> None:
    payload = {"schema": "eval_evolution_campaign_v1", **asdict(campaign)}
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path = root / "campaign.json"
    if path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise ValueError("campaign policy changed after freeze")
    path.write_text(encoded, encoding="utf-8")


def _write_optimizer_proposal(root: Path, campaign: Campaign, optimizer: OptimizerOutcome) -> None:
    payload = {
        "schema": "eval_evolution_optimizer_proposal_v1",
        "campaign_id": campaign.campaign_id,
        "hypothesis": optimizer.hypothesis,
        "patch": optimizer.patch,
        "patch_sha256": sha256(optimizer.patch.encode("utf-8")).hexdigest(),
        "identity": optimizer.identity,
        "usage": optimizer.usage,
        "trace_id": optimizer.trace_id,
    }
    validate_optimizer_visible_payload(payload)
    (root / "optimizer-proposal.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _skill_deterministic_gates(campaign: Campaign, *, workspace: Path) -> dict[str, bool]:
    target = workspace / str(campaign.target["mutable_paths"][0])
    content = target.read_text(encoding="utf-8")
    return {
        "candidate_identity_frozen": (workspace / "candidate.json").is_file(),
        "skill_non_empty": bool(content.strip()),
        "skill_utf8": "\ufffd" not in content,
        "skill_within_campaign_limit": len(content.encode("utf-8"))
        <= int(campaign.candidate_limits["max_patch_bytes"]) * 8,
    }


def _run_training_matrix(
    campaign: Campaign, workspace: Path | None, lane: str
) -> list[dict[str, Any]]:
    suites = campaign.training.get("suites")
    if (
        not isinstance(suites, list)
        or not suites
        or not all(isinstance(item, str) for item in suites)
    ):
        raise ValueError("training.suites must be a non-empty string list")
    trials: list[dict[str, Any]] = []
    for suite_ref in suites:
        run = run_eval_suite(
            suite_ref,
            output_root=Path("output/eval-evolution") / campaign.campaign_id / "evals" / lane,
            budget=str(campaign.training.get("budget") or "focused"),
            agent_engine="openai-agents-sdk",
            provider_profile=str(campaign.robot["provider_profile"]),
            model=str(campaign.robot["model"]),
            live_execution="run",
            skill_delivery_cell="static-full",
            skill_source_root=workspace,
            live_timeout_s=float(campaign.budgets["timeout_s"]),
            live_retry_limit=int(campaign.budgets["retries"]),
        )
        trials.extend(_selection_trials(run.bundle["results"], skill_delivery_cell="static-full"))
    return trials


def _selection_trials(
    results: list[dict[str, Any]], *, skill_delivery_cell: str
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for result in results:
        identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
        grader_outputs = (
            result.get("grader_outputs") if isinstance(result.get("grader_outputs"), dict) else {}
        )
        projected.append(
            {
                "pair_id": "|".join(
                    str(identity.get(key) or "")
                    for key in ("suite_id", "sample_id", "seed", "repetition_index")
                ),
                "status": result.get("status"),
                "skill_delivery_cell": skill_delivery_cell,
                "quality_gates": {
                    name: _grader_passed(output) for name, output in grader_outputs.items()
                },
                "metrics": dict(result.get("metrics") or {}),
            }
        )
    return projected


def _grader_passed(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    if isinstance(output.get("passed"), bool):
        return bool(output["passed"])
    return output.get("status") in {"passed", "success"}


def _run_holdout_pair(
    campaign: Campaign,
    *,
    candidate_id: str,
    sealed_ref: str,
    workspace: Path,
    matrix_runner: MatrixRunner,
) -> dict[str, Any]:
    holdout_campaign = Campaign(
        **{
            **asdict(campaign),
            "training": {**campaign.training, "suites": [sealed_ref]},
        }
    )
    baseline = matrix_runner(holdout_campaign, None, "holdout-baseline")
    candidate = matrix_runner(holdout_campaign, workspace, f"holdout-{candidate_id}")
    selection = select_training_winner(
        holdout_campaign,
        baseline_trials=baseline,
        candidate_trials={candidate_id: candidate},
    )
    winner = selection.get("winner")
    return {
        "status": "passed" if isinstance(winner, dict) else "failed",
        "quality_gates": {"authoritative": isinstance(winner, dict)},
        "minimum_improvement": {
            "passed": isinstance(winner, dict),
            "value": float(winner.get("improvement", 0)) if isinstance(winner, dict) else 0,
        },
    }


def _write_terminal_campaign(
    root: Path,
    campaign: Campaign,
    *,
    status: str,
    optimizer: OptimizerOutcome,
    materialized: dict[str, Any],
    deterministic_gates: dict[str, bool],
    training: dict[str, Any] | None,
    sealed_confirmation: dict[str, Any] | None,
) -> dict[str, Any]:
    report = {
        "schema": "eval_evolution_selection_report_v1",
        "campaign_id": campaign.campaign_id,
        "baseline_identity": {
            "commit": campaign.target["baseline_commit"],
            "target_sha256": campaign.target["target_sha256"],
        },
        "candidate_id": materialized["patch_sha256"],
        "training": training or {"status": "not_run"},
        "holdout": sealed_confirmation or {"status": "not_run"},
        "quality_gates": deterministic_gates,
        "minimum_improvement": {
            "threshold": campaign.selection.get("minimum_improvement"),
            "passed": status == "accepted",
        },
        "status": status,
        "digests": {
            "patch_sha256": materialized["patch_sha256"],
            "materialized_sha256": materialized["materialized_sha256"],
        },
        "optimizer": {
            "identity": optimizer.identity,
            "usage": optimizer.usage,
            "trace_id": optimizer.trace_id,
        },
        "robot": {
            "role": "robot",
            "agent_engine": "openai-agents-sdk",
            "provider_profile": campaign.robot["provider_profile"],
            "model": campaign.robot["model"],
            "agents_sdk_version": campaign.identity.get("agents_sdk_version", "unavailable"),
        },
        "limitations": list(campaign.training.get("limitations") or []),
    }
    candidate = {
        "schema": "eval_evolution_candidate_v1",
        "candidate_id": materialized["patch_sha256"],
        "campaign_id": campaign.campaign_id,
        "target_kind": campaign.target["kind"],
        "parent_commit": materialized["parent_commit"],
        "parent_target_sha256": materialized["parent_target_sha256"],
        "hypothesis": optimizer.hypothesis,
        "patch": materialized["patch"],
        "patch_sha256": materialized["patch_sha256"],
        "mutable_paths": materialized["mutable_paths"],
        "materialized_sha256": materialized["materialized_sha256"],
        "optimizer_identity": optimizer.identity,
        "optimizer_usage": optimizer.usage,
        "gates": deterministic_gates,
        "eval_identities": _eval_identities(training),
        "terminal_status": _candidate_terminal_status(status),
    }
    candidate_model = Candidate.from_mapping(candidate)
    candidate_model.validate_for_campaign(campaign)
    validate_optimizer_visible_payload(candidate)
    candidate_path = root / "candidate-summary.json"
    candidate_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report["digests"]["candidate_summary_sha256"] = sha256(candidate_path.read_bytes()).hexdigest()
    SelectionReport.from_mapping(report)
    path = root / "selection-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**report, "report_path": str(path)}


def _write_rejected_submission(
    root: Path, campaign: Campaign, optimizer: OptimizerOutcome, *, reason: str
) -> dict[str, Any]:
    patch_sha256 = sha256(optimizer.patch.encode("utf-8")).hexdigest()
    report = {
        "schema": "eval_evolution_selection_report_v1",
        "campaign_id": campaign.campaign_id,
        "baseline_identity": {
            "commit": campaign.target["baseline_commit"],
            "target_sha256": campaign.target["target_sha256"],
        },
        "candidate_id": patch_sha256,
        "training": {"status": "not_run"},
        "holdout": {"status": "not_run"},
        "quality_gates": {"candidate_materialization": False, "reason": reason},
        "minimum_improvement": {
            "threshold": campaign.selection.get("minimum_improvement"),
            "passed": False,
        },
        "status": "rejected",
        "digests": {"patch_sha256": patch_sha256},
        "optimizer": {
            "identity": optimizer.identity,
            "usage": optimizer.usage,
            "trace_id": optimizer.trace_id,
        },
        "robot": {
            "role": "robot",
            "agent_engine": "openai-agents-sdk",
            "provider_profile": campaign.robot["provider_profile"],
            "model": campaign.robot["model"],
            "agents_sdk_version": campaign.identity.get("agents_sdk_version", "unavailable"),
        },
        "limitations": [
            *list(campaign.training.get("limitations") or []),
            "candidate rejected before robot live execution",
        ],
    }
    SelectionReport.from_mapping(report)
    path = root / "selection-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**report, "report_path": str(path)}


def _eval_identities(training: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(training, dict):
        return []
    eligible = training.get("eligible")
    if not isinstance(eligible, list):
        return []
    return [
        {"candidate_id": item.get("candidate_id"), "improvement": item.get("improvement")}
        for item in eligible
        if isinstance(item, dict)
    ]


def _candidate_terminal_status(status: str) -> str:
    if status == "accepted":
        return "accepted"
    if status == "no_improving_candidate":
        return "rejected"
    return status if status in {"rejected", "blocked", "inconclusive"} else "evaluated"
