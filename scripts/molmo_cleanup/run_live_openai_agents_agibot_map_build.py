#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.agents.drivers.household_live import map_build_server_argv
from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest
from roboclaws.core.json_sources import read_json_object
from roboclaws.household.agibot_map_build_mcp_server import MCP_SERVER_NAME
from scripts.molmo_cleanup.openai_agents_perf_profile import resolve_agent_sdk_perf_profile

AGIBOT_MAP_BUILD_SKILL = "household-world"
MAX_AGENT_SDK_SKILL_CONTEXT_BYTES = 24_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live OpenAI Agents SDK intent=map-build pilot against Agibot MCP tools."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--status-path", type=Path, required=True)
    parser.add_argument("--client-url", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--provider-profile", default="codex-router-responses")
    parser.add_argument("--model", default="")
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--cache-tools-list", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--mcp-client-session-timeout-s", type=float, default=None)
    parser.add_argument("--model-service-retry-attempts", type=int, default=None)
    parser.add_argument("--model-service-retry-sleep-s", type=float, default=None)
    parser.add_argument("--agent-sdk-perf-profile", default="")
    parser.add_argument("--continuation-mode", default="")
    parser.add_argument("--model-thinking-mode", default="default")
    parser.add_argument("--server-startup-timeout-s", type=float, default=600.0)
    parser.add_argument("--kickoff-prompt", required=True)
    parser.add_argument("--backend", default="agibot_gdk")
    parser.add_argument("--policy", default="openai_agents_agibot_map_build")
    parser.add_argument("--task", default="map-build")
    parser.add_argument("--server-arg", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return LiveOpenAIAgentsAgibotMapBuildRunner(parse_args(argv)).run()


class LiveOpenAIAgentsAgibotMapBuildRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_dir = args.run_dir
        self.status_path = args.status_path
        self.server_proc: subprocess.Popen[bytes] | None = None
        self.agent_sdk_perf_profile = resolve_agent_sdk_perf_profile(args)
        self.skill_context = _load_agent_sdk_skill_context(
            args.repo_root,
            skill_name=AGIBOT_MAP_BUILD_SKILL,
        )

    def run(self) -> int:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._write_status("starting-server")
            self._start_server()
            self._wait_for_mcp_ready()
            self._write_status("running-sdk")
            result = OpenAIAgentsLiveRuntime().run(self._sdk_request())
            if result.exit_status not in {0, None}:
                raise RuntimeError(f"OpenAI Agents SDK runtime failed: {result.reason}")
            if not (self.run_dir / "run_result.json").is_file():
                raise RuntimeError("OpenAI Agents SDK turn ended without calling done")
            self._write_status("waiting-for-server-finish")
            self._wait_for_server_finish()
            self._check_result()
        except KeyboardInterrupt:
            self._write_status("failed", 130, reason="keyboard_interrupt")
            self._cleanup_server()
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
            self._write_status("failed", 1, reason=str(exc))
            self._cleanup_server()
            return 1
        self._write_status("finished", 0)
        return 0

    def _start_server(self) -> None:
        probe_host = _probe_host(self.args.host)
        if _port_accepting(probe_host, self.args.port):
            raise RuntimeError(
                f"TCP port {self.args.host}:{self.args.port} is already in use before server start"
            )
        command = [
            *map_build_server_argv(str(self.args.repo_root / ".venv/bin/python")),
            *self.args.server_arg,
        ]
        self.server_proc = subprocess.Popen(
            command,
            cwd=self.args.repo_root,
            env=os.environ.copy(),
        )
        (self.run_dir / "server.pid").write_text(f"{self.server_proc.pid}\n", encoding="utf-8")

    def _wait_for_mcp_ready(self) -> None:
        assert self.server_proc is not None
        probe_host = _probe_host(self.args.host)
        deadline = time.monotonic() + self.args.server_startup_timeout_s
        while time.monotonic() < deadline:
            if self.server_proc.poll() is not None:
                raise RuntimeError("Agibot map-build MCP server exited before becoming ready")
            if _port_accepting(probe_host, self.args.port):
                return
            time.sleep(0.5)
        raise RuntimeError(
            f"Agibot map-build MCP server did not become ready at {self.args.host}:{self.args.port}"
        )

    def _sdk_request(self) -> LiveAgentRequest:
        return LiveAgentRequest(
            run_id="household-world",
            skill_name=AGIBOT_MAP_BUILD_SKILL,
            kickoff_prompt=_agibot_map_build_prompt(self.args.kickoff_prompt),
            mcp_server=LiveAgentMCPServer(name="cleanup", url=self.args.client_url),
            run_dir=self.run_dir,
            model=self.args.model,
            provider_profile=self.args.provider_profile,
            max_turns=int(self.agent_sdk_perf_profile["max_turns"]),
            one_turn=True,
            metadata={
                "provider_profile": self.args.provider_profile,
                "model": self.args.model,
                "max_turns": int(self.agent_sdk_perf_profile["max_turns"]),
                "cache_tools_list": bool(self.agent_sdk_perf_profile["cache_tools_list"]),
                "mcp_client_session_timeout_s": float(
                    self.agent_sdk_perf_profile["mcp_client_session_timeout_s"] or 0.0
                ),
                "model_service_retry_attempts": int(
                    self.agent_sdk_perf_profile["model_service_retry_attempts"] or 0
                ),
                "model_service_retry_sleep_s": float(
                    self.agent_sdk_perf_profile["model_service_retry_sleep_s"] or 0.0
                ),
                "agent_sdk_perf_profile": self.agent_sdk_perf_profile,
                "sdk_model_settings": self.agent_sdk_perf_profile["sdk_model_settings"],
                "sdk_run_config": self.agent_sdk_perf_profile["sdk_run_config"],
                "model_thinking_mode": self.agent_sdk_perf_profile["model_thinking_mode"],
                "skill_context": self.skill_context,
                "surface": "household-world",
                "intent": "map-build",
                "task_name": "household-world",
                "task_intent": "map-build",
                "evidence_lane": _server_arg_value(self.args.server_arg, "--evidence-lane"),
                "backend": self.args.backend,
            },
            artifact_paths={
                "live_status": self.status_path,
                "openai_agents_events": self.run_dir / "openai-agents-events.jsonl",
                "openai_agents_trace": self.run_dir / "openai-agents-trace.json",
                "openai_agents_spans": self.run_dir / "openai-agents-spans.jsonl",
                "openai_agents_skill_context": self.run_dir / "openai-agents-skill-context.json",
            },
        )

    def _wait_for_server_finish(self) -> None:
        assert self.server_proc is not None
        status = self.server_proc.wait()
        self.server_proc = None
        if status != 0:
            raise RuntimeError(f"Agibot map-build MCP server exited with status {status}")

    def _check_result(self) -> None:
        payload = _read_agibot_map_build_run_result(self.run_dir / "run_result.json")
        if payload.get("mcp_server") != MCP_SERVER_NAME:
            raise RuntimeError(f"run_result has unexpected mcp_server: {payload.get('mcp_server')}")
        if payload.get("backend_variant") != "agibot_gdk":
            raise RuntimeError(
                f"run_result has unexpected backend_variant: {payload.get('backend_variant')}"
            )
        if payload.get("agent_driven") is not True:
            raise RuntimeError("run_result is not marked agent_driven=true")
        print(f"==> report: {self.run_dir / 'report.html'}")

    def _cleanup_server(self) -> None:
        proc = self.server_proc
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def _write_status(
        self,
        phase: str,
        exit_status: int | None = None,
        *,
        reason: str = "",
    ) -> None:
        payload: dict[str, Any] = {"phase": phase}
        if reason:
            payload["reason"] = reason
        if exit_status is not None:
            payload["exit_status"] = exit_status
        self.status_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _agibot_map_build_prompt(prompt: str) -> str:
    return (
        "Agibot intent=map-build route: use the cleanup MCP server only. "
        "Call metric_map first. Build a waypoint checklist from "
        "metric_map.inspection_waypoints and use public_semantic_anchors plus "
        "observation evidence as map context. Visit public waypoint ids only with "
        "navigate_to_waypoint, then call observe. Do not invent coordinates, do not "
        "call static_fixture_projection, raw Agibot/GDK/PNC tools, or private files, and do not "
        "use manipulation tools except to verify they remain blocked when needed. "
        "Call done after every selected public waypoint has either been observed or "
        "explicitly left for operator review.\n\n"
        f"{prompt}"
    )


def _load_agent_sdk_skill_context(repo_root: Path, *, skill_name: str) -> dict[str, Any]:
    relative_path = Path("skills") / skill_name / "SKILL.md"
    source_path = Path(repo_root) / relative_path
    base_payload: dict[str, Any] = {
        "schema": "agent_sdk_skill_context_v1",
        "skill_name": skill_name,
        "source_path": str(source_path),
        "relative_path": str(relative_path),
        "policy": "canonical_skill_markdown",
    }
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        return {
            **base_payload,
            "included": False,
            "reason": "source_unavailable",
            "error_type": exc.__class__.__name__,
        }
    truncated = raw[:MAX_AGENT_SDK_SKILL_CONTEXT_BYTES]
    text = truncated.decode("utf-8", errors="replace")
    return {
        **base_payload,
        "included": bool(text),
        "reason": "included" if text else "empty",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "included_bytes": len(truncated),
        "truncated": len(raw) > len(truncated),
        "estimated_tokens": _estimated_tokens_from_chars(len(text)),
        "content": text,
    }


def _estimated_tokens_from_chars(chars: int) -> int:
    return max(1, (max(chars, 0) + 3) // 4)


def _server_arg_value(server_args: list[str], flag: str) -> str:
    for index, item in enumerate(server_args):
        if item == flag and index + 1 < len(server_args):
            return server_args[index + 1]
    prefix = f"{flag}="
    for item in server_args:
        if item.startswith(prefix):
            return item[len(prefix) :]
    return ""


def _read_agibot_map_build_run_result(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="Agibot map-build run_result")


def _port_accepting(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _probe_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


if __name__ == "__main__":
    raise SystemExit(main())
