from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from roboclaws.mcp import profiles as mcp_profiles

AGENT_VIEW_SCHEMA = "agent_view_v2"
SECTION_METADATA_SCHEMA = "agent_view_section_metadata_v1"
PRIVACY_SCHEMA = "agent_view_privacy_v1"

SECTION_TASK = "task"
SECTION_CAPABILITIES = "capabilities"
SECTION_BASE_METRIC_MAP = "base_metric_map"
SECTION_RUNTIME_METRIC_MAP = "runtime_metric_map"
SECTION_ACTIVE_PERCEPTION = "active_perception"
SECTION_POLICY_VIEW = "policy_view"
SECTION_READINESS = "readiness"
SECTION_PRIVACY = "privacy"

_SECTION_NAMES = (
    SECTION_TASK,
    SECTION_CAPABILITIES,
    SECTION_BASE_METRIC_MAP,
    SECTION_RUNTIME_METRIC_MAP,
    SECTION_ACTIVE_PERCEPTION,
    SECTION_POLICY_VIEW,
    SECTION_READINESS,
    SECTION_PRIVACY,
)


def build_agent_view(
    *,
    contract: str,
    perception_mode: str,
    detection_exposure_policy: str,
    structured_detections_available: bool,
    base_metric_map: dict[str, Any],
    runtime_metric_map: dict[str, Any],
    observed_objects: Iterable[dict[str, Any]],
    raw_fpv_observations: Iterable[dict[str, Any]],
    camera_model_policy_evidence: dict[str, Any],
    model_declared_observations: Iterable[dict[str, Any]],
    model_declared_observation_evidence: dict[str, Any],
    policy_view: dict[str, Any],
    cleanup_worklist: dict[str, Any],
    observed_waypoint_ids: Iterable[str],
    public_tool_names: Iterable[str],
    forbidden_keys: frozenset[str],
    public_acceptance_config: dict[str, Any] | None = None,
    blocked_capabilities: Iterable[str] = (),
    capability_profiles: Iterable[str] = (),
) -> dict[str, Any]:
    active_perception_payload = _active_perception_payload(
        perception_mode=perception_mode,
        detection_exposure_policy=detection_exposure_policy,
        structured_detections_available=structured_detections_available,
        observed_objects=observed_objects,
        raw_fpv_observations=raw_fpv_observations,
        camera_model_policy_evidence=camera_model_policy_evidence,
        model_declared_observations=model_declared_observations,
        model_declared_observation_evidence=model_declared_observation_evidence,
    )
    capability_payload = _capabilities_payload(
        public_tool_names=public_tool_names,
        capability_profiles=capability_profiles,
        blocked_capabilities=blocked_capabilities,
    )
    payload = {
        "schema": AGENT_VIEW_SCHEMA,
        "contract": contract,
        "section_metadata": _section_metadata(),
        SECTION_TASK: {
            "contract": contract,
            "perception_mode": perception_mode,
            "detection_exposure_policy": detection_exposure_policy,
            "structured_detections_available": bool(structured_detections_available),
            "public_acceptance_config": dict(public_acceptance_config or {}),
        },
        SECTION_CAPABILITIES: capability_payload,
        SECTION_BASE_METRIC_MAP: copy.deepcopy(base_metric_map),
        SECTION_RUNTIME_METRIC_MAP: copy.deepcopy(runtime_metric_map),
        SECTION_ACTIVE_PERCEPTION: active_perception_payload,
        SECTION_POLICY_VIEW: copy.deepcopy(policy_view),
        SECTION_READINESS: {
            "cleanup_worklist": copy.deepcopy(cleanup_worklist),
            "observed_waypoint_ids": sorted(str(item) for item in observed_waypoint_ids),
        },
        SECTION_PRIVACY: {
            "schema": PRIVACY_SCHEMA,
            "forbidden_private_fields_absent": True,
            "private_truth_included": False,
            "forbidden_private_field_policy": "agent_view_forbidden_keys_v1",
            "forbidden_private_field_names": sorted(forbidden_keys),
            "excluded_report_only_views": list(
                (policy_view.get("excluded_report_only_views") or [])
                if isinstance(policy_view, dict)
                else []
            ),
        },
    }
    assert_no_private_fields(payload, forbidden_keys)
    return payload


def _capabilities_payload(
    *,
    public_tool_names: Iterable[str],
    capability_profiles: Iterable[str],
    blocked_capabilities: Iterable[str],
) -> dict[str, Any]:
    profile_ids = [mcp_profiles.normalize_profile_id(str(item)) for item in capability_profiles]
    actual_public_tools = _ordered_unique(str(item) for item in public_tool_names)
    if not profile_ids:
        profile_ids = _infer_capability_profiles(actual_public_tools)
    profile_metadata = [
        mcp_profiles.contract_profile_metadata(profile_id) for profile_id in profile_ids
    ]
    expected_by_profile = {
        profile_id: list(mcp_profiles.contract_profile(profile_id).public_tool_names())
        for profile_id in profile_ids
    }
    expected_public_tools = _ordered_unique(
        name for names in expected_by_profile.values() for name in names
    )
    blocked = [str(item) for item in blocked_capabilities]
    blocked_set = set(blocked)
    tool_descriptors = []
    for tool_name in actual_public_tools:
        descriptor = _tool_descriptor_from_profiles(tool_name, profile_metadata)
        if descriptor:
            descriptor["registration_status"] = "registered"
            descriptor["blocked_status"] = (
                "blocked_capability" if tool_name in blocked_set else "available"
            )
            tool_descriptors.append(descriptor)
        else:
            tool_descriptors.append(
                {
                    "name": tool_name,
                    "semantic_name": tool_name,
                    "family": "",
                    "classification": "runtime_registered",
                    "provenance": [],
                    "summary": "",
                    "source_profile_id": "",
                    "registration_status": "registered_extra",
                    "blocked_status": "blocked_capability"
                    if tool_name in blocked_set
                    else "available",
                }
            )
    return {
        "schema": "agent_view_capabilities_v1",
        "public_tool_names": actual_public_tools,
        "capability_profiles": profile_ids,
        "profile_metadata": profile_metadata,
        "profile_public_tool_names": expected_public_tools,
        "profile_public_tool_names_by_profile": expected_by_profile,
        "runtime_extra_public_tool_names": [
            name for name in actual_public_tools if name not in set(expected_public_tools)
        ],
        "blocked_capabilities": blocked,
        "blocked_capability_details": [
            _blocked_capability_detail(name, profile_metadata) for name in blocked
        ],
        "public_tool_descriptors": tool_descriptors,
        "source": "mcp_profile_metadata_and_runtime_tool_registration",
        "private_truth_included": False,
    }


def _tool_descriptor_from_profiles(
    tool_name: str,
    profile_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    for profile in profile_metadata:
        for tool in profile.get("public_tools") or []:
            if str(tool.get("name") or "") == tool_name:
                return {**copy.deepcopy(tool), "source_profile_id": profile.get("profile_id", "")}
    return {}


def _blocked_capability_detail(
    tool_name: str,
    profile_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    descriptor = _tool_descriptor_from_profiles(tool_name, profile_metadata)
    if descriptor:
        return {
            "name": tool_name,
            "semantic_name": descriptor.get("semantic_name", tool_name),
            "family": descriptor.get("family", ""),
            "source_profile_id": descriptor.get("source_profile_id", ""),
            "status": "blocked_capability",
        }
    return {
        "name": tool_name,
        "semantic_name": tool_name,
        "family": "",
        "source_profile_id": "",
        "status": "blocked_capability",
    }


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _infer_capability_profiles(public_tool_names: list[str]) -> list[str]:
    if not public_tool_names:
        return []
    public_tool_set = set(public_tool_names)
    return [
        profile_id
        for profile_id in mcp_profiles.contract_profile_names()
        if public_tool_set.intersection(
            mcp_profiles.contract_profile(profile_id).public_tool_names()
        )
    ]


def _active_perception_payload(
    *,
    perception_mode: str,
    detection_exposure_policy: str,
    structured_detections_available: bool,
    observed_objects: Iterable[dict[str, Any]],
    raw_fpv_observations: Iterable[dict[str, Any]],
    camera_model_policy_evidence: dict[str, Any],
    model_declared_observations: Iterable[dict[str, Any]],
    model_declared_observation_evidence: dict[str, Any],
) -> dict[str, Any]:
    observed_rows = [copy.deepcopy(item) for item in observed_objects]
    raw_rows = [copy.deepcopy(item) for item in raw_fpv_observations]
    declared_rows = [copy.deepcopy(item) for item in model_declared_observations]
    camera_policy = copy.deepcopy(camera_model_policy_evidence)
    declared_evidence = copy.deepcopy(model_declared_observation_evidence)
    return {
        "perception_mode": perception_mode,
        "structured_detections_available": bool(structured_detections_available),
        "detection_exposure_policy": detection_exposure_policy,
        "observed_objects": observed_rows,
        "raw_fpv_observations": raw_rows,
        "raw_fpv_summary": _raw_fpv_summary(raw_rows),
        "camera_grounded_labels": _camera_grounded_labels_summary(camera_policy),
        "visual_candidate_lifecycle": _visual_candidate_lifecycle_summary(
            observed_rows,
            declared_rows,
        ),
        "camera_model_policy_evidence": camera_policy,
        "model_declared_observations": declared_rows,
        "model_declared_observation_evidence": declared_evidence,
    }


def _raw_fpv_summary(raw_observations: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    artifact_status_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for item in raw_observations:
        status = str(item.get("status") or "available")
        artifact_status = str(item.get("artifact_status") or "")
        source = str(
            item.get("source")
            or item.get("primitive_provenance")
            or item.get("perception_mode")
            or "robot_camera"
        )
        status_counts[status] = status_counts.get(status, 0) + 1
        if artifact_status:
            artifact_status_counts[artifact_status] = (
                artifact_status_counts.get(artifact_status, 0) + 1
            )
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "schema": "agent_view_raw_fpv_summary_v1",
        "observation_count": len(raw_observations),
        "status_counts": status_counts,
        "artifact_status_counts": artifact_status_counts,
        "source_counts": source_counts,
        "private_truth_included": False,
    }


def _camera_grounded_labels_summary(
    camera_model_policy_evidence: dict[str, Any],
) -> dict[str, Any]:
    events = list(camera_model_policy_evidence.get("events") or [])
    pipeline_ids = [
        str(item)
        for item in camera_model_policy_evidence.get("visual_grounding_pipeline_ids") or []
        if str(item)
    ]
    if not pipeline_ids:
        pipeline_id = str(camera_model_policy_evidence.get("visual_grounding_pipeline_id") or "")
        if pipeline_id:
            pipeline_ids = [pipeline_id]
    pipeline_status_counts: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    for event in events:
        pipeline = event.get("visual_grounding_pipeline") or {}
        status = str(pipeline.get("status") or "unknown")
        pipeline_status_counts[status] = pipeline_status_counts.get(status, 0) + 1
        reason = str(pipeline.get("failure_reason") or "")
        if reason:
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    failure_count = int(camera_model_policy_evidence.get("visual_grounding_failure_count") or 0)
    enabled = bool(camera_model_policy_evidence.get("enabled"))
    if not enabled:
        sidecar_status = "disabled"
    elif failure_count:
        sidecar_status = "failed"
    elif events:
        sidecar_status = "available"
    else:
        sidecar_status = "not_invoked"
    return {
        "schema": "agent_view_camera_grounded_labels_v1",
        "enabled": enabled,
        "model_provenance": str(camera_model_policy_evidence.get("model_provenance") or ""),
        "visual_grounding_pipeline_id": str(
            camera_model_policy_evidence.get("visual_grounding_pipeline_id") or ""
        ),
        "visual_grounding_pipeline_ids": sorted(set(pipeline_ids)),
        "sidecar_status": sidecar_status,
        "event_count": int(camera_model_policy_evidence.get("event_count") or len(events)),
        "candidate_count": int(camera_model_policy_evidence.get("candidate_count") or 0),
        "unresolved_count": int(camera_model_policy_evidence.get("unresolved_count") or 0),
        "failure_count": failure_count,
        "failure_reasons": failure_reasons,
        "pipeline_status_counts": pipeline_status_counts,
        "duplicate_rate": float(camera_model_policy_evidence.get("duplicate_rate") or 0.0),
        "private_truth_included": False,
    }


def _visual_candidate_lifecycle_summary(
    observed_objects: list[dict[str, Any]],
    model_declared_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_state_counts: dict[str, int] = {}
    actionability_status_counts: dict[str, int] = {}
    grounding_status_counts: dict[str, int] = {}
    for item in [*observed_objects, *model_declared_observations]:
        state = str(item.get("candidate_state") or "")
        actionability = str(item.get("actionability_status") or "")
        grounding = str(item.get("grounding_status") or "")
        if state:
            candidate_state_counts[state] = candidate_state_counts.get(state, 0) + 1
        if actionability:
            actionability_status_counts[actionability] = (
                actionability_status_counts.get(actionability, 0) + 1
            )
        if grounding:
            grounding_status_counts[grounding] = grounding_status_counts.get(grounding, 0) + 1
    return {
        "schema": "agent_view_visual_candidate_lifecycle_v1",
        "observed_object_count": len(observed_objects),
        "model_declared_observation_count": len(model_declared_observations),
        "candidate_state_counts": candidate_state_counts,
        "actionability_status_counts": actionability_status_counts,
        "grounding_status_counts": grounding_status_counts,
        "private_truth_included": False,
    }


def _section_metadata() -> dict[str, Any]:
    return {
        "schema": SECTION_METADATA_SCHEMA,
        SECTION_TASK: {
            "obtainability": "operator_or_public_run_config",
            "provenance": "surface_intent_and_public_acceptance_config",
        },
        SECTION_CAPABILITIES: {
            "obtainability": "public_capability_contract",
            "provenance": "mcp_tool_registration_and_capability_profiles",
        },
        SECTION_BASE_METRIC_MAP: {
            "obtainability": "real_robot_obtainable_public_evidence",
            "provenance": "base_metric_map",
        },
        SECTION_RUNTIME_METRIC_MAP: {
            "obtainability": "public_current_run_evidence",
            "provenance": "runtime_metric_map",
        },
        SECTION_ACTIVE_PERCEPTION: {
            "obtainability": "real_robot_obtainable_or_provenance_limited_public_evidence",
            "provenance": "robot_camera_and_detector_evidence",
        },
        SECTION_POLICY_VIEW: {
            "obtainability": "public_policy_boundary",
            "provenance": "agent_view_policy",
        },
        SECTION_READINESS: {
            "obtainability": "public_current_run_evidence",
            "provenance": "agent_view_and_public_trace_evidence",
        },
        SECTION_PRIVACY: {
            "obtainability": "contract_enforcement_evidence",
            "provenance": "agent_view_guard",
        },
    }


def require_agent_view(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AssertionError(f"Agent View must be a JSON object, got {type(payload).__name__}")
    if payload.get("schema") != AGENT_VIEW_SCHEMA:
        raise AssertionError(f"expected {AGENT_VIEW_SCHEMA}, got {payload.get('schema')!r}")
    for section_name in _SECTION_NAMES:
        if section_name not in payload:
            raise AssertionError(f"missing Agent View section {section_name!r}")
    return payload


def section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    require_agent_view(payload)
    value = payload.get(name)
    if not isinstance(value, dict):
        raise AssertionError(f"Agent View section {name!r} must be an object")
    return value


def task(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_TASK)


def capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_CAPABILITIES)


def base_metric_map(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_BASE_METRIC_MAP)


def base_metric_runtime_metric_map(payload: dict[str, Any]) -> dict[str, Any]:
    runtime_map = base_metric_map(payload).get("runtime_metric_map")
    return dict(runtime_map) if isinstance(runtime_map, dict) else {}


def runtime_metric_map(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_RUNTIME_METRIC_MAP)


def active_perception(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_ACTIVE_PERCEPTION)


def policy_view(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_POLICY_VIEW)


def readiness(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_READINESS)


def privacy(payload: dict[str, Any]) -> dict[str, Any]:
    return section(payload, SECTION_PRIVACY)


def public_tool_names(payload: dict[str, Any]) -> list[str]:
    return list(capabilities(payload).get("public_tool_names") or [])


def with_public_tool_names(
    payload: dict[str, Any],
    names: Iterable[str],
    *,
    capability_profiles: Iterable[str] | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(require_agent_view(payload))
    current = capabilities(updated)
    updated[SECTION_CAPABILITIES] = _capabilities_payload(
        public_tool_names=names,
        capability_profiles=(
            capability_profiles
            if capability_profiles is not None
            else current.get("capability_profiles") or ()
        ),
        blocked_capabilities=current.get("blocked_capabilities") or (),
    )
    return updated


def observed_objects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(active_perception(payload).get("observed_objects") or [])


def raw_fpv_observations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(active_perception(payload).get("raw_fpv_observations") or [])


def camera_model_policy_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(active_perception(payload).get("camera_model_policy_evidence") or {})


def model_declared_observations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(active_perception(payload).get("model_declared_observations") or [])


def model_declared_observation_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(active_perception(payload).get("model_declared_observation_evidence") or {})


def cleanup_worklist(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(readiness(payload).get("cleanup_worklist") or {})


def static_map(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(runtime_metric_map(payload).get("static_map") or {})


def static_map_fixtures(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(static_map(payload).get("fixtures") or [])


def observed_waypoint_ids(payload: dict[str, Any]) -> list[str]:
    return list(readiness(payload).get("observed_waypoint_ids") or [])


def perception_mode(payload: dict[str, Any]) -> str:
    return str(task(payload).get("perception_mode") or "")


def structured_detections_available(payload: dict[str, Any]) -> bool:
    return bool(task(payload).get("structured_detections_available"))


def detection_exposure_policy(payload: dict[str, Any]) -> str:
    return str(task(payload).get("detection_exposure_policy") or "")


def forbidden_private_fields_absent(payload: dict[str, Any]) -> bool:
    return privacy(payload).get("forbidden_private_fields_absent") is True


def assert_no_private_fields(payload: Any, forbidden_keys: frozenset[str]) -> None:
    if isinstance(payload, dict):
        forbidden = forbidden_keys.intersection(payload)
        if forbidden:
            raise AssertionError(f"forbidden agent-view keys present: {sorted(forbidden)}")
        for value in payload.values():
            assert_no_private_fields(value, forbidden_keys)
    elif isinstance(payload, list):
        for value in payload:
            assert_no_private_fields(value, forbidden_keys)


def strip_private_fields(payload: Any, forbidden_keys: frozenset[str]) -> Any:
    if isinstance(payload, dict):
        return {
            key: strip_private_fields(value, forbidden_keys)
            for key, value in payload.items()
            if key not in forbidden_keys
        }
    if isinstance(payload, list):
        return [strip_private_fields(value, forbidden_keys) for value in payload]
    return payload
