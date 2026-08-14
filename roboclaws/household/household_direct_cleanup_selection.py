"""Direct cleanup destination selection and placed-state reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.household.realworld_done_readiness import destination_options_for_policy


@dataclass(frozen=True)
class VisibleObjectCandidate:
    detection: dict[str, Any]
    target_fixture: dict[str, Any]
    support: dict[str, Any]
    target_fixture_id: str
    view_index: int


def visible_object_candidate(
    *, detection: dict[str, Any], target_fixture: dict[str, Any], view_index: int
) -> VisibleObjectCandidate:
    return VisibleObjectCandidate(
        detection=detection,
        target_fixture=target_fixture,
        support=detection.get("support_estimate") or {},
        target_fixture_id=str(target_fixture["fixture_id"]),
        view_index=view_index,
    )


def direct_policy_target_fixture(
    *,
    contract: HouseholdRuntimeContract,
    detection: dict[str, Any],
) -> dict[str, Any] | None:
    inferred = contract.target_fixture_for_detection(
        detection,
        include_runtime_backend_fixtures=True,
    )
    if not contract.sanitize_world_labels:
        return inferred
    options = destination_options_for_policy(
        contract,
        detection.get("destination_policy") or {},
    )
    source_fixture_id = str((detection.get("support_estimate") or {}).get("fixture_id") or "")
    inferred_fixture_id = str((inferred or {}).get("fixture_id") or "")
    option_fixture_ids = {str(item.get("candidate_fixture_id") or "") for item in options}
    if inferred_fixture_id and (
        inferred_fixture_id != source_fixture_id or source_fixture_id in option_fixture_ids
    ):
        return inferred
    selected = _preferred_public_destination_option(detection, options)
    if selected is None:
        return inferred
    return contract.target_fixture_for_detection(
        {**detection, **selected},
        include_runtime_backend_fixtures=True,
    )


def _preferred_public_destination_option(
    detection: dict[str, Any], options: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if not options:
        return None
    source_fixture_id = str((detection.get("support_estimate") or {}).get("fixture_id") or "")
    source_waypoint_id = str(
        detection.get("waypoint_id")
        or detection.get("last_waypoint_id")
        or (detection.get("support_estimate") or {}).get("waypoint_id")
        or ""
    )
    return dict(
        min(
            options,
            key=lambda item: (
                str(item.get("candidate_fixture_id") or "") != source_fixture_id,
                str(item.get("waypoint_id") or "") != source_waypoint_id,
            ),
        )
    )


def current_worklist_target_fixture(
    *, contract: HouseholdRuntimeContract, object_id: str, source_fixture_id: str
) -> dict[str, Any] | None:
    worklist = contract.cleanup_worklist_payload()
    for item in worklist.get("objects", []):
        if str(item.get("object_id") or "") != object_id:
            continue
        candidate_fixture_id = str(item.get("candidate_fixture_id") or "")
        if not candidate_fixture_id or candidate_fixture_id == source_fixture_id:
            return None
        target = contract.public_receptacles_by_id().get(candidate_fixture_id)
        return dict(target) if target else None
    return None


def redirect_if_already_on_inferred_fixture(
    *,
    contract: HouseholdRuntimeContract,
    handle: str,
    candidate: VisibleObjectCandidate,
    agent_scratchpad: dict[str, Any],
) -> VisibleObjectCandidate | None:
    if candidate.support.get("fixture_id") != candidate.target_fixture_id:
        return candidate
    refreshed_target = current_worklist_target_fixture(
        contract=contract,
        object_id=handle,
        source_fixture_id=str(candidate.support.get("fixture_id") or ""),
    )
    if refreshed_target is None:
        contract._handled_handles.add(handle)  # noqa: SLF001
        contract._set_handle_state(  # noqa: SLF001
            handle,
            "placed",
            tool="direct_policy_reconciliation",
            resolution="already_on_inferred_fixture",
        )
        agent_scratchpad["notes"].append(
            {"object_id": handle, "reason": "already_on_inferred_fixture"}
        )
        return None
    return visible_object_candidate(
        detection=candidate.detection,
        target_fixture=refreshed_target,
        view_index=candidate.view_index,
    )
