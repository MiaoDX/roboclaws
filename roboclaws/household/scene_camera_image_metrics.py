from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image


def render_domain_calibration(
    view_results: list[dict[str, Any]],
    *,
    baseline_lane_id: str,
    candidate_lane_id: str,
    optional_float: Callable[[Any], float | None],
) -> dict[str, Any]:
    """Estimate whether one global candidate luminance gain explains the visual delta."""
    pairs = []
    for item in view_results:
        lanes = item.get("lanes") if isinstance(item.get("lanes"), dict) else {}
        baseline = (
            lanes.get(baseline_lane_id) if isinstance(lanes.get(baseline_lane_id), dict) else {}
        )
        candidate = (
            lanes.get(candidate_lane_id) if isinstance(lanes.get(candidate_lane_id), dict) else {}
        )
        baseline_luminance = optional_float(baseline.get("mean_luminance"))
        candidate_luminance = optional_float(candidate.get("mean_luminance"))
        if baseline_luminance is None or candidate_luminance is None or candidate_luminance <= 0:
            continue
        pairs.append(
            {
                "view_id": str(item.get("view_id") or ""),
                "molmospaces_luminance": baseline_luminance,
                "isaac_luminance": candidate_luminance,
            }
        )
    if not pairs:
        return {
            "schema": "scene_camera_render_domain_calibration_v1",
            "status": "missing_luminance_pairs",
            "pair_count": 0,
        }

    numerator = sum(pair["molmospaces_luminance"] * pair["isaac_luminance"] for pair in pairs)
    denominator = sum(pair["isaac_luminance"] ** 2 for pair in pairs)
    gain = numerator / denominator if denominator > 0 else 1.0
    residuals = []
    original_abs_deltas = []
    for pair in pairs:
        calibrated = pair["isaac_luminance"] * gain
        residual = calibrated - pair["molmospaces_luminance"]
        original_delta = pair["isaac_luminance"] - pair["molmospaces_luminance"]
        original_abs_deltas.append(abs(original_delta))
        residuals.append(
            {
                **pair,
                "calibrated_isaac_luminance": calibrated,
                "original_luminance_delta": original_delta,
                "calibrated_luminance_residual": residual,
                "abs_calibrated_luminance_residual": abs(residual),
            }
        )
    mean_original_delta = sum(original_abs_deltas) / len(original_abs_deltas)
    abs_residuals = [item["abs_calibrated_luminance_residual"] for item in residuals]
    mean_residual = sum(abs_residuals) / len(abs_residuals)
    max_residual = max(abs_residuals)
    improvement_fraction = (
        1.0 - mean_residual / mean_original_delta if mean_original_delta > 0 else 1.0
    )
    if mean_original_delta <= 10.0:
        status = "already_luminance_matched"
        next_action = "Do not tune exposure from this artifact; inspect material/texture deltas."
    elif mean_residual <= 12.0 and max_residual <= 20.0:
        status = "global_luminance_gain_sufficient"
        next_action = "A global Isaac exposure/gain adjustment is a plausible next renderer slice."
    else:
        status = "view_dependent_render_domain_delta"
        next_action = (
            "A single global gain leaves large residuals; inspect per-room lights, material "
            "albedo, indirect lighting, and tone response before changing camera geometry."
        )
    return {
        "schema": "scene_camera_render_domain_calibration_v1",
        "status": status,
        "pair_count": len(pairs),
        "global_isaac_luminance_gain": gain,
        "mean_abs_original_luminance_delta": mean_original_delta,
        "mean_abs_calibrated_luminance_residual": mean_residual,
        "max_abs_calibrated_luminance_residual": max_residual,
        "mean_luminance_delta_improvement_fraction": improvement_fraction,
        "recommended_next_action": next_action,
        "residuals": residuals,
    }


def image_visual_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path).convert("RGB") as image:
        pixels = list(image.getdata())
    return pixel_visual_metrics(pixels)


def image_region_visual_metrics(path: Path, *, region_id: str) -> dict[str, Any]:
    with Image.open(path).convert("RGB") as image:
        width, height = image.size
        if region_id == "upper_center_wall_proxy":
            left = int(width * 0.30)
            right = max(left + 1, int(width * 0.70))
            top = int(height * 0.08)
            bottom = max(top + 1, int(height * 0.42))
        else:
            left, top, right, bottom = 0, 0, width, height
        pixels = list(image.crop((left, top, right, bottom)).getdata())
    metrics = pixel_visual_metrics(pixels)
    metrics["region_id"] = region_id
    metrics["region_box_fraction"] = {
        "left": left / max(width, 1),
        "top": top / max(height, 1),
        "right": right / max(width, 1),
        "bottom": bottom / max(height, 1),
    }
    return metrics


def pixel_visual_metrics(pixels: list[tuple[int, int, int]]) -> dict[str, Any]:
    count = max(len(pixels), 1)
    sums = [0.0, 0.0, 0.0]
    luminance_sum = 0.0
    luminance_sq_sum = 0.0
    overexposed_count = 0
    underexposed_count = 0
    for red, green, blue in pixels:
        red_f = float(red)
        green_f = float(green)
        blue_f = float(blue)
        sums[0] += red_f
        sums[1] += green_f
        sums[2] += blue_f
        luminance = 0.2126 * red_f + 0.7152 * green_f + 0.0722 * blue_f
        luminance_sum += luminance
        luminance_sq_sum += luminance * luminance
        if red >= 250 and green >= 250 and blue >= 250:
            overexposed_count += 1
        if red <= 5 and green <= 5 and blue <= 5:
            underexposed_count += 1
    mean_luminance = luminance_sum / count
    variance = max(luminance_sq_sum / count - mean_luminance * mean_luminance, 0.0)
    return {
        "mean_rgb": [value / count for value in sums],
        "mean_luminance": mean_luminance,
        "std_luminance": math.sqrt(variance),
        "overexposed_fraction": overexposed_count / count,
        "underexposed_fraction": underexposed_count / count,
    }


def image_pair_visual_delta(left_path: Path, right_path: Path) -> dict[str, Any]:
    with Image.open(left_path).convert("RGB") as left_image:
        with Image.open(right_path).convert("RGB") as right_image:
            if left_image.size != right_image.size:
                right_image = right_image.resize(left_image.size, Image.Resampling.BILINEAR)
            left_pixels = list(left_image.getdata())
            right_pixels = list(right_image.getdata())
    count = max(len(left_pixels), 1)
    absolute_sum = 0.0
    rms_sum = 0.0
    max_delta = 0.0
    for left, right in zip(left_pixels, right_pixels, strict=True):
        channel_deltas = [abs(float(left[index]) - float(right[index])) for index in range(3)]
        pixel_delta = sum(channel_deltas) / 3.0
        absolute_sum += pixel_delta
        rms_sum += sum(delta * delta for delta in channel_deltas) / 3.0
        max_delta = max(max_delta, max(channel_deltas))
    return {
        "mean_absolute_pixel_delta": absolute_sum / count,
        "rms_pixel_delta": math.sqrt(rms_sum / count),
        "max_channel_delta": max_delta,
    }
