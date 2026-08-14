"""Operator-session and message artifacts for the local console."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.core.operator_messages import (
    MESSAGE_LOG,
    RESUME_REQUEST_LOG,
    read_operator_message_rows,
    read_operator_resume_rows,
)
from roboclaws.operator_console.context_packets import (
    sanitize_operator_context_packet,
    strip_private_payload,
)
from roboclaws.operator_console.launch_support import launch_overrides_from_run_state
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import ConsoleLaunchSelection, get_selection
from roboclaws.operator_console.state import (
    derive_operator_state,
    resolve_display_run_dir,
)
from roboclaws.operator_console.state_summary import is_terminal_run_phase

SESSION_SCHEMA = "operator_console_session_v1"
MESSAGE_SCHEMA = "operator_console_message_v1"
SESSION_LOG = "sessions.jsonl"
SESSION_DIR = "sessions"
NEXT_GOAL_QUEUE = "next_goal_queue.jsonl"


class InteractionError(ValueError):
    """User-facing interaction validation error."""


class UnknownOperatorSessionError(InteractionError):
    """Raised when an operator session record is missing."""


def create_operator_session(root: Path) -> dict[str, Any]:
    """Create a durable operator session record."""

    session_id = _new_id("session")
    now = _utc_now()
    payload = {
        "schema": SESSION_SCHEMA,
        "operator_session_id": session_id,
        "created_at_epoch": now,
        "created_at": _format_epoch(now),
        "active_run_id": "",
        "run_ids": [],
        "message_ids": [],
    }
    path = _session_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _append_jsonl(_session_log_path(root), payload)
    return payload


def get_operator_session(root: Path, session_id: str) -> dict[str, Any]:
    payload = _read_session_json(_session_path(root, session_id), session_id=session_id)
    if not payload:
        raise UnknownOperatorSessionError(f"unknown operator session: {session_id}")
    return payload


def attach_run_to_session(root: Path, run_id: str, session_id: str = "") -> dict[str, Any]:
    """Attach a run to an existing or new operator session."""

    session = (
        get_operator_session(root, session_id) if session_id else create_operator_session(root)
    )
    run_ids = list(session.get("run_ids") or [])
    if run_id not in run_ids:
        run_ids.append(run_id)
    session["run_ids"] = run_ids
    session["active_run_id"] = run_id
    _write_session(root, session)
    return session


def append_steer_message(root: Path, run_id: str, body: str) -> dict[str, Any]:
    """Append an active-run steering message for routes that support the MCP inbox."""

    body = _clean_text(body)
    if not body:
        raise InteractionError("Steer Current Run requires message text.")
    run_dir, route, run_state = _run_context(root, run_id, strict=True)
    state = derive_operator_state(root, run_dir, route)
    if _is_terminal_state(state):
        raise InteractionError("Robot Run is terminal; use Next Goal instead.")
    if _is_operator_handoff_paused(state):
        raise InteractionError("Robot Run is paused for operator handoff; use Resume With Prompt.")
    if route is None or not route.supports_operator_steer:
        raise InteractionError("Steer Current Run is unavailable for this route.")
    message = _base_message(command_type="steer", run_id=run_id, body=body, status="queued")
    message["delivery"] = {
        "transport": "mcp_check_operator_messages",
        "operator_message_pending": True,
    }
    _preflight_session_source(root, run_state)
    _append_message(run_dir, message)
    _record_session_message(root, run_dir, message, run_state=run_state)
    return message


def append_resume_request(root: Path, run_id: str, prompt: str) -> dict[str, Any]:
    """Record a paused-handoff resume prompt for a route with runner-owned resume."""

    prompt = _clean_text(prompt)
    if not prompt:
        raise InteractionError("Resume With Prompt requires prompt text.")
    run_dir, route, run_state = _run_context(root, run_id, strict=True)
    state = derive_operator_state(root, run_dir, route)
    if not _is_operator_handoff_paused(state):
        raise InteractionError("Resume With Prompt is available only during operator handoff.")
    if route is None or not route.supports_paused_handoff_resume:
        raise InteractionError(
            "Resume With Prompt is unsupported for this route; stop this run or wait for a "
            "runner-owned resume implementation."
        )
    controls = state.get("controls") if isinstance(state.get("controls"), dict) else {}
    if not bool(controls.get("resume_available")):
        raise InteractionError(
            "Resume With Prompt is not available because the paused runner did not expose "
            "a resumable handoff state."
        )
    session = _session_for_run(root, run_dir, run_id, run_state=run_state)
    resume_packet = _resume_request_packet(state, session, run_id, prompt)
    message = _base_message(
        command_type="resume_with_prompt",
        run_id=run_id,
        body=prompt,
        status="queued",
    )
    message.update(
        {
            "operator_session_id": session["operator_session_id"],
            "selection_id": _state_selection_id(state),
            "intent": str(state.get("selected_intent") or ""),
            "resume_request_packet": resume_packet,
            "delivery": {
                "transport": "runner_owned_paused_handoff_resume",
                "operator_resume_pending": True,
            },
        }
    )
    _append_jsonl(run_dir / RESUME_REQUEST_LOG, message)
    _append_message(run_dir, message)
    _record_session_message(root, run_dir, message, run_state=run_state)
    return message


def append_next_goal_request(
    root: Path,
    run_id: str,
    prompt: str,
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Create a linked next-goal run request after a terminal parent."""

    prompt = _clean_text(prompt)
    if not prompt:
        raise InteractionError("Next Goal requires a goal prompt.")
    run_dir, route, run_state = _run_context(root, run_id, strict=True)
    state = derive_operator_state(root, run_dir, route)
    session = _session_for_run(root, run_dir, run_id, run_state=run_state)
    terminal = _is_terminal_state(state)
    if not terminal:
        raise InteractionError(
            "Next Goal is available after this Robot Run is terminal. "
            "Use Steer while this run is active."
        )
    requires_confirmation = _requires_next_goal_confirmation(route)
    result_available = _parent_result_available(run_dir, state)
    terminal_success = _terminal_success(state)
    status = "ready_to_start"
    if not result_available:
        reason = "waiting_for_parent_result_artifacts"
        status = "blocked"
    elif not terminal_success:
        reason = "operator_confirmation_required_after_parent_terminal_status"
        status = "ready_to_start" if confirmed else "confirmation_required"
    elif requires_confirmation:
        reason = "operator_confirmation_required"
        status = "ready_to_start" if confirmed else "confirmation_required"
    else:
        reason = "parent_terminal_and_result_available"
    message = _base_message(
        command_type="next_goal",
        run_id=run_id,
        body=prompt,
        status=status,
    )
    message.update(
        {
            "operator_session_id": session["operator_session_id"],
            "parent_run_id": run_id,
            "selection_id": _state_selection_id(state),
            "intent": str(state.get("selected_intent") or ""),
            "launch_overrides": launch_overrides_from_run_state(run_state),
            "queue_reason": reason,
            "auto_start_allowed": status == "ready_to_start",
            "confirmation_required": status == "confirmation_required",
            "confirmed": bool(confirmed),
            "next_goal_packet": _next_goal_packet(state, session, run_id, prompt),
        }
    )
    _append_jsonl(run_dir / NEXT_GOAL_QUEUE, message)
    _append_message(run_dir, message)
    _record_session_message(root, run_dir, message, run_state=run_state)
    return message


def list_operator_messages(root: Path, run_id: str) -> dict[str, Any]:
    run_dir, route, _run_state = _run_context(root, run_id)
    state = derive_operator_state(root, run_dir, route)
    messages, source_errors = read_operator_message_rows(run_dir)
    resume_requests, resume_source_errors = read_operator_resume_rows(run_dir)
    return {
        "run_id": run_id,
        "operator_session_id": _session_id_from_run_state(run_dir),
        "messages": messages,
        "source_errors": source_errors,
        "source_error": bool(source_errors),
        "resume_requests": resume_requests,
        "resume_source_errors": resume_source_errors,
        "resume_source_error": bool(resume_source_errors),
        "operator_message_pending": any(
            item.get("command_type") == "steer" and item.get("status") == "queued"
            for item in messages
        ),
        "operator_resume_pending": any(
            item.get("command_type") == "resume_with_prompt" and item.get("status") == "queued"
            for item in resume_requests
        ),
        "steer_available": bool(
            route
            and route.supports_operator_steer
            and not _is_terminal_state(state)
            and not _is_operator_handoff_paused(state)
        ),
        "resume_available": bool(
            route
            and route.supports_paused_handoff_resume
            and _is_operator_handoff_paused(state)
            and (state.get("controls") or {}).get("resume_available")
        ),
    }


def _base_message(
    *,
    command_type: str,
    run_id: str,
    body: str,
    status: str,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "schema": MESSAGE_SCHEMA,
        "message_id": _new_id(command_type),
        "command_type": command_type,
        "run_id": run_id,
        "body": body,
        "status": status,
        "created_at_epoch": now,
        "created_at": _format_epoch(now),
    }


def _next_goal_packet(
    state: dict[str, Any],
    session: dict[str, Any],
    parent_run_id: str,
    prompt: str,
) -> dict[str, Any]:
    artifacts = state.get("artifact_paths") if isinstance(state.get("artifact_paths"), list) else []
    packet = {
        "schema": "operator_console_next_goal_packet_v1",
        "operator_session_id": session["operator_session_id"],
        "parent_run_id": parent_run_id,
        "operator_prompt": prompt,
        "parent_public_summary": {
            "status": state.get("status"),
            "phase": state.get("phase"),
            "latest_action": state.get("latest_action"),
            "public_run_result": state.get("public_run_result") or {},
            "latest_public_decision_evidence": state.get("latest_public_decision_evidence") or {},
        },
        "artifact_scope": _public_artifact_scope(artifacts),
        "instruction": (
            "This is a linked follow-up Robot Run. Use only public parent context; "
            "do not mutate or reinterpret the parent run report."
        ),
    }
    return sanitize_operator_context_packet(packet)


def _resume_request_packet(
    state: dict[str, Any],
    session: dict[str, Any],
    run_id: str,
    prompt: str,
) -> dict[str, Any]:
    artifacts = state.get("artifact_paths") if isinstance(state.get("artifact_paths"), list) else []
    packet = {
        "schema": "operator_console_resume_request_packet_v1",
        "operator_session_id": session["operator_session_id"],
        "run_id": run_id,
        "operator_prompt": prompt,
        "handoff_public_summary": {
            "status": state.get("status"),
            "phase": state.get("phase"),
            "terminal_reason": state.get("terminal_reason"),
            "latest_action": state.get("latest_action"),
            "latest_operator_control": state.get("latest_operator_control") or {},
            "operator_interventions": state.get("operator_interventions") or {},
            "latest_public_decision_evidence": state.get("latest_public_decision_evidence") or {},
        },
        "artifact_scope": _public_artifact_scope(artifacts),
        "instruction": (
            "This is an explicit paused-handoff resume request for the same Robot Run. "
            "Use only public handoff context and current MCP state; do not consume queued "
            "Steer messages as resume input."
        ),
    }
    return sanitize_operator_context_packet(packet)


def _public_artifact_scope(artifacts: list[Any]) -> list[dict[str, str]]:
    allowed_labels = {
        "Operator State",
        "Report",
        "Run Result",
        "Trace",
        "Agent Events",
        "Runtime Map",
        "Actionable Map",
    }
    output: list[dict[str, str]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        if label not in allowed_labels:
            continue
        output.append(
            {
                "label": label,
                "kind": str(item.get("kind") or ""),
                "href": str(item.get("href") or ""),
                "path": str(item.get("path") or ""),
            }
        )
    return output


def _run_context(
    root: Path,
    run_id: str,
    *,
    strict: bool = False,
) -> tuple[Path, ConsoleLaunchSelection | None, dict[str, Any]]:
    if not run_id:
        raise InteractionError("run_id is required.")
    run_dir = console_output_root(root) / "runs" / run_id
    if not run_dir.is_dir():
        raise InteractionError(f"unknown run: {run_id}")
    state = (
        _read_run_state(run_dir / "operator_state.json")
        if strict
        else _read_json(run_dir / "operator_state.json")
    )
    selection_id = _state_selection_id(state)
    try:
        route = get_selection(selection_id) if selection_id else None
    except KeyError:
        route = None
    return run_dir, route, state


def _state_selection_id(state: dict[str, Any]) -> str:
    payload = state.get("launch_selection")
    if isinstance(payload, dict):
        return str(payload.get("selection_id") or payload.get("id") or "")
    route_payload = state.get("route")
    if isinstance(route_payload, dict):
        return str(route_payload.get("selection_id") or route_payload.get("id") or "")
    return ""


def _is_terminal_state(state: dict[str, Any]) -> bool:
    values = {
        str(state.get("status") or "").lower(),
        str(state.get("phase") or "").lower(),
        str(state.get("terminal_reason") or "").lower(),
    }
    if any(is_terminal_run_phase(value) for value in values):
        return True
    checker = state.get("checker_status")
    return isinstance(checker, dict) and str(checker.get("status") or "").lower() == "passed"


def _is_operator_handoff_paused(state: dict[str, Any]) -> bool:
    return (
        str(state.get("phase") or "").strip().lower() == "paused"
        and str(state.get("terminal_reason") or "").strip().lower() == "operator_handoff_requested"
    )


def _parent_result_available(run_dir: Path, state: dict[str, Any]) -> bool:
    if (resolve_display_run_dir(run_dir) / "run_result.json").is_file():
        return True
    checker = state.get("checker_status")
    return isinstance(checker, dict) and bool(checker.get("report_exists"))


def _terminal_success(state: dict[str, Any]) -> bool:
    status = str(state.get("status") or "").lower()
    phase = str(state.get("phase") or "").lower()
    if status in {"failed", "stopped_by_operator", "human_takeover_stop", "emergency_stopped"}:
        return False
    if phase in {"failed", "stopped_by_operator", "human_takeover_stop", "emergency_stopped"}:
        return False
    checker = state.get("checker_status")
    if isinstance(checker, dict) and str(checker.get("status") or "").lower() == "failed":
        return False
    return True


def _requires_next_goal_confirmation(route: ConsoleLaunchSelection | None) -> bool:
    if route is None:
        return True
    return route.emergency_stop_required or route.resource_kind in {"physical_robot", "real_robot"}


def _session_for_run(
    root: Path,
    run_dir: Path,
    run_id: str,
    *,
    run_state: dict[str, Any],
) -> dict[str, Any]:
    session_id = _session_id_from_state(run_state)
    if session_id:
        try:
            return get_operator_session(root, session_id)
        except UnknownOperatorSessionError:
            pass
    return attach_run_to_session(root, run_id)


def _record_session_message(
    root: Path,
    run_dir: Path,
    message: dict[str, Any],
    *,
    run_state: dict[str, Any] | None = None,
) -> None:
    state = run_state if run_state is not None else _read_run_state(run_dir / "operator_state.json")
    session_id = str(state.get("operator_session_id") or message.get("operator_session_id") or "")
    if not session_id:
        session = attach_run_to_session(root, str(message.get("run_id") or run_dir.name))
        session_id = session["operator_session_id"]
    try:
        session = get_operator_session(root, session_id)
    except UnknownOperatorSessionError:
        return
    message_ids = list(session.get("message_ids") or [])
    message_id = str(message.get("message_id") or "")
    if message_id and message_id not in message_ids:
        message_ids.append(message_id)
    session["message_ids"] = message_ids
    if str(message.get("run_id") or ""):
        run_ids = list(session.get("run_ids") or [])
        if message["run_id"] not in run_ids:
            run_ids.append(message["run_id"])
        session["run_ids"] = run_ids
    _write_session(root, session)


def _session_id_from_run_state(run_dir: Path) -> str:
    state = _read_json(run_dir / "operator_state.json")
    return _session_id_from_state(state)


def _session_id_from_state(state: dict[str, Any]) -> str:
    return str(state.get("operator_session_id") or "")


def _preflight_session_source(root: Path, run_state: dict[str, Any]) -> None:
    session_id = _session_id_from_state(run_state)
    if not session_id:
        return
    try:
        get_operator_session(root, session_id)
    except UnknownOperatorSessionError:
        return


def _write_session(root: Path, session: dict[str, Any]) -> None:
    session_id = str(session.get("operator_session_id") or "")
    if not session_id:
        raise InteractionError("operator session id is required.")
    path = _session_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(session, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_message(run_dir: Path, message: dict[str, Any]) -> None:
    _append_jsonl(run_dir / MESSAGE_LOG, strip_private_payload(message))


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json_object(path, label=path.name)
    except (OSError, ValueError):
        return {}


def _read_session_json(path: Path, *, session_id: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = _read_strict_json_object(path, source_name="operator session")
    if str(payload.get("operator_session_id") or session_id) != session_id:
        raise InteractionError(f"operator session source id mismatch at {path}")
    return payload


def _read_run_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise InteractionError(f"unknown run: {path.parent.name}")
    return _read_strict_json_object(path, source_name="operator state")


def _read_strict_json_object(path: Path, *, source_name: str) -> dict[str, Any]:
    try:
        return read_json_object(path, label=source_name)
    except ValueError as exc:
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            raise InteractionError(
                (
                    f"{source_name} source contains invalid JSON at {path}: "
                    f"line {cause.lineno} column {cause.colno}: {cause.msg}"
                )
            ) from exc
        raise InteractionError(f"{source_name} source must be a JSON object at {path}") from exc
    except OSError as exc:
        raise InteractionError(f"{source_name} source cannot be read at {path}: {exc}") from exc


def _session_path(root: Path, session_id: str) -> Path:
    return console_output_root(root) / SESSION_DIR / f"{session_id}.json"


def _session_log_path(root: Path) -> Path:
    return console_output_root(root) / SESSION_LOG


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _utc_now() -> float:
    return time.time()


def _format_epoch(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _first_artifact_href(artifacts: list[Any], label: str) -> str:
    for item in artifacts:
        if isinstance(item, dict) and item.get("label") == label:
            return str(item.get("href") or "")
    return ""
