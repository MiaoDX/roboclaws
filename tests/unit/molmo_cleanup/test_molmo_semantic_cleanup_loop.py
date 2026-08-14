from __future__ import annotations

from typing import Any

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.semantic_camera_timeline import robot_view_capture_for_tool
from roboclaws.household.semantic_cleanup_loop import run_semantic_cleanup_loop
from roboclaws.household.semantic_timeline import (
    NAVIGATE_TO_OBJECT_PHASE,
    NAVIGATE_TO_RECEPTACLE_PHASE,
    PICK_PHASE,
    PLACE_PHASE,
    has_complete_semantic_sequence,
    primitive_provenance_counts,
    semantic_diagnostics,
    semantic_substeps,
    visual_grounding_status,
)


def test_semantic_cleanup_loop_runs_canonical_fridge_sequence() -> None:
    contract = _FakeCleanupContract()
    calls: list[tuple[str, dict[str, Any]]] = []
    recorded: list[str] = []

    result = run_semantic_cleanup_loop(
        targets=[
            {
                "object_id": "apple_01",
                "target_receptacle_id": "fridge_01",
                "target_receptacle": {"category": "Fridge", "fixture_id": "fridge_01"},
                "source_receptacle_id": "counter_01",
            }
        ],
        contract=contract,
        call_tool=lambda tool, request, fn: _record_call(calls, tool, request, fn),
        record_tool_view=lambda tool, _request, _response: recorded.append(tool),
    )

    assert result.attempted_objects == 1
    assert result.completed_objects == 1
    assert result.failed_objects == ()
    assert [tool for tool, _request in calls] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place_inside",
        "close_receptacle",
    ]
    assert recorded == [tool for tool, _request in calls]
    assert calls[0][1] == {
        "object_id": "apple_01",
        "source_receptacle_id": "counter_01",
    }
    assert calls[3][1] == {
        "object_id": "apple_01",
        "receptacle_id": "fridge_01",
    }
    assert calls[4][1] == {
        "object_id": "apple_01",
        "receptacle_id": "fridge_01",
    }
    assert calls[5][1] == {
        "object_id": "apple_01",
        "receptacle_id": "fridge_01",
    }


def test_semantic_cleanup_loop_preserves_fixture_style_target_requests() -> None:
    contract = _FakeCleanupContract()
    calls: list[tuple[str, dict[str, Any]]] = []

    result = run_semantic_cleanup_loop(
        targets=[
            {
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "target_receptacle": {"category": "Sink", "fixture_id": "sink_01"},
            }
        ],
        contract=contract,
        target_request_key="fixture_id",
        include_object_id_in_receptacle_request=False,
        include_object_id_in_target_requests=False,
        call_tool=lambda tool, request, fn: _record_call(calls, tool, request, fn),
    )

    assert result.completed_objects == 1
    assert [tool for tool, _request in calls] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]
    assert calls[2][1] == {"receptacle_id": "sink_01"}
    assert calls[3][1] == {"fixture_id": "sink_01"}


def test_semantic_cleanup_loop_places_inside_open_shelf_without_close() -> None:
    contract = _FakeCleanupContract()
    calls: list[tuple[str, dict[str, Any]]] = []

    result = run_semantic_cleanup_loop(
        targets=[
            {
                "object_id": "book_01",
                "target_receptacle_id": "bookshelf_01",
                "target_receptacle": {"category": "bookshelf", "fixture_id": "bookshelf_01"},
            }
        ],
        contract=contract,
        call_tool=lambda tool, request, fn: _record_call(calls, tool, request, fn),
    )

    assert result.completed_objects == 1
    assert [tool for tool, _request in calls] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place_inside",
    ]


def test_robot_view_capture_can_translate_public_handles_to_focus_ids() -> None:
    capture = robot_view_capture_for_tool(
        "place_inside",
        {"fixture_id": "fridge_01"},
        {
            "ok": True,
            "object_id": "observed_001",
            "receptacle_id": "fridge_01",
        },
        object_id_transform=lambda value: "apple_01" if value == "observed_001" else value,
    )

    assert capture is not None
    assert capture["action"] == "place_inside observed_001"
    assert capture["label_suffix"] == "place_inside_observed_001"
    assert capture["focus_object_id"] == "apple_01"
    assert capture["focus_receptacle_id"] == "fridge_01"


def test_robot_view_capture_records_close_receptacle_focus() -> None:
    capture = robot_view_capture_for_tool(
        "close_receptacle",
        {"fixture_id": "fridge_01", "object_id": "observed_001"},
        {
            "ok": True,
            "object_id": "observed_001",
            "receptacle_id": "fridge_01",
        },
    )

    assert capture is not None
    assert capture["action"] == "close_receptacle fridge_01"
    assert capture["label_suffix"] == "close_receptacle_fridge_01"
    assert capture["focus_object_id"] == "observed_001"
    assert capture["focus_receptacle_id"] == "fridge_01"


def test_visual_candidate_navigation_counts_as_object_navigation() -> None:
    capture = robot_view_capture_for_tool(
        "navigate_to_visual_candidate",
        {
            "source_observation_id": "raw_fpv_001",
            "category": "dish",
            "image_region": {"type": "bbox", "value": [10, 20, 30, 40]},
        },
        {
            "ok": True,
            "tool": "navigate_to_visual_candidate",
            "object_id": "observed_001",
            "source_receptacle_id": "counter_01",
            "visual_grounding_evidence": {
                "source_observation_id": "raw_fpv_001",
                "image_bbox": [10, 20, 30, 40],
                "bbox_coordinate_space": "pixel_xywh",
                "camera_frame": "agent_facing_fpv",
                "reviewability_status": "reviewable",
                "grounding_status": "resolved",
            },
            "model_declared_observation": {
                "category": "dish",
                "evidence_note": "white dish on table",
                "grounding_status": "resolved",
                "grounding_confidence": 0.72,
                "grounding_basis": "single public object matched category",
                "source_observation_id": "raw_fpv_001",
            },
        },
        object_id_transform=lambda value: "apple_01" if value == "observed_001" else value,
    )

    assert capture is not None
    assert capture["action"] == "navigate_to_visual_candidate observed_001"
    assert capture["label_suffix"] == "navigate_visual_candidate_observed_001"
    assert capture["focus_object_id"] == "apple_01"
    assert capture["focus_receptacle_id"] == "counter_01"
    assert capture["semantic_phase"] == "navigate_to_object"
    assert capture["action_evidence"] == {
        "schema": "robot_timeline_action_evidence_v1",
        "agent_tool": "navigate_to_visual_candidate",
        "agent_action": "navigate_to_visual_candidate observed_001",
        "backend_primitive": "navigate_to_object",
        "resolved_object_id": "observed_001",
        "source_observation_id": "raw_fpv_001",
        "source_image_bbox": [10, 20, 30, 40],
        "bbox_coordinate_space": "pixel_xywh",
        "camera_frame": "agent_facing_fpv",
        "reviewability_status": "reviewable",
        "grounding_status": "resolved",
        "grounding_confidence": 0.72,
        "grounding_basis": "single public object matched category",
        "declared_category": "dish",
        "evidence_note": "white dish on table",
    }

    substeps = semantic_substeps(
        [
            {
                "event": "response",
                "tool": "navigate_to_visual_candidate",
                "response": {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                    "source_receptacle_id": "counter_01",
                },
            },
            {
                "event": "response",
                "tool": "pick",
                "response": {"ok": True, "tool": "pick", "object_id": "observed_001"},
            },
            {
                "event": "response",
                "tool": "navigate_to_receptacle",
                "response": {
                    "ok": True,
                    "tool": "navigate_to_receptacle",
                    "object_id": "observed_001",
                    "receptacle_id": "sink_01",
                },
            },
            {
                "event": "response",
                "tool": "place",
                "response": {
                    "ok": True,
                    "tool": "place",
                    "object_id": "observed_001",
                    "receptacle_id": "sink_01",
                },
            },
        ],
        {"sink_01": {"category": "Sink"}},
    )

    assert [step["phase"] for step in substeps[0]["steps"]] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]
    assert substeps[0]["steps"][0]["tool"] == "navigate_to_visual_candidate"


def test_primitive_provenance_counts_summarizes_atomic_semantic_steps() -> None:
    counts = primitive_provenance_counts(
        [
            _trace_response(NAVIGATE_TO_OBJECT_PHASE, _ok(NAVIGATE_TO_OBJECT_PHASE)),
            _trace_response(PICK_PHASE, _ok(PICK_PHASE)),
            _trace_response(NAVIGATE_TO_RECEPTACLE_PHASE, _ok(NAVIGATE_TO_RECEPTACLE_PHASE)),
            _trace_response(PLACE_PHASE, _ok(PLACE_PHASE)),
            _trace_response(
                "observe",
                {
                    "ok": True,
                    "tool": "observe",
                    "primitive_provenance": "camera_artifact",
                },
            ),
        ]
    )

    assert counts[API_SEMANTIC_PROVENANCE] == 4
    assert counts["camera_artifact"] == 1


def test_complete_semantic_sequence_tolerates_later_retries_after_place() -> None:
    assert has_complete_semantic_sequence(
        [
            "navigate_to_object",
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            "place",
        ]
    )
    assert has_complete_semantic_sequence(
        [
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            "place",
            "navigate_to_object",
            "navigate_to_object",
        ]
    )
    assert has_complete_semantic_sequence(
        [
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            "place_inside",
            "navigate_to_object",
        ]
    )
    assert not has_complete_semantic_sequence(
        [
            "navigate_to_object",
            "pick",
            "navigate_to_receptacle",
            "navigate_to_object",
        ]
    )


def test_semantic_diagnostics_flags_duplicate_post_place_visual_navigation() -> None:
    diagnostics = semantic_diagnostics(
        [
            _trace_response("observe", {"ok": True, "tool": "observe"}),
            _trace_response(
                "navigate_to_visual_candidate",
                {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                },
            ),
            _trace_response("pick", {"ok": True, "tool": "pick", "object_id": "observed_001"}),
            _trace_response("place", {"ok": True, "tool": "place", "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_visual_candidate",
                {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                },
            ),
        ],
        [],
        {"score": {"restored_count": 1, "total_targets": 1}},
    )

    assert diagnostics["duplicate_post_place_navigation_count"] == 1
    assert diagnostics["duplicate_post_place_navigation_handles"] == ["observed_001"]


def test_semantic_diagnostics_allows_normal_visual_cleanup_sequence() -> None:
    diagnostics = semantic_diagnostics(
        [
            _trace_response("observe", {"ok": True, "tool": "observe"}),
            _trace_response(
                "navigate_to_visual_candidate",
                {
                    "ok": True,
                    "tool": "navigate_to_visual_candidate",
                    "object_id": "observed_001",
                },
            ),
            _trace_response("pick", {"ok": True, "tool": "pick", "object_id": "observed_001"}),
            _trace_response(
                "navigate_to_receptacle",
                {
                    "ok": True,
                    "tool": "navigate_to_receptacle",
                    "object_id": "observed_001",
                    "receptacle_id": "sink_01",
                },
            ),
            _trace_response("place", {"ok": True, "tool": "place", "object_id": "observed_001"}),
        ],
        [],
        {"score": {"restored_count": 1, "total_targets": 1}},
    )

    assert diagnostics["duplicate_post_place_navigation_count"] == 0
    assert diagnostics["duplicate_post_place_navigation_handles"] == []


def test_semantic_diagnostics_tracks_recovered_semantic_order_errors() -> None:
    diagnostics = semantic_diagnostics(
        [
            _trace_response(
                "place",
                {
                    "ok": False,
                    "tool": "place",
                    "object_id": "observed_001",
                    "error_reason": "semantic_order",
                    "required_tool": "place_inside",
                },
            )
        ],
        [
            {
                "object_id": "observed_001",
                "target_receptacle_category": "ShelvingUnit",
                "steps": [
                    {"phase": "navigate_to_object", "ok": True},
                    {"phase": "pick", "ok": True},
                    {"phase": "navigate_to_receptacle", "ok": True},
                    {
                        "phase": "place",
                        "ok": False,
                        "error_reason": "semantic_order",
                    },
                    {"phase": "place_inside", "ok": True},
                ],
            }
        ],
        {"score": {"restored_count": 1, "total_targets": 1}},
    )

    assert diagnostics["semantic_order_errors"] == 1
    assert diagnostics["semantic_order_recovered_errors"] == 1
    assert diagnostics["semantic_order_unrecovered_errors"] == 0


def test_visual_grounding_only_hides_closed_container_contents() -> None:
    visibility = {"status": "ok", "object_pixels": 0}

    assert (
        visual_grounding_status(
            {
                "object_id": "apple_01",
                "receptacle_id": "fridge_01",
                "receptacle_category": "Fridge",
                "object_contained_in": "fridge_01",
                "object_location_relation": "inside",
            },
            visibility,
        )
        == "contained_inside"
    )
    assert (
        visual_grounding_status(
            {
                "object_id": "book_01",
                "receptacle_id": "shelf_01",
                "receptacle_category": "ShelvingUnit",
                "object_contained_in": "shelf_01",
                "object_location_relation": "inside",
            },
            visibility,
        )
        == "weak_object_visibility"
    )


def _record_call(
    calls: list[tuple[str, dict[str, Any]]],
    tool: str,
    request: dict[str, Any],
    fn: Any,
) -> dict[str, Any]:
    calls.append((tool, dict(request)))
    return fn()


def _trace_response(tool: str, response: dict[str, Any]) -> dict[str, Any]:
    return {"event": "response", "tool": tool, "response": response}


class _FakeCleanupContract:
    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return _ok(
            "navigate_to_object",
            object_id=object_id,
            source_receptacle_id="counter_01",
        )

    def pick(self, object_id: str) -> dict[str, Any]:
        return _ok(
            "pick",
            object_id=object_id,
            previous_location_id="counter_01",
        )

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return _ok(
            "navigate_to_receptacle",
            object_id="held_object",
            receptacle_id=receptacle_id,
        )

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return _ok("open_receptacle", receptacle_id=receptacle_id, opened=True)

    def place(self, receptacle_id: str) -> dict[str, Any]:
        return _ok("place", object_id="held_object", receptacle_id=receptacle_id)

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        return _ok("place_inside", object_id="held_object", receptacle_id=receptacle_id)

    def close_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return _ok("close_receptacle", object_id="held_object", receptacle_id=receptacle_id)


def _ok(tool: str, **payload: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "status": "ok",
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        **payload,
    }
