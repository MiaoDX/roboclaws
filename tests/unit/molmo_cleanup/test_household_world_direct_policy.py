from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.core.map_build_scan_profile import map_build_scan_profile
from roboclaws.household import (
    household_direct_cleanup_selection,
    household_world_direct_policy,
)
from roboclaws.household.household_runtime_contract import CAMERA_MODEL_POLICY_MODE


@pytest.mark.parametrize(
    ("perception_mode", "expected_observes", "expected_turns"),
    [(CAMERA_MODEL_POLICY_MODE, 4, 3), ("world_public_labels", 1, 0)],
)
def test_direct_cleanup_scan_uses_bounded_turns_only_for_camera_grounded_mode(
    perception_mode: str,
    expected_observes: int,
    expected_turns: int,
) -> None:
    calls: list[str] = []
    observation_index = 0

    def observe():
        nonlocal observation_index
        observation_index += 1
        return {
            "ok": True,
            "raw_fpv_observation": {
                "observation_id": f"obs-{observation_index}",
                "camera_control_contract": {"robot_pose": {"theta": 0.0}},
            },
        }

    def call_tool(_events, _started_at, tool, _request, callback, postprocess=None):
        calls.append(tool)
        response = callback()
        return postprocess(response) if postprocess is not None else response

    contract = SimpleNamespace(
        observe=observe,
        navigate_to_relative_pose=lambda **kwargs: {
            "ok": True,
            "applied_delta": {"yaw_delta_deg": kwargs["yaw_delta_deg"]},
        },
    )
    hooks = SimpleNamespace(
        call_tool=call_tool,
        attach_raw_fpv_robot_view=lambda **kwargs: kwargs["response"],
        view_index_after_raw_fpv=lambda _steps, index: index,
        detections_for_policy=lambda **_kwargs: [],
    )

    household_world_direct_policy._observe_direct_cleanup_waypoint(
        trace_events=[],
        started_at=0.0,
        contract=contract,
        base_contract=SimpleNamespace(),
        robot_view_steps=[],
        output_dir=Path("unused"),
        view_index=0,
        record_robot_views=False,
        episode_policy=household_world_direct_policy.DirectHouseholdEpisodePolicy(
            policy_name="test",
            artifact_kind="household_episode",
            cleanup_actions_enabled=True,
        ),
        perception_mode=perception_mode,
        hooks=hooks,
        map_build_scan_profile=map_build_scan_profile(),
    )

    assert calls.count("observe") == expected_observes
    assert calls.count("navigate_to_relative_pose") == expected_turns


def test_direct_policy_uses_same_waypoint_public_destination_for_unknown_category(
    monkeypatch,
) -> None:
    options = [
        {
            "candidate_fixture_id": "anchor_fixture_counter",
            "candidate_fixture_category": "countertop",
            "recommended_tool": "place",
            "waypoint_id": "room_2_inspection",
        },
        {
            "candidate_fixture_id": "anchor_fixture_desk",
            "candidate_fixture_category": "desk",
            "recommended_tool": "place",
            "waypoint_id": "room_7_inspection",
        },
    ]
    monkeypatch.setattr(
        household_direct_cleanup_selection,
        "destination_options_for_policy",
        lambda contract, policy: options,
    )
    selected_detections = []

    def target_fixture_for_detection(detection, **kwargs):
        del kwargs
        selected_detections.append(dict(detection))
        if "candidate_fixture_id" not in detection:
            return {"fixture_id": "anchor_fixture_bed"}
        return {"fixture_id": detection["candidate_fixture_id"]}

    contract = SimpleNamespace(
        sanitize_world_labels=True,
        target_fixture_for_detection=target_fixture_for_detection,
    )
    detection = {
        "object_id": "observed_box",
        "category": "Box",
        "waypoint_id": "room_7_inspection",
        "support_estimate": {"fixture_id": "anchor_fixture_bed"},
        "destination_policy": {"preferred_fixture_categories": ["countertop", "desk"]},
    }

    target = household_direct_cleanup_selection.direct_policy_target_fixture(
        contract=contract,
        detection=detection,
    )

    assert target == {"fixture_id": "anchor_fixture_desk"}
    assert selected_detections[-1]["candidate_fixture_id"] == "anchor_fixture_desk"
    assert selected_detections[-1]["recommended_tool"] == "place"


def test_direct_policy_keeps_non_source_category_inference(monkeypatch) -> None:
    monkeypatch.setattr(
        household_direct_cleanup_selection,
        "destination_options_for_policy",
        lambda contract, policy: [
            {
                "candidate_fixture_id": "anchor_fixture_counter",
                "candidate_fixture_category": "countertop",
                "recommended_tool": "place",
                "waypoint_id": "room_6_inspection",
            }
        ],
    )
    calls = []

    def target_fixture_for_detection(detection, **kwargs):
        del kwargs
        calls.append(dict(detection))
        return {"fixture_id": "anchor_fixture_sink"}

    contract = SimpleNamespace(
        sanitize_world_labels=True,
        target_fixture_for_detection=target_fixture_for_detection,
    )

    target = household_direct_cleanup_selection.direct_policy_target_fixture(
        contract=contract,
        detection={
            "category": "Plate",
            "support_estimate": {"fixture_id": "anchor_fixture_bed"},
            "destination_policy": {"preferred_fixture_categories": ["sink", "countertop"]},
        },
    )

    assert target == {"fixture_id": "anchor_fixture_sink"}
    assert len(calls) == 1


def test_already_satisfied_direct_candidate_stays_handled_after_reobservation() -> None:
    lifecycle = {}

    def set_handle_state(handle, state, **updates):
        lifecycle[handle] = {"state": state, **updates}

    contract = SimpleNamespace(
        _handled_handles=set(),
        _set_handle_state=set_handle_state,
        cleanup_worklist_payload=lambda **kwargs: {
            "objects": [
                {
                    "object_id": "observed_box",
                    "candidate_fixture_id": "anchor_fixture_desk",
                }
            ]
        },
        static_fixture_projection=lambda: {},
        public_receptacles_by_id=lambda: {},
    )
    candidate = household_direct_cleanup_selection.VisibleObjectCandidate(
        detection={"object_id": "observed_box"},
        target_fixture={"fixture_id": "anchor_fixture_desk"},
        support={"fixture_id": "anchor_fixture_desk"},
        target_fixture_id="anchor_fixture_desk",
        view_index=0,
    )
    scratchpad = {"notes": []}

    result = household_direct_cleanup_selection.redirect_if_already_on_inferred_fixture(
        contract=contract,
        handle="observed_box",
        candidate=candidate,
        agent_scratchpad=scratchpad,
    )

    assert result is None
    assert "observed_box" in contract._handled_handles
    assert lifecycle["observed_box"]["state"] == "placed"
    assert scratchpad["notes"] == [
        {"object_id": "observed_box", "reason": "already_on_inferred_fixture"}
    ]


def test_blocked_done_fallback_preserves_semantic_acceptability() -> None:
    scenario = {
        "objects": [{"object_id": "book", "category": "Book"}],
        "receptacles": [{"receptacle_id": "shelf", "category": "ShelvingUnit"}],
    }
    contract = SimpleNamespace(
        scenario=scenario,
        _realworld_metrics=lambda score, final_locations: {
            "completion_status": "success",
            "final_location_count": len(final_locations),
        },
    )
    base_contract = SimpleNamespace(
        done=lambda reason: {
            "score": {
                "status": "success",
                "success_threshold": 1,
                "total_targets": 1,
                "object_results": [
                    {
                        "object_id": "book",
                        "actual_location_id": "shelf",
                        "restored": True,
                    }
                ],
            },
            "final_locations": {"book": "shelf"},
            "final_containment": {},
            "tool_event_counts": {"done": 1},
        },
        final_locations=lambda locations: locations,
    )

    result = household_world_direct_policy._done_with_failed_score(
        contract=contract,
        base_contract=base_contract,
        done={"ok": False, "error_reason": "pending_cleanup_candidates"},
        reason="incomplete",
        hooks=SimpleNamespace(failed_score=lambda contract: {}),
    )

    assert result["score"]["object_results"][0]["restored"] is True
    assert result["score"]["object_results"][0]["semantic_acceptability"] == "preferred"
    assert result["score"]["semantic_acceptability"]["accepted_count"] == 1
    assert result["score"]["completion_status"] == "success"
