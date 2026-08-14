from __future__ import annotations

from pathlib import Path

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup


def test_cleanup_report_renders_planner_proof_requests_before_agent_view(
    tmp_path: Path,
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
    run_result = {
        "contract": "realworld_cleanup_v1",
        "cleanup_status": "success",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "planner_cleanup_bridge_evidence": {
            "status": "blocked_capability",
            "target_runtime": {"embodiment": "rby1m"},
            "cleanup_primitives": {"status": "blocked_capability", "subphase_count": 4},
            "blockers": [],
            "target_runtime_ready": True,
            "cleanup_primitives_ready": False,
            "planner_backed": False,
        },
        "planner_proof_requests": {
            "schema": "planner_cleanup_proof_requests_v1",
            "request_count": 2,
            "ready_count": 1,
            "agent_view_exposed": False,
            "blockers": [{"code": "planner_binding_backend_unavailable"}],
            "requests": [
                {
                    "request_id": "proof_001",
                    "ready": True,
                    "object_id": "observed_001",
                    "source_receptacle_id": "counter_01",
                    "target_receptacle_id": "sink_01",
                    "tools": [
                        "navigate_to_object",
                        "pick",
                        "navigate_to_receptacle",
                        "place",
                    ],
                    "binding": {
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "planner_probe_args": {},
                    "blockers": [],
                },
                {
                    "request_id": "proof_002",
                    "ready": False,
                    "object_id": "observed_002",
                    "source_receptacle_id": "table_01",
                    "target_receptacle_id": "cabinet_01",
                    "tools": ["navigate_to_object"],
                    "binding": {},
                    "planner_probe_args": {},
                    "blockers": [{"code": "planner_binding_backend_unavailable"}],
                },
            ],
        },
        "agent_view": {
            "contract": "realworld_cleanup_v1",
            "metric_map": {"rooms": [], "inspection_waypoints": []},
            "static_fixture_projection": {"rooms": []},
            "observed_objects": [{"object_id": "observed_001", "category": "dish"}],
        },
        "private_evaluation": {
            "generated_mess_count": 1,
            "generated_mess_set": ["mug_01"],
            "acceptable_destination_sets": {"mug_01": ["sink_01"]},
        },
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
    ordered_headings = [
        "<h2>Planner Cleanup Bridge</h2>",
        "<h2>Planner Proof Requests</h2>",
        "<h2>Agent View</h2>",
    ]
    positions = [html.index(heading) for heading in ordered_headings]
    assert positions == sorted(positions)
    assert "Requests" in html
    assert "proof_001" in html
    assert "ready" in html
    assert "blocked" in html
    assert "observed_001" in html
    assert "counter_01" in html
    assert "sink_01" in html
    assert "navigate_to_object, pick, navigate_to_receptacle, place" in html
    assert "pickup/body" in html
    assert "sink/body" in html
    assert "planner_binding_backend_unavailable" in html
    agent_view_html = html[html.index("<h2>Agent View</h2>") :]
    assert "pickup/body" not in agent_view_html
    assert "sink/body" not in agent_view_html
