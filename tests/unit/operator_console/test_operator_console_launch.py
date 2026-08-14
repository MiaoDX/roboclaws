from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launcher import (
    route_readiness,
)
from roboclaws.operator_console.locks import ResourceLock, ResourceLockError
from roboclaws.operator_console.routes import (
    get_selection,
)
from tests.support.b1_robot_proof import write_b1_readiness_fixtures
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
    KIMI_ENV,
    _console_server,
    _free_port,
)


def test_console_readiness_omits_isaac_marker_diagnostic_but_keeps_locks_blocking(
    tmp_path: Path,
) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    b1_overrides = write_b1_readiness_fixtures(tmp_path)
    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port(), **b1_overrides},
        env=KIMI_ENV,
    )
    assert readiness["can_start"] is True
    assert readiness["blocker_kind"] == ""
    assert {gate["id"] for gate in readiness["gates"]} == {
        "provider_key",
        "mcp_port_free",
    }

    lock = ResourceLock(tmp_path, route.lock_name)
    lock.acquire(run_id="active", pid=os.getpid())
    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port(), **b1_overrides},
        env=KIMI_ENV,
    )
    assert readiness["can_start"] is False
    assert "Backend lock is held" in readiness["blocker"]


def test_console_readiness_uses_provider_profile_override(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port(), "provider_profile": "minimax-responses"},
        env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "minimax-responses"
    assert readiness["provider"]["model"] == "MiniMax-M3"


def test_resource_lock_prevents_conflicting_starts(tmp_path: Path) -> None:
    lock = ResourceLock(tmp_path, "molmospaces_mujoco")
    first = lock.acquire(run_id="run-a", pid=os.getpid())
    assert first.held is True
    assert first.owner_run_id == "run-a"

    with pytest.raises(ResourceLockError):
        lock.acquire(run_id="run-b", pid=os.getpid())

    lock.release(run_id="run-a")
    assert lock.read().held is False


def test_operator_console_next_goal_autostarts_ready_followup(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "parent-run"
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
                "provider_profile": "minimax-responses",
                "mcp_host": "127.0.0.1",
                "mcp_port": 19888,
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
    (run_dir / "run_result.json").write_text(
        json.dumps({"cleanup_success": True}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")

    launched: dict[str, object] = {}

    def fake_start(root, request):  # noqa: ANN001, ANN202
        launched["root"] = root
        launched["request"] = request
        return {"run_id": "child-run"}

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/next-goal",
            method="POST",
            data=json.dumps({"prompt": "Run the next sweep"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with patch("roboclaws.operator_console.server.start_console_run", fake_start):
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

    assert payload["status"] == "started"
    assert payload["started_run"]["run_id"] == "child-run"
    launch_request = launched["request"]
    assert launch_request.selection_id_override == route.id
    assert launch_request.intent_id == "open-ended"
    assert launch_request.operator_session_id == "session-test"
    assert launch_request.parent_run_id == run_id
    assert launch_request.overrides == {
        "host": "127.0.0.1",
        "port": "19888",
        "provider_profile": "minimax-responses",
    }
    assert launch_request.next_goal_packet["operator_session_id"] == "session-test"
    assert launch_request.next_goal_packet["parent_run_id"] == run_id
    assert "parent_public_summary" in launch_request.next_goal_packet
