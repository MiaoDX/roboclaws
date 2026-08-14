from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.b1_nurec_scene import prepare_b1_nurec_scene_usd
from roboclaws.household.camera_control import load_camera_control_request
from roboclaws.household.subprocess_backend import _scenario_from_worker_payload
from roboclaws.household.worker_runner import run_json_worker_once, worker_env, worker_timeout_s

ISAACLAB_SUBPROCESS_BACKEND = "isaaclab_subprocess"
ISAAC_SEMANTIC_POSE_STATE_SCHEMA = "isaac_semantic_pose_state_v1"
ISAAC_SEMANTIC_POSE_EVENT_SCHEMA = "isaac_semantic_pose_event_v1"
ISAAC_SEMANTIC_POSE_STATE_SOURCE = "backend_json_state"
ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA = "isaac_scene_index_artifact_v1"
ISAACLAB_ROBOT_VIEW_VARIANT = "isaaclab-fpv-topdown-chase-verify"
DEFAULT_ISAACLAB_PYTHON = Path(__file__).resolve().parents[2] / ".venv-isaaclab" / "bin" / "python"
DEFAULT_ISAAC_WORKER_TIMEOUT_S = 120.0
ISAAC_WORKER_TIMEOUTS_S = {
    "init": 300.0,
    "snapshot": 120.0,
    "robot_views": 120.0,
    "camera_views": 180.0,
}
ISAAC_WORKER_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "isaac_lab_cleanup"
    / "isaac_lab_backend_worker.py"
)
_ISAACLAB_TRUE_ENV_VALUES = {"1", "true", "TRUE", "yes", "YES"}


class IsaacLabSubprocessBackend:
    """Subprocess boundary for the heavy Isaac Sim / Isaac Lab runtime.

    The wrapper deliberately mirrors ``MolmoSpacesSubprocessBackend`` without
    importing Isaac packages in the normal Roboclaws process. CI tests may opt
    into the worker's explicit fake protocol mode; real local runs should use a
    `.venv-isaaclab/` Python with Isaac installed.
    """

    def __init__(
        self,
        *,
        run_dir: Path,
        seed: int = 7,
        python_executable: Path | None = None,
        scene_source: str = "procthor-10k-val",
        scene_index: int = 0,
        include_robot: bool = False,
        robot_name: str = "rby1m",
        generated_mess_count: int = 1,
        generated_mess_object_ids: tuple[str, ...] = (),
        generated_mess_manifest_path: Path | None = None,
        map_bundle_dir: Path | None = None,
        scene_usd_path: Path | None = None,
        enable_segmentation: bool | None = None,
        segmentation_data_types: tuple[str, ...] | None = None,
        segmentation_semantic_filter: tuple[str, ...] | None = None,
        runtime_mode: str | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "isaac_lab_backend_state.json"
        self.python_executable = python_executable or Path(
            os.environ.get("ROBOCLAWS_ISAACLAB_PYTHON", str(DEFAULT_ISAACLAB_PYTHON))
        )
        self.runtime_mode = runtime_mode or os.environ.get(
            "ROBOCLAWS_ISAACLAB_RUNTIME_MODE", "real"
        )
        prepared_scene_usd_path = prepare_b1_nurec_scene_usd(scene_usd_path)
        self.snapshot_artifacts: list[dict[str, Any]] = []
        init_args = [
            "--run-dir",
            str(run_dir),
            "--seed",
            str(seed),
            "--scene-source",
            scene_source,
            "--scene-index",
            str(scene_index),
            "--generated-mess-count",
            str(generated_mess_count),
            "--runtime-mode",
            self.runtime_mode,
        ]
        _extend_isaac_init_args(
            init_args,
            generated_mess_object_ids=generated_mess_object_ids,
            generated_mess_manifest_path=generated_mess_manifest_path,
            include_robot=include_robot,
            robot_name=robot_name,
            map_bundle_dir=map_bundle_dir,
            scene_usd_path=prepared_scene_usd_path,
        )
        _extend_segmentation_args(
            init_args,
            enable_segmentation=enable_segmentation,
            segmentation_data_types=segmentation_data_types,
            segmentation_semantic_filter=segmentation_semantic_filter,
        )
        result = self._run_worker("init", *init_args)
        self.backend = ISAACLAB_SUBPROCESS_BACKEND
        self.scenario = _scenario_from_worker_payload(
            result["scenario"],
            result["private_manifest"],
        )
        self.runtime = result["runtime"]
        self.scenario_source = str(result.get("scenario_source") or "")
        self.scene_usd = result.get("scene_usd", "")
        self.scene_index = int(result.get("scene_index", scene_index))
        self.object_index = result.get("object_index", {})
        self.receptacle_index = result.get("receptacle_index", {})
        self.segmentation = result.get("segmentation", {})
        self.scene_load = result.get("scene_load", {})
        self.scene_index_diagnostics = result.get("scene_index_diagnostics", {})
        self.scene_binding_diagnostics = result.get("scene_binding_diagnostics", {})
        self.mapping_gaps = result.get("mapping_gaps", [])
        self.robot_import = result.get("robot_import", {})
        self.room_outlines = [
            dict(item)
            for item in (self.scene_index_diagnostics.get("room_outlines") or [])
            if isinstance(item, dict)
        ]
        self.requested_generated_mess_count = int(
            result.get("requested_generated_mess_count", generated_mess_count)
        )
        self.generated_mess_count = int(result.get("generated_mess_count", 0))
        self.robot = result.get("robot")

    @property
    def held_object_id(self) -> str | None:
        state = self._read_state()
        value = state.get("held_object_id")
        return str(value) if value is not None else None

    def object_locations(self) -> dict[str, str]:
        result = self._run_worker("locations")
        return {str(key): str(value) for key, value in result["final_locations"].items()}

    @property
    def mess_placement_diagnostics(self) -> list[dict[str, Any]]:
        raw = self._read_state().get("mess_placement_diagnostics") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    @property
    def placement_diagnostics(self) -> list[dict[str, Any]]:
        raw = self._read_state().get("placement_diagnostics") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    @property
    def semantic_pose_state(self) -> dict[str, Any]:
        raw = self._read_state().get("semantic_pose_state") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    @property
    def current_mapping_gaps(self) -> list[dict[str, Any]]:
        raw = self._read_state().get("mapping_gaps") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    @property
    def semantic_pose_view_capture(self) -> dict[str, Any]:
        raw = self._read_state().get("semantic_pose_view_capture") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def scene_index_artifact_payload(self) -> dict[str, Any]:
        """Return report-only USD scene index evidence without private scoring truth."""

        return {
            "schema": ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA,
            "backend": ISAACLAB_SUBPROCESS_BACKEND,
            "runtime_mode": str(self.runtime.get("runtime_mode") or self.runtime_mode),
            "scene_index": self.scene_index,
            "scene_usd": self.scene_usd,
            "scenario_source": self.scenario_source,
            "object_index_count": len(self.object_index),
            "receptacle_index_count": len(self.receptacle_index),
            "object_index": self.object_index,
            "receptacle_index": self.receptacle_index,
            "scene_load": self.scene_load,
            "scene_index_diagnostics": self.scene_index_diagnostics,
            "scene_binding_diagnostics": self.scene_binding_diagnostics,
            "segmentation": self.segmentation,
            "mapping_gaps": self.current_mapping_gaps,
            "robot": self.robot,
            "robot_import": self.robot_import,
            "requested_generated_mess_count": self.requested_generated_mess_count,
            "generated_mess_count": self.generated_mess_count,
            "agent_facing": False,
            "private_manifest_exposed_to_agent": False,
        }

    def write_snapshot(self, output_path: Path, *, title: str) -> Path:
        result = self._run_worker("snapshot", "--output-path", str(output_path), "--title", title)
        self._record_snapshot_artifact(result, title=title)
        return output_path

    def write_snapshot_with_resolution(
        self,
        output_path: Path,
        *,
        title: str,
        width: int,
        height: int,
    ) -> Path:
        result = self._run_worker(
            "snapshot",
            "--output-path",
            str(output_path),
            "--title",
            title,
            "--render-width",
            str(width),
            "--render-height",
            str(height),
        )
        self._record_snapshot_artifact(result, title=title)
        return output_path

    def _record_snapshot_artifact(self, result: dict[str, Any], *, title: str) -> None:
        if result.get("ok") is not True:
            raise RuntimeError(f"Isaac Lab snapshot failed: {result}")
        provenance = result.get("snapshot_provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        self.snapshot_artifacts.append(
            {
                "title": title,
                "output_path": str(result.get("output_path") or ""),
                "visual_artifact_provenance": result.get("visual_artifact_provenance"),
                "placeholder_visuals": result.get("placeholder_visuals"),
                "native_render_diagnostics": result.get("native_render_diagnostics") or {},
                "snapshot_provenance": provenance,
            }
        )

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        args = ["--output-dir", str(output_dir), "--label", label]
        if focus_object_id is not None:
            args.extend(["--focus-object-id", focus_object_id])
        if focus_receptacle_id is not None:
            args.extend(["--focus-receptacle-id", focus_receptacle_id])
        if camera_yaw_offset_deg:
            args.extend(["--camera-yaw-offset-deg", str(float(camera_yaw_offset_deg))])
        if camera_pitch_offset_deg:
            args.extend(["--camera-pitch-offset-deg", str(float(camera_pitch_offset_deg))])
        return self._run_worker("robot_views", *args)

    def write_robot_views_with_resolution(
        self,
        output_dir: Path,
        *,
        label: str,
        width: int,
        height: int,
        render_settle_frames: int = 0,
        isaac_aa_op: int | None = None,
        isaac_tonemap_op: int | None = None,
        isaac_exposure_bias: float | None = None,
        isaac_colorcorr_gain: tuple[float, float, float] | None = None,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        args = [
            "--output-dir",
            str(output_dir),
            "--label",
            label,
            "--render-width",
            str(width),
            "--render-height",
            str(height),
        ]
        if isaac_aa_op is not None:
            args.extend(["--isaac-aa-op", str(int(isaac_aa_op))])
        if isaac_tonemap_op is not None:
            args.extend(["--isaac-tonemap-op", str(int(isaac_tonemap_op))])
        if isaac_exposure_bias is not None:
            args.extend(["--isaac-exposure-bias", str(float(isaac_exposure_bias))])
        if isaac_colorcorr_gain is not None:
            args.extend(
                [
                    "--isaac-colorcorr-gain",
                    ",".join(f"{float(value):.6g}" for value in isaac_colorcorr_gain),
                ]
            )
        if render_settle_frames:
            args.extend(["--render-settle-frames", str(max(0, int(render_settle_frames)))])
        if focus_object_id is not None:
            args.extend(["--focus-object-id", focus_object_id])
        if focus_receptacle_id is not None:
            args.extend(["--focus-receptacle-id", focus_receptacle_id])
        if camera_yaw_offset_deg:
            args.extend(["--camera-yaw-offset-deg", str(float(camera_yaw_offset_deg))])
        if camera_pitch_offset_deg:
            args.extend(["--camera-pitch-offset-deg", str(float(camera_pitch_offset_deg))])
        return self._run_worker("robot_views", *args)

    def write_camera_views_with_resolution(
        self,
        output_dir: Path,
        *,
        view_specs_path: Path,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        return self._run_worker(
            "camera_views",
            "--output-dir",
            str(output_dir),
            "--view-specs-path",
            str(view_specs_path),
            "--render-width",
            str(width),
            "--render-height",
            str(height),
        )

    def render_camera_control_request(
        self,
        output_dir: Path,
        *,
        request_path: Path,
    ) -> dict[str, Any]:
        """Render externally supplied Roboclaws camera-control views."""

        request = load_camera_control_request(request_path)
        resolution = request["render_resolution"]
        return self._run_worker(
            "camera_views",
            "--output-dir",
            str(output_dir),
            "--camera-request-path",
            str(request_path),
            "--render-width",
            str(resolution["width"]),
            "--render-height",
            str(resolution["height"]),
        )

    def observe(self) -> dict[str, Any]:
        return self._run_worker("observe")

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return self._run_worker("navigate_to_object", "--object-id", object_id)

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._run_worker("navigate_to_receptacle", "--receptacle-id", receptacle_id)

    def navigate_to_waypoint(self, *, waypoint: dict[str, Any]) -> dict[str, Any]:
        return self._run_worker(
            "navigate_to_waypoint",
            "--waypoint-json",
            json.dumps(waypoint, sort_keys=True),
        )

    def navigate_to_relative_pose(
        self,
        *,
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict[str, Any]:
        return self._run_worker(
            "navigate_to_relative_pose",
            "--forward-m",
            str(float(forward_m)),
            "--lateral-m",
            str(float(lateral_m)),
            "--yaw-delta-deg",
            str(float(yaw_delta_deg)),
        )

    def pick(self, object_id: str) -> dict[str, Any]:
        return self._run_worker("pick", "--object-id", object_id)

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._run_worker("open_receptacle", "--receptacle-id", receptacle_id)

    def place(self, receptacle_id: str) -> dict[str, Any]:
        return self._run_worker("place", "--receptacle-id", receptacle_id)

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        return self._run_worker("place_inside", "--receptacle-id", receptacle_id)

    def close_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._run_worker("close_receptacle", "--receptacle-id", receptacle_id)

    def done(self, reason: str = "") -> dict[str, Any]:
        return self._run_worker("done", "--reason", reason)

    def _read_state(self) -> dict[str, Any]:
        return read_json_object(self.state_path, label="Isaac Lab backend state")

    def _run_worker(self, command: str, *args: str) -> dict[str, Any]:
        return run_json_worker_once(
            worker_name="Isaac Lab",
            python_executable=self.python_executable,
            missing_runtime_hint=(
                "Create .venv-isaaclab/ or set ROBOCLAWS_ISAACLAB_PYTHON. "
                "CI tests may set ROBOCLAWS_ISAACLAB_RUNTIME_MODE=fake explicitly."
            ),
            worker_script=ISAAC_WORKER_SCRIPT,
            state_path=self.state_path,
            command=command,
            args=args,
            env=_isaac_worker_env(self.runtime_mode),
            timeout_s=_isaac_worker_timeout_s(command),
        )


def _extend_isaac_init_args(
    args: list[str],
    *,
    generated_mess_object_ids: tuple[str, ...],
    generated_mess_manifest_path: Path | None,
    include_robot: bool,
    robot_name: str,
    map_bundle_dir: Path | None,
    scene_usd_path: Path | None,
) -> None:
    for object_id in generated_mess_object_ids:
        args.extend(["--generated-mess-object-id", str(object_id)])
    if generated_mess_manifest_path is not None:
        args.extend(["--generated-mess-manifest-path", str(generated_mess_manifest_path)])
    if include_robot:
        args.extend(["--include-robot", "--robot-name", robot_name])
    if map_bundle_dir is not None:
        args.extend(["--map-bundle-dir", str(map_bundle_dir)])
    if scene_usd_path is not None:
        args.extend(["--scene-usd-path", str(scene_usd_path)])


def _extend_segmentation_args(
    args: list[str],
    *,
    enable_segmentation: bool | None,
    segmentation_data_types: tuple[str, ...] | None,
    segmentation_semantic_filter: tuple[str, ...] | None,
) -> None:
    data_types = segmentation_data_types or _csv_env_tuple(
        "ROBOCLAWS_ISAACLAB_SEGMENTATION_DATA_TYPES"
    )
    semantic_filter = segmentation_semantic_filter or _csv_env_tuple(
        "ROBOCLAWS_ISAACLAB_SEGMENTATION_SEMANTIC_FILTER"
    )
    enabled = enable_segmentation
    if enabled is None:
        enabled = (
            os.environ.get("ROBOCLAWS_ISAACLAB_ENABLE_SEGMENTATION") in _ISAACLAB_TRUE_ENV_VALUES
        )
    if data_types or semantic_filter:
        enabled = True
    if not enabled:
        return
    args.append("--enable-segmentation")
    for data_type in data_types:
        args.extend(["--segmentation-data-type", data_type])
    for instance_name in semantic_filter:
        args.extend(["--segmentation-semantic-filter", instance_name])


def _csv_env_tuple(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.environ.get(name, "").split(",") if item.strip())


def _isaac_worker_env(runtime_mode: str) -> dict[str, str]:
    return worker_env(
        defaults={
            "PYTHONUNBUFFERED": "1",
            "ROBOCLAWS_ISAACLAB_RUNTIME_MODE": runtime_mode,
            "OMNI_KIT_ACCEPT_EULA": "YES",
        },
        remove=(
            "PYTHONPATH",
            "AMENT_PREFIX_PATH",
            "COLCON_PREFIX_PATH",
            "ROS_DISTRO",
            "ROS_VERSION",
            "ROS_PYTHON_VERSION",
        ),
    )


def _isaac_worker_timeout_s(command: str) -> float:
    return worker_timeout_s(
        command=command,
        override_env_var="ROBOCLAWS_ISAACLAB_WORKER_TIMEOUT_S",
        command_timeouts=ISAAC_WORKER_TIMEOUTS_S,
        default_timeout_s=DEFAULT_ISAAC_WORKER_TIMEOUT_S,
    )
