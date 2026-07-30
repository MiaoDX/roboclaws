from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_REQUEST_FALLBACK_GENERATION_SCHEMA,
)
from roboclaws.household.planner_proof_fallbacks import (
    discovered_alias_values as _discovered_alias_values,
)
from roboclaws.household.planner_proof_fallbacks import (
    planner_arg as _planner_arg,
)
from roboclaws.household.planner_proof_fallbacks import (
    prior_fallback_candidate_filters_by_source_request,
)
from roboclaws.household.planner_proof_fallbacks import (
    prior_pair_filter_lookup as _prior_pair_filter_lookup,
)
from roboclaws.household.planner_proof_fallbacks import (
    unique_nonempty_values as _unique_nonempty_values,
)
from roboclaws.household.planner_proof_results import normalized_blockers
from roboclaws.household.planner_proof_selection_evidence import prior_result_blocker_fields

_prior_fallback_candidate_filters_by_source_request = (
    prior_fallback_candidate_filters_by_source_request
)
_FALLBACK_REQUEST_ID_MARKER = "_fallback_"
_RUNTIME_ALIAS_RE = re.compile(r"^(?P<prefix>.+)_(?P<group>\d+)_(?P<variant>\d+)_(?P<room>\d+)$")


def build_fallback_generation(
    *,
    enabled: bool,
    ready_request_count: int,
    excluded_requests: list[dict[str, Any]],
    generated_requests: list[dict[str, Any]],
    filtered_aliases: list[dict[str, Any]],
    discovered_aliases: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
    normalized_aliases: list[dict[str, Any]],
    fallback_alias_limit: int,
) -> dict[str, Any]:
    if not enabled and not generated_requests:
        return {
            "schema": PLANNER_PROOF_REQUEST_FALLBACK_GENERATION_SCHEMA,
            "status": "disabled",
            "enabled": False,
            "generated_request_count": 0,
            "generated_requests": [],
            "filtered_alias_count": 0,
            "filtered_aliases": [],
            "discovered_alias_count": 0,
            "discovered_aliases": [],
            "filtered_pair_count": 0,
            "filtered_pairs": [],
            "normalized_alias_count": 0,
            "normalized_aliases": [],
        }
    generated_source_ids = {str(item.get("source_request_id") or "") for item in generated_requests}
    unavailable_count = len(excluded_requests) - len(generated_source_ids)
    status = _fallback_generation_status(
        enabled=enabled,
        excluded_request_count=len(excluded_requests),
        generated_request_count=len(generated_requests),
    )
    exhaustion_blockers = _fallback_exhaustion_blockers(
        status=status,
        filtered_aliases=filtered_aliases,
        filtered_pairs=filtered_pairs,
        normalized_aliases=normalized_aliases,
        unavailable_source_request_count=max(unavailable_count, 0),
    )
    return {
        "schema": PLANNER_PROOF_REQUEST_FALLBACK_GENERATION_SCHEMA,
        "status": status,
        "enabled": enabled,
        "ready_request_count": ready_request_count,
        "excluded_request_count": len(excluded_requests),
        "generated_request_count": len(generated_requests),
        "unavailable_source_request_count": max(unavailable_count, 0),
        "fallback_alias_limit": max(int(fallback_alias_limit or 0), 0),
        "generated_requests": generated_requests,
        "filtered_alias_count": len(filtered_aliases),
        "filtered_aliases": filtered_aliases,
        "discovered_alias_count": len(discovered_aliases),
        "discovered_aliases": discovered_aliases,
        "filtered_pair_count": len(filtered_pairs),
        "filtered_pairs": filtered_pairs,
        "normalized_alias_count": len(normalized_aliases),
        "normalized_aliases": normalized_aliases,
        "exhaustion_blocker_count": len(exhaustion_blockers),
        "exhaustion_blockers": exhaustion_blockers,
        "evidence_note": (
            "Private generated fallback proof requests. They preserve cleanup-facing "
            "object and target IDs while trying alternate exact-scene planner aliases."
        ),
    }


def _fallback_generation_status(
    *,
    enabled: bool,
    excluded_request_count: int,
    generated_request_count: int,
) -> str:
    if not enabled:
        return "disabled"
    if generated_request_count > 0:
        return "generated"
    if excluded_request_count > 0:
        return "exhausted"
    return "not_required"


def _fallback_exhaustion_blockers(
    *,
    status: str,
    filtered_aliases: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
    normalized_aliases: list[dict[str, Any]],
    unavailable_source_request_count: int,
) -> list[dict[str, Any]]:
    if status != "exhausted":
        return []
    blockers = []
    normalized_object_aliases = {
        str(item.get("alias") or "")
        for item in normalized_aliases
        if isinstance(item, dict) and str(item.get("axis") or "") == "object"
    }
    non_root_alias_count = sum(
        1
        for item in filtered_aliases
        if str(item.get("axis") or "") == "object"
        and str(item.get("reason") or "")
        in {"prior_non_root_body_alias", "not_pickup_root_body_alias"}
        and str(item.get("alias") or "") not in normalized_object_aliases
    )
    if non_root_alias_count:
        blockers.append(
            {
                "code": "pickup_root_body_alias_required",
                "count": non_root_alias_count,
                "message": (
                    "Known object-side runtime fallback aliases are filtered as "
                    "non-root pickup bodies; a richer pickup root-body alias source "
                    "is required before more object-side commands can be generated."
                ),
            }
        )
    grasp_feasibility_pair_count = sum(
        1
        for item in filtered_pairs
        if str(item.get("reason") or "") == "prior_task_feasibility_blocked_pair"
        and str(item.get("prior_task_feasibility_blocker_kind") or "") == "grasp_feasibility"
    )
    if grasp_feasibility_pair_count:
        blockers.append(
            {
                "code": "grasp_feasibility_blocked_pairs",
                "count": grasp_feasibility_pair_count,
                "message": (
                    "Known object/target fallback alias pairs clear robot placement "
                    "but are blocked by post-placement grasp/candidate rejection."
                ),
            }
        )
    task_feasibility_pair_count = sum(
        1
        for item in filtered_pairs
        if str(item.get("reason") or "") == "prior_task_feasibility_blocked_pair"
        and str(item.get("prior_task_feasibility_blocker_kind") or "") != "grasp_feasibility"
    )
    if task_feasibility_pair_count:
        blockers.append(
            {
                "code": "target_task_feasibility_blocked_pairs",
                "count": task_feasibility_pair_count,
                "message": (
                    "Known object/target fallback alias pairs are already "
                    "task-feasibility blocked by the upstream sampler."
                ),
            }
        )
    if unavailable_source_request_count:
        blockers.append(
            {
                "code": "no_fallback_candidate_available",
                "count": unavailable_source_request_count,
                "message": (
                    "Excluded source requests have no remaining generated fallback "
                    "candidate after alias and pair filters are applied."
                ),
            }
        )
    if not blockers:
        blockers.append(
            {
                "code": "fallback_candidate_pool_exhausted",
                "count": 0,
                "message": "No generated fallback commands remain for the current evidence pool.",
            }
        )
    return blockers


def build_fallback_requests_for_blocked_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    limit: int,
    discovered_aliases: dict[str, list[dict[str, Any]]] | None = None,
    prior_candidate_filters: dict[str, Any] | None = None,
    prior_result_match_kind: str = "",
) -> dict[str, list[dict[str, Any]]]:
    if limit <= 0:
        return {
            "generated_requests": [],
            "filtered_aliases": [],
            "discovered_aliases": [],
            "filtered_pairs": [],
            "normalized_aliases": [],
        }
    args = request.get("planner_probe_args") or {}
    current_object_alias = _planner_arg(args, "--cleanup-planner-object-id")
    current_target_alias = _planner_arg(args, "--cleanup-planner-target-receptacle-id")
    discovered = discovered_aliases or {}
    prior_filters = prior_candidate_filters or {}
    prior_alias_filters = prior_filters.get("aliases") if isinstance(prior_filters, dict) else {}
    if not isinstance(prior_alias_filters, dict):
        prior_alias_filters = {}
    (
        pickup_candidates,
        filtered_pickup_aliases,
        normalized_pickup_aliases,
    ) = _executable_candidate_aliases(
        request,
        axis="object",
        candidate_key="candidate_pickup_names",
        current_alias=current_object_alias,
        extra_aliases=_discovered_alias_values(discovered, "object"),
        prior_filtered_aliases=prior_alias_filters.get("object", {}),
    )
    (
        target_candidates,
        filtered_target_aliases,
        normalized_target_aliases,
    ) = _executable_candidate_aliases(
        request,
        axis="target",
        candidate_key="candidate_place_receptacle_names",
        current_alias=current_target_alias,
        extra_aliases=_discovered_alias_values(discovered, "target"),
        prior_filtered_aliases=prior_alias_filters.get("target", {}),
    )
    filtered_aliases = [
        *filtered_pickup_aliases,
        *filtered_target_aliases,
    ]
    normalized_aliases = [
        *normalized_pickup_aliases,
        *normalized_target_aliases,
    ]
    flattened_discovered_aliases = [
        *discovered.get("object", []),
        *discovered.get("target", []),
    ]
    prior_pair_filters = _prior_pair_filter_lookup(prior_filters)
    filtered_pairs = []
    seen_filtered_pairs: set[tuple[str, str]] = set()
    generated: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for object_alias in pickup_candidates:
        for target_alias in target_candidates:
            pair = (object_alias, target_alias)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if pair == (current_object_alias, current_target_alias):
                continue
            prior_pair_filter = prior_pair_filters.get(pair)
            if prior_pair_filter:
                if pair not in seen_filtered_pairs:
                    filtered_pairs.append(dict(prior_pair_filter))
                    seen_filtered_pairs.add(pair)
                continue
            generated.append(
                _fallback_request_with_planner_aliases(
                    request,
                    prior_result,
                    index=len(generated) + 1,
                    planner_object_id=object_alias,
                    planner_target_receptacle_id=target_alias,
                    prior_result_match_kind=prior_result_match_kind,
                )
            )
            if len(generated) >= limit:
                return {
                    "generated_requests": generated,
                    "filtered_aliases": filtered_aliases,
                    "discovered_aliases": flattened_discovered_aliases,
                    "filtered_pairs": filtered_pairs,
                    "normalized_aliases": normalized_aliases,
                }
    return {
        "generated_requests": generated,
        "filtered_aliases": filtered_aliases,
        "discovered_aliases": flattened_discovered_aliases,
        "filtered_pairs": filtered_pairs,
        "normalized_aliases": normalized_aliases,
    }


def _fallback_request_with_planner_aliases(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    index: int,
    planner_object_id: str,
    planner_target_receptacle_id: str,
    prior_result_match_kind: str,
) -> dict[str, Any]:
    source_request_id = str(request.get("request_id") or "")
    fallback = deepcopy(request)
    fallback["request_id"] = f"{source_request_id}_fallback_{index:02d}"
    fallback["ready"] = True
    fallback["source_request_id"] = source_request_id
    fallback["fallback_request"] = {
        "source_request_id": source_request_id,
        "reason": "prior_task_feasibility_blocked",
        "strategy": "alternate_planner_alias",
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_receptacle_id,
        "prior_status": str(prior_result.get("status") or ""),
        "prior_task_feasibility_status": str(prior_result.get("task_feasibility_status") or ""),
        "prior_blockers": normalized_blockers(prior_result.get("blockers") or []),
        "agent_view_exposed": False,
    }
    fallback["fallback_request"].update(prior_result_blocker_fields(prior_result))
    if prior_result_match_kind:
        fallback["fallback_request"]["prior_result_match_kind"] = prior_result_match_kind
    args = dict(fallback.get("planner_probe_args") or {})
    if planner_object_id:
        args["--cleanup-planner-object-id"] = planner_object_id
    if planner_target_receptacle_id:
        args["--cleanup-planner-target-receptacle-id"] = planner_target_receptacle_id
    fallback["planner_probe_args"] = args
    binding = fallback.get("binding")
    if isinstance(binding, dict):
        binding["planner_object_id"] = planner_object_id
        binding["planner_target_receptacle_id"] = planner_target_receptacle_id
        binding["planner_probe_args"] = args
        requested = binding.get("requested_cleanup_primitive_binding")
        if isinstance(requested, dict):
            requested["planner_object_id"] = planner_object_id
            requested["planner_target_receptacle_id"] = planner_target_receptacle_id
    return fallback


def _candidate_aliases(
    request: dict[str, Any],
    *,
    candidate_key: str,
    current_alias: str,
) -> list[str]:
    binding = request.get("binding") or {}
    backend_binding = (
        binding.get("backend_planner_task_binding") if isinstance(binding, dict) else {}
    )
    values = [current_alias]
    if isinstance(binding, dict):
        values.extend(str(item) for item in binding.get(candidate_key) or [])
    if isinstance(backend_binding, dict):
        values.extend(str(item) for item in backend_binding.get(candidate_key) or [])
    return _unique_nonempty_values(values)


def _executable_candidate_aliases(
    request: dict[str, Any],
    *,
    axis: str,
    candidate_key: str,
    current_alias: str,
    extra_aliases: list[str] | None = None,
    prior_filtered_aliases: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    source_request_id = str(request.get("request_id") or "")
    candidates = _unique_nonempty_values(
        [
            *_candidate_aliases(
                request,
                candidate_key=candidate_key,
                current_alias=current_alias,
            ),
            *(extra_aliases or []),
        ]
    )
    normalized = []
    if axis == "object":
        for alias in list(candidates):
            root_alias = _runtime_object_root_alias(alias)
            if not root_alias:
                continue
            normalized.append(
                {
                    "source_request_id": source_request_id,
                    "axis": axis,
                    "alias": alias,
                    "normalized_alias": root_alias,
                    "reason": "pickup_root_variant_normalized",
                    "evidence_note": (
                        "Normalized a non-root MolmoSpaces runtime pickup alias to "
                        "the variant-0 root-body alias before command generation."
                    ),
                }
            )
            if root_alias not in candidates:
                candidates.append(root_alias)
    executable = []
    filtered = []
    prior_filters = prior_filtered_aliases or {}
    for alias in candidates:
        prior_filter = prior_filters.get(alias)
        if prior_filter:
            filtered.append(dict(prior_filter))
            continue
        if axis == "object" and _is_non_root_runtime_object_alias(alias):
            filtered.append(
                {
                    "source_request_id": source_request_id,
                    "axis": axis,
                    "alias": alias,
                    "reason": "not_pickup_root_body_alias",
                    "evidence_note": (
                        "Filtered before command generation because pickup aliases "
                        "matching the MolmoSpaces runtime pattern must use variant 0 "
                        "to refer to a root body."
                    ),
                }
            )
            continue
        if _is_exact_scene_planner_alias(alias):
            executable.append(alias)
            continue
        filtered.append(
            {
                "source_request_id": source_request_id,
                "axis": axis,
                "alias": alias,
                "reason": "not_exact_scene_runtime_alias",
                "evidence_note": (
                    "Filtered before command generation because upstream/display aliases "
                    "with '|' fail exact-scene task sampling with KeyError."
                ),
            }
        )
    return executable, filtered, normalized


def _is_exact_scene_planner_alias(alias: str) -> bool:
    return bool(alias) and "|" not in alias


def _is_non_root_runtime_object_alias(alias: str) -> bool:
    match = _RUNTIME_ALIAS_RE.match(alias)
    return bool(match and match.group("variant") != "0")


def _runtime_object_root_alias(alias: str) -> str:
    match = _RUNTIME_ALIAS_RE.match(alias)
    if not match or match.group("variant") == "0":
        return ""
    return f"{match.group('prefix')}_{match.group('group')}_0_{match.group('room')}"
