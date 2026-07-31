#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from roboclaws.core.task_intents import (
    HOUSEHOLD_INTENT_OPEN_ENDED,
)
from roboclaws.household.household_runtime_contract import (
    HouseholdRuntimeContract,
)
from roboclaws.maps.runtime_prior_artifact import read_runtime_map_prior_artifact


def _load_runtime_map_prior(path: str | Path | None) -> dict[str, Any] | None:
    return read_runtime_map_prior_artifact(path)


def _open_ended_prior_waypoint_ids(
    *,
    runtime_map_prior: dict[str, Any] | None,
    task_prompt: str,
    goal_contract: Any | None,
    run_metadata_overrides: dict[str, Any] | None,
) -> tuple[str, ...]:
    if not runtime_map_prior:
        return ()
    sample_id = str((run_metadata_overrides or {}).get("eval_sample_id") or "")
    if not sample_id.startswith("open_ended."):
        return ()
    if str(getattr(goal_contract, "intent", "") or "") != HOUSEHOLD_INTENT_OPEN_ENDED:
        return ()
    prompt_tokens = _search_tokens(
        [
            task_prompt,
            str(getattr(goal_contract, "normalized_goal", "") or ""),
            str(getattr(goal_contract, "raw_prompt", "") or ""),
        ]
    )
    if not prompt_tokens:
        return ()
    matches: list[str] = []
    for anchor in runtime_map_prior.get("public_semantic_anchors") or []:
        if not isinstance(anchor, dict):
            continue
        waypoint_id = str(anchor.get("waypoint_id") or "")
        if not waypoint_id:
            continue
        anchor_tokens = _search_tokens(
            [
                str(anchor.get("label") or ""),
                str(anchor.get("category") or ""),
                str(anchor.get("anchor_type") or ""),
                *[str(item) for item in anchor.get("aliases") or []],
            ]
        )
        if prompt_tokens.intersection(anchor_tokens) and waypoint_id not in matches:
            matches.append(waypoint_id)
    return tuple(matches)


def _search_tokens(values: list[str]) -> set[str]:
    ignored = {
        "and",
        "area",
        "find",
        "it",
        "is",
        "report",
        "room",
        "the",
        "there",
        "to",
        "where",
    }
    tokens: set[str] = set()
    for value in values:
        for token in re.findall(r"[a-zA-Z0-9]+", value.lower()):
            if len(token) > 2 and token not in ignored:
                tokens.add(token)
    return tokens


def _prior_waypoint_filter(
    waypoint_ids: tuple[str, ...],
) -> Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None:
    if not waypoint_ids:
        return None
    priority = {waypoint_id: index for index, waypoint_id in enumerate(waypoint_ids)}

    def filter_waypoints(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            waypoints,
            key=lambda waypoint: priority.get(
                str(waypoint.get("waypoint_id") or ""),
                len(priority),
            ),
        )

    return filter_waypoints


def _open_ended_prior_stop(
    waypoint_ids: tuple[str, ...],
) -> Callable[[HouseholdRuntimeContract], bool] | None:
    if not waypoint_ids:
        return None
    priority = set(waypoint_ids)

    def stop_after_current_confirmation(contract: HouseholdRuntimeContract) -> bool:
        return bool(priority.intersection(contract._observed_waypoint_ids))  # noqa: SLF001

    return stop_after_current_confirmation


def _failed_score(contract: HouseholdRuntimeContract) -> dict[str, Any]:
    total_targets = len(contract.scenario.private_manifest.targets)
    return {
        "status": "failed",
        "restored_count": 0,
        "total_targets": total_targets,
        "success_threshold": contract.scenario.private_manifest.success_threshold,
        "restored_object_ids": [],
        "missed_object_ids": [
            target.object_id for target in contract.scenario.private_manifest.targets
        ],
        "object_results": [],
        "mess_restoration_rate": 0.0,
        "sweep_coverage_rate": 0.0,
        "disturbance_count": 0,
        "completion_status": "failed",
        "semantic_acceptability": {
            "accepted_count": 0,
            "total_targets": total_targets,
            "rate": 0.0,
            "status": "failed",
        },
    }
