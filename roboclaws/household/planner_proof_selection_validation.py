from __future__ import annotations

from typing import Any

from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_REQUEST_SELECTION_SCHEMA,
)


def assert_proof_request_selection(
    selection: dict[str, Any],
    commands: list[dict[str, Any]],
) -> None:
    assert selection.get("schema") == PLANNER_PROOF_REQUEST_SELECTION_SCHEMA, selection
    selected_ids = [str(item) for item in selection.get("selected_request_ids") or []]
    command_ids = [str(item.get("request_id") or "") for item in commands]
    assert selected_ids == command_ids, selection
    assert int(selection.get("selected_count") or 0) == len(command_ids), selection
    _assert_request_filter(selection)
    _assert_selected_and_excluded_requests(selection)
    _assert_feasibility_blockers(selection)
    _assert_fallback_generation(selection, selected_ids)


def assert_selection_requirements(
    selection: dict[str, Any],
    *,
    min_selected_requests: int | None,
    max_selected_requests: int | None,
    require_prior_covered_exclusion: bool,
) -> None:
    selected_count = int(selection.get("selected_count") or 0)
    if min_selected_requests is not None:
        assert selected_count >= min_selected_requests, selection
    if max_selected_requests is not None:
        assert selected_count <= max_selected_requests, selection
    if not require_prior_covered_exclusion:
        return
    excluded = selection.get("excluded_requests") or []
    covered = [
        item
        for item in excluded
        if isinstance(item, dict) and item.get("reason") == "prior_planner_proof_covered"
    ]
    assert covered, selection
    assert int(selection.get("covered_request_count") or 0) == len(covered), selection


def generated_fallback_request_count(selection: dict[str, Any]) -> int:
    fallback_generation = selection.get("fallback_generation") or {}
    if not isinstance(fallback_generation, dict):
        return 0
    return int(fallback_generation.get("generated_request_count") or 0)


def _assert_request_filter(selection: dict[str, Any]) -> None:
    request_filter = selection.get("request_filter") or {}
    if not isinstance(request_filter, dict) or not request_filter.get("enabled"):
        return
    requested = [str(item) for item in request_filter.get("requested_request_ids") or []]
    matched = [str(item) for item in request_filter.get("matched_request_ids") or []]
    unavailable = [str(item) for item in request_filter.get("unavailable_request_ids") or []]
    assert int(request_filter.get("requested_count") or 0) == len(requested), selection
    assert int(request_filter.get("matched_count") or 0) == len(matched), selection
    assert int(request_filter.get("unavailable_count") or 0) == len(unavailable), selection


def _assert_selected_and_excluded_requests(
    selection: dict[str, Any],
) -> None:
    for item in selection.get("selected_requests") or []:
        for key in ("request_id", "object_id", "target_receptacle_id"):
            assert item.get(key), item
    for item in selection.get("excluded_requests") or []:
        for key in ("request_id", "reason", "prior_task_feasibility_status"):
            assert item.get(key), item


def _assert_feasibility_blockers(selection: dict[str, Any]) -> None:
    target_feasibility_blockers = selection.get("target_feasibility_blockers") or []
    if "target_feasibility_blocker_count" in selection:
        assert int(selection.get("target_feasibility_blocker_count") or 0) == len(
            target_feasibility_blockers
        ), selection
    grasp_feasibility_blockers = selection.get("grasp_feasibility_blockers") or []
    if "grasp_feasibility_blocker_count" in selection:
        assert int(selection.get("grasp_feasibility_blocker_count") or 0) == len(
            grasp_feasibility_blockers
        ), selection
    _assert_target_feasibility_blockers(target_feasibility_blockers)
    _assert_grasp_feasibility_blockers(grasp_feasibility_blockers)


def _assert_target_feasibility_blockers(blockers: list[dict[str, Any]]) -> None:
    for item in blockers:
        for key in ("kind", "source_request_id", "reason", "prior_task_feasibility_status"):
            assert item.get(key), item


def _assert_grasp_feasibility_blockers(blockers: list[dict[str, Any]]) -> None:
    for item in blockers:
        for key in ("kind", "source_request_id", "prior_task_feasibility_blocker_summary"):
            assert item.get(key), item


def _assert_fallback_generation(
    selection: dict[str, Any],
    selected_ids: list[str],
) -> None:
    fallback_generation = selection.get("fallback_generation") or {}
    if not fallback_generation:
        return
    fallback_status = str(fallback_generation.get("status") or "")
    assert fallback_status in {"disabled", "not_required", "generated", "exhausted"}, (
        fallback_generation
    )
    generated = fallback_generation.get("generated_requests") or []
    filtered_aliases = fallback_generation.get("filtered_aliases") or []
    discovered_aliases = fallback_generation.get("discovered_aliases") or []
    filtered_pairs = fallback_generation.get("filtered_pairs") or []
    normalized_aliases = fallback_generation.get("normalized_aliases") or []
    exhaustion_blockers = fallback_generation.get("exhaustion_blockers") or []
    _assert_fallback_counts(
        selection,
        fallback_generation,
        generated=generated,
        discovered_aliases=discovered_aliases,
        filtered_aliases=filtered_aliases,
        filtered_pairs=filtered_pairs,
        normalized_aliases=normalized_aliases,
        exhaustion_blockers=exhaustion_blockers,
    )
    if fallback_status == "generated":
        assert generated, fallback_generation
    if fallback_status == "exhausted":
        assert not generated, fallback_generation
        if not selected_ids:
            assert selection.get("fallback_required") is True, selection
        assert exhaustion_blockers, fallback_generation
    _assert_generated_fallback_requests(generated)
    _assert_discovered_aliases(discovered_aliases)
    _assert_filtered_aliases(filtered_aliases)
    _assert_filtered_pairs(filtered_pairs)
    _assert_exhaustion_blockers(exhaustion_blockers)
    _assert_normalized_aliases(normalized_aliases)


def _assert_fallback_counts(
    selection: dict[str, Any],
    fallback_generation: dict[str, Any],
    *,
    generated: list[dict[str, Any]],
    discovered_aliases: list[dict[str, Any]],
    filtered_aliases: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
    normalized_aliases: list[dict[str, Any]],
    exhaustion_blockers: list[dict[str, Any]],
) -> None:
    assert int(selection.get("generated_fallback_request_count") or 0) == len(generated), selection
    assert int(fallback_generation.get("discovered_alias_count") or 0) == len(discovered_aliases), (
        fallback_generation
    )
    assert int(fallback_generation.get("filtered_alias_count") or 0) == len(filtered_aliases), (
        fallback_generation
    )
    assert int(fallback_generation.get("filtered_pair_count") or 0) == len(filtered_pairs), (
        fallback_generation
    )
    assert int(fallback_generation.get("normalized_alias_count") or 0) == len(normalized_aliases), (
        fallback_generation
    )
    assert int(fallback_generation.get("exhaustion_blocker_count") or 0) == len(
        exhaustion_blockers
    ), fallback_generation


def _assert_generated_fallback_requests(
    generated: list[dict[str, Any]],
) -> None:
    for item in generated:
        fallback = item.get("fallback_request") or {}
        for key in ("request_id", "object_id", "target_receptacle_id"):
            assert item.get(key), item
        assert fallback.get("source_request_id"), item


def _assert_discovered_aliases(aliases: list[dict[str, Any]]) -> None:
    for item in aliases:
        for key in ("source_request_id", "axis", "alias", "derived_from", "reason"):
            assert item.get(key), item


def _assert_filtered_aliases(aliases: list[dict[str, Any]]) -> None:
    for item in aliases:
        for key in ("source_request_id", "axis", "alias", "reason"):
            assert item.get(key), item


def _assert_filtered_pairs(pairs: list[dict[str, Any]]) -> None:
    for item in pairs:
        for key in (
            "source_request_id",
            "object_alias",
            "target_alias",
            "derived_from",
            "reason",
        ):
            assert item.get(key), item


def _assert_exhaustion_blockers(blockers: list[dict[str, Any]]) -> None:
    for item in blockers:
        for key in ("code", "message"):
            assert item.get(key), item


def _assert_normalized_aliases(aliases: list[dict[str, Any]]) -> None:
    for item in aliases:
        for key in ("alias", "normalized_alias", "reason"):
            assert item.get(key), item
