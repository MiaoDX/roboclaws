from __future__ import annotations

import math
from typing import Any

from roboclaws.household import scene_camera_diagnostic_values as values
from roboclaws.household.camera_control import scene_light_rig, scene_light_rig_roles
from roboclaws.household.scene_camera_render_diagnostics import (
    float_list,
    normalized_vec3,
)

MOLMOSPACES_LANE_ID = "molmospaces-mujoco"
ISAAC_LANE_ID = "isaaclab-prepared-usd"


def native_isaac_render_diagnostics(manifest: dict[str, Any]) -> dict[str, Any]:
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), dict) else {}
    lane = lanes.get(ISAAC_LANE_ID) if isinstance(lanes.get(ISAAC_LANE_ID), dict) else {}
    diagnostics = (
        lane.get("native_render_diagnostics")
        if isinstance(lane.get("native_render_diagnostics"), dict)
        else {}
    )
    if not diagnostics:
        return {
            "schema": "scene_camera_native_isaac_render_diagnostics_v1",
            "status": "missing_native_diagnostics",
            "settings_api_available": None,
            "native_settings_recorded": False,
            "default_render_settings_changed": None,
            "post_render_comparison_profile": {
                "applied": False,
                "source": "not_a_native_renderer_setting",
            },
            "recommended_next_action": (
                "Run scene-camera capture against an Isaac worker that returns native "
                "RTX/camera diagnostics before tuning brightness or exposure."
            ),
        }
    settings_api_available = diagnostics.get("settings_api_available")
    if settings_api_available is True:
        status = "native_settings_recorded"
        next_action = (
            "Native Isaac settings are recorded for scene-camera capture. Use held-out "
            "FPV and scene-camera comparisons before changing exposure or tone defaults."
        )
    elif diagnostics.get("status") == "fake_protocol":
        status = "fake_protocol_schema_present"
        next_action = (
            "CI fake mode proves the schema only; run local Isaac scene-camera capture "
            "to read native RTX/camera settings."
        )
    else:
        status = "native_settings_api_unavailable"
        next_action = (
            "Scene-camera capture did not read Kit settings. Confirm carb.settings is "
            "available before promoting a native exposure or tone preset."
        )
    return {
        "schema": "scene_camera_native_isaac_render_diagnostics_v1",
        "status": status,
        "native_settings_recorded": status == "native_settings_recorded",
        "source_schema": diagnostics.get("schema"),
        "source_status": diagnostics.get("status"),
        "renderer_mode": diagnostics.get("renderer_mode"),
        "capture_method": diagnostics.get("capture_method"),
        "view_kind": diagnostics.get("view_kind"),
        "settings_api_available": settings_api_available,
        "available_setting_count": diagnostics.get("available_setting_count"),
        "missing_setting_count": diagnostics.get("missing_setting_count"),
        "camera_prim_paths": diagnostics.get("camera_prim_paths") or [],
        "render_product_paths": diagnostics.get("render_product_paths") or [],
        "render_resolution": diagnostics.get("render_resolution") or {},
        "isaac_lab_isp_active": diagnostics.get("isaac_lab_isp_active"),
        "default_render_settings_changed": diagnostics.get("default_render_settings_changed"),
        "post_render_comparison_profile": diagnostics.get("post_render_comparison_profile")
        or {
            "applied": False,
            "source": "not_a_native_renderer_setting",
        },
        "tone_mapping": native_setting_group_summary(
            diagnostics.get("tone_mapping")
            if isinstance(diagnostics.get("tone_mapping"), dict)
            else {}
        ),
        "camera_exposure": native_setting_group_summary(
            diagnostics.get("camera_exposure")
            if isinstance(diagnostics.get("camera_exposure"), dict)
            else {}
        ),
        "ocio": native_setting_group_summary(
            diagnostics.get("ocio") if isinstance(diagnostics.get("ocio"), dict) else {}
        ),
        "color_correction": native_setting_group_summary(
            diagnostics.get("color_correction")
            if isinstance(diagnostics.get("color_correction"), dict)
            else {}
        ),
        "color_grading": native_setting_group_summary(
            diagnostics.get("color_grading")
            if isinstance(diagnostics.get("color_grading"), dict)
            else {}
        ),
        "renderer": native_setting_group_summary(
            diagnostics.get("renderer") if isinstance(diagnostics.get("renderer"), dict) else {}
        ),
        "interpretation": (
            "These rows are native Isaac/RTX and camera diagnostics returned by the "
            "Isaac scene-camera capture path. They are separate from report-side "
            "color-profile replay or RGB/view-gain comparison controls."
        ),
        "recommended_next_action": next_action,
    }


def native_setting_group_summary(group: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, raw in group.items():
        row = raw if isinstance(raw, dict) else {}
        summary[str(key)] = {
            "status": row.get("status"),
            "value": row.get("value"),
            "setting_path": row.get("setting_path"),
        }
    return summary


def lighting_tone_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), dict) else {}
    rows = []
    missing_environment_light = []
    tone_adjusted_lanes = []
    for lane_id, lane in lanes.items():
        if not isinstance(lane, dict):
            continue
        row = lane_lighting_tone_provenance(str(lane_id), lane, manifest=manifest)
        rows.append(row)
        if row["environment_light_status"] == "missing_environment_light":
            missing_environment_light.append(str(lane_id))
        if row["tone_adjustment_status"] == "post_render_tone_adjustment_applied":
            tone_adjusted_lanes.append(str(lane_id))
    if missing_environment_light:
        status = "missing_environment_light"
        next_action = (
            "Fix the backend lighting configuration before tuning exposure, gain, or material "
            "response."
        )
    elif tone_adjusted_lanes:
        status = "environment_light_configured_tone_adjusted"
        next_action = (
            "Lighting is configured for all successful lanes. Treat remaining Isaac visual "
            "differences as tone, exposure, material, or renderer-response residuals."
        )
    else:
        status = "environment_light_configured"
        next_action = (
            "Lighting is configured; inspect render-domain residual diagnostics before changing "
            "lighting defaults."
        )
    return {
        "schema": "scene_camera_lighting_tone_provenance_v1",
        "status": status,
        "missing_environment_light_lanes": missing_environment_light,
        "tone_adjusted_lanes": tone_adjusted_lanes,
        "lane_count": len(rows),
        "interpretation": (
            "This normalizes backend-specific light and color-management diagnostics. It "
            "separates configured environment/fill lighting from post-render tone, exposure, "
            "and material-response residuals."
        ),
        "recommended_next_action": next_action,
        "lanes": rows,
    }


def shadow_parity_probe(manifest: dict[str, Any]) -> dict[str, Any]:
    camera = (
        manifest.get("camera_control") if isinstance(manifest.get("camera_control"), dict) else {}
    )
    lighting = (
        camera.get("lighting_profile") if isinstance(camera.get("lighting_profile"), dict) else {}
    )
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), dict) else {}
    isaac = lanes.get(ISAAC_LANE_ID) if isinstance(lanes.get(ISAAC_LANE_ID), dict) else {}
    isaac_lighting = (
        isaac.get("lighting_diagnostics")
        if isinstance(isaac.get("lighting_diagnostics"), dict)
        else {}
    )
    render_probe = (
        manifest.get("render_domain_contract_probe")
        if isinstance(manifest.get("render_domain_contract_probe"), dict)
        else {}
    )
    candidate_visual = (
        manifest.get("candidate_visual_diagnostics")
        if isinstance(manifest.get("candidate_visual_diagnostics"), dict)
        else {}
    )
    candidate_warning_reasons = sorted(
        {
            str(reason)
            for candidate in (
                candidate_visual.get("candidates")
                if isinstance(candidate_visual.get("candidates"), list)
                else []
            )
            if isinstance(candidate, dict)
            for reason in (
                candidate.get("warning_reasons")
                if isinstance(candidate.get("warning_reasons"), list)
                else []
            )
        }
    )
    rig = lighting_rig(lighting)
    rig_roles = scene_light_rig_roles(rig)
    ambient = rig_ambient(lighting)
    isaac_override = rig_backend_override(lighting, "isaac")
    key_light_direction = key_light_direction_diagnostics(
        lighting_profile=lighting,
        render_probe=render_probe,
        isaac_lighting=isaac_lighting,
    )
    isaac_dome_intensity = values.optional_float(
        isaac_lighting.get("requested_dome_intensity", ambient.get("isaac_dome_intensity"))
    )
    isaac_key_intensity = values.optional_float(
        isaac_lighting.get("requested_key_intensity", isaac_override.get("key_intensity"))
    )
    shadow_disabled_count = (
        values.optional_int(render_probe.get("isaac_shadow_disabled_prim_count")) or 0
    )
    profile_id = str(lighting.get("profile_id") or "")
    is_shadow_probe = profile_id == "scene_probe_shadow_parity_probe_v1"
    is_shadow_capable_profile = is_shadow_probe
    isaac_probe_ready = (
        isaac_dome_intensity is not None
        and isaac_dome_intensity <= 20.0
        and isaac_key_intensity is not None
        and isaac_key_intensity > 0.0
    )
    isaac_lighting_ready = (
        isaac_dome_intensity is not None
        and isaac_dome_intensity > 0.0
        and isaac_key_intensity is not None
        and isaac_key_intensity >= 0.0
    )
    comparison_passed = comparison_successful(manifest)
    if is_shadow_probe and isaac_probe_ready:
        status = "shadow_parity_probe_configured"
        if comparison_passed:
            next_action = (
                "Review bed/object views for cast-shadow return, then check room views remain "
                "bright enough before promoting any default."
            )
        else:
            next_action = (
                "Shadow lighting is configured, but the visual comparison gate did not pass. "
                "Treat this as probe evidence only; do not promote it as the default."
            )
    elif is_shadow_probe:
        status = "shadow_parity_probe_partially_configured"
        next_action = (
            "Inspect per-lane lighting diagnostics before trusting visual shadow evidence."
        )
    elif is_shadow_capable_profile and isaac_lighting_ready:
        if comparison_passed:
            status = "shadow_capable_profile_accepted"
            next_action = (
                "Lighting profile is shadow-capable and passes the visual comparison gate; "
                "review contact sheets before treating it as the default."
            )
        else:
            status = "shadow_capable_profile_visual_gate_failed"
            next_action = (
                "Lighting profile is shadow-capable, but the visual comparison gate did not "
                "pass. Keep it opt-in until candidate diagnostics improve."
            )
    else:
        status = "default_fill_profile_not_shadow_parity"
        next_action = (
            "Run with lighting_profile=shadow-parity to test MuJoCo-like cast shadows without "
            "changing the default fill profile."
        )
    return {
        "schema": "scene_camera_shadow_parity_probe_v1",
        "status": status,
        "profile_id": profile_id,
        "scene_light_rig_schema": rig.get("schema"),
        "scene_light_rig_roles": rig_roles,
        "is_shadow_parity_profile": is_shadow_probe,
        "is_shadow_capable_profile": is_shadow_capable_profile,
        "isaac_dome_intensity": isaac_dome_intensity,
        "isaac_key_intensity": isaac_key_intensity,
        "isaac_existing_light_intensity_scale": isaac_lighting.get(
            "existing_light_intensity_scale"
        ),
        "isaac_existing_light_intensity_adjustments": isaac_lighting.get(
            "existing_light_intensity_adjustments"
        )
        or [],
        "isaac_added_light_paths": isaac_lighting.get("added_light_paths") or [],
        "isaac_shadow_disabled_prim_count": shadow_disabled_count,
        "mujoco_light_count": render_probe.get("mujoco_light_count"),
        "isaac_light_count": render_probe.get("isaac_light_count"),
        "key_light_direction": key_light_direction,
        "comparison_successful": comparison_passed,
        "candidate_visual_status": candidate_visual.get("status"),
        "candidate_visual_degraded_candidates": candidate_visual.get("degraded_candidates") or [],
        "candidate_visual_warning_reasons": candidate_warning_reasons,
        "render_contract_high_priority_delta_count": render_probe.get("high_priority_delta_count"),
        "interpretation": (
            "This probe tracks whether the run is configured to test MuJoCo-like cast shadows. "
            "It is configuration and report evidence; visual acceptance still requires "
            "reviewing the bed view and room views."
        ),
        "recommended_next_action": next_action,
    }


def lane_lighting_tone_provenance(
    lane_id: str,
    lane: dict[str, Any],
    *,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    lighting_profile = (
        lane.get("lighting_profile") if isinstance(lane.get("lighting_profile"), dict) else {}
    )
    lighting_diagnostics = (
        lane.get("lighting_diagnostics")
        if isinstance(lane.get("lighting_diagnostics"), dict)
        else {}
    )
    color_profile = lane.get("color_profile") if isinstance(lane.get("color_profile"), dict) else {}
    native = (
        lane.get("native_render_diagnostics")
        if isinstance(lane.get("native_render_diagnostics"), dict)
        else {}
    )
    if lane_id == ISAAC_LANE_ID:
        lighting_summary = isaac_lighting_summary(lighting_diagnostics, lighting_profile)
    elif lane_id == MOLMOSPACES_LANE_ID:
        lighting_summary = mujoco_lighting_summary(manifest, lighting_profile)
    else:
        lighting_summary = generic_lighting_summary(lighting_diagnostics, lighting_profile)
    color_summary = color_tone_summary(lane_id, color_profile, native)
    return {
        "lane_id": lane_id,
        "environment_light_status": lighting_summary["status"],
        "environment_light_summary": lighting_summary["summary"],
        "environment_light_source": lighting_summary.get("source") or "",
        "tone_adjustment_status": color_summary["status"],
        "tone_adjustment_summary": color_summary["summary"],
        "tone_adjustment_source": color_summary.get("source") or "",
        "native_render_summary": native_render_summary(native),
    }


def isaac_lighting_summary(
    diagnostics: dict[str, Any],
    lighting_profile: dict[str, Any],
) -> dict[str, str]:
    rig = lighting_rig(lighting_profile)
    roles = scene_light_rig_roles(rig)
    existing = values.optional_int(diagnostics.get("existing_light_count"))
    added = values.optional_int(diagnostics.get("added_light_count"))
    existing_scale = values.optional_float(diagnostics.get("existing_light_intensity_scale"))
    dome_intensity = diagnostics.get("requested_dome_intensity")
    if dome_intensity is None:
        dome_intensity = rig_ambient(lighting_profile).get("isaac_dome_intensity")
    key_intensity = diagnostics.get("requested_key_intensity")
    if key_intensity is None:
        key_intensity = rig_backend_override(lighting_profile, "isaac").get("key_intensity")
    existing_count = existing or 0
    added_count = added or 0
    active_existing_count = existing_count if existing_scale is None or existing_scale > 0.0 else 0
    active_capture_roles = []
    if values.positive_number(dome_intensity):
        active_capture_roles.append("dome_environment")
    if values.positive_number(key_intensity):
        active_capture_roles.append("directional_key")
    active_roles_text = values.cell_text(active_capture_roles)
    has_environment = active_existing_count + added_count > 0 or values.positive_number(
        dome_intensity
    )
    status = "environment_light_configured" if has_environment else "missing_environment_light"
    summary = (
        f"{diagnostics.get('status') or 'isaac_lighting_profile'}; "
        f"rig={roles.get('schema')}; key={roles.get('key_enabled')}; "
        f"ambient={roles.get('ambient_enabled')}; fill={roles.get('fill_enabled')}; "
        f"authored={roles.get('authored_scene_lights_policy')}; "
        f"authored_usd_lights={existing_count}; "
        f"active_authored_usd_lights={active_existing_count}; "
        f"added_capture_lights={added_count}; active_roles={active_roles_text}; "
        f"dome_intensity={values.float_text(dome_intensity)}; "
        f"key_intensity={values.float_text(key_intensity)}; "
        f"existing_scale={values.float_text(existing_scale)}; "
        f"added_paths={values.cell_text(diagnostics.get('added_light_paths'))}"
    )
    return {
        "status": status,
        "summary": summary,
        "source": str(diagnostics.get("profile_source") or lighting_profile.get("source") or ""),
    }


def mujoco_lighting_summary(
    manifest: dict[str, Any],
    lighting_profile: dict[str, Any],
) -> dict[str, str]:
    rig = lighting_rig(lighting_profile)
    roles = scene_light_rig_roles(rig)
    probe = (
        manifest.get("render_domain_contract_probe")
        if isinstance(manifest.get("render_domain_contract_probe"), dict)
        else {}
    )
    light_count = values.optional_int(probe.get("mujoco_light_count"))
    ambient = rig_ambient(lighting_profile).get("mujoco_headlight_ambient")
    diffuse = rig_ambient(lighting_profile).get("mujoco_headlight_diffuse")
    has_environment = bool(ambient or diffuse or (light_count or 0) > 0)
    status = "environment_light_configured" if has_environment else "missing_environment_light"
    scene_lights = light_count if light_count is not None else ""
    summary = (
        f"scene_light_rig; rig={roles.get('schema')}; key={roles.get('key_enabled')}; "
        f"ambient={roles.get('ambient_enabled')}; fill={roles.get('fill_enabled')}; "
        f"authored={roles.get('authored_scene_lights_policy')}; "
        f"headlight_ambient={values.cell_text(ambient)}; "
        f"diffuse={values.cell_text(diffuse)}; scene_lights={scene_lights}"
    )
    return {
        "status": status,
        "summary": summary,
        "source": str(lighting_profile.get("source") or ""),
    }


def generic_lighting_summary(
    diagnostics: dict[str, Any],
    lighting_profile: dict[str, Any],
) -> dict[str, str]:
    status = str(diagnostics.get("status") or "")
    profile_id = str(lighting_profile.get("profile_id") or diagnostics.get("profile_id") or "")
    return {
        "status": "environment_light_configured" if status or profile_id else "unknown",
        "summary": f"{status}; profile={profile_id}".strip("; "),
        "source": str(lighting_profile.get("source") or diagnostics.get("profile_source") or ""),
    }


def lighting_rig(lighting_profile: dict[str, Any]) -> dict[str, Any]:
    return scene_light_rig(lighting_profile)


def rig_key(lighting_profile: dict[str, Any]) -> dict[str, Any]:
    rig = lighting_rig(lighting_profile)
    return rig.get("key") if isinstance(rig.get("key"), dict) else {}


def rig_ambient(lighting_profile: dict[str, Any]) -> dict[str, Any]:
    rig = lighting_rig(lighting_profile)
    return rig.get("ambient") if isinstance(rig.get("ambient"), dict) else {}


def rig_backend_override(lighting_profile: dict[str, Any], backend: str) -> dict[str, Any]:
    rig = lighting_rig(lighting_profile)
    overrides = (
        rig.get("backend_overrides") if isinstance(rig.get("backend_overrides"), dict) else {}
    )
    return overrides.get(backend) if isinstance(overrides.get(backend), dict) else {}


def color_tone_summary(
    lane_id: str,
    color_profile: dict[str, Any],
    native_diagnostics: dict[str, Any],
) -> dict[str, str]:
    gains = (
        color_profile.get("backend_luminance_gain")
        if isinstance(color_profile.get("backend_luminance_gain"), dict)
        else {}
    )
    rgb_gains = (
        color_profile.get("backend_rgb_gain")
        if isinstance(color_profile.get("backend_rgb_gain"), dict)
        else {}
    )
    tone_adjustments = (
        color_profile.get("backend_tone_adjustment")
        if isinstance(color_profile.get("backend_tone_adjustment"), dict)
        else {}
    )
    view_tone_adjustments = (
        color_profile.get("backend_view_tone_adjustment")
        if isinstance(color_profile.get("backend_view_tone_adjustment"), dict)
        else {}
    )
    gain = gains.get(lane_id)
    rgb_gain = rgb_gains.get(lane_id)
    tone = tone_adjustments.get(lane_id)
    view_tone = view_tone_adjustments.get(lane_id)
    view_tone_count = len(view_tone) if isinstance(view_tone, dict) else 0
    has_post_tone = tone is not None or view_tone_count > 0 or rgb_gain is not None
    has_gain = gain is not None
    if has_post_tone:
        status = "post_render_tone_adjustment_applied"
    elif values.non_unity_gain(gain):
        status = "post_render_luminance_gain_applied"
    elif has_gain:
        status = "baseline_color_profile_reference"
    else:
        status = "no_backend_tone_adjustment"
    summary = (
        f"profile={color_profile.get('profile_id') or ''}; "
        f"luminance_gain={values.float_text(gain)}; rgb_gain={values.cell_text(rgb_gain)}; "
        f"tone={values.cell_text(tone)}; view_tone_overrides={view_tone_count}"
    )
    native_summary = native_render_summary(native_diagnostics)
    if native_summary:
        summary = f"{summary}; native={native_summary}"
    return {
        "status": status,
        "summary": summary,
        "source": tone_source_text(lane_id, color_profile),
    }


def tone_source_text(lane_id: str, color_profile: dict[str, Any]) -> str:
    backend_prefix = backend_source_prefix(lane_id)
    lane_specific_sources = unique_source_values(
        color_profile,
        (
            f"{backend_prefix}_backend_tone_adjustment_source",
            f"{backend_prefix}_backend_luminance_gain_source",
            f"{backend_prefix}_backend_rgb_gain_source",
        ),
    )
    if lane_specific_sources:
        return "; ".join(lane_specific_sources)
    return "; ".join(
        unique_source_values(
            color_profile,
            (
                "backend_tone_adjustment_source",
                "backend_view_tone_adjustment_source",
                "backend_luminance_gain_source",
                "backend_rgb_gain_source",
            ),
        )
    )


def unique_source_values(color_profile: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    sources = []
    for key in keys:
        value = str(color_profile.get(key) or "")
        if value and value not in sources:
            sources.append(value)
    return sources


def backend_source_prefix(lane_id: str) -> str:
    if lane_id == ISAAC_LANE_ID:
        return "isaac"
    if lane_id == MOLMOSPACES_LANE_ID:
        return "mujoco"
    return lane_id.split("-", 1)[0].replace("-", "_")


def native_render_summary(diagnostics: dict[str, Any]) -> str:
    if not diagnostics:
        return ""
    tone_mapping = (
        diagnostics.get("tone_mapping") if isinstance(diagnostics.get("tone_mapping"), dict) else {}
    )
    exposure = (
        diagnostics.get("camera_exposure")
        if isinstance(diagnostics.get("camera_exposure"), dict)
        else {}
    )
    tonemap_operator = native_setting_value(tone_mapping.get("operator"))
    exposure_bias = native_setting_value(tone_mapping.get("exposure_bias"))
    auto_exposure = native_setting_value(exposure.get("auto_exposure_enabled"))
    parts = [
        f"status={diagnostics.get('status') or ''}",
        f"tonemap_operator={tonemap_operator}",
        f"exposure_bias={values.cell_text(exposure_bias)}",
        f"auto_exposure={auto_exposure}",
    ]
    return "; ".join(part for part in parts if not part.endswith("="))


def native_setting_value(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) else None


def light_intensity_text(lights: Any) -> str:
    if not isinstance(lights, list):
        return ""
    intensities = []
    for item in lights:
        if isinstance(item, dict) and item.get("intensity") is not None:
            intensities.append(item.get("intensity"))
    return values.cell_text(intensities)


def angle_deg_between(left: Any, right: Any) -> float | None:
    left_vec = normalized_vec3(left)
    right_vec = normalized_vec3(right)
    if left_vec is None or right_vec is None:
        return None
    dot = sum(left_item * right_item for left_item, right_item in zip(left_vec, right_vec))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def primary_mujoco_key_light_direction(render_probe: dict[str, Any]) -> list[float] | None:
    lights = (
        render_probe.get("mujoco_lights")
        if isinstance(render_probe.get("mujoco_lights"), list)
        else []
    )
    for light in lights:
        if not isinstance(light, dict):
            continue
        direction = normalized_vec3(light.get("dir_vector") or float_list(light.get("dir")))
        if direction is not None:
            return direction
    return None


def key_light_direction_diagnostics(
    *,
    lighting_profile: dict[str, Any],
    render_probe: dict[str, Any],
    isaac_lighting: dict[str, Any],
) -> dict[str, Any]:
    rig = lighting_rig(lighting_profile)
    key = rig_key(lighting_profile)
    canonical = normalized_vec3(key.get("direction"))
    mujoco = primary_mujoco_key_light_direction(render_probe)
    isaac = normalized_vec3(isaac_lighting.get("applied_key_light_direction"))
    isaac_angle = angle_deg_between(mujoco, isaac)
    threshold = 15.0
    status = (
        "key_light_direction_aligned"
        if mujoco is not None
        and isaac is not None
        and isaac_angle is not None
        and isaac_angle <= threshold
        else "key_light_direction_delta"
    )
    return {
        "schema": "scene_camera_key_light_direction_diagnostics_v1",
        "status": status,
        "threshold_deg": threshold,
        "scene_key_light_frame": rig.get("frame"),
        "canonical_scene_key_light_direction": canonical,
        "mujoco_key_light_direction": mujoco,
        "isaac_key_light_direction": isaac,
        "isaac_angle_delta_deg": isaac_angle,
    }


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
