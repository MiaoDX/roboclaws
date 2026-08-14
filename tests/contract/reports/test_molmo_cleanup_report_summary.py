from __future__ import annotations

from pathlib import Path

from roboclaws.household.advisory_scoring import build_advisory_evaluation
from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.manipulation_provenance import (
    api_semantic_manipulation_evidence,
)
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup


def test_cleanup_report_renders_score_moves_and_provenance(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    final_locations = scenario.object_locations()
    final_locations.update({"mug_01": "sink_01", "book_01": "bookshelf_01"})
    score = score_cleanup(final_locations, scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(scenario, final_locations, tmp_path / "after.png", title="After")
    run_result = {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "manipulation_evidence": api_semantic_manipulation_evidence(
            backend="api_semantic_synthetic",
            primitive_summary={API_SEMANTIC_PROVENANCE: 1},
        ),
        "score": score.to_dict(),
        "advisory_evaluation": build_advisory_evaluation(
            score=score.to_dict(),
            scenario_id=scenario.scenario_id,
        ),
    }
    trace_events = [
        {
            "tool": "place",
            "event": "response",
            "response": {
                "ok": True,
                "object_id": "mug_01",
                "receptacle_id": "sink_01",
                "primitive_provenance": API_SEMANTIC_PROVENANCE,
            },
        }
    ]
    run_result["cleanup_primitive_evidence"] = cleanup_primitive_evidence_from_substeps(
        [
            {
                "object_id": "mug_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {
                        "phase": "navigate_to_object",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                    },
                    {
                        "phase": "pick",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                    },
                    {
                        "phase": "navigate_to_receptacle",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                    },
                    {
                        "phase": "place",
                        "status": "ok",
                        "primitive_provenance": API_SEMANTIC_PROVENANCE,
                        "state_mutation": "mujoco_freejoint_qpos",
                    },
                ],
            }
        ]
    )

    report_path = render_cleanup_report(
        run_dir=tmp_path,
        scenario=scenario,
        run_result=run_result,
        trace_events=trace_events,
        before_snapshot=before,
        after_snapshot=after,
    )

    html = report_path.read_text(encoding="utf-8")
    assert "MolmoSpaces Cleanup Pilot" in html
    assert "Rerun Locally" not in html
    assert "rerun_command" not in run_result
    assert "api_semantic" in html
    assert "Manipulation Provenance" in html
    assert "Cleanup Primitive Gate" in html
    assert "<td>nav</td>" in html
    assert "<td>object</td>" in html
    assert "mujoco_freejoint_qpos" in html
    assert "does not prove planner-backed robot manipulation" in html
    assert "mug_01" in html
    assert "Semantic acceptability" in html
    assert "Advisory Review" in html
    assert "authoritative=false" in html
    assert "valid_receptacle_ids" not in html
    assert before.is_file()
    assert after.is_file()


def test_cleanup_report_surfaces_failure_reason_on_summary(tmp_path: Path) -> None:
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
    reason = (
        "Task could not be completed with public robot capabilities; "
        "generated_exploration_004 was blocked by goal_occupied."
    )
    run_result = {
        "cleanup_status": "failed",
        "completion_status": "failed",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": {**score.to_dict(), "completion_summary": "less specific summary"},
        "terminate_reason": reason,
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
    assert "Failure Reason" in html
    assert reason in html
    assert html.index("Failure Reason") < html.index("Run metadata")


def test_cleanup_report_hides_failure_reason_on_success(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    final_locations = scenario.object_locations()
    final_locations.update({"mug_01": "sink_01", "book_01": "bookshelf_01"})
    score = score_cleanup(final_locations, scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(scenario, final_locations, tmp_path / "after.png", title="After")
    run_result = {
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "terminate_reason": "successful completion note",
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
    assert "Failure Reason" not in html
    assert "successful completion note" not in html


def test_open_ended_report_ignores_advisory_cleanup_failure(tmp_path: Path) -> None:
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
    run_result = {
        "task_intent": "open-ended",
        "goal_contract": {"intent": "open-ended"},
        "cleanup_status_role": "advisory",
        "intent_status": "success",
        "goal_status": "success",
        "final_status": "success",
        "cleanup_status": "failed",
        "completion_status": "failed",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": {**score.to_dict(), "status": "success"},
        "terminate_reason": "open-ended task completed",
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
    assert "MolmoSpaces Open-ended Pilot" in html
    assert "Open-ended artifact" in html
    assert "Failure Reason" not in html
    assert "<span>Status</span><strong>Success</strong>" in html
