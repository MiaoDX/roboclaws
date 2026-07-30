"""Stdlib HTTP server for the standalone agent operator console."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import time
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import ParseResult, parse_qs, unquote, urlparse

from roboclaws.core.json_sources import parse_json_object_text
from roboclaws.operator_console.control import (
    OperatorControlError,
    read_operator_state_for_control,
    run_operator_control,
)
from roboclaws.operator_console.history import latest_run_payload
from roboclaws.operator_console.interactions import (
    InteractionError,
    append_next_goal_request,
    append_resume_request,
    append_steer_message,
    create_operator_session,
    get_operator_session,
    list_operator_messages,
)
from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.launcher import (
    LaunchRequest,
    load_repo_dotenv,
    route_readiness,
    start_console_run,
    stop_console_run,
)
from roboclaws.operator_console.paths import (
    OUTPUT_ROOT_ENV,
    console_output_root,
    operator_output_file,
)
from roboclaws.operator_console.prompt_preview import (
    PromptPreviewRequest,
    build_prompt_preview,
    prompt_preview_env,
)
from roboclaws.operator_console.routes import (
    get_selection,
    list_console_combinations,
    list_evidence_lanes,
    list_prior_catalog,
    list_workflows,
    list_worlds,
    selection_task_selector,
)
from roboclaws.operator_console.runtime_inventory import (
    requested_mcp_endpoint,
    runtime_blockers_from_inventory,
    runtime_blockers_payload,
    runtime_inventory_payload,
)
from roboclaws.operator_console.state import derive_operator_state, redacted_artifact_text

FOLLOW_UP_AUTOSTART_ATTEMPTS = 30
FOLLOW_UP_AUTOSTART_RETRY_DELAY_S = 1.0


def _registered_preview_asset_names(*, include_optional_worlds: bool = False) -> frozenset[str]:
    """Return catalog-backed /previews asset names, including scene metadata."""

    names: set[str] = set()
    for world in list_worlds(include_optional_worlds=include_optional_worlds):
        preview_assets = world.get("preview_assets") or {}
        if not isinstance(preview_assets, dict):
            continue
        for asset in preview_assets.values():
            if not isinstance(asset, dict):
                continue
            path = str(asset.get("path") or asset.get("href") or "")
            if not path.startswith("/previews/"):
                continue
            name = path.removeprefix("/previews/")
            names.add(name)
            if name.endswith(".png") and "-" in name:
                scene_name = name.rsplit("-", 1)[0]
                names.add(f"{scene_name}-preview.json")
    return frozenset(names)


def _readiness_selection_id(query: dict[str, list[str]]) -> str:
    selection_id = str(query.get("selection_id", [""])[0])
    if selection_id:
        return selection_id
    world_id = str(query.get("world_id", [""])[0])
    backend_id = str(query.get("backend_id", [""])[0])
    intent_id = str(query.get("intent_id", [""])[0])
    agent_engine_id = str(query.get("agent_engine_id", [""])[0])
    evidence_lane = str(query.get("evidence_lane", ["world-public-labels"])[0])
    return "::".join(
        (
            world_id,
            backend_id,
            selection_task_selector(intent_id),
            agent_engine_id,
            evidence_lane,
        )
    )


def _query_overrides(query: dict[str, list[str]], keys: tuple[str, ...]) -> dict[str, str]:
    return {key: str(query[key][0]) for key in keys if query.get(key, [""])[0]}


def _query_gates(query: dict[str, list[str]], keys: tuple[str, ...]) -> dict[str, bool]:
    return {key: str(query[key][0]).lower() == "true" for key in keys if query.get(key, [""])[0]}


def _query_provider_env_overrides(query: dict[str, list[str]]) -> dict[str, str]:
    provider = (
        str(query.get("provider_profile", [""])[0])
        or str(query.get("codex_provider", [""])[0])
        or str(query.get("claude_provider", [""])[0])
    )
    return {"ROBOCLAWS_PROVIDER_PROFILE": provider} if provider else {}


def _launch_request_from_payload(payload: dict[str, object]) -> LaunchRequest:
    return LaunchRequest(
        world_id=str(payload.get("world_id") or ""),
        backend_id=str(payload.get("backend_id") or ""),
        intent_id=str(payload.get("intent_id") or payload.get("intent") or ""),
        agent_engine_id=str(payload.get("agent_engine_id") or ""),
        provider_profile=str(payload.get("provider_profile") or ""),
        evidence_lane=str(payload.get("evidence_lane") or ""),
        scenario_setup=str(payload.get("scenario_setup") or ""),
        prompt=str(payload.get("prompt") or ""),
        overrides=dict(payload.get("overrides") or {}),
        env_overrides=dict(payload.get("env_overrides") or {}),
        gates=dict(payload.get("gates") or {}),
        operator_session_id=str(payload.get("operator_session_id") or ""),
        parent_run_id=str(payload.get("parent_run_id") or ""),
        next_goal_packet=dict(payload.get("next_goal_packet") or {}),
        selection_id_override=str(payload.get("selection_id") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
    )


def _try_autostart_follow_up(root: Path, parent_run_id: str, follow_up: dict[str, object]) -> None:
    launch = _follow_up_launch_request(parent_run_id, follow_up)
    for attempt in range(1, FOLLOW_UP_AUTOSTART_ATTEMPTS + 1):
        try:
            follow_up["started_run"] = start_console_run(root, launch)
            follow_up["status"] = "started"
            follow_up["autostart_attempts"] = attempt
            follow_up.pop("start_error", None)
            return
        except ConsoleLaunchError as exc:
            follow_up["start_error"] = str(exc)
            follow_up["autostart_attempts"] = attempt
            if attempt >= FOLLOW_UP_AUTOSTART_ATTEMPTS or not _retryable_follow_up_start_error(
                str(exc),
                parent_run_id=parent_run_id,
            ):
                return
            time.sleep(FOLLOW_UP_AUTOSTART_RETRY_DELAY_S)


def _retryable_follow_up_start_error(error: str, *, parent_run_id: str = "") -> bool:
    normalized = error.lower()
    return (
        "background task visual-slot:" in normalized
        or "molmo visual slot" in normalized
        or "visual backend slot" in normalized
        or (
            bool(parent_run_id)
            and f"background task operator-run:{parent_run_id.lower()}" in normalized
        )
    )


def _follow_up_launch_request(parent_run_id: str, follow_up: dict[str, object]) -> LaunchRequest:
    selection_id = str(follow_up.get("selection_id") or "")
    route = get_selection(selection_id)
    launch_overrides = follow_up.get("launch_overrides")
    return LaunchRequest(
        selection_id_override=selection_id,
        intent_id=str(follow_up.get("intent") or "") or route.intent_id,
        prompt=str(follow_up.get("body") or ""),
        operator_session_id=str(follow_up.get("operator_session_id") or ""),
        parent_run_id=parent_run_id,
        next_goal_packet=dict(follow_up.get("next_goal_packet") or {}),
        overrides=dict(launch_overrides) if isinstance(launch_overrides, dict) else {},
        world_id=route.world_id,
        backend_id=route.backend_id,
        agent_engine_id=route.agent_engine_id,
        evidence_lane=route.evidence_lane,
    )


class ConsoleRequestHandler(SimpleHTTPRequestHandler):
    """Serve static assets plus JSON APIs."""

    def __init__(
        self,
        *args: object,
        root: Path,
        include_optional_worlds: bool = False,
        **kwargs: object,
    ) -> None:
        self.repo_root = root.resolve()
        self.include_optional_worlds = include_optional_worlds
        self.project_root = Path(__file__).resolve().parents[2]
        static_root = Path(__file__).resolve().parent / "static"
        self.static_root = static_root.resolve()
        super().__init__(*args, directory=str(static_root), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if self._handle_static_get(parsed):
            return
        if self._handle_api_get(parsed):
            return
        if self._handle_file_get(parsed):
            return
        return super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if self._is_static_asset(parsed.path):
            return self._static_file(parsed.path, body=False)
        return super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_payload(source=f"POST {parsed.path}")
            if self._handle_exact_post(parsed.path, payload):
                return
            if self._handle_run_action_post(parsed.path, payload):
                return
        except (ConsoleLaunchError, InteractionError, KeyError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=400)
        return self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_static_get(self, parsed: ParseResult) -> bool:
        if self._is_static_asset(parsed.path):
            self._static_file(parsed.path)
            return True
        if parsed.path.startswith("/previews/"):
            self._serve_preview_asset(parsed.path)
            return True
        if parsed.path.startswith("/asset-previews/maps/"):
            self._serve_map_preview_asset(parsed.path)
            return True
        return False

    def _is_static_asset(self, request_path: str) -> bool:
        if request_path in {"/", "/index.html", "/styles.css"}:
            return True
        name = request_path.removeprefix("/")
        return (
            "/" not in name
            and name.endswith(".js")
            and not name.startswith(".")
            and (self.static_root / name).is_file()
        )

    def _handle_api_get(self, parsed: ParseResult) -> bool:
        if parsed.path == "/api/routes":
            self._json(self._routes_payload())
            return True
        if parsed.path == "/api/runtime/tasks":
            self._serve_runtime_tasks(parsed.query)
            return True
        if parsed.path == "/api/readiness":
            self._serve_route_readiness(parsed.query)
            return True
        if parsed.path == "/api/runs/latest":
            self._serve_latest_run()
            return True
        if parsed.path.startswith("/api/sessions/"):
            self._serve_session_get(parsed.path)
            return True
        if parsed.path.startswith("/api/runs/"):
            self._serve_run_get(parsed)
            return True
        if parsed.path.startswith("/api/raw/"):
            self._serve_raw_artifact(parsed.path)
            return True
        return False

    def _handle_file_get(self, parsed: ParseResult) -> bool:
        if not parsed.path.startswith("/artifacts/"):
            return False
        path = operator_output_file(
            self.repo_root,
            unquote(parsed.path.removeprefix("/artifacts/")),
        )
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return True
        self._file(path)
        return True

    def _handle_exact_post(self, path: str, payload: dict[str, object]) -> bool:
        if path == "/api/sessions":
            self._json(create_operator_session(self.repo_root), status=201)
            return True
        if path == "/api/prompt-preview":
            self._serve_prompt_preview(payload)
            return True
        if path == "/api/runs":
            self._serve_run_start(payload)
            return True
        return False

    def _handle_run_action_post(self, path: str, payload: dict[str, object]) -> bool:
        run_action = _parse_run_action_path(path)
        if not run_action:
            return False
        run_id, action = run_action
        handlers = {
            "messages": self._serve_steer_message,
            "next-goal": self._serve_next_goal,
            "resume": self._serve_resume,
            "control": self._serve_control_post,
            "stop": self._serve_stop_post,
            "emergency-stop": self._serve_emergency_stop_post,
        }
        handler = handlers.get(action)
        if handler is None:
            return False
        handler(run_id, payload)
        return True

    def _serve_preview_asset(self, request_path: str) -> None:
        rel = Path(unquote(request_path.removeprefix("/previews/")))
        path = (self.static_root / "previews" / rel).resolve()
        preview_root = (self.static_root / "previews").resolve()
        if not path.is_relative_to(preview_root):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        relative_name = path.relative_to(preview_root).as_posix()
        if (
            relative_name
            not in _registered_preview_asset_names(
                include_optional_worlds=self.include_optional_worlds
            )
            or not path.exists()
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._file(path)

    def _serve_map_preview_asset(self, request_path: str) -> None:
        rel = Path(unquote(request_path.removeprefix("/asset-previews/maps/")))
        preview_root = (self.project_root / "assets" / "maps").resolve()
        path = (preview_root / rel).resolve()
        if not path.is_relative_to(preview_root) or path.name != "preview.png":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._file(path)

    def _routes_payload(self) -> dict[str, object]:
        inventory = runtime_inventory_payload(self.repo_root)
        runtime_tasks = inventory["tasks"]
        worlds = list_worlds(include_optional_worlds=self.include_optional_worlds)
        visible_world_ids = {str(world["id"]) for world in worlds}
        combinations = tuple(
            selection
            for selection in list_console_combinations(include_disabled=True)
            if selection.world_id in visible_world_ids
        )
        return {
            "worlds": list(worlds),
            "workflows": list(list_workflows()),
            "recommended_priors": list(list_prior_catalog()),
            "evidence_lanes": list(list_evidence_lanes()),
            "combinations": [selection.to_payload() for selection in combinations],
            "readiness": {
                selection.id: route_readiness(
                    self.repo_root,
                    selection,
                    runtime_tasks=runtime_tasks,
                )
                for selection in combinations
                if selection.enabled
            },
            "runtime": runtime_blockers_from_inventory(inventory),
        }

    def _serve_runtime_tasks(self, query_string: str) -> None:
        query = parse_qs(query_string)
        ports: list[int] = []
        for value in query.get("port", []):
            try:
                ports.append(int(value))
            except ValueError:
                continue
        self._json(runtime_blockers_payload(self.repo_root, ports=ports or None))

    def _serve_route_readiness(self, query_string: str) -> None:
        try:
            query = parse_qs(query_string)
            selection_id = _readiness_selection_id(query)
            route = get_selection(selection_id)
            override_map = _query_overrides(
                query,
                (
                    "host",
                    "port",
                    "context_json",
                    "real_movement_enabled",
                    "scenario_setup",
                    "provider_profile",
                    "runtime_map_prior",
                    "isaac_scene_usd_path",
                    "b1_alignment_artifact",
                    "b1_navigation_artifact",
                ),
            )
            _, port = requested_mcp_endpoint(override_map)
            inventory = runtime_inventory_payload(self.repo_root, ports=[port])
            self._json(
                route_readiness(
                    self.repo_root,
                    route,
                    overrides=override_map,
                    env_overrides=_query_provider_env_overrides(query),
                    gates=_query_gates(
                        query,
                        ("localization_ready", "run_enabled", "estop_ready"),
                    ),
                    runtime_tasks=inventory["tasks"],
                )
            )
        except (ConsoleLaunchError, KeyError, ValueError) as exc:
            self._json({"error": str(exc)}, status=400)

    def _serve_latest_run(self) -> None:
        latest = latest_run_payload(self.repo_root)
        if not latest:
            self._json({"error": "No operator-console run artifacts found."}, status=404)
            return
        self._json(latest)

    def _serve_session_get(self, request_path: str) -> None:
        session_id = unquote(request_path.removeprefix("/api/sessions/"))
        try:
            self._json(get_operator_session(self.repo_root, session_id))
        except InteractionError as exc:
            self._json({"error": str(exc)}, status=404)

    def _serve_run_get(self, parsed: ParseResult) -> None:
        run_id = unquote(parsed.path.removeprefix("/api/runs/"))
        if run_id.endswith("/messages"):
            self._serve_run_messages_get(run_id.removesuffix("/messages"))
            return
        selection_id = parse_qs(parsed.query).get("selection_id", [""])[0]
        route = get_selection(selection_id) if selection_id else None
        run_dir = console_output_root(self.repo_root) / "runs" / run_id
        self._json(derive_operator_state(self.repo_root, run_dir, route))

    def _serve_run_messages_get(self, run_id: str) -> None:
        try:
            self._json(list_operator_messages(self.repo_root, run_id))
        except InteractionError as exc:
            self._json({"error": str(exc)}, status=404)

    def _serve_raw_artifact(self, request_path: str) -> None:
        path = operator_output_file(
            self.repo_root,
            unquote(request_path.removeprefix("/api/raw/")),
        )
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._text(redacted_artifact_text(path))

    def _serve_run_start(self, payload: dict[str, object]) -> None:
        request = _launch_request_from_payload(payload)
        self._json(start_console_run(self.repo_root, request), status=201)

    def _serve_prompt_preview(self, payload: dict[str, object]) -> None:
        request = _launch_request_from_payload(payload)
        route = get_selection(request.selection_id)
        overrides = dict(request.overrides or {})
        if request.provider_profile:
            overrides.setdefault("provider_profile", request.provider_profile)
        if request.scenario_setup:
            overrides.setdefault("scenario_setup", request.scenario_setup)
        self._json(
            build_prompt_preview(
                route,
                PromptPreviewRequest(
                    intent_id=request.intent_id or route.intent_id,
                    prompt=request.prompt,
                    overrides=overrides,
                    env_overrides=prompt_preview_env(
                        load_repo_dotenv(self.repo_root, os.environ),
                        request.env_overrides or {},
                    ),
                ),
            )
        )

    def _serve_steer_message(self, run_id: str, payload: dict[str, object]) -> None:
        self._json(
            append_steer_message(self.repo_root, run_id, str(payload.get("body") or "")),
            status=201,
        )

    def _serve_next_goal(self, run_id: str, payload: dict[str, object]) -> None:
        follow_up = append_next_goal_request(
            self.repo_root,
            run_id,
            str(payload.get("prompt") or payload.get("body") or ""),
            confirmed=bool(payload.get("confirmed")),
        )
        if follow_up.get("status") == "ready_to_start" and follow_up.get("auto_start_allowed"):
            _try_autostart_follow_up(self.repo_root, run_id, follow_up)
        self._json(follow_up, status=201)

    def _serve_resume(self, run_id: str, payload: dict[str, object]) -> None:
        self._json(
            append_resume_request(
                self.repo_root,
                run_id,
                str(payload.get("prompt") or payload.get("body") or ""),
            ),
            status=201,
        )

    def _serve_control_post(self, run_id: str, payload: dict[str, object]) -> None:
        try:
            route = _route_for_run(self.repo_root, run_id)
            self._json(run_operator_control(self.repo_root, run_id, route, payload))
        except OperatorControlError as exc:
            self._json({"ok": False, "error": str(exc)}, status=exc.status)
        except (KeyError, ValueError) as exc:
            self._json({"ok": False, "error": str(exc)}, status=400)

    def _serve_stop_post(self, run_id: str, payload: dict[str, object]) -> None:
        del payload
        self._json(stop_console_run(self.repo_root, run_id))

    def _serve_emergency_stop_post(self, run_id: str, payload: dict[str, object]) -> None:
        del payload
        self._json(stop_console_run(self.repo_root, run_id, emergency=True))

    def _read_payload(self, *, source: str) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        return parse_json_object_text(
            data.decode("utf-8"),
            label="operator console request body",
            source=source,
        )

    def _json(self, payload: object, *, status: int = 200) -> None:
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _text(self, text: str, *, status: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static_file(self, request_path: str, *, body: bool = True) -> None:
        name = "index.html" if request_path in {"/", "/index.html"} else request_path.lstrip("/")
        path = Path(self.directory) / name
        if not path.exists():
            return self.send_error(HTTPStatus.NOT_FOUND)
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in {".html", ".css", ".js"}:
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }[path.suffix]
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)


def run_server(root: Path, host: str, port: int, *, include_optional_worlds: bool = False) -> None:
    handler = partial(
        ConsoleRequestHandler,
        root=root,
        include_optional_worlds=include_optional_worlds,
    )
    server = ThreadingHTTPServer((host, port), handler)
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    print(f"Agent Operator Console: http://{url_host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the standalone agent operator console.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument(
        "--include-optional-worlds",
        action="store_true",
        help="Include validation-required Agibot and B1 worlds in console discovery.",
    )
    args = parser.parse_args(argv)
    if args.output_root is not None:
        os.environ[OUTPUT_ROOT_ENV] = str(args.output_root)
    run_server(
        args.repo_root.resolve(),
        args.host,
        args.port,
        include_optional_worlds=args.include_optional_worlds,
    )
    return 0


def _parse_run_action_path(path: str) -> tuple[str, str] | None:
    prefix = "/api/runs/"
    if not path.startswith(prefix):
        return None
    remainder = path.removeprefix(prefix)
    for action in (
        "emergency-stop",
        "next-goal",
        "messages",
        "resume",
        "control",
        "stop",
    ):
        suffix = f"/{action}"
        if remainder.endswith(suffix):
            return unquote(remainder[: -len(suffix)]), action
    return None


def _route_for_run(root: Path, run_id: str):
    state_path = console_output_root(root) / "runs" / run_id / "operator_state.json"
    if not state_path.is_file():
        raise OperatorControlError("unknown run", status=404)
    payload = read_operator_state_for_control(state_path)
    route_payload = payload.get("route")
    selection_id = str(route_payload.get("id") or "") if isinstance(route_payload, dict) else ""
    if not selection_id:
        raise ValueError("operator state does not include route id")
    return get_selection(selection_id)
