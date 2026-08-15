from __future__ import annotations

from types import SimpleNamespace

from roboclaws.agents.drivers.openai_agents_event_projection import _usage_summary


def test_usage_summary_reads_agents_sdk_context_wrapper_usage() -> None:
    result = SimpleNamespace(
        context_wrapper=SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=120,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
                output_tokens=30,
                output_tokens_details=SimpleNamespace(reasoning_tokens=10),
            )
        )
    )

    assert _usage_summary(result) == {
        "usage_available": True,
        "input_tokens": 120,
        "cached_input_tokens": 20,
        "uncached_input_tokens": 100,
        "output_tokens": 30,
        "reasoning_tokens": 10,
    }
