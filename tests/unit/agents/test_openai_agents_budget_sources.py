from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.household_live_continuation import _budget_failure_from_run_state


def test_openai_agents_budget_guard_fails_aloud_on_malformed_trace_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        '{"event":"request","tool":"navigate_to_visual_candidate"}\n{bad-json}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents budget trace source row must contain valid JSON object: "
        r".*trace\.jsonl:2",
    ):
        _budget_failure_from_run_state(
            run_dir,
            {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
            {
                "profile_id": "context_managed_v1",
                "context_hard_limit_tokens": None,
                "raw_fpv_candidate_budget": 1,
                "max_observe_per_waypoint": None,
            },
        )


def test_openai_agents_budget_guard_fails_aloud_on_non_object_trace_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        json.dumps(["not", "a", "trace-event"]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents budget trace source row must contain a JSON object: "
        r".*trace\.jsonl:1",
    ):
        _budget_failure_from_run_state(
            run_dir,
            {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
            {
                "profile_id": "context_managed_v1",
                "context_hard_limit_tokens": None,
                "raw_fpv_candidate_budget": 1,
                "max_observe_per_waypoint": None,
            },
        )


def test_openai_agents_budget_guard_treats_missing_trace_as_no_budget_evidence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    failure = _budget_failure_from_run_state(
        run_dir,
        {"evidence_lane": "camera-raw-fpv", "cache_tools_list": True},
        {
            "profile_id": "context_managed_v1",
            "context_hard_limit_tokens": None,
            "raw_fpv_candidate_budget": 1,
            "max_observe_per_waypoint": None,
        },
    )

    assert failure is None
