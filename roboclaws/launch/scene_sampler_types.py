"""Typed scene-sampler row contracts shared by launch/catalog surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_arg

SAMPLER_GENERATOR_VERSION = "2026-06-15.preview-readiness-v1"

UI_LANE = "ui"
EVAL_STRESS_LANE = "eval_stress"
READINESS_READY = "ready"
READINESS_BLOCKED = "blocked"
READINESS_REJECTED = "rejected"


@dataclass(frozen=True)
class MolmoSpacesSceneRef:
    """A parsed MolmoSpaces world id with explicit source identity."""

    scene_source: str
    scene_index: int


@dataclass(frozen=True)
class SceneSamplerRow:
    """One source-qualified scene sampler candidate or blocked source row."""

    scene_family: str
    scene_split: str
    scene_source: str
    scene_index: int | None
    backend: str
    readiness_status: str
    lanes: tuple[str, ...]
    world_id: str
    room_count: int
    waypoint_count: int
    category_provenance: str
    category_manifest: str
    preview_assets: tuple[tuple[str, str], ...]
    selected_reason: str
    blocked_reason: str = ""
    failure_class: str = ""
    quality_score: float = 0.0
    coverage_score: float = 0.0

    @property
    def ui_ready(self) -> bool:
        return self.readiness_status == READINESS_READY and UI_LANE in self.lanes

    @property
    def eval_ready(self) -> bool:
        return self.readiness_status == READINESS_READY and EVAL_STRESS_LANE in self.lanes

    @property
    def index_token(self) -> str:
        if self.scene_index is None:
            return "blocked"
        return str(self.scene_index)

    @property
    def default_overrides(self) -> tuple[str, ...]:
        if self.scene_index is None:
            return ()
        return (
            f"scene_source={self.scene_source}",
            f"scene_index={self.scene_index}",
            molmospaces_nav2_map_bundle_arg(
                scene_source=self.scene_source,
                scene_index=self.scene_index,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_family": self.scene_family,
            "scene_split": self.scene_split,
            "scene_source": self.scene_source,
            "scene_index": self.scene_index,
            "backend": self.backend,
            "readiness_status": self.readiness_status,
            "lanes": list(self.lanes),
            "world_id": self.world_id,
            "room_count": self.room_count,
            "waypoint_count": self.waypoint_count,
            "category_provenance": self.category_provenance,
            "category_manifest": self.category_manifest,
            "preview_assets": [{"view": view, "path": path} for view, path in self.preview_assets],
            "selected_reason": self.selected_reason,
            "blocked_reason": self.blocked_reason,
            "failure_class": self.failure_class,
            "quality_score": self.quality_score,
            "coverage_score": self.coverage_score,
            "generator_version": SAMPLER_GENERATOR_VERSION,
        }
