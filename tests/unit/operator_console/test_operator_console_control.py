from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.routes import (
    get_selection,
)
from roboclaws.operator_console.state import (
    derive_operator_state,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_CLEANUP,
    AGIBOT_SDK_MAP_BUILD,
    AGIBOT_SDK_OPEN_TASK,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_CLEANUP,
    B1_OPENAI_AGENTS_MAP_BUILD,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)
from tests.unit.operator_console.operator_console_support import (
    _assert_allowlisted_operator_control_response,
    _assert_operator_control_artifacts,
    _blocked_operator_control_payload,
    _console_server,
    _exercise_allowlisted_operator_control,
    _write_running_operator_control_state,
)


def test_operator_console_resume_endpoint_records_paused_handoff_request(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "paused-handoff-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "operator_session_id": "session-test",
                "selected_intent": "open-ended",
                "route": route.to_payload(),
                "phase": "paused",
                "reason": "operator_handoff_requested",
                "resume_available": True,
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    session_dir = tmp_path / "output" / "operator-console" / "sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "session-test.json").write_text(
        json.dumps(
            {
                "schema": "operator_console_session_v1",
                "operator_session_id": "session-test",
                "created_at_epoch": 1,
                "created_at": "2026-06-09T00:00:00Z",
                "active_run_id": run_id,
                "run_ids": [run_id],
                "message_ids": [],
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/resume",
            method="POST",
            data=json.dumps({"prompt": "Manual control finished; continue."}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["command_type"] == "resume_with_prompt"
    assert payload["status"] == "queued"
    assert payload["delivery"]["transport"] == "runner_owned_paused_handoff_resume"
    assert payload["resume_request_packet"]["schema"] == (
        "operator_console_resume_request_packet_v1"
    )
    rows = (run_dir / "operator_resume_requests.jsonl").read_text(encoding="utf-8")
    assert "Manual control finished; continue." in rows


def test_operator_console_control_endpoint_is_allowlisted_and_records_operator_rows(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "control-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)

    payload, blocked_payload, large_payload = _exercise_allowlisted_operator_control(
        tmp_path,
        run_id,
    )

    _assert_allowlisted_operator_control_response(payload, blocked_payload, large_payload)
    _assert_operator_control_artifacts(tmp_path, run_dir, route)


def test_operator_console_control_endpoint_rejects_malformed_control_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-control-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    (run_dir / "operator_control.jsonl").write_text("\n{not-json}\n", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator control source contains invalid JSON" in payload["error"]
    assert "operator_control.jsonl:2" in payload["error"]
    assert (run_dir / "operator_control.jsonl").read_text(encoding="utf-8") == "\n{not-json}\n"


def test_operator_console_control_endpoint_rejects_non_object_control_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-control-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    (run_dir / "operator_control.jsonl").write_text("[]\n", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator control source row must be an object" in payload["error"]
    assert "operator_control.jsonl:1" in payload["error"]
    assert (run_dir / "operator_control.jsonl").read_text(encoding="utf-8") == "[]\n"


def test_operator_console_control_endpoint_rejects_malformed_operator_state_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-control-state-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("{not-json", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator state source contains invalid JSON" in payload["error"]
    assert "operator_state.json" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "{not-json"
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_non_object_operator_state_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-control-state-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("[]\n", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator state source must be a JSON object" in payload["error"]
    assert "operator_state.json" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "[]\n"
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_does_not_overwrite_corrupt_state_after_tool_call(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "corrupt-control-state-after-call-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    state_path = run_dir / "operator_state.json"

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "observe"
        assert arguments == {}
        state_path.write_text("{corrupt-after-call", encoding="utf-8")
        return {"ok": True, "tool": action, "status": "ok"}

    with _console_server(tmp_path) as (host, port):
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            payload = _blocked_operator_control_payload(
                host,
                port,
                run_id,
                {"action": "observe"},
            )

    assert "operator state source contains invalid JSON" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "{corrupt-after-call"
    rows = [
        json.loads(line)
        for line in (run_dir / "operator_control.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in rows] == ["request", "response"]
    assert not (run_dir / "operator_interventions.json").exists()


def test_operator_console_control_endpoint_allows_paused_operator_handoff(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "handoff-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "paused",
                "reason": "operator_handoff_requested",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "observe"
        assert arguments == {}
        return {
            "ok": True,
            "tool": action,
            "status": "ok",
            "visible_object_detections": [],
        }

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/control",
            method="POST",
            data=json.dumps({"action": "observe"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

    assert payload["ok"] is True
    state = derive_operator_state(tmp_path, run_dir, route)
    assert state["phase"] == "paused"
    assert state["controls"]["relative_navigation_control_available"] is True
    assert state["controls"]["next_goal_available"] is False
    assert state["latest_operator_control"]["action"] == "observe"


def test_operator_console_control_endpoint_waits_for_mcp_ready(
    tmp_path: Path,
) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    run_id = "starting-control-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert payload["error"] == "manual control is waiting for the MCP endpoint to become ready"
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_unsupported_route(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_MAP_BUILD)
    run_id = "map-build-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/control",
            method="POST",
            data=json.dumps({"action": "observe"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 409
    assert payload["error"] == "route does not support relative navigation control"


def test_operator_console_control_endpoint_rejects_terminal_run(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "finished-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "finished",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/control",
            method="POST",
            data=json.dumps({"action": "observe"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 409
    assert payload["error"] == "terminal run cannot be controlled"


def test_operator_console_stop_endpoint_decodes_browser_encoded_run_id(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = (
        "20260610-224107-molmospaces-procthor-objaverse-val-0-mujoco-open-task-"
        "openai-agents-sdk-world-public-labels"
    )
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    attempt_dir = run_dir / "0610_2241" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 99999999,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{urllib.parse.quote(run_id, safe='')}/stop",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with (
            patch("roboclaws.operator_console.launch_lifecycle._stop_live_child_run"),
            patch("roboclaws.operator_console.launch_lifecycle._terminate_process_group"),
        ):
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

    assert payload["run_id"] == run_id
    assert payload["phase"] == "stopped_by_operator"
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_operator_console_stop_endpoint_rejects_non_object_operator_state_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-stop-state-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("[]\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/stop",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 400
    assert "operator stop source error" in payload["error"]
    assert "operator_state.json must contain a JSON object" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "[]\n"
    assert ResourceLock(tmp_path, route.lock_name).read().held is True


def test_operator_console_stop_endpoint_rejects_malformed_live_status_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-live-status-stop-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    attempt_dir = run_dir / "0619_1112" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 99999999,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    status_path = attempt_dir / "live_status.json"
    status_path.write_text("{bad-live-status", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/stop",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with (
            patch("roboclaws.operator_console.launch_lifecycle._stop_live_child_run") as stop_child,
            patch(
                "roboclaws.operator_console.launch_lifecycle._terminate_process_group"
            ) as stop_wrapper,
            pytest.raises(urllib.error.HTTPError) as exc_info,
        ):
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 400
    assert "operator stop source error" in payload["error"]
    assert "live_status.json contains invalid JSON" in payload["error"]
    assert status_path.read_text(encoding="utf-8") == "{bad-live-status"
    stop_child.assert_not_called()
    stop_wrapper.assert_not_called()
    assert ResourceLock(tmp_path, route.lock_name).read().held is True
