from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import cleanup_validation_isaac_pose as checker_module


def _load_checker():
    return checker_module


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            '{"event": "response", "response": {"ok": true, "tool": "pick"}}\n{not-json\n',
            r"Isaac semantic-pose trace source row must contain valid JSON object: "
            r".*trace\.jsonl:2",
        ),
        (
            '{"event": "response", "response": {"ok": true, "tool": "pick"}}\n[]\n',
            r"Isaac semantic-pose trace source row must contain a JSON object: "
            r".*trace\.jsonl:2",
        ),
    ],
)
def test_isaac_semantic_pose_checker_rejects_malformed_trace_rows(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    checker = _load_checker()
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        checker.assert_isaac_runtime_semantic_pose(
            data=_semantic_pose_data(trace_path),
            base=tmp_path,
            report_text=_semantic_pose_report_text(),
            isaac={"semantic_pose_state": _semantic_pose_state()},
            scene_bindings=None,
            scene_index_payload=None,
        )


def test_isaac_semantic_pose_checker_accepts_object_trace_rows(tmp_path: Path) -> None:
    checker = _load_checker()
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        _valid_pick_trace_line() + _valid_place_trace_line(),
        encoding="utf-8",
    )

    checker.assert_isaac_runtime_semantic_pose(
        data=_semantic_pose_data(trace_path),
        base=tmp_path,
        report_text=_semantic_pose_report_text(),
        isaac={"semantic_pose_state": _semantic_pose_state()},
        scene_bindings=None,
        scene_index_payload=None,
    )


def _semantic_pose_data(trace_path: Path) -> dict[str, object]:
    return {
        "primitive_provenance": "isaac_semantic_pose",
        "manipulation_evidence": {
            "primitive_provenance": "isaac_semantic_pose",
            "isaac_semantic_pose_edits": True,
            "planner_backed": False,
            "physical_robot": False,
        },
        "semantic_substeps": [],
        "artifacts": {"trace": str(trace_path)},
    }


def _semantic_pose_state() -> dict[str, object]:
    return {
        "schema": "isaac_semantic_pose_state_v1",
        "state_source": "backend_json_state",
        "primitive_provenance": "isaac_semantic_pose",
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "semantic_pose_only": True,
        "object_poses": {
            "mug_01": {
                "state_source": "backend_json_state",
                "rendered_to_usd": False,
                "usd_prim_path": "/World/Objects/mug_01",
            }
        },
        "articulations": {},
        "transform_events": [
            _semantic_pose_event("pick", object_id="mug_01"),
            _semantic_pose_event("place", object_id="mug_01", receptacle_id="sink_01"),
        ],
    }


def _semantic_pose_event(
    tool: str,
    *,
    object_id: str,
    receptacle_id: str = "",
) -> dict[str, object]:
    return {
        "schema": "isaac_semantic_pose_event_v1",
        "state_source": "backend_json_state",
        "primitive_provenance": "isaac_semantic_pose",
        "rendered_to_usd": False,
        "planner_backed": False,
        "physical_robot": False,
        "tool": tool,
        "state_mutation": "isaac_prim_transform",
        "object_id": object_id,
        "receptacle_id": receptacle_id,
        "object_usd_prim_path": "/World/Objects/mug_01",
        "receptacle_usd_prim_path": "/World/Receptacles/sink_01" if receptacle_id else "",
    }


def _semantic_pose_report_text() -> str:
    return " ".join(
        [
            "isaac_semantic_pose",
            "Semantic Pose State",
            "Semantic Pose Events",
            "Rendered to USD",
            "Planner backed",
            "Object USD",
            "Support USD",
            "USD prim",
            "Mutation",
            "Receptacle USD",
            "mug_01",
            "sink_01",
            "pick",
            "place",
            "isaac_prim_transform",
            "/World/Objects/mug_01",
            "/World/Receptacles/sink_01",
        ]
    )


def _valid_pick_trace_line() -> str:
    return _trace_response_line("pick", object_id="mug_01")


def _valid_place_trace_line() -> str:
    return _trace_response_line("place", object_id="mug_01", receptacle_id="sink_01")


def _trace_response_line(
    tool: str,
    *,
    object_id: str,
    receptacle_id: str = "",
) -> str:
    return (
        json.dumps(
            {
                "event": "response",
                "tool": tool,
                "response": {
                    "ok": True,
                    "tool": tool,
                    "object_id": object_id,
                    "receptacle_id": receptacle_id,
                    "state_mutation": "isaac_prim_transform",
                    "primitive_provenance": "isaac_semantic_pose",
                    "planner_backed": False,
                    "physical_robot": False,
                },
            },
            sort_keys=True,
        )
        + "\n"
    )
