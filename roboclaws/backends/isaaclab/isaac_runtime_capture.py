"""Isaac Lab backend runtime support."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IsaacRuntimeCaptureHooks:
    capture_isaac_lab_camera_views: Callable[..., dict[str, Any]]
    dict_value: Callable[..., dict[str, Any]]
    generated_scene_filename: Callable[..., str]
    inspect_usd_scene_index: Callable[..., dict[str, Any]]
    isaac_app_launcher_args: Callable[..., Any]
    module_version: Callable[..., str | None]
    rby1m_robot_import_plan: Callable[..., dict[str, Any]]
    require_isaac_import: Callable[[], None]
    runtime_smoke_robot_view_paths: Callable[..., dict[str, Path]]
    scene_usd_path: Callable[..., str]
    set_deferred_simulation_app: Callable[[Any], None]
    write_generated_runtime_smoke_usd: Callable[..., int]


def real_runtime_smoke(
    args: Any,
    scenario: Any,
    *,
    hooks: IsaacRuntimeCaptureHooks,
    default_width: int,
    default_height: int,
    robot_view_keys: tuple[str, ...],
    segmentation_data_types: tuple[str, ...],
    real_smoke_renderer_mode: str,
    real_smoke_capture_method: str,
    real_robot_view_capture_method: str,
) -> dict[str, Any]:
    """Launch Isaac Lab and capture the minimal renderer/USD proof.

    This function intentionally stays behind the worker subprocess. Normal
    Roboclaws imports must not import Isaac packages or start Omniverse.
    """

    hooks.require_isaac_import()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    smoke_image = args.run_dir / "isaac_runtime_smoke.png"
    robot_view_paths = hooks.runtime_smoke_robot_view_paths(
        args.run_dir,
        smoke_image=smoke_image,
    )
    if args.scene_usd_path is not None:
        scene_usd = args.scene_usd_path
        if not scene_usd.is_file():
            raise RuntimeError(f"local Isaac scene USD is missing: {scene_usd}")
        loaded_asset_kind = "local_scene_usd"
    else:
        scene_usd = args.run_dir / hooks.generated_scene_filename(args.generated_scene_kind)
        loaded_asset_kind = "generated_runtime_smoke_usd"
    robot_import = hooks.rby1m_robot_import_plan(args.robot_name) if args.include_robot else {}

    from isaaclab.app import AppLauncher

    launcher_args = hooks.isaac_app_launcher_args(AppLauncher)
    app_launcher = AppLauncher(launcher_args)
    simulation_app = app_launcher.app
    hooks.set_deferred_simulation_app(simulation_app)

    # Isaac Sim requires that Omniverse/pxr modules are not imported before
    # SimulationApp starts. Generate and inspect USD only after AppLauncher
    # owns the Kit bootstrap.
    if args.scene_usd_path is None:
        hooks.write_generated_runtime_smoke_usd(
            scene_usd,
            scenario,
            scene_kind=args.generated_scene_kind,
        )
    scene_index_diagnostics = hooks.inspect_usd_scene_index(scene_usd)
    stage_prim_count = int(scene_index_diagnostics["stage_prim_count"])

    capture = hooks.capture_isaac_lab_camera_views(
        scene_usd=scene_usd,
        view_paths=robot_view_paths,
        width=default_width,
        height=default_height,
        simulation_app=simulation_app,
        robot_import=robot_import,
        include_segmentation=args.enable_segmentation,
        segmentation_data_types=tuple(args.segmentation_data_type or segmentation_data_types),
        semantic_filter=tuple(args.segmentation_semantic_filter or ("class",)),
        scene_index_diagnostics=scene_index_diagnostics,
    )
    robot_view_images = dict(capture["robot_view_images"])
    segmentation = hooks.dict_value(capture.get("segmentation"))

    _validate_runtime_smoke_artifacts(
        smoke_image=smoke_image,
        scene_index_diagnostics=scene_index_diagnostics,
        robot_view_images=robot_view_images,
        robot_view_keys=robot_view_keys,
    )
    return {
        "image_path": str(smoke_image),
        "scene_usd": str(scene_usd),
        "loaded_asset_kind": loaded_asset_kind,
        "generated_scene_kind": args.generated_scene_kind if args.scene_usd_path is None else "",
        "requested_scene_source": args.scene_source,
        "requested_scene_index": args.scene_index,
        "requested_molmospaces_scene_usd": hooks.scene_usd_path(
            args.scene_source,
            args.scene_index,
        ),
        "isaac_lab_version": hooks.module_version("isaaclab"),
        "isaac_sim_version": hooks.module_version("isaacsim"),
        "renderer_mode": real_smoke_renderer_mode,
        "capture_method": real_smoke_capture_method,
        "robot_view_capture_method": real_robot_view_capture_method,
        "robot_view_images": robot_view_images,
        "robot_import": robot_import,
        "robot_view_uses_mounted_head_camera": bool(
            capture.get("robot_view_uses_mounted_head_camera")
        ),
        "camera_resolution": [default_width, default_height],
        "scene_bounds": capture.get("scene_bounds"),
        "stage_prim_count": stage_prim_count,
        "render_steps": int(capture["render_steps"]),
        "scene_index_diagnostics": scene_index_diagnostics,
        "object_index": scene_index_diagnostics["object_index"],
        "receptacle_index": scene_index_diagnostics["receptacle_index"],
        "segmentation": segmentation,
        "native_render_diagnostics": hooks.dict_value(capture.get("native_render_diagnostics")),
    }


def capture_semantic_pose_robot_views(
    *,
    state: dict[str, Any],
    scene_usd: Path,
    view_paths: dict[str, Path],
    width: int,
    height: int,
    hooks: IsaacRuntimeCaptureHooks,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    color_profile_override: dict[str, Any] | None = None,
    render_settle_frames: int = 0,
    isaac_aa_op: int | None = None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    del focus_object_id, focus_receptacle_id
    hooks.require_isaac_import()
    from isaaclab.app import AppLauncher

    launcher_args = hooks.isaac_app_launcher_args(AppLauncher)
    app_launcher = AppLauncher(launcher_args)
    simulation_app = app_launcher.app
    hooks.set_deferred_simulation_app(simulation_app)
    capture = hooks.capture_isaac_lab_camera_views(
        scene_usd=scene_usd,
        view_paths=view_paths,
        width=width,
        height=height,
        simulation_app=simulation_app,
        robot_import=hooks.dict_value(state.get("robot_import")),
        semantic_pose_state=hooks.dict_value(state.get("semantic_pose_state")),
        color_profile_override=color_profile_override,
        render_settle_frames=render_settle_frames,
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    )
    capture["simulation_app_reuse_token"] = simulation_app
    return capture


def _validate_runtime_smoke_artifacts(
    *,
    smoke_image: Path,
    scene_index_diagnostics: dict[str, Any] | None,
    robot_view_images: dict[str, Any],
    robot_view_keys: tuple[str, ...],
) -> None:
    if not smoke_image.is_file():
        raise RuntimeError(f"Isaac Lab camera capture did not write {smoke_image}")
    if scene_index_diagnostics is None:
        raise RuntimeError("Isaac Lab runtime smoke did not inspect the USD scene index.")
    missing_views = sorted(
        key for key in robot_view_keys if not Path(str(robot_view_images.get(key, ""))).is_file()
    )
    if missing_views:
        raise RuntimeError(f"Isaac Lab robot view capture missed views: {', '.join(missing_views)}")
