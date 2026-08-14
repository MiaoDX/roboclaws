from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any, Protocol

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
from roboclaws.household.realworld_contract_projection import _room_category_from_label
from roboclaws.household.realworld_runtime_target_selection import safe_anchor_id

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


class RuntimeMapTargetContract(Protocol):
    perception_mode: str
    sanitize_world_labels: bool
    _camera_adjustment_events: Sequence[dict[str, Any]]
    _current_waypoint_id: str
    _detections_by_handle: Mapping[str, dict[str, Any]]
    _fixtures: dict[str, dict[str, Any]]
    _generated_inspection_waypoints: Mapping[str, dict[str, Any]]
    _inspection_observations: Sequence[dict[str, Any]]
    _fixture_observations_by_fixture_id: Mapping[str, dict[str, Any]]
    _object_lifecycle: Mapping[str, dict[str, Any]]
    _observed_waypoint_ids: Collection[str]
    _private_waypoint_by_public_id: Mapping[str, dict[str, Any]]
    _public_anchor_ids_by_private_fixture_id: dict[str, str]
    _public_waypoints: Iterable[dict[str, Any]]
    _runtime_map_anchor_priors: Iterable[dict[str, Any]]
    _waypoints: Iterable[dict[str, Any]]

    def _generated_inspection_waypoint_for_object(self, handle: str) -> dict[str, Any]: ...
    def _observation_id_for_waypoint(self, waypoint_id: str) -> str: ...
    def _private_waypoint_for_public_waypoint(self, waypoint: dict[str, Any]) -> dict[str, Any]: ...
    def _preferred_waypoint_for_fixture(self, fixture_id: str) -> str: ...
    def _public_navigation_waypoints(self) -> list[dict[str, Any]]: ...
    def _waypoint_by_id(self, waypoint_id: str) -> dict[str, Any] | None: ...
    def _waypoint_pose(self, waypoint: dict[str, Any]) -> dict[str, float]: ...
    def static_fixture_projection(self) -> dict[str, Any]: ...


def runtime_public_semantic_anchors(
    contract: RuntimeMapTargetContract,
    *,
    assert_no_forbidden_agent_view_keys: Any = None,
) -> list[dict[str, Any]]:
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


def seed_public_fixture_anchor_ids_from_prior_anchors(contract: RuntimeMapTargetContract) -> None:
    for anchor in contract._runtime_map_anchor_priors:
        anchor_id = str(anchor.get("anchor_id") or "")
        if not _is_place_anchor(anchor) or not anchor_id:
            continue
        fixture_id = _best_internal_fixture_for_prior_anchor(contract, anchor)
        if fixture_id:
            contract._public_anchor_ids_by_private_fixture_id.setdefault(fixture_id, anchor_id)


def seed_public_fixture_anchor_ids_for_waypoint(
    contract: RuntimeMapTargetContract,
    waypoint: dict[str, Any],
) -> None:
    private_waypoint = contract._private_waypoint_for_public_waypoint(waypoint)
    for fixture_id in private_waypoint.get("fixture_ids") or []:
        fixture_id = str(fixture_id or "")
        if fixture_id and fixture_id in contract._fixtures:
            public_anchor_id_for_fixture(contract, fixture_id)


def record_fixture_observations_for_waypoint(
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
    fixture_id: str,
) -> str:
    if not fixture_id:
        return fixture_id
    if fixture_id.startswith("anchor_"):
        return fixture_id
    return public_anchor_id_for_fixture(contract, fixture_id)


def public_anchor_id_for_fixture(contract: RuntimeMapTargetContract, fixture_id: str) -> str:
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
    fixture_id: str,
) -> str:
    waypoint = public_waypoint_for_private_fixture(contract, fixture_id)
    public_waypoint_id = str(waypoint.get("waypoint_id") or "")
    return public_waypoint_id or contract._current_waypoint_id


def best_internal_fixture_for_anchor(
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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
    contract: RuntimeMapTargetContract,
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


def _append_generated_public_semantic_anchors(
    contract: RuntimeMapTargetContract,
    *,
    anchors: list[dict[str, Any]],
    seen: set[str],
) -> None:
    for waypoint in contract._public_waypoints:
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if waypoint_id not in contract._observed_waypoint_ids:
            continue
        for anchor in (
            _room_area_public_semantic_anchor(contract, waypoint),
            _waypoint_public_semantic_anchor(contract, waypoint),
        ):
            anchor_id = str(anchor.get("anchor_id") or "")
            if anchor_id and anchor_id not in seen:
                anchors.append(anchor)
                seen.add(anchor_id)


def _append_fixture_public_semantic_anchors(
    contract: RuntimeMapTargetContract,
    *,
    anchors: list[dict[str, Any]],
    seen: set[str],
) -> None:
    candidates_by_anchor_id: dict[str, dict[str, Any]] = {}
    for fixture_id, anchor_id in sorted(
        contract._public_anchor_ids_by_private_fixture_id.items(),
        key=lambda item: item[1],
    ):
        anchor = _fixture_public_semantic_anchor(contract, fixture_id, anchor_id)
        if not anchor:
            continue
        current = candidates_by_anchor_id.get(anchor_id)
        if current is None or _fixture_anchor_evidence_rank(anchor) > _fixture_anchor_evidence_rank(
            current
        ):
            candidates_by_anchor_id[anchor_id] = anchor
    seen_viewpoint_keys: set[tuple[str, str, str, str, str]] = set()
    for anchor_id, anchor in sorted(candidates_by_anchor_id.items()):
        if not anchor or anchor_id in seen:
            continue
        viewpoint_key = _fixture_anchor_viewpoint_key(anchor)
        if viewpoint_key in seen_viewpoint_keys:
            continue
        anchors.append(anchor)
        seen.add(anchor_id)
        seen_viewpoint_keys.add(viewpoint_key)


def _append_prior_public_semantic_anchors(
    contract: RuntimeMapTargetContract,
    *,
    anchors: list[dict[str, Any]],
    seen: set[str],
) -> None:
    for prior_anchor in contract._runtime_map_anchor_priors:
        anchor_id = str(prior_anchor.get("anchor_id") or "")
        if anchor_id and anchor_id in seen:
            continue
        waypoint_id = str(prior_anchor.get("waypoint_id") or "")
        if waypoint_id and contract._waypoint_by_id(waypoint_id) is None:
            continue
        anchors.append(dict(prior_anchor))
        if anchor_id:
            seen.add(anchor_id)


def _room_area_public_semantic_anchor(
    contract: RuntimeMapTargetContract,
    waypoint: dict[str, Any],
) -> dict[str, Any]:
    room_id = str(waypoint.get("room_id") or "generated_area")
    room_label = str(waypoint.get("room_label") or room_id.replace("_", " ").title())
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    observation_id = contract._observation_id_for_waypoint(waypoint_id)
    return {
        "anchor_id": f"anchor_room_{safe_anchor_id(room_id)}",
        "anchor_type": "room_area",
        "category": _room_category_from_label(room_label, room_id),
        "label": room_label,
        "room_id": room_id,
        "room_label": room_label,
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_INSPECTION_WAYPOINT,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "affordances": ["navigate", "observe"],
        "aliases": [room_id, room_label],
        "producer_type": "generated_exploration_candidate",
        "producer_id": "base_metric_map_exploration",
        "confidence": 0.8 if room_label else 0.6,
        "freshness": "current_run",
        "actionability": "actionable",
        "source_observation_id": observation_id,
        "promotion_status": "run_local",
        "evidence": {
            "type": "visited_generated_area",
            "visited": True,
            "candidate_provenance": dict(waypoint.get("candidate_provenance") or {}),
        },
    }


def _waypoint_public_semantic_anchor(
    contract: RuntimeMapTargetContract,
    waypoint: dict[str, Any],
) -> dict[str, Any]:
    waypoint_id = str(waypoint.get("waypoint_id") or "")
    observation_id = contract._observation_id_for_waypoint(waypoint_id)
    return {
        "anchor_id": f"anchor_waypoint_{safe_anchor_id(waypoint_id)}",
        "anchor_type": "observation_waypoint",
        "category": "observation_waypoint",
        "label": str(waypoint.get("label") or waypoint_id),
        "room_id": str(waypoint.get("room_id") or ""),
        "room_label": str(waypoint.get("room_label") or ""),
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_INSPECTION_WAYPOINT,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "affordances": ["observe"],
        "producer_type": "generated_exploration_candidate",
        "producer_id": "base_metric_map_exploration",
        "confidence": 1.0,
        "freshness": "current_run",
        "actionability": "actionable",
        "source_observation_id": observation_id,
        "promotion_status": "run_local",
        "evidence": {
            "type": "visited_generated_exploration_candidate",
            "visited": True,
            "candidate_provenance": dict(waypoint.get("candidate_provenance") or {}),
        },
    }


def _fixture_public_semantic_anchor(
    contract: RuntimeMapTargetContract,
    fixture_id: str,
    anchor_id: str,
) -> dict[str, Any]:
    fixture = contract._fixtures.get(fixture_id)
    if fixture is None:
        return {}
    supporting = _supporting_detections_for_fixture(contract, fixture_id)
    fixture_observation = dict(contract._fixture_observations_by_fixture_id.get(fixture_id) or {})
    if not supporting and not fixture_observation:
        return {}
    best_detection = supporting[0] if supporting else {}
    best_lifecycle = contract._object_lifecycle.get(
        str(best_detection.get("object_id") or ""),
        {},
    )
    waypoint_id = str(fixture_observation.get("waypoint_id") or "")
    if not waypoint_id:
        waypoint_id = public_waypoint_id_for_private_fixture(contract, fixture_id)
    if not waypoint_id:
        waypoint_id = str(best_lifecycle.get("waypoint_id") or contract._current_waypoint_id)
    waypoint = contract._waypoint_by_id(waypoint_id) or {}
    source_observation_id = str(
        fixture_observation.get("source_observation_id")
        or contract._observation_id_for_waypoint(waypoint_id)
        or best_detection.get("source_observation_id")
        or best_lifecycle.get("source_observation_id")
    )
    confidence_values = [
        _float_or_zero(item.get("visibility_confidence"))
        or _float_or_zero((item.get("support_estimate") or {}).get("confidence"))
        for item in supporting
    ]
    confidence = max(confidence_values) if confidence_values else 0.68
    return {
        "anchor_id": anchor_id,
        "anchor_type": _semantic_anchor_type_for_fixture(fixture),
        "category": str(
            fixture_observation.get("category")
            or fixture.get("category")
            or fixture.get("name")
            or "fixture"
        ),
        "label": str(
            fixture_observation.get("label")
            or fixture.get("category")
            or fixture.get("name")
            or "Observed fixture"
        ),
        "room_id": str(
            fixture_observation.get("room_id")
            or (waypoint or {}).get("room_id")
            or fixture.get("room_id")
            or best_lifecycle.get("room_id")
            or ""
        ),
        "waypoint_id": waypoint_id,
        "pose": contract._waypoint_pose(waypoint),
        "pose_source": POSE_ROLE_INSPECTION_WAYPOINT,
        "pose_role": POSE_ROLE_BEST_VIEW_POSE,
        "localization_status": LOCALIZATION_STATUS_VIEWPOINT_ONLY,
        "affordances": _anchor_affordances_for_fixture(fixture),
        "producer_type": str(
            best_detection.get("producer_type")
            or best_detection.get("perception_source")
            or fixture_observation.get("producer_type")
            or "visible_detection"
        ),
        "producer_id": str(
            best_detection.get("producer_id")
            or best_detection.get("model_provenance")
            or best_detection.get("producer_type")
            or fixture_observation.get("producer_id")
            or "visible_detection"
        ),
        "confidence": round(float(confidence), 6),
        "freshness": "current_run",
        "actionability": "actionable",
        "source_observation_id": source_observation_id,
        "promotion_status": "run_local",
        "evidence": {
            "type": "support_estimate",
            "relation": str((best_detection.get("support_estimate") or {}).get("relation") or ""),
            "supporting_observed_object_ids": [
                str(item.get("object_id") or "") for item in supporting
            ],
            "fixture_observation_id": str(fixture_observation.get("source_observation_id") or ""),
            "image_region": (
                best_detection.get("image_region")
                or {"type": "bbox", "value": best_detection.get("image_bbox") or []}
            ),
        },
    }


def _supporting_detections_for_fixture(
    contract: RuntimeMapTargetContract,
    fixture_id: str,
) -> list[dict[str, Any]]:
    supporting = []
    for handle in sorted(contract._detections_by_handle):
        detection = contract._detections_by_handle[handle]
        support = detection.get("support_estimate") or {}
        if str(support.get("fixture_id") or "") != fixture_id:
            continue
        supporting.append(dict(detection))
    return supporting


def _fixture_anchor_evidence_rank(anchor: dict[str, Any]) -> tuple[int, int, float]:
    evidence = anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {}
    supporting_count = len(evidence.get("supporting_observed_object_ids") or [])
    image_region = (
        evidence.get("image_region") if isinstance(evidence.get("image_region"), dict) else {}
    )
    has_image_region = int(bool(image_region.get("value")))
    return (
        supporting_count,
        has_image_region,
        _float_or_zero(anchor.get("confidence")),
    )


def _fixture_anchor_viewpoint_key(anchor: dict[str, Any]) -> tuple[str, str, str, str, str]:
    pose = anchor.get("pose") if isinstance(anchor.get("pose"), dict) else {}
    pose_key = ",".join(str(round(_float_or_zero(pose.get(key)), 4)) for key in ("x", "y", "yaw"))
    return (
        str(anchor.get("category") or ""),
        str(anchor.get("room_id") or ""),
        str(anchor.get("waypoint_id") or ""),
        pose_key,
        str(anchor.get("source_observation_id") or ""),
    )


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
