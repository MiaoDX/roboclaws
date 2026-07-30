"""Compose Isaac runtime, rendering, scene, and segmentation evidence."""

from __future__ import annotations

from roboclaws.backends.isaaclab.runtime_dependencies import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ISAAC_SEGMENTATION_DATA_TYPES,
    ISAAC_SEMANTIC_POSE_PROVENANCE,
    MAX_SEGMENTATION_CANDIDATES,
    REAL_SMOKE_CAPTURE_METHOD,
    REAL_SMOKE_RENDERER_MODE,
    Any,
    isaac_capture_quality,
    isaac_mapping_diagnostics,
    isaac_render_diagnostics,
    isaac_runtime_diagnostics,
    isaac_segmentation_diagnostics,
)


def runtime_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return isaac_runtime_diagnostics.runtime_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
        primitive_provenance=ISAAC_SEMANTIC_POSE_PROVENANCE,
        real_smoke_renderer_mode=REAL_SMOKE_RENDERER_MODE,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
    )


def rendering_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return isaac_runtime_diagnostics.rendering_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        real_smoke_renderer_mode=REAL_SMOKE_RENDERER_MODE,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
    )


def _isaac_native_render_diagnostics(
    *,
    renderer_mode: str,
    capture_method: str,
    view_kind: str,
    render_resolution: dict[str, Any],
    camera_prim_paths: list[str],
    render_product_paths: list[str] | None = None,
    isaac_lab_isp_active: bool = False,
    capture_quality_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return isaac_render_diagnostics.native_render_diagnostics(
        renderer_mode=renderer_mode,
        capture_method=capture_method,
        view_kind=view_kind,
        render_resolution=render_resolution,
        camera_prim_paths=camera_prim_paths,
        settings=_isaac_settings_interface(),
        render_product_paths=render_product_paths,
        isaac_lab_isp_active=isaac_lab_isp_active,
        capture_quality_settings=capture_quality_settings,
    )


def _apply_isaac_capture_quality_overrides(
    *,
    settings: Any | None,
    isaac_aa_op: int | None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:

    return isaac_capture_quality.apply_isaac_capture_quality_overrides(
        settings=settings,
        setting_paths=isaac_render_diagnostics.ISAAC_NATIVE_RENDER_SETTING_PATHS,
        capture_quality_fields=isaac_render_diagnostics.ISAAC_CAPTURE_QUALITY_SETTING_FIELDS,
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    )


def _isaac_settings_interface() -> Any | None:

    try:
        import carb.settings  # type: ignore[import-untyped]

        return carb.settings.get_settings()
    except Exception:
        return None


def scene_load_diagnostics(
    runtime_mode: str,
    scene_source: str,
    scene_index: int,
    *,
    real_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return isaac_mapping_diagnostics.scene_load_diagnostics(
        runtime_mode,
        scene_source,
        scene_index,
        real_smoke=real_smoke,
    )


def segmentation_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
    scene_binding_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:

    return isaac_segmentation_diagnostics.segmentation_diagnostics(
        runtime_mode,
        real_smoke=real_smoke,
        scene_binding_diagnostics=scene_binding_diagnostics,
        requested_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
        max_candidates=MAX_SEGMENTATION_CANDIDATES,
    )
