"""Isaac Lab backend runtime support."""

from __future__ import annotations

from typing import Any

from roboclaws.household.types import CleanupScenario


def norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def vec3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None


def has_xy(value: dict[str, Any]) -> bool:
    if "x" not in value or "y" not in value:
        return False
    try:
        float(value["x"])
        float(value["y"])
    except (TypeError, ValueError):
        return False
    return True


def index_or_default(
    value: Any,
    default: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        return default
    return {
        str(key): dict(item) for key, item in value.items() if isinstance(item, dict)
    } or default


def objects_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["object_id"]): item for item in state["scenario"]["objects"]}


def receptacles_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["receptacle_id"]): item for item in state["scenario"]["receptacles"]}


def object_index(scenario: CleanupScenario) -> dict[str, dict[str, Any]]:
    return {
        item.object_id: {
            "usd_prim_path": f"/World/Scene/Objects/{item.object_id}",
            "category": item.category,
            "public_label": item.name,
        }
        for item in scenario.objects
    }


def receptacle_index(scenario: CleanupScenario) -> dict[str, dict[str, Any]]:
    return {
        item.receptacle_id: {
            "usd_prim_path": f"/World/Scene/Receptacles/{item.receptacle_id}",
            "category": item.category or item.kind,
            "public_label": item.name,
            "support_pose": pose_near(item.receptacle_id),
        }
        for item in scenario.receptacles
    }


def pose_near(anchor_id: str) -> dict[str, float | str]:
    value = sum(ord(char) for char in anchor_id)
    return {
        "frame": "world",
        "x": round((value % 17) * 0.17, 3),
        "y": round(((value // 17) % 17) * 0.13, 3),
        "z": 0.0,
        "yaw_deg": float((value * 13) % 360),
    }
