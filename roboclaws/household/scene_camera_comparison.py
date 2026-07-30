from __future__ import annotations

import html
import json
import math
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from roboclaws.core.json_sources import parse_json_object_text
from roboclaws.household import (
    scene_camera_geometry_contract,
    scene_camera_image_metrics,
    scene_camera_lighting_diagnostics,
    scene_camera_render_domain,
    scene_camera_usda_contract,
)
from roboclaws.household.artifact_paths import dimensions_from_shape, output_relpath
from roboclaws.household.camera_control import (
    CAMERA_CONTROL_API_NAME,
    CANONICAL_CAMERA_MODEL,
    CANONICAL_POSE_CALIBRATION,
    DEFAULT_SCENE_PROBE_CAMERA_ORBIT,
    DEFAULT_SCENE_PROBE_COLOR_PROFILE,
    DEFAULT_SCENE_PROBE_LENS,
    MOLMOSPACES_SCENE_FRAME,
    SCENE_PROBE_LIGHTING_PROFILES,
    canonical_scene_camera_control_request,
    normalize_camera_control_request,
    write_camera_control_request,
)
from roboclaws.household.isaac_lab_backend import IsaacLabSubprocessBackend
from roboclaws.household.scene_camera_render_diagnostics import (
    mujoco_render_contract_from_xml as _mujoco_render_contract_from_xml,
)
from roboclaws.household.scene_camera_render_diagnostics import (
    view_usd_prim_path as _view_usd_prim_path_impl,
)
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend

SCENE_CAMERA_COMPARISON_SCHEMA = "molmospaces_isaac_scene_camera_comparison_v1"
MOLMOSPACES_LANE_ID = scene_camera_render_domain.MOLMOSPACES_LANE_ID
ISAAC_LANE_ID = scene_camera_render_domain.ISAAC_LANE_ID
DEFAULT_RENDER_WIDTH = 960
DEFAULT_RENDER_HEIGHT = 640
CANONICAL_CAMERA_ELEVATION_DEG = 78.0
ROOM_CAMERA_HEIGHT_M = 1.45
ROOM_CAMERA_INSET_FRACTION = 0.35
CANDIDATE_VISUAL_MEAN_PIXEL_DELTA_WARN = 45.0
CANDIDATE_VISUAL_MAX_PIXEL_DELTA_WARN = 60.0
REPO_ROOT = scene_camera_render_domain.REPO_ROOT
USD_PHYSICS_PRIM_TYPE_NAMES = scene_camera_usda_contract.USD_PHYSICS_PRIM_TYPE_NAMES
USD_PHYSICS_API_SCHEMA_NAMES = scene_camera_usda_contract.USD_PHYSICS_API_SCHEMA_NAMES

_isaac_render_contract_from_usda = scene_camera_usda_contract.isaac_render_contract_from_usda
_image_visual_metrics = scene_camera_image_metrics.image_visual_metrics
_image_region_visual_metrics = scene_camera_image_metrics.image_region_visual_metrics
_image_pair_visual_delta = scene_camera_image_metrics.image_pair_visual_delta
_native_isaac_render_diagnostics = scene_camera_lighting_diagnostics.native_isaac_render_diagnostics
_lighting_tone_provenance = scene_camera_lighting_diagnostics.lighting_tone_provenance
_shadow_parity_probe = scene_camera_lighting_diagnostics.shadow_parity_probe
_key_light_direction_diagnostics = scene_camera_lighting_diagnostics.key_light_direction_diagnostics
OFFICIAL_RENDER_SOURCE_REFERENCES = scene_camera_render_domain.OFFICIAL_RENDER_SOURCE_REFERENCES


@dataclass(frozen=True)
class SceneCameraComparisonConfig:
    output_dir: Path
    scene_usd_path: Path
    seed: int = 7
    generated_mess_count: int = 1
    scene_source: str = "procthor-10k-val"
    scene_index: int = 1
    molmospaces_python: Path = Path(".venv/bin/python")
    isaac_python: Path = Path(".venv-isaaclab/bin/python")
    render_width: int = DEFAULT_RENDER_WIDTH
    render_height: int = DEFAULT_RENDER_HEIGHT
    lighting_profile_id: str = "default"


def _scene_camera_lighting_profile(profile_id: str) -> dict[str, Any]:
    key = str(profile_id or "default")
    profile = SCENE_PROBE_LIGHTING_PROFILES.get(key)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(SCENE_PROBE_LIGHTING_PROFILES))
        raise ValueError(f"unknown scene-camera lighting profile {key!r}; available: {available}")
    return dict(profile)


def run_scene_camera_comparison(config: SceneCameraComparisonConfig) -> dict[str, Any]:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    lighting_profile = _scene_camera_lighting_profile(config.lighting_profile_id)
    manifest: dict[str, Any] = {
        "schema": SCENE_CAMERA_COMPARISON_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "purpose": (
            "Render-only scene identity probe. This does not execute household cleanup, "
            "pick, place, or scoring."
        ),
        "scene": {
            "scene_source": config.scene_source,
            "scene_index": config.scene_index,
            "seed": config.seed,
            "generated_mess_count": config.generated_mess_count,
            "scene_usd_path": str(config.scene_usd_path),
            "render_width": config.render_width,
            "render_height": config.render_height,
            "lighting_profile_id": str(lighting_profile.get("profile_id") or ""),
        },
        "camera_control": {
            "api_name": CAMERA_CONTROL_API_NAME,
            "camera_model": CANONICAL_CAMERA_MODEL,
            "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
            "lens": dict(DEFAULT_SCENE_PROBE_LENS),
            "lighting_profile": dict(lighting_profile),
            "color_profile": dict(DEFAULT_SCENE_PROBE_COLOR_PROFILE),
            "calibration_status": CANONICAL_POSE_CALIBRATION,
            "calibration_note": (
                "One Roboclaws camera-control request carries explicit eye/target/up poses "
                "in the MolmoSpaces scene frame. Backends apply their registered scene-frame "
                "transform internally; the report records fit residuals instead of hiding "
                "camera mismatch behind lane-local orbit overrides."
            ),
            "request_artifact": "camera_control_request.json",
        },
        "frame_mapping_note": (
            "The canonical camera frame is the MolmoSpaces scene frame. Prepared-USD candidate "
            "lanes render the same explicit eye/target/up request for both room-level and "
            "object-anchor views. The report also records USD-bounds residuals for matched "
            "anchors. If residuals are high, the artifact is evidence of a target-definition "
            "or scene geometry mismatch rather than proof of full backend-swappable visual "
            "parity."
        ),
        "official_molmospaces_source": _official_molmospaces_source(),
        "room_camera_views": [],
        "anchors": [],
        "view_specs": {},
        "lane_registry": {
            "baseline": MOLMOSPACES_LANE_ID,
            "candidates": [ISAAC_LANE_ID],
            "diagnostic_baseline": MOLMOSPACES_LANE_ID,
            "pairwise_diagnostic_candidate": ISAAC_LANE_ID,
            "candidate_diagnostic_note": (
                "Current scene-camera comparison is the MuJoCo-to-Isaac render parity probe. "
                "Retired third-party render artifacts are historical evidence, not active lanes."
            ),
        },
        "lanes": {},
        "artifacts": {
            "comparison_manifest": "comparison_manifest.json",
            "report": "report.html",
        },
    }

    molmo = _capture_molmospaces_lane(config)
    manifest["lanes"][MOLMOSPACES_LANE_ID] = molmo
    molmo_state = molmo.pop("_state", {}) if isinstance(molmo, dict) else {}
    if isinstance(molmo, dict) and isinstance(molmo_state, dict):
        molmo["runtime_object_positions"] = _runtime_object_positions(molmo_state)
        molmo["runtime_render_state"] = _runtime_render_state(molmo_state)
    anchors = _scene_anchors(molmo_state, limit=4)
    manifest["anchors"] = anchors
    room_views = _room_camera_control_views(molmo_state)
    manifest["room_camera_views"] = room_views
    molmo_specs = _molmospaces_view_specs(anchors, molmo_state=molmo_state)
    isaac_specs = _isaac_view_specs(
        anchors,
        scene_usd_path=config.scene_usd_path,
        scene_index=config.scene_index,
    )
    scene_transform = scene_camera_geometry_contract.identity_scene_frame_transform()
    anchor_views = _canonical_anchor_camera_control_views(
        anchors,
        molmo_specs=molmo_specs,
        isaac_specs=isaac_specs,
        scene_transform=scene_transform,
    )
    canonical_views = [*room_views, *anchor_views]
    camera_request = canonical_scene_camera_control_request(
        canonical_views,
        width=config.render_width,
        height=config.render_height,
        lens=DEFAULT_SCENE_PROBE_LENS,
        lighting_profile=lighting_profile,
        color_profile=DEFAULT_SCENE_PROBE_COLOR_PROFILE,
    )
    if isinstance(molmo.get("runtime_object_positions"), dict):
        camera_request["runtime_object_positions"] = molmo["runtime_object_positions"]
        camera_request["runtime_object_position_source"] = MOLMOSPACES_LANE_ID
    if isinstance(molmo.get("runtime_render_state"), dict):
        camera_request["runtime_render_state"] = molmo["runtime_render_state"]
        camera_request["runtime_render_state_source"] = MOLMOSPACES_LANE_ID
    camera_request_path = write_camera_control_request(
        output_dir / "camera_control_request.json",
        camera_request,
    )
    manifest["camera_control"]["request_artifact"] = output_relpath(camera_request_path, output_dir)
    manifest["view_specs"] = {
        "room-level-canonical": room_views,
        MOLMOSPACES_LANE_ID: molmo_specs,
        ISAAC_LANE_ID: isaac_specs,
    }
    manifest["scene_frame_transform"] = scene_transform
    manifest["canonical_camera_views"] = canonical_views
    manifest["camera_control"]["view_count"] = len(camera_request.get("views") or [])
    manifest["camera_control"]["same_pose_contract"] = True
    if molmo.get("status") == "success" and canonical_views:
        molmo.update(
            _capture_molmospaces_camera_views(
                config,
                camera_request_path=camera_request_path,
                lane_dir=output_dir / "molmospaces",
            )
        )
    manifest["lanes"][ISAAC_LANE_ID] = _capture_isaac_lane(
        config,
        camera_request_path=camera_request_path,
        lane_dir=output_dir / "isaaclab",
    )
    manifest["camera_pose_contract"] = (
        scene_camera_geometry_contract.camera_pose_contract_from_capture(
            canonical_views=canonical_views,
            molmospaces_lane=molmo,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    manifest["camera_intrinsics_contract"] = (
        scene_camera_geometry_contract.camera_intrinsics_contract_from_capture(
            requested_lens=camera_request.get("lens"),
            requested_resolution=camera_request.get("render_resolution"),
            molmospaces_lane=molmo,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    manifest["room_scale_contract"] = (
        scene_camera_geometry_contract.room_scale_contract_from_scene_capture(
            room_views=room_views,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    manifest["scene_frame_transform"] = (
        scene_camera_geometry_contract.scene_frame_transform_from_capture(
            canonical_views=canonical_views,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    _hydrate_manifest_diagnostics(manifest, output_dir=output_dir)
    _write_contact_sheet(manifest, output_dir=output_dir)
    manifest_path = output_dir / "comparison_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_scene_camera_comparison_report(manifest, output_dir=output_dir)
    return manifest


def render_scene_camera_comparison_report(manifest: dict[str, Any], *, output_dir: Path) -> Path:
    _write_contact_sheet(manifest, output_dir=output_dir)
    _hydrate_manifest_diagnostics(manifest, output_dir=output_dir)
    report_path = output_dir / "report.html"
    report_path.write_text(_report_html(manifest), encoding="utf-8")
    return report_path


def _hydrate_manifest_diagnostics(manifest: dict[str, Any], *, output_dir: Path) -> None:
    builders = (
        (
            "candidate_visual_diagnostics",
            lambda: _candidate_visual_diagnostics(manifest, output_dir=output_dir),
        ),
        (
            "projection_diagnostics",
            lambda: scene_camera_geometry_contract.projection_diagnostics(manifest),
        ),
        ("visual_diagnostics", lambda: _visual_diagnostics(manifest, output_dir=output_dir)),
        (
            "room_wall_light_diagnostics",
            lambda: _room_wall_light_diagnostics(manifest, output_dir=output_dir),
        ),
        ("native_isaac_render_diagnostics", lambda: _native_isaac_render_diagnostics(manifest)),
        ("render_domain_source_diagnostics", lambda: _render_domain_source_diagnostics(manifest)),
        ("render_domain_view_triage", lambda: _render_domain_view_triage(manifest)),
        ("render_domain_contract_probe", lambda: _render_domain_contract_probe(manifest)),
        ("lighting_tone_provenance", lambda: _lighting_tone_provenance(manifest)),
        ("shadow_parity_probe", lambda: _shadow_parity_probe(manifest)),
        ("backend_swap_geometry_contract", lambda: _backend_swap_geometry_contract(manifest)),
    )
    for key, build in builders:
        if not isinstance(manifest.get(key), dict):
            manifest[key] = build()


def _report_html(manifest: dict[str, Any]) -> str:
    """Render a compact review index; the JSON manifest remains the evidence owner."""
    title = "MolmoSpaces / Isaac Scene Camera Comparison"
    purpose = html.escape(str(manifest.get("purpose") or "Render-only scene identity probe."))
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    contact_sheet = html.escape(str(artifacts.get("contact_sheet") or "contact_sheet.png"))
    manifest_json = html.escape(json.dumps(manifest, indent=2, sort_keys=True))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem}}
img{{max-width:100%;height:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style></head>
<body><h1>{title}</h1><p>{purpose}</p><h2>Contact Sheet</h2>
<a href="{contact_sheet}"><img src="{contact_sheet}" alt="Scene camera contact sheet"></a>
<h2>Comparison Manifest</h2><pre>{manifest_json}</pre></body></html>"""


def comparison_successful(manifest: dict[str, Any]) -> bool:
    lanes = manifest.get("lanes") or {}
    lanes_successful = bool(lanes) and all(
        isinstance(lane, dict) and lane.get("status") == "success" for lane in lanes.values()
    )
    if not lanes_successful:
        return False
    candidate_visual = (
        manifest.get("candidate_visual_diagnostics")
        if isinstance(manifest.get("candidate_visual_diagnostics"), dict)
        else {}
    )
    return str(candidate_visual.get("status") or "") not in {"degraded_visual_fidelity"}


def failed_lane_summaries(manifest: dict[str, Any]) -> list[str]:
    summaries = []
    for lane_id, lane in (manifest.get("lanes") or {}).items():
        if not isinstance(lane, dict) or lane.get("status") == "success":
            continue
        failure = lane.get("failure") if isinstance(lane.get("failure"), dict) else {}
        summaries.append(f"{lane_id}: {failure.get('message') or lane.get('status')}")
    candidate_visual = (
        manifest.get("candidate_visual_diagnostics")
        if isinstance(manifest.get("candidate_visual_diagnostics"), dict)
        else {}
    )
    if candidate_visual.get("status") == "degraded_visual_fidelity":
        next_action = (
            candidate_visual.get("recommended_next_action") or "review candidate render quality"
        )
        summaries.append(f"candidate visual fidelity: {next_action}")
    return summaries


def _lane_order(manifest: dict[str, Any]) -> list[str]:
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), dict) else {}
    registry = (
        manifest.get("lane_registry") if isinstance(manifest.get("lane_registry"), dict) else {}
    )
    ordered: list[str] = []
    baseline = registry.get("baseline")
    if isinstance(baseline, str):
        ordered.append(baseline)
    candidates = registry.get("candidates") if isinstance(registry.get("candidates"), list) else []
    for lane_id in candidates:
        if isinstance(lane_id, str) and lane_id not in ordered:
            ordered.append(lane_id)
    for fallback in (MOLMOSPACES_LANE_ID, ISAAC_LANE_ID):
        if fallback in lanes and fallback not in ordered:
            ordered.append(fallback)
    for lane_id in lanes:
        if isinstance(lane_id, str) and lane_id not in ordered:
            ordered.append(lane_id)
    return ordered


def _official_molmospaces_source() -> dict[str, Any]:
    try:
        distribution = metadata.distribution("molmo-spaces")
    except metadata.PackageNotFoundError:
        return {
            "package": "molmo-spaces",
            "status": "not_installed",
            "expected_source": "https://github.com/allenai/molmospaces",
        }
    try:
        direct_url_text = distribution.read_text("direct_url.json")
    except OSError as exc:
        return _molmospaces_source_metadata_error(status="metadata_unreadable", error=exc)
    if not direct_url_text:
        return _molmospaces_source_metadata_error(status="metadata_unavailable")
    try:
        payload = parse_json_object_text(direct_url_text, label="molmo-spaces direct_url.json")
    except ValueError as exc:
        return _molmospaces_source_metadata_error(status="metadata_unreadable", error=exc)
    vcs_info = payload.get("vcs_info") if isinstance(payload, dict) else {}
    return {
        "package": "molmo-spaces",
        "status": "installed",
        "url": str(payload.get("url") or ""),
        "vcs": str(vcs_info.get("vcs") or "") if isinstance(vcs_info, dict) else "",
        "commit_id": str(vcs_info.get("commit_id") or "") if isinstance(vcs_info, dict) else "",
        "requested_revision": str(vcs_info.get("requested_revision") or "")
        if isinstance(vcs_info, dict)
        else "",
    }


def _molmospaces_source_metadata_error(
    *,
    status: str,
    error: BaseException | None = None,
) -> dict[str, Any]:
    payload = {
        "package": "molmo-spaces",
        "status": status,
        "expected_source": "https://github.com/allenai/molmospaces",
    }
    if error is not None:
        payload["error"] = str(error)
    return payload


def _runtime_object_positions(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = state.get("objects") if isinstance(state.get("objects"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for object_key, item in objects.items():
        if not isinstance(item, dict):
            continue
        position = item.get("position")
        if not scene_camera_geometry_contract.is_vec3(position):
            continue
        result[str(object_key)] = {
            "category": item.get("category") or "",
            "position": [float(value) for value in position[:3]],
            "seeded_start_receptacle_id": item.get("seeded_start_receptacle_id") or "",
            "target_receptacle_id": item.get("target_receptacle_id") or "",
            "location_id": item.get("location_id") or "",
            "location_relation": item.get("location_relation") or "",
            "contained_in": item.get("contained_in"),
            "upstream_object_id": item.get("upstream_object_id") or "",
        }
    return result


def _runtime_render_state(state: dict[str, Any]) -> dict[str, Any]:
    runtime_state = (
        state.get("runtime_render_state")
        if isinstance(state.get("runtime_render_state"), dict)
        else {}
    )
    if runtime_state:
        return runtime_state
    positions = _runtime_object_positions(state)
    return {
        "schema": "molmospaces_runtime_render_state_v1",
        "status": "positions_only_legacy_state",
        "source": "legacy_runtime_object_positions_without_articulation",
        "object_count": len(positions),
        "articulated_object_count": 0,
        "objects": {
            object_key: {
                "object_key": object_key,
                "category": value.get("category") or "",
                "position": value.get("position") or [],
                "subtree_joint_count": 0,
                "articulation_status": "unknown_legacy_state",
                "articulation_joints": [],
            }
            for object_key, value in positions.items()
        },
    }


def _capture_molmospaces_lane(config: SceneCameraComparisonConfig) -> dict[str, Any]:
    lane_dir = config.output_dir / "molmospaces"
    try:
        backend = MolmoSpacesSubprocessBackend(
            run_dir=lane_dir,
            seed=config.seed,
            python_executable=config.molmospaces_python,
            scene_source=config.scene_source,
            scene_index=config.scene_index,
            include_robot=False,
            generated_mess_count=config.generated_mess_count,
        )
        try:
            state = backend._read_state()
            return {
                "status": "success",
                "python_executable": str(config.molmospaces_python),
                "runtime": dict(backend.runtime),
                "scene_xml": backend.scene_xml,
                "requested_generated_mess_count": backend.requested_generated_mess_count,
                "generated_mess_count": backend.generated_mess_count,
                "_state": state,
            }
        finally:
            backend.close()
    except Exception as exc:
        return _lane_failure(config.molmospaces_python, exc)


def _capture_molmospaces_camera_views(
    config: SceneCameraComparisonConfig,
    *,
    camera_request_path: Path,
    lane_dir: Path,
) -> dict[str, Any]:
    try:
        lane_dir.mkdir(parents=True, exist_ok=True)
        backend = MolmoSpacesSubprocessBackend(
            run_dir=lane_dir,
            seed=config.seed,
            python_executable=config.molmospaces_python,
            scene_source=config.scene_source,
            scene_index=config.scene_index,
            include_robot=False,
            generated_mess_count=config.generated_mess_count,
        )
        try:
            result = backend.render_camera_control_request(
                lane_dir / "camera_views",
                request_path=camera_request_path,
            )
        finally:
            backend.close()
        if result.get("ok") is not True:
            raise RuntimeError(f"MolmoSpaces camera view capture failed: {result}")
        return {
            "status": "success",
            "view_variant": result.get("view_variant"),
            "visual_artifact_provenance": result.get("visual_artifact_provenance"),
            "camera_control_api": result.get("camera_control_api"),
            "camera_request_schema": result.get("camera_request_schema"),
            "calibration_status": result.get("calibration_status"),
            "lighting_profile": result.get("lighting_profile") or {},
            "lighting_diagnostics": result.get("lighting_diagnostics") or {},
            "color_profile": result.get("color_profile") or {},
            "color_management": result.get("color_management") or {},
            "lens": result.get("lens") or {},
            "images": _image_entries(output_dir=config.output_dir, result=result),
            "views": result.get("views") or [],
            "camera_control_request": output_relpath(camera_request_path, config.output_dir),
        }
    except Exception as exc:
        return _lane_failure(config.molmospaces_python, exc)


def _capture_isaac_lane(
    config: SceneCameraComparisonConfig,
    *,
    camera_request_path: Path,
    lane_dir: Path,
) -> dict[str, Any]:
    try:
        lane_dir.mkdir(parents=True, exist_ok=True)
        backend = IsaacLabSubprocessBackend(
            run_dir=lane_dir,
            seed=config.seed,
            python_executable=config.isaac_python,
            scene_source=config.scene_source,
            scene_index=config.scene_index,
            include_robot=False,
            generated_mess_count=config.generated_mess_count,
            scene_usd_path=config.scene_usd_path,
            runtime_mode="real",
        )
        result = backend.render_camera_control_request(
            lane_dir / "camera_views",
            request_path=camera_request_path,
        )
        if result.get("ok") is not True:
            raise RuntimeError(f"Isaac camera view capture failed: {result}")
        return {
            "status": "success",
            "python_executable": str(config.isaac_python),
            "runtime": dict(backend.runtime),
            "scene_usd": backend.scene_usd,
            "scene_load": backend.scene_load,
            "scene_index_diagnostics": backend.scene_index_diagnostics,
            "requested_generated_mess_count": backend.requested_generated_mess_count,
            "generated_mess_count": backend.generated_mess_count,
            "view_variant": result.get("view_variant"),
            "visual_artifact_provenance": result.get("visual_artifact_provenance"),
            "camera_control_api": result.get("camera_control_api"),
            "camera_request_schema": result.get("camera_request_schema"),
            "calibration_status": result.get("calibration_status"),
            "lighting_profile": result.get("lighting_profile") or {},
            "lighting_diagnostics": result.get("lighting_diagnostics") or {},
            "color_profile": result.get("color_profile") or {},
            "color_management": result.get("color_management") or {},
            "native_render_diagnostics": result.get("native_render_diagnostics") or {},
            "lens": result.get("lens") or {},
            "derived_lens": result.get("derived_lens") or {},
            "render_steps": result.get("render_steps"),
            "scene_bounds": result.get("scene_bounds"),
            "images": _image_entries(output_dir=config.output_dir, result=result),
            "views": result.get("views") or [],
            "camera_control_request": output_relpath(camera_request_path, config.output_dir),
        }
    except Exception as exc:
        return _lane_failure(config.isaac_python, exc)


def _scene_anchors(state: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    anchors = []
    for item in (state.get("receptacles") or {}).values():
        if not isinstance(item, dict):
            continue
        position = item.get("position")
        if not isinstance(position, list) or len(position) < 3:
            continue
        room_id = str(item.get("room_area") or "")
        room = _room_outline(state, room_id)
        room_center = room.get("center") if isinstance(room.get("center"), list) else None
        anchors.append(
            {
                "anchor_id": str(item.get("receptacle_id") or ""),
                "anchor_kind": "receptacle",
                "category": str(item.get("category") or ""),
                "room_id": room_id,
                "label": str(item.get("name") or item.get("receptacle_id") or ""),
                "molmospaces_position": [
                    float(position[0]),
                    float(position[1]),
                    float(position[2]),
                ],
                "molmospaces_support_top_z": scene_camera_geometry_contract.optional_float(
                    item.get("support_top_z")
                ),
                "room_center_xy": [float(room_center[0]), float(room_center[1])]
                if isinstance(room_center, list) and len(room_center) >= 2
                else None,
            }
        )
    anchors.sort(key=lambda item: (item["room_id"], item["category"], item["anchor_id"]))
    return anchors[:limit]


def _molmospaces_view_specs(
    anchors: list[dict[str, Any]],
    *,
    molmo_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    specs = []
    for index, anchor in enumerate(anchors, start=1):
        position = anchor["molmospaces_position"]
        support_top_z = anchor.get("molmospaces_support_top_z")
        target_z = float(support_top_z) + 0.25 if support_top_z is not None else position[2]
        lookat = [position[0], position[1], max(float(target_z), 0.6)]
        camera_orbit = _anchor_camera_orbit(anchor, state=molmo_state or {})
        specs.append(
            {
                "view_id": f"view_{index:02d}_{_safe_id(anchor['category'])}",
                "label": f"{anchor['room_id']} {anchor['category']} {anchor['anchor_id']}",
                "anchor_id": anchor["anchor_id"],
                "anchor_kind": anchor["anchor_kind"],
                "camera_mode": "anchor_orbit",
                "focus_receptacle_id": anchor["anchor_id"],
                "lookat": lookat,
                "target_source": "molmospaces_metadata_anchor_position",
                "camera_orbit": camera_orbit,
            }
        )
    return specs


def _anchor_camera_orbit(anchor: dict[str, Any], *, state: dict[str, Any]) -> dict[str, float]:
    """Choose a room-interior orbit that keeps the anchor visible in MuJoCo."""

    category = _category_key(anchor.get("category"))
    if category == "sink":
        azimuth = 315.0
    elif category in {"diningtable", "table"}:
        azimuth = 90.0
    elif category == "bed":
        azimuth = _bed_anchor_azimuth(anchor, state=state)
    else:
        azimuth = float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["azimuth_deg"])
    return {
        "distance_m": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["distance_m"]),
        "azimuth_deg": azimuth,
        "elevation_deg": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["elevation_deg"]),
    }


def _bed_anchor_azimuth(anchor: dict[str, Any], *, state: dict[str, Any]) -> float:
    room = _room_outline(state, str(anchor.get("room_id") or ""))
    position = anchor.get("molmospaces_position") if isinstance(anchor, dict) else None
    if room and isinstance(position, list) and len(position) >= 2:
        center = room.get("center")
        if isinstance(center, list) and len(center) >= 2:
            dy = float(position[1]) - float(center[1])
            return 90.0 if dy >= 0 else 225.0
    return 90.0


def _room_outline(state: dict[str, Any], room_id: str) -> dict[str, Any]:
    for room in state.get("room_outlines") or []:
        if isinstance(room, dict) and str(room.get("room_id") or "") == room_id:
            return room
    return {}


def _category_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _isaac_lane_camera_orbit(anchor: dict[str, Any]) -> dict[str, float]:
    category = _category_key(anchor.get("category"))
    if category == "bed":
        azimuth = 225.0
    elif category in {"diningtable", "table"}:
        azimuth = 180.0
    elif category == "sink":
        azimuth = 315.0
    else:
        azimuth = float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["azimuth_deg"])
    return {
        "distance_m": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["distance_m"]),
        "azimuth_deg": azimuth,
        "elevation_deg": float(DEFAULT_SCENE_PROBE_CAMERA_ORBIT["elevation_deg"]),
    }


def _isaac_view_specs(
    anchors: list[dict[str, Any]],
    *,
    scene_usd_path: Path,
    scene_index: int,
) -> list[dict[str, Any]]:
    metadata = scene_camera_usda_contract.load_scene_metadata(scene_usd_path)
    local_scene_index = scene_camera_usda_contract.load_local_isaac_scene_index(scene_usd_path)
    specs = []
    for index, anchor in enumerate(anchors, start=1):
        raw = metadata.get(anchor["anchor_id"]) or {}
        index_entry = scene_camera_usda_contract.isaac_scene_index_entry(
            anchor["anchor_id"], local_scene_index
        )
        usd_prim_path = (
            str(index_entry.get("usd_prim_path") or "") if isinstance(index_entry, dict) else ""
        )
        support_pose = index_entry.get("support_pose") if isinstance(index_entry, dict) else None
        isaac_support_position = scene_camera_usda_contract.support_pose_position(support_pose)
        if not usd_prim_path and raw:
            usd_prim_path = f"/val_{scene_index}/Geometry/{anchor['anchor_id']}"
        specs.append(
            {
                "view_id": f"view_{index:02d}_{_safe_id(anchor['category'])}",
                "label": f"{anchor['room_id']} {anchor['category']} {anchor['anchor_id']}",
                "anchor_id": anchor["anchor_id"],
                "anchor_kind": anchor["anchor_kind"],
                "usd_prim_path": usd_prim_path,
                "target_source": (
                    "isaac_worker_usd_prim_world_bounds_diagnostic"
                    if usd_prim_path
                    else "missing_isaac_usd_prim_path"
                ),
                "isaac_support_position": isaac_support_position,
                "min_target_z": 0.6,
            }
        )
        anchor["isaac_usd_prim_path"] = usd_prim_path
        if isaac_support_position:
            anchor["isaac_support_position"] = isaac_support_position
            anchor["isaac_target_source"] = (
                "Canonical explicit target; Isaac support pose recorded as navigation metadata"
            )
        else:
            anchor["isaac_target_source"] = (
                "Canonical explicit target; USD prim bounds resolved in Isaac worker"
            )
    return specs


def _room_camera_control_views(state: dict[str, Any]) -> list[dict[str, Any]]:
    views = []
    rooms = [room for room in (state.get("room_outlines") or []) if isinstance(room, dict)]
    rooms.sort(key=lambda item: str(item.get("room_id") or ""))
    for index, room in enumerate(rooms, start=1):
        center = room.get("center")
        half_extents = room.get("half_extents")
        if not (
            isinstance(center, list)
            and len(center) >= 2
            and isinstance(half_extents, list)
            and len(half_extents) >= 2
        ):
            continue
        room_id = str(room.get("room_id") or f"room_{index}")
        hx = max(float(half_extents[0]), 0.5)
        hy = max(float(half_extents[1]), 0.5)
        target = [float(center[0]), float(center[1]), ROOM_CAMERA_HEIGHT_M]
        eye = [
            float(center[0]) - hx * ROOM_CAMERA_INSET_FRACTION,
            float(center[1]) - hy * ROOM_CAMERA_INSET_FRACTION,
            ROOM_CAMERA_HEIGHT_M,
        ]
        views.append(
            {
                "view_id": f"room_{index:02d}_{_safe_id(room_id)}",
                "label": f"{room.get('label') or room_id} canonical room view",
                "anchor_id": room_id,
                "anchor_kind": "room",
                "category": "Room",
                "room_id": room_id,
                "camera_mode": "canonical_eye_target",
                "camera_model": CANONICAL_CAMERA_MODEL,
                "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
                "coordinate_convention": MOLMOSPACES_SCENE_FRAME,
                "calibration_status": CANONICAL_POSE_CALIBRATION,
                "eye": eye,
                "target": target,
                "lookat": target,
                "up": [0.0, 0.0, 1.0],
                "camera_basis": "room_center_inset_eye_target",
                "target_source": {
                    MOLMOSPACES_LANE_ID: "molmospaces_room_outline_center",
                    ISAAC_LANE_ID: "canonical_explicit_room_target_from_molmospaces_scene_frame",
                },
                "lane_targets": {
                    MOLMOSPACES_LANE_ID: {"lookat": target, "room_id": room_id},
                    ISAAC_LANE_ID: {"room_id": room_id},
                },
                "room_outline": {
                    "center": [float(center[0]), float(center[1])],
                    "half_extents": [hx, hy],
                    "provenance": str(room.get("provenance") or ""),
                },
            }
        )
    return views


def _canonical_anchor_camera_control_views(
    anchors: list[dict[str, Any]],
    *,
    molmo_specs: list[dict[str, Any]],
    isaac_specs: list[dict[str, Any]],
    scene_transform: dict[str, Any],
) -> list[dict[str, Any]]:
    views = []
    for anchor, molmo_spec, isaac_spec in zip(anchors, molmo_specs, isaac_specs, strict=True):
        target = [float(value) for value in molmo_spec.get("lookat") or []]
        camera_orbit = molmo_spec.get("camera_orbit") or DEFAULT_SCENE_PROBE_CAMERA_ORBIT
        distance = float(
            camera_orbit.get("distance_m", DEFAULT_SCENE_PROBE_CAMERA_ORBIT["distance_m"])
        )
        azimuth = float(
            camera_orbit.get("azimuth_deg", DEFAULT_SCENE_PROBE_CAMERA_ORBIT["azimuth_deg"])
        )
        eye = _eye_from_mujoco_orbit(
            target=target,
            distance=distance,
            azimuth=azimuth,
            elevation=-CANONICAL_CAMERA_ELEVATION_DEG,
        )
        view = {
            "view_id": molmo_spec["view_id"],
            "label": molmo_spec["label"],
            "anchor_id": anchor["anchor_id"],
            "anchor_kind": anchor["anchor_kind"],
            "category": anchor["category"],
            "room_id": anchor["room_id"],
            "camera_mode": "canonical_eye_target",
            "camera_model": CANONICAL_CAMERA_MODEL,
            "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
            "coordinate_convention": MOLMOSPACES_SCENE_FRAME,
            "calibration_status": CANONICAL_POSE_CALIBRATION,
            "eye": eye,
            "target": target,
            "lookat": target,
            "up": [0.0, 0.0, 1.0],
            "camera_basis": "near_topdown_anchor_orbit",
            "backend_transforms": {
                ISAAC_LANE_ID: scene_transform,
            },
            "target_source": {
                MOLMOSPACES_LANE_ID: molmo_spec.get("target_source"),
                ISAAC_LANE_ID: "canonical_explicit_target_from_molmospaces_scene_frame",
            },
            "lane_targets": {
                MOLMOSPACES_LANE_ID: {
                    "lookat": target,
                    "focus_receptacle_id": molmo_spec.get("focus_receptacle_id"),
                },
                ISAAC_LANE_ID: {
                    "usd_prim_path": isaac_spec.get("usd_prim_path"),
                    "support_position": isaac_spec.get("isaac_support_position"),
                    "min_target_z": isaac_spec.get("min_target_z", 0.6),
                },
            },
            "usd_prim_path": isaac_spec.get("usd_prim_path"),
            "min_target_z": isaac_spec.get("min_target_z", 0.6),
        }
        views.append(view)
    return views


_canonical_camera_control_views = _canonical_anchor_camera_control_views


def _camera_control_views(
    anchors: list[dict[str, Any]],
    *,
    molmo_specs: list[dict[str, Any]],
    isaac_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    views = []
    for anchor, molmo_spec, isaac_spec in zip(anchors, molmo_specs, isaac_specs, strict=True):
        view = {
            "view_id": molmo_spec["view_id"],
            "label": molmo_spec["label"],
            "anchor_id": anchor["anchor_id"],
            "anchor_kind": anchor["anchor_kind"],
            "category": anchor["category"],
            "room_id": anchor["room_id"],
            "camera_mode": "anchor_orbit",
            "camera_orbit": dict(
                molmo_spec.get("camera_orbit") or DEFAULT_SCENE_PROBE_CAMERA_ORBIT
            ),
            "lane_camera_orbits": {
                MOLMOSPACES_LANE_ID: dict(
                    molmo_spec.get("camera_orbit") or DEFAULT_SCENE_PROBE_CAMERA_ORBIT
                ),
                ISAAC_LANE_ID: _isaac_lane_camera_orbit(anchor),
            },
            "target_source": {
                MOLMOSPACES_LANE_ID: molmo_spec.get("target_source"),
                ISAAC_LANE_ID: isaac_spec.get("target_source"),
            },
            "lane_targets": {
                MOLMOSPACES_LANE_ID: {
                    "lookat": list(molmo_spec.get("lookat") or []),
                    "focus_receptacle_id": molmo_spec.get("focus_receptacle_id"),
                },
                ISAAC_LANE_ID: {
                    "usd_prim_path": isaac_spec.get("usd_prim_path"),
                    "min_target_z": isaac_spec.get("min_target_z", 0.6),
                },
            },
            "lookat": list(molmo_spec.get("lookat") or []),
            "usd_prim_path": isaac_spec.get("usd_prim_path"),
            "min_target_z": isaac_spec.get("min_target_z", 0.6),
        }
        views.append(view)
    return views


def _write_contact_sheet(manifest: dict[str, Any], *, output_dir: Path) -> Path | None:
    entries = _contact_sheet_entries(manifest, output_dir=output_dir)
    if not entries:
        return None
    contact_path = output_dir / "contact_sheet.png"
    tile_width = 360
    tile_height = 240
    label_height = 44
    gap = 12
    margin = 16
    lanes = tuple(_lane_order(manifest))
    sheet_width = margin * 2 + len(lanes) * tile_width + (len(lanes) - 1) * gap
    sheet_height = margin * 2 + len(entries) * (tile_height + label_height + gap) - gap
    sheet = Image.new("RGB", (sheet_width, sheet_height), (238, 242, 246))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for row_index, entry in enumerate(entries):
        y = margin + row_index * (tile_height + label_height + gap)
        draw.text(
            (margin, y),
            f"{entry['view_id']}  {entry.get('label') or ''}",
            fill=(32, 36, 44),
            font=font,
        )
        for lane_index, lane_id in enumerate(lanes):
            x = margin + lane_index * (tile_width + gap)
            tile_y = y + label_height
            draw.rectangle(
                (x, tile_y, x + tile_width, tile_y + tile_height),
                fill=(255, 255, 255),
                outline=(203, 213, 225),
            )
            image_path = entry["images"].get(lane_id)
            if image_path is None:
                draw.text(
                    (x + 12, tile_y + 12),
                    f"missing {lane_id}",
                    fill=(100, 116, 139),
                    font=font,
                )
                continue
            with Image.open(image_path).convert("RGB") as image:
                image.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
                paste_x = x + (tile_width - image.width) // 2
                paste_y = tile_y + (tile_height - image.height) // 2
                sheet.paste(image, (paste_x, paste_y))
            draw.rectangle((x, tile_y, x + tile_width, tile_y + 18), fill=(15, 23, 42))
            draw.text((x + 6, tile_y + 4), lane_id, fill=(248, 250, 252), font=font)
    contact_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_path)
    manifest.setdefault("artifacts", {})["contact_sheet"] = output_relpath(contact_path, output_dir)
    manifest["contact_sheet"] = {
        "path": output_relpath(contact_path, output_dir),
        "view_count": len(entries),
        "lanes": list(lanes),
        "dimensions": {
            "width": sheet.width,
            "height": sheet.height,
            "channels": 3,
        },
    }
    return contact_path


def _contact_sheet_entries(manifest: dict[str, Any], *, output_dir: Path) -> list[dict[str, Any]]:
    views = [
        item
        for item in manifest.get("canonical_camera_views") or []
        if isinstance(item, dict) and item.get("view_id")
    ]
    entries = []
    for view in views:
        view_id = str(view.get("view_id") or "")
        images: dict[str, Path] = {}
        for lane_id in _lane_order(manifest):
            lane = (manifest.get("lanes") or {}).get(lane_id)
            if not isinstance(lane, dict):
                continue
            lane_images = lane.get("images") if isinstance(lane.get("images"), dict) else {}
            image = lane_images.get(view_id) if isinstance(lane_images, dict) else None
            if not isinstance(image, dict):
                continue
            rel_path = str(image.get("path") or "")
            path = output_dir / rel_path
            if path.is_file():
                images[lane_id] = path
        if images:
            entries.append(
                {
                    "view_id": view_id,
                    "label": view.get("label") or view.get("category") or "",
                    "images": images,
                }
            )
    return entries


def _visual_diagnostics(manifest: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    entries = _contact_sheet_entries(manifest, output_dir=output_dir)
    view_results = []
    replay_results = []
    camera_control = (
        manifest.get("camera_control") if isinstance(manifest.get("camera_control"), dict) else {}
    )
    color_profile = (
        camera_control.get("color_profile")
        if isinstance(camera_control.get("color_profile"), dict)
        else DEFAULT_SCENE_PROBE_COLOR_PROFILE
    )
    color_profile = _normalize_color_profile_for_replay(color_profile)
    for entry in entries:
        molmo_path = entry["images"].get(MOLMOSPACES_LANE_ID)
        isaac_path = entry["images"].get(ISAAC_LANE_ID)
        if molmo_path is None or isaac_path is None:
            continue
        molmo_metrics = _image_visual_metrics(molmo_path)
        isaac_metrics = _image_visual_metrics(isaac_path)
        diff_metrics = _image_pair_visual_delta(molmo_path, isaac_path)
        view_results.append(
            {
                "view_id": entry["view_id"],
                "label": entry.get("label") or "",
                "lanes": {
                    MOLMOSPACES_LANE_ID: molmo_metrics,
                    ISAAC_LANE_ID: isaac_metrics,
                },
                "delta": {
                    **diff_metrics,
                    "mean_luminance_delta": (
                        isaac_metrics["mean_luminance"] - molmo_metrics["mean_luminance"]
                    ),
                    "mean_rgb_abs_delta": [
                        abs(
                            float(isaac_metrics["mean_rgb"][index])
                            - float(molmo_metrics["mean_rgb"][index])
                        )
                        for index in range(3)
                    ],
                },
            }
        )
        replay_results.append(
            _offline_color_profile_replay(
                view_id=entry["view_id"],
                label=entry.get("label") or "",
                molmo_path=molmo_path,
                isaac_path=isaac_path,
                color_profile=color_profile,
            )
        )
    luminance_deltas = [
        abs(float(item["delta"]["mean_luminance_delta"]))
        for item in view_results
        if isinstance(item.get("delta"), dict)
    ]
    mae_values = [
        float(item["delta"]["mean_absolute_pixel_delta"])
        for item in view_results
        if isinstance(item.get("delta"), dict)
    ]
    max_overexposed_fraction = 0.0
    max_underexposed_fraction = 0.0
    for item in view_results:
        lanes = item.get("lanes") if isinstance(item.get("lanes"), dict) else {}
        for metrics in lanes.values():
            if not isinstance(metrics, dict):
                continue
            max_overexposed_fraction = max(
                max_overexposed_fraction,
                float(metrics.get("overexposed_fraction") or 0.0),
            )
            max_underexposed_fraction = max(
                max_underexposed_fraction,
                float(metrics.get("underexposed_fraction") or 0.0),
            )
    return {
        "schema": "scene_camera_visual_diagnostics_v1",
        "status": "computed" if view_results else "missing_view_images",
        "interpretation": (
            "These image-level metrics quantify renderer/material/lighting differences after "
            "pose, intrinsics, room-scale, and target diagnostics pass. They are not a "
            "camera-pose contract."
        ),
        "view_count": len(view_results),
        "max_abs_mean_luminance_delta": max(luminance_deltas) if luminance_deltas else None,
        "mean_abs_mean_luminance_delta": (
            sum(luminance_deltas) / len(luminance_deltas) if luminance_deltas else None
        ),
        "max_mean_absolute_pixel_delta": max(mae_values) if mae_values else None,
        "mean_absolute_pixel_delta": sum(mae_values) / len(mae_values) if mae_values else None,
        "max_overexposed_fraction": max_overexposed_fraction,
        "max_underexposed_fraction": max_underexposed_fraction,
        "render_domain_calibration": _render_domain_calibration(view_results),
        "color_profile_replay": _color_profile_replay_summary(replay_results),
        "candidate_color_calibrations": _candidate_color_calibrations(
            view_results,
            entries=entries,
            base_color_profile=color_profile,
        ),
        "views": view_results,
    }


def _room_wall_light_diagnostics(manifest: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    entries = [
        entry
        for entry in _contact_sheet_entries(manifest, output_dir=output_dir)
        if _is_room_view(manifest, str(entry.get("view_id") or ""))
    ]
    registry = (
        manifest.get("lane_registry") if isinstance(manifest.get("lane_registry"), dict) else {}
    )
    baseline_id = str(registry.get("baseline") or MOLMOSPACES_LANE_ID)
    candidate_ids = [lane_id for lane_id in _lane_order(manifest) if lane_id != baseline_id]
    pairs = []
    for entry in entries:
        view_id = str(entry.get("view_id") or "")
        baseline_path = entry["images"].get(baseline_id)
        if baseline_path is None:
            continue
        baseline_image = _image_visual_metrics(baseline_path)
        baseline_wall = _image_region_visual_metrics(
            baseline_path,
            region_id="upper_center_wall_proxy",
        )
        for candidate_id in candidate_ids:
            candidate_path = entry["images"].get(candidate_id)
            if candidate_path is None:
                continue
            candidate_image = _image_visual_metrics(candidate_path)
            candidate_wall = _image_region_visual_metrics(
                candidate_path,
                region_id="upper_center_wall_proxy",
            )
            image_delta = float(candidate_image["mean_luminance"]) - float(
                baseline_image["mean_luminance"]
            )
            wall_delta = float(candidate_wall["mean_luminance"]) - float(
                baseline_wall["mean_luminance"]
            )
            pairs.append(
                {
                    "view_id": view_id,
                    "label": entry.get("label") or "",
                    "candidate": candidate_id,
                    "baseline": baseline_id,
                    "region_id": "upper_center_wall_proxy",
                    "baseline_image_luminance": baseline_image["mean_luminance"],
                    "candidate_image_luminance": candidate_image["mean_luminance"],
                    "image_luminance_delta": image_delta,
                    "baseline_wall_luminance": baseline_wall["mean_luminance"],
                    "candidate_wall_luminance": candidate_wall["mean_luminance"],
                    "wall_luminance_delta": wall_delta,
                    "wall_luminance_ratio": (
                        float(candidate_wall["mean_luminance"])
                        / float(baseline_wall["mean_luminance"])
                    )
                    if float(baseline_wall["mean_luminance"]) > 0
                    else None,
                    "classification": _room_wall_light_classification(
                        image_delta=image_delta,
                        wall_delta=wall_delta,
                    ),
                }
            )
    if not pairs:
        return {
            "schema": "scene_camera_room_wall_light_diagnostics_v1",
            "status": "missing_room_view_pairs",
            "room_view_count": len(entries),
            "candidate_count": len(candidate_ids),
            "region_id": "upper_center_wall_proxy",
            "interpretation": (
                "No room-view baseline/candidate image pairs were available for wall-light review."
            ),
            "pairs": [],
        }
    dark_wall_pairs = [
        item
        for item in pairs
        if item.get("classification")
        in {
            "candidate_wall_proxy_darker_than_baseline",
            "candidate_global_tone_darker_than_baseline",
        }
    ]
    wall_specific_pairs = [
        item
        for item in pairs
        if item.get("classification") == "candidate_wall_proxy_darker_than_baseline"
    ]
    if wall_specific_pairs:
        status = "wall_light_or_shadow_delta"
        next_action = (
            "Inspect room lights, wall/ceiling shadow flags, and wall material albedo before "
            "changing camera geometry or accepting a simple global gain."
        )
    elif dark_wall_pairs:
        status = "global_tone_or_exposure_delta"
        next_action = (
            "A candidate room view is darker as a whole; compare exposure/gain before "
            "local wall-light tuning."
        )
    else:
        status = "wall_proxy_luminance_reviewable"
        next_action = ""
    return {
        "schema": "scene_camera_room_wall_light_diagnostics_v1",
        "status": status,
        "room_view_count": len(entries),
        "candidate_count": len(candidate_ids),
        "pair_count": len(pairs),
        "dark_wall_pair_count": len(dark_wall_pairs),
        "wall_specific_pair_count": len(wall_specific_pairs),
        "region_id": "upper_center_wall_proxy",
        "region_note": (
            "This is an image-space proxy over the upper-center room view, not semantic wall "
            "segmentation. It is intended to catch the dark-wall failure mode visible in "
            "review artifacts."
        ),
        "interpretation": (
            "Room/wall diagnostics compare baseline and candidate luminance in room views. "
            "They separate wall-proxy darkness from object-anchor material deltas."
        ),
        "recommended_next_action": next_action,
        "pairs": pairs,
    }


def _room_wall_light_classification(*, image_delta: float, wall_delta: float) -> str:
    if wall_delta <= -25.0 and abs(image_delta) < 20.0:
        return "candidate_wall_proxy_darker_than_baseline"
    if wall_delta <= -25.0 and image_delta <= -20.0:
        return "candidate_global_tone_darker_than_baseline"
    if abs(wall_delta) <= 12.0:
        return "wall_proxy_luminance_matched"
    if wall_delta >= 25.0:
        return "candidate_wall_proxy_brighter_than_baseline"
    return "wall_proxy_luminance_delta"


def _is_room_view(manifest: dict[str, Any], view_id: str) -> bool:
    if view_id.startswith("room_"):
        return True
    for item in manifest.get("canonical_camera_views") or []:
        if (
            isinstance(item, dict)
            and str(item.get("view_id") or "") == view_id
            and str(item.get("anchor_kind") or "") == "room"
        ):
            return True
    return False


def _candidate_visual_diagnostics(manifest: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    entries = _contact_sheet_entries(manifest, output_dir=output_dir)
    registry = (
        manifest.get("lane_registry") if isinstance(manifest.get("lane_registry"), dict) else {}
    )
    baseline_id = str(registry.get("baseline") or MOLMOSPACES_LANE_ID)
    candidate_ids = [
        str(lane_id)
        for lane_id in _lane_order(manifest)
        if isinstance(lane_id, str) and lane_id != baseline_id
    ]
    candidate_summaries = []
    degraded_candidates = []
    for candidate_id in candidate_ids:
        summary = _candidate_visual_summary(
            manifest,
            entries=entries,
            baseline_id=baseline_id,
            candidate_id=candidate_id,
        )
        candidate_summaries.append(summary)
        if summary.get("status") == "degraded_visual_fidelity":
            degraded_candidates.append(candidate_id)
    status = "computed"
    if not candidate_summaries:
        status = "missing_candidate_lanes"
    elif degraded_candidates:
        status = "degraded_visual_fidelity"
    return {
        "schema": "scene_camera_candidate_visual_diagnostics_v1",
        "status": status,
        "baseline": baseline_id,
        "candidate_count": len(candidate_summaries),
        "degraded_candidates": degraded_candidates,
        "thresholds": {
            "mean_absolute_pixel_delta_warn": CANDIDATE_VISUAL_MEAN_PIXEL_DELTA_WARN,
            "max_mean_absolute_pixel_delta_warn": CANDIDATE_VISUAL_MAX_PIXEL_DELTA_WARN,
        },
        "interpretation": (
            "Candidate visual diagnostics compare each opt-in render lane against the "
            "MuJoCo baseline. Runtime success and nonblank images are necessary but not "
            "sufficient for visual acceptance."
        ),
        "recommended_next_action": _candidate_visual_next_action(degraded_candidates),
        "candidates": candidate_summaries,
    }


def _candidate_visual_summary(
    manifest: dict[str, Any],
    *,
    entries: list[dict[str, Any]],
    baseline_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    lane = (manifest.get("lanes") or {}).get(candidate_id)
    if not isinstance(lane, dict):
        return {
            "candidate": candidate_id,
            "status": "missing_candidate_lane",
            "views": [],
        }
    view_results = []
    for entry in entries:
        baseline_path = entry["images"].get(baseline_id)
        candidate_path = entry["images"].get(candidate_id)
        if baseline_path is None or candidate_path is None:
            continue
        baseline_metrics = _image_visual_metrics(baseline_path)
        candidate_metrics = _image_visual_metrics(candidate_path)
        diff_metrics = _image_pair_visual_delta(baseline_path, candidate_path)
        view_results.append(
            {
                "view_id": entry["view_id"],
                "label": entry.get("label") or "",
                "lanes": {
                    baseline_id: baseline_metrics,
                    candidate_id: candidate_metrics,
                },
                "delta": {
                    **diff_metrics,
                    "mean_luminance_delta": (
                        candidate_metrics["mean_luminance"] - baseline_metrics["mean_luminance"]
                    ),
                    "mean_rgb_abs_delta": [
                        abs(
                            float(candidate_metrics["mean_rgb"][index])
                            - float(baseline_metrics["mean_rgb"][index])
                        )
                        for index in range(3)
                    ],
                },
            }
        )
    mae_values = [
        float(item["delta"]["mean_absolute_pixel_delta"])
        for item in view_results
        if isinstance(item.get("delta"), dict)
    ]
    warning_reasons = _candidate_visual_warning_reasons(
        mae_values=mae_values,
    )
    status = "computed"
    if not view_results:
        status = "missing_view_images"
    elif warning_reasons:
        status = "degraded_visual_fidelity"
    return {
        "candidate": candidate_id,
        "status": status,
        "view_count": len(view_results),
        "warning_reasons": warning_reasons,
        "mean_absolute_pixel_delta": sum(mae_values) / len(mae_values) if mae_values else None,
        "max_mean_absolute_pixel_delta": max(mae_values) if mae_values else None,
        "views": view_results,
    }


def _candidate_visual_warning_reasons(
    *,
    mae_values: list[float],
) -> list[str]:
    reasons = []
    if mae_values:
        mean_value = sum(mae_values) / len(mae_values)
        max_value = max(mae_values)
        if mean_value > CANDIDATE_VISUAL_MEAN_PIXEL_DELTA_WARN:
            reasons.append("mean_absolute_pixel_delta_above_warning_threshold")
        if max_value > CANDIDATE_VISUAL_MAX_PIXEL_DELTA_WARN:
            reasons.append("max_mean_absolute_pixel_delta_above_warning_threshold")
    return reasons


def _candidate_visual_next_action(degraded_candidates: list[str]) -> str:
    if not degraded_candidates:
        return ""
    return "Review candidate render quality before accepting the comparison artifact."


def _candidate_color_calibrations(
    view_results: list[dict[str, Any]],
    *,
    entries: list[dict[str, Any]],
    base_color_profile: dict[str, Any],
) -> dict[str, Any]:
    if not view_results:
        return {
            "schema": "scene_camera_candidate_color_calibrations_v1",
            "status": "missing_view_metrics",
            "candidates": [],
        }
    entry_by_id = {str(item.get("view_id") or ""): item for item in entries}
    candidates = [
        _candidate_color_calibration(
            "current_profile",
            view_results,
            entry_by_id=entry_by_id,
            base_color_profile=base_color_profile,
            color_profile=base_color_profile,
            interpretation="Current camera-control color profile replay.",
        ),
        _candidate_color_calibration(
            "ideal_per_view_luminance_gain",
            view_results,
            entry_by_id=entry_by_id,
            base_color_profile=base_color_profile,
            color_profile=_candidate_per_view_luminance_profile(view_results, base_color_profile),
            interpretation=(
                "Upper-bound diagnostic: per-view scalar gains match mean luminance. "
                "Do not promote directly without broader scene validation."
            ),
        ),
        _candidate_color_calibration(
            "ideal_per_view_rgb_gain",
            view_results,
            entry_by_id=entry_by_id,
            base_color_profile=base_color_profile,
            color_profile=_candidate_per_view_rgb_profile(view_results, base_color_profile),
            interpretation=(
                "Upper-bound diagnostic: per-view RGB channel gains match mean RGB. "
                "Useful for separating color response from geometry/material residuals."
            ),
        ),
    ]
    best = min(
        (item for item in candidates if item.get("status") == "computed"),
        key=lambda item: float(item.get("mean_absolute_pixel_delta") or 1e12),
        default=None,
    )
    return {
        "schema": "scene_camera_candidate_color_calibrations_v1",
        "status": "computed",
        "interpretation": (
            "Candidate calibrations replay existing PNGs with generated gain tables. They are "
            "diagnostics for choosing the next renderer slice, not fresh backend renders."
        ),
        "candidate_count": len(candidates),
        "best_candidate": best.get("candidate_id") if isinstance(best, dict) else None,
        "candidates": candidates,
    }


def _candidate_color_calibration(
    candidate_id: str,
    view_results: list[dict[str, Any]],
    *,
    entry_by_id: dict[str, dict[str, Any]],
    base_color_profile: dict[str, Any],
    color_profile: dict[str, Any],
    interpretation: str,
) -> dict[str, Any]:
    replay_results = []
    for item in view_results:
        view_id = str(item.get("view_id") or "")
        entry = entry_by_id.get(view_id)
        if not isinstance(entry, dict):
            continue
        molmo_path = entry["images"].get(MOLMOSPACES_LANE_ID)
        isaac_path = entry["images"].get(ISAAC_LANE_ID)
        if molmo_path is None or isaac_path is None:
            continue
        replay_results.append(
            _offline_color_profile_replay(
                view_id=view_id,
                label=str(item.get("label") or ""),
                molmo_path=molmo_path,
                isaac_path=isaac_path,
                color_profile=color_profile,
            )
        )
    summary = _color_profile_replay_summary(replay_results)
    return {
        "candidate_id": candidate_id,
        "status": summary.get("status"),
        "interpretation": interpretation,
        "gain_delta": _candidate_gain_delta(base_color_profile, color_profile),
        "view_count": summary.get("view_count"),
        "mean_abs_mean_luminance_delta": summary.get("mean_abs_mean_luminance_delta"),
        "mean_absolute_pixel_delta": summary.get("mean_absolute_pixel_delta"),
        "render_domain_calibration": summary.get("render_domain_calibration"),
    }


def _candidate_per_view_luminance_profile(
    view_results: list[dict[str, Any]],
    base_color_profile: dict[str, Any],
) -> dict[str, Any]:
    profile = json.loads(json.dumps(base_color_profile))
    gains: dict[str, float] = {}
    for item in view_results:
        view_id = str(item.get("view_id") or "")
        lanes = item.get("lanes") if isinstance(item.get("lanes"), dict) else {}
        molmo = lanes.get(MOLMOSPACES_LANE_ID) if isinstance(lanes, dict) else {}
        isaac = lanes.get(ISAAC_LANE_ID) if isinstance(lanes, dict) else {}
        molmo_luminance = scene_camera_geometry_contract.optional_float(
            molmo.get("mean_luminance") if isinstance(molmo, dict) else None
        )
        isaac_luminance = scene_camera_geometry_contract.optional_float(
            isaac.get("mean_luminance") if isinstance(isaac, dict) else None
        )
        if not view_id or molmo_luminance is None or isaac_luminance is None:
            continue
        gains[view_id] = molmo_luminance / isaac_luminance if isaac_luminance > 0 else 1.0
    if gains:
        profile["backend_view_luminance_gain"] = {ISAAC_LANE_ID: gains}
        profile["backend_view_luminance_gain_source"] = "candidate_from_current_view_metrics"
    return profile


def _candidate_per_view_rgb_profile(
    view_results: list[dict[str, Any]],
    base_color_profile: dict[str, Any],
) -> dict[str, Any]:
    profile = json.loads(json.dumps(base_color_profile))
    gains: dict[str, list[float]] = {}
    for item in view_results:
        view_id = str(item.get("view_id") or "")
        lanes = item.get("lanes") if isinstance(item.get("lanes"), dict) else {}
        molmo = lanes.get(MOLMOSPACES_LANE_ID) if isinstance(lanes, dict) else {}
        isaac = lanes.get(ISAAC_LANE_ID) if isinstance(lanes, dict) else {}
        molmo_rgb = molmo.get("mean_rgb") if isinstance(molmo, dict) else None
        isaac_rgb = isaac.get("mean_rgb") if isinstance(isaac, dict) else None
        if not view_id or not isinstance(molmo_rgb, list) or not isinstance(isaac_rgb, list):
            continue
        channel_gains = []
        for molmo_value, isaac_value in zip(molmo_rgb[:3], isaac_rgb[:3], strict=False):
            molmo_float = scene_camera_geometry_contract.optional_float(molmo_value)
            isaac_float = scene_camera_geometry_contract.optional_float(isaac_value)
            if molmo_float is None or isaac_float is None or isaac_float <= 0:
                channel_gains.append(1.0)
            else:
                channel_gains.append(molmo_float / isaac_float)
        if len(channel_gains) == 3:
            gains[view_id] = channel_gains
    if gains:
        profile["backend_view_rgb_gain"] = {ISAAC_LANE_ID: gains}
        profile["backend_view_rgb_gain_source"] = "candidate_from_current_view_metrics"
        profile["backend_view_luminance_gain"] = {
            ISAAC_LANE_ID: {view_id: 1.0 for view_id in gains}
        }
        profile["backend_view_luminance_gain_source"] = (
            "candidate_rgb_gain_already_includes_luminance"
        )
    return profile


def _candidate_gain_delta(
    base_color_profile: dict[str, Any],
    color_profile: dict[str, Any],
) -> dict[str, Any]:
    keys = (
        "backend_view_luminance_gain",
        "backend_view_rgb_gain",
        "backend_luminance_gain",
        "backend_rgb_gain",
    )
    return {
        key: color_profile.get(key)
        for key in keys
        if color_profile.get(key) != base_color_profile.get(key)
    }


def _offline_color_profile_replay(
    *,
    view_id: str,
    label: str,
    molmo_path: Path,
    isaac_path: Path,
    color_profile: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    molmo_replay_path = _color_profile_replay_image(
        molmo_path,
        np=np,
        color_profile=color_profile,
        backend=MOLMOSPACES_LANE_ID,
        view_id=view_id,
    )
    isaac_replay_path = _color_profile_replay_image(
        isaac_path,
        np=np,
        color_profile=color_profile,
        backend=ISAAC_LANE_ID,
        view_id=view_id,
    )
    molmo_metrics = _image_visual_metrics(molmo_replay_path)
    isaac_metrics = _image_visual_metrics(isaac_replay_path)
    diff_metrics = _image_pair_visual_delta(molmo_replay_path, isaac_replay_path)
    return {
        "view_id": view_id,
        "label": label,
        "lanes": {
            MOLMOSPACES_LANE_ID: molmo_metrics,
            ISAAC_LANE_ID: isaac_metrics,
        },
        "delta": {
            **diff_metrics,
            "mean_luminance_delta": isaac_metrics["mean_luminance"]
            - molmo_metrics["mean_luminance"],
        },
    }


def _normalize_color_profile_for_replay(color_profile: dict[str, Any]) -> dict[str, Any]:
    request = normalize_camera_control_request(
        {
            "render_resolution": {"width": 1, "height": 1},
            "color_profile": color_profile,
            "views": [],
        }
    )
    return dict(request.get("color_profile") or {})


def _color_profile_replay_image(
    path: Path,
    *,
    np: Any,
    color_profile: dict[str, Any],
    backend: str,
    view_id: str,
) -> Path:
    with Image.open(path).convert("RGB") as image:
        array = np.asarray(image)
    rgb_gain = _color_profile_backend_rgb_gain(
        color_profile,
        backend=backend,
        view_id=view_id,
    )
    adjusted = array.astype("float32") * np.asarray(rgb_gain, dtype="float32").reshape(1, 1, 3)
    gain = _color_profile_backend_luminance_gain(
        color_profile,
        backend=backend,
        view_id=view_id,
    )
    adjusted = np.clip(adjusted * gain, 0, 255).astype("uint8")
    replay_path = path.with_name(f"{path.stem}.color_profile_replay.png")
    Image.fromarray(adjusted).save(replay_path)
    return replay_path


def _color_profile_backend_luminance_gain(
    color_profile: dict[str, Any],
    *,
    backend: str,
    view_id: str,
) -> float:
    view_gains = color_profile.get("backend_view_luminance_gain")
    if isinstance(view_gains, dict):
        backend_view_gains = view_gains.get(backend)
        if isinstance(backend_view_gains, dict) and view_id in backend_view_gains:
            try:
                return float(backend_view_gains[view_id])
            except (TypeError, ValueError):
                return 1.0
    gains = color_profile.get("backend_luminance_gain")
    if not isinstance(gains, dict) or backend not in gains:
        return 1.0
    try:
        return float(gains[backend])
    except (TypeError, ValueError):
        return 1.0


def _color_profile_backend_rgb_gain(
    color_profile: dict[str, Any],
    *,
    backend: str,
    view_id: str,
) -> list[float]:
    view_gains = color_profile.get("backend_view_rgb_gain")
    if isinstance(view_gains, dict):
        backend_view_gains = view_gains.get(backend)
        if isinstance(backend_view_gains, dict) and view_id in backend_view_gains:
            return _rgb_gain_or_identity(backend_view_gains[view_id])
    gains = color_profile.get("backend_rgb_gain")
    if isinstance(gains, dict) and backend in gains:
        return _rgb_gain_or_identity(gains[backend])
    return [1.0, 1.0, 1.0]


def _rgb_gain_or_identity(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return [1.0, 1.0, 1.0]
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return [1.0, 1.0, 1.0]


def _color_profile_replay_summary(view_results: list[dict[str, Any]]) -> dict[str, Any]:
    if not view_results:
        return {
            "schema": "scene_camera_color_profile_replay_v1",
            "status": "missing_view_images",
            "view_count": 0,
        }
    luminance_deltas = [
        abs(float(item["delta"]["mean_luminance_delta"]))
        for item in view_results
        if isinstance(item.get("delta"), dict)
    ]
    mae_values = [
        float(item["delta"]["mean_absolute_pixel_delta"])
        for item in view_results
        if isinstance(item.get("delta"), dict)
    ]
    return {
        "schema": "scene_camera_color_profile_replay_v1",
        "status": "computed",
        "interpretation": (
            "Offline replay applies only the current backend_luminance_gain delta to "
            "existing already-color-managed PNGs. It estimates the expected direction of "
            "renderer calibration without claiming a fresh backend rerender."
        ),
        "view_count": len(view_results),
        "mean_abs_mean_luminance_delta": (
            sum(luminance_deltas) / len(luminance_deltas) if luminance_deltas else None
        ),
        "max_abs_mean_luminance_delta": max(luminance_deltas) if luminance_deltas else None,
        "mean_absolute_pixel_delta": sum(mae_values) / len(mae_values) if mae_values else None,
        "max_mean_absolute_pixel_delta": max(mae_values) if mae_values else None,
        "render_domain_calibration": _render_domain_calibration(view_results),
        "views": view_results,
    }


def _render_domain_calibration(view_results: list[dict[str, Any]]) -> dict[str, Any]:
    return scene_camera_image_metrics.render_domain_calibration(
        view_results,
        baseline_lane_id=MOLMOSPACES_LANE_ID,
        candidate_lane_id=ISAAC_LANE_ID,
        optional_float=scene_camera_geometry_contract.optional_float,
    )


def _backend_swap_geometry_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    return scene_camera_render_domain.backend_swap_geometry_contract(
        manifest,
        optional_float=scene_camera_geometry_contract.optional_float,
    )


def _render_domain_source_diagnostics(manifest: dict[str, Any]) -> dict[str, Any]:
    return scene_camera_render_domain.render_domain_source_diagnostics(manifest)


def _render_domain_view_triage(manifest: dict[str, Any]) -> dict[str, Any]:
    return scene_camera_render_domain.render_domain_view_triage(
        manifest,
        optional_float=scene_camera_geometry_contract.optional_float,
        view_usd_prim_path=_view_usd_prim_path,
    )


def _view_usd_prim_path(manifest: dict[str, Any], view_id: str) -> str:
    return _view_usd_prim_path_impl(manifest, view_id, isaac_lane_id=ISAAC_LANE_ID)


def _render_domain_contract_probe(manifest: dict[str, Any]) -> dict[str, Any]:
    return scene_camera_render_domain.render_domain_contract_probe(
        manifest,
        render_domain_view_triage_builder=_render_domain_view_triage,
        mujoco_render_contract_from_xml=_mujoco_render_contract_from_xml,
        isaac_render_contract_from_usda=_isaac_render_contract_from_usda,
        view_usd_prim_path=_view_usd_prim_path,
    )


_mujoco_view_render_contract = scene_camera_render_domain.mujoco_view_render_contract
_isaac_view_render_contract = scene_camera_render_domain.isaac_view_render_contract
_view_render_contract_delta = scene_camera_render_domain.view_render_contract_delta


def _eye_from_mujoco_orbit(
    *,
    target: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> list[float]:
    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)
    horizontal = math.cos(elevation_rad) * distance
    return [
        float(target[0]) - math.cos(azimuth_rad) * horizontal,
        float(target[1]) - math.sin(azimuth_rad) * horizontal,
        float(target[2]) - math.sin(elevation_rad) * distance,
    ]


def _canonical_eye_from_room_context(
    anchor: dict[str, Any],
    *,
    target: list[float],
    distance: float,
    azimuth: float,
    elevation: float,
) -> tuple[list[float], str]:
    room_center = anchor.get("room_center_xy")
    if isinstance(room_center, list) and len(room_center) >= 2:
        dx = float(room_center[0]) - float(target[0])
        dy = float(room_center[1]) - float(target[1])
        norm = math.hypot(dx, dy)
        if norm > 1e-6:
            elevation_rad = math.radians(elevation)
            horizontal = math.cos(elevation_rad) * distance
            return (
                [
                    float(target[0]) + dx / norm * horizontal,
                    float(target[1]) + dy / norm * horizontal,
                    float(target[2]) - math.sin(elevation_rad) * distance,
                ],
                "room_center_to_anchor",
            )
    return (
        _eye_from_mujoco_orbit(
            target=target,
            distance=distance,
            azimuth=azimuth,
            elevation=elevation,
        ),
        "anchor_orbit_fallback",
    )


def _image_entries(*, output_dir: Path, result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    images = result.get("images") if isinstance(result.get("images"), dict) else {}
    shapes = result.get("shapes") if isinstance(result.get("shapes"), dict) else {}
    entries = {}
    for view_id, raw_path in images.items():
        path = Path(str(raw_path))
        entries[str(view_id)] = {
            "path": output_relpath(path, output_dir),
            "dimensions": dimensions_from_shape(shapes.get(view_id)),
        }
    return entries


def _lane_failure(python_executable: Path, exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "python_executable": str(python_executable),
        "failure": {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(limit=8),
        },
    }


def _safe_id(value: Any) -> str:
    text = str(value or "scene").lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
    return safe or "scene"


def default_output_dir() -> Path:
    stamp = datetime.now().astimezone().strftime("%m%d_%H%M")
    return Path("output/molmo/scene-camera-comparison") / stamp


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=("Render the same MolmoSpaces scene anchors through MuJoCo and Isaac.")
    )
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--scene-usd-path", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generated-mess-count", type=int, default=1)
    parser.add_argument("--scene-source", default="procthor-10k-val")
    parser.add_argument("--scene-index", type=int, default=1)
    parser.add_argument("--molmospaces-python", type=Path, default=Path(".venv/bin/python"))
    parser.add_argument("--isaac-python", type=Path, default=Path(".venv-isaaclab/bin/python"))
    parser.add_argument("--render-width", type=_positive_int_arg, default=DEFAULT_RENDER_WIDTH)
    parser.add_argument("--render-height", type=_positive_int_arg, default=DEFAULT_RENDER_HEIGHT)
    parser.add_argument(
        "--lighting-profile",
        default="default",
        choices=tuple(sorted(SCENE_PROBE_LIGHTING_PROFILES)),
        help=(
            "Scene-camera lighting profile. Use shadow-parity for a probe run; "
            "default uses the shared scene_light_rig_v1 single-key review profile."
        ),
    )
    args = parser.parse_args(argv)

    if args.scene_usd_path.is_file():
        os.environ.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")
    manifest = run_scene_camera_comparison(
        SceneCameraComparisonConfig(
            output_dir=args.output_dir,
            scene_usd_path=args.scene_usd_path,
            seed=args.seed,
            generated_mess_count=args.generated_mess_count,
            scene_source=args.scene_source,
            scene_index=args.scene_index,
            molmospaces_python=args.molmospaces_python,
            isaac_python=args.isaac_python,
            render_width=args.render_width,
            render_height=args.render_height,
            lighting_profile_id=args.lighting_profile,
        )
    )
    print(f"scene camera comparison manifest: {args.output_dir / 'comparison_manifest.json'}")
    print(f"scene camera comparison report: {args.output_dir / 'report.html'}")
    if comparison_successful(manifest):
        return 0
    print("scene camera comparison failed:", file=sys.stderr)
    for summary in failed_lane_summaries(manifest):
        print(f"  {summary}", file=sys.stderr)
    return 1


def _positive_int_arg(value: str) -> int:
    import argparse

    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
