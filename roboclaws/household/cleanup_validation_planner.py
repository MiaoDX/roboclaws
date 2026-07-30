#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.cleanup_primitive_evidence import (
    validate_cleanup_primitive_evidence,
)
from roboclaws.household.cleanup_validation_run import _is_map_build
from roboclaws.household.cleanup_validation_support import (
    agent_view_runtime_metric_map as _agent_view_runtime_metric_map,
)
from roboclaws.household.cleanup_validation_support import (
    resolve_path as _resolve_path,
)
from roboclaws.household.cleanup_validation_waypoints import (
    assert_waypoint_honesty,
    post_place_observe_count_allowing_public_state_queries,
)
from roboclaws.household.household_runtime_contract import (
    REAL_ROBOT_MAP_BUNDLE_SCHEMA,
    REAL_ROBOT_READINESS_SCHEMA,
)
from roboclaws.household.household_runtime_contract import (
    RUNTIME_METRIC_MAP_SCHEMA as RUNTIME_METRIC_MAP_SCHEMA,
)
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.planner_cleanup_bridge import (
    validate_planner_cleanup_bridge_evidence,
)
from roboclaws.household.planner_proof_attachment import (
    validate_planner_proof_attachment,
)
from roboclaws.household.planner_proof_bundle import (
    PLANNER_PROOF_BUNDLE_SCHEMA,
    planner_proof_attachments,
    validate_planner_proof_bundle,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    validate_planner_proof_quality_evidence,
)
from roboclaws.household.planner_proof_requests import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.semantic_timeline import (
    CANONICAL_SURFACE_CLEANUP_PHASES,
    CLOSE_RECEPTACLE_PHASE,
    FOCUSED_SEMANTIC_ACTION_PREFIXES,
    NAVIGATE_TO_VISUAL_CANDIDATE_TOOL,
    OPEN_RECEPTACLE_PHASE,
    PLACE_INSIDE_PHASE,
    annotate_focus_visual_grounding,
)
from roboclaws.maps.route import SIM_COSTMAP_PLANNER


def _assert_planner_proof_attachment(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_quality: bool = False,
    min_steps_executed: int | None = None,
) -> None:
    assert data.get("primitive_provenance") in {
        API_SEMANTIC_PROVENANCE,
        "planner_backed",
    }, data
    evidence = data.get("manipulation_evidence") or {}
    assert evidence.get("primitive_provenance") in {
        API_SEMANTIC_PROVENANCE,
        "planner_backed",
    }, evidence
    attachment = data.get("planner_backed_manipulation_proof") or {}
    if attachment.get("schema") == PLANNER_PROOF_BUNDLE_SCHEMA:
        validate_planner_proof_bundle(attachment)
        proof_attachments = planner_proof_attachments(attachment)
        assert "Attached Planner-Backed Proofs" in report_text, report_text[:500]
    else:
        validate_planner_proof_attachment(attachment)
        proof_attachments = [attachment]
        assert "Attached Planner-Backed Proof" in report_text, report_text[:500]
    for proof in proof_attachments:
        quality = planner_proof_quality_evidence(proof)
        validate_planner_proof_quality_evidence(
            quality,
            min_steps_executed=min_steps_executed or 1,
        )
        if require_quality:
            assert "Proof Quality" in report_text, report_text[:500]
            assert str(quality.get("quality_tier") or "") in report_text, report_text[:500]
        for value in (proof.get("image_artifacts") or {}).values():
            path = _resolve_path(base, str(value))
            assert path.is_file(), path
            assert path.stat().st_size > 0, path
    assert "Planner Initial" in report_text, report_text[:500]
    assert "Planner Final" in report_text, report_text[:500]
    if attachment.get("schema") != PLANNER_PROOF_BUNDLE_SCHEMA:
        assert "Cleanup object moves" in report_text, report_text[:500]


def _assert_cleanup_primitive_gate(
    data: dict[str, Any],
    report_text: str,
    *,
    accept_blocked: bool = False,
    require_planner_backed: bool = False,
) -> None:
    evidence = data.get("cleanup_primitive_evidence") or {}
    validate_cleanup_primitive_evidence(
        evidence,
        accept_blocked_capability=accept_blocked,
        require_planner_backed=require_planner_backed,
    )
    assert "Cleanup Primitive Gate" in report_text, report_text[:500]
    assert "Display subphase" in report_text, report_text[:500]
    assert "Subphase role" in report_text, report_text[:500]
    if require_planner_backed:
        assert data.get("primitive_provenance") != API_SEMANTIC_PROVENANCE, data


def _assert_bound_planner_cleanup_objects(
    data: dict[str, Any],
    report_text: str,
    specs: list[str],
) -> None:
    assert data.get("planner_proof_cleanup_executor_enabled") is True, data
    evidence = data.get("cleanup_primitive_evidence") or {}
    assert evidence.get("schema") == "planner_backed_cleanup_primitives_v1", evidence
    objects = evidence.get("objects") or []
    assert objects, evidence
    for spec in specs:
        object_id, target_receptacle_id = _parse_bound_object_spec(spec)
        row = next(
            (
                item
                for item in objects
                if item.get("object_id") == object_id
                and item.get("target_receptacle_id") == target_receptacle_id
            ),
            None,
        )
        assert row is not None, (spec, objects)
        assert row.get("planner_backed") is True, row
        assert row.get("strict_proof_eligible") is True, row
        subphases = row.get("subphases") or []
        assert subphases, row
        required_phases = _required_bound_cleanup_phases(subphases)
        assert required_phases <= {str(step.get("phase") or "") for step in subphases}, row
        for step in subphases:
            assert step.get("primitive_provenance") == "planner_backed", step
            assert step.get("planner_backed") is True, step
            assert step.get("strict_proof_eligible") is True, step
            assert step.get("status") == "ok", step
            assert step.get("object_id_matches") is True, step
            assert step.get("target_receptacle_id_matches") is True, step
        assert object_id in report_text, report_text[:500]
        assert target_receptacle_id in report_text, report_text[:500]
        assert "planner_backed" in report_text, report_text[:500]


def _required_bound_cleanup_phases(subphases: list[dict[str, Any]]) -> set[str]:
    phases = {str(step.get("phase") or "") for step in subphases}
    required = set(CANONICAL_SURFACE_CLEANUP_PHASES)
    if PLACE_INSIDE_PHASE in phases:
        required = required - {"place"} | {PLACE_INSIDE_PHASE}
    return required | (phases & {OPEN_RECEPTACLE_PHASE, CLOSE_RECEPTACLE_PHASE})


def _assert_mixed_planner_cleanup_primitives(
    data: dict[str, Any],
    report_text: str,
) -> None:
    evidence = data.get("cleanup_primitive_evidence") or {}
    assert evidence.get("status") == "blocked_capability", evidence
    assert evidence.get("planner_backed") is False, evidence
    assert data.get("primitive_provenance") == API_SEMANTIC_PROVENANCE, data
    objects = evidence.get("objects") or []
    assert any(item.get("planner_backed") is True for item in objects), objects
    assert any(item.get("planner_backed") is False for item in objects), objects
    summary = evidence.get("primitive_provenance_summary") or {}
    assert int(summary.get("planner_backed") or 0) >= 1, summary
    assert int(summary.get(API_SEMANTIC_PROVENANCE) or 0) >= 1, summary
    blockers = evidence.get("blockers") or []
    assert any(
        blocker.get("code") == "cleanup_subphase_not_planner_backed" for blocker in blockers
    ), blockers
    assert "Cleanup Primitive Gate" in report_text, report_text[:500]
    assert "blocked_capability" in report_text, report_text[:500]


def _parse_bound_object_spec(spec: str) -> tuple[str, str]:
    object_id, sep, target_receptacle_id = spec.partition(":")
    assert sep and object_id and target_receptacle_id, spec
    return object_id, target_receptacle_id


def _assert_planner_cleanup_bridge(
    data: dict[str, Any],
    report_text: str,
    *,
    accept_blocked: bool = False,
    require_ready: bool = False,
) -> None:
    evidence = data.get("planner_cleanup_bridge_evidence") or {}
    validate_planner_cleanup_bridge_evidence(
        evidence,
        accept_blocked_capability=accept_blocked,
        require_ready=require_ready,
    )
    assert "Planner Cleanup Bridge" in report_text, report_text[:500]
    if require_ready:
        assert data.get("primitive_provenance") != API_SEMANTIC_PROVENANCE, data


def _assert_waypoint_honesty(data: dict[str, Any], report_text: str) -> None:
    assert_waypoint_honesty(
        data,
        report_text,
        open_ended_intent=_is_open_ended_intent(data),
        map_build=_is_map_build(data),
    )


def _is_open_ended_intent(data: dict[str, Any]) -> bool:
    goal_contract = data.get("goal_contract") if isinstance(data.get("goal_contract"), dict) else {}
    intent = str(data.get("task_intent") or goal_contract.get("intent") or "").strip()
    return intent == "open-ended"


def _post_place_observe_count_allowing_public_state_queries(trace: dict[str, Any]) -> int:
    return post_place_observe_count_allowing_public_state_queries(trace)


def _assert_real_robot_alignment(data: dict[str, Any], base: Path, report_text: str) -> None:
    agent_view = data.get("agent_view") or {}
    metric_map = agent_view_module.base_metric_map(agent_view)
    runtime_metric_map = data.get("runtime_metric_map") or _agent_view_runtime_metric_map(
        agent_view
    )
    static_map = runtime_metric_map.get("static_map") or {}
    assert metric_map.get("schema") == REAL_ROBOT_MAP_BUNDLE_SCHEMA, metric_map
    for key in (
        "frame_id",
        "map_id",
        "map_version",
        "resolution_m",
        "origin",
        "width",
        "height",
        "occupancy_values",
        "map_bundle",
        "robot_pose",
    ):
        assert key in metric_map, metric_map
    map_bundle_metadata = metric_map.get("map_bundle") or {}
    assert map_bundle_metadata.get("schema") == "nav2_map_bundle_v1", map_bundle_metadata
    assert map_bundle_metadata.get("robot_profile_id") == "rby1m", map_bundle_metadata
    assert map_bundle_metadata.get("parameter_hash"), map_bundle_metadata
    waypoints = metric_map.get("inspection_waypoints") or []
    assert waypoints, metric_map
    for waypoint in waypoints:
        for key in ("frame_id", "x", "y", "yaw", "room_id", "label", "visited", "purpose"):
            assert key in waypoint, waypoint
    assert static_map.get("contains_runtime_observations") is False, static_map
    assert "observations" not in static_map, static_map
    for fixture in static_map.get("fixtures") or []:
        assert fixture.get("fixture_id"), fixture
        assert fixture.get("affordances"), fixture
        assert fixture.get("pose", {}).get("frame_id") == "map", fixture
        assert "observed_objects" not in fixture, fixture
    policy_view = agent_view_module.policy_view(agent_view)
    assert policy_view.get("chase_camera_policy_input") is False, policy_view
    assert not any("chase" in str(item).lower() for item in policy_view.get("allowed_inputs", []))
    readiness = data.get("real_robot_readiness") or {}
    assert readiness.get("schema") == REAL_ROBOT_READINESS_SCHEMA, readiness
    assert readiness.get("map_bundle_fields_present") is True, readiness
    assert readiness.get("pose_stamped_waypoints") is True, readiness
    assert readiness.get("public_static_map") is True, readiness
    assert readiness.get("static_fixture_projection") is False, readiness
    assert readiness.get("policy_view_chase_excluded") is True, readiness
    assert readiness.get("semantic_navigation_only") is True, readiness
    assert readiness.get("sim_costmap_route_validation") is True, readiness
    assert readiness.get("real_robot_ready") is False, readiness
    assert readiness.get("physical_navigation_pilot") is False, readiness
    assert readiness.get("physical_cleanup_ready") is False, readiness
    assert readiness.get("map_bundle_snapshot_present") is True, readiness
    assert readiness.get("map_bundle_parameter_hash"), readiness
    assert readiness.get("navigation_backend_summary", {}).get(SIM_COSTMAP_PLANNER), readiness
    nav2_bundle = data.get("nav2_map_bundle") or {}
    assert nav2_bundle.get("schema") == "nav2_map_bundle_snapshot_v1", nav2_bundle
    assert nav2_bundle.get("snapshot_complete") is True, nav2_bundle
    artifact_paths = nav2_bundle.get("artifact_paths") or {}
    artifact_hashes = nav2_bundle.get("artifact_hashes") or {}
    for key in (
        "map_yaml",
        "occupancy_image",
        "semantics_json",
        "robot_profile",
        "costmap_params",
        "preview_png",
    ):
        assert key in artifact_paths, nav2_bundle
        assert key in artifact_hashes, nav2_bundle
        assert len(str(artifact_hashes[key])) == 64, artifact_hashes
        assert _resolve_path(base, str(artifact_paths[key])).is_file(), artifact_paths[key]
    assert "Real-Robot Readiness" in report_text, report_text[:500]
    assert "Nav2 Map Bundle" in report_text, report_text[:500]
    assert "map_bundle/map.yaml" in report_text, report_text[:500]
    assert "report_only_simulation_view" in report_text, report_text[:500]


def _assert_b1_robot_consumption_proof(data: dict[str, Any], base: Path) -> None:
    nav2_bundle = data.get("nav2_map_bundle") or {}
    assert nav2_bundle.get("schema") == "nav2_map_bundle_snapshot_v1", nav2_bundle
    assert nav2_bundle.get("snapshot_complete") is True, nav2_bundle
    artifact_paths = nav2_bundle.get("artifact_paths") or {}
    artifact_hashes = nav2_bundle.get("artifact_hashes") or {}
    semantics_path = _resolve_path(base, str(artifact_paths.get("semantics_json") or ""))
    assert len(str(artifact_hashes.get("semantics_json") or "")) == 64, artifact_hashes
    semantics = read_json_object(semantics_path, label="B1 Nav2 semantics")
    assert semantics.get("schema") == "nav2_cleanup_semantics_v1", semantics
    assert semantics.get("environment_id") == "agibot-robot-map-12", semantics
    assert (semantics.get("spatial_contract") or {}).get("alignment_status") == "verified", (
        semantics.get("spatial_contract") or {}
    )
    proof = (
        (semantics.get("digital_twin_capabilities") or {}).get("robot_consumption_proof")
    ) or {}
    assert proof.get("schema") == "b1_map12_robot_consumption_proof_v1", proof
    assert proof.get("status") == "robot_navigation_verified", proof
    assert proof.get("alignment_status") == "verified", proof
    assert proof.get("navigation_status") == "verified", proof
    assert proof.get("robot_navigation_supported") is True, proof
    assert proof.get("robot_navigation_provenance") == "isaac_b1_map12_navigation_smoke", proof
    assert int(proof.get("navigation_waypoint_count") or 0) >= 1, proof
    assert proof.get("alignment_artifact"), proof
    assert proof.get("navigation_artifact"), proof
    assert proof.get("physical_robot") is False, proof
    assert proof.get("manipulation_supported") is False, proof
    _assert_b1_robot_consumption_manifest(base, proof)


def _assert_b1_robot_consumption_manifest(base: Path, proof: dict[str, Any]) -> None:
    manifest_path = base / "b1_robot_consumption_manifest.json"
    manifest = read_json_object(manifest_path, label="B1 robot consumption manifest")
    assert manifest.get("schema") == "b1_map12_robot_consumption_manifest_v1", manifest
    assert manifest.get("status") == "robot_navigation_ready", manifest
    navigation = manifest.get("navigation") if isinstance(manifest.get("navigation"), dict) else {}
    assert navigation.get("ready") is True, navigation
    assert navigation.get("status") == proof.get("status"), navigation
    assert navigation.get("alignment_status") == proof.get("alignment_status"), navigation
    assert navigation.get("navigation_status") == proof.get("navigation_status"), navigation
    assert navigation.get("alignment_artifact") == proof.get("alignment_artifact"), navigation
    assert navigation.get("navigation_artifact") == proof.get("navigation_artifact"), navigation
    assert navigation.get("robot_navigation_provenance") == proof.get(
        "robot_navigation_provenance"
    ), navigation
    assert int(navigation.get("navigation_waypoint_count") or 0) == int(
        proof.get("navigation_waypoint_count") or 0
    ), navigation
    capabilities = (
        manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}
    )
    assert capabilities.get("robot_navigation") is True, capabilities
    assert capabilities.get("manipulation") is False, capabilities
    semantics = manifest.get("semantics") if isinstance(manifest.get("semantics"), dict) else {}
    assert semantics.get("object_projection_status") == "blocked_until_object_semantic_anchors", (
        semantics
    )
    policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
    assert policy.get("no_output_directory_autodiscovery") is True, policy
    assert policy.get("object_labels_are_not_inferred_from_room_anchors") is True, policy


def _has_planner_proof_requests(data: dict[str, Any]) -> bool:
    artifacts = data.get("artifacts") or {}
    return bool(data.get("planner_proof_requests") or artifacts.get("planner_proof_requests"))


def _assert_planner_proof_requests(data: dict[str, Any], base: Path, report_text: str) -> None:
    artifacts = data.get("artifacts") or {}
    manifest = data.get("planner_proof_requests")
    if manifest is None and artifacts.get("planner_proof_requests"):
        path = _resolve_path(base, str(artifacts["planner_proof_requests"]))
        manifest = read_json_object(path, label="planner proof requests")
    if manifest is None:
        return
    assert "Planner Proof Requests" in report_text, report_text[:500]
    assert manifest.get("schema") == PLANNER_PROOF_REQUESTS_SCHEMA, manifest
    assert manifest.get("agent_view_exposed") is False, manifest
    requests = manifest.get("requests") or []
    assert manifest.get("request_count") == len(requests), manifest
    semantic_substeps = data.get("semantic_substeps") or []
    if semantic_substeps:
        assert len(requests) == len(semantic_substeps), manifest
    for request in requests:
        assert request.get("object_id"), request
        if request.get("ready") is False:
            assert request.get("blockers"), request
        else:
            assert request.get("target_receptacle_id"), request
        assert "planner_probe_args" in request, request
    assert "planner_proof_requests" not in data.get("agent_view", {}), data.get("agent_view")


def _is_focused_robot_action(action: str) -> bool:
    return action.startswith(
        (
            "navigate_to_waypoint ",
            "observe ",
            f"{NAVIGATE_TO_VISUAL_CANDIDATE_TOOL} ",
            *FOCUSED_SEMANTIC_ACTION_PREFIXES,
        )
    )


def _canonical_robot_view_phase(step: dict[str, Any], action: str) -> str:
    semantic_phase = step.get("semantic_phase")
    if isinstance(semantic_phase, str) and semantic_phase:
        return semantic_phase
    action_evidence = step.get("action_evidence")
    if isinstance(action_evidence, dict):
        backend_primitive = action_evidence.get("backend_primitive")
        if isinstance(backend_primitive, str) and backend_primitive:
            return backend_primitive
    return action.split(" ", 1)[0]


def _assert_focused_robot_step(step: dict[str, Any]) -> None:
    focus = annotate_focus_visual_grounding(step.get("focus") or {}) or {}
    assert focus.get("has_focus") is True, step
    if _has_reviewable_source_fpv_action_evidence(step):
        return
    fpv_visibility = focus.get("fpv_visibility") or {}
    verify_visibility = focus.get("visibility") or {}
    visibility_states = [
        _focus_visibility_grounding_state(fpv_visibility, focus, step),
        _focus_visibility_grounding_state(verify_visibility, focus, step),
    ]
    if _has_reviewable_place_surface_evidence(step, focus):
        return
    assert any(state == "grounded" for state in visibility_states) or all(
        state == "unavailable" for state in visibility_states
    ), step


def _has_reviewable_source_fpv_action_evidence(step: dict[str, Any]) -> bool:
    action_evidence = step.get("action_evidence")
    if not isinstance(action_evidence, dict):
        return False
    if action_evidence.get("backend_primitive") != "navigate_to_object":
        return False
    if action_evidence.get("candidate_state") != "navigation_authorized":
        return False
    if action_evidence.get("reviewability_status") != "reviewable":
        return False
    if action_evidence.get("locality_status") != "same_waypoint_source_observation":
        return False
    if not action_evidence.get("source_observation_id"):
        return False
    bbox = action_evidence.get("source_image_bbox")
    return isinstance(bbox, list) and len(bbox) == 4


def _has_reviewable_place_surface_evidence(
    step: dict[str, Any],
    focus: dict[str, Any],
) -> bool:
    if step.get("semantic_phase") not in {"place", "place_inside"}:
        return False
    if not (focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")):
        return False
    if not (
        focus.get("receptacle_id")
        or focus.get("receptacle_body_name")
        or focus.get("receptacle_label")
    ):
        return False
    if not (focus.get("object_location_relation") or focus.get("object_contained_in")):
        return False
    visibilities = [focus.get("fpv_visibility") or {}, focus.get("visibility") or {}]
    return any(
        visibility.get("status") == "weak_object_visibility"
        and int(visibility.get("receptacle_pixels") or 0) > 0
        for visibility in visibilities
    )


def _focus_visibility_grounding_state(
    visibility: dict[str, Any],
    focus: dict[str, Any],
    step: dict[str, Any],
) -> str:
    status = visibility.get("status")
    assert status in {
        "ok",
        "contained_inside",
        "segmentation_unavailable",
        "weak_object_visibility",
    }, step
    if status == "segmentation_unavailable":
        return "unavailable"
    if status == "contained_inside":
        return "grounded"
    if status == "weak_object_visibility":
        return "weak"
    has_object_focus = bool(
        focus.get("object_id") or focus.get("object_body_name") or focus.get("object_label")
    )
    if status == "ok" and "object_pixels" in visibility and has_object_focus:
        assert int(visibility.get("object_pixels") or 0) > 0, step
    return "grounded"
