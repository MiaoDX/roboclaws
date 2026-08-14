from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

CAPTURE_PATH = REPO_ROOT / "scripts" / "agibot" / "capture_map_context_views.py"

GENERATOR_PATH = REPO_ROOT / "scripts" / "agibot" / "generate_metric_map_from_context.py"

VERIFY_PATH = REPO_ROOT / "scripts" / "agibot" / "verify_waypoints_with_pnc.py"

SDK_RUNNER_PATH = REPO_ROOT / "vendors" / "agibot_sdk" / "tools" / "run_agibot_cleanup_backend.py"

RAW_FPV_CHECK_PATH = REPO_ROOT / "vendors" / "agibot_sdk" / "tools" / "check_raw_fpv_status.py"

NAV_ARTIFACTS_PATH = REPO_ROOT / "vendors" / "agibot_sdk" / "tools" / "agibot_nav_artifacts.py"

SIX_CAMERA_CAPTURE_PATH = REPO_ROOT / "vendors/agibot_sdk/tools/capture_six_camera_views.py"

COMPLETED_CONTEXT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "public_map_context.synthetic.json"


def _require_agibot_sdk_runner() -> None:
    if not SDK_RUNNER_PATH.is_file():
        pytest.skip("Agibot SDK vendor runner is unavailable in this checkout")


def _require_raw_fpv_checker() -> None:
    if not RAW_FPV_CHECK_PATH.is_file():
        pytest.skip("Agibot raw-FPV checker is unavailable in this checkout")


def _require_six_camera_capture() -> None:
    if not SIX_CAMERA_CAPTURE_PATH.is_file():
        pytest.skip("Agibot six-camera capture helper is unavailable in this checkout")


def _completed_context() -> dict:
    return json.loads(COMPLETED_CONTEXT_FIXTURE.read_text(encoding="utf-8"))


def _base_metric_map_context() -> dict:
    return {
        "schema": "agibot_gdk_map_context_authoring_v1",
        "environment_id": "agibot-minimal-office",
        "map_version": "minimal-navigation-map-v1",
        "frame_id": "map",
        "map_source": {
            "type": "agibot_gdk_map_context",
            "map_id": 7,
            "map_name": "minimal_office",
            "is_curr_map": True,
        },
        "robot_pose": {
            "pose_source": "agibot_gdk_slam_get_curr_pose",
            "x": 0.0,
            "y": 0.0,
            "yaw": 0.0,
        },
        "safety_bounds": {
            "frame_id": "map",
            "polygon": [
                {"x": -1.0, "y": -1.0},
                {"x": 3.0, "y": -1.0},
                {"x": 3.0, "y": 3.0},
                {"x": -1.0, "y": 3.0},
            ],
            "max_linear_speed_mps": 0.25,
        },
        "free_space_samples": [
            {
                "x": 0.5,
                "y": 0.0,
                "yaw": 0.0,
                "room_id": "open_office",
                "reachability_status": "verified",
            },
            {
                "x": 1.5,
                "y": 0.8,
                "yaw": 1.57,
                "room_id": "open_office",
                "reachability_status": "verified",
            },
            {
                "x": 2.2,
                "y": 2.0,
                "yaw": 3.14,
                "room_id": "open_office",
                "reachability_status": "verified",
            },
        ],
        "rooms": [
            {
                "room_id": "open_office",
                "room_label": "Open office",
                "polygon": [
                    {"x": -1.0, "y": -1.0},
                    {"x": 3.0, "y": -1.0},
                    {"x": 3.0, "y": 3.0},
                    {"x": -1.0, "y": 3.0},
                ],
            }
        ],
        "fixtures": [],
        "inspection_waypoints": [],
        "driveable_ways": [],
    }


def _capture_manifest(waypoint_id: str, *, x: float, y: float) -> dict:
    return {
        "schema": "agibot_gdk_map_context_capture_v1",
        "captured_at": "2026-05-19T00:00:00Z",
        "waypoint_id": waypoint_id,
        "map_source": {
            "type": "agibot_gdk_map_context",
            "map_id": 3,
            "map_name": "office_floor_1",
            "is_curr_map": True,
        },
        "robot_pose": {
            "frame_id": "map",
            "x": x,
            "y": y,
            "yaw": 0.1,
            "pose_source": "agibot_gdk_slam_get_curr_pose",
        },
        "camera_results": [
            {
                "camera_name": "head_color",
                "ok": True,
                "image_path": "head_color.jpg",
            }
        ],
    }


def _load_module(path: Path, name: str):
    if not path.is_file():
        pytest.skip(f"optional integration module is unavailable: {path.name}")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class _FakeTask:
    def __init__(self, state: int, *, task_id: int = 1, message: str = "") -> None:
        self.id = task_id
        self.state = state
        self.type = "normal_navi"
        self.message = message


class _FakePnc:
    def __init__(self) -> None:
        self._tasks = [_FakeTask(0, message="idle"), _FakeTask(9, message="success")]
        self.normal_navi_calls = 0
        self.last_request: object | None = None

    def get_task_state(self) -> _FakeTask:
        if len(self._tasks) > 1:
            return self._tasks.pop(0)
        return self._tasks[0]

    def normal_navi(self, request: object) -> None:
        self.normal_navi_calls += 1
        self.last_request = request


class _TimeoutPnc:
    def __init__(self) -> None:
        self._canceled = False
        self.normal_navi_calls = 0
        self.cancel_task_calls: list[int] = []
        self.last_request: object | None = None

    def get_task_state(self) -> _FakeTask:
        if self.normal_navi_calls == 0:
            return _FakeTask(0, task_id=42, message="idle")
        if self._canceled:
            return _FakeTask(7, task_id=42, message="canceled")
        return _FakeTask(2, task_id=42, message="running")

    def normal_navi(self, request: object) -> None:
        self.normal_navi_calls += 1
        self.last_request = request

    def cancel_task(self, task_id: int) -> None:
        self.cancel_task_calls.append(task_id)
        self._canceled = True


class _FakeSlam:
    def __init__(self, odom: object | None = None) -> None:
        self.odom = odom or SimpleNamespace(loc_state=1, loc_confidence=100)

    def get_odom_info(self) -> object:
        return self.odom


class _FakeAgibotGDK:
    class GDKRes:
        kSuccess = 0

    class NaviReq:
        def __init__(self) -> None:
            self.target = SimpleNamespace(
                position=SimpleNamespace(x=0.0, y=0.0, z=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            )
            self.timestamp_ns = 0

    class CameraType:
        kHeadColor = "kHeadColor"
        kHeadStereoLeft = "kHeadStereoLeft"
        kHeadStereoRight = "kHeadStereoRight"
        kHeadDepth = "kHeadDepth"
        kHandLeftColor = "kHandLeftColor"
        kHandRightColor = "kHandRightColor"

    def __init__(
        self,
        pnc: object | None = None,
        map_item: object | None = None,
        slam: object | None = None,
        camera_factory: object | None = None,
    ) -> None:
        self.pnc = pnc or _FakePnc()
        self.map_item = map_item
        self.slam = slam or _FakeSlam()
        self.camera_factory = camera_factory
        self.map_calls = 0
        self.gdk_release_calls = 0

    def gdk_init(self) -> int:
        return self.GDKRes.kSuccess

    def gdk_release(self) -> None:
        self.gdk_release_calls += 1

    def Pnc(self) -> _FakePnc:
        return self.pnc

    def Map(self) -> object:
        self.map_calls += 1
        return _FakeMap(self.map_item)

    def Slam(self) -> object:
        return self.slam

    def Camera(self) -> object:
        if self.camera_factory is None:
            raise AssertionError("unexpected Camera() call")
        return self.camera_factory()


class _FakeMap:
    def __init__(self, item: object | None) -> None:
        self.item = item

    def get_curr_map(self) -> object | None:
        return self.item


class _FakeCameraFactory:
    def __init__(self, *, missing_numpy: bool = False, events: list[str] | None = None) -> None:
        self.missing_numpy = missing_numpy
        self.events = events if events is not None else []

    def __call__(self) -> object:
        self.events.append("camera_created")
        return _FakeCamera(self.events, missing_numpy=self.missing_numpy)


class _FakeCamera:
    def __init__(self, events: list[str], *, missing_numpy: bool) -> None:
        self.events = events
        self.missing_numpy = missing_numpy

    def get_image_shape(self, camera_type: object) -> tuple[int, int]:
        return (640, 400)

    def get_image_fps(self, camera_type: object) -> float:
        return 30.0

    def get_latest_image(self, camera_type: object, timeout_ms: float) -> object:
        self.events.append("get_latest_image")
        if self.missing_numpy:
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        return SimpleNamespace(
            timestamp_ns=123,
            width=640,
            height=400,
            encoding=SimpleNamespace(name="JPEG"),
            color_format=SimpleNamespace(name="RGB"),
            bit_depth=8,
            data=_FakeImageData(b"\xff\xd8fake-jpeg\xff\xd9"),
        )

    def close_camera(self) -> int:
        self.events.append("close_camera")
        return _FakeAgibotGDK.GDKRes.kSuccess


class _FakeImageData:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.shape = (len(payload),)

    def tobytes(self) -> bytes:
        return self.payload


def _run_sdk(*args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, str(SDK_RUNNER_PATH), *args],
        cwd=SDK_RUNNER_PATH.parent.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def _run_sdk_allowing_failure(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SDK_RUNNER_PATH), *args],
        cwd=SDK_RUNNER_PATH.parent.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
