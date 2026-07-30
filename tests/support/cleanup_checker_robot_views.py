# ruff: noqa: F403, F405, F821
from tests.support.cleanup_checker_isaac import *


def _isaac_robot_view_provenance(
    views: dict[str, str],
    *,
    capture_method: str,
    semantic_pose_state_refreshed: bool,
    canonical_camera_control: bool,
    mounted_head_camera: bool,
    head_camera_equivalent: bool,
) -> dict[str, object]:
    provenance: dict[str, object] = {key: f"{capture_method}:{key}" for key in views}
    if canonical_camera_control:
        provenance["fpv"] = "isaac_lab_camera_rgb_canonical_robot_view:fpv"
        provenance["verify"] = "isaac_lab_camera_rgb_canonical_robot_view:verify"
    if mounted_head_camera:
        provenance["fpv"] = "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv"
    if head_camera_equivalent:
        provenance["fpv"] = "isaac_lab_camera_rgb_head_camera_equivalent:fpv"
    provenance["semantic_pose_state_refreshed"] = semantic_pose_state_refreshed
    provenance["canonical_camera_control"] = canonical_camera_control
    provenance["robot_mounted_head_camera"] = mounted_head_camera
    provenance["head_camera_equivalent"] = head_camera_equivalent
    return provenance


def _mounted_head_camera_contract(
    robot_pose: dict[str, object],
    provenance: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "robot_mounted_head_camera_robot_view",
        "camera_control_api": None,
        "camera_model": "robot_mounted_head_camera_v1",
        "same_pose_api": False,
        "camera_prim_path": "/World/robot_0/head_camera",
        "robot_pose": robot_pose,
        "agent_facing_fpv": {
            "source": "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
            "canonical_camera_control": False,
            "robot_mounted": True,
            "head_camera_equivalent": False,
            "camera_prim_path": "/World/robot_0/head_camera",
        },
        "report_verify_view": {
            "source": provenance["verify"],
            "canonical_camera_control": False,
        },
    }


def _head_camera_equivalent_contract(
    robot_pose: dict[str, object],
    provenance: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "robot_head_camera_equivalent_robot_view",
        "camera_control_api": None,
        "camera_model": "robot_head_camera_equivalent_v1",
        "same_pose_api": False,
        "robot_pose": robot_pose,
        "agent_facing_fpv": {
            "source": "isaac_lab_camera_rgb_head_camera_equivalent:fpv",
            "canonical_camera_control": False,
            "head_camera_equivalent": True,
        },
        "report_verify_view": {
            "source": provenance["verify"],
            "canonical_camera_control": False,
        },
    }


def _canonical_camera_control_contract(robot_pose: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "canonical_camera_control_robot_view",
        "camera_control_api": "roboclaws.camera_control.render_views",
        "camera_model": "canonical_eye_target_camera_v1",
        "same_pose_api": True,
        "lighting_profile": {"profile_id": "scene_probe_existing_usd_lights_v1"},
        "color_profile": {"profile_id": "display_srgb_soft_highlight_v1"},
        "robot_pose": robot_pose,
        "agent_facing_fpv": {
            "source": "canonical_eye_target_robot_pose",
            "canonical_camera_control": True,
            "eye": [1.0, 2.0, 1.55],
            "target": [2.5, 5.5, 0.6],
        },
        "report_verify_view": {
            "source": "canonical_eye_target_robot_verify",
            "canonical_camera_control": True,
            "eye": [1.2, 2.4, 2.3],
            "target": [2.5, 5.5, 0.6],
        },
    }


def _backend_local_camera_control_contract(provenance: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "robot_view_camera_control_contract_v1",
        "backend": "isaaclab_subprocess",
        "status": "backend_local_scene_bounds_camera",
        "camera_control_api": None,
        "camera_model": "backend_local_robot_view",
        "same_pose_api": False,
        "agent_facing_fpv": {
            "source": provenance["fpv"],
            "canonical_camera_control": False,
        },
        "report_verify_view": {
            "source": provenance["verify"],
            "canonical_camera_control": False,
        },
    }


def _isaac_robot_view_camera_control_contract(
    robot_pose: dict[str, object],
    provenance: dict[str, object],
    *,
    canonical_camera_control: bool,
    mounted_head_camera: bool,
    head_camera_equivalent: bool,
) -> dict[str, object]:
    if mounted_head_camera:
        return _mounted_head_camera_contract(robot_pose, provenance)
    if head_camera_equivalent:
        return _head_camera_equivalent_contract(robot_pose, provenance)
    if canonical_camera_control:
        return _canonical_camera_control_contract(robot_pose)
    return _backend_local_camera_control_contract(provenance)


def _apply_isaac_robot_view_step_metadata(
    step: dict[str, object],
    views: dict[str, str],
    *,
    capture_method: str,
    semantic_pose_state_refreshed: bool,
    canonical_camera_control: bool,
    mounted_head_camera: bool,
    head_camera_equivalent: bool,
) -> None:
    provenance = _isaac_robot_view_provenance(
        views,
        capture_method=capture_method,
        semantic_pose_state_refreshed=semantic_pose_state_refreshed,
        canonical_camera_control=canonical_camera_control,
        mounted_head_camera=mounted_head_camera,
        head_camera_equivalent=head_camera_equivalent,
    )
    robot_pose = _isaac_robot_view_pose()
    step["robot_pose"] = robot_pose
    step["view_provenance"] = provenance
    step["camera_control_contract"] = _isaac_robot_view_camera_control_contract(
        robot_pose,
        provenance,
        canonical_camera_control=canonical_camera_control,
        mounted_head_camera=mounted_head_camera,
        head_camera_equivalent=head_camera_equivalent,
    )


def _isaac_robot_view_camera_control_summary(
    step_count: int,
    *,
    canonical_camera_control: bool,
    head_camera_equivalent: bool,
) -> dict[str, object]:
    if head_camera_equivalent:
        return {
            "schema": "robot_view_camera_control_summary_v1",
            "status": "all_robot_views_use_head_camera_fpv",
            "same_pose_api": False,
            "head_camera_fpv": True,
            "step_count": step_count,
            "contract_count": step_count,
            "canonical_contract_count": 0,
            "head_camera_contract_count": step_count,
            "backend_local_contract_count": step_count,
        }
    if canonical_camera_control:
        return {
            "schema": "robot_view_camera_control_summary_v1",
            "status": "all_robot_views_use_canonical_camera_control",
            "same_pose_api": True,
            "head_camera_fpv": False,
            "step_count": step_count,
            "contract_count": step_count,
            "canonical_contract_count": step_count,
            "head_camera_contract_count": 0,
            "backend_local_contract_count": 0,
        }
    return {
        "schema": "robot_view_camera_control_summary_v1",
        "status": "mixed_or_backend_local_robot_views",
        "same_pose_api": False,
        "head_camera_fpv": False,
        "step_count": step_count,
        "contract_count": step_count,
        "canonical_contract_count": 0,
        "head_camera_contract_count": 0,
        "backend_local_contract_count": step_count,
    }


def _add_isaac_robot_view_step(
    data: dict[str, object],
    base: Path,
    *,
    blank_key: str = "",
    capture_method: str = "isaac_lab_camera_rgb_static_robot_views",
    semantic_pose_state_refreshed: bool = False,
    canonical_camera_control: bool = False,
    mounted_head_camera: bool = False,
    head_camera_equivalent: bool = False,
) -> None:
    view_dir, views = _write_isaac_robot_view_images(base, blank_key=blank_key)
    report = _ensure_isaac_robot_view_report(base)
    artifacts = data.setdefault("artifacts", {})
    assert isinstance(artifacts, dict)
    artifacts["robot_views"] = str(view_dir.relative_to(base))
    artifacts["report"] = str(report.relative_to(base))
    data["view_variant"] = "isaaclab-fpv-topdown-chase-verify"
    steps = _base_isaac_robot_view_steps(views)
    for step in steps:
        _apply_isaac_robot_view_step_metadata(
            step,
            views,
            capture_method=capture_method,
            semantic_pose_state_refreshed=semantic_pose_state_refreshed,
            canonical_camera_control=canonical_camera_control,
            mounted_head_camera=mounted_head_camera,
            head_camera_equivalent=head_camera_equivalent,
        )
    data["robot_view_steps"] = steps
    data["robot_view_camera_control"] = _isaac_robot_view_camera_control_summary(
        len(steps),
        canonical_camera_control=canonical_camera_control,
        head_camera_equivalent=head_camera_equivalent,
    )


def _add_isaac_snapshot_artifacts(
    data: dict[str, object],
    base: Path,
    *,
    blank_output: bool = False,
) -> None:
    snapshot_dir = base / "isaac_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    source_path = snapshot_dir / "source.png"
    _write_nonblank_png(source_path)
    snapshots: list[dict[str, object]] = []
    for index in range(2):
        output_path = snapshot_dir / f"snapshot_{index}.png"
        if blank_output and index == 0:
            _write_blank_png(output_path)
        else:
            _write_nonblank_png(output_path)
        snapshots.append(
            {
                "title": f"snapshot {index}",
                "output_path": str(output_path.relative_to(base)),
                "visual_artifact_provenance": "isaac_lab_camera_rgb",
                "placeholder_visuals": False,
                "snapshot_provenance": {
                    "source_path": str(source_path.relative_to(base)),
                    "visual_artifact_provenance": "isaac_lab_camera_rgb",
                    "placeholder_visuals": False,
                    "static_isaac_capture": True,
                    "semantic_pose_rendered": False,
                },
            }
        )
    isaac_runtime = data["isaac_runtime"]
    assert isinstance(isaac_runtime, dict)
    isaac_runtime["snapshot_artifacts"] = snapshots


def _write_nonblank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (8, 8), (24, 40, 72))
    image.putpixel((0, 0), (220, 180, 40))
    image.save(path)


def _write_blank_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (0, 0, 0)).save(path)


__all__ = [name for name in globals() if not name.startswith("__")]
