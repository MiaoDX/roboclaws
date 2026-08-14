from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.household import (
    scene_camera_geometry_contract,
    scene_camera_image_metrics,
    scene_camera_render_contracts,
    scene_camera_render_domain,
    scene_camera_usda_contract,
)
from roboclaws.household.camera_control import normalize_camera_control_request
from roboclaws.household.scene_camera_render_diagnostics import (
    mujoco_render_contract_from_xml as _mujoco_render_contract_from_xml,
)
from roboclaws.household.scene_camera_render_diagnostics import (
    view_usd_prim_path as _view_usd_prim_path_impl,
)
from roboclaws.household.scene_camera_results import contact_sheet_entries, lane_order

MOLMOSPACES_LANE_ID = scene_camera_render_domain.MOLMOSPACES_LANE_ID
ISAAC_LANE_ID = scene_camera_render_domain.ISAAC_LANE_ID
CANDIDATE_VISUAL_MEAN_PIXEL_DELTA_WARN = 45.0
CANDIDATE_VISUAL_MAX_PIXEL_DELTA_WARN = 60.0

_image_visual_metrics = scene_camera_image_metrics.image_visual_metrics
_image_pair_visual_delta = scene_camera_image_metrics.image_pair_visual_delta
_isaac_render_contract_from_usda = scene_camera_usda_contract.isaac_render_contract_from_usda


def _candidate_visual_diagnostics(manifest: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    entries = contact_sheet_entries(manifest, output_dir=output_dir)
    registry = (
        manifest.get("lane_registry") if isinstance(manifest.get("lane_registry"), dict) else {}
    )
    baseline_id = str(registry.get("baseline") or MOLMOSPACES_LANE_ID)
    candidate_ids = [
        str(lane_id)
        for lane_id in lane_order(manifest)
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


_mujoco_view_render_contract = scene_camera_render_contracts.mujoco_view_render_contract
_isaac_view_render_contract = scene_camera_render_contracts.isaac_view_render_contract
_view_render_contract_delta = scene_camera_render_contracts.view_render_contract_delta
