from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_REQUEST_SELECTION_SCHEMA,
)
from roboclaws.household.planner_proof_fallback_selection import (
    build_fallback_generation,
    build_fallback_requests_for_blocked_request,
)
from roboclaws.household.planner_proof_fallbacks import (
    discovered_runtime_aliases_by_source_request as _discovered_runtime_aliases_by_source_request,
)
from roboclaws.household.planner_proof_fallbacks import (
    planner_arg as _planner_arg,
)
from roboclaws.household.planner_proof_fallbacks import (
    prior_fallback_candidate_filters_by_source_request,
)
from roboclaws.household.planner_proof_fallbacks import (
    proof_cleanup_task_config as _proof_cleanup_task_config,
)
from roboclaws.household.planner_proof_fallbacks import (
    unique_nonempty_values as _unique_nonempty_values,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
)
from roboclaws.household.planner_proof_results import normalized_blockers
from roboclaws.household.planner_proof_selection_evidence import prior_result_blocker_fields

_prior_fallback_candidate_filters_by_source_request = (
    prior_fallback_candidate_filters_by_source_request
)
_FALLBACK_REQUEST_ID_MARKER = "_fallback_"
_RUNTIME_ALIAS_RE = re.compile(r"^(?P<prefix>.+)_(?P<group>\d+)_(?P<variant>\d+)_(?P<room>\d+)$")


def proof_request_selection_from_summary(
    proof_requests: dict[str, Any],
    *,
    prior_proof_result_summary: dict[str, Any] | None = None,
    include_request_ids: Sequence[str] | None = None,
    exclude_task_feasibility_blocked: bool = False,
    exclude_prior_covered: bool = False,
    prior_covered_min_proof_steps: int = 1,
    generate_fallback_requests: bool = False,
    fallback_alias_limit: int = 4,
) -> dict[str, Any]:
    """Select ready proof requests, optionally excluding known infeasible requests."""
    prior_covered_min_proof_steps = max(1, int(prior_covered_min_proof_steps))
    requested_ids = _normalized_request_ids(include_request_ids)
    all_requests = [request for request in proof_requests.get("requests") or []]
    all_ready_requests = [
        request for request in proof_requests.get("requests") or [] if request.get("ready")
    ]
    request_filter = _request_id_filter(
        requested_ids=requested_ids,
        requests=all_requests,
        ready_requests=all_ready_requests,
    )
    ready_requests = [
        request
        for request in all_ready_requests
        if not requested_ids or str(request.get("request_id") or "") in set(requested_ids)
    ]
    prior_summary = prior_proof_result_summary or {}
    prior_results = _prior_results_by_request_id(prior_summary)
    prior_results_by_cleanup_pair = _prior_results_by_cleanup_pair(prior_summary)
    prior_results_by_planner_object_target = _prior_results_by_planner_object_target(prior_summary)
    discovered_aliases_by_request = _discovered_runtime_aliases_by_source_request(
        ready_requests,
        prior_summary,
    )
    prior_candidate_filters_by_request = _prior_fallback_candidate_filters_by_source_request(
        prior_summary
    )
    selected = []
    excluded = []
    generated = []
    filtered_aliases = []
    discovered_aliases = []
    filtered_pairs = []
    normalized_aliases = []
    for request in ready_requests:
        request_id = str(request.get("request_id") or "")
        prior_result, prior_result_match_kind = _prior_result_for_request(
            request,
            prior_results_by_request_id=prior_results,
            prior_results_by_cleanup_pair=prior_results_by_cleanup_pair,
            prior_results_by_planner_object_target=prior_results_by_planner_object_target,
        )
        if exclude_prior_covered and _prior_result_has_cleanup_binding_coverage(
            prior_result,
            min_proof_steps=prior_covered_min_proof_steps,
        ):
            excluded.append(
                _excluded_request(
                    request,
                    prior_result,
                    reason="prior_planner_proof_covered",
                    prior_result_match_kind=prior_result_match_kind,
                )
            )
            continue
        if (
            exclude_task_feasibility_blocked
            and prior_result.get("task_feasibility_status") == "blocked"
        ):
            excluded.append(
                _excluded_request(
                    request,
                    prior_result,
                    reason="prior_task_feasibility_blocked",
                    prior_result_match_kind=prior_result_match_kind,
                )
            )
            if generate_fallback_requests:
                fallback = build_fallback_requests_for_blocked_request(
                    request,
                    prior_result,
                    limit=fallback_alias_limit,
                    discovered_aliases=discovered_aliases_by_request.get(request_id, {}),
                    prior_candidate_filters=prior_candidate_filters_by_request.get(request_id, {}),
                    prior_result_match_kind=prior_result_match_kind,
                )
                generated.extend(fallback["generated_requests"])
                filtered_aliases.extend(fallback["filtered_aliases"])
                discovered_aliases.extend(fallback["discovered_aliases"])
                filtered_pairs.extend(fallback["filtered_pairs"])
                normalized_aliases.extend(fallback["normalized_aliases"])
            continue
        selected.append(
            _selected_request(
                request,
                prior_result,
                prior_result_match_kind=prior_result_match_kind,
            )
        )
    selected.extend(
        _selected_request(request, {}, prior_result_match_kind="") for request in generated
    )
    fallback_required = bool(ready_requests) and not selected
    fallback_generation = build_fallback_generation(
        enabled=generate_fallback_requests,
        ready_request_count=len(ready_requests),
        excluded_requests=excluded,
        generated_requests=generated,
        filtered_aliases=filtered_aliases,
        discovered_aliases=discovered_aliases,
        filtered_pairs=filtered_pairs,
        normalized_aliases=normalized_aliases,
        fallback_alias_limit=fallback_alias_limit,
    )
    target_feasibility_blockers = _target_feasibility_blockers(
        excluded_requests=excluded,
        filtered_pairs=fallback_generation.get("filtered_pairs") or [],
    )
    grasp_feasibility_blockers = _grasp_feasibility_blockers(target_feasibility_blockers)
    return {
        "schema": PLANNER_PROOF_REQUEST_SELECTION_SCHEMA,
        "mode": _proof_request_selection_mode(
            include_request_ids=bool(requested_ids),
            exclude_task_feasibility_blocked=exclude_task_feasibility_blocked,
            exclude_prior_covered=exclude_prior_covered,
            generate_fallback_requests=generate_fallback_requests,
        ),
        "ready_request_count": len(all_ready_requests),
        "candidate_request_count": len(ready_requests),
        "request_filter": request_filter,
        "selected_count": len(selected),
        "excluded_count": len(excluded),
        "covered_request_count": sum(
            1 for item in excluded if item.get("reason") == "prior_planner_proof_covered"
        ),
        "prior_covered_min_proof_steps": prior_covered_min_proof_steps,
        "generated_fallback_request_count": len(generated),
        "fallback_required": fallback_required,
        "selected_request_ids": [item["request_id"] for item in selected],
        "selected_requests": selected,
        "excluded_requests": excluded,
        "target_feasibility_blocker_count": len(target_feasibility_blockers),
        "target_feasibility_blockers": target_feasibility_blockers,
        "grasp_feasibility_blocker_count": len(grasp_feasibility_blockers),
        "grasp_feasibility_blockers": grasp_feasibility_blockers,
        "fallback_generation": fallback_generation,
        "prior_summary_available": bool(prior_proof_result_summary),
        "prior_result_count": len(prior_results),
        "evidence_note": (
            "Private proof request selection for local proof-bundle execution. "
            "Excluded requests require fallback generation before another exact proof run."
        ),
    }


def _proof_request_selection_mode(
    *,
    include_request_ids: bool,
    exclude_task_feasibility_blocked: bool,
    exclude_prior_covered: bool,
    generate_fallback_requests: bool,
) -> str:
    if exclude_task_feasibility_blocked and exclude_prior_covered and generate_fallback_requests:
        mode = "exclude_task_feasibility_blocked_and_prior_covered_with_fallbacks"
    elif exclude_task_feasibility_blocked and exclude_prior_covered:
        mode = "exclude_task_feasibility_blocked_and_prior_covered"
    elif exclude_task_feasibility_blocked and generate_fallback_requests:
        mode = "exclude_task_feasibility_blocked_with_fallbacks"
    elif exclude_task_feasibility_blocked:
        mode = "exclude_task_feasibility_blocked"
    elif exclude_prior_covered:
        mode = "exclude_prior_covered"
    else:
        mode = "all_ready"
    if include_request_ids:
        if mode == "all_ready":
            return "request_id_filter"
        return f"request_id_filter_and_{mode}"
    return mode


def _normalized_request_ids(request_ids: Sequence[str] | None) -> list[str]:
    if not request_ids:
        return []
    return _unique_nonempty_values([str(item).strip() for item in request_ids])


def _request_id_filter(
    *,
    requested_ids: list[str],
    requests: list[dict[str, Any]],
    ready_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    if not requested_ids:
        return {
            "enabled": False,
            "requested_request_ids": [],
            "matched_request_ids": [],
            "unavailable_request_ids": [],
        }
    request_ids = {str(item.get("request_id") or "") for item in requests}
    ready_ids = {str(item.get("request_id") or "") for item in ready_requests}
    matched = [request_id for request_id in requested_ids if request_id in ready_ids]
    unavailable = [request_id for request_id in requested_ids if request_id not in ready_ids]
    missing = [request_id for request_id in requested_ids if request_id not in request_ids]
    return {
        "enabled": True,
        "requested_request_ids": requested_ids,
        "requested_count": len(requested_ids),
        "matched_request_ids": matched,
        "matched_count": len(matched),
        "unavailable_request_ids": unavailable,
        "unavailable_count": len(unavailable),
        "missing_request_ids": missing,
        "missing_count": len(missing),
        "evidence_note": ("Explicit proof request filter for bounded local proof-bundle runs."),
    }


def selected_request_ids(request_selection: dict[str, Any] | None) -> set[str] | None:
    if not request_selection:
        return None
    raw = request_selection.get("selected_request_ids")
    if raw is None:
        return None
    return {str(item) for item in raw}


def generated_ready_proof_requests(
    request_selection: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not request_selection:
        return []
    fallback_generation = request_selection.get("fallback_generation") or {}
    if not isinstance(fallback_generation, dict):
        return []
    raw = fallback_generation.get("generated_requests") or []
    return [
        dict(item)
        for item in raw
        if isinstance(item, dict) and item.get("ready") and item.get("request_id")
    ]


def _prior_results_by_request_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("request_id") or ""): dict(item)
        for item in summary.get("results") or []
        if isinstance(item, dict) and item.get("request_id")
    }


def _prior_results_by_cleanup_pair(
    summary: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for item in summary.get("results") or []:
        if not isinstance(item, dict):
            continue
        pair = _cleanup_pair_from_result(item)
        if not all(pair):
            continue
        existing = results.get(pair)
        if existing is None or _prior_selection_result_rank(item) >= _prior_selection_result_rank(
            existing
        ):
            results[pair] = dict(item)
    return results


def _prior_results_by_planner_object_target(
    summary: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for item in summary.get("results") or []:
        if not isinstance(item, dict):
            continue
        pair = _planner_object_target_pair_from_result(item)
        if not all(pair):
            continue
        existing = results.get(pair)
        if existing is None or _prior_selection_result_rank(item) >= _prior_selection_result_rank(
            existing
        ):
            results[pair] = dict(item)
    return results


def _prior_result_for_request(
    request: dict[str, Any],
    *,
    prior_results_by_request_id: dict[str, dict[str, Any]],
    prior_results_by_cleanup_pair: dict[tuple[str, str], dict[str, Any]],
    prior_results_by_planner_object_target: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    request_id = str(request.get("request_id") or "")
    prior_by_request_id = prior_results_by_request_id.get(request_id)
    if prior_by_request_id and _request_id_prior_result_matches_request(
        request,
        prior_by_request_id,
    ):
        return prior_by_request_id, "request_id"
    pair = _cleanup_pair_from_request(request)
    prior_by_cleanup_pair = prior_results_by_cleanup_pair.get(pair)
    if prior_by_cleanup_pair and _cleanup_pair_prior_result_matches_request(
        request,
        prior_by_cleanup_pair,
    ):
        return prior_by_cleanup_pair, "object_target"
    planner_pair = _planner_object_target_pair_from_request(request)
    if planner_pair in prior_results_by_planner_object_target:
        return prior_results_by_planner_object_target[planner_pair], "planner_object_target"
    return {}, ""


def _cleanup_pair_from_request(request: dict[str, Any]) -> tuple[str, str]:
    return (
        str(request.get("object_id") or ""),
        str(request.get("target_receptacle_id") or ""),
    )


def _cleanup_pair_from_result(result: dict[str, Any]) -> tuple[str, str]:
    return (
        str(result.get("object_id") or ""),
        str(result.get("target_receptacle_id") or ""),
    )


def _planner_object_target_pair_from_request(request: dict[str, Any]) -> tuple[str, str]:
    args = request.get("planner_probe_args") or {}
    planner_object_id = _planner_arg(args, "--cleanup-planner-object-id")
    planner_target_id = _planner_arg(args, "--cleanup-planner-target-receptacle-id")
    return (
        planner_object_id,
        str(request.get("target_receptacle_id") or planner_target_id),
    )


def _planner_object_target_pair_from_result(result: dict[str, Any]) -> tuple[str, str]:
    config = _proof_cleanup_task_config(result)
    planner_object_id = str(config.get("planner_object_id") or "")
    planner_target_id = str(config.get("planner_target_receptacle_id") or "")
    return (
        planner_object_id,
        str(
            result.get("target_receptacle_id")
            or config.get("target_receptacle_id")
            or planner_target_id
        ),
    )


def _request_id_prior_result_matches_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
) -> bool:
    if _planner_object_target_pairs_conflict(request, prior_result):
        return False
    request_cleanup_pair = _cleanup_pair_from_request(request)
    prior_cleanup_pair = _cleanup_pair_from_result(prior_result)
    if all(request_cleanup_pair) and all(prior_cleanup_pair):
        return request_cleanup_pair == prior_cleanup_pair
    request_planner_pair = _planner_object_target_pair_from_request(request)
    prior_planner_pair = _planner_object_target_pair_from_result(prior_result)
    if all(request_planner_pair) and all(prior_planner_pair):
        return request_planner_pair == prior_planner_pair
    return True


def _cleanup_pair_prior_result_matches_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
) -> bool:
    return not _planner_object_target_pairs_conflict(request, prior_result)


def _planner_object_target_pairs_conflict(
    request: dict[str, Any],
    prior_result: dict[str, Any],
) -> bool:
    request_planner_pair = _planner_object_target_pair_from_request(request)
    prior_planner_pair = _planner_object_target_pair_from_result(prior_result)
    return (
        all(request_planner_pair)
        and all(prior_planner_pair)
        and (request_planner_pair != prior_planner_pair)
    )


def _prior_selection_result_rank(item: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(str(item.get("task_feasibility_status") or "") == "blocked"),
        int(str(item.get("status") or "") == "blocked_capability"),
        int(bool(item.get("run_result_exists") or item.get("run_result"))),
    )


def _prior_result_has_cleanup_binding_coverage(
    item: dict[str, Any],
    *,
    min_proof_steps: int,
) -> bool:
    if not bool(item.get("planner_backed")) or not bool(item.get("cleanup_binding_promoted")):
        return False
    if min_proof_steps <= 1 and not _has_prior_quality_inputs(item):
        return True
    quality = planner_proof_quality_evidence(item)
    return (
        bool(quality.get("one_step_motion"))
        and int(quality.get("steps_executed") or 0) >= min_proof_steps
        and float(quality.get("max_abs_qpos_delta") or 0.0) > 0.0
    )


def _has_prior_quality_inputs(item: dict[str, Any]) -> bool:
    return any(
        key in item
        for key in (
            "proof_quality",
            "steps_executed",
            "max_abs_qpos_delta",
            "containment_proven",
            "object_state_evidence",
        )
    )


def _selected_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    prior_result_match_kind: str,
) -> dict[str, Any]:
    fallback = request.get("fallback_request") or {}
    is_fallback = isinstance(fallback, dict) and bool(fallback)
    item = {
        "request_id": str(request.get("request_id") or ""),
        "request_type": "fallback_generated" if is_fallback else "source",
        "source_request_id": str(fallback.get("source_request_id") or ""),
        "object_id": str(request.get("object_id") or ""),
        "target_receptacle_id": str(request.get("target_receptacle_id") or ""),
        "prior_task_feasibility_status": str(
            prior_result.get("task_feasibility_status")
            or fallback.get("prior_task_feasibility_status")
            or "unknown"
        ),
    }
    item.update(
        _nonempty_prior_blocker_fields(
            prior_result.get("task_feasibility_blocker_kind")
            or fallback.get("prior_task_feasibility_blocker_kind"),
            prior_result.get("task_feasibility_blocker_summary")
            or fallback.get("prior_task_feasibility_blocker_summary"),
        )
    )
    match_kind = prior_result_match_kind or str(fallback.get("prior_result_match_kind") or "")
    if match_kind:
        item["prior_result_match_kind"] = match_kind
    if prior_result:
        item.update(_prior_result_evidence_fields(prior_result))
    return item


def _excluded_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    reason: str,
    prior_result_match_kind: str,
) -> dict[str, Any]:
    item = {
        "request_id": str(request.get("request_id") or ""),
        "object_id": str(request.get("object_id") or ""),
        "target_receptacle_id": str(request.get("target_receptacle_id") or ""),
        "reason": reason,
        "prior_status": str(prior_result.get("status") or ""),
        "prior_task_feasibility_status": str(prior_result.get("task_feasibility_status") or ""),
        "prior_blockers": normalized_blockers(prior_result.get("blockers") or []),
        **_prior_result_evidence_fields(prior_result),
    }
    item.update(_prior_result_blocker_fields(prior_result))
    if prior_result_match_kind:
        item["prior_result_match_kind"] = prior_result_match_kind
    return item


def _target_feasibility_blockers(
    *,
    excluded_requests: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in excluded_requests:
        if str(item.get("prior_task_feasibility_status") or "") != "blocked":
            continue
        blockers.append(
            _target_feasibility_blocker(
                item,
                kind="source_request",
                source_request_id=str(item.get("request_id") or ""),
                object_id=str(item.get("object_id") or ""),
                target_receptacle_id=str(item.get("target_receptacle_id") or ""),
            )
        )
    for item in filtered_pairs:
        if str(item.get("reason") or "") != "prior_task_feasibility_blocked_pair":
            continue
        blockers.append(
            _target_feasibility_blocker(
                item,
                kind="fallback_pair",
                source_request_id=str(item.get("source_request_id") or ""),
                object_alias=str(item.get("object_alias") or ""),
                target_alias=str(item.get("target_alias") or ""),
                derived_from=str(item.get("derived_from") or ""),
            )
        )
    return blockers


def _target_feasibility_blocker(
    item: dict[str, Any],
    *,
    kind: str,
    source_request_id: str,
    object_id: str = "",
    target_receptacle_id: str = "",
    object_alias: str = "",
    target_alias: str = "",
    derived_from: str = "",
) -> dict[str, Any]:
    blocker = {
        "kind": kind,
        "source_request_id": source_request_id,
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "object_alias": object_alias,
        "target_alias": target_alias,
        "derived_from": derived_from,
        "reason": str(item.get("reason") or ""),
        "prior_status": str(item.get("prior_status") or ""),
        "prior_task_feasibility_status": str(item.get("prior_task_feasibility_status") or ""),
        "prior_blockers": normalized_blockers(item.get("prior_blockers") or []),
        "prior_run_result": str(item.get("prior_run_result") or ""),
        "prior_report": str(item.get("prior_report") or ""),
        "prior_stdout": str(item.get("prior_stdout") or ""),
        "prior_stderr": str(item.get("prior_stderr") or ""),
        "last_worker_stage": str(item.get("last_worker_stage") or ""),
        "execution_attempted": bool(item.get("execution_attempted")),
    }
    blocker.update(
        _nonempty_prior_blocker_fields(
            item.get("prior_task_feasibility_blocker_kind"),
            item.get("prior_task_feasibility_blocker_summary"),
        )
    )
    if item.get("prior_result_match_kind"):
        blocker["prior_result_match_kind"] = str(item.get("prior_result_match_kind") or "")
    return blocker


def _grasp_feasibility_blockers(
    target_feasibility_blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in target_feasibility_blockers
        if str(item.get("prior_task_feasibility_blocker_kind") or "") == "grasp_feasibility"
    ]


def _prior_result_evidence_fields(result: dict[str, Any]) -> dict[str, Any]:
    quality = planner_proof_quality_evidence(result)
    return {
        "prior_run_result": str(result.get("run_result") or ""),
        "prior_report": str(result.get("report") or ""),
        "prior_stdout": str(result.get("stdout") or ""),
        "prior_stderr": str(result.get("stderr") or ""),
        "last_worker_stage": str(result.get("last_worker_stage") or ""),
        "execution_attempted": bool(result.get("execution_attempted")),
        "prior_proof_quality": str(quality.get("quality_tier") or ""),
        "prior_steps_executed": int(quality.get("steps_executed") or 0),
        "prior_max_abs_qpos_delta": float(quality.get("max_abs_qpos_delta") or 0.0),
    }


def _prior_result_blocker_fields(result: dict[str, Any]) -> dict[str, Any]:
    return prior_result_blocker_fields(result)


def _nonempty_prior_blocker_fields(kind: Any, summary: Any) -> dict[str, str]:
    fields = {}
    kind_text = str(kind or "")
    summary_text = str(summary or "")
    if kind_text:
        fields["prior_task_feasibility_blocker_kind"] = kind_text
    if summary_text:
        fields["prior_task_feasibility_blocker_summary"] = summary_text
    return fields
