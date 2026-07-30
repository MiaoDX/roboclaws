from __future__ import annotations

import copy
from typing import Any

from roboclaws.maps.navigation_memory import (
    required_xy_yaw_pose_source,
)
from roboclaws.maps.rasterize import OccupancyGrid, world_to_grid
from roboclaws.maps.runtime_prior_contracts import (
    ACTIONABLE_ANCHOR_STATUSES,
    MOVABLE_ANCHOR_TYPES,
)
from roboclaws.maps.runtime_prior_source_validation import (
    _reject_frame_drift,
    _runtime_metric_map_frame_id,
    _safe_id,
    _stable_id,
)
from roboclaws.maps.spatial_contract import (
    ALIGNMENT_STATUS_CANDIDATE,
    GEOMETRY_SOURCE_RUNTIME_OBSERVATION,
    POLYGON_ROLE_NAVIGATION_AREA,
    normalize_spatial_room,
    require_source_frame_spatial_contract,
)


def _anchor_from_navigation_memory_item(
    item: dict[str, Any],
    *,
    index: int,
    grid: OccupancyGrid,
) -> dict[str, Any]:
    item_id = str(item.get("id") or f"navigation_memory_{index:03d}")
    anchor_type = _anchor_type(item)
    nav_goal_raw = item["nav_goal"] if "nav_goal" in item else item.get("pose")
    object_pose_raw = item["pose"] if "pose" in item else item.get("nav_goal")
    nav_goal = required_xy_yaw_pose_source(
        nav_goal_raw,
        label=f"Agibot navigation memory item {item_id} nav_goal",
    )
    object_pose = required_xy_yaw_pose_source(
        object_pose_raw,
        label=f"Agibot navigation memory item {item_id} pose",
    )
    reachability = _reachability_status(nav_goal, grid=grid)
    classification_status = _classification_status(item, anchor_type=anchor_type)
    actionability = _actionability(anchor_type, reachability["status"], classification_status)
    waypoint_id = _stable_id("wp", item_id)
    affordances = _affordances(item, anchor_type=anchor_type)
    anchor_id = item_id if item_id.startswith("anchor_") else f"anchor_{_safe_id(item_id)}"
    evidence = {
        "type": "agibot_navigation_memory_entry",
        "source": str(item.get("source") or ""),
        "evidence": copy.deepcopy(item.get("evidence") or {}),
        "successful_run_count": len(item.get("successful_runs") or []),
        "notes": str(item.get("notes") or ""),
    }
    materialization = {
        "waypoint": {
            "waypoint_id": waypoint_id,
            "frame_id": "map",
            **nav_goal,
            "anchor_id": anchor_id,
            "anchor_type": anchor_type,
            "label": str(item.get("label") or item_id),
            "room_id": _room_id(item, anchor_type=anchor_type),
            "room_label": _room_label(item, anchor_type=anchor_type),
            "waypoint_source": "agibot_navigation_memory_conversion",
            "actionability": actionability,
            "reachability_status": reachability["status"],
            "costmap_cell": reachability["cell"],
            "costmap_value": reachability["costmap_value"],
        },
        "fixture_candidate": _fixture_candidate(
            anchor_id=anchor_id,
            waypoint_id=waypoint_id,
            item=item,
            anchor_type=anchor_type,
            affordances=affordances,
            actionability=actionability,
            enabled=anchor_type not in MOVABLE_ANCHOR_TYPES
            and anchor_type not in {"landmark", "room_area"},
        ),
    }
    return {
        "anchor_id": anchor_id,
        "source_anchor_id": item_id,
        "anchor_type": anchor_type,
        "category": _category(item, anchor_type=anchor_type),
        "label": str(item.get("label") or item_id),
        "room_id": _room_id(item, anchor_type=anchor_type),
        "room_label": _room_label(item, anchor_type=anchor_type),
        "waypoint_id": waypoint_id,
        "pose": nav_goal,
        "pose_source": "agibot_navigation_memory_nav_goal",
        "pose_role": "nav_goal",
        "localization_status": "target_pose_verified",
        "object_pose": object_pose,
        "object_pose_source": "agibot_navigation_memory_pose",
        "affordances": affordances,
        "aliases": [str(alias) for alias in item.get("aliases") or []],
        "producer_type": "agibot_navigation_memory_conversion",
        "producer_id": "navigation_memory.json",
        "confidence": _confidence(item),
        "freshness": "prior",
        "classification_status": classification_status,
        "reachability_status": reachability["status"],
        "actionability": actionability,
        "promotion_status": _promotion_status(anchor_type, actionability),
        "materialization": materialization,
        "evidence": evidence,
        "review_status": "needs_review" if classification_status == "needs_review" else "converted",
    }


def _bundle_rooms(semantics: dict[str, Any], *, map_frame_id: str) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = []
    for index, room in enumerate(semantics.get("rooms") or []):
        if not isinstance(room, dict):
            raise ValueError(f"Nav2 cleanup room {index + 1} must be a JSON object")
        room_id = str(room.get("room_id") or f"rooms[{index}]")
        source_map_frame_id = str(room.get("source_map_frame_id") or "")
        if source_map_frame_id and source_map_frame_id != map_frame_id:
            raise ValueError(
                "Nav2 cleanup room source_map_frame_id must match "
                f"semantics.json frame_ids.map: {room_id}"
            )
        item = copy.deepcopy(room)
        item.setdefault("source_map_frame_id", map_frame_id)
        rooms.append(item)
    return rooms


def _bundle_waypoint(waypoint: dict[str, Any], *, map_frame_id: str) -> dict[str, Any]:
    waypoint_id = str(waypoint.get("waypoint_id") or waypoint.get("id") or "")
    pose = required_xy_yaw_pose_source(
        waypoint,
        label=f"Nav2 cleanup waypoint {waypoint_id}",
    )
    frame_id = str(waypoint.get("frame_id") or map_frame_id)
    if frame_id != map_frame_id:
        raise ValueError(
            f"Nav2 cleanup waypoint frame_id must match semantics.json frame_ids.map: {waypoint_id}"
        )
    return {
        "waypoint_id": waypoint_id,
        "frame_id": frame_id,
        **pose,
        "room_id": str(waypoint.get("room_id") or ""),
        "label": str(waypoint.get("label") or waypoint_id),
        "waypoint_source": str(waypoint.get("waypoint_source") or "nav2_cleanup_bundle"),
        "actionability": _bundle_waypoint_actionability(waypoint),
    }


def _anchor_from_bundle_waypoint(waypoint: dict[str, Any], *, index: int) -> dict[str, Any]:
    waypoint_id = str(waypoint.get("waypoint_id") or f"bundle_waypoint_{index:03d}")
    anchor_id = f"anchor_{_safe_id(waypoint_id)}"
    actionability = str(waypoint.get("actionability") or "actionable")
    return {
        "anchor_id": anchor_id,
        "source_anchor_id": waypoint_id,
        "anchor_type": "room_area" if waypoint.get("room_id") else "landmark",
        "category": "room_area" if waypoint.get("room_id") else "navigation_waypoint",
        "label": str(waypoint.get("label") or waypoint_id),
        "room_id": str(waypoint.get("room_id") or ""),
        "room_label": str(waypoint.get("label") or waypoint.get("room_id") or ""),
        "waypoint_id": waypoint_id,
        "pose": {
            "x": waypoint["x"],
            "y": waypoint["y"],
            "yaw": waypoint["yaw"],
        },
        "pose_source": "nav2_cleanup_bundle_waypoint",
        "pose_role": "inspection_waypoint",
        "localization_status": "viewpoint_only",
        "affordances": ["navigate", "observe"],
        "aliases": [waypoint_id],
        "producer_type": "nav2_cleanup_bundle_conversion",
        "producer_id": "semantics.json",
        "confidence": 0.8 if actionability == "actionable" else 0.5,
        "freshness": "prior",
        "classification_status": "map_prior",
        "reachability_status": actionability,
        "actionability": actionability,
        "promotion_status": "materialized_static_anchor"
        if actionability == "actionable"
        else actionability,
        "materialization": {
            "waypoint": copy.deepcopy(waypoint),
            "fixture_candidate": {
                "enabled": False,
                "reason": "compiled_bundle_waypoint_not_fixture_anchor",
                "anchor_type": "room_area" if waypoint.get("room_id") else "landmark",
            },
        },
        "evidence": {
            "type": "nav2_cleanup_bundle_waypoint",
            "source": "semantics.json",
        },
        "review_status": "converted",
    }


def _bundle_waypoint_actionability(waypoint: dict[str, Any]) -> str:
    explicit = str(waypoint.get("actionability") or "")
    if explicit:
        return explicit
    source = str(waypoint.get("waypoint_source") or "")
    if source == "generated_exploration_candidate":
        return "actionable"
    return "observe_only"


def _bundle_frame_id(semantics: dict[str, Any]) -> str:
    frame_ids = semantics.get("frame_ids") if isinstance(semantics.get("frame_ids"), dict) else {}
    map_frame_id = str(frame_ids.get("map") or "")
    if not map_frame_id:
        raise ValueError("Nav2 cleanup semantics must contain frame_ids.map")
    errors: list[str] = []
    require_source_frame_spatial_contract(semantics, errors)
    if errors:
        raise ValueError(
            "Nav2 cleanup semantics source-frame contract invalid: " + "; ".join(errors)
        )
    return map_frame_id


def _waypoint_from_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(anchor["materialization"]["waypoint"])


def _prior_observed_object_from_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_id": anchor["source_anchor_id"],
        "category": anchor["category"],
        "room_id": anchor["room_id"],
        "waypoint_id": anchor["waypoint_id"],
        "source_fixture_id": "",
        "source_observation_id": _selected_frame(anchor),
        "image_region": {},
        "producer_type": anchor["producer_type"],
        "producer_id": anchor["producer_id"],
        "confidence": anchor["confidence"],
        "freshness": "prior",
        "actionability": "needs_confirm",
        "state": "prior",
        "grounding_status": "prior",
        "candidate_fixture_id": "",
        "candidate_source": "runtime_map_prior_snapshot",
        "promotion_status": "movable_prior_not_static_fixture",
    }


def _fixture_candidate(
    *,
    anchor_id: str,
    waypoint_id: str,
    item: dict[str, Any],
    anchor_type: str,
    affordances: list[str],
    actionability: str,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {
            "enabled": False,
            "reason": "not_a_fixture_or_receptacle_anchor",
            "anchor_type": anchor_type,
        }
    return {
        "enabled": True,
        "fixture_id": anchor_id,
        "receptacle_id": anchor_id,
        "anchor_id": anchor_id,
        "category": _category(item, anchor_type=anchor_type),
        "name": str(item.get("label") or item.get("id") or anchor_id),
        "room_id": _room_id(item, anchor_type=anchor_type),
        "room_label": _room_label(item, anchor_type=anchor_type),
        "affordances": list(affordances),
        "preferred_inspection_waypoint_id": waypoint_id,
        "preferred_manipulation_waypoint_id": waypoint_id,
        "public_fixture_source": "runtime_map_prior_snapshot",
        "actionability": actionability,
    }


def _materialized_waypoints_from_runtime_map(
    runtime_metric_map: dict[str, Any],
) -> list[dict[str, Any]]:
    anchors = runtime_metric_map.get("public_semantic_anchors") or []
    frame_id = _runtime_metric_map_frame_id(runtime_metric_map)
    waypoints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        waypoint_id = str(anchor.get("waypoint_id") or "")
        if not waypoint_id or waypoint_id in seen:
            continue
        anchor_id = str(anchor.get("anchor_id") or "")
        _reject_frame_drift(
            anchor,
            expected_frame_id=frame_id,
            label=f"runtime metric map anchor {anchor_id or waypoint_id}",
        )
        pose = _pose_dict(anchor.get("pose") or {})
        waypoints.append(
            {
                "waypoint_id": waypoint_id,
                "frame_id": frame_id,
                **pose,
                "anchor_id": anchor_id,
                "anchor_type": str(anchor.get("anchor_type") or ""),
                "label": str(anchor.get("label") or waypoint_id),
                "waypoint_source": "runtime_metric_map_public_semantic_anchor",
                "actionability": _anchor_actionability(anchor),
            }
        )
        seen.add(waypoint_id)
    for waypoint in runtime_metric_map.get("generated_exploration_candidates") or []:
        if not isinstance(waypoint, dict):
            continue
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if waypoint_id and waypoint_id not in seen:
            item = copy.deepcopy(waypoint)
            _reject_frame_drift(
                item,
                expected_frame_id=frame_id,
                label=f"runtime metric map generated waypoint {waypoint_id}",
            )
            item.setdefault("frame_id", frame_id)
            item.setdefault("actionability", "actionable")
            waypoints.append(item)
            seen.add(waypoint_id)
    return waypoints


def _materialized_fixtures_from_runtime_map(
    runtime_metric_map: dict[str, Any],
) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for anchor in runtime_metric_map.get("public_semantic_anchors") or []:
        if not isinstance(anchor, dict):
            continue
        anchor_type = str(anchor.get("anchor_type") or "")
        affordances = [str(item) for item in anchor.get("affordances") or []]
        if anchor_type not in {"fixture", "surface", "receptacle"}:
            continue
        if not {"place", "place_inside", "open", "close"}.intersection(affordances):
            continue
        anchor_id = str(anchor.get("anchor_id") or "")
        if not anchor_id:
            continue
        fixtures.append(
            {
                "enabled": True,
                "fixture_id": anchor_id,
                "receptacle_id": anchor_id,
                "anchor_id": anchor_id,
                "category": str(anchor.get("category") or anchor_type),
                "name": str(anchor.get("label") or anchor_id),
                "room_id": str(anchor.get("room_id") or ""),
                "affordances": affordances,
                "preferred_inspection_waypoint_id": str(anchor.get("waypoint_id") or ""),
                "preferred_manipulation_waypoint_id": str(anchor.get("waypoint_id") or ""),
                "public_fixture_source": "runtime_metric_map_public_semantic_anchor",
                "actionability": _anchor_actionability(anchor),
            }
        )
    return fixtures


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    anchors = snapshot.get("public_semantic_anchors") or []
    fixtures = snapshot.get("fixture_candidates") or []
    waypoints = snapshot.get("inspection_waypoints") or []
    movable_priors = [
        item
        for item in snapshot.get("runtime_metric_map", {}).get("observed_objects", [])
        if isinstance(item, dict) and item.get("freshness") == "prior"
    ]
    return {
        "anchor_count": len(anchors),
        "inspection_waypoint_count": len(waypoints),
        "fixture_candidate_count": len(fixtures),
        "actionable_anchor_count": sum(
            1 for item in anchors if item.get("actionability") in ACTIONABLE_ANCHOR_STATUSES
        ),
        "movable_prior_count": len(movable_priors),
    }


def _nav2_cleanup_waypoint_sources(semantics: dict[str, Any]) -> list[dict[str, Any]]:
    waypoints = semantics.get("inspection_waypoints")
    if not isinstance(waypoints, list) or not waypoints:
        raise ValueError("Nav2 cleanup semantics inspection_waypoints must be a non-empty list")
    result: list[dict[str, Any]] = []
    for index, waypoint in enumerate(waypoints, start=1):
        if not isinstance(waypoint, dict):
            raise ValueError(f"Nav2 cleanup waypoint {index} must be a JSON object")
        result.append(waypoint)
    return result


def _anchor_type(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").lower()
    item_id = str(item.get("id") or "").lower()
    label = str(item.get("label") or "").lower()
    text = " ".join(
        [kind, item_id, label, " ".join(str(a).lower() for a in item.get("aliases") or [])]
    )
    if kind in {"room", "area"} or "center" in item_id:
        return "room_area"
    if kind in {"plastic_bottle", "bottle"} or any(term in text for term in ("bottle", "水瓶")):
        return "movable_object"
    if kind in {"sink"} or any(
        term in text for term in ("sink", "fridge", "refrigerator", "水槽", "冰箱")
    ):
        return "receptacle"
    if kind in {"surface", "table", "sofa"} or any(
        term in text for term in ("table", "desk", "sofa", "counter", "茶几", "桌", "沙发")
    ):
        return "surface"
    if _confidence(item) < 0.65:
        return "landmark"
    return "fixture"


def _category(item: dict[str, Any], *, anchor_type: str) -> str:
    kind = str(item.get("kind") or "").strip()
    if kind:
        return kind
    if anchor_type == "room_area":
        return "room_area"
    return anchor_type


def _room_label(item: dict[str, Any], *, anchor_type: str) -> str:
    if anchor_type == "room_area":
        return str(item.get("label") or item.get("id") or "room area")
    explicit = str(item.get("room_label") or item.get("room_area") or "").strip()
    if explicit:
        return explicit
    room_id = _room_id(item, anchor_type=anchor_type)
    return room_id.replace("_", " ")


def _room_id(item: dict[str, Any], *, anchor_type: str) -> str:
    if anchor_type == "room_area":
        return _safe_id(str(item.get("id") or "room_area"))
    text = " ".join(
        [
            str(item.get("id") or "").lower(),
            str(item.get("label") or "").lower(),
            " ".join(str(a).lower() for a in item.get("aliases") or []),
        ]
    )
    if any(term in text for term in ("sink", "fridge", "kitchen", "水槽", "冰箱", "厨房")):
        return "kitchen_area"
    if any(
        term in text for term in ("sofa", "coffee", "monitor", "decor", "茶几", "沙发", "显示器")
    ):
        return "living_area"
    return "agibot_map_area"


def _rooms_from_anchors(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in anchors:
        if str(anchor.get("anchor_type") or "") != "room_area":
            continue
        room_id = str(anchor.get("room_id") or "")
        if not room_id or room_id in seen:
            continue
        pose = dict(anchor.get("pose") or {})
        room_label = str(
            anchor.get("room_label") or anchor.get("label") or room_id.replace("_", " ")
        )
        rooms.append(
            normalize_spatial_room(
                {
                    "room_id": room_id,
                    "room_label": room_label,
                    "category": _room_category_from_label(room_label, room_id),
                    "map_center": {
                        "x": float(pose.get("x") or 0.0),
                        "y": float(pose.get("y") or 0.0),
                    },
                    "polygon": [],
                    "source_anchor_id": str(anchor.get("anchor_id") or ""),
                    "public_room_source": "agibot_navigation_memory_room_area",
                },
                frame_id=str(anchor.get("frame_id") or "map"),
                polygon_role=POLYGON_ROLE_NAVIGATION_AREA,
                geometry_source=GEOMETRY_SOURCE_RUNTIME_OBSERVATION,
                alignment_status=ALIGNMENT_STATUS_CANDIDATE,
            )
        )
        seen.add(room_id)
    return rooms


def _room_category_hints_from_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints = []
    for room in rooms:
        room_id = str(room.get("room_id") or "")
        room_label = str(room.get("room_label") or room_id.replace("_", " "))
        if not room_id:
            continue
        hints.append(
            {
                "anchor_type": "room_area",
                "category": str(
                    room.get("category") or _room_category_from_label(room_label, room_id)
                ),
                "label": room_label,
                "room_id": room_id,
                "room_label": room_label,
                "affordances": ["navigate", "observe"],
                "classification_status": "map_prior",
                "confidence": 0.8,
                "aliases": [room_id, room_label],
                "producer_type": "agibot_navigation_memory_conversion",
            }
        )
    return hints


def _driveable_ways(rooms: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "from_room_id": str(previous.get("room_id") or ""),
            "to_room_id": str(current.get("room_id") or ""),
        }
        for previous, current in zip(rooms, rooms[1:], strict=False)
        if previous.get("room_id") and current.get("room_id")
    ]


def _room_category_from_label(room_label: str, room_id: str) -> str:
    text = f"{room_label} {room_id}".lower()
    if any(term in text for term in ("kitchen", "dining", "bar", "counter", "厨房", "吧台")):
        return "kitchen"
    if any(term in text for term in ("living", "sofa", "lounge", "客厅", "沙发")):
        return "living_room"
    if any(term in text for term in ("storage", "store", "utility", "储藏", "库房")):
        return "storage_room"
    if any(term in text for term in ("meeting", "conference", "会议")):
        return "meeting_room"
    if any(term in text for term in ("bed", "卧室")):
        return "bedroom"
    if any(term in text for term in ("bath", "toilet", "卫生间")):
        return "bathroom"
    return "room_area"


def _affordances(item: dict[str, Any], *, anchor_type: str) -> list[str]:
    if anchor_type == "movable_object":
        return ["observe"]
    if anchor_type == "room_area":
        return ["navigate", "observe"]
    if anchor_type == "landmark":
        return ["navigate", "observe"]
    text = " ".join(
        [
            str(item.get("id") or "").lower(),
            str(item.get("label") or "").lower(),
            str(item.get("kind") or "").lower(),
            " ".join(str(a).lower() for a in item.get("aliases") or []),
        ]
    )
    affordances = ["navigate", "observe", "place"]
    if any(term in text for term in ("fridge", "refrigerator", "冰箱")):
        affordances.extend(["open", "place_inside", "close"])
    elif any(term in text for term in ("sink", "水槽", "hamper", "bin", "cabinet")):
        affordances.append("place_inside")
    return list(dict.fromkeys(affordances))


def _classification_status(item: dict[str, Any], *, anchor_type: str) -> str:
    if anchor_type == "landmark" or _confidence(item) < 0.65:
        return "needs_review"
    return "classified"


def _actionability(anchor_type: str, reachability_status: str, classification_status: str) -> str:
    if anchor_type in MOVABLE_ANCHOR_TYPES:
        return "needs_confirm"
    if classification_status == "needs_review":
        return "needs_review"
    if reachability_status == "reachable":
        return "actionable"
    if reachability_status == "costmap_disagrees":
        return "costmap_disagrees"
    return "observe_only"


def _promotion_status(anchor_type: str, actionability: str) -> str:
    if anchor_type in MOVABLE_ANCHOR_TYPES:
        return "movable_prior_needs_current_run_confirmation"
    if actionability == "actionable":
        return "materialized_static_anchor"
    return actionability


def _reachability_status(pose: dict[str, Any], *, grid: OccupancyGrid) -> dict[str, Any]:
    if "x" not in pose or "y" not in pose:
        return {"status": "projected", "cell": None, "costmap_value": None}
    x = float(pose["x"])
    y = float(pose["y"])
    col, row = world_to_grid(x, y, grid)
    if not grid.in_bounds(col, row):
        return {"status": "costmap_disagrees", "cell": [col, row], "costmap_value": None}
    value = grid.rows[row][col]
    return {
        "status": "reachable" if grid.is_free_cell(col, row) else "costmap_disagrees",
        "cell": [col, row],
        "costmap_value": value,
    }


def _anchor_actionability(anchor: dict[str, Any]) -> str:
    explicit = str(anchor.get("actionability") or "")
    if explicit:
        return explicit
    if str(anchor.get("freshness") or "") == "prior" and str(anchor.get("anchor_type") or "") in (
        "object",
        "movable_object",
    ):
        return "needs_confirm"
    if str(anchor.get("promotion_status") or "") in {"needs_review", "observe_only"}:
        return str(anchor.get("promotion_status"))
    return "actionable"


def _pose_dict(raw: dict[str, Any]) -> dict[str, float]:
    pose: dict[str, float] = {}
    for key in ("x", "y", "yaw"):
        pose[key] = _float(raw.get(key))
    return pose


def _float(value: Any) -> float:
    try:
        return round(float(value or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _confidence(item: dict[str, Any]) -> float:
    try:
        return round(float(item.get("confidence") or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _selected_frame(anchor: dict[str, Any]) -> str:
    evidence = anchor.get("evidence") if isinstance(anchor.get("evidence"), dict) else {}
    raw_evidence = evidence.get("evidence") if isinstance(evidence.get("evidence"), dict) else {}
    return str(raw_evidence.get("selected_frame") or raw_evidence.get("grounding_artifact") or "")
