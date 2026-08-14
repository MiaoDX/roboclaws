from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from roboclaws.household import (
    scene_camera_image_metrics,
    scene_camera_lighting_diagnostics,
    scene_camera_projection,
)
from roboclaws.household.artifact_paths import output_relpath
from roboclaws.household.camera_control import DEFAULT_SCENE_PROBE_COLOR_PROFILE
from roboclaws.household.scene_camera_color_diagnostics import (
    _backend_swap_geometry_contract,
    _candidate_color_calibrations,
    _candidate_visual_diagnostics,
    _color_profile_replay_summary,
    _normalize_color_profile_for_replay,
    _offline_color_profile_replay,
    _render_domain_calibration,
    _render_domain_contract_probe,
    _render_domain_source_diagnostics,
    _render_domain_view_triage,
)
from roboclaws.household.scene_camera_results import contact_sheet_entries, lane_order

MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"

_image_visual_metrics = scene_camera_image_metrics.image_visual_metrics
_image_region_visual_metrics = scene_camera_image_metrics.image_region_visual_metrics
_image_pair_visual_delta = scene_camera_image_metrics.image_pair_visual_delta
_native_isaac_render_diagnostics = scene_camera_lighting_diagnostics.native_isaac_render_diagnostics
_lighting_tone_provenance = scene_camera_lighting_diagnostics.lighting_tone_provenance
_shadow_parity_probe = scene_camera_lighting_diagnostics.shadow_parity_probe


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
            lambda: scene_camera_projection.projection_diagnostics(manifest),
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


def _write_contact_sheet(manifest: dict[str, Any], *, output_dir: Path) -> Path | None:
    entries = contact_sheet_entries(manifest, output_dir=output_dir)
    if not entries:
        return None
    contact_path = output_dir / "contact_sheet.png"
    tile_width = 360
    tile_height = 240
    label_height = 44
    gap = 12
    margin = 16
    lanes = tuple(lane_order(manifest))
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

    return entries


def _visual_diagnostics(manifest: dict[str, Any], *, output_dir: Path) -> dict[str, Any]:
    entries = contact_sheet_entries(manifest, output_dir=output_dir)
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
        for entry in contact_sheet_entries(manifest, output_dir=output_dir)
        if _is_room_view(manifest, str(entry.get("view_id") or ""))
    ]
    registry = (
        manifest.get("lane_registry") if isinstance(manifest.get("lane_registry"), dict) else {}
    )
    baseline_id = str(registry.get("baseline") or MOLMOSPACES_LANE_ID)
    candidate_ids = [lane_id for lane_id in lane_order(manifest) if lane_id != baseline_id]
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
