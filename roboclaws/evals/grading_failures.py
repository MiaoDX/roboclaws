"""Eval runner exception classification and blocked-result projection."""

from __future__ import annotations

from typing import Any

from roboclaws.evals.live_timeout import LiveEvalTimeoutError, live_exception_debug_fields
from roboclaws.evals.models import EvalResult, EvalTrial


def blocked_result_from_exception(trial: EvalTrial, exc: Exception) -> EvalResult:
    failure_class = failure_class_from_exception(exc)
    blocked = failure_class in {"environment_blocked", "model_or_provider_unavailable"}
    runner_output: dict[str, Any] = {
        "status": "blocked" if blocked else "failed",
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    runner_output.update(live_exception_debug_fields(exc))
    return EvalResult.from_trial(
        trial,
        status="blocked" if blocked else "failed",
        failure_class=failure_class,
        grader_outputs={"runner": runner_output},
        artifacts={},
        metrics={"pass": 0.0},
        limitations=(*trial.limitations, "product_run_failed_before_grading"),
    )


def failure_class_from_exception(exc: Exception) -> str:
    typed_failure_class = _typed_failure_class(exc)
    if typed_failure_class is not None:
        return typed_failure_class
    message = str(exc).lower()
    if any(
        token in message
        for token in (
            "agent_sdk_turn_budget_exceeded",
            "budget_exhausted",
            "observe_budget_exhausted",
            "provider_context_budget_exceeded",
        )
    ):
        return "budget_exhausted"
    if "checker_validation_failed" in message:
        return "checker_validation_failed"
    environment_tokens = ("no module named", "not installed", "unavailable", "timed out", "mcp")
    if "another interactive codex molmo cleanup session appears to be active" in message:
        return "environment_blocked"
    if any(token in message for token in environment_tokens):
        return "environment_blocked"
    artifact_tokens = (
        "generated_mess_count must be a non-negative integer",
        "launch_overrides.relocation_count must be a non-negative integer",
        "launch_overrides.scene_index must be a non-negative integer",
        "launch_overrides.scene_source must be a non-empty string",
        "runtime_map_prior must be a string path",
        "runtime_map_prior_from_sample must be a non-empty string",
        "eval_effective_run_dir",
        "live eval run_result",
        "invalid live eval json artifact",
        "live eval json artifact",
        "regrade_source",
        "regrade effective run dir",
        "regrade run_result",
    )
    if any(token in message for token in artifact_tokens):
        return "artifact_missing"
    if any(
        token in message
        for token in (
            "invalid function arguments json",
            "invalid function arguments",
            "invalid_prompt",
            "tool_call_id",
        )
    ):
        return "tool_argument_invalid"
    if "turn ended without done" in message:
        return "agent_no_completion_claim"
    provider_tokens = (
        "access_terminated_error",
        "provider_",
        "usage limit for this billing cycle",
        "model_service",
        "error code: 5",
        "error code: 429",
        "bad_response_status_code",
        "openai_error",
        "rate_limit",
    )
    if any(token in message for token in provider_tokens):
        return "model_or_provider_unavailable"
    return "harness_bug_unclassified"


def _typed_failure_class(exc: Exception) -> str | None:
    if isinstance(exc, LiveEvalTimeoutError) and exc.timeout_kind == "wall_clock_budget_exhausted":
        return "budget_exhausted"
    if isinstance(exc, (ImportError, ModuleNotFoundError, TimeoutError)):
        return "environment_blocked"
    return None
