from __future__ import annotations

from pathlib import Path

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup


def test_cleanup_report_prefers_recorded_rerun_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
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
    prior = "output/household/household-world/map-build/anchor/seed-7/runtime_metric_map.json"
    command = (
        "just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 "
        "backend=mujoco intent=cleanup agent_engine=openai-agents-sdk "
        "provider_profile=kimi-openai-chat evidence_lane=world-public-labels seed=7 "
        "scenario_setup=relocate-cleanup-related-objects relocation_count=5 "
        "robot_views=on "
        f"runtime_map_prior={prior} "
        "output_dir=output/household/cleanup/sdk-from-semantic-map-with-views"
    )
    monkeypatch.setenv(
        "ROBOCLAWS_REPORT_RERUN_COMMAND",
        "just run::surface surface=household-world agent_engine=direct-runner "
        "intent=cleanup evidence_lane=world-public-labels seed=7",
    )
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "rerun_command": command,
    }

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=[],
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert "just run::surface \\\n" in html
    assert "surface=household-world" in html
    assert "agent_engine=openai-agents-sdk" in html
    assert "provider_profile=kimi-openai-chat" in html
    assert f"runtime_map_prior={prior}" in html
    assert run_result["rerun_command"] == command
    assert "household-cleanup direct world-public-labels" not in html
