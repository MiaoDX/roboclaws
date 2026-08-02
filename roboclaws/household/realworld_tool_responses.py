from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract

from roboclaws.household import realworld_runtime_map_targets
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE


def public_fixture_response_id(
    contract: HouseholdRuntimeContract,
    internal_fixture_id: str,
    requested_fixture_id: str,
) -> str:
    if requested_fixture_id.startswith("anchor_"):
        return requested_fixture_id
    return realworld_runtime_map_targets.public_fixture_reference_id(
        contract,
        internal_fixture_id,
    )


def public_manipulation_response(
    contract: HouseholdRuntimeContract,
    tool: str,
    handle: str,
    response: dict[str, Any],
    *,
    fixture_id: str | None = None,
    navigate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "object_id": handle,
        "primitive_provenance": response.get("primitive_provenance", API_SEMANTIC_PROVENANCE),
        "state_mutation": response.get("state_mutation"),
    }
    if fixture_id is not None:
        payload["fixture_id"] = fixture_id
        payload["receptacle_id"] = fixture_id
    if navigate is not None:
        payload["navigation_status"] = navigate.get("status")
    if response.get("location_relation") is not None:
        payload["location_relation"] = response.get("location_relation")
    if response.get("previous_location_id") is not None:
        payload["previous_location_id"] = response.get("previous_location_id")
        payload["source_receptacle_id"] = response.get("previous_location_id")
    if response.get("location_id") is not None:
        payload["location_id"] = response.get("location_id")
    if response.get("contained_in") is not None:
        payload["contained_in"] = response.get("contained_in")
    if response.get("placement_diagnostic") is not None:
        payload["placement_diagnostic"] = response.get("placement_diagnostic")
    if response.get("ok"):
        return contract._ok(tool, **payload)
    return contract._error(
        tool,
        str(response.get("error_reason", "error")),
        object_id=handle,
    )


def public_fixture_response(
    contract: HouseholdRuntimeContract,
    tool: str,
    fixture_id: str,
    response: dict[str, Any],
    *,
    object_id: str | None = None,
) -> dict[str, Any]:
    if not response.get("ok"):
        return contract._error(
            tool,
            str(response.get("error_reason", "error")),
            fixture_id=fixture_id,
        )
    return contract._ok(
        tool,
        fixture_id=fixture_id,
        receptacle_id=fixture_id,
        object_id=object_id if object_id is not None else contract._held_handle,
        primitive_provenance=response.get("primitive_provenance", API_SEMANTIC_PROVENANCE),
        opened=response.get("opened"),
        closed=response.get("closed"),
        state_mutation=response.get("state_mutation"),
    )


def public_error_from_private(
    contract: HouseholdRuntimeContract,
    tool: str,
    handle: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    return contract._error(
        tool,
        str(response.get("error_reason", "error")),
        object_id=handle,
    )


def semantic_order_error(
    contract: HouseholdRuntimeContract,
    tool: str,
    *,
    required_tool: str,
    semantic_loop_variant: str,
    object_id: str | None = None,
    fixture_id: str | None = None,
    recovery_hint: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "required_tool": required_tool,
        "semantic_loop_variant": semantic_loop_variant,
        "recovery_hint": recovery_hint,
    }
    if object_id is not None:
        payload["object_id"] = object_id
    if fixture_id is not None:
        payload["fixture_id"] = fixture_id
        payload["receptacle_id"] = fixture_id
    return contract._error(tool, "semantic_order", **payload)
