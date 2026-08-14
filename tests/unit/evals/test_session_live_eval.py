from __future__ import annotations

import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from roboclaws.core.operator_messages import check_operator_messages_for_mcp
from roboclaws.evals.session_live import (
    SESSION_LIVE_API_TIMEOUT_S,
    _blocked_parent_provider_result,
    _wait_for_terminal,
    run_session_live_eval,
)
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.server import (
    FOLLOW_UP_AUTOSTART_ATTEMPTS,
    FOLLOW_UP_AUTOSTART_RETRY_DELAY_S,
    ConsoleRequestHandler,
)


def test_session_live_eval_blocks_when_provider_not_ready(tmp_path: Path) -> None:
    run = run_session_live_eval(
        output_root=tmp_path,
        stamp="blocked",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        env={},
    )

    payload = json.loads(run.results_path.read_text(encoding="utf-8"))
    result = payload["results"][0]
    assert result["status"] == "blocked"
    assert result["failure_class"] == "model_or_provider_unavailable"
    assert payload["aggregate"]["blocked"] == 1


def test_session_live_parent_provider_failure_preempts_steer_grading(tmp_path: Path) -> None:
    run_dir = tmp_path / "parent" / "timestamp" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed",
                "reason": "provider_quota_failure",
                "provider_reason": "billing_limit",
                "retryable": False,
                "resume_available": False,
                "exit_status": 1,
                "detail": "private provider error detail",
            }
        ),
        encoding="utf-8",
    )

    result = _blocked_parent_provider_result(
        parent_dir=tmp_path / "parent",
        parent_state={"phase": "failed"},
        provider_profile="kimi-openai-chat",
    )

    assert result is not None
    assert result["status"] == "blocked"
    assert result["failure_class"] == "model_or_provider_unavailable"
    details = result["grader_outputs"]["session_live"]["details"]
    assert details["parent_live_status"]["reason"] == "provider_quota_failure"
    assert "detail" not in details["parent_live_status"]


def test_session_live_eval_runs_headless_console_flow_with_fake_product(
    tmp_path: Path,
) -> None:
    seen_eval_env: dict[str, str] = {}

    def fake_start(root, request):  # noqa: ANN001, ANN202
        seen_eval_env["ROBOCLAWS_SESSION_LIVE_ENV_SENTINEL"] = os.environ.get(
            "ROBOCLAWS_SESSION_LIVE_ENV_SENTINEL", ""
        )
        run_id = "parent-run" if not request.parent_run_id else "child-run"
        run_dir = console_output_root(root) / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "operator_session_id": request.operator_session_id or "session-test",
            "parent_run_id": request.parent_run_id,
            "next_goal_packet": request.next_goal_packet or {},
            "phase": "finished" if request.parent_run_id else "running",
            "status": "done" if request.parent_run_id else "running",
            "selected_intent": request.intent_id or "open-ended",
            "route": get_selection(request.selection_id_override).to_payload(),
            "agent_kickoff_prompt": (
                "Operator Session follow-up context "
                f"{request.operator_session_id} {request.parent_run_id} "
                "parent_public_summary artifact_scope"
                if request.parent_run_id
                else "parent prompt"
            ),
        }
        (run_dir / "operator_state.json").write_text(json.dumps(state), encoding="utf-8")
        if not request.parent_run_id:
            threading.Thread(
                target=_consume_parent_steer_then_finish,
                args=(run_dir, state),
                daemon=True,
            ).start()
        else:
            (run_dir / "run_result.json").write_text(
                json.dumps({"task_intent": "open-ended", "status": "passed"}),
                encoding="utf-8",
            )
            (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
        return state

    def start_server(root: Path) -> ThreadingHTTPServer:
        return ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args, **kwargs: ConsoleRequestHandler(*args, root=root, **kwargs),
        )

    env = {
        "KIMI_API_KEY": "key",
        "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
        "ROBOCLAWS_SESSION_LIVE_MCP_PORT": "19888",
        "ROBOCLAWS_SESSION_LIVE_ENV_SENTINEL": "visible-to-console",
    }
    with (
        patch("roboclaws.evals.session_live.importlib.util.find_spec", return_value=object()),
        patch("roboclaws.operator_console.server.start_console_run", side_effect=fake_start),
    ):
        run = run_session_live_eval(
            output_root=tmp_path,
            stamp="session",
            provider_profile="kimi-openai-chat",
            live_execution="run",
            live_timeout_s=5,
            env=env,
            start_server=start_server,
        )

    payload = json.loads(run.results_path.read_text(encoding="utf-8"))
    result = payload["results"][0]
    assert result["status"] == "passed"
    assert payload["aggregate"]["passed"] == 1
    assert result["artifacts"]["parent_run_id"] == "parent-run"
    assert result["artifacts"]["child_run_id"] == "child-run"
    assert run.report_path.exists()
    assert os.environ.get("ROBOCLAWS_OPERATOR_CONSOLE_OUTPUT_ROOT") is None
    assert seen_eval_env["ROBOCLAWS_SESSION_LIVE_ENV_SENTINEL"] == "visible-to-console"
    assert os.environ.get("ROBOCLAWS_SESSION_LIVE_ENV_SENTINEL") is None


def test_session_live_classifies_blocked_next_goal_parent_artifact_gap(
    tmp_path: Path,
) -> None:
    def fake_start(root, request):  # noqa: ANN001, ANN202
        run_id = "parent-run" if not request.parent_run_id else "child-run"
        run_dir = console_output_root(root) / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "operator_session_id": request.operator_session_id or "session-test",
            "parent_run_id": request.parent_run_id,
            "next_goal_packet": request.next_goal_packet or {},
            "phase": "running",
            "status": "running",
            "selected_intent": request.intent_id or "open-ended",
            "route": get_selection(request.selection_id_override).to_payload(),
            "agent_kickoff_prompt": "parent prompt",
        }
        (run_dir / "operator_state.json").write_text(json.dumps(state), encoding="utf-8")
        threading.Thread(
            target=_consume_parent_steer_then_finish,
            args=(run_dir, state, False),
            daemon=True,
        ).start()
        return state

    def start_server(root: Path) -> ThreadingHTTPServer:
        return ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args, **kwargs: ConsoleRequestHandler(*args, root=root, **kwargs),
        )

    env = {
        "KIMI_API_KEY": "key",
        "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
        "ROBOCLAWS_SESSION_LIVE_MCP_PORT": "19889",
    }
    with (
        patch("roboclaws.evals.session_live.importlib.util.find_spec", return_value=object()),
        patch("roboclaws.operator_console.server.start_console_run", side_effect=fake_start),
    ):
        run = run_session_live_eval(
            output_root=tmp_path,
            stamp="session-artifact-gap",
            provider_profile="kimi-openai-chat",
            live_execution="run",
            live_timeout_s=5,
            env=env,
            start_server=start_server,
        )

    payload = json.loads(run.results_path.read_text(encoding="utf-8"))
    result = payload["results"][0]
    details = result["grader_outputs"]["session_live"]["details"]

    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 1}
    assert details["next_goal"]["status"] == "blocked"
    assert details["next_goal"]["queue_reason"] == "waiting_for_parent_result_artifacts"


def test_session_live_next_goal_timeout_covers_autostart_retry_window() -> None:
    server_retry_window_s = FOLLOW_UP_AUTOSTART_ATTEMPTS * FOLLOW_UP_AUTOSTART_RETRY_DELAY_S

    assert SESSION_LIVE_API_TIMEOUT_S > server_retry_window_s


def test_session_live_waits_for_lifecycle_phase_after_product_status_passed() -> None:
    states = iter(
        [
            {"status": "passed", "phase": "running-sdk"},
            {"status": "passed", "phase": "finished", "pid": 1234},
            {"status": "passed", "phase": "finished", "pid": 1234},
        ]
    )

    with (
        patch("roboclaws.evals.session_live._api_json", side_effect=lambda *_args: next(states)),
        patch("roboclaws.evals.session_live.pid_is_active", side_effect=[True, False]),
        patch("roboclaws.evals.session_live.time.sleep"),
    ):
        terminal = _wait_for_terminal("http://console", "run-1", deadline=time.monotonic() + 1)

    assert terminal["phase"] == "finished"


def _consume_parent_steer_then_finish(
    run_dir: Path,
    state: dict[str, object],
    write_result: bool = True,
) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        messages_path = run_dir / "operator_messages.jsonl"
        if messages_path.is_file() and "queued" in messages_path.read_text(encoding="utf-8"):
            check_operator_messages_for_mcp(run_dir)
            (run_dir / "trace.jsonl").write_text(
                json.dumps({"tool": "check_operator_messages"}) + "\n",
                encoding="utf-8",
            )
            state["phase"] = "finished"
            state["status"] = "done"
            (run_dir / "operator_state.json").write_text(json.dumps(state), encoding="utf-8")
            if write_result:
                (run_dir / "run_result.json").write_text(
                    json.dumps({"task_intent": "open-ended", "status": "passed"}),
                    encoding="utf-8",
                )
                (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")
            return
        time.sleep(0.05)
