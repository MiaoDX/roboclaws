from __future__ import annotations

import json
from typing import Any

from roboclaws.household.planner_feasibility_contracts import (
    GRASP_FEASIBILITY_MITIGATION_DECISION_SCHEMA,
    GRASP_FEASIBILITY_SIGNATURE_SCHEMA,
)


def task_feasibility_blocker_kind(
    blockers: list[dict[str, Any]],
    task_sampler_failure_diagnostics: dict[str, Any],
) -> str:
    robot_placement_failures = int(
        task_sampler_failure_diagnostics.get("robot_placement_failure_count") or 0
    )
    grasp_failures = int(task_sampler_failure_diagnostics.get("grasp_failure_count") or 0)
    if robot_placement_failures:
        return "robot_placement"
    if grasp_failures:
        return "grasp_feasibility"
    codes = {str(item.get("code") or "") for item in blockers}
    if "HouseInvalidForTask" in codes:
        return "task_sampling"
    return ""


def task_feasibility_blocker_summary(
    blocker_kind: str,
    task_sampler_failure_diagnostics: dict[str, Any],
) -> str:
    if blocker_kind == "robot_placement":
        return (
            f"{int(task_sampler_failure_diagnostics.get('robot_placement_failure_count') or 0)} "
            "robot-placement failures"
        )
    if blocker_kind == "grasp_feasibility":
        grasp_load_failures = int(
            task_sampler_failure_diagnostics.get("grasp_load_failure_count") or 0
        )
        grasp_collision_checks = int(
            task_sampler_failure_diagnostics.get("grasp_collision_check_count") or 0
        )
        zero_noncolliding_checks = int(
            task_sampler_failure_diagnostics.get("zero_noncolliding_grasp_check_count") or 0
        )
        summary = (
            f"{int(task_sampler_failure_diagnostics.get('grasp_failure_count') or 0)} "
            "grasp failures; "
            f"{int(task_sampler_failure_diagnostics.get('candidate_removal_count') or 0)} "
            "candidate-removal calls"
        )
        if "candidate_effective_removal_count" in task_sampler_failure_diagnostics:
            effective_removals = int(
                task_sampler_failure_diagnostics.get("candidate_effective_removal_count") or 0
            )
            summary += f"; {effective_removals} effective removals"
        if "candidate_name_miss_count" in task_sampler_failure_diagnostics:
            name_misses = int(
                task_sampler_failure_diagnostics.get("candidate_name_miss_count") or 0
            )
            summary += f"; {name_misses} candidate-name misses"
        if grasp_load_failures:
            summary += f"; {grasp_load_failures} grasp-load failures"
            missing_assets = _grasp_load_exception_asset_uids(task_sampler_failure_diagnostics)
            if missing_assets:
                summary += f"; missing grasp cache: {', '.join(missing_assets)}"
        if grasp_collision_checks:
            summary += f"; {grasp_collision_checks} grasp collision checks"
        if zero_noncolliding_checks:
            summary += f"; {zero_noncolliding_checks} zero non-colliding checks"
        return summary
    return ""


def grasp_feasibility_signature(
    task_sampler_failure_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    grasp_failure_count = int(task_sampler_failure_diagnostics.get("grasp_failure_count") or 0)
    if not grasp_failure_count:
        return {}
    object_names = _unique_nonempty(
        str(item.get("object_name") or "")
        for item in task_sampler_failure_diagnostics.get("grasp_failures") or []
        if isinstance(item, dict)
    )
    signature = {
        "schema": GRASP_FEASIBILITY_SIGNATURE_SCHEMA,
        "kind": "grasp_feasibility",
        "subkind": _grasp_feasibility_subkind(task_sampler_failure_diagnostics),
        "pattern_key": _grasp_pattern_key(task_sampler_failure_diagnostics),
        "summary": task_feasibility_blocker_summary(
            "grasp_feasibility",
            task_sampler_failure_diagnostics,
        ),
        "grasp_failure_count": grasp_failure_count,
        "candidate_removal_count": int(
            task_sampler_failure_diagnostics.get("candidate_removal_count") or 0
        ),
        "robot_placement_attempt_count": int(
            task_sampler_failure_diagnostics.get("robot_placement_attempt_count") or 0
        ),
        "robot_placement_failure_count": int(
            task_sampler_failure_diagnostics.get("robot_placement_failure_count") or 0
        ),
        "place_robot_near_call_count": int(
            task_sampler_failure_diagnostics.get("place_robot_near_call_count") or 0
        ),
        "grasp_load_attempt_count": int(
            task_sampler_failure_diagnostics.get("grasp_load_attempt_count") or 0
        ),
        "grasp_load_failure_count": int(
            task_sampler_failure_diagnostics.get("grasp_load_failure_count") or 0
        ),
        "grasp_collision_check_count": int(
            task_sampler_failure_diagnostics.get("grasp_collision_check_count") or 0
        ),
        "zero_noncolliding_grasp_check_count": int(
            task_sampler_failure_diagnostics.get("zero_noncolliding_grasp_check_count") or 0
        ),
        "grasp_load_exception_asset_uids": _grasp_load_exception_asset_uids(
            task_sampler_failure_diagnostics
        ),
        "grasp_load_exception_types": _grasp_load_exception_types(task_sampler_failure_diagnostics),
        "object_name_count": len(object_names),
        "object_names": object_names,
        "image_artifact_count": len(task_sampler_failure_diagnostics.get("image_artifacts") or {}),
    }
    for key in (
        "candidate_effective_removal_count",
        "candidate_name_miss_count",
        "grasp_threshold_exceeded_count",
    ):
        if key in task_sampler_failure_diagnostics:
            signature[key] = int(task_sampler_failure_diagnostics.get(key) or 0)
    return signature


def grasp_feasibility_signature_counts(
    proof_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in proof_results:
        signature = item.get("grasp_feasibility_signature") or {}
        if not isinstance(signature, dict) or not signature:
            continue
        key = str(signature.get("pattern_key") or json.dumps(signature, sort_keys=True))
        group = groups.setdefault(
            key,
            {
                "schema": "planner_grasp_feasibility_signature_group_v1",
                "pattern_key": key,
                "summary": str(signature.get("summary") or ""),
                "count": 0,
                "request_ids": [],
                "object_ids": [],
                "target_receptacle_ids": [],
                "object_names": [],
                "proof_reports": [],
                "grasp_failure_count": signature.get("grasp_failure_count"),
                "candidate_removal_count": signature.get("candidate_removal_count"),
                "candidate_effective_removal_count": signature.get(
                    "candidate_effective_removal_count"
                ),
                "candidate_name_miss_count": signature.get("candidate_name_miss_count"),
                "grasp_threshold_exceeded_count": signature.get("grasp_threshold_exceeded_count"),
                "robot_placement_attempt_count": signature.get("robot_placement_attempt_count"),
                "robot_placement_failure_count": signature.get("robot_placement_failure_count"),
                "place_robot_near_call_count": signature.get("place_robot_near_call_count"),
                "grasp_load_attempt_count": signature.get("grasp_load_attempt_count"),
                "grasp_load_failure_count": signature.get("grasp_load_failure_count"),
                "grasp_collision_check_count": signature.get("grasp_collision_check_count"),
                "zero_noncolliding_grasp_check_count": signature.get(
                    "zero_noncolliding_grasp_check_count"
                ),
                "subkind": signature.get("subkind"),
                "grasp_load_exception_asset_uids": [],
                "grasp_load_exception_types": [],
                "image_artifact_count": 0,
            },
        )
        group["count"] += 1
        group["image_artifact_count"] += int(signature.get("image_artifact_count") or 0)
        _append_unique(group["request_ids"], str(item.get("request_id") or ""))
        _append_unique(group["object_ids"], str(item.get("object_id") or ""))
        _append_unique(
            group["target_receptacle_ids"],
            str(item.get("target_receptacle_id") or ""),
        )
        for object_name in signature.get("object_names") or []:
            _append_unique(group["object_names"], str(object_name or ""))
        for asset_uid in signature.get("grasp_load_exception_asset_uids") or []:
            _append_unique(group["grasp_load_exception_asset_uids"], str(asset_uid or ""))
        for exception_type in signature.get("grasp_load_exception_types") or []:
            _append_unique(group["grasp_load_exception_types"], str(exception_type or ""))
        _append_unique(group["proof_reports"], str(item.get("report") or ""))
    return sorted(
        groups.values(),
        key=lambda item: (-int(item.get("count") or 0), str(item.get("pattern_key") or "")),
    )


def grasp_feasibility_mitigation_decision(
    *,
    prior_proof_result_summary: dict[str, Any] | None = None,
    proof_result_summary: dict[str, Any] | None = None,
    proof_request_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prior_summary = prior_proof_result_summary or {}
    proof_summary = proof_result_summary or {}
    selection = proof_request_selection or {}
    signature_rows = _mitigation_signature_rows(
        [
            ("prior_proof_result_summary", prior_summary),
            ("proof_result_summary", proof_summary),
        ]
    )
    subkind_counts: dict[str, int] = {}
    missing_assets: list[str] = []
    exception_types: list[str] = []
    request_ids: list[str] = []
    for row in signature_rows:
        subkind = str(row.get("subkind") or "unknown")
        subkind_counts[subkind] = subkind_counts.get(subkind, 0) + int(row.get("count") or 0)
        for value in row.get("grasp_load_exception_asset_uids") or []:
            _append_unique(missing_assets, str(value or ""))
        for value in row.get("grasp_load_exception_types") or []:
            _append_unique(exception_types, str(value or ""))
        for value in row.get("request_ids") or []:
            _append_unique(request_ids, str(value or ""))
    selected_count = int(selection.get("selected_count") or 0)
    excluded_count = int(selection.get("excluded_count") or 0)
    source_rotation_state = _source_rotation_state(selected_count, excluded_count)
    primary_route, status, recommendation, rationale = _mitigation_route(
        missing_assets=missing_assets,
        subkind_counts=subkind_counts,
        source_rotation_state=source_rotation_state,
    )
    return {
        "schema": GRASP_FEASIBILITY_MITIGATION_DECISION_SCHEMA,
        "status": status,
        "primary_route": primary_route,
        "recommendation": recommendation,
        "rationale": rationale,
        "source_rotation_state": source_rotation_state,
        "selected_request_count": selected_count,
        "excluded_request_count": excluded_count,
        "signature_group_count": len(signature_rows),
        "subkind_counts": subkind_counts,
        "missing_grasp_asset_uids": missing_assets,
        "grasp_load_exception_types": exception_types,
        "evidence_request_ids": request_ids,
        "signature_groups": signature_rows,
    }


def _grasp_pattern_key(task_sampler_failure_diagnostics: dict[str, Any]) -> str:
    fields = {
        "candidate_removal_count": int(
            task_sampler_failure_diagnostics.get("candidate_removal_count") or 0
        ),
        "grasp_failure_count": int(
            task_sampler_failure_diagnostics.get("grasp_failure_count") or 0
        ),
        "place_robot_near_call_count": int(
            task_sampler_failure_diagnostics.get("place_robot_near_call_count") or 0
        ),
        "robot_placement_failure_count": int(
            task_sampler_failure_diagnostics.get("robot_placement_failure_count") or 0
        ),
        "subkind": _grasp_feasibility_subkind(task_sampler_failure_diagnostics),
    }
    for key in ("candidate_effective_removal_count", "candidate_name_miss_count"):
        if key in task_sampler_failure_diagnostics:
            fields[key] = int(task_sampler_failure_diagnostics.get(key) or 0)
    for key in (
        "grasp_load_attempt_count",
        "grasp_load_failure_count",
        "grasp_collision_check_count",
        "zero_noncolliding_grasp_check_count",
    ):
        if key in task_sampler_failure_diagnostics:
            fields[key] = int(task_sampler_failure_diagnostics.get(key) or 0)
    missing_assets = _grasp_load_exception_asset_uids(task_sampler_failure_diagnostics)
    if missing_assets:
        fields["grasp_load_exception_asset_uids"] = missing_assets
    exception_types = _grasp_load_exception_types(task_sampler_failure_diagnostics)
    if exception_types:
        fields["grasp_load_exception_types"] = exception_types
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def _mitigation_signature_rows(
    summaries: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows = []
    for source, summary in summaries:
        if not isinstance(summary, dict) or not summary:
            continue
        signature_groups = summary.get("grasp_feasibility_signature_counts") or []
        if not signature_groups:
            signature_groups = grasp_feasibility_signature_counts(summary.get("results") or [])
        for group in signature_groups:
            if not isinstance(group, dict) or not group:
                continue
            rows.append(
                {
                    "source": source,
                    "subkind": str(group.get("subkind") or "unknown"),
                    "count": int(group.get("count") or 0),
                    "summary": str(group.get("summary") or ""),
                    "request_ids": [str(value) for value in group.get("request_ids") or []],
                    "object_names": [str(value) for value in group.get("object_names") or []],
                    "grasp_load_exception_asset_uids": [
                        str(value) for value in group.get("grasp_load_exception_asset_uids") or []
                    ],
                    "grasp_load_exception_types": [
                        str(value) for value in group.get("grasp_load_exception_types") or []
                    ],
                }
            )
    return rows


def _source_rotation_state(selected_count: int, excluded_count: int) -> str:
    if selected_count:
        return "available_for_unproven_requests"
    if excluded_count:
        return "exhausted_by_prior_memory"
    return "not_applicable"


def _mitigation_route(
    *,
    missing_assets: list[str],
    subkind_counts: dict[str, int],
    source_rotation_state: str,
) -> tuple[str, str, str, str]:
    if missing_assets:
        recommendation = "mitigate_missing_grasp_cache_before_retry"
        rationale = (
            "At least one exact-scene proof failed before collision masking because cached "
            "grasps could not be loaded for the requested asset."
        )
        if source_rotation_state == "available_for_unproven_requests":
            rationale += (
                " Source rotation still has selected unproven requests, but it should not "
                "be treated as a retry path for the missing-cache asset."
            )
        return ("grasp_cache_mitigation", "action_required", recommendation, rationale)
    if subkind_counts.get("zero_noncolliding_grasps"):
        return (
            "collision_or_pose_mitigation",
            "action_required",
            "investigate_zero_noncolliding_grasps",
            "Cached grasps loaded, but collision masking rejected every checked pose.",
        )
    if subkind_counts:
        return (
            "source_rotation",
            "action_required",
            "rotate_source_or_improve_grasp_policy",
            "Current grasp-feasibility evidence is not a missing-cache signature.",
        )
    return (
        "none",
        "not_applicable",
        "no_grasp_feasibility_signature_evidence",
        "No grouped grasp-feasibility signatures were present in prior or current proof results.",
    )


def _grasp_feasibility_subkind(task_sampler_failure_diagnostics: dict[str, Any]) -> str:
    if int(task_sampler_failure_diagnostics.get("grasp_load_failure_count") or 0) and not int(
        task_sampler_failure_diagnostics.get("grasp_collision_check_count") or 0
    ):
        return "grasp_cache_missing"
    if int(task_sampler_failure_diagnostics.get("zero_noncolliding_grasp_check_count") or 0):
        return "zero_noncolliding_grasps"
    return "grasp_rejection"


def _grasp_load_exception_asset_uids(
    task_sampler_failure_diagnostics: dict[str, Any],
) -> list[str]:
    return _unique_nonempty(
        str(item.get("asset_uid") or "")
        for item in task_sampler_failure_diagnostics.get("grasp_load_attempts") or []
        if isinstance(item, dict) and str(item.get("result") or "") != "loaded"
    )


def _grasp_load_exception_types(
    task_sampler_failure_diagnostics: dict[str, Any],
) -> list[str]:
    return _unique_nonempty(
        str(item.get("exception_type") or "")
        for item in task_sampler_failure_diagnostics.get("grasp_load_attempts") or []
        if isinstance(item, dict) and str(item.get("result") or "") != "loaded"
    )


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _unique_nonempty(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        _append_unique(result, str(value or ""))
    return result
