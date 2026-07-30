from roboclaws.evals.grading_failures import failure_class_from_exception


def test_grading_classifies_agent_turn_without_done() -> None:
    failure_class = failure_class_from_exception(
        RuntimeError("OpenAI Agents SDK turn ended without done after 2 invocation(s)")
    )

    assert failure_class == "agent_no_completion_claim"


def test_grading_classifies_provider_billing_limit() -> None:
    failure_class = failure_class_from_exception(
        RuntimeError("OpenAI Agents SDK runtime failed: provider_quota_failure")
    )

    assert failure_class == "model_or_provider_unavailable"
