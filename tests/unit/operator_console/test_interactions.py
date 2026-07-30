from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.core.operator_messages import (
    check_operator_messages_for_mcp,
    consume_resume_request_for_runner,
    operator_message_state,
    pending_operator_message_hint,
)
from roboclaws.operator_console.interactions import (
    InteractionError,
    append_next_goal_request,
    append_resume_request,
    append_steer_message,
    attach_run_to_session,
    get_operator_session,
    list_operator_messages,
)
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from tests.unit.operator_console.conftest import (
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,  # noqa: F401  re-exported for tests
)


def _write_run(
    root: Path,
    *,
    run_id: str = "run-a",
    selection_id: str = MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    phase: str = "running-sdk",
    run_result: dict[str, object] | None = None,
    provider_profile: str = "kimi-openai-chat",
    mcp_host: str = "127.0.0.1",
    mcp_port: int = 18788,
) -> Path:
    route = get_selection(selection_id)
    run_dir = console_output_root(root) / "runs" / run_id
    run_dir.mkdir(parents=True)
    session = attach_run_to_session(root, run_id)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "operator_session_id": session["operator_session_id"],
                "route": route.to_payload(),
                "phase": phase,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
                "provider_profile": provider_profile,
                "mcp_host": mcp_host,
                "mcp_port": mcp_port,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "response",
                "tool": "observe",
                "response": {
                    "ok": True,
                    "visible_object_detections": [{"object_id": "observed_001"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    if run_result is not None:
        (run_dir / "run_result.json").write_text(json.dumps(run_result), encoding="utf-8")
        (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
    return run_dir


def test_steer_rejects_terminal_run_and_offers_next_goal(tmp_path: Path) -> None:
    _write_run(tmp_path, phase="finished", run_result={"cleanup_success": True})

    with pytest.raises(InteractionError, match="use Next Goal"):
        append_steer_message(tmp_path, "run-a", "Do not move the cup")


def test_next_goal_rejects_active_run_without_touching_steer_inbox(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")

    with pytest.raises(InteractionError, match="Use Steer"):
        append_next_goal_request(tmp_path, "run-a", "Now build the Runtime Metric Map")
    messages = list_operator_messages(tmp_path, "run-a")

    assert not any(item["command_type"] == "steer" for item in messages["messages"])
    assert not (run_dir / "next_goal_queue.jsonl").exists()
    assert not (run_dir / "continue_queue.jsonl").exists()


def test_steer_rejects_malformed_operator_state_source_without_writing_message(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")
    state_path = run_dir / "operator_state.json"
    state_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(InteractionError, match="operator state source contains invalid JSON"):
        append_steer_message(tmp_path, "run-a", "Observe the desk again")

    assert state_path.read_text(encoding="utf-8") == "{not-json"
    assert not (run_dir / "operator_messages.jsonl").exists()


def test_next_goal_rejects_non_object_operator_state_source_without_writing_queue(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path, phase="finished", run_result={"cleanup_success": True})
    state_path = run_dir / "operator_state.json"
    state_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(InteractionError, match="operator state source must be a JSON object"):
        append_next_goal_request(tmp_path, "run-a", "Run the next sweep")

    assert state_path.read_text(encoding="utf-8") == "[]\n"
    assert not (run_dir / "operator_messages.jsonl").exists()
    assert not (run_dir / "next_goal_queue.jsonl").exists()


@pytest.mark.parametrize("source", ["{not-json", "[]\n"])
def test_list_messages_preserves_passive_bad_operator_state_summary(
    tmp_path: Path,
    source: str,
) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")
    state_path = run_dir / "operator_state.json"
    state_path.write_text(source, encoding="utf-8")

    messages = list_operator_messages(tmp_path, "run-a")
    state = operator_message_state(run_dir)

    assert messages["operator_session_id"] == ""
    assert messages["messages"] == []
    assert messages["source_error"] is False
    assert state["operator_session_id"] == ""
    assert state["source_error"] is False
    assert state_path.read_text(encoding="utf-8") == source


def test_get_operator_session_rejects_malformed_session_source(tmp_path: Path) -> None:
    session = attach_run_to_session(tmp_path, "run-a")
    session_id = session["operator_session_id"]
    session_path = console_output_root(tmp_path) / "sessions" / f"{session_id}.json"
    session_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(InteractionError, match="operator session source contains invalid JSON"):
        get_operator_session(tmp_path, session_id)

    assert session_path.read_text(encoding="utf-8") == "{not-json"


def test_steer_rejects_non_object_session_source_without_writing_message(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")
    state = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    session_id = state["operator_session_id"]
    session_path = console_output_root(tmp_path) / "sessions" / f"{session_id}.json"
    session_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(InteractionError, match="operator session source must be a JSON object"):
        append_steer_message(tmp_path, "run-a", "Observe the desk again")

    assert session_path.read_text(encoding="utf-8") == "[]\n"
    assert not (run_dir / "operator_messages.jsonl").exists()


def test_get_operator_session_rejects_session_id_mismatch(tmp_path: Path) -> None:
    session = attach_run_to_session(tmp_path, "run-a")
    session_id = session["operator_session_id"]
    session_path = console_output_root(tmp_path) / "sessions" / f"{session_id}.json"
    session["operator_session_id"] = "session-other"
    session_path.write_text(json.dumps(session), encoding="utf-8")

    with pytest.raises(InteractionError, match="operator session source id mismatch"):
        get_operator_session(tmp_path, session_id)


def test_terminal_simulator_next_goal_is_ready_with_public_packet(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        phase="finished",
        run_result={"cleanup_success": True},
        provider_profile="minimax-responses",
        mcp_port=19888,
    )

    request = append_next_goal_request(tmp_path, "run-a", "Run the next sweep")

    assert request["command_type"] == "next_goal"
    assert request["status"] == "ready_to_start"
    assert request["auto_start_allowed"] is True
    assert request["queue_reason"] == "parent_terminal_and_result_available"
    assert request["operator_session_id"].startswith("session-")
    assert request["selection_id"] == MUJOCO_OPENAI_AGENTS_OPEN_TASK
    assert request["launch_overrides"] == {
        "host": "127.0.0.1",
        "port": "19888",
        "provider_profile": "minimax-responses",
    }
    assert request["next_goal_packet"]["instruction"].startswith(
        "This is a linked follow-up Robot Run"
    )


def test_failed_parent_next_goal_requires_confirmation(tmp_path: Path) -> None:
    _write_run(tmp_path, phase="failed", run_result={"cleanup_success": False})

    request = append_next_goal_request(tmp_path, "run-a", "Try the next goal")
    confirmed = append_next_goal_request(
        tmp_path,
        "run-a",
        "Try the next goal",
        confirmed=True,
    )

    assert request["command_type"] == "next_goal"
    assert request["status"] == "confirmation_required"
    assert request["auto_start_allowed"] is False
    assert request["confirmation_required"] is True
    assert request["queue_reason"] == "operator_confirmation_required_after_parent_terminal_status"
    assert confirmed["status"] == "ready_to_start"
    assert confirmed["confirmed"] is True


def test_active_steer_is_seen_only_by_check_operator_messages(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")

    steer = append_steer_message(tmp_path, "run-a", "Observe the desk again")
    before = list_operator_messages(tmp_path, "run-a")
    seen = check_operator_messages_for_mcp(run_dir)
    after = list_operator_messages(tmp_path, "run-a")

    assert steer["status"] == "queued"
    assert before["operator_message_pending"] is True
    assert seen["message_count"] == 1
    assert seen["messages"][0]["body"] == "Observe the desk again"
    assert after["operator_message_pending"] is False
    assert after["messages"][0]["status"] == "seen"


def test_paused_handoff_rejects_delayed_steer_and_records_resume_request(
    tmp_path: Path,
) -> None:
    run_dir = _write_run(tmp_path, phase="paused")
    state = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    state["reason"] = "operator_handoff_requested"
    state["resume_available"] = True
    (run_dir / "operator_state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(InteractionError, match="paused for operator handoff"):
        append_steer_message(tmp_path, "run-a", "Observe the kitchen")

    request = append_resume_request(tmp_path, "run-a", "I moved forward; continue the task")
    listed = list_operator_messages(tmp_path, "run-a")
    claimed = consume_resume_request_for_runner(run_dir)
    after = list_operator_messages(tmp_path, "run-a")

    assert request["command_type"] == "resume_with_prompt"
    assert request["status"] == "queued"
    assert request["resume_request_packet"]["schema"] == "operator_console_resume_request_packet_v1"
    assert "private_target_truth" not in json.dumps(request, ensure_ascii=False)
    assert not (run_dir / "continue_queue.jsonl").exists()
    assert listed["operator_resume_pending"] is True
    assert listed["steer_available"] is False
    assert listed["resume_available"] is True
    assert claimed["request_count"] == 1
    assert claimed["requests"][0]["status"] == "claimed"
    assert after["operator_resume_pending"] is False


def test_paused_handoff_resume_fails_loudly_for_unsupported_route(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        selection_id=(
            "agibot-g2/map-12::agibot-gdk::map-build::openai-agents-sdk::camera-grounded-labels"
        ),
        phase="paused",
    )
    state = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    state["reason"] = "operator_handoff_requested"
    (run_dir / "operator_state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(InteractionError, match="unsupported for this route"):
        append_resume_request(tmp_path, "run-a", "Continue")

    assert not (run_dir / "operator_resume_requests.jsonl").exists()


def test_operator_message_state_surfaces_malformed_source_errors(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")
    (run_dir / "operator_messages.jsonl").write_text("\n{not-json}\n", encoding="utf-8")

    messages = list_operator_messages(tmp_path, "run-a")
    state = operator_message_state(run_dir)
    seen = check_operator_messages_for_mcp(run_dir)
    hint = pending_operator_message_hint(run_dir)

    assert messages["source_error"] is True
    assert messages["source_errors"][0]["line"] == 2
    assert "invalid JSON" in messages["source_errors"][0]["message"]
    assert messages["operator_message_pending"] is False
    assert state["source_error"] is True
    assert state["pending_steer_count"] == 0
    assert seen["ok"] is False
    assert seen["status"] == "source_error"
    assert seen["error_reason"] == "operator_message_source_error"
    assert "operator_messages.jsonl" in seen["source_errors"][0]["path"]
    assert hint["operator_message_source_error"] is True
    assert (run_dir / "operator_messages.jsonl").read_text(encoding="utf-8") == "\n{not-json}\n"


def test_operator_message_state_surfaces_non_object_source_errors(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")
    (run_dir / "operator_messages.jsonl").write_text("[]\n", encoding="utf-8")

    messages = list_operator_messages(tmp_path, "run-a")
    seen = check_operator_messages_for_mcp(run_dir)

    assert messages["source_error"] is True
    assert messages["source_errors"][0]["line"] == 1
    assert messages["source_errors"][0]["message"] == "row must be a JSON object"
    assert messages["messages"] == []
    assert seen["ok"] is False
    assert seen["message_count"] == 0


def test_operator_messages_keep_valid_rows_with_source_errors(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, phase="running-sdk")
    (run_dir / "operator_messages.jsonl").write_text(
        json.dumps(
            {
                "schema": "operator_console_message_v1",
                "message_id": "msg-1",
                "command_type": "steer",
                "status": "queued",
                "body": "Observe the desk",
            }
        )
        + "\n{bad-json}\n",
        encoding="utf-8",
    )

    messages = list_operator_messages(tmp_path, "run-a")
    state = operator_message_state(run_dir)
    seen = check_operator_messages_for_mcp(run_dir)

    assert messages["source_error"] is True
    assert messages["source_errors"][0]["line"] == 2
    assert messages["source_errors"][0]["message"] == (
        "invalid JSON: Expecting property name enclosed in double quotes"
    )
    assert messages["messages"][0]["message_id"] == "msg-1"
    assert state["source_error"] is True
    assert state["pending_steer_count"] == 1
    assert seen["ok"] is False
    assert seen["message_count"] == 0
