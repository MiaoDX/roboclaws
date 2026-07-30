"""Isaac runtime capture and USD inspection composition."""

from __future__ import annotations

from roboclaws.backends.isaaclab.runtime_dependencies import (
    _DEFERRED_SIMULATION_APP,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ISAAC_SEGMENTATION_DATA_TYPES,
    REAL_ROBOT_VIEW_CAPTURE_METHOD,
    REAL_SMOKE_CAPTURE_METHOD,
    REAL_SMOKE_RENDERER_MODE,
    ROBOT_VIEW_KEYS,
    Any,
    CleanupScenario,
    Path,
    _authored_reference_asset_paths,
    _dict,
    _is_object_prim_path,
    _is_receptacle_prim_path,
    _local_reference_asset_missing,
    _merge_molmospaces_metadata_index,
    _module_version,
    _pose_near,
    _round_vec3,
    _support_pose_from_support_surface,
    _support_pose_from_usd_bounds,
    _usd_handle_from_prim,
    _usd_index_entry,
    argparse,
    isaac_runtime_capture,
    isaac_runtime_smoke_usd,
    isaac_scene_index_geometry,
)


def _require_isaac_import() -> None:
    try:
        import isaaclab  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Isaac Lab runtime is unavailable. Install Isaac Sim / Isaac Lab in "
            ".venv-isaaclab/ or set ROBOCLAWS_ISAACLAB_RUNTIME_MODE=fake for "
            "CI protocol tests that do not claim renderer proof."
        ) from exc


def real_runtime_smoke(
    args: argparse.Namespace,
    scenario: CleanupScenario,
) -> dict[str, Any]:

    return isaac_runtime_capture.real_runtime_smoke(
        args,
        scenario,
        hooks=_isaac_runtime_capture_hooks(),
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
        robot_view_keys=ROBOT_VIEW_KEYS,
        segmentation_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
        real_smoke_renderer_mode=REAL_SMOKE_RENDERER_MODE,
        real_smoke_capture_method=REAL_SMOKE_CAPTURE_METHOD,
        real_robot_view_capture_method=REAL_ROBOT_VIEW_CAPTURE_METHOD,
    )


def _isaac_runtime_capture_hooks() -> isaac_runtime_capture.IsaacRuntimeCaptureHooks:

    from roboclaws.backends.isaaclab.runtime_camera import (
        _capture_isaac_lab_camera_views,
        _isaac_app_launcher_args,
    )
    from roboclaws.backends.isaaclab.runtime_state import (
        _rby1m_robot_import_plan,
        _scene_usd_path,
    )

    return isaac_runtime_capture.IsaacRuntimeCaptureHooks(
        capture_isaac_lab_camera_views=_capture_isaac_lab_camera_views,
        dict_value=_dict,
        generated_scene_filename=isaac_runtime_smoke_usd.generated_scene_filename,
        inspect_usd_scene_index=_inspect_usd_scene_index,
        isaac_app_launcher_args=_isaac_app_launcher_args,
        module_version=_module_version,
        rby1m_robot_import_plan=_rby1m_robot_import_plan,
        require_isaac_import=_require_isaac_import,
        runtime_smoke_robot_view_paths=_runtime_smoke_robot_view_paths,
        scene_usd_path=_scene_usd_path,
        set_deferred_simulation_app=_set_deferred_simulation_app,
        write_generated_runtime_smoke_usd=isaac_runtime_smoke_usd.write_generated_runtime_smoke_usd,
    )


def _set_deferred_simulation_app(simulation_app: Any) -> None:

    _DEFERRED_SIMULATION_APP[0] = simulation_app


def _inspect_usd_scene_index(usd_path: Path) -> dict[str, Any]:

    return isaac_scene_index_geometry.inspect_usd_scene_index(
        usd_path,
        hooks=_isaac_usd_scene_index_hooks(),
    )


def _isaac_usd_scene_index_hooks() -> isaac_scene_index_geometry.IsaacUsdSceneIndexHooks:

    return isaac_scene_index_geometry.IsaacUsdSceneIndexHooks(
        annotate_usd_index_geometry=_annotate_usd_index_geometry,
        authored_reference_asset_paths=_authored_reference_asset_paths,
        dict_value=_dict,
        iter_usd_prim_range=_iter_usd_prim_range,
        is_object_prim_path=_is_object_prim_path,
        is_receptacle_prim_path=_is_receptacle_prim_path,
        local_reference_asset_missing=_local_reference_asset_missing,
        merge_molmospaces_metadata_index=_merge_molmospaces_metadata_index,
        pose_near=_pose_near,
        room_outline_from_usd_prim=_room_outline_from_usd_prim,
        round_vec3=_round_vec3,
        support_pose_from_support_surface=_support_pose_from_support_surface,
        support_pose_from_usd_bounds=_support_pose_from_usd_bounds,
        usd_handle_from_prim=_usd_handle_from_prim,
        usd_index_entry=_usd_index_entry,
        usd_receptacle_support_surfaces=_usd_receptacle_support_surfaces,
        usd_world_bounds=_usd_world_bounds,
        usd_world_root_position=_usd_world_root_position,
    )


def _annotate_usd_index_geometry(
    *,
    usd_path: Path,
    stage: Any,
    object_index: dict[str, dict[str, Any]],
    receptacle_index: dict[str, dict[str, Any]],
    usd_geom: Any,
) -> None:

    return isaac_scene_index_geometry.annotate_usd_index_geometry(
        usd_path=usd_path,
        stage=stage,
        object_index=object_index,
        receptacle_index=receptacle_index,
        usd_geom=usd_geom,
        hooks=_isaac_usd_scene_index_hooks(),
    )


def _usd_world_bounds(prim: Any, *, usd_geom: Any) -> dict[str, Any] | None:

    return isaac_scene_index_geometry.usd_world_bounds(
        prim,
        usd_geom=usd_geom,
        round_vec3=_round_vec3,
    )


def _usd_world_root_position(prim: Any, *, usd_geom: Any) -> list[float] | None:

    return isaac_scene_index_geometry.usd_world_root_position(
        prim,
        usd_geom=usd_geom,
        round_vec3=_round_vec3,
    )


def _usd_receptacle_support_surfaces(*, prim: Any, usd_geom: Any) -> list[dict[str, Any]]:

    return isaac_scene_index_geometry.receptacle_support_surfaces(
        prim=prim,
        usd_geom=usd_geom,
        world_bounds=_usd_world_bounds,
        iter_prim_range=_iter_usd_prim_range,
    )


def _room_outline_from_usd_prim(
    prim_path: str,
    prim: Any,
    *,
    usd_geom: Any,
) -> dict[str, Any] | None:

    return isaac_scene_index_geometry.room_outline_from_usd_prim(
        prim_path,
        prim,
        usd_geom=usd_geom,
        world_bounds=_usd_world_bounds,
    )


def _iter_usd_prim_range(prim: Any) -> Any:

    return isaac_scene_index_geometry.iter_usd_prim_range(prim)


def _runtime_smoke_robot_view_paths(
    run_dir: Path,
    *,
    smoke_image: Path,
) -> dict[str, Path]:

    return {
        "fpv": smoke_image,
        "chase": run_dir / "isaac_runtime_smoke.chase.png",
        "topdown": run_dir / "isaac_runtime_smoke.topdown.png",
        "verify": run_dir / "isaac_runtime_smoke.verify.png",
    }


def capture_semantic_pose_robot_views(
    *,
    state: dict[str, Any],
    scene_usd: Path,
    view_paths: dict[str, Path],
    width: int,
    height: int,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
    color_profile_override: dict[str, Any] | None = None,
    render_settle_frames: int = 0,
    isaac_aa_op: int | None = None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:

    return isaac_runtime_capture.capture_semantic_pose_robot_views(
        state=state,
        scene_usd=scene_usd,
        view_paths=view_paths,
        width=width,
        height=height,
        hooks=_isaac_runtime_capture_hooks(),
        focus_object_id=focus_object_id,
        focus_receptacle_id=focus_receptacle_id,
        color_profile_override=color_profile_override,
        render_settle_frames=render_settle_frames,
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    )
