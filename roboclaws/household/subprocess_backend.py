from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.camera_control import load_camera_control_request
from roboclaws.household.household_backend_port import HouseholdRuntimeEvidence
from roboclaws.household.planner_observed_binding import (
    backend_planner_task_binding_from_state,
)
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
    TargetRule,
)
from roboclaws.household.worker_runner import (
    parse_last_json_object,
    parse_worker_json_object_line,
    worker_env,
    worker_timeout_s,
)
from roboclaws.household.worker_runner import read_process_stderr as _read_process_stderr

MOLMOSPACES_SUBPROCESS_BACKEND = "molmospaces_subprocess"
DEFAULT_MOLMOSPACES_PYTHON = Path(sys.executable)
DEFAULT_MOLMOSPACES_MUJOCO_GL = "egl"
DEFAULT_WORKER_TIMEOUT_S = 120.0
WORKER_TIMEOUTS_S = {
    "init": 300.0,
    "snapshot": 60.0,
    "robot_views": 120.0,
    "camera_views": 180.0,
}
WORKER_MODULE = "roboclaws.backends.molmospaces.worker"
PERSISTENT_WORKER_DISABLED_VALUES = {"0", "false", "no", "off"}

_parse_last_json_object = parse_last_json_object


class MolmoSpacesSubprocessBackend:
    """Backend wrapper for the uv-managed MolmoSpaces runtime."""

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
        generated_mess_count: int = 5,
        generated_mess_object_ids: tuple[str, ...] = (),
        generated_mess_manifest_path: Path | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "molmospaces_backend_state.json"
        self.python_executable = python_executable or Path(
            os.environ.get("ROBOCLAWS_MOLMOSPACES_PYTHON", str(DEFAULT_MOLMOSPACES_PYTHON))
        )
        self._persistent_enabled = _persistent_worker_enabled()
        self._persistent_process: subprocess.Popen[str] | None = None
        self._persistent_lock = threading.Lock()
        self._persistent_request_id = 0
        init_args = [
            "--seed",
            str(seed),
            "--scene-source",
            scene_source,
            "--scene-index",
            str(scene_index),
            "--generated-mess-count",
            str(generated_mess_count),
        ]
        for object_id in generated_mess_object_ids:
            init_args.extend(["--generated-mess-object-id", str(object_id)])
        if generated_mess_manifest_path is not None:
            init_args.extend(["--generated-mess-manifest-path", str(generated_mess_manifest_path)])
        if include_robot:
            init_args.extend(["--include-robot", "--robot-name", robot_name])
        result = self._run_worker("init", *init_args)
        self.backend = MOLMOSPACES_SUBPROCESS_BACKEND
        self.scenario = _scenario_from_worker_payload(
            result["scenario"],
            result["private_manifest"],
        )
        self.runtime = result["runtime"]
        self.model_stats = result["model_stats"]
        self.scene_xml = result["scene_xml"]
        self.metadata_object_count = result["metadata_object_count"]
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

    def backend_name(self) -> str:
        return MOLMOSPACES_SUBPROCESS_BACKEND

    def supports_visual_snapshots(self) -> bool:
        return True

    def supports_robot_views(self) -> bool:
        return True

    def requested_mess_count(self) -> int | None:
        return self.requested_generated_mess_count

    def location_relation(self, object_id: str) -> str:
        return "on"

    def scene_index_source(self) -> str:
        return ""

    def scene_index_fixture_pose(self, fixture_id: str) -> list[float] | None:
        return None

    def planner_scene(self) -> dict[str, Any]:
        return {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": bool(self.scene_xml),
            "scene_xml": str(self.scene_xml or ""),
            "backend": self.backend_name(),
            **(
                {
                    "evidence_note": (
                        "Real MolmoSpaces cleanup scene used to sample exact planner proof tasks."
                    )
                }
                if self.scene_xml
                else {}
            ),
        }

    def runtime_evidence(self) -> HouseholdRuntimeEvidence:
        return {
            "runtime": self.runtime,
            "model_stats": self.model_stats,
            "scene_xml": self.scene_xml,
            "metadata_object_count": self.metadata_object_count,
            "requested_generated_mess_count": self.requested_generated_mess_count,
            "generated_mess_count": self.generated_mess_count,
            "python_executable": str(self.python_executable),
            "scenario_source": "",
            "scene_usd": "",
            "scene_index": None,
            "object_index": {},
            "receptacle_index": {},
            "scene_index_diagnostics": {},
            "scene_binding_diagnostics": {},
            "segmentation": {},
            "scene_load": {},
            "mapping_gaps": [],
            "snapshot_artifacts": [],
            "semantic_pose_state": {},
            "semantic_pose_view_capture": {},
            "robot": self.robot,
            "robot_import": {},
            "mess_placement_diagnostics": self.mess_placement_diagnostics,
            "placement_diagnostics": self.placement_diagnostics,
            "scene_index_artifact": {},
        }

    @property
    def mess_placement_diagnostics(self) -> list[dict[str, Any]]:
        raw = self._read_state().get("mess_placement_diagnostics") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    @property
    def placement_diagnostics(self) -> list[dict[str, Any]]:
        raw = self._read_state().get("placement_diagnostics") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def write_snapshot(self, output_path: Path, *, title: str) -> Path:
        self._run_worker("snapshot", "--output-path", str(output_path), "--title", title)
        return output_path

    def write_snapshot_with_resolution(
        self,
        output_path: Path,
        *,
        title: str,
        width: int,
        height: int,
    ) -> Path:
        self._run_worker(
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
        return output_path

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
            args.extend(["--camera-yaw-offset-deg", str(camera_yaw_offset_deg)])
        if camera_pitch_offset_deg:
            args.extend(["--camera-pitch-offset-deg", str(camera_pitch_offset_deg)])
        return self._run_worker("robot_views", *args)

    def write_robot_views_with_resolution(
        self,
        output_dir: Path,
        *,
        label: str,
        width: int,
        height: int,
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
        if focus_object_id is not None:
            args.extend(["--focus-object-id", focus_object_id])
        if focus_receptacle_id is not None:
            args.extend(["--focus-receptacle-id", focus_receptacle_id])
        if camera_yaw_offset_deg:
            args.extend(["--camera-yaw-offset-deg", str(camera_yaw_offset_deg)])
        if camera_pitch_offset_deg:
            args.extend(["--camera-pitch-offset-deg", str(camera_pitch_offset_deg)])
        return self._run_worker("robot_views", *args)

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

    def planner_task_binding(self, object_id: str, receptacle_id: str) -> dict[str, Any]:
        return backend_planner_task_binding_from_state(
            self._read_state(),
            object_id=object_id,
            target_receptacle_id=receptacle_id,
        )

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return self._run_worker("navigate_to_object", "--object-id", object_id)

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._run_worker("navigate_to_receptacle", "--receptacle-id", receptacle_id)

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

    def close(self) -> None:
        self._stop_persistent_worker()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _read_state(self) -> dict[str, Any]:
        return read_json_object(self.state_path, label="MolmoSpaces backend state")

    def _run_worker(self, command: str, *args: str) -> dict[str, Any]:
        if getattr(self, "_persistent_enabled", False) and command != "init":
            return self._run_persistent_worker(command, *args)
        return self._run_worker_once(command, *args)

    def _run_worker_once(self, command: str, *args: str) -> dict[str, Any]:
        if not self.python_executable.is_file():
            raise RuntimeError(
                "MolmoSpaces Python runtime is missing: "
                f"{self.python_executable}. Set ROBOCLAWS_MOLMOSPACES_PYTHON."
            )
        timeout_s = _worker_timeout_s(command)
        try:
            completed = subprocess.run(
                _worker_command(self.python_executable, self.state_path, command, args),
                check=False,
                capture_output=True,
                text=True,
                env=_worker_env(),
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"MolmoSpaces subprocess worker timed out ({command}, {timeout_s:g}s)"
            ) from exc
        if completed.returncode != 0:
            raise RuntimeError(
                "MolmoSpaces subprocess worker failed "
                f"({command}, exit {completed.returncode}): {completed.stderr.strip()}"
            )
        return parse_last_json_object(completed.stdout, worker_name="MolmoSpaces")

    def _run_persistent_worker(self, command: str, *args: str) -> dict[str, Any]:
        if not self.python_executable.is_file():
            raise RuntimeError(
                "MolmoSpaces Python runtime is missing: "
                f"{self.python_executable}. Set ROBOCLAWS_MOLMOSPACES_PYTHON."
            )
        timeout_s = _worker_timeout_s(command)
        with self._persistent_lock:
            process = self._ensure_persistent_worker()
            self._persistent_request_id += 1
            request_id = self._persistent_request_id
            payload = {
                "id": request_id,
                "command": command,
                "kwargs": _worker_kwargs_from_args(command, args),
            }
            assert process.stdin is not None
            try:
                process.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
                process.stdin.flush()
            except BrokenPipeError as exc:
                self._stop_persistent_worker_locked()
                raise RuntimeError(
                    f"MolmoSpaces persistent worker pipe broke before {command}"
                ) from exc

            line = self._read_persistent_line(process, timeout_s=timeout_s, command=command)
            try:
                response = _parse_persistent_worker_packet(line, command=command)
            except ValueError as exc:
                self._stop_persistent_worker_locked()
                raise RuntimeError(str(exc)) from exc
            if response.get("id") != request_id:
                self._stop_persistent_worker_locked()
                raise RuntimeError(
                    "MolmoSpaces persistent worker response id mismatch "
                    f"for {command}: expected {request_id}, got {response.get('id')}"
                )
            if not response.get("ok"):
                error = str(response.get("error") or "unknown error")
                error_type = str(response.get("error_type") or "RuntimeError")
                raise RuntimeError(
                    f"MolmoSpaces persistent worker failed ({command}, {error_type}): {error}"
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(
                    f"MolmoSpaces persistent worker returned non-object result for {command}: "
                    f"{result!r}"
                )
            return result

    def _ensure_persistent_worker(self) -> subprocess.Popen[str]:
        process = self._persistent_process
        if process is not None and process.poll() is None:
            return process
        worker_env = _worker_env()
        worker_command = _worker_command(
            self.python_executable,
            self.state_path,
            "serve",
            (),
        )
        process = subprocess.Popen(
            worker_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=worker_env,
            bufsize=1,
        )
        self._persistent_process = process
        line = self._read_persistent_line(
            process,
            timeout_s=_worker_timeout_s("serve"),
            command="serve",
        )
        try:
            ready = _parse_persistent_worker_packet(line, command="serve")
        except ValueError as exc:
            self._stop_persistent_worker_locked()
            raise RuntimeError(str(exc)) from exc
        if not ready.get("ok") or ready.get("event") != "ready":
            self._stop_persistent_worker_locked()
            raise RuntimeError(
                "MolmoSpaces persistent worker did not become ready: "
                f"{json.dumps(ready, sort_keys=True)}"
            )
        return process

    def _read_persistent_line(
        self,
        process: subprocess.Popen[str],
        *,
        timeout_s: float,
        command: str,
    ) -> str:
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        try:
            selector.register(process.stdout, selectors.EVENT_READ)
            events = selector.select(timeout_s)
        finally:
            selector.close()
        if not events:
            if process.poll() is not None:
                stderr = _read_process_stderr(process)
                self._stop_persistent_worker_locked()
                raise RuntimeError(
                    "MolmoSpaces persistent worker exited before responding "
                    f"({command}): {stderr.strip()}"
                )
            self._stop_persistent_worker_locked(kill=True)
            raise RuntimeError(
                f"MolmoSpaces persistent worker timed out ({command}, {timeout_s:g}s)"
            )
        line = process.stdout.readline()
        if not line:
            stderr = _read_process_stderr(process) if process.poll() is not None else ""
            self._stop_persistent_worker_locked()
            raise RuntimeError(
                "MolmoSpaces persistent worker closed stdout before responding "
                f"({command}): {stderr.strip()}"
            )
        return line

    def _stop_persistent_worker(self) -> None:
        lock = getattr(self, "_persistent_lock", None)
        if lock is None:
            return
        with lock:
            self._stop_persistent_worker_locked()

    def _stop_persistent_worker_locked(self, *, kill: bool = False) -> None:
        process = getattr(self, "_persistent_process", None)
        self._persistent_process = None
        if process is None or process.poll() is not None:
            return
        if not kill and process.stdin is not None:
            try:
                process.stdin.write(
                    json.dumps(
                        {
                            "id": -1,
                            "command": "shutdown",
                            "kwargs": {},
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                process.stdin.flush()
            except Exception:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)


def _worker_env() -> dict[str, str]:
    return worker_env(
        defaults={
            "MUJOCO_GL": os.environ.get(
                "ROBOCLAWS_MOLMOSPACES_MUJOCO_GL",
                DEFAULT_MOLMOSPACES_MUJOCO_GL,
            )
        }
    )


def _worker_command(
    python_executable: Path,
    state_path: Path,
    command: str,
    args: tuple[str, ...],
) -> list[str]:
    return [
        str(python_executable),
        "-m",
        WORKER_MODULE,
        "--state-path",
        str(state_path),
        command,
        *args,
    ]


def _worker_timeout_s(command: str) -> float:
    return worker_timeout_s(
        command=command,
        override_env_var="ROBOCLAWS_MOLMOSPACES_WORKER_TIMEOUT_S",
        command_timeouts=WORKER_TIMEOUTS_S,
        default_timeout_s=DEFAULT_WORKER_TIMEOUT_S,
    )


def _persistent_worker_enabled() -> bool:
    value = os.environ.get("ROBOCLAWS_MOLMOSPACES_PERSISTENT_WORKER", "1")
    return value.strip().lower() not in PERSISTENT_WORKER_DISABLED_VALUES


def _parse_persistent_worker_packet(line: str, *, command: str) -> dict[str, Any]:
    try:
        return parse_worker_json_object_line(
            line,
            worker_name="MolmoSpaces persistent",
            source=f"{command} response",
        )
    except ValueError as exc:
        raise ValueError(
            f"MolmoSpaces persistent worker returned invalid packet for {command}: {exc}"
        ) from exc


def _worker_kwargs_from_args(command: str, args: tuple[str, ...]) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    index = 0
    while index < len(args):
        flag = args[index]
        if not flag.startswith("--"):
            raise ValueError(f"unexpected worker argument for {command}: {flag!r}")
        if index + 1 >= len(args):
            raise ValueError(f"missing value for worker argument {flag!r} ({command})")
        key = flag[2:].replace("-", "_")
        kwargs[key] = args[index + 1]
        index += 2
    return kwargs


def _scenario_from_worker_payload(
    public: dict[str, Any],
    private: dict[str, Any],
) -> CleanupScenario:
    manifest = PrivateScoringManifest(
        scenario_id=str(private["scenario_id"]),
        success_threshold=int(private["success_threshold"]),
        targets=tuple(
            TargetRule(
                object_id=str(target["object_id"]),
                valid_receptacle_ids=tuple(str(value) for value in target["valid_receptacle_ids"]),
            )
            for target in private["targets"]
        ),
    )
    return CleanupScenario(
        scenario_id=str(public["scenario_id"]),
        task=str(public["task"]),
        seed=int(public["seed"]),
        objects=tuple(
            CleanupObject(
                object_id=str(item["object_id"]),
                name=str(item["name"]),
                category=str(item["category"]),
                location_id=str(item.get("location_id", "")),
                pickupable=bool(item.get("pickupable", True)),
            )
            for item in public["objects"]
        ),
        receptacles=tuple(
            CleanupReceptacle(
                receptacle_id=str(item["receptacle_id"]),
                name=str(item["name"]),
                room_area=str(item.get("room_area", "unknown")),
                kind=str(item.get("kind", "receptacle")),
                category=str(item["category"]) if item.get("category") is not None else None,
            )
            for item in public["receptacles"]
        ),
        private_manifest=manifest,
    )
