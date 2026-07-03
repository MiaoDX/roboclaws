"""Live Operator Session eval for linked SDK robot runs."""

from __future__ import annotations

import html
import importlib.util
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from roboclaws.agents.provider_registry import provider_readiness
from roboclaws.evals.models import EVAL_RESULT_SCHEMA, MISSING_NOT_APPLICABLE
from roboclaws.evals.reports import RESULTS_BUNDLE_SCHEMA
from roboclaws.operator_console.interactions import MESSAGE_LOG
from roboclaws.operator_console.paths import OUTPUT_ROOT_ENV, console_output_root
from roboclaws.operator_console.routes import ConsoleLaunchSelection, list_console_combinations
from roboclaws.operator_console.server import ConsoleRequestHandler

SESSION_LIVE_SUITE_SCHEMA = "roboclaws_session_live_eval_suite_v1"
SESSION_LIVE_RUN_SCHEMA = "roboclaws_session_live_eval_run_v1"
SESSION_LIVE_SAMPLE_ID = "operator_session.linked_next_goal"
SESSION_LIVE_SUITE_ID = "operator_session_live"
SESSION_LIVE_API_TIMEOUT_S = 90


@dataclass(frozen=True)
class SessionLiveRun:
    output_dir: Path
    results_path: Path
    report_path: Path
    bundle: dict[str, Any]


class SessionLiveHTTPError(RuntimeError):
    """Raised when the headless console API rejects the eval flow."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        self.method = method
        self.path = path
        self.status = status
        self.body = body
        super().__init__(f"{method} {path} failed with HTTP {status}: {body}")


StartServer = Callable[[Path], ThreadingHTTPServer]


def run_session_live_eval(
    *,
    output_root: Path,
    budget: str = "smoke",
    stamp: str | None = None,
    agent_engine: str = "openai-agents-sdk",
    provider_profile: str = "codex-router-responses",
    live_execution: str = "blocked",
    live_timeout_s: float = 900.0,
    env: dict[str, str] | None = None,
    start_server: StartServer | None = None,
) -> SessionLiveRun:
    """Run or block the headless Operator Session live eval."""

    if agent_engine != "openai-agents-sdk":
        raise ValueError("session-live requires agent_engine=openai-agents-sdk")
    if live_execution not in {"blocked", "run"}:
        raise ValueError("live_execution must be blocked or run")

    run_stamp = stamp or time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    output_dir = output_root / SESSION_LIVE_SUITE_ID / run_stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    env_map = dict(os.environ if env is None else env)
    result = _blocked_result(
        provider_profile=provider_profile,
        reason="live_execution is not run",
        failure_class="environment_blocked",
        details={"live_execution": live_execution},
    )
    if live_execution == "run":
        result = _run_live_flow(
            output_dir=output_dir,
            provider_profile=provider_profile,
            live_timeout_s=live_timeout_s,
            env=env_map,
            start_server=start_server,
        )
    bundle = _bundle(output_dir=output_dir, budget=budget, result=result)
    results_path = output_dir / "eval_results.json"
    report_path = output_dir / "eval_report.html"
    _write_json(results_path, bundle)
    report_path.write_text(_render_report(bundle), encoding="utf-8")
    bundle["artifacts"]["eval_results"] = str(results_path)
    bundle["artifacts"]["eval_report"] = str(report_path)
    _write_json(results_path, bundle)
    return SessionLiveRun(
        output_dir=output_dir,
        results_path=results_path,
        report_path=report_path,
        bundle=bundle,
    )


def _run_live_flow(
    *,
    output_dir: Path,
    provider_profile: str,
    live_timeout_s: float,
    env: dict[str, str],
    start_server: StartServer | None,
) -> dict[str, Any]:
    provider = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile=provider_profile,
        env=env,
    )
    if not provider.get("ok"):
        return _blocked_result(
            provider_profile=provider_profile,
            reason=str(provider.get("message") or "provider not ready"),
            failure_class="model_or_provider_unavailable",
            details={"provider": provider},
        )
    if importlib.util.find_spec("agents") is None:
        return _blocked_result(
            provider_profile=provider_profile,
            reason="OpenAI Agents SDK package is not importable",
            failure_class="environment_blocked",
            details={"missing_package": "agents"},
        )

    root = Path(__file__).resolve().parents[2]
    route = _session_live_route(provider_profile)
    if route is None:
        return _blocked_result(
            provider_profile=provider_profile,
            reason="no enabled operator-console OpenAI Agents SDK open-ended route",
            failure_class="environment_blocked",
            details={"route": "missing"},
        )

    previous_env_values: dict[str, str | None] = {}
    for key, value in env.items():
        if os.environ.get(key) != value:
            previous_env_values[key] = os.environ.get(key)
            os.environ[key] = value
    previous_env_values.setdefault(OUTPUT_ROOT_ENV, os.environ.get(OUTPUT_ROOT_ENV))
    os.environ[OUTPUT_ROOT_ENV] = str(output_dir / "operator-console")
    server = (start_server or _start_http_server)(root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://{server.server_address[0]}:{server.server_address[1]}"
        return _exercise_session_flow(
            root=root,
            route=route,
            base_url=base_url,
            provider_profile=provider_profile,
            deadline=time.monotonic() + live_timeout_s,
            env=env,
        )
    except SessionLiveHTTPError as exc:
        return _blocked_result(
            provider_profile=provider_profile,
            reason=str(exc),
            failure_class="environment_blocked",
            details={
                "method": exc.method,
                "path": exc.path,
                "status": exc.status,
                "body": exc.body,
            },
        )
    except RuntimeError as exc:
        return _failed_result(
            provider_profile=provider_profile,
            reason=str(exc),
            failure_class="harness_bug_unclassified",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for key, previous in previous_env_values.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _start_http_server(root: Path) -> ThreadingHTTPServer:
    handler = partial(ConsoleRequestHandler, root=root)
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def _session_live_route(provider_profile: str) -> ConsoleLaunchSelection | None:
    for route in list_console_combinations(include_disabled=False):
        if (
            route.agent_engine_id == "openai-agents-sdk"
            and route.intent_id == "open-ended"
            and route.backend_id == "mujoco"
            and route.evidence_lane == "world-public-labels"
            and route.supports_operator_steer
        ):
            return route
    return None


def _exercise_session_flow(
    *,
    root: Path,
    route: ConsoleLaunchSelection,
    base_url: str,
    provider_profile: str,
    deadline: float,
    env: dict[str, str],
) -> dict[str, Any]:
    session = _api_json(base_url, "POST", "/api/sessions", {})
    parent = _api_json(
        base_url,
        "POST",
        "/api/runs",
        {
            "selection_id": route.id,
            "prompt": "find something useful to drink",
            "provider_profile": provider_profile,
            "operator_session_id": session["operator_session_id"],
            "overrides": {"port": env.get("ROBOCLAWS_SESSION_LIVE_MCP_PORT") or _free_port()},
        },
    )
    parent_run_id = str(parent.get("run_id") or "")
    if not parent_run_id:
        raise RuntimeError("parent run did not return run_id")

    steer = _api_json(
        base_url,
        "POST",
        f"/api/runs/{parent_run_id}/messages",
        {"body": "Before finishing, check whether the nearest table has a drink."},
    )
    if steer.get("status") != "queued":
        raise RuntimeError("steer message was not queued")

    parent_state = _wait_for_terminal(base_url, parent_run_id, deadline=deadline)
    parent_dir = console_output_root(root) / "runs" / parent_run_id
    if not _parent_consumed_steer(parent_dir):
        raise RuntimeError("parent did not consume steer through check_operator_messages")

    next_goal = _api_json(
        base_url,
        "POST",
        f"/api/runs/{parent_run_id}/next-goal",
        {"prompt": "Now inspect one more public waypoint and report useful context."},
        timeout_s=SESSION_LIVE_API_TIMEOUT_S,
    )
    if next_goal.get("status") != "started":
        raise RuntimeError(f"Next Goal did not start child run: {next_goal.get('start_error')}")
    child = next_goal.get("started_run") if isinstance(next_goal.get("started_run"), dict) else {}
    child_run_id = str(child.get("run_id") or "")
    if not child_run_id:
        raise RuntimeError("child run did not return run_id")
    child_state = _wait_for_terminal(base_url, child_run_id, deadline=deadline)
    child_operator_state = _read_json_object(
        console_output_root(root) / "runs" / child_run_id / "operator_state.json"
    )
    _validate_child_context(
        child_state=child_operator_state,
        child_run_id=child_run_id,
        parent_run_id=parent_run_id,
        operator_session_id=str(session["operator_session_id"]),
    )
    return _passed_result(
        provider_profile=provider_profile,
        artifacts={
            "parent_run_id": parent_run_id,
            "child_run_id": child_run_id,
            "parent_state": parent_state,
            "child_state": child_state,
            "child_operator_state": child_operator_state,
            "next_goal": next_goal,
        },
    )


def _wait_for_terminal(base_url: str, run_id: str, *, deadline: float) -> dict[str, Any]:
    while time.monotonic() < deadline:
        state = _api_json(base_url, "GET", f"/api/runs/{run_id}", {})
        state_markers = {
            str(state.get("status") or "").lower(),
            str(state.get("phase") or "").lower(),
            str(state.get("terminal_reason") or "").lower(),
        }
        if state_markers & {
            "done",
            "finished",
            "passed",
            "failed",
            "stopped_by_operator",
            "human_takeover_stop",
            "emergency_stopped",
        }:
            return state
        time.sleep(1.0)
    raise RuntimeError(f"run {run_id} did not reach terminal state before timeout")


def _parent_consumed_steer(parent_dir: Path) -> bool:
    messages_path = parent_dir / MESSAGE_LOG
    if not messages_path.is_file():
        return False
    seen = False
    for line in messages_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("command_type") == "steer" and row.get("status") == "seen":
            seen = True
            break
    if not seen:
        return False
    return _trace_mentions_tool(parent_dir, "check_operator_messages")


def _trace_mentions_tool(run_dir: Path, tool_name: str) -> bool:
    for trace_path in run_dir.rglob("trace.jsonl"):
        try:
            lines = trace_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if tool_name in line:
                return True
    return False


def _validate_child_context(
    *,
    child_state: dict[str, Any],
    child_run_id: str,
    parent_run_id: str,
    operator_session_id: str,
) -> None:
    if child_state.get("run_id") != child_run_id:
        raise RuntimeError("child state run_id mismatch")
    if child_state.get("operator_session_id") != operator_session_id:
        raise RuntimeError("child did not preserve operator_session_id")
    raw_parent = str(child_state.get("parent_run_id") or "")
    if raw_parent != parent_run_id:
        raise RuntimeError("child did not preserve parent_run_id")
    packet = child_state.get("next_goal_packet")
    if not isinstance(packet, dict) or packet.get("parent_run_id") != parent_run_id:
        raise RuntimeError("child next_goal_packet missing parent_run_id")
    prompt = str(child_state.get("agent_kickoff_prompt") or "")
    required = (
        "Operator Session follow-up context",
        operator_session_id,
        parent_run_id,
        "parent_public_summary",
        "artifact_scope",
    )
    missing = [item for item in required if item not in prompt]
    if missing:
        raise RuntimeError(f"child prompt missing follow-up context: {', '.join(missing)}")
    forbidden = (
        "generated_mess_set",
        "generated_mess_truth",
        "acceptable_destination_sets",
        "private_manifest",
        "private_target_truth",
        "global_movable_object_inventory",
        "private_scorer_truth",
    )
    leaked = [item for item in forbidden if item in prompt]
    if leaked:
        raise RuntimeError(f"child prompt leaked private context: {', '.join(leaked)}")


def _api_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout_s: float = 30,
) -> dict[str, Any]:
    data = None if method == "GET" else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        method=method,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SessionLiveHTTPError(method, path, exc.code, body) from exc
    payload_out = json.loads(body)
    if not isinstance(payload_out, dict):
        raise RuntimeError(f"{method} {path} returned non-object JSON")
    return payload_out


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not contain a JSON object")
    return payload


def _blocked_result(
    *,
    provider_profile: str,
    reason: str,
    failure_class: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return _result(
        status="blocked",
        provider_profile=provider_profile,
        failure_class=failure_class,
        reason=reason,
        grader_outputs={
            "session_live": {
                "status": "blocked",
                "reason": reason,
                "details": details,
            }
        },
    )


def _failed_result(
    *,
    provider_profile: str,
    reason: str,
    failure_class: str,
) -> dict[str, Any]:
    return _result(
        status="failed",
        provider_profile=provider_profile,
        failure_class=failure_class,
        reason=reason,
        grader_outputs={"session_live": {"status": "failed", "reason": reason}},
    )


def _passed_result(*, provider_profile: str, artifacts: dict[str, Any]) -> dict[str, Any]:
    return _result(
        status="passed",
        provider_profile=provider_profile,
        failure_class=MISSING_NOT_APPLICABLE,
        reason="operator session live flow passed",
        grader_outputs={
            "session_live": {
                "status": "passed",
                "checks": [
                    "parent_started",
                    "steer_consumed",
                    "next_goal_started_child",
                    "child_prompt_received_sanitized_context",
                    "child_terminal",
                ],
            }
        },
        artifacts=artifacts,
    )


def _result(
    *,
    status: str,
    provider_profile: str,
    failure_class: str,
    reason: str,
    grader_outputs: dict[str, Any],
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": EVAL_RESULT_SCHEMA,
        "identity": {
            "schema": "roboclaws_eval_identity_v1",
            "suite_id": SESSION_LIVE_SUITE_ID,
            "suite_version": "2026-06-28",
            "sample_id": SESSION_LIVE_SAMPLE_ID,
            "sample_version": "2026-06-28",
            "trial_id": f"{SESSION_LIVE_SAMPLE_ID}.trial-0000",
            "repetition_index": 0,
            "surface": "household-world",
            "intent": "open-ended",
            "preset": "",
            "world": "operator-console-selected",
            "backend": "mujoco",
            "evidence_lane": "world-public-labels",
            "camera_labeler": "not_applicable",
            "scenario_setup": "baseline",
            "seed": 7,
            "prompt": "operator session parent steer plus next goal",
            "goal_contract_hash": "not_applicable",
            "agent_engine": "openai-agents-sdk",
            "runner_class": "live",
            "provider_profile": provider_profile,
            "model": "provider_default",
            "skill_name": "household-world",
            "prompt_source": "operator_session_live",
            "mcp_profile": "household_world",
            "tool_surface": ["metric_map", "observe", "check_operator_messages", "done"],
            "budgets": {"session_live": "smoke"},
            "runtime": {"operator_console_api": True},
            "limitations": [],
        },
        "status": status,
        "failure_class": failure_class,
        "grader_outputs": grader_outputs,
        "artifacts": dict(artifacts or {}),
        "artifact_schema_versions": {},
        "metrics": {"session_flow_reason": reason},
        "limitations": [],
    }


def _bundle(*, output_dir: Path, budget: str, result: dict[str, Any]) -> dict[str, Any]:
    aggregate = _aggregate([result])
    return {
        "schema": RESULTS_BUNDLE_SCHEMA,
        "suite": {
            "schema": SESSION_LIVE_SUITE_SCHEMA,
            "suite_id": SESSION_LIVE_SUITE_ID,
            "version": "2026-06-28",
            "capability": "operator_session_chaining",
            "sample_ids": [SESSION_LIVE_SAMPLE_ID],
            "required_graders": ["session_live"],
            "thresholds": {"pass_at_1": 1.0},
        },
        "budget": budget,
        "result_schema": EVAL_RESULT_SCHEMA,
        "aggregate": aggregate,
        "results": [result],
        "artifacts": {"output_dir": str(output_dir)},
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.get("status") == "passed")
    failed = sum(1 for result in results if result.get("status") == "failed")
    blocked = sum(1 for result in results if result.get("status") == "blocked")
    failure_classes: dict[str, int] = {}
    for result in results:
        failure_class = str(result.get("failure_class") or "")
        if failure_class and failure_class != MISSING_NOT_APPLICABLE:
            failure_classes[failure_class] = failure_classes.get(failure_class, 0) + 1
    return {
        "total": total,
        "trial_count": total,
        "sample_count": 1,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "pass_at_1": float(passed) / float(total or 1),
        "failure_classes": failure_classes,
    }


def _render_report(bundle: dict[str, Any]) -> str:
    result = bundle["results"][0]
    identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Roboclaws Eval - Operator Session Live</title>
</head>
<body>
  <h1>Operator Session Live</h1>
  <p>Status: <strong>{html.escape(str(result.get("status") or ""))}</strong></p>
  <p>Provider: {html.escape(str(identity.get("provider_profile") or ""))}</p>
  <p>Failure: {html.escape(str(result.get("failure_class") or ""))}</p>
  <pre>{html.escape(json.dumps(result.get("grader_outputs") or {}, indent=2, sort_keys=True))}</pre>
</body>
</html>
"""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
