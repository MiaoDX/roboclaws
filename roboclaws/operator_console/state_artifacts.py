"""Operator-console artifact links and visual asset projection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.maps.preview import (
    BASE_MAP_SOURCE_FAMILY,
    BASE_METRIC_MAP_PREVIEW_ROLE,
    RUNTIME_MAP_SOURCE_FAMILY,
    RUNTIME_METRIC_MAP_PREVIEW_ROLE,
    SCENE_RENDER_SOURCE_FAMILY,
    TOPDOWN_SCENE_RENDER_ROLE,
)
from roboclaws.operator_console.grounding_assets import grounding_frames_payload
from roboclaws.operator_console.state_presentation import _artifact_href


@dataclass(frozen=True)
class ArtifactLink:
    label: str
    path: Path
    kind: str

    def to_payload(self, root: Path) -> dict[str, str]:
        return {
            "label": self.label,
            "kind": self.kind,
            "path": str(self.path),
            "href": _artifact_href(root, self.path),
        }


def _latest_existing(run_dir: Path, names: tuple[str, ...]) -> Path:
    candidates: list[Path] = []
    for name in names:
        candidates.extend(path for path in run_dir.rglob(name) if path.is_file())
    if not candidates:
        return run_dir / names[0]
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _artifact_links(run_dir: Path) -> list[ArtifactLink]:
    specs = (
        ("Report", "report.html", "html"),
        ("Run Result", "run_result.json", "json"),
        ("Trace", "trace.jsonl", "jsonl"),
        ("Agent Events", "openai-agents-events.jsonl", "jsonl"),
        ("OpenAI Agents Trace", "openai-agents-trace.json", "json"),
        ("Driver Log", "driver.log", "log"),
        ("Checker Output", "checker.log", "log"),
        ("Runtime Map", "runtime_metric_map.json", "json"),
        ("Runtime Metric Map Preview", "runtime_metric_map_preview.png", "image"),
        ("B1 Robot Consumption", "b1_robot_consumption_manifest.json", "json"),
        ("Runtime Map Prior", "runtime_map_prior_snapshot.json", "json"),
        ("Runtime Map Prior Targets", "runtime_map_prior_targets.json", "json"),
    )
    links: list[ArtifactLink] = []
    for label, name, kind in specs:
        path = _latest_existing(run_dir, (name,))
        if path.exists():
            links.append(ArtifactLink(label=label, path=path.resolve(), kind=kind))
    return links


def _wrapper_artifact_links(run_dir: Path) -> list[ArtifactLink]:
    specs = (
        ("Console Launch Log", "console-launch.log", "log"),
        ("Operator State", "operator_state.json", "json"),
        ("Operator Messages", "operator_messages.jsonl", "jsonl"),
        ("Operator Control", "operator_control.jsonl", "jsonl"),
        ("Operator Interventions", "operator_interventions.json", "json"),
        ("B1 Robot Consumption", "b1_robot_consumption_manifest.json", "json"),
        ("Runtime Map Prior", "runtime_map_prior_snapshot.json", "json"),
        ("Runtime Map Prior Targets", "runtime_map_prior_targets.json", "json"),
    )
    links: list[ArtifactLink] = []
    for label, name, kind in specs:
        path = run_dir / name
        if path.exists():
            links.append(ArtifactLink(label=label, path=path.resolve(), kind=kind))
    return links


def _latest_view_assets(root: Path, run_dir: Path) -> dict[str, dict[str, Any]]:
    patterns = {
        "fpv": ("*.fpv*.png", "*.fpv*.jpg", "*fpv*.png", "*fpv*.jpg"),
        "chase": ("*.chase*.png", "*.chase*.jpg", "*chase*.png", "*chase*.jpg"),
        "map": ("map_bundle/preview.png",),
        "runtime_map": ("runtime_metric_map_preview.png",),
        "topdown": (
            "*topdown*.png",
            "*topdown*.jpg",
            "*top-down*.png",
            "*top-down*.jpg",
            "*top_down*.png",
            "*top_down*.jpg",
        ),
        "grounding": (
            "visual_grounding/overlays/**/*.jpg",
            "visual_grounding/overlays/**/*.png",
        ),
    }
    preferred_dirs = {
        "fpv": ("robot_views",),
        "chase": ("robot_views",),
        "topdown": ("robot_views",),
    }
    output: dict[str, dict[str, Any]] = {}
    for key, globs in patterns.items():
        matches: list[Path] = []
        for directory in preferred_dirs.get(key, ()):
            base = run_dir / directory
            if not base.is_dir():
                continue
            for pattern in globs:
                matches.extend(path for path in base.rglob(pattern) if path.is_file())
        if not matches:
            for pattern in globs:
                matches.extend(path for path in run_dir.rglob(pattern) if path.is_file())
        if not matches:
            continue
        path = max(matches, key=lambda item: item.stat().st_mtime).resolve()
        output[key] = {
            "path": str(path),
            "href": _artifact_href(root, path),
            "mtime": str(path.stat().st_mtime),
            **_view_asset_role_metadata(key),
        }
    grounding_frames = grounding_frames_payload(root, run_dir)
    if grounding_frames:
        output["grounding_frames"] = grounding_frames
    return output


def _view_asset_role_metadata(key: str) -> dict[str, str]:
    if key == "map":
        return {
            "visual_role": BASE_METRIC_MAP_PREVIEW_ROLE,
            "artifact_source_family": BASE_MAP_SOURCE_FAMILY,
        }
    if key == "runtime_map":
        return {
            "visual_role": RUNTIME_METRIC_MAP_PREVIEW_ROLE,
            "artifact_source_family": RUNTIME_MAP_SOURCE_FAMILY,
        }
    if key == "topdown":
        return {
            "visual_role": TOPDOWN_SCENE_RENDER_ROLE,
            "artifact_source_family": SCENE_RENDER_SOURCE_FAMILY,
        }
    return {"visual_role": key, "artifact_source_family": "run_view_artifact"}
