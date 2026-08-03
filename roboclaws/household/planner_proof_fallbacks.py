from __future__ import annotations

import ast
import re
from typing import Any

from roboclaws.household.planner_proof_quality import planner_proof_quality_evidence

_FALLBACK_REQUEST_ID_MARKER = "_fallback_"
_INVALID_NAME_RE = re.compile(r"Invalid name '([^']+)'. Valid names: (\[.*\])")
_RUNTIME_ALIAS_RE = re.compile(r"^(?P<prefix>.+)_(?P<group>\d+)_(?P<variant>\d+)_(?P<room>\d+)$")


def _blockers(raw: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in raw if isinstance(item, dict)]


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
    fields = nonempty_prior_blocker_fields(
        result.get("task_feasibility_blocker_kind"),
        result.get("task_feasibility_blocker_summary"),
    )
    if result.get("task_feasibility_status"):
        fields["prior_task_feasibility_status"] = str(result.get("task_feasibility_status") or "")
    return fields


def nonempty_prior_blocker_fields(kind: Any, summary: Any) -> dict[str, str]:
    fields = {}
    if kind:
        fields["prior_task_feasibility_blocker_kind"] = str(kind)
    if summary:
        fields["prior_task_feasibility_blocker_summary"] = str(summary)
    return fields


def _is_exact_scene_planner_alias(alias: str) -> bool:
    return bool(alias) and "|" not in alias


def discovered_alias_values(
    discovered_aliases: dict[str, list[dict[str, Any]]],
    axis: str,
) -> list[str]:
    return [
        str(item.get("alias") or "")
        for item in discovered_aliases.get(axis, [])
        if isinstance(item, dict)
    ]


def discovered_runtime_aliases_by_source_request(
    ready_requests: list[dict[str, Any]],
    prior_summary: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    request_by_id = _request_by_id(ready_requests)
    discovered: dict[str, dict[str, list[dict[str, Any]]]] = {}
    seen: set[tuple[str, str, str]] = set()
    _add_carried_discovered_aliases(
        discovered=discovered,
        seen=seen,
        request_by_id=request_by_id,
        prior_summary=prior_summary,
    )
    _add_prior_keyerror_aliases(
        discovered=discovered,
        seen=seen,
        request_by_id=request_by_id,
        prior_summary=prior_summary,
    )
    return discovered


def _request_by_id(requests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(request.get("request_id") or ""): request
        for request in requests
        if request.get("request_id")
    }


def _add_carried_discovered_aliases(
    *,
    discovered: dict[str, dict[str, list[dict[str, Any]]]],
    seen: set[tuple[str, str, str]],
    request_by_id: dict[str, dict[str, Any]],
    prior_summary: dict[str, Any],
) -> None:
    for item in _carried_discovered_aliases(prior_summary):
        source_request_id = str(item.get("source_request_id") or "")
        axis = str(item.get("axis") or "")
        alias = str(item.get("alias") or "")
        if source_request_id not in request_by_id:
            continue
        _add_discovered_alias(
            discovered=discovered,
            seen=seen,
            source_request_id=source_request_id,
            axis=axis,
            alias=alias,
            payload=item,
        )


def _add_prior_keyerror_aliases(
    *,
    discovered: dict[str, dict[str, list[dict[str, Any]]]],
    seen: set[tuple[str, str, str]],
    request_by_id: dict[str, dict[str, Any]],
    prior_summary: dict[str, Any],
) -> None:
    for result in prior_summary.get("results") or []:
        if not isinstance(result, dict):
            continue
        source_request_id = _source_request_id_from_result(result)
        request = request_by_id.get(source_request_id)
        if not request:
            continue
        for payload in _prior_keyerror_alias_payloads(
            request=request,
            result=result,
            source_request_id=source_request_id,
        ):
            _add_discovered_alias(
                discovered=discovered,
                seen=seen,
                source_request_id=source_request_id,
                axis=str(payload.get("axis") or ""),
                alias=str(payload.get("alias") or ""),
                payload=payload,
            )


def _prior_keyerror_alias_payloads(
    *,
    request: dict[str, Any],
    result: dict[str, Any],
    source_request_id: str,
) -> list[dict[str, Any]]:
    config = proof_cleanup_task_config(result)
    payloads = []
    for invalid in _invalid_name_entries_from_blockers(result.get("blockers") or []):
        axis = _invalid_alias_axis(invalid["invalid_alias"], config)
        current_alias = _current_planner_alias(request, axis)
        for alias in _runtime_alias_siblings(current_alias, invalid["valid_names"]):
            payloads.append(
                {
                    "source_request_id": source_request_id,
                    "axis": axis,
                    "alias": alias,
                    "derived_from": str(result.get("request_id") or ""),
                    "invalid_alias": invalid["invalid_alias"],
                    "reason": "valid_name_sibling_from_prior_keyerror",
                    "evidence_note": (
                        "Derived from a prior exact-scene KeyError valid-name list "
                        "for the same runtime object or target family."
                    ),
                }
            )
    return payloads


def _current_planner_alias(request: dict[str, Any], axis: str) -> str:
    if axis == "object":
        key = "--cleanup-planner-object-id"
    elif axis == "target":
        key = "--cleanup-planner-target-receptacle-id"
    else:
        return ""
    return planner_arg(request.get("planner_probe_args") or {}, key)


def _add_discovered_alias(
    *,
    discovered: dict[str, dict[str, list[dict[str, Any]]]],
    seen: set[tuple[str, str, str]],
    source_request_id: str,
    axis: str,
    alias: str,
    payload: dict[str, Any],
) -> None:
    if axis not in {"object", "target"} or not source_request_id or not alias:
        return
    key = (source_request_id, axis, alias)
    if key in seen:
        return
    seen.add(key)
    discovered.setdefault(source_request_id, {"object": [], "target": []})[axis].append(
        dict(payload)
    )


def _carried_discovered_aliases(prior_summary: dict[str, Any]) -> list[dict[str, Any]]:
    fallback_generation = prior_summary.get("fallback_generation") or {}
    if not isinstance(fallback_generation, dict):
        return []
    return [
        dict(item)
        for item in fallback_generation.get("discovered_aliases") or []
        if isinstance(item, dict)
    ]


def prior_fallback_candidate_filters_by_source_request(
    prior_summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    filters: dict[str, dict[str, Any]] = {}
    seen_aliases: set[tuple[str, str, str]] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    _add_carried_filtered_aliases(filters, seen_aliases, prior_summary)
    _add_carried_filtered_pairs(filters, seen_pairs, prior_summary)
    _add_prior_result_candidate_filters(filters, seen_aliases, seen_pairs, prior_summary)
    return filters


def _add_carried_filtered_aliases(
    filters: dict[str, dict[str, Any]],
    seen_aliases: set[tuple[str, str, str]],
    prior_summary: dict[str, Any],
) -> None:
    for item in _carried_filtered_aliases(prior_summary):
        source_request_id = str(item.get("source_request_id") or "")
        axis = str(item.get("axis") or "")
        alias = str(item.get("alias") or "")
        if not _add_alias_filter(
            filters=filters,
            seen_aliases=seen_aliases,
            source_request_id=source_request_id,
            axis=axis,
            alias=alias,
            payload=dict(item),
        ):
            continue


def _add_carried_filtered_pairs(
    filters: dict[str, dict[str, Any]],
    seen_pairs: set[tuple[str, str, str]],
    prior_summary: dict[str, Any],
) -> None:
    for item in _carried_filtered_pairs(prior_summary):
        source_request_id = str(item.get("source_request_id") or "")
        object_alias = str(item.get("object_alias") or "")
        target_alias = str(item.get("target_alias") or "")
        _add_pair_filter(
            filters=filters,
            seen_pairs=seen_pairs,
            source_request_id=source_request_id,
            object_alias=object_alias,
            target_alias=target_alias,
            payload=dict(item),
        )


def _add_prior_result_candidate_filters(
    filters: dict[str, dict[str, Any]],
    seen_aliases: set[tuple[str, str, str]],
    seen_pairs: set[tuple[str, str, str]],
    prior_summary: dict[str, Any],
) -> None:
    for result in prior_summary.get("results") or []:
        if not isinstance(result, dict):
            continue
        _add_prior_result_candidate_filter(
            filters=filters,
            seen_aliases=seen_aliases,
            seen_pairs=seen_pairs,
            result=result,
        )


def _add_prior_result_candidate_filter(
    *,
    filters: dict[str, dict[str, Any]],
    seen_aliases: set[tuple[str, str, str]],
    seen_pairs: set[tuple[str, str, str]],
    result: dict[str, Any],
) -> None:
    result_id = str(result.get("request_id") or "")
    if _FALLBACK_REQUEST_ID_MARKER not in result_id:
        return
    source_request_id = _source_request_id_from_result(result)
    config = proof_cleanup_task_config(result)
    object_alias = str(config.get("planner_object_id") or "")
    target_alias = str(config.get("planner_target_receptacle_id") or "")
    blockers = _blockers(result.get("blockers") or [])
    if _has_non_root_body_blocker(blockers) and object_alias:
        _add_alias_filter(
            filters=filters,
            seen_aliases=seen_aliases,
            source_request_id=source_request_id,
            axis="object",
            alias=object_alias,
            payload=_prior_non_root_alias_filter(
                source_request_id=source_request_id,
                alias=object_alias,
                derived_from=result_id,
                blockers=blockers,
            ),
        )
        return
    is_task_feasibility_blocked = str(result.get("task_feasibility_status") or "") == "blocked"
    if object_alias and target_alias and is_task_feasibility_blocked:
        _add_task_feasibility_pair_filter(
            filters=filters,
            seen_pairs=seen_pairs,
            source_request_id=source_request_id,
            object_alias=object_alias,
            target_alias=target_alias,
            derived_from=result_id,
            blockers=blockers,
            result=result,
        )


def _add_alias_filter(
    *,
    filters: dict[str, dict[str, Any]],
    seen_aliases: set[tuple[str, str, str]],
    source_request_id: str,
    axis: str,
    alias: str,
    payload: dict[str, Any],
) -> bool:
    if axis not in {"object", "target"} or not source_request_id or not alias:
        return False
    key = (source_request_id, axis, alias)
    if key in seen_aliases:
        return False
    bucket = _fallback_filter_bucket(filters, source_request_id)
    bucket["aliases"][axis][alias] = payload
    seen_aliases.add(key)
    return True


def _add_pair_filter(
    *,
    filters: dict[str, dict[str, Any]],
    seen_pairs: set[tuple[str, str, str]],
    source_request_id: str,
    object_alias: str,
    target_alias: str,
    payload: dict[str, Any],
) -> bool:
    if not source_request_id or not object_alias or not target_alias:
        return False
    key = (source_request_id, object_alias, target_alias)
    if key in seen_pairs:
        return False
    _fallback_filter_bucket(filters, source_request_id)["pairs"].append(payload)
    seen_pairs.add(key)
    return True


def _fallback_filter_bucket(
    filters: dict[str, dict[str, Any]],
    source_request_id: str,
) -> dict[str, Any]:
    return filters.setdefault(
        source_request_id,
        {"aliases": {"object": {}, "target": {}}, "pairs": []},
    )


def _prior_non_root_alias_filter(
    *,
    source_request_id: str,
    alias: str,
    derived_from: str,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_request_id": source_request_id,
        "axis": "object",
        "alias": alias,
        "derived_from": derived_from,
        "reason": "prior_non_root_body_alias",
        "prior_blockers": blockers,
        "evidence_note": (
            "Filtered before command generation because a prior generated fallback "
            "proof reported that this pickup alias is not a root body."
        ),
    }


def _add_task_feasibility_pair_filter(
    *,
    filters: dict[str, dict[str, Any]],
    seen_pairs: set[tuple[str, str, str]],
    source_request_id: str,
    object_alias: str,
    target_alias: str,
    derived_from: str,
    blockers: list[dict[str, Any]],
    result: dict[str, Any],
) -> None:
    key = (source_request_id, object_alias, target_alias)
    pair_filter = _task_feasibility_pair_filter(
        source_request_id=source_request_id,
        object_alias=object_alias,
        target_alias=target_alias,
        derived_from=derived_from,
        blockers=blockers,
        result=result,
    )
    if key in seen_pairs:
        pairs = _fallback_filter_bucket(filters, source_request_id)["pairs"]
        _enrich_existing_pair_filter(pairs, key, pair_filter)
        return
    _fallback_filter_bucket(filters, source_request_id)["pairs"].append(pair_filter)
    seen_pairs.add(key)


def _task_feasibility_pair_filter(
    *,
    source_request_id: str,
    object_alias: str,
    target_alias: str,
    derived_from: str,
    blockers: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    item = {
        "source_request_id": source_request_id,
        "object_alias": object_alias,
        "target_alias": target_alias,
        "derived_from": derived_from,
        "reason": "prior_task_feasibility_blocked_pair",
        "prior_status": str(result.get("status") or ""),
        "prior_task_feasibility_status": str(result.get("task_feasibility_status") or ""),
        "prior_blockers": blockers,
        **_prior_result_evidence_fields(result),
    }
    item.update(_prior_result_blocker_fields(result))
    return item


def _enrich_existing_pair_filter(
    pairs: list[dict[str, Any]],
    key: tuple[str, str, str],
    candidate: dict[str, Any],
) -> None:
    for item in pairs:
        if (
            str(item.get("source_request_id") or ""),
            str(item.get("object_alias") or ""),
            str(item.get("target_alias") or ""),
        ) != key:
            continue
        for field in (
            "prior_status",
            "prior_task_feasibility_status",
            "prior_task_feasibility_blocker_kind",
            "prior_task_feasibility_blocker_summary",
            "prior_run_result",
            "prior_report",
            "prior_stdout",
            "prior_stderr",
            "last_worker_stage",
            "execution_attempted",
        ):
            if candidate.get(field) and not item.get(field):
                item[field] = candidate[field]
        if candidate.get("prior_blockers") and not item.get("prior_blockers"):
            item["prior_blockers"] = candidate["prior_blockers"]
        return


def _carried_filtered_aliases(prior_summary: dict[str, Any]) -> list[dict[str, Any]]:
    fallback_generation = prior_summary.get("fallback_generation") or {}
    if not isinstance(fallback_generation, dict):
        return []
    return [
        dict(item)
        for item in fallback_generation.get("filtered_aliases") or []
        if isinstance(item, dict)
    ]


def _carried_filtered_pairs(prior_summary: dict[str, Any]) -> list[dict[str, Any]]:
    fallback_generation = prior_summary.get("fallback_generation") or {}
    if not isinstance(fallback_generation, dict):
        return []
    return [
        dict(item)
        for item in fallback_generation.get("filtered_pairs") or []
        if isinstance(item, dict)
    ]


def prior_pair_filter_lookup(
    prior_filters: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    raw = prior_filters.get("pairs") if isinstance(prior_filters, dict) else []
    if not isinstance(raw, list):
        return {}
    pairs = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        object_alias = str(item.get("object_alias") or "")
        target_alias = str(item.get("target_alias") or "")
        if object_alias and target_alias:
            pairs[(object_alias, target_alias)] = dict(item)
    return pairs


def _has_non_root_body_blocker(blockers: list[dict[str, Any]]) -> bool:
    for blocker in blockers:
        code = str(blocker.get("code") or "")
        message = str(blocker.get("message") or "").lower()
        if code == "AssertionError" and "not a root body" in message:
            return True
        if "object is not a root body" in message:
            return True
    return False


def _source_request_id_from_result(result: dict[str, Any]) -> str:
    request_id = str(result.get("request_id") or "")
    return request_id.split(_FALLBACK_REQUEST_ID_MARKER, 1)[0]


def proof_cleanup_task_config(result: dict[str, Any]) -> dict[str, Any]:
    config = result.get("cleanup_task_config")
    if isinstance(config, dict):
        return config
    requested = result.get("requested_cleanup_primitive_binding")
    return requested if isinstance(requested, dict) else {}


def _invalid_name_entries_from_blockers(blockers: Any) -> list[dict[str, Any]]:
    entries = []
    for blocker in blockers:
        if not isinstance(blocker, dict):
            continue
        match = _INVALID_NAME_RE.search(str(blocker.get("message") or ""))
        if not match:
            continue
        valid_names = _valid_names_from_literal(match.group(2))
        if valid_names:
            entries.append(
                {
                    "invalid_alias": match.group(1),
                    "valid_names": valid_names,
                }
            )
    return entries


def _valid_names_from_literal(value: str) -> list[str]:
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        single_quoted = re.findall(r"'([^']+)'", value)
        double_quoted = re.findall(r'"([^"]+)"', value)
        return unique_nonempty_values([*single_quoted, *double_quoted])
    if not isinstance(parsed, list):
        return []
    return unique_nonempty_values([str(item) for item in parsed if isinstance(item, str)])


def _invalid_alias_axis(invalid_alias: str, config: dict[str, Any]) -> str:
    if invalid_alias == str(config.get("planner_object_id") or ""):
        return "object"
    if invalid_alias == str(config.get("planner_target_receptacle_id") or ""):
        return "target"
    return ""


def _runtime_alias_siblings(current_alias: str, valid_names: list[str]) -> list[str]:
    match = _RUNTIME_ALIAS_RE.match(current_alias)
    if not match:
        return []
    siblings = []
    for name in valid_names:
        candidate = _RUNTIME_ALIAS_RE.match(name)
        if (
            candidate
            and candidate.group("prefix") == match.group("prefix")
            and candidate.group("group") == match.group("group")
            and candidate.group("room") == match.group("room")
            and name != current_alias
            and _is_exact_scene_planner_alias(name)
        ):
            siblings.append(name)
    return unique_nonempty_values(siblings)


def planner_arg(args: Any, key: str) -> str:
    return str(args.get(key) or "") if isinstance(args, dict) else ""


def unique_nonempty_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
