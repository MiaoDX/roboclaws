from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract

from roboclaws.household import (
    realworld_runtime_map_contract,
    realworld_visual_candidates,
)
from roboclaws.household.realworld_contract_fixture_projection import (
    _OBJECT_CATEGORY_TARGETS,
    _anchor_affordances_for_fixture,
    _first_matching_fixture,
    _fixture_requires_open,
    _is_place_anchor,
    _semantic_anchor_type_for_fixture,
)

RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"

TARGET_ACTIONABILITY_VISIBLE_ONLY = "visible_only"
TARGET_ACTIONABILITY_ANCHOR_UNBOUND = "anchor_unbound"
TARGET_ACTIONABILITY_NEEDS_OBSERVE = "needs_observe"
TARGET_ACTIONABILITY_ACTIONABLE = "actionable"

POSE_ROLE_INSPECTION_WAYPOINT = "inspection_waypoint"
POSE_ROLE_BEST_VIEW_POSE = "best_view_pose"
LOCALIZATION_STATUS_VIEWPOINT_ONLY = "viewpoint_only"

CANDIDATE_STATE_VISUAL_SCAN_REQUIRED = (
    realworld_visual_candidates.CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
)

_float_or_zero = realworld_visual_candidates._float_or_zero


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def runtime_public_semantic_anchors(
    contract: HouseholdRuntimeContract,
    *,
    assert_no_forbidden_agent_view_keys: Any = None,
) -> list[dict[str, Any]]:
    from roboclaws.household.runtime_map_target_projection import (
        _append_fixture_public_semantic_anchors,
        _append_generated_public_semantic_anchors,
        _append_prior_public_semantic_anchors,
    )

    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    _append_generated_public_semantic_anchors(
        contract,
        anchors=anchors,
        seen=seen,
    )
    _append_fixture_public_semantic_anchors(contract, anchors=anchors, seen=seen)
    _append_prior_public_semantic_anchors(contract, anchors=anchors, seen=seen)
    if assert_no_forbidden_agent_view_keys is not None:
        for anchor in anchors:
            assert_no_forbidden_agent_view_keys(anchor)
    return anchors


def seed_public_fixture_anchor_ids_from_prior_anchors(contract: HouseholdRuntimeContract) -> None:
    for anchor in contract._runtime_map_anchor_priors:
        anchor_id = str(anchor.get("anchor_id") or "")
        if not _is_place_anchor(anchor) or not anchor_id:
            continue
        fixture_id = _best_internal_fixture_for_prior_anchor(contract, anchor)
        if fixture_id:
            contract._public_anchor_ids_by_private_fixture_id.setdefault(fixture_id, anchor_id)


def seed_public_fixture_anchor_ids_for_waypoint(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
) -> None:
    private_waypoint = contract._private_waypoint_for_public_waypoint(waypoint)
    for fixture_id in private_waypoint.get("fixture_ids") or []:
        fixture_id = str(fixture_id or "")
        if fixture_id and fixture_id in contract._fixtures:
            public_anchor_id_for_fixture(contract, fixture_id)


def record_fixture_observations_for_waypoint(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
    *,
    source_observation_id: str,
    producer_type: str,
    producer_id: str,
) -> list[dict[str, Any]]:
    public_waypoint_id = str(waypoint.get("waypoint_id") or contract._current_waypoint_id)
    room_id = str(waypoint.get("room_id") or "")
    rows = []
    for fixture_id in _fixture_ids_for_public_waypoint(contract, waypoint):
        fixture = contract._fixtures.get(fixture_id)
        if not fixture:
            continue
        anchor_id = public_anchor_id_for_fixture(contract, fixture_id)
        row = {
            "fixture_id": fixture_id,
            "anchor_id": anchor_id,
            "category": str(fixture.get("category") or fixture.get("name") or "fixture"),
            "label": str(fixture.get("category") or fixture.get("name") or "Observed fixture"),
            "anchor_type": _semantic_anchor_type_for_fixture(fixture),
            "room_id": room_id or str(fixture.get("room_id") or fixture.get("room_area") or ""),
            "waypoint_id": public_waypoint_id,
            "source_observation_id": str(source_observation_id),
            "producer_type": str(producer_type),
            "producer_id": str(producer_id),
            "confidence": 0.68,
            "private_truth_included": False,
        }
        if not row["anchor_id"]:
            continue
        contract._fixture_observations_by_fixture_id[fixture_id] = row
        rows.append(dict(row))
    return rows


def _fixture_ids_for_public_waypoint(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
) -> list[str]:
    private_waypoint = contract._private_waypoint_for_public_waypoint(waypoint)
    waypoint_id = str(waypoint.get("waypoint_id") or private_waypoint.get("waypoint_id") or "")
    fixture_ids = {str(item) for item in private_waypoint.get("fixture_ids") or [] if str(item)}
    for fixture_id in contract._fixtures:
        if public_waypoint_id_for_private_fixture(contract, fixture_id) == waypoint_id:
            fixture_ids.add(str(fixture_id))
    return sorted(fixture_ids)


def public_runtime_fixture_candidates(
    contract: HouseholdRuntimeContract,
    *,
    include_runtime_backend_fixtures: bool = False,
    assert_no_forbidden_agent_view_keys: Any = None,
) -> list[dict[str, Any]]:
    candidates = []
    seen: set[str] = set()
    for anchor in runtime_public_semantic_anchors(contract):
        if not _is_place_anchor(anchor):
            continue
        anchor_id = str(anchor.get("anchor_id") or "")
        if not anchor_id:
            continue
        fixture_id = internal_fixture_id_for_public_anchor(
            contract,
            anchor_id,
        )
        fixture = contract._fixtures.get(fixture_id) if fixture_id else {}
        category = str(anchor.get("category") or (fixture or {}).get("category") or "")
        name = str(anchor.get("label") or (fixture or {}).get("name") or category or anchor_id)
        waypoint_id = str(
            anchor.get("waypoint_id")
            or (
                public_waypoint_for_private_fixture(
                    contract,
                    fixture_id,
                ).get("waypoint_id")
                if fixture_id
                else ""
            )
            or contract._current_waypoint_id
        )
        waypoint = contract._waypoint_by_id(waypoint_id) or {}
        pose = dict(anchor.get("pose") or contract._waypoint_pose(waypoint))
        item = {
            "fixture_id": anchor_id,
            "receptacle_id": anchor_id,
            "category": category,
            "name": name,
            "room_id": str(anchor.get("room_id") or waypoint.get("room_id") or ""),
            "affordances": list(anchor.get("affordances") or []),
            "pose": {"frame_id": "map", **pose},
            "preferred_inspection_waypoint_id": waypoint_id,
            "preferred_manipulation_waypoint_id": waypoint_id,
            "public_fixture_source": "runtime_semantic_anchor",
        }
        if assert_no_forbidden_agent_view_keys is not None:
            assert_no_forbidden_agent_view_keys(item)
        candidates.append(item)
        seen.add(anchor_id)
    if not include_runtime_backend_fixtures:
        return candidates
    for fixture_id in sorted(contract._fixtures):
        fixture = contract._fixtures[fixture_id]
        anchor_id = public_anchor_id_for_fixture(contract, fixture_id)
        if not anchor_id or anchor_id in seen:
            continue
        item = _public_runtime_fixture_candidate_from_fixture(
            contract,
            fixture_id=fixture_id,
            fixture=fixture,
            anchor_id=anchor_id,
        )
        if assert_no_forbidden_agent_view_keys is not None:
            assert_no_forbidden_agent_view_keys(item)
        candidates.append(item)
        seen.add(anchor_id)
    return candidates


def _public_runtime_fixture_candidate_from_fixture(
    contract: HouseholdRuntimeContract,
    *,
    fixture_id: str,
    fixture: dict[str, Any],
    anchor_id: str,
) -> dict[str, Any]:
    waypoint_id = public_waypoint_id_for_private_fixture(contract, fixture_id)
    waypoint = contract._waypoint_by_id(waypoint_id) or {}
    pose = contract._waypoint_pose(waypoint)
    category = str(fixture.get("category") or fixture.get("name") or fixture_id)
    name = str(fixture.get("name") or category or fixture_id)
    return {
        "fixture_id": anchor_id,
        "receptacle_id": anchor_id,
        "category": category,
        "name": name,
        "room_id": str(waypoint.get("room_id") or fixture.get("room_id") or ""),
        "affordances": _anchor_affordances_for_fixture(fixture),
        "pose": {"frame_id": "map", **pose},
        "preferred_inspection_waypoint_id": waypoint_id,
        "preferred_manipulation_waypoint_id": waypoint_id,
        "public_fixture_source": "runtime_backend_fixture_overlay",
    }


def target_fixture_for_detection(
    contract: HouseholdRuntimeContract,
    detection: dict[str, Any],
    static_fixture_projection: dict[str, Any],
    *,
    include_runtime_backend_fixtures: bool = False,
) -> dict[str, Any] | None:
    return runtime_anchor_target_fixture_for_detection(
        contract,
        detection,
        include_runtime_backend_fixtures=include_runtime_backend_fixtures,
    )


def resolve_runtime_anchor_target_fixture_id(
    contract: HouseholdRuntimeContract,
    category: str,
    *,
    include_runtime_backend_fixtures: bool = False,
) -> str:
    pseudo_detection = {
        "category": category,
        "name": category,
        "support_estimate": {"fixture_id": ""},
    }
    target = runtime_anchor_target_fixture_for_detection(
        contract,
        pseudo_detection,
        include_runtime_backend_fixtures=include_runtime_backend_fixtures,
    )
    return str((target or {}).get("fixture_id") or "")


def public_fixture_reference_payload(
    contract: HouseholdRuntimeContract,
    value: Any,
) -> Any:
    fixture_keys = {
        "fixture_id",
        "receptacle_id",
        "source_fixture_id",
        "target_fixture_id",
        "candidate_fixture_id",
        "expected_fixture_id",
        "requested_source_fixture_id",
        "source_receptacle_id",
        "previous_receptacle_id",
    }
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in fixture_keys and isinstance(item, str):
                result[key] = public_fixture_reference_id(
                    contract,
                    item,
                )
            elif key == "fixture_ids" and isinstance(item, list):
                result[key] = [
                    public_fixture_reference_id(
                        contract,
                        str(raw_item),
                    )
                    for raw_item in item
                ]
            else:
                result[key] = public_fixture_reference_payload(
                    contract,
                    item,
                )
        return result
    if isinstance(value, list):
        return [
            public_fixture_reference_payload(
                contract,
                item,
            )
            for item in value
        ]
    return value


def public_fixture_reference_id(
    contract: HouseholdRuntimeContract,
    fixture_id: str,
) -> str:
    if not fixture_id:
        return fixture_id
    if fixture_id.startswith("anchor_"):
        return fixture_id
    return public_anchor_id_for_fixture(contract, fixture_id)


def public_anchor_id_for_fixture(contract: HouseholdRuntimeContract, fixture_id: str) -> str:
    fixture_id = str(fixture_id or "")
    if not fixture_id:
        return ""
    anchor_id = contract._public_anchor_ids_by_private_fixture_id.get(fixture_id)
    if anchor_id:
        return anchor_id
    allocation_key = _fixture_anchor_allocation_key(contract, fixture_id)
    for mapped_fixture_id, mapped_anchor_id in sorted(
        contract._public_anchor_ids_by_private_fixture_id.items()
    ):
        if not mapped_anchor_id:
            continue
        if _fixture_anchor_allocation_key(contract, mapped_fixture_id) == allocation_key:
            contract._public_anchor_ids_by_private_fixture_id[fixture_id] = mapped_anchor_id
            return mapped_anchor_id
    used_anchor_ids = set(contract._public_anchor_ids_by_private_fixture_id.values())
    used_anchor_ids.update(
        str(anchor.get("anchor_id") or "") for anchor in contract._runtime_map_anchor_priors
    )
    index = len(contract._public_anchor_ids_by_private_fixture_id) + 1
    while f"anchor_fixture_{index:03d}" in used_anchor_ids:
        index += 1
    anchor_id = f"anchor_fixture_{index:03d}"
    contract._public_anchor_ids_by_private_fixture_id[fixture_id] = anchor_id
    return anchor_id


def _fixture_anchor_allocation_key(
    contract: HouseholdRuntimeContract,
    fixture_id: str,
) -> tuple[str, str, str]:
    fixture = getattr(contract, "_fixtures", {}).get(fixture_id) or {}
    return (
        _semantic_anchor_type_for_fixture(fixture),
        _norm(str(fixture.get("category") or fixture.get("name") or fixture_id)),
        public_waypoint_id_for_private_fixture(contract, fixture_id)
        if hasattr(contract, "_preferred_waypoint_for_fixture")
        else "",
    )


def internal_fixture_id_for_public_reference(
    contract: HouseholdRuntimeContract,
    fixture_id: str | None,
) -> str | None:
    if fixture_id is None:
        return None
    resolved = internal_fixture_id_for_public_anchor(
        contract,
        str(fixture_id),
    )
    return resolved or str(fixture_id)


def internal_fixture_id_for_public_anchor(
    contract: HouseholdRuntimeContract,
    anchor_id: str,
) -> str:
    if not anchor_id:
        return ""
    for fixture_id, public_anchor_id in contract._public_anchor_ids_by_private_fixture_id.items():
        if public_anchor_id == anchor_id:
            return fixture_id
    anchor = next(
        (
            item
            for item in runtime_public_semantic_anchors(contract)
            if str(item.get("anchor_id") or "") == anchor_id
        ),
        {},
    )
    if not _is_place_anchor(anchor):
        return ""
    fixture_id = (
        _best_internal_fixture_for_prior_anchor(contract, anchor)
        if _is_prior_runtime_anchor(anchor)
        else best_internal_fixture_for_anchor(contract, anchor)
    )
    if fixture_id:
        contract._public_anchor_ids_by_private_fixture_id.setdefault(fixture_id, anchor_id)
    return fixture_id


def public_waypoint_for_private_fixture(
    contract: HouseholdRuntimeContract,
    fixture_id: str,
) -> dict[str, Any]:
    private_waypoint_id = contract._preferred_waypoint_for_fixture(fixture_id)
    private_waypoint = next(
        (
            item
            for item in contract._waypoints
            if str(item.get("waypoint_id") or "") == private_waypoint_id
        ),
        {},
    )
    for public_id, mapped in contract._private_waypoint_by_public_id.items():
        if str(mapped.get("waypoint_id") or "") == str(private_waypoint.get("waypoint_id") or ""):
            return contract._waypoint_by_id(public_id) or {}
    return contract._waypoint_by_id(contract._current_waypoint_id) or {}


def public_waypoint_id_for_private_fixture(
    contract: HouseholdRuntimeContract,
    fixture_id: str,
) -> str:
    waypoint = public_waypoint_for_private_fixture(contract, fixture_id)
    public_waypoint_id = str(waypoint.get("waypoint_id") or "")
    return public_waypoint_id or contract._current_waypoint_id


def best_internal_fixture_for_anchor(
    contract: HouseholdRuntimeContract,
    anchor: dict[str, Any],
) -> str:
    category = str(anchor.get("category") or "")
    waypoint_id = str(anchor.get("waypoint_id") or "")
    public_waypoint = contract._waypoint_by_id(waypoint_id) or {}
    private_waypoint = contract._private_waypoint_for_public_waypoint(public_waypoint)
    fixture_ids = [str(item) for item in private_waypoint.get("fixture_ids") or []]
    for fixture_id in fixture_ids:
        fixture = contract._fixtures.get(fixture_id, {})
        if _norm(category) and _norm(category) in _norm(
            " ".join(str(fixture.get(key, "")) for key in ("fixture_id", "category", "name"))
        ):
            return fixture_id
    for fixture_id, public_anchor_id in contract._public_anchor_ids_by_private_fixture_id.items():
        if public_anchor_id == str(anchor.get("anchor_id") or ""):
            return fixture_id
    for fixture_id, fixture in contract._fixtures.items():
        if _norm(category) and _norm(category) in _norm(
            " ".join(str(fixture.get(key, "")) for key in ("fixture_id", "category", "name"))
        ):
            return fixture_id
    return ""


def _best_internal_fixture_for_prior_anchor(
    contract: HouseholdRuntimeContract,
    anchor: dict[str, Any],
) -> str:
    """Bind prior anchors only when the local waypoint evidence agrees."""

    category = str(anchor.get("category") or "")
    if not _norm(category):
        return ""
    waypoint_id = str(anchor.get("waypoint_id") or "")
    public_waypoint = contract._waypoint_by_id(waypoint_id) or {}
    private_waypoint = contract._private_waypoint_for_public_waypoint(public_waypoint)
    for fixture_id in [str(item) for item in private_waypoint.get("fixture_ids") or []]:
        fixture = contract._fixtures.get(fixture_id, {})
        if _anchor_category_matches_fixture(category, fixture, fixture_id):
            return fixture_id
    for fixture_id, fixture in contract._fixtures.items():
        if public_waypoint_id_for_private_fixture(contract, fixture_id) != waypoint_id:
            continue
        if _anchor_category_matches_fixture(category, fixture, fixture_id):
            return fixture_id
    return ""


def _is_prior_runtime_anchor(anchor: dict[str, Any]) -> bool:
    return (
        str(anchor.get("freshness") or "") == "prior"
        or str(anchor.get("promotion_status") or "") == "prior_runtime_snapshot"
    )


def _anchor_category_matches_fixture(
    category: str,
    fixture: dict[str, Any],
    fixture_id: str,
) -> bool:
    return _norm(category) in _norm(
        " ".join(str(fixture.get(key, "")) for key in ("fixture_id", "category", "name"))
        or fixture_id
    )


def runtime_anchor_target_fixture_for_detection(
    contract: HouseholdRuntimeContract,
    detection: dict[str, Any],
    *,
    include_runtime_backend_fixtures: bool = False,
) -> dict[str, Any] | None:
    public_runtime_fixtures = public_runtime_fixture_candidates(
        contract,
        include_runtime_backend_fixtures=include_runtime_backend_fixtures,
    )
    public_hints = {
        "rooms": [
            {
                "room_id": "runtime_semantic_anchors",
                "room_label": "Runtime semantic anchors",
                "fixtures": public_runtime_fixtures,
            }
        ]
    }
    inferred = realworld_runtime_map_contract.infer_target_fixture_for_detection(
        detection,
        public_hints,
        norm=_norm,
        object_category_targets=_OBJECT_CATEGORY_TARGETS,
        first_matching_fixture=_first_matching_fixture,
        fixture_requires_open=_fixture_requires_open,
    )
    if inferred is not None:
        return inferred
    requested = internal_fixture_id_for_public_reference(
        contract,
        str((detection.get("support_estimate") or {}).get("fixture_id") or ""),
    )
    if not requested:
        return None
    for fixture in public_runtime_fixtures:
        if (
            internal_fixture_id_for_public_reference(
                contract,
                str(fixture.get("fixture_id") or ""),
            )
            == requested
        ):
            return fixture
    return None
