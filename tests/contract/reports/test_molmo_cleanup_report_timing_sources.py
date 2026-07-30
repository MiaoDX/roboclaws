from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import render_cleanup_report
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"report live timing source must contain valid JSON object: .*live_timing\.json",
        ),
        (
            "[]\n",
            r"report live timing source must contain a JSON object: .*live_timing\.json",
        ),
    ],
)
def test_cleanup_report_rejects_bad_present_live_timing_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    run_result = {
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "runtime_timing": {
            "total_elapsed_s": 1.0,
            "tool_handler_s": 0.2,
            "robot_view_capture_s": 0.0,
            "between_tool_gap_s": 0.3,
            "other_mcp_overhead_s": 0.5,
            "tool_call_count": 1,
        },
        "score": score_cleanup(scenario.object_locations(), scenario.private_manifest).to_dict(),
    }
    (tmp_path / "live_timing.json").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        render_cleanup_report(
            run_dir=tmp_path,
            scenario=scenario,
            run_result=run_result,
            trace_events=[],
            before_snapshot=before,
            after_snapshot=after,
        )
