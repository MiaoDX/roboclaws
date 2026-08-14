from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_jsonl_objects
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SEMANTIC_POSE_EVENT_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SOURCE,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE
from roboclaws.household.realworld_mcp_atomic_tools import ATOMIC_CLEANUP_TOOL_NAMES
from roboclaws.household.semantic_timeline import SEMANTIC_RESPONSE_PHASES


def assert_isaac_runtime_semantic_pose(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    isaac: dict[str, Any],
    *,
    scene_bindings: dict[str, Any] | None,
    scene_index_payload: dict[str, Any] | None,
) -> None:
    assert data.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, data
    evidence = data.get("manipulation_evidence") or {}
    assert evidence.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, evidence
    assert evidence.get("isaac_semantic_pose_edits") is True, evidence
    assert evidence.get("planner_backed") is False, evidence
    assert evidence.get("physical_robot") is False, evidence
    assert ISAAC_SEMANTIC_POSE_PROVENANCE in report_text, report_text[:500]
    _assert_report_text_values(
        report_text,
        "Semantic Pose State",
        "Semantic Pose Events",
        "Rendered to USD",
        "Planner backed",
    )
    for item in data.get("semantic_substeps") or []:
        for step in item.get("steps") or []:
            if step.get("phase") in SEMANTIC_RESPONSE_PHASES and step.get("status") == "ok":
                assert step.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, step
                assert step.get("planner_backed") is not True, step
                assert step.get("physical_robot") is not True, step
    semantic_pose_state = isaac.get("semantic_pose_state") or {}
    _assert_isaac_semantic_pose_state(
        isaac,
        scene_bindings=scene_bindings,
        scene_index_payload=scene_index_payload,
    )
    _assert_isaac_semantic_pose_report_rows(semantic_pose_state, report_text)
    _assert_isaac_semantic_pose_trace(data, base, semantic_pose_state)


def _assert_isaac_semantic_pose_state(
    isaac: dict[str, Any],
    *,
    scene_bindings: dict[str, Any] | None = None,
    scene_index_payload: dict[str, Any] | None = None,
) -> None:
    state = isaac.get("semantic_pose_state") or {}
    assert state.get("schema") == ISAAC_SEMANTIC_POSE_STATE_SCHEMA, state
    assert state.get("state_source") == ISAAC_SEMANTIC_POSE_STATE_SOURCE, state
    assert state.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, state
    rendered_to_usd = state.get("rendered_to_usd")
    assert rendered_to_usd in {False, True}, state
    if rendered_to_usd is True:
        capture = state.get("semantic_pose_view_capture") or {}
        assert isinstance(capture, dict), state
        assert capture.get("schema") == "isaac_semantic_pose_robot_view_capture_v1", capture
        assert capture.get("capture_method") == (
            "isaac_lab_camera_rgb_semantic_pose_robot_views"
        ), capture
        assert capture.get("rendered_to_usd") is True, capture
        assert int(capture.get("render_steps") or 0) > 0, capture
    assert state.get("planner_backed") is False, state
    assert state.get("physical_robot") is False, state
    assert state.get("semantic_pose_only") is True, state
    object_poses = state.get("object_poses") or {}
    assert object_poses, state
    events = state.get("transform_events") or []
    assert events, state
    tools = {str(event.get("tool") or "") for event in events if isinstance(event, dict)}
    assert "pick" in tools, events
    assert tools & {"place", "place_inside"}, events
    event_object_ids = {
        str(event.get("object_id") or "") for event in events if isinstance(event, dict)
    }
    assert any(object_id in object_poses for object_id in event_object_ids), (
        event_object_ids,
        object_poses,
    )
    for event in events:
        assert event.get("schema") == ISAAC_SEMANTIC_POSE_EVENT_SCHEMA, event
        assert event.get("state_source") == ISAAC_SEMANTIC_POSE_STATE_SOURCE, event
        assert event.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, event
        assert event.get("rendered_to_usd") is False, event
        assert event.get("planner_backed") is False, event
        assert event.get("physical_robot") is False, event
        assert str(event.get("state_mutation") or "").startswith("isaac_"), event
    for pose in object_poses.values():
        assert pose.get("state_source") == ISAAC_SEMANTIC_POSE_STATE_SOURCE, pose
        assert pose.get("rendered_to_usd") is False, pose
    if scene_bindings is not None and scene_index_payload is not None:
        _assert_isaac_semantic_pose_usd_paths_match_scene_index(
            state,
            scene_bindings=scene_bindings,
            object_index=scene_index_payload.get("object_index") or {},
            receptacle_index=scene_index_payload.get("receptacle_index") or {},
        )


def _assert_isaac_semantic_pose_usd_paths_match_scene_index(
    state: dict[str, Any],
    *,
    scene_bindings: dict[str, Any],
    object_index: dict[str, Any],
    receptacle_index: dict[str, Any],
) -> None:
    object_paths = _index_usd_prim_paths(object_index)
    receptacle_paths = _index_usd_prim_paths(receptacle_index)
    selected_object_paths = _selected_binding_usd_prim_paths(
        scene_bindings,
        "selected_object_bindings",
    )
    selected_receptacle_paths = _selected_binding_usd_prim_paths(
        scene_bindings,
        "selected_target_receptacle_bindings",
    )
    _assert_semantic_pose_object_paths(state, selected_object_paths, receptacle_paths)
    _assert_semantic_pose_articulation_paths(state, selected_receptacle_paths, receptacle_paths)
    _assert_semantic_pose_event_paths(
        state,
        selected_object_paths=selected_object_paths,
        selected_receptacle_paths=selected_receptacle_paths,
        object_paths=object_paths,
        receptacle_paths=receptacle_paths,
    )


def _assert_semantic_pose_object_paths(
    state: dict[str, Any],
    selected_object_paths: dict[str, str],
    receptacle_paths: dict[str, str],
) -> None:
    object_poses = state.get("object_poses") or {}
    assert isinstance(object_poses, dict), state
    for object_id, pose in object_poses.items():
        assert isinstance(pose, dict), (object_id, pose)
        _assert_semantic_usd_path_matches_scene_index(
            "semantic object pose",
            public_id=str(object_id),
            usd_prim_path=str(pose.get("usd_prim_path") or ""),
            selected_paths=selected_object_paths,
            index_paths=selected_object_paths,
        )
        support_receptacle_id = str(pose.get("support_receptacle_id") or "")
        if support_receptacle_id:
            _assert_semantic_usd_path_matches_scene_index(
                "semantic object support",
                public_id=support_receptacle_id,
                usd_prim_path=str(pose.get("support_usd_prim_path") or ""),
                selected_paths=receptacle_paths,
                index_paths=receptacle_paths,
            )


def _assert_semantic_pose_articulation_paths(
    state: dict[str, Any],
    selected_receptacle_paths: dict[str, str],
    receptacle_paths: dict[str, str],
) -> None:
    articulations = state.get("articulations") or {}
    assert isinstance(articulations, dict), state
    for receptacle_id, articulation in articulations.items():
        assert isinstance(articulation, dict), (receptacle_id, articulation)
        _assert_semantic_usd_path_matches_scene_index(
            "semantic articulation",
            public_id=str(receptacle_id),
            usd_prim_path=str(articulation.get("usd_prim_path") or ""),
            selected_paths=selected_receptacle_paths,
            index_paths=receptacle_paths,
        )


def _assert_semantic_pose_event_paths(
    state: dict[str, Any],
    *,
    selected_object_paths: dict[str, str],
    selected_receptacle_paths: dict[str, str],
    object_paths: dict[str, str],
    receptacle_paths: dict[str, str],
) -> None:
    events = state.get("transform_events") or []
    assert isinstance(events, list), state
    for event in events:
        assert isinstance(event, dict), event
        object_id = str(event.get("object_id") or "")
        if object_id:
            _assert_semantic_usd_path_matches_scene_index(
                "semantic pose event object",
                public_id=object_id,
                usd_prim_path=str(event.get("object_usd_prim_path") or ""),
                selected_paths=selected_object_paths,
                index_paths=object_paths,
            )
        receptacle_id = str(event.get("receptacle_id") or "")
        if receptacle_id:
            _assert_semantic_usd_path_matches_scene_index(
                "semantic pose event receptacle",
                public_id=receptacle_id,
                usd_prim_path=str(event.get("receptacle_usd_prim_path") or ""),
                selected_paths=selected_receptacle_paths,
                index_paths=receptacle_paths,
            )


def _selected_binding_usd_prim_paths(
    scene_bindings: dict[str, Any],
    bindings_key: str,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    bindings = scene_bindings.get(bindings_key) or {}
    assert isinstance(bindings, dict), scene_bindings
    for public_id, binding in bindings.items():
        assert isinstance(binding, dict), (bindings_key, public_id, binding)
        if binding.get("status") != "bound":
            continue
        paths[str(public_id)] = str(binding.get("usd_prim_path") or "")
    return paths


def _index_usd_prim_paths(index: dict[str, Any]) -> dict[str, str]:
    assert isinstance(index, dict) and index, index
    paths: dict[str, str] = {}
    for handle, row in index.items():
        assert isinstance(row, dict), (handle, row)
        usd_prim_path = str(row.get("usd_prim_path") or "")
        assert usd_prim_path, (handle, row)
        paths[str(handle)] = usd_prim_path
    return paths


def _assert_semantic_usd_path_matches_scene_index(
    label: str,
    *,
    public_id: str,
    usd_prim_path: str,
    selected_paths: dict[str, str],
    index_paths: dict[str, str],
) -> None:
    selected_path = selected_paths.get(public_id)
    if selected_path is not None:
        assert usd_prim_path == selected_path, (label, public_id, usd_prim_path, selected_path)
    indexed_path = index_paths.get(public_id)
    if indexed_path:
        assert usd_prim_path == indexed_path, (label, public_id, usd_prim_path, indexed_path)
        return
    if not usd_prim_path:
        return
    assert usd_prim_path in index_paths.values(), (
        label,
        public_id,
        usd_prim_path,
        index_paths,
    )


def _assert_isaac_semantic_pose_report_rows(
    state: dict[str, Any],
    report_text: str,
) -> None:
    for expected in (
        "Object USD",
        "Support USD",
        "USD prim",
        "Mutation",
        "Receptacle USD",
    ):
        assert expected in report_text, (expected, report_text[:1000])

    object_poses = state.get("object_poses") or {}
    assert isinstance(object_poses, dict), state
    for object_id, pose in object_poses.items():
        assert isinstance(pose, dict), (object_id, pose)
        _assert_report_text_values(
            report_text,
            str(object_id),
            str(pose.get("support_receptacle_id") or ""),
            str(pose.get("usd_prim_path") or ""),
            str(pose.get("support_usd_prim_path") or ""),
        )

    articulations = state.get("articulations") or {}
    assert isinstance(articulations, dict), state
    for receptacle_id, articulation in articulations.items():
        assert isinstance(articulation, dict), (receptacle_id, articulation)
        _assert_report_text_values(
            report_text,
            str(receptacle_id),
            str(articulation.get("usd_prim_path") or ""),
        )

    events = state.get("transform_events") or []
    assert isinstance(events, list), state
    for event in events:
        assert isinstance(event, dict), event
        _assert_report_text_values(
            report_text,
            str(event.get("tool") or ""),
            str(event.get("state_mutation") or ""),
            str(event.get("object_id") or ""),
            str(event.get("receptacle_id") or ""),
            str(event.get("object_usd_prim_path") or ""),
            str(event.get("receptacle_usd_prim_path") or ""),
        )


def _assert_report_text_values(report_text: str, *values: str) -> None:
    for value in values:
        if value:
            assert value in report_text, (value, report_text[:1000])


def _assert_isaac_semantic_pose_trace(
    data: dict[str, Any],
    base: Path,
    state: dict[str, Any],
) -> None:
    artifacts = data.get("artifacts") or {}
    trace_path = _resolve_path(base, artifacts.get("trace", ""))
    assert trace_path.is_file(), (trace_path, data)
    trace_responses = [
        event.get("response")
        for event in _trace_events_from_path(trace_path)
        if event.get("event") == "response" and isinstance(event.get("response"), dict)
    ]
    successful_pose_responses = [
        response
        for response in trace_responses
        if response.get("tool") in _ISAAC_SEMANTIC_POSE_TRACE_TOOLS and response.get("ok") is True
    ]
    assert successful_pose_responses, trace_path
    trace_tools = {str(response.get("tool") or "") for response in successful_pose_responses}
    assert "pick" in trace_tools, (trace_path, trace_tools)
    assert trace_tools & {"place", "place_inside"}, (trace_path, trace_tools)

    state_events = state.get("transform_events") or []
    assert isinstance(state_events, list), state
    state_tools = {
        str(event.get("tool") or "")
        for event in state_events
        if isinstance(event, dict) and event.get("tool") in _ISAAC_SEMANTIC_POSE_TRACE_TOOLS
    }
    assert state_tools <= trace_tools, (state_tools, trace_tools, trace_path)
    for response in successful_pose_responses:
        assert response.get("primitive_provenance") == ISAAC_SEMANTIC_POSE_PROVENANCE, response
        assert str(response.get("state_mutation") or "").startswith("isaac_"), response
        assert response.get("planner_backed") is not True, response
        assert response.get("physical_robot") is not True, response


def _trace_events_from_path(trace_path: Path) -> list[dict[str, Any]]:
    return read_jsonl_objects(trace_path, label="Isaac semantic-pose trace")


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    repo_path = Path(__file__).resolve().parents[2] / path
    if repo_path.exists():
        return repo_path
    return base / path


_ISAAC_SEMANTIC_POSE_TRACE_TOOLS = frozenset(ATOMIC_CLEANUP_TOOL_NAMES)
