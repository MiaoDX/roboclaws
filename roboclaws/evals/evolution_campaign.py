"""Skill campaign orchestration inside the canonical eval control plane."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict
from functools import partial
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from roboclaws.agents.drivers.openai_agents_provider_runtime import failure_from_exception
from roboclaws.agents.evolution_optimizer import OptimizerOutcome, run_optimizer_agent
from roboclaws.evals.evolution_budget import CampaignBudgetExceeded, CampaignBudgetLedger
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
from roboclaws.evals.suite_loading import load_suite

OptimizerRunner = Callable[..., OptimizerOutcome]
MatrixRunner = Callable[[Campaign, Path | None, str], list[dict[str, Any]]]
SuiteRunner = Callable[..., Any]


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
    suite_runner: SuiteRunner | None = None,
) -> dict[str, Any]:
    campaign_started_at = time.monotonic()
    if campaign.target["kind"] != "skill":
        raise ValueError("Phase 1 campaign runner supports target.kind=skill only")
    repo_root = Path(repo_root)
    target_content = _frozen_target_content(campaign, repo_root=repo_root)
    budget_ledger = CampaignBudgetLedger(campaign, campaign_started_at)
    campaign_root = Path(output_root) / campaign.campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True)
    _freeze_campaign(campaign_root, campaign)
    feedback = _initial_feedback(campaign)
    optimizer: OptimizerOutcome | None = None
    try:
        optimizer = _run_budgeted_optimizer(
            campaign,
            target_content=target_content,
            optimizer_runner=optimizer_runner,
            budget_ledger=budget_ledger,
            feedback=feedback,
            campaign_root=campaign_root,
        )
        _write_optimizer_proposal(campaign_root, campaign, optimizer)
        budget_ledger.record_optimizer(optimizer)
    except CampaignBudgetExceeded as exc:
        return _write_pre_candidate_budget_terminal(
            campaign_root,
            campaign,
            exc=exc,
            optimizer=optimizer,
        )
    except Exception as exc:  # noqa: BLE001 - paid campaigns require a terminal packet.
        return _write_pre_candidate_execution_terminal(
            campaign_root,
            campaign,
            exc=exc,
            optimizer=optimizer,
        )
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
    try:
        run_matrix = _campaign_matrix_runner(
            matrix_runner=matrix_runner,
            suite_runner=suite_runner,
            output_root=output_root,
            budget_ledger=budget_ledger,
        )
        baseline_trials = run_matrix(campaign, None, "training-baseline")
        candidate_trials = run_matrix(campaign, workspace, "training-candidate")
    except CampaignBudgetExceeded as exc:
        return _write_terminal_campaign(
            campaign_root,
            campaign,
            status="inconclusive",
            optimizer=optimizer,
            materialized=materialized,
            deterministic_gates=deterministic_gates,
            training=_budget_inconclusive(campaign, exc),
            sealed_confirmation=None,
        )
    except Exception as exc:  # noqa: BLE001 - paid campaigns require a terminal packet.
        failure = failure_from_exception(exc)
        return _write_terminal_campaign(
            campaign_root,
            campaign,
            status="inconclusive",
            optimizer=optimizer,
            materialized=materialized,
            deterministic_gates={**deterministic_gates, "training_execution": False},
            training=_inconclusive_training(
                campaign,
                reason=f"training_{failure.reason}",
            ),
            sealed_confirmation=None,
        )
    training = select_training_winner(
        campaign,
        baseline_trials=baseline_trials,
        candidate_trials={materialized["patch_sha256"]: candidate_trials},
    )
    sealed_confirmation = _run_sealed_confirmation(
        campaign,
        training=training,
        workspace=workspace,
        matrix_runner=run_matrix,
    )
    return _write_terminal_campaign(
        campaign_root,
        campaign,
        status=_campaign_result_status(training, sealed_confirmation),
        optimizer=optimizer,
        materialized=materialized,
        deterministic_gates=deterministic_gates,
        training=training,
        sealed_confirmation=sealed_confirmation,
    )


def _frozen_target_content(campaign: Campaign, *, repo_root: Path) -> str:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    if head != campaign.target["baseline_commit"]:
        raise ValueError("campaign baseline commit is stale")
    target_path = repo_root / str(campaign.target["mutable_paths"][0])
    target_content = target_path.read_text(encoding="utf-8")
    if sha256(target_content.encode("utf-8")).hexdigest() != campaign.target["target_sha256"]:
        raise ValueError("current target does not match frozen campaign digest")
    return target_content


def _run_sealed_confirmation(
    campaign: Campaign,
    *,
    training: dict[str, Any],
    workspace: Path,
    matrix_runner: MatrixRunner,
) -> dict[str, Any] | None:
    if not training["holdout_allowed"]:
        return None
    try:
        return run_sealed_holdout_once(
            campaign,
            training_selection=training,
            runner=lambda candidate_id, sealed_ref: _run_holdout_pair(
                campaign,
                candidate_id=candidate_id,
                sealed_ref=sealed_ref,
                workspace=workspace,
                matrix_runner=matrix_runner,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - paid campaigns require a terminal packet.
        if isinstance(exc, CampaignBudgetExceeded):
            reason = exc.reason
            budget: dict[str, Any] | None = exc.usage
        else:
            reason = f"holdout_{failure_from_exception(exc).reason}"
            budget = None
        result: dict[str, Any] = {
            "schema": "eval_evolution_sealed_holdout_result_v1",
            "campaign_id": campaign.campaign_id,
            "candidate_id": training["winner"]["candidate_id"],
            "status": "inconclusive",
            "reason": reason,
            "terminal": True,
            "optimizer_feedback_allowed": False,
        }
        if budget is not None:
            result["budget"] = budget
        return result


def _run_budgeted_optimizer(
    campaign: Campaign,
    *,
    target_content: str,
    optimizer_runner: OptimizerRunner,
    budget_ledger: CampaignBudgetLedger,
    feedback: Feedback,
    campaign_root: Path,
) -> OptimizerOutcome:
    optimizer_campaign = budget_ledger.campaign_for_optimizer()
    try:
        optimizer = optimizer_runner(
            optimizer_campaign,
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
    except TimeoutError as exc:
        raise CampaignBudgetExceeded(
            "optimizer_timeout_s_exhausted", budget_ledger.packet()
        ) from exc
    return optimizer


def _campaign_matrix_runner(
    *,
    matrix_runner: MatrixRunner | None,
    suite_runner: SuiteRunner | None,
    output_root: Path,
    budget_ledger: CampaignBudgetLedger,
) -> MatrixRunner:
    if matrix_runner is not None:
        return partial(
            _run_budgeted_matrix,
            matrix_runner=matrix_runner,
            budget_ledger=budget_ledger,
        )
    if suite_runner is None:
        raise ValueError("skill campaign requires a suite runner")
    return partial(
        _run_training_matrix,
        suite_runner=suite_runner,
        output_root=output_root,
        budget_ledger=budget_ledger,
    )


def _campaign_result_status(
    training: dict[str, Any], sealed_confirmation: dict[str, Any] | None
) -> str:
    if sealed_confirmation and sealed_confirmation["status"] == "accepted":
        return "accepted"
    if training["status"] == "inconclusive" or (
        sealed_confirmation and sealed_confirmation["status"] == "inconclusive"
    ):
        return "inconclusive"
    if training["status"] == "no_improving_candidate":
        return "no_improving_candidate"
    return "rejected"


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
    campaign: Campaign,
    workspace: Path | None,
    lane: str,
    *,
    suite_runner: SuiteRunner | None,
    output_root: Path = Path("output/eval-evolution"),
    budget_ledger: CampaignBudgetLedger,
) -> list[dict[str, Any]]:
    if suite_runner is None:
        raise ValueError("skill campaign requires a suite runner")
    suites = campaign.training.get("suites")
    if (
        not isinstance(suites, list)
        or not suites
        or not all(isinstance(item, str) for item in suites)
    ):
        raise ValueError("training.suites must be a non-empty string list")
    trials: list[dict[str, Any]] = []
    retry_limit = int(campaign.budgets["retries"])
    for suite_ref in suites:
        trial_count = _suite_trial_count(suite_ref)
        reservation = budget_ledger.reserve_suite(trial_count, retry_limit=retry_limit)
        observed_count = 0

        def observe_result(result: Any) -> None:
            nonlocal observed_count
            payload = result.to_dict() if hasattr(result, "to_dict") else result
            if not isinstance(payload, dict):
                raise TypeError("suite result observer requires an eval-result object")
            budget_ledger.record_reserved_result(payload)
            observed_count += 1

        run_kwargs: dict[str, Any] = {
            "output_root": Path(output_root) / campaign.campaign_id / "evals" / lane,
            "budget": str(campaign.training.get("budget") or "focused"),
            "agent_engine": "openai-agents-sdk",
            "provider_profile": str(campaign.robot["provider_profile"]),
            "model": str(campaign.robot["model"]),
            "live_execution": "run",
            "skill_delivery_cell": "static-full",
            "skill_source_root": workspace,
            "skill_name": _campaign_skill_name(campaign),
            "live_timeout_s": reservation["timeout_s"],
            "live_retry_limit": retry_limit,
            "live_token_budget": reservation["attempt_tokens"],
            "live_cost_budget_usd": reservation["attempt_cost_usd"],
            "result_observer": observe_result,
        }
        run = suite_runner(suite_ref, **run_kwargs)
        results = list(run.bundle["results"])
        budget_ledger.record_reserved_suite(
            results,
            trial_count=trial_count,
            observed_count=observed_count,
        )
        trials.extend(_selection_trials(results, skill_delivery_cell="static-full"))
    return trials


def _run_budgeted_matrix(
    campaign: Campaign,
    workspace: Path | None,
    lane: str,
    *,
    matrix_runner: MatrixRunner,
    budget_ledger: CampaignBudgetLedger,
) -> list[dict[str, Any]]:
    budgeted_campaign = budget_ledger.campaign_for_unbounded_matrix()
    trials = list(matrix_runner(budgeted_campaign, workspace, lane))
    budget_ledger.record_unbounded_matrix(trials)
    return trials


def _suite_trial_count(suite_ref: str) -> int:
    _suite, samples = load_suite(suite_ref)
    return sum(sample.trial_count for sample in samples)


def _campaign_skill_name(campaign: Campaign) -> str:
    path = PurePosixPath(str(campaign.target["mutable_paths"][0]))
    return path.parent.name


def _budget_inconclusive(campaign: Campaign, exc: CampaignBudgetExceeded) -> dict[str, Any]:
    return _inconclusive_training(
        campaign,
        reason=exc.reason,
        budget=exc.usage,
    )


def _inconclusive_training(
    campaign: Campaign,
    *,
    reason: str,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema": "eval_evolution_training_selection_v1",
        "campaign_id": campaign.campaign_id,
        "status": "inconclusive",
        "reason": reason,
        "winner": None,
        "eligible": [],
        "rejected": {},
        "holdout_allowed": False,
    }
    if budget is not None:
        result["budget"] = budget
    return result


def _write_pre_candidate_budget_terminal(
    root: Path,
    campaign: Campaign,
    *,
    exc: CampaignBudgetExceeded,
    optimizer: OptimizerOutcome | None,
) -> dict[str, Any]:
    return _write_pre_candidate_inconclusive_terminal(
        root,
        campaign,
        reason=exc.reason,
        budget=exc.usage,
        optimizer=optimizer,
        quality_gate="campaign_budget",
        limitation="campaign budget exhausted before candidate evaluation",
    )


def _write_pre_candidate_execution_terminal(
    root: Path,
    campaign: Campaign,
    *,
    exc: Exception,
    optimizer: OptimizerOutcome | None,
) -> dict[str, Any]:
    failure = failure_from_exception(exc)
    return _write_pre_candidate_inconclusive_terminal(
        root,
        campaign,
        reason=f"optimizer_{failure.reason}",
        budget=None,
        optimizer=optimizer,
        quality_gate="optimizer_execution",
        limitation=f"optimizer execution failed: {failure.reason}",
    )


def _write_pre_candidate_inconclusive_terminal(
    root: Path,
    campaign: Campaign,
    *,
    reason: str,
    budget: dict[str, Any] | None,
    optimizer: OptimizerOutcome | None,
    quality_gate: str,
    limitation: str,
) -> dict[str, Any]:
    patch_sha256 = (
        sha256(optimizer.patch.encode("utf-8")).hexdigest()
        if optimizer is not None
        else "not_applicable"
    )
    optimizer_identity = (
        optimizer.identity
        if optimizer is not None
        else {
            "role": "optimizer",
            "agent_engine": campaign.optimizer["agent_engine"],
            "provider_profile": campaign.optimizer["provider_profile"],
            "model": campaign.optimizer["model"],
        }
    )
    report = {
        "schema": "eval_evolution_selection_report_v1",
        "campaign_id": campaign.campaign_id,
        "baseline_identity": {
            "commit": campaign.target["baseline_commit"],
            "target_sha256": campaign.target["target_sha256"],
        },
        "candidate_id": patch_sha256,
        "training": _inconclusive_training(
            campaign,
            reason=reason,
            budget=budget,
        ),
        "holdout": {"status": "not_run"},
        "quality_gates": {quality_gate: False},
        "minimum_improvement": {
            "threshold": campaign.selection.get("minimum_improvement"),
            "passed": False,
        },
        "status": "inconclusive",
        "digests": ({"patch_sha256": patch_sha256} if optimizer is not None else {}),
        "optimizer": {
            "identity": optimizer_identity,
            "usage": optimizer.usage if optimizer is not None else {"usage_available": False},
            "trace_id": optimizer.trace_id if optimizer is not None else "",
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
            limitation,
        ],
    }
    SelectionReport.from_mapping(report)
    path = root / "selection-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**report, "report_path": str(path)}


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
                "failure_class": result.get("failure_class"),
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
