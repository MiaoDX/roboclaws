from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.contract.agibot.agibot_map_context_scripts_support import (
    SDK_RUNNER_PATH,
    _completed_context,
    _FakeAgibotGDK,
    _FakeCameraFactory,
    _FakeSlam,
    _load_module,
    _require_agibot_sdk_runner,
    _run_sdk,
    _run_sdk_allowing_failure,
    _TimeoutPnc,
)


def test_sdk_runner_writes_three_reviewable_dry_run_reports(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")
    root = tmp_path / "sdk-runner"
    agent_view_dir = root / "01-agent-view"
    observe_dir = root / "02-observe"
    navigate_dir = root / "03-navigate"

    _run_sdk(
        "agent-view",
        "--context-json",
        str(context_path),
        "--output-dir",
        str(agent_view_dir),
    )
    _run_sdk(
        "observe",
        "--agent-view-json",
        str(agent_view_dir / "agent_view.json"),
        "--output-dir",
        str(observe_dir),
    )
    _run_sdk(
        "navigate-waypoint",
        "--agent-view-json",
        str(agent_view_dir / "agent_view.json"),
        "--output-dir",
        str(navigate_dir),
        "--waypoint-id",
        "wp_sofa_front",
    )

    agent_view = json.loads((agent_view_dir / "agent_view.json").read_text(encoding="utf-8"))
    navigate_result = json.loads((navigate_dir / "run_result.json").read_text(encoding="utf-8"))

    for report in (
        agent_view_dir / "report.html",
        observe_dir / "report.html",
        navigate_dir / "report.html",
    ):
        text = report.read_text(encoding="utf-8")
        assert "AgiBot SDK Runner Report" in text
        assert len(text) > 1000

    assert "source_agibot_map" not in json.dumps(agent_view).lower()
    assert "current_agibot_map" not in json.dumps(agent_view).lower()
    assert "map_source" not in json.dumps(agent_view)
    assert "verification" not in json.dumps(agent_view)
    assert navigate_result["tool_response"]["navigation_status"] == "dry_run_not_executed"
    assert navigate_result["tool_response"]["primitive_provenance"] == "blocked_capability"


def test_sdk_runner_blocks_unverified_waypoint_before_dry_run_navigation(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    context = _completed_context()
    context["inspection_waypoints"][0]["reachability_status"] = "unverified"
    context["inspection_waypoints"][0].pop("verification")
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")
    root = tmp_path / "sdk-runner"
    agent_view_dir = root / "01-agent-view"
    navigate_dir = root / "03-navigate"

    _run_sdk(
        "agent-view",
        "--context-json",
        str(context_path),
        "--output-dir",
        str(agent_view_dir),
    )
    proc = _run_sdk_allowing_failure(
        "navigate-waypoint",
        "--agent-view-json",
        str(agent_view_dir / "agent_view.json"),
        "--output-dir",
        str(navigate_dir),
        "--waypoint-id",
        "wp_sofa_front",
    )
    navigate_result = json.loads((navigate_dir / "run_result.json").read_text(encoding="utf-8"))

    assert proc.returncode == 2
    assert navigate_result["status"] == "blocked_capability"
    assert navigate_result["tool_response"]["failure_type"] == "waypoint_not_pnc_verified"
    assert navigate_result["tool_response"]["navigation_status"] == "blocked"


def test_sdk_runner_agent_view_source_rejects_non_object_json(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    agent_view_path = tmp_path / "agent_view.json"
    agent_view_path.write_text("[]\n", encoding="utf-8")

    proc = _run_sdk_allowing_failure(
        "navigate-waypoint",
        "--agent-view-json",
        str(agent_view_path),
        "--output-dir",
        str(tmp_path / "navigate"),
        "--waypoint-id",
        "wp_sofa_front",
    )

    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert "Agibot SDK agent view source must contain a JSON object" in proc.stderr
    assert str(agent_view_path) in proc.stderr


def test_sdk_runner_map_artifact_source_rejects_malformed_json(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")
    artifact_dir = tmp_path / "agibot"
    artifact_dir.mkdir()
    (artifact_dir / "occupancy.pgm").write_bytes(b"P2\n1 1\n255\n0\n")
    (artifact_dir / "nav2.yaml").write_text(
        "image: occupancy.pgm\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n",
        encoding="utf-8",
    )
    source_path = artifact_dir / "source.json"
    source_path.write_text("{bad json\n", encoding="utf-8")

    proc = _run_sdk_allowing_failure(
        "agent-view",
        "--context-json",
        str(context_path),
        "--output-dir",
        str(tmp_path / "agent-view"),
        "--agibot-map-artifact-dir",
        str(artifact_dir),
    )

    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert "Agibot SDK map artifact metadata source must contain valid JSON object" in proc.stderr
    assert str(source_path) in proc.stderr


def test_sdk_runner_successful_mocked_gdk_navigation_records_normal_navi(
    monkeypatch, tmp_path: Path
) -> None:
    _require_agibot_sdk_runner()
    runner = _load_module(SDK_RUNNER_PATH, "run_agibot_cleanup_backend_mocked_success")
    waypoint = runner._metric_map_from_context(_completed_context(), map_artifacts={})[
        "inspection_waypoints"
    ][0]
    fake_gdk = _FakeAgibotGDK()

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(runner, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(runner, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    response = runner._execute_waypoint_navigation(
        waypoint=waypoint,
        context_json=None,
        output_dir=tmp_path,
        robot_host="127.0.0.1",
        init_wait_s=0.0,
        timeout_s=1.0,
        poll_s=0.0,
        arrival_observe=False,
        image_timeout_ms=1.0,
    )

    assert response["ok"] is True
    assert response["navigation_status"] == "succeeded"
    assert response["navigation_backend"] == "agibot_gdk"
    assert response["primitive_provenance"] == "agibot_gdk_normal_navi"
    assert response["pose_source"] == "agibot_gdk_pnc_arrival"
    assert response["navi_request"]["sent"] is True
    assert response["navi_request"]["not_sent"] is False
    assert fake_gdk.pnc.normal_navi_calls == 1
    assert fake_gdk.gdk_release_calls == 1


def test_sdk_runner_camera_observation_uses_vendor_camera_then_sleep_order(
    monkeypatch, tmp_path: Path
) -> None:
    _require_agibot_sdk_runner()
    runner = _load_module(SDK_RUNNER_PATH, "run_agibot_cleanup_backend_mocked_camera_order")
    events: list[str] = []
    fake_gdk = _FakeAgibotGDK(camera_factory=_FakeCameraFactory(events=events))

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(runner, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(runner, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: events.append(f"sleep:{seconds}"))

    response = runner._execute_camera_observation(
        output_dir=tmp_path,
        camera_name="head_color",
        robot_host="127.0.0.1",
        init_wait_s=3.0,
        image_timeout_ms=1000.0,
    )

    assert response["ok"] is True
    assert response["primitive_provenance"] == "agibot_gdk_head_color_camera"
    assert response["camera_artifact"] == "head_color.jpg"
    assert events == ["camera_created", "sleep:3.0", "get_latest_image", "close_camera"]
    assert fake_gdk.gdk_release_calls == 1
    assert (tmp_path / "head_color.jpg").read_bytes().startswith(b"\xff\xd8")


def test_sdk_runner_camera_observation_fails_loudly_on_missing_numpy(
    monkeypatch, tmp_path: Path
) -> None:
    _require_agibot_sdk_runner()
    runner = _load_module(SDK_RUNNER_PATH, "run_agibot_cleanup_backend_mocked_camera_numpy")
    fake_gdk = _FakeAgibotGDK(camera_factory=_FakeCameraFactory(missing_numpy=True))

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(runner, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(runner, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    with pytest.raises(ModuleNotFoundError, match="numpy"):
        runner._execute_camera_observation(
            output_dir=tmp_path,
            camera_name="head_color",
            robot_host="127.0.0.1",
            init_wait_s=0.0,
            image_timeout_ms=1000.0,
        )

    assert fake_gdk.gdk_release_calls == 1


def test_sdk_runner_timeout_cancels_gdk_navigation_and_records_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    _require_agibot_sdk_runner()
    runner = _load_module(SDK_RUNNER_PATH, "run_agibot_cleanup_backend_mocked_timeout")
    waypoint = runner._metric_map_from_context(_completed_context(), map_artifacts={})[
        "inspection_waypoints"
    ][0]
    fake_gdk = _FakeAgibotGDK(pnc=_TimeoutPnc())

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(runner, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(runner, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    response = runner._execute_waypoint_navigation(
        waypoint=waypoint,
        context_json=None,
        output_dir=tmp_path,
        robot_host="127.0.0.1",
        init_wait_s=0.0,
        timeout_s=0.0,
        poll_s=0.0,
        arrival_observe=False,
        image_timeout_ms=1.0,
    )

    assert response["ok"] is False
    assert response["status"] == "blocked_capability"
    assert response["failure_type"] == "timeout"
    assert response["navigation_status"] == "blocked"
    assert response["final_task"]["state_name"] == "running"
    assert response["final_task_after_cancel"]["state_name"] == "canceled"
    assert response["cancel_attempted"] is True
    assert response["cancel_task_id"] == 42
    assert response["cancel_requested"] is True
    assert response["cancel_error"] == ""
    assert fake_gdk.pnc.normal_navi_calls == 1
    assert fake_gdk.pnc.cancel_task_calls == [42]
    assert fake_gdk.gdk_release_calls == 1


def test_sdk_runner_execute_blocks_current_map_mismatch_before_normal_navi(
    monkeypatch, tmp_path: Path
) -> None:
    _require_agibot_sdk_runner()
    runner = _load_module(SDK_RUNNER_PATH, "run_agibot_cleanup_backend_mocked_map_mismatch")
    waypoint = runner._metric_map_from_context(_completed_context(), map_artifacts={})[
        "inspection_waypoints"
    ][0]
    context_path = tmp_path / "agibot_map_context.completed.json"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")
    fake_gdk = _FakeAgibotGDK(map_item=SimpleNamespace(id=99, name="wrong_map", is_curr_map=True))

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(runner, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(runner, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    response = runner._execute_waypoint_navigation(
        waypoint=waypoint,
        context_json=context_path,
        output_dir=tmp_path,
        robot_host="127.0.0.1",
        init_wait_s=0.0,
        timeout_s=1.0,
        poll_s=0.0,
        arrival_observe=False,
        image_timeout_ms=1.0,
    )

    assert response["ok"] is False
    assert response["status"] == "blocked_capability"
    assert response["failure_type"] == "map_mismatch"
    assert response["navigation_status"] == "blocked"
    assert response["map_check"]["ok"] is False
    assert response["map_check"]["expected_map_name"] == "office_floor_1"
    assert response["map_check"]["current_map_name"] == "wrong_map"
    assert fake_gdk.map_calls == 1
    assert fake_gdk.pnc.normal_navi_calls == 0
    assert fake_gdk.gdk_release_calls == 1


def test_sdk_runner_execute_blocks_missing_localization_before_normal_navi(
    monkeypatch, tmp_path: Path
) -> None:
    _require_agibot_sdk_runner()
    runner = _load_module(SDK_RUNNER_PATH, "run_agibot_cleanup_backend_mocked_localization_block")
    waypoint = runner._metric_map_from_context(_completed_context(), map_artifacts={})[
        "inspection_waypoints"
    ][0]
    fake_gdk = _FakeAgibotGDK(slam=_FakeSlam(odom=SimpleNamespace()))

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(runner, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(runner, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    response = runner._execute_waypoint_navigation(
        waypoint=waypoint,
        context_json=None,
        output_dir=tmp_path,
        robot_host="127.0.0.1",
        init_wait_s=0.0,
        timeout_s=1.0,
        poll_s=0.0,
        arrival_observe=False,
        image_timeout_ms=1.0,
    )

    assert response["ok"] is False
    assert response["status"] == "blocked_capability"
    assert response["failure_type"] == "gdk_localization_not_ready"
    assert response["navigation_status"] == "blocked"
    assert response["localization_check"]["report_present"] is False
    assert response["localization_check"]["pad_relocalization_required_when_not_ok"] is True
    assert "Relocalize on the G02 Pad" in response["backend_error_summary"]
    assert fake_gdk.pnc.normal_navi_calls == 0
    assert fake_gdk.gdk_release_calls == 1
