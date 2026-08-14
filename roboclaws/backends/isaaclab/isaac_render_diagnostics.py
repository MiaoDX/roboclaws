"""Isaac Lab backend runtime support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab.isaac_capture_quality import (
    json_safe_setting_value,
)

ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA = "isaac_native_render_diagnostics_v1"

ISAAC_NATIVE_RENDER_SETTING_PATHS = {
    "tone_mapping": {
        "operator": (
            "/rtx/post/tonemap/op",
            "/rtx/post/tonemap/operator",
            "/rtx/post/tonemap/tonemapOp",
        ),
        "exposure_bias": (
            "/rtx/post/tonemap/exposure",
            "/rtx/post/tonemap/exposureBias",
        ),
        "exposure_value": (
            "/rtx/post/tonemap/cameraExposure",
            "/rtx/post/camera/exposure",
            "/rtx/post/camera/exposureValue",
        ),
        "white_point": (
            "/rtx/post/tonemap/whitepoint",
            "/rtx/post/tonemap/whitePoint",
        ),
        "cm2_factor": ("/rtx/post/tonemap/cm2Factor",),
        "max_white_luminance": ("/rtx/post/tonemap/maxWhiteLuminance",),
    },
    "camera_exposure": {
        "auto_exposure_enabled": (
            "/rtx/post/histogram/autoExposure/enabled",
            "/rtx/post/tonemap/autoExposure",
            "/rtx/post/tonemap/autoExposure/enabled",
        ),
        "auto_exposure_min": (
            "/rtx/post/histogram/autoExposure/min",
            "/rtx/post/tonemap/autoExposure/min",
        ),
        "auto_exposure_max": (
            "/rtx/post/histogram/autoExposure/max",
            "/rtx/post/tonemap/autoExposure/max",
        ),
        "iso": (
            "/rtx/post/camera/iso",
            "/rtx/post/tonemap/filmIso",
        ),
        "f_stop": (
            "/rtx/post/camera/fStop",
            "/rtx/post/tonemap/fNumber",
        ),
        "shutter_speed": (
            "/rtx/post/camera/shutterSpeed",
            "/rtx/post/tonemap/cameraShutter",
        ),
    },
    "ocio": {
        "enabled": (
            "/rtx/post/ocio/enabled",
            "/app/renderer/colorManagement/ocio/enabled",
        ),
        "config": (
            "/rtx/post/ocio/config",
            "/app/renderer/colorManagement/ocio/config",
        ),
        "display": (
            "/rtx/post/ocio/display",
            "/app/renderer/colorManagement/ocio/display",
        ),
        "view": (
            "/rtx/post/ocio/view",
            "/app/renderer/colorManagement/ocio/view",
        ),
        "look": (
            "/rtx/post/ocio/look",
            "/app/renderer/colorManagement/ocio/look",
        ),
    },
    "color_correction": {
        "enabled": ("/rtx/post/colorcorr/enabled",),
        "mode": ("/rtx/post/colorcorr/mode",),
        "saturation": ("/rtx/post/colorcorr/saturation",),
        "contrast": ("/rtx/post/colorcorr/contrast",),
        "gamma": ("/rtx/post/colorcorr/gamma",),
        "gain": ("/rtx/post/colorcorr/gain",),
        "offset": ("/rtx/post/colorcorr/offset",),
    },
    "color_grading": {
        "enabled": ("/rtx/post/colorGrading/enabled",),
        "lut": (
            "/rtx/post/colorGrading/lut",
            "/rtx/post/colorGrading/lutFile",
        ),
        "amount": ("/rtx/post/colorGrading/amount",),
    },
    "renderer": {
        "renderer": (
            "/renderer/active",
            "/rtx/rendermode",
        ),
        "render_mode": (
            "/rtx/mode",
            "/rtx/renderMode",
        ),
        "anti_aliasing": ("/rtx/post/aa/op",),
    },
}

ISAAC_CAPTURE_QUALITY_SETTING_FIELDS = {
    "samples_per_pixel": (),
    "anti_aliasing": ISAAC_NATIVE_RENDER_SETTING_PATHS["renderer"]["anti_aliasing"],
    "denoise": (),
    "taa": (),
    "texture_filtering": (),
}


def native_render_diagnostics_unavailable(
    *,
    runtime_mode: str,
    reason: str,
) -> dict[str, Any]:
    groups = {
        group: {
            key: {
                "status": "not_available",
                "value": None,
                "setting_path": "",
                "candidate_paths": list(paths),
            }
            for key, paths in fields.items()
        }
        for group, fields in ISAAC_NATIVE_RENDER_SETTING_PATHS.items()
    }
    return {
        "schema": ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA,
        "status": "fake_protocol" if runtime_mode == "fake" else "settings_unavailable",
        "source": "fake_protocol" if runtime_mode == "fake" else "isaac_kit_settings_unavailable",
        "renderer_mode": "fake_isaac_protocol"
        if runtime_mode == "fake"
        else "isaac_runtime_unvalidated",
        "capture_method": "not_attempted",
        "view_kind": "not_captured",
        "settings_api_available": False,
        "available_setting_count": 0,
        "missing_setting_count": native_setting_candidate_count(),
        "groups": groups,
        "tone_mapping": groups["tone_mapping"],
        "camera_exposure": groups["camera_exposure"],
        "ocio": groups["ocio"],
        "color_correction": groups["color_correction"],
        "color_grading": groups["color_grading"],
        "renderer": groups["renderer"],
        "camera_prim_paths": [],
        "render_product_paths": [],
        "render_resolution": {},
        "capture_quality_settings": capture_quality_settings_unavailable(
            render_settle_frames=0,
            reason=reason,
        ),
        "isaac_lab_isp_active": False,
        "settings_mutation_attempted": False,
        "default_render_settings_changed": False,
        "post_render_comparison_profile": {
            "applied": False,
            "source": "not_a_native_renderer_setting",
        },
        "reason": reason,
    }


def native_setting_candidate_count() -> int:
    return sum(
        len(fields)
        for fields in ISAAC_NATIVE_RENDER_SETTING_PATHS.values()
        if isinstance(fields, dict)
    )


def capture_quality_settings_unavailable(
    *,
    render_settle_frames: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema": "isaac_capture_quality_settings_v1",
        "render_settle_frames": max(0, int(render_settle_frames)),
        "samples_per_pixel": {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": [],
        },
        "anti_aliasing": {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": list(ISAAC_CAPTURE_QUALITY_SETTING_FIELDS["anti_aliasing"]),
        },
        "denoise": {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": [],
        },
        "taa": {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": [],
        },
        "texture_filtering": {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": [],
        },
        "settings_mutation_attempted": False,
        "default_render_settings_changed": False,
        "reason": reason,
    }


def capture_quality_settings(
    *,
    render_settle_frames: int,
    settings: Any | None,
    settings_mutation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = {
        key: isaac_setting_value(settings, paths)
        if paths
        else {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": [],
        }
        for key, paths in ISAAC_CAPTURE_QUALITY_SETTING_FIELDS.items()
    }
    mutation = _dict(settings_mutation)
    mutated_rows = _dict(mutation.get("settings"))
    for key, row in mutated_rows.items():
        rows[str(key)] = _dict(row)
    settings_mutation_attempted = bool(mutation.get("settings_mutation_attempted"))
    default_render_settings_changed = bool(mutation.get("default_render_settings_changed"))
    reason = (
        "Capture-quality probe metadata includes explicit opt-in native renderer setting "
        "mutation. The worker records previous values and attempts to restore them after "
        "capture."
        if settings_mutation_attempted
        else (
            "Capture-quality probe metadata is recorded without mutating native renderer "
            "defaults. Unsupported sampling, denoise, TAA, or texture filtering knobs are "
            "reported as not_available."
        )
    )
    return {
        "schema": "isaac_capture_quality_settings_v1",
        "render_settle_frames": max(0, int(render_settle_frames)),
        **rows,
        "settings_mutation_attempted": settings_mutation_attempted,
        "default_render_settings_changed": default_render_settings_changed,
        "settings_mutation": mutation,
        "reason": reason,
    }


def native_render_diagnostics(
    *,
    renderer_mode: str,
    capture_method: str,
    view_kind: str,
    render_resolution: dict[str, Any],
    camera_prim_paths: list[str],
    settings: Any | None,
    render_product_paths: list[str] | None = None,
    isaac_lab_isp_active: bool = False,
    capture_quality_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    available_count = 0
    missing_count = 0
    for group_name, fields in ISAAC_NATIVE_RENDER_SETTING_PATHS.items():
        group: dict[str, Any] = {}
        for field_name, candidate_paths in fields.items():
            row = isaac_setting_value(settings, candidate_paths)
            group[field_name] = row
            if row["status"] == "available":
                available_count += 1
            else:
                missing_count += 1
        groups[group_name] = group
    status = "captured" if settings is not None else "settings_api_unavailable"
    settings_mutation = _dict(
        capture_quality_settings.get("settings_mutation")
        if isinstance(capture_quality_settings, dict)
        else None
    )
    settings_mutation_attempted = bool(
        capture_quality_settings.get("settings_mutation_attempted")
        if isinstance(capture_quality_settings, dict)
        else False
    )
    default_render_settings_changed = bool(
        capture_quality_settings.get("default_render_settings_changed")
        if isinstance(capture_quality_settings, dict)
        else False
    )
    reason = (
        "Native Isaac renderer/camera settings were read from carb.settings. "
        + (
            "An explicit capture-quality probe setting was applied for this capture "
            "and restoration was attempted afterward."
            if settings_mutation_attempted
            else "No renderer defaults were changed by this diagnostics capture."
        )
        if settings is not None
        else (
            "Isaac Kit settings API was not available to this worker; diagnostics "
            "record the requested native axes without changing renderer defaults."
        )
    )
    return {
        "schema": ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA,
        "status": status,
        "source": "carb.settings" if settings is not None else "isaac_kit_settings_unavailable",
        "renderer_mode": renderer_mode,
        "capture_method": capture_method,
        "view_kind": view_kind,
        "settings_api_available": settings is not None,
        "available_setting_count": available_count,
        "missing_setting_count": missing_count,
        "groups": groups,
        "tone_mapping": groups["tone_mapping"],
        "camera_exposure": groups["camera_exposure"],
        "ocio": groups["ocio"],
        "color_correction": groups["color_correction"],
        "color_grading": groups["color_grading"],
        "renderer": groups["renderer"],
        "camera_prim_paths": _dedupe([path for path in camera_prim_paths if path]),
        "render_product_paths": _dedupe(render_product_paths or []),
        "render_resolution": dict(render_resolution),
        "capture_quality_settings": capture_quality_settings
        or capture_quality_settings_fn(
            render_settle_frames=0,
            settings=settings,
        ),
        "isaac_lab_isp_active": bool(isaac_lab_isp_active),
        "settings_mutation_attempted": settings_mutation_attempted,
        "default_render_settings_changed": default_render_settings_changed,
        "settings_mutation": settings_mutation,
        "post_render_comparison_profile": {
            "applied": False,
            "source": "not_a_native_renderer_setting",
        },
        "reason": reason,
    }


def capture_quality_settings_fn(
    *,
    render_settle_frames: int,
    settings: Any | None,
    settings_mutation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return capture_quality_settings(
        render_settle_frames=render_settle_frames,
        settings=settings,
        settings_mutation=settings_mutation,
    )


def isaac_setting_value(settings: Any | None, candidate_paths: tuple[str, ...]) -> dict[str, Any]:
    paths = list(candidate_paths)
    if settings is None:
        return {
            "status": "not_available",
            "value": None,
            "setting_path": "",
            "candidate_paths": paths,
        }
    for path in candidate_paths:
        try:
            value = settings.get(path)
        except Exception:
            continue
        if value is None:
            continue
        return {
            "status": "available",
            "value": json_safe_setting_value(value),
            "setting_path": path,
            "candidate_paths": paths,
        }
    return {
        "status": "not_available",
        "value": None,
        "setting_path": "",
        "candidate_paths": paths,
    }


def camera_render_product_paths(camera: Any) -> list[str]:
    paths: list[str] = []
    for attr_name in (
        "render_product_path",
        "render_product_paths",
        "_render_product_path",
        "_render_product_paths",
    ):
        value = getattr(camera, attr_name, None)
        paths.extend(render_product_paths_from_value(value))
    data = getattr(camera, "data", None)
    if data is not None:
        for attr_name in ("render_product_path", "render_product_paths"):
            paths.extend(render_product_paths_from_value(getattr(data, attr_name, None)))
    return _dedupe(paths)


def render_product_paths_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Path):
        return [str(value)]
    if isinstance(value, dict):
        return [str(item) for item in value.values() if isinstance(item, (str, Path)) and str(item)]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if isinstance(item, (str, Path)) and str(item)]
    return []


def _dedupe(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
