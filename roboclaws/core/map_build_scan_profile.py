"""Shared map-build scan policy values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAP_BUILD_SCAN_PROFILE_SCHEMA = "map_build_scan_profile_v1"
FIXTURE_FOCUSED_MAP_BUILD_SCAN_PROFILE = "fixture-focused"
DEFAULT_MAP_BUILD_SCAN_PROFILE = FIXTURE_FOCUSED_MAP_BUILD_SCAN_PROFILE

NEUTRAL_CAMERA_SCHEDULE: tuple[dict[str, float], ...] = (
    {"yaw_delta_deg": 0.0, "pitch_delta_deg": 0.0},
)


@dataclass(frozen=True)
class MapBuildScanProfile:
    profile_id: str
    description: str
    camera_schedule: tuple[dict[str, float], ...]
    body_turn_yaw_delta_deg: float = 0.0
    body_turn_count_per_waypoint: int = 0
    stable_anchor_priority: bool = False
    movable_prior_policy: str = (
        "movable observations are non-actionable search hints until current confirmation"
    )

    @property
    def uses_robot_body_turns(self) -> bool:
        return self.body_turn_count_per_waypoint > 0

    @property
    def observe_count_per_waypoint(self) -> int:
        if self.uses_robot_body_turns:
            return 1 + self.body_turn_count_per_waypoint
        return len(self.camera_schedule)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": MAP_BUILD_SCAN_PROFILE_SCHEMA,
            "profile": self.profile_id,
            "description": self.description,
            "default_for_dedicated_map_build": self.profile_id == DEFAULT_MAP_BUILD_SCAN_PROFILE,
            "public_launch_axis": False,
            "camera_schedule": [dict(item) for item in self.camera_schedule],
            "uses_robot_body_turns": self.uses_robot_body_turns,
            "body_turn_yaw_delta_deg": self.body_turn_yaw_delta_deg,
            "body_turn_count_per_waypoint": self.body_turn_count_per_waypoint,
            "observe_count_per_waypoint": self.observe_count_per_waypoint,
            "stable_anchor_priority": self.stable_anchor_priority,
            "movable_prior_policy": self.movable_prior_policy,
        }


def map_build_scan_profile() -> MapBuildScanProfile:
    return MapBuildScanProfile(
        profile_id=FIXTURE_FOCUSED_MAP_BUILD_SCAN_PROFILE,
        description=(
            "MapBuild scan emphasizing stable fixtures, surfaces, receptacles, "
            "room or area anchors, and navigation-visible landmarks."
        ),
        camera_schedule=NEUTRAL_CAMERA_SCHEDULE,
        body_turn_yaw_delta_deg=90.0,
        body_turn_count_per_waypoint=4,
        stable_anchor_priority=True,
    )
