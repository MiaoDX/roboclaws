from __future__ import annotations

import json
import os
import socket
import threading
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launcher import (
    ConsoleLaunchError,
    LaunchRequest,
    route_readiness,
    start_console_run,
)
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.server import ConsoleRequestHandler, _follow_up_launch_request

CODEX_ENV = {
    "CODEX_BASE_URL": "https://codex.example.test/v1",
    "CODEX_API_KEY": "key",
}

from tests.unit.operator_console.conftest import MUJOCO_OPENAI_AGENTS_OPEN_TASK  # noqa: F401  re-exported for tests


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


@contextmanager
def _console_server(root: Path):
    handler = partial(ConsoleRequestHandler, root=root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _write_session(root: Path, run_id: str) -> None:
    session_dir = root / "output" / "operator-console" / "sessions"
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


def _post_next_goal(host: str, port: int, run_id: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://{host}:{port}/api/runs/{run_id}/next-goal",
        method="POST",
        data=json.dumps({"prompt": "Run the next sweep"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def test_followup_launch_request_uses_route_registry_for_selection_axes() -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    request = _follow_up_launch_request(
        "parent-run",
        {
            "selection_id": route.id,
            "body": "Run the next sweep",
            "operator_session_id": "session-test",
            "next_goal_packet": {"schema": "operator_console_next_goal_packet_v1"},
        },
    )

    assert request.selection_id_override == route.id
    assert request.selection_id == route.id
    assert request.intent_id == route.intent_id
    assert request.world_id == route.world_id
    assert request.backend_id == route.backend_id
    assert request.agent_engine_id == route.agent_engine_id
    assert request.evidence_lane == route.evidence_lane
    assert request.prompt == "Run the next sweep"
    assert request.operator_session_id == "session-test"
    assert request.parent_run_id == "parent-run"


def test_followup_launch_request_rejects_unknown_selection_id() -> None:
    with pytest.raises(KeyError):
        _follow_up_launch_request(
            "parent-run",
            {
                "selection_id": "unknown::selection",
                "body": "Run the next sweep",
            },
        )


def test_launcher_sanitizes_followup_context_for_child_prompt(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    class FakeProcess:
        pid = 12345

    with patch("roboclaws.operator_console.launcher.subprocess.Popen", return_value=FakeProcess()):
        state = start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                intent_id="open-ended",
                prompt="收拾桌面上的杯子",
                parent_run_id="parent-run",
                next_goal_packet={
                    "schema": "operator_console_next_goal_packet_v1",
                    "operator_session_id": "session-test",
                    "parent_run_id": "parent-run",
                    "parent_public_summary": {"status": "done"},
                    "artifact_scope": [{"label": "Report", "href": "/artifacts/report.html"}],
                    "generated_mess_set": ["private"],
                    "generated_mess_truth": ["private"],
                    "acceptable_destination_sets": {"cup": ["private"]},
                    "private_scorer_truth": {"must_not": "persist"},
                },
                overrides={"port": _free_port()},
            ),
            env=CODEX_ENV,
        )

    assert state["parent_run_id"] == "parent-run"
    assert state["next_goal_packet"]["schema"] == "operator_console_next_goal_packet_v1"
    assert "parent-run" in state["agent_kickoff_prompt"]
    assert "Operator Session follow-up context" in state["agent_kickoff_prompt"]
    assert "operator_session_context_json=" in " ".join(state["argv"])
    for private_term in (
        "generated_mess_set",
        "generated_mess_truth",
        "acceptable_destination_sets",
        "private_scorer_truth",
    ):
        assert private_term not in state["next_goal_packet"]
        assert private_term not in state["agent_kickoff_prompt"]


def test_readiness_releases_lock_when_parent_result_finished_before_live_status(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "result-finished-wrapper-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0629_0845" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": os.getpid(),
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_surface": "household-world",
                "task_intent": "open-ended",
                "intent_status": "success",
                "goal_status": "success",
                "final_status": "success",
                "terminate_reason": "parent finished from public result",
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=os.getpid())

    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=CODEX_ENV)

    assert readiness["can_start"] is True
    assert readiness["blocker_kind"] == ""
    assert readiness["attachable_run"] is None
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_next_goal_autostart_retries_visual_slot_wind_down(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "parent-visual-slot-wind-down"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "operator_session_id": "session-test",
                "selected_intent": "open-ended",
                "route": route.to_payload(),
                "phase": "finished",
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    _write_session(tmp_path, run_id)
    (run_dir / "run_result.json").write_text(
        json.dumps({"cleanup_success": True}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
    attempts = 0

    def fake_start(root, request):  # noqa: ANN001, ANN202
        del root, request
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConsoleLaunchError(
                "Background task visual-slot:1 is using Molmo visual slot 1 and 127.0.0.1:59777."
            )
        return {"run_id": "child-run"}

    with _console_server(tmp_path) as (host, port):
        with (
            patch("roboclaws.operator_console.server.FOLLOW_UP_AUTOSTART_ATTEMPTS", 2),
            patch("roboclaws.operator_console.server.FOLLOW_UP_AUTOSTART_RETRY_DELAY_S", 0),
            patch("roboclaws.operator_console.server.start_console_run", fake_start),
        ):
            payload = _post_next_goal(str(host), int(port), run_id)

    assert payload["status"] == "started"
    assert payload["started_run"]["run_id"] == "child-run"
    assert payload["autostart_attempts"] == 2
    assert "start_error" not in payload


def test_next_goal_autostart_releases_parent_lock_during_live_status_wind_down(
    tmp_path: Path,
) -> None:
    mcp_port = int(_free_port())
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "parent-wind-down-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    display_dir = run_dir / "0629_0845" / "seed-7"
    display_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "operator_session_id": "session-test",
                "selected_intent": "open-ended",
                "route": route.to_payload(),
                "phase": "starting",
                "pid": os.getpid(),
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    _write_session(tmp_path, run_id)
    (display_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_surface": "household-world",
                "task_intent": "open-ended",
                "intent_status": "success",
                "goal_status": "success",
                "final_status": "success",
                "terminate_reason": "parent finished from public result",
            }
        ),
        encoding="utf-8",
    )
    (display_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=os.getpid())

    class FakeProcess:
        pid = 12345

    with (
        patch.dict(os.environ, CODEX_ENV),
        patch("roboclaws.operator_console.readiness.DEFAULT_MCP_PORT", mcp_port),
        patch("roboclaws.operator_console.runtime_inventory.DEFAULT_MCP_PORT", mcp_port),
        patch("roboclaws.operator_console.launcher.subprocess.Popen", return_value=FakeProcess()),
        _console_server(tmp_path) as (host, port),
    ):
        payload = _post_next_goal(str(host), int(port), run_id)

    assert payload["status"] == "started"
    assert payload["started_run"]["parent_run_id"] == run_id
    lock = ResourceLock(tmp_path, route.lock_name).read()
    assert lock.owner_run_id == payload["started_run"]["run_id"]
