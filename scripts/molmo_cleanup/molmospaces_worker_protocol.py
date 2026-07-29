from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import parse_json_object_text, read_json_object
from roboclaws.household.artifact_paths import home_relative_paths, resolve_home_relative_paths

type WorkerCommandHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def serve_worker(
    state_path: Path,
    *,
    run_state_command: Callable[[Path, str, dict[str, Any]], dict[str, Any]],
    ok: Callable[..., dict[str, Any]],
    stdin: Any = sys.stdin,
    stdout: Any = sys.stdout,
) -> None:
    """Serve JSON-line worker requests while keeping MuJoCo state warm."""
    print(json.dumps({"ok": True, "event": "ready", "tool": "serve"}, sort_keys=True), file=stdout)
    stdout.flush()
    for line in stdin:
        if not line.strip():
            continue
        request: Any = {}
        try:
            request = parse_json_object_text(
                line,
                label="MolmoSpaces worker request",
                source="stdin",
            )
            request_id = request.get("id")
            command = str(request.get("command") or "")
            kwargs = request.get("kwargs") or {}
            if not isinstance(kwargs, dict):
                raise ValueError("MolmoSpaces worker request kwargs must be a JSON object")
            kwargs = resolve_home_relative_paths(kwargs)
            if command == "shutdown":
                response = {
                    "id": request_id,
                    "ok": True,
                    "result": ok("shutdown"),
                }
                print(json.dumps(response, sort_keys=True), file=stdout)
                stdout.flush()
                break
            result = run_state_command(state_path, command, kwargs)
            response = {"id": request_id, "ok": True, "result": result}
        except Exception as exc:
            response = {
                "id": request.get("id") if isinstance(request, dict) else None,
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        print(json.dumps(response, sort_keys=True), file=stdout)
        stdout.flush()


def run_worker_command(
    state_path: Path,
    command: str,
    kwargs: dict[str, Any],
    *,
    read_state: Callable[[Path], dict[str, Any]],
    write_state: Callable[[Path, dict[str, Any]], None],
    run_loaded_state_command: Callable[
        [dict[str, Any], str, dict[str, Any]], tuple[dict[str, Any], bool]
    ],
) -> dict[str, Any]:
    state = read_state(state_path)
    result, should_write = run_loaded_state_command(state, command, kwargs)
    if should_write:
        write_state(state_path, state)
    return result


def run_loaded_state_command(
    state: dict[str, Any],
    command: str,
    kwargs: dict[str, Any],
    *,
    handlers: dict[str, WorkerCommandHandler],
    mutating_commands: set[str],
) -> tuple[dict[str, Any], bool]:
    handler = handlers.get(command)
    if handler is None:
        raise ValueError(f"unknown MolmoSpaces worker command: {command!r}")
    return handler(state, kwargs), command in mutating_commands


def cli_command_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    command = str(args.command)
    if command == "snapshot":
        return {
            "output_path": args.output_path,
            "title": args.title,
            "render_width": args.render_width,
            "render_height": args.render_height,
        }
    if command == "robot_views":
        return {
            "output_dir": args.output_dir,
            "label": args.label,
            "focus_object_id": args.focus_object_id,
            "focus_receptacle_id": args.focus_receptacle_id,
            "camera_yaw_offset_deg": args.camera_yaw_offset_deg,
            "camera_pitch_offset_deg": args.camera_pitch_offset_deg,
            "render_width": args.render_width,
            "render_height": args.render_height,
        }
    if command == "camera_views":
        return {
            "output_dir": args.output_dir,
            "view_specs_path": args.view_specs_path,
            "camera_request_path": args.camera_request_path,
            "render_width": args.render_width,
            "render_height": args.render_height,
        }
    if command in {"navigate_to_object", "frame_comparison_object", "pick"}:
        return {"object_id": args.object_id}
    if command == "navigate_to_waypoint":
        return {"waypoint_json": args.waypoint_json}
    if command == "navigate_to_relative_pose":
        return {
            "forward_m": args.forward_m,
            "lateral_m": args.lateral_m,
            "yaw_delta_deg": args.yaw_delta_deg,
        }
    if command in {
        "navigate_to_receptacle",
        "open_receptacle",
        "close_receptacle",
        "place",
        "place_inside",
    }:
        return {"receptacle_id": args.receptacle_id}
    if command == "done":
        return {"reason": args.reason}
    return {}


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def positive_int(value: Any, default: int, *, setting_name: str = "value") -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{setting_name} must be a positive integer; got {value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{setting_name} must be a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise ValueError(f"{setting_name} must be a positive integer; got {value!r}")
    return parsed


def float_or_zero(value: Any, *, setting_name: str = "value") -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError(f"{setting_name} must be a finite number; got {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{setting_name} must be a finite number; got {value!r}") from None
    if not math.isfinite(parsed):
        raise ValueError(f"{setting_name} must be a finite number; got {value!r}")
    return parsed


def json_object_from_text(text: str) -> dict[str, Any]:
    return parse_json_object_text(text, label="MolmoSpaces worker inline JSON")


def read_state(path: Path) -> dict[str, Any]:
    return resolve_home_relative_paths(read_json_object(path, label="MolmoSpaces worker state"))


def write_state(
    path: Path,
    state: dict[str, Any],
    *,
    refresh_runtime_render_state: Callable[[dict[str, Any]], None],
) -> None:
    refresh_runtime_render_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    persisted = home_relative_paths(state)
    path.write_text(json.dumps(persisted, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def count_tool_request(state: dict[str, Any], tool: str) -> None:
    counts = state.setdefault("tool_event_counts", {})
    key = f"{tool}:request"
    counts[key] = int(counts.get(key, 0)) + 1


def ok_response(tool: str, **payload: Any) -> dict[str, Any]:
    return home_relative_paths({"ok": True, "tool": tool, "status": "ok", **payload})


def error_response(tool: str, error_reason: str, **payload: Any) -> dict[str, Any]:
    return home_relative_paths(
        {"ok": False, "tool": tool, "status": "error", "error_reason": error_reason, **payload}
    )
