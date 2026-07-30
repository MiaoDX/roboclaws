#!/usr/bin/env python3
"""Run one OpenAI Agents SDK household-world live-agent session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from roboclaws.agents.drivers.household_live import (
    HouseholdLiveRunLease,
    acquire_household_live_run_lease,
    add_household_cleanup_live_runner_args,
    household_server_argv,
)
from roboclaws.agents.drivers.openai_agents_budget import (
    context_budget_failure as _shared_context_budget_failure,
)
from roboclaws.agents.drivers.openai_agents_continuation_state import (
    candidate_attempt_counts_by_waypoint,
    candidate_outcomes_by_waypoint,
    latest_done_completion_blockers,
    raw_fpv_revisit_waypoints,
    reconcile_remaining_observes_with_heading_blocker,
    remaining_observes_by_waypoint,
    waypoints_by_observation_recency,
)
from roboclaws.agents.drivers.openai_agents_household_budget import (
    raw_fpv_budget_failure as _raw_fpv_budget_failure,
)
from roboclaws.agents.drivers.openai_agents_household_budget import (
    raw_fpv_budget_metrics as _raw_fpv_budget_metrics,
)
from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.drivers.openai_agents_metrics import (
    model_input_filter_metrics as _model_input_filter_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    model_racing_observability_metrics as _model_racing_observability_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    model_service_fallback_metrics as _model_service_fallback_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    openai_agents_cache_metrics as _cache_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    openai_agents_context_growth_metrics as _context_growth_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    openai_agents_context_metrics as _context_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    openai_agents_event_metrics as _openai_agents_event_metrics,
)
from roboclaws.agents.drivers.openai_agents_metrics import (
    openai_agents_span_metrics as _openai_agents_span_metrics,
)
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    MODEL_THINKING_MODE_ENV,
    camera_grounded_composite_tools_enabled_for_run,
)
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    resolve_agent_sdk_perf_profile as _resolve_agent_sdk_perf_profile,
)
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest
from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.agents.live_status_writer import LiveRunStatusWriter
from roboclaws.agents.live_timing import compact_metric_group as _compact_metric_group
from roboclaws.agents.live_timing import (
    live_timing_timeline as _live_timing_timeline,
)
from roboclaws.agents.live_timing import (
    mcp_control_plane_metrics as _mcp_control_plane_metrics,
)
from roboclaws.agents.live_timing import mcp_trace_timing as _mcp_trace_timing
from roboclaws.agents.live_timing import (
    model_or_sdk_unattributed_seconds as _model_or_sdk_unattributed_seconds,
)
from roboclaws.agents.live_timing import round_duration as _round_duration
from roboclaws.agents.live_timing import (
    runner_timing_breakdown as _runner_timing_breakdown,
)
from roboclaws.agents.prompts.household_cleanup import (
    render_kickoff_prompt,
    render_map_build_prompt,
)
from roboclaws.agents.thinking_policy import THINKING_MODES
from roboclaws.core.evaluation import (
    checker_flags_for_household_intent,
    household_intent_id_for_checker,
    merge_checker_flags,
)
from roboclaws.core.json_sources import read_json_value, read_jsonl_objects
from roboclaws.core.open_ended_artifacts import validate_open_ended_artifacts
from roboclaws.core.operator_messages import consume_resume_request_for_runner
from roboclaws.household.household_mcp_server import ROBOT_VIEW_CAPTURE_POLICY_FULL
from roboclaws.household.raw_fpv_guidance import raw_fpv_edge_reframe_instruction
from roboclaws.household.task_intent import (
    household_intent_from_args as _household_intent,
)
from roboclaws.household.task_intent import (
    household_task_name_from_args as _household_run_id,
)
from roboclaws.reports.live_performance import (
    extract_model_call_metrics,
    write_model_call_metrics_jsonl,
)

CHECKER_SCRIPT = "scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py"
REPORT_RERUN_COMMAND_ENV = "ROBOCLAWS_REPORT_RERUN_COMMAND"
MAX_AGENT_SDK_SKILL_CONTEXT_BYTES = 24_000
OPERATOR_HANDOFF_REASON = "operator_handoff_requested"
OPERATOR_HANDOFF_MARKERS = (
    "manual adjust",
    "manual reposition",
    "manual control",
    "operator handoff",
    "human handoff",
    "wait for operator",
    "wait for human",
    "手动调整",
    "手动调",
    "手动控制",
    "手动移动",
    "人工调整",
    "人工接管",
    "人工介入",
)
OPERATOR_HANDOFF_WAIT_MARKERS = (
    "do not call done",
    "don't call done",
    "not call done",
    "without done",
    "do not exit",
    "don't exit",
    "wait",
    "stop here",
    "不调用 done",
    "不调用done",
    "不要调用 done",
    "不要调用done",
    "不 call done",
    "不退出",
    "不要退出",
    "不要推出",
    "等待",
    "我现在停止",
)

DEFAULT_INCOMPLETE_TURN_CONTINUATION_PROMPT = """
Continuation recovery for the same live household cleanup run:

The previous OpenAI Agents SDK invocation ended without calling `done`, so no
`run_result.json` was produced. Continue from the current cleanup MCP server
state. Do not summarize progress as a final answer. First inspect the current
runtime state through cleanup tools, then continue only missing waypoint,
visual-grounding, pick/place, or completion steps. Call `done` only after the
MCP-visible task state satisfies the cleanup instructions. The runner will count
success only when MCP `done` produces `run_result.json`.
""".strip()


class LiveAgentRunFailure(RuntimeError):
    """Raised after the SDK runtime writes structured failure status."""

    def __init__(self, message: str, failure: LiveAgentFailure) -> None:
        super().__init__(message)
        self.failure = failure


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Own the cleanup MCP server, OpenAI Agents SDK runtime, checker, and "
            "status files for one experimental live run."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_household_cleanup_live_runner_args(parser, policy_default="openai_agents_agent")
    parser.add_argument("--provider-profile", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help=(
            "Maximum OpenAI Agents SDK agent turns inside one runner invocation. "
            "This is not runner-side continuation."
        ),
    )
    parser.add_argument(
        "--incomplete-turn-continuation-attempts",
        type=int,
        default=None,
        help=(
            "Bounded continuation attempts after a successful SDK turn ends without "
            "MCP done/run_result.json. The runner still never infers cleanup success."
        ),
    )
    parser.add_argument(
        "--cache-tools-list",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", default=True),
        help=(
            "Ask the OpenAI Agents SDK MCP client to cache the cleanup tool list. "
            "The cleanup MCP tool catalog is static within one live run."
        ),
    )
    parser.add_argument(
        "--mcp-client-session-timeout-s",
        type=float,
        default=None,
        help=(
            "OpenAI Agents SDK MCP ClientSession read timeout. Visual cleanup lanes can "
            "exceed the SDK's short default while robot-view artifacts are captured."
        ),
    )
    parser.add_argument(
        "--agent-sdk-perf-profile",
        default="",
        help=(
            "Private OpenAI Agents SDK performance profile id. Known values: "
            "context_managed_v1, baseline."
        ),
    )
    parser.add_argument("--continuation-mode", default="")
    parser.add_argument(
        "--model-thinking-mode",
        choices=THINKING_MODES,
        default=os.environ.get(MODEL_THINKING_MODE_ENV, "default"),
        help=(
            "Provider-aware model thinking policy. default enables supported OpenAI "
            "Chat/Responses thinking, enabled forces it, disabled sends the provider-specific "
            "off switch for A/B runs."
        ),
    )
    parser.add_argument(
        "--model-input-compaction",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to the SDK call_model_input_filter compaction arm. This is private "
            "OpenAI Agents SDK candidate-I evidence and is disabled by default."
        ),
    )
    parser.add_argument("--model-input-compaction-min-chars", type=int, default=None)
    parser.add_argument(
        "--model-racing",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-C get_response model-call racing. "
            "stream_response remains single-arm."
        ),
    )
    parser.add_argument("--model-racing-arm-count", type=int, default=None)
    parser.add_argument(
        "--raw-fpv-image-memory",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-AA raw-FPV image-memory policy. "
            "This only compacts older image blocks before SDK model calls; reports and "
            "MCP traces keep full image artifacts."
        ),
    )
    parser.add_argument("--raw-fpv-image-memory-retain", type=int, default=None)
    parser.add_argument(
        "--camera-grounded-history-compaction",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-AC camera-grounded history compaction. "
            "Older camera-grounded observation/declaration outputs are summarized before "
            "SDK model calls while recent actionable outputs and MCP/report artifacts remain "
            "complete."
        ),
    )
    parser.add_argument("--camera-grounded-history-retain", type=int, default=None)
    parser.add_argument(
        "--camera-grounded-composite-tools",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-O MCP composite tools for "
            "camera-grounded-labels. The cleanup server enables the extra tool only "
            "for this SDK run."
        ),
    )
    parser.add_argument(
        "--robot-view-capture-policy",
        default="",
        help=(
            "Private Agent SDK Candidate-F robot-view report capture policy. "
            "Use action_timeline to keep before/after and cleanup action views while "
            "skipping report-only observe/scene_objects captures."
        ),
    )
    parser.add_argument("--context-soft-limit-tokens", type=int, default=None)
    parser.add_argument("--context-hard-limit-tokens", type=int, default=None)
    parser.add_argument("--max-observe-per-waypoint", type=int, default=None)
    parser.add_argument("--raw-fpv-candidate-budget", type=int, default=None)
    parser.add_argument("--raw-fpv-repeated-failure-limit", type=int, default=None)
    parser.add_argument("--done-retry-budget", type=int, default=None)
    parser.add_argument(
        "--model-service-retry-attempts",
        type=int,
        default=None,
        help=(
            "Bounded same-provider Agent SDK model-request retries for classified "
            "transient provider/model service failures. Set 0 to disable."
        ),
    )
    parser.add_argument(
        "--model-service-retry-sleep-s",
        type=float,
        default=None,
        help="Delay between Agent SDK model-service retry attempts.",
    )
    return parser.parse_args(argv)


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if (value := raw.strip().lower()) in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        return value in {"1", "true", "yes", "on"}
    raise ValueError(f"{name} must be true or false, got {raw!r}")


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


def _skill_context_timing_summary(skill_context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in skill_context.items()
        if key
        in {
            "schema",
            "skill_name",
            "source_path",
            "relative_path",
            "policy",
            "included",
            "reason",
            "sha256",
            "bytes",
            "included_bytes",
            "truncated",
            "estimated_tokens",
            "error_type",
        }
    }


def _stable_prefix_packet(
    prompt: str,
    skill_context: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    skill_hash = str(skill_context.get("sha256") or "")
    prompt_prefix = str(prompt or "")[:2048]
    material = "\n".join(
        [
            str(skill_context.get("relative_path") or ""),
            skill_hash,
            str(profile.get("provider_profile") or ""),
            str(profile.get("wire_api") or ""),
            prompt_prefix,
        ]
    )
    return {
        "schema": "agent_sdk_stable_prefix_v1",
        "hash": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "material": "skill-path+skill-hash+provider-profile+wire-api+prompt-prefix",
        "skill_context_sha256": skill_hash,
        "prompt_prefix_chars": len(prompt_prefix),
        "prompt_cache_retention": (profile.get("sdk_model_settings") or {}).get(
            "prompt_cache_retention"
        )
        or "",
    }


def main(argv: list[str] | None = None) -> int:
    return LiveOpenAIAgentsHouseholdRunner(parse_args(argv)).run()


class LiveOpenAIAgentsHouseholdRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.skill_name = str(getattr(args, "skill_name", "") or "household-world")
        self.run_dir = args.run_dir
        self.status_path = args.status_path
        self.timing_path = self.run_dir / "live_timing.json"
        self.started_at_epoch = time.time()
        self.server_proc: subprocess.Popen[bytes] | None = None
        self.server_log_path = self.run_dir / "openai-agents-server.log"
        self.server_log_file: BinaryIO | None = None
        self.server_log_thread: threading.Thread | None = None
        self.run_lease = HouseholdLiveRunLease()
        self.status_writer = LiveRunStatusWriter(
            run_dir=self.run_dir,
            status_path=self.status_path,
            started_at_epoch=self.started_at_epoch,
            lease_status_fields=self.run_lease.status_fields,
        )
        self.operator_handoff_active = False
        self.agent_sdk_perf_profile = _resolve_agent_sdk_perf_profile(args)
        self.skill_context = _load_agent_sdk_skill_context(
            args.repo_root,
            skill_name=self.skill_name,
        )
        self.initial_kickoff_prompt = _profiled_kickoff_prompt(
            args,
            profile=self.agent_sdk_perf_profile,
        )
        self.live_timing: dict[str, Any] = {
            "schema": "molmo_live_timing_v1",
            "started_at_epoch": self.started_at_epoch,
            "surface": "household-world",
            "intent": _household_intent(args),
            "task_name": _household_run_id(args),
            "evidence_lane": getattr(args, "profile", ""),
            "profile": getattr(args, "profile", ""),
            "backend": getattr(args, "backend", ""),
            "policy": getattr(args, "policy", ""),
            "runtime": "openai-agents-live",
            "provider_profile": getattr(args, "provider_profile", ""),
            "wire_api": self.agent_sdk_perf_profile["wire_api"],
            "model": getattr(args, "model", ""),
            "cache_tools_list": bool(getattr(args, "cache_tools_list", True)),
            "kickoff_prompt_chars": len(self.initial_kickoff_prompt),
            "kickoff_prompt_estimated_tokens": _estimated_tokens_from_chars(
                len(self.initial_kickoff_prompt)
            ),
            "kickoff_prompt_source": _kickoff_prompt_source(args, self.agent_sdk_perf_profile),
            "kickoff_prompt_stable_prefix": _stable_prefix_packet(
                self.initial_kickoff_prompt,
                self.skill_context,
                self.agent_sdk_perf_profile,
            ),
            "mcp_client_session_timeout_s": _round_duration(
                max(0.0, float(getattr(args, "mcp_client_session_timeout_s", 0.0) or 0.0))
            ),
            "agent_sdk_perf_profile": self.agent_sdk_perf_profile,
            "agent_sdk_camera_grounded_composite_tools": (
                self.agent_sdk_perf_profile["camera_grounded_composite_tools"]
            ),
            "agent_sdk_robot_view_capture_policy": (
                self.agent_sdk_perf_profile["robot_view_capture_policy"]
            ),
            "prompt_profile_id": self.agent_sdk_perf_profile["profile_id"],
            "agent_sdk_skill_context": _skill_context_timing_summary(self.skill_context),
        }

    def run(self) -> int:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._acquire_lock()
            self.status_writer.start_heartbeat()
            self._write_status("starting-server")
            self._start_server()
            self._wait_for_mcp_ready()
            self._run_sdk_agent()
            if self.operator_handoff_active:
                status = self._finish_operator_handoff()
                self._release_visual_slot()
                return status
            self._wait_for_server_finish()
            self._check_result()
        except KeyboardInterrupt:
            self._write_status("failed", 130, reason="keyboard_interrupt")
            self._write_live_timing("failed", 130, reason="keyboard_interrupt")
            self._cleanup_server()
            self._release_visual_slot()
            self.status_writer.stop_heartbeat()
            return 130
        except LiveAgentRunFailure as exc:
            print(f"error: {exc}", file=sys.stderr)
            self._write_status("failed", 1, **exc.failure.status_fields())
            self._write_live_timing("failed", 1, **exc.failure.status_fields())
            self._cleanup_server()
            self._release_visual_slot()
            self.status_writer.stop_heartbeat()
            return 1
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            self._write_status("failed", 1, reason=str(exc))
            self._write_live_timing("failed", 1, reason=str(exc))
            self._cleanup_server()
            self._release_visual_slot()
            self.status_writer.stop_heartbeat()
            return 1

        self._write_live_timing("finished", 0)
        self._write_status("finished", 0)
        self._release_visual_slot()
        self.status_writer.stop_heartbeat()
        return 0

    def _acquire_lock(self) -> None:
        self.run_lease = acquire_household_live_run_lease(
            backend=self.args.backend,
            repo_root=self.args.repo_root,
            run_dir=self.run_dir,
            status_path=self.status_path,
            lock_path=self.args.lock_path,
            port=self.args.port,
            owner="openai-agents-live",
            started_at_epoch=self.started_at_epoch,
            extra_lock_payload={"runtime": "openai-agents-live"},
        )

    def _release_visual_slot(self) -> None:
        self.run_lease.release_visual_slot()

    def _start_server(self) -> None:
        print("==> OpenAI Agents SDK household runner")
        print(f"    repo    : {self.args.repo_root}")
        print(f"    run dir : {self.run_dir}")
        print(f"    MCP URL : {self.args.client_url}")
        self._mark_timing("server_start")

        probe_host = _probe_host(self.args.host)
        if _port_accepting(probe_host, self.args.port):
            raise RuntimeError(
                f"TCP port {self.args.host}:{self.args.port} is already in use before server start"
            )

        command = [
            *household_server_argv(str(self.args.repo_root / ".venv/bin/python")),
            *self.args.server_arg,
        ]
        if camera_grounded_composite_tools_enabled_for_run(
            self.agent_sdk_perf_profile,
            evidence_lane=str(getattr(self.args, "profile", "") or ""),
        ):
            command.append("--agent-sdk-camera-grounded-composite-tools")
        robot_view_capture_policy = self.agent_sdk_perf_profile["robot_view_capture_policy"]
        if robot_view_capture_policy["policy"] != ROBOT_VIEW_CAPTURE_POLICY_FULL:
            command.extend(["--robot-view-capture-policy", robot_view_capture_policy["policy"]])
        env = os.environ.copy()
        if env.get(REPORT_RERUN_COMMAND_ENV):
            command.extend(["--rerun-command", env[REPORT_RERUN_COMMAND_ENV]])
        self.server_proc = subprocess.Popen(
            command,
            cwd=self.args.repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._start_server_log_tee()
        (self.run_dir / "server.pid").write_text(f"{self.server_proc.pid}\n", encoding="utf-8")

    def _wait_for_mcp_ready(self) -> None:
        assert self.server_proc is not None
        probe_host = _probe_host(self.args.host)
        deadline = time.monotonic() + self.args.server_startup_timeout_s
        while time.monotonic() < deadline:
            if self.server_proc.poll() is not None:
                raise RuntimeError("cleanup MCP server exited before becoming ready")
            if _port_accepting(probe_host, self.args.port):
                self._mark_timing("server_ready")
                return
            time.sleep(0.5)
        raise RuntimeError(
            f"cleanup MCP server did not become ready at {self.args.host}:{self.args.port} "
            f"within {self.args.server_startup_timeout_s:g}s"
        )

    def _run_sdk_agent(self) -> None:
        self._mark_timing("openai_agents_start")
        recovery_policy = IncompleteTurnRecoveryPolicy(
            max_attempts=int(self.agent_sdk_perf_profile["max_continuations"]),
            continuation_suffix=_task_aware_continuation_suffix(self.args),
        )
        runtime = OpenAIAgentsLiveRuntime()
        prompt = self.initial_kickoff_prompt
        attempt_index = 0
        result = None
        attempts: list[dict[str, Any]] = []
        while True:
            self._write_status("running-sdk")
            self._raise_agent_sdk_budget_failure_if_any(
                attempt_index=attempt_index,
                stage="before",
            )
            request = self._sdk_request(prompt=prompt, attempt_index=attempt_index)
            result = runtime.run(request)
            attempt_summary = _sdk_attempt_summary(result, attempt_index=attempt_index)
            attempts.append(attempt_summary)
            self.live_timing["openai_agents_attempts"] = attempts
            context_budget_recovery = _is_context_budget_result(result)
            turn_budget_recovery = _is_turn_budget_result(result)
            budget_recovery = context_budget_recovery or turn_budget_recovery
            if result.exit_status not in {0, None} and not budget_recovery:
                break
            if (self.run_dir / "run_result.json").is_file():
                break
            if self._start_operator_handoff_if_requested(attempt_summary):
                break
            if not context_budget_recovery:
                self._raise_agent_sdk_budget_failure_if_any(
                    attempt_index=attempt_index,
                    stage="after",
                )
            continuation_prompt = recovery_policy.continuation_prompt(
                original_prompt=self.initial_kickoff_prompt,
                result=result,
                run_dir=self.run_dir,
                attempt_index=attempt_index,
                profile=self.agent_sdk_perf_profile,
                context_metrics=_context_metrics(self.run_dir, self.live_timing),
            )
            if continuation_prompt is None:
                break
            attempt_summary["recovery_action"] = "continue"
            attempt_summary["recovery_reason"] = _continuation_recovery_reason(
                context_budget_recovery=context_budget_recovery,
                turn_budget_recovery=turn_budget_recovery,
                default_reason=recovery_policy.reason,
            )
            attempt_summary["continuation_prompt_chars"] = len(continuation_prompt)
            attempt_summary["continuation_prompt_estimated_tokens"] = _estimated_tokens_from_chars(
                len(continuation_prompt)
            )
            attempt_index += 1
            prompt = continuation_prompt

        assert result is not None
        self._mark_timing("openai_agents_end")
        self.live_timing["openai_agents"] = {
            "phase": result.phase,
            "exit_status": result.exit_status,
            "reason": result.reason,
            "provider_reason": result.provider_reason,
            "retryable": result.retryable,
            "resume_available": result.resume_available,
            "usage": dict(result.usage),
            "trace_id": result.trace_id,
            "provider_session_id": result.provider_session_id,
        }
        self._raise_sdk_result_failure(result)
        if self.operator_handoff_active:
            return
        if not (self.run_dir / "run_result.json").is_file():
            raise RuntimeError(
                "OpenAI Agents SDK turn ended without done after "
                f"{len(attempts)} OpenAI Agents SDK invocation(s)"
            )

    def _start_operator_handoff_if_requested(self, attempt_summary: dict[str, Any]) -> bool:
        handoff = _explicit_operator_handoff_requested(self.args)
        if not handoff or self.server_proc is None or self.server_proc.poll() is not None:
            return False
        attempt_summary["recovery_action"] = "operator_handoff"
        attempt_summary["recovery_reason"] = OPERATOR_HANDOFF_REASON
        self.operator_handoff_active = True
        self._write_status(
            "paused",
            reason=OPERATOR_HANDOFF_REASON,
            resume_available=True,
            detail=handoff,
        )
        print(
            "==> OpenAI Agents SDK requested an operator handoff; keeping "
            "MCP server alive for manual control"
        )
        return True

    def _raise_sdk_result_failure(self, result: Any) -> None:
        if result.exit_status in {0, None}:
            return
        failure = _failure_from_sdk_result(
            result,
            run_dir=self.run_dir,
            timing=self.live_timing,
            profile=self.agent_sdk_perf_profile,
        )
        if result.reason in {
            "agent_sdk_turn_budget_exceeded",
            "provider_context_budget_exceeded",
        }:
            self.live_timing["agent_sdk_budget_terminal"] = failure.status_fields()
        raise LiveAgentRunFailure(
            f"OpenAI Agents SDK runtime failed: {failure.reason}",
            failure,
        )

    def _raise_agent_sdk_budget_failure_if_any(self, *, attempt_index: int, stage: str) -> None:
        budget_failure = _raw_fpv_budget_failure(
            self.run_dir,
            self.live_timing,
            self.agent_sdk_perf_profile,
        )
        if budget_failure is None:
            return
        self.live_timing["agent_sdk_budget_terminal"] = budget_failure.status_fields()
        raise LiveAgentRunFailure(
            f"OpenAI Agents SDK budget guard stopped {stage} attempt {attempt_index}: "
            f"{budget_failure.reason}",
            budget_failure,
        )

    def _sdk_request(self, *, prompt: str, attempt_index: int) -> LiveAgentRequest:
        artifact_paths = {
            "live_status": self.status_path,
            "openai_agents_events": self.run_dir / "openai-agents-events.jsonl",
            "openai_agents_trace": self.run_dir / "openai-agents-trace.json",
            "openai_agents_spans": self.run_dir / "openai-agents-spans.jsonl",
            "openai_agents_skill_context": self.run_dir / "openai-agents-skill-context.json",
        }
        if attempt_index:
            artifact_paths.update(
                {
                    "openai_agents_events": self.run_dir
                    / f"openai-agents-events.continuation-{attempt_index}.jsonl",
                    "openai_agents_trace": self.run_dir
                    / f"openai-agents-trace.continuation-{attempt_index}.json",
                    "openai_agents_spans": self.run_dir
                    / f"openai-agents-spans.continuation-{attempt_index}.jsonl",
                }
            )
        return LiveAgentRequest(
            run_id=_household_run_id(self.args),
            skill_name=self.skill_name,
            kickoff_prompt=prompt,
            mcp_server=LiveAgentMCPServer(name="cleanup", url=self.args.client_url),
            run_dir=self.run_dir,
            model=self.args.model,
            provider_profile=self.args.provider_profile,
            max_turns=int(self.agent_sdk_perf_profile["max_turns"]),
            one_turn=True,
            metadata={
                "provider_profile": self.args.provider_profile,
                "max_turns": int(self.agent_sdk_perf_profile["max_turns"]),
                "attempt_index": attempt_index,
                "attempt_role": "continuation" if attempt_index else "initial",
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
                "intent": _household_intent(self.args),
                "task_name": _household_run_id(self.args),
                "evidence_lane": getattr(self.args, "profile", ""),
            },
            artifact_paths=artifact_paths,
        )

    def _wait_for_server_finish(self) -> None:
        assert self.server_proc is not None
        self._write_status("waiting-for-server-finish")
        print("==> waiting for cleanup MCP server to finish after agent done")
        self._mark_timing("server_wait_start")
        status = self.server_proc.wait()
        self._mark_timing("server_finished")
        self._finish_server_log_tee()
        self.server_proc = None
        if status != 0:
            raise RuntimeError(f"cleanup MCP server exited with status {status}")

    def _finish_operator_handoff(self) -> int:
        assert self.server_proc is not None
        print("==> waiting for operator handoff to finish")
        self._mark_timing("operator_handoff_wait_start")
        status = self._wait_for_handoff_resume_or_server_exit()
        if status is None:
            return self._finish_after_resume()
        self._mark_timing("server_finished")
        self._finish_server_log_tee()
        self.server_proc = None

        terminal_phase = _wait_for_terminal_phase_from_status(self.status_path)
        if (self.run_dir / "run_result.json").is_file() and status == 0:
            self._check_result()
            self._write_live_timing("finished", 0)
            self._write_status("finished", 0)
            return 0
        if terminal_phase in {
            "stopped_by_operator",
            "human_takeover_stop",
            "emergency_stopped",
        }:
            self._write_live_timing(terminal_phase, 130, reason=terminal_phase)
            return 0
        if status != 0:
            reason = f"cleanup MCP server exited with status {status} during operator handoff"
            self._write_status("failed", 1, reason=reason)
            self._write_live_timing("failed", 1, reason=reason)
            return 1
        reason = "operator handoff server exited without run_result.json"
        self._write_status("failed", 1, reason=reason)
        self._write_live_timing("failed", 1, reason=reason)
        return 1

    def _wait_for_handoff_resume_or_server_exit(self) -> int | None:
        assert self.server_proc is not None
        while self.server_proc.poll() is None:
            request = _claim_operator_resume_request(self.args.operator_resume_requests_path)
            if request:
                self._run_sdk_resume(request)
                return None
            time.sleep(0.5)
        return self.server_proc.wait()

    def _run_sdk_resume(self, request: dict[str, Any]) -> None:
        attempt_index = _next_sdk_resume_attempt_index(self.run_dir)
        prompt = _resume_prompt(self.initial_kickoff_prompt, request)
        self._write_status(
            "running-sdk",
            reason=OPERATOR_HANDOFF_REASON,
            resume_available=False,
            detail=str(request.get("message_id") or ""),
        )
        self._append_handoff_resume_attempt(
            attempt_index=attempt_index,
            request=request,
            status="started",
        )
        result = OpenAIAgentsLiveRuntime().run(
            self._sdk_request(prompt=prompt, attempt_index=attempt_index)
        )
        attempt_summary = _sdk_attempt_summary(result, attempt_index=attempt_index)
        attempt_summary["recovery_action"] = "operator_handoff_resume"
        attempt_summary["recovery_reason"] = OPERATOR_HANDOFF_REASON
        attempts = list(self.live_timing.get("openai_agents_attempts") or [])
        attempts.append(attempt_summary)
        self.live_timing["openai_agents_attempts"] = attempts
        self.live_timing["openai_agents"] = {
            "phase": result.phase,
            "exit_status": result.exit_status,
            "reason": result.reason,
            "provider_reason": result.provider_reason,
            "retryable": result.retryable,
            "resume_available": result.resume_available,
            "usage": dict(result.usage),
            "trace_id": result.trace_id,
            "provider_session_id": result.provider_session_id,
        }
        if result.exit_status not in {0, None} and not (self.run_dir / "run_result.json").is_file():
            failure = _failure_from_sdk_result(
                result,
                run_dir=self.run_dir,
                timing=self.live_timing,
                profile=self.agent_sdk_perf_profile,
            )
            self._append_handoff_resume_attempt(
                attempt_index=attempt_index,
                request=request,
                status="failed",
                failure=failure.status_fields(),
            )
            raise LiveAgentRunFailure(
                f"OpenAI Agents SDK resume failed: {failure.reason}",
                failure,
            )
        self._append_handoff_resume_attempt(
            attempt_index=attempt_index,
            request=request,
            status="turn_complete",
        )

    def _finish_after_resume(self) -> int:
        assert self.server_proc is not None
        if (self.run_dir / "run_result.json").is_file():
            status = self.server_proc.wait()
            self._mark_timing("server_finished")
            self._finish_server_log_tee()
            self.server_proc = None
            if status != 0:
                reason = (
                    f"cleanup MCP server exited with status {status} after OpenAI Agents SDK resume"
                )
                self._write_status("failed", 1, reason=reason)
                self._write_live_timing("failed", 1, reason=reason)
                return 1
            self._check_result()
            self._write_live_timing("finished", 0)
            self._write_status("finished", 0)
            return 0
        if self.server_proc.poll() is None:
            self._write_status(
                "paused",
                reason=OPERATOR_HANDOFF_REASON,
                resume_available=True,
                detail=(
                    "OpenAI Agents SDK resume turn ended without done; MCP server remains alive."
                ),
            )
            return self._finish_operator_handoff()
        status = self.server_proc.wait()
        self._mark_timing("server_finished")
        self._finish_server_log_tee()
        self.server_proc = None
        reason = (
            f"cleanup MCP server exited with status {status} after OpenAI Agents SDK "
            "resume without done"
        )
        self._write_status("failed", 1, reason=reason)
        self._write_live_timing("failed", 1, reason=reason)
        return 1

    def _append_handoff_resume_attempt(
        self,
        *,
        attempt_index: int,
        request: dict[str, Any],
        status: str,
        failure: dict[str, Any] | None = None,
    ) -> None:
        attempts = list(self.live_timing.get("operator_handoff_resume_attempts") or [])
        row = {
            "schema": "operator_handoff_resume_attempt_v1",
            "agent_engine": "openai-agents-sdk",
            "attempt_index": attempt_index,
            "status": status,
            "message_id": str(request.get("message_id") or ""),
            "created_at_epoch": time.time(),
        }
        if failure:
            row["failure"] = failure
        attempts.append(row)
        self.live_timing["operator_handoff_resume_attempts"] = attempts
        (self.run_dir / "operator_handoff_resume_attempts.json").write_text(
            json.dumps(
                {
                    "schema": "operator_handoff_resume_attempts_v1",
                    "attempts": attempts,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _check_result(self) -> None:
        self._write_status("checking-result")
        self._mark_timing("checker_start")
        task_name = _household_run_id(self.args)
        task_intent = _household_intent(self.args)
        run_result = self.run_dir / "run_result.json"
        if not run_result.is_file():
            raise RuntimeError(f"live run finished without {run_result}")
        if task_intent == "open-ended":
            try:
                validate_open_ended_artifacts(run_result)
            finally:
                self._mark_timing("checker_end")
            print(f"==> report: {self.run_dir / 'report.html'}")
            return
        checker_profile = str(getattr(self.args, "checker_profile", "") or self.args.profile)
        checker_visual_args = list(self.args.checker_visual_arg)
        intent_id = household_intent_id_for_checker(task_intent=task_intent)
        checker_policy_args = checker_flags_for_household_intent(
            intent_id=intent_id,
            profile=checker_profile,
            min_generated_mess_count=self.args.min_generated_mess_count,
        )
        checker_args = [
            str(self.args.repo_root / ".venv/bin/python"),
            CHECKER_SCRIPT,
            "--expect-task",
            self.args.task,
            "--expect-task-name",
            task_name,
            "--expect-backend",
            self.args.backend,
            "--expect-policy",
            self.args.policy,
            "--expect-profile",
            checker_profile,
            "--expect-mcp-server",
            "household_world",
            "--min-generated-mess-count",
            self.args.min_generated_mess_count,
            *merge_checker_flags(checker_policy_args, checker_visual_args),
        ]
        checker_args.append(str(run_result))

        try:
            status = _run_and_tee(
                checker_args,
                cwd=self.args.repo_root,
                stdout_path=self.run_dir / "checker.log",
                stderr_path=self.run_dir / "checker.log",
                env=os.environ.copy(),
            )
        finally:
            self._mark_timing("checker_end")
        if status != 0:
            raise RuntimeError(f"cleanup checker exited with status {status}")
        print(f"==> report: {self.run_dir / 'report.html'}")

    def _mark_timing(self, name: str) -> None:
        self.live_timing[f"{name}_epoch"] = time.time()

    def _write_live_timing(
        self,
        phase: str,
        exit_status: int,
        *,
        reason: str = "",
        provider_reason: str = "",
        retryable: bool | None = None,
        resume_available: bool | None = None,
        detail: str = "",
    ) -> str:
        finished_at = time.time()
        payload = dict(self.live_timing)
        payload.update(
            {
                "phase": phase,
                "exit_status": exit_status,
                "finished_at_epoch": finished_at,
            }
        )
        if reason:
            payload["reason"] = reason
        if provider_reason:
            payload["provider_reason"] = provider_reason
        if retryable is not None:
            payload["retryable"] = retryable
        if resume_available is not None:
            payload["resume_available"] = resume_available
        if detail:
            payload["detail"] = detail
        payload["runner_timing"] = _runner_timing_breakdown(payload, finished_at)
        source_error = ""
        try:
            payload["mcp_trace_timing"] = _mcp_trace_timing(self.run_dir)
            payload["mcp_control_plane_metrics"] = _mcp_control_plane_metrics(self.run_dir)
            payload["openai_agents_event_metrics"] = _openai_agents_event_metrics(self.run_dir)
            payload["openai_agents_span_metrics"] = _openai_agents_span_metrics(self.run_dir)
            payload["model_service_fallback_metrics"] = _model_service_fallback_metrics(
                self.run_dir
            )
            payload["model_racing_observability_metrics"] = _model_racing_observability_metrics(
                self.run_dir
            )
            payload["model_input_filter_metrics"] = _model_input_filter_metrics(self.run_dir)
            payload["context_metrics"] = _context_metrics(self.run_dir, payload)
            payload["cache_metrics"] = _cache_metrics(payload["context_metrics"], payload)
            payload["context_growth_metrics"] = _context_growth_metrics(self.run_dir, payload)
            payload["model_or_sdk_unattributed_s"] = _model_or_sdk_unattributed_seconds(payload)
            payload["timeline"] = _live_timing_timeline(payload)
        except ValueError as exc:
            source_error = f"live_timing_source_error: {exc}"
            payload["live_timing_source_error"] = source_error
            if phase == "finished" and exit_status == 0:
                payload["phase"] = "failed"
                payload["exit_status"] = 1
                payload["reason"] = source_error
            payload["mcp_trace_timing"] = {"available": False, "source_error": str(exc)}
        self.timing_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        write_model_call_metrics_jsonl(
            self.run_dir / "model_call_metrics.jsonl",
            extract_model_call_metrics(self.run_dir, live_timing=payload),
        )
        return source_error

    def _cleanup_server(self) -> None:
        proc = self.server_proc
        if proc is None:
            return
        if proc.poll() is not None:
            self._finish_server_log_tee()
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        self._finish_server_log_tee()

    def _start_server_log_tee(self) -> None:
        proc = self.server_proc
        if proc is None:
            return
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return
        self.server_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.server_log_file = self.server_log_path.open("ab")
        self.server_log_thread = threading.Thread(
            target=_tee_stream,
            args=(stream, [self.server_log_file, sys.stdout.buffer]),
            daemon=True,
        )
        self.server_log_thread.start()

    def _finish_server_log_tee(self) -> None:
        thread = self.server_log_thread
        if thread is not None:
            thread.join(timeout=5)
            self.server_log_thread = None
        log_file = self.server_log_file
        if log_file is not None:
            log_file.close()
            self.server_log_file = None

    def _write_status(
        self,
        phase: str,
        exit_status: int | None = None,
        *,
        reason: str = "",
        provider_reason: str = "",
        retryable: bool | None = None,
        resume_available: bool | None = None,
        detail: str = "",
    ) -> None:
        self.status_writer.write(
            phase, exit_status, reason, provider_reason, retryable, resume_available, detail
        )


@dataclass(frozen=True)
class IncompleteTurnRecoveryPolicy:
    """Bounded recovery for SDK turns that end cleanly before MCP completion."""

    max_attempts: int
    reason: str = "incomplete_agent_turn"
    continuation_suffix: str = DEFAULT_INCOMPLETE_TURN_CONTINUATION_PROMPT

    def continuation_prompt(
        self,
        *,
        original_prompt: str,
        result: Any,
        run_dir: Path,
        attempt_index: int,
        profile: dict[str, Any] | None = None,
        context_metrics: dict[str, Any] | None = None,
    ) -> str | None:
        if self.max_attempts <= 0:
            return None
        if attempt_index >= self.max_attempts:
            return None
        if (run_dir / "run_result.json").is_file():
            return None
        context_budget_recovery = _is_context_budget_result(result)
        turn_budget_recovery = _is_turn_budget_result(result)
        budget_recovery = context_budget_recovery or turn_budget_recovery
        if getattr(result, "exit_status", None) not in {0, None} and not budget_recovery:
            return None
        if getattr(result, "phase", "") != "agent-turn-complete" and not budget_recovery:
            return None
        profile = profile or {}
        context_metrics = context_metrics or {}
        continuation_mode = str(profile.get("continuation_mode") or "repeat_full_prompt")
        total_input_tokens = _int_or_none(context_metrics.get("total_input_tokens"))
        soft_limit = _int_or_none(profile.get("context_soft_limit_tokens"))
        if (
            budget_recovery
            or continuation_mode == "state_summary_only"
            or (
                soft_limit is not None
                and total_input_tokens is not None
                and total_input_tokens >= soft_limit
            )
        ):
            return _compact_continuation_prompt(
                run_dir,
                profile=profile,
                context_metrics=context_metrics,
            )
        return f"{original_prompt.rstrip()}\n\n{self.continuation_suffix}\n"


def _is_context_budget_result(result: Any) -> bool:
    return str(getattr(result, "reason", "") or "") == "provider_context_budget_exceeded"


def _is_turn_budget_result(result: Any) -> bool:
    return str(getattr(result, "reason", "") or "") == "agent_sdk_turn_budget_exceeded"


def _continuation_recovery_reason(
    *,
    context_budget_recovery: bool,
    turn_budget_recovery: bool,
    default_reason: str,
) -> str:
    if context_budget_recovery:
        return "context_budget_compact_continuation"
    if turn_budget_recovery:
        return "turn_budget_compact_continuation"
    return default_reason


def _profiled_kickoff_prompt(args: argparse.Namespace, *, profile: dict[str, Any]) -> str:
    original = str(getattr(args, "kickoff_prompt", "") or "")
    lane = str(getattr(args, "profile", "") or "")
    composite_tools = camera_grounded_composite_tools_enabled_for_run(
        profile,
        evidence_lane=lane,
    )
    if _prompt_already_matches_profile(
        original,
        camera_grounded_composite_tools=composite_tools,
    ):
        return original
    intent = _household_intent(args)
    can_render = lane in {"world-public-labels", "camera-grounded-labels", "camera-raw-fpv"}
    if not can_render:
        return original
    if intent == "map-build":
        try:
            return render_map_build_prompt(
                lane,
                str(getattr(args, "task", "") or "build a Runtime Metric Map of this room"),
                camera_grounded_composite_tools=composite_tools,
                max_observe_per_waypoint=_int_or_none(profile.get("max_observe_per_waypoint")),
            )
        except ValueError:
            return original
    if intent != "cleanup":
        return original
    target_cleanup_count = _target_cleanup_count_for_prompt(args, lane=lane)
    try:
        return render_kickoff_prompt(
            lane,
            task=str(getattr(args, "task", "") or ""),
            target_cleanup_count=target_cleanup_count,
            intent=intent,
            goal_contract=None,
            raw_fpv_candidate_budget=int(profile.get("raw_fpv_candidate_budget") or 24),
            max_observe_per_waypoint=int(profile.get("max_observe_per_waypoint") or 1),
            done_retry_budget=int(profile.get("done_retry_budget") or 1),
            camera_grounded_composite_tools=composite_tools,
        )
    except ValueError:
        return original


def _target_cleanup_count_for_prompt(args: argparse.Namespace, *, lane: str) -> int:
    raw_count = str(getattr(args, "min_generated_mess_count", "") or "")
    try:
        count = int(raw_count)
    except ValueError:
        count = 7
    if lane == "camera-raw-fpv":
        return max(1, (count * 7 + 9) // 10)
    return max(1, count)


def _kickoff_prompt_source(args: argparse.Namespace, profile: dict[str, Any]) -> str:
    original = str(getattr(args, "kickoff_prompt", "") or "")
    composite_tools = camera_grounded_composite_tools_enabled_for_run(
        profile,
        evidence_lane=str(getattr(args, "profile", "") or ""),
    )
    if _prompt_already_matches_profile(
        original,
        camera_grounded_composite_tools=composite_tools,
    ):
        return "provided-lane-default"
    rendered = _profiled_kickoff_prompt(args, profile=profile)
    if rendered == original:
        return "provided"
    return "profile-rendered-lane-default"


def _prompt_already_matches_profile(
    prompt: str, *, camera_grounded_composite_tools: bool = False
) -> bool:
    marker = "observe_camera_grounded_candidates instead of a"
    if camera_grounded_composite_tools:
        return marker in prompt
    return marker not in prompt and (
        "Compact action cadence for world-public-labels" in prompt
        or "Compact action cadence for camera-grounded-labels" in prompt
        or "Compact action cadence for camera-raw-fpv" in prompt
    )


def _budget_failure_from_run_state(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure | None:
    context_failure = _context_budget_failure(run_dir, timing, profile)
    if context_failure is not None:
        return context_failure
    return _raw_fpv_budget_failure(run_dir, timing, profile)


def _failure_from_sdk_result(
    result: Any,
    *,
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure:
    if (
        str(getattr(result, "reason", "") or "") == "agent_sdk_turn_budget_exceeded"
        and str(timing.get("evidence_lane") or timing.get("profile") or "") == "camera-raw-fpv"
    ):
        context_metrics = _context_metrics(run_dir, timing)
        detail = json.dumps(
            {
                "schema": "agent_sdk_raw_fpv_budget_terminal_v1",
                "profile_id": profile.get("profile_id") or "baseline",
                "reason": "raw_fpv_sdk_turn_budget_exhausted",
                "max_turns": profile.get("max_turns"),
                "context_hard_limit_tokens": profile.get("context_hard_limit_tokens"),
                "max_input_tokens": context_metrics.get("max_input_tokens"),
                "total_input_tokens": context_metrics.get("total_input_tokens"),
                "total_uncached_input_tokens": context_metrics.get("total_uncached_input_tokens"),
                "response_span_count": context_metrics.get("response_span_count"),
            },
            sort_keys=True,
        )
        return LiveAgentFailure(
            "raw_fpv_sdk_turn_budget_exhausted",
            retryable=False,
            resume_available=False,
            detail=detail,
        )
    return LiveAgentFailure(
        reason=getattr(result, "reason", "") or "agent_cli_failure",
        retryable=bool(getattr(result, "retryable", False)),
        provider_reason=getattr(result, "provider_reason", ""),
        resume_available=bool(getattr(result, "resume_available", False)),
        detail=getattr(result, "detail", ""),
    )


def _explicit_operator_handoff_requested(args: argparse.Namespace) -> str:
    parts = [
        str(getattr(args, "task", "") or ""),
        str(getattr(args, "kickoff_prompt", "") or ""),
    ]
    text = _normalized_handoff_text("\n".join(part for part in parts if part))
    if not text:
        return ""
    has_manual_marker = any(marker in text for marker in OPERATOR_HANDOFF_MARKERS)
    has_wait_marker = any(marker in text for marker in OPERATOR_HANDOFF_WAIT_MARKERS)
    if not (has_manual_marker and has_wait_marker):
        return ""
    return (
        "OpenAI Agents SDK ended without done after an explicit operator handoff request. "
        "The MCP server remains alive for operator-console manual control."
    )


def _claim_operator_resume_request(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    result = consume_resume_request_for_runner(path.parent)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error_reason") or "operator resume source error"))
    requests = result.get("requests")
    if isinstance(requests, list) and requests:
        request = requests[0]
        return request if isinstance(request, dict) else {}
    return {}


def _resume_prompt(original_prompt: str, request: dict[str, Any]) -> str:
    packet = request.get("resume_request_packet")
    public_packet = packet if isinstance(packet, dict) else {}
    return (
        f"{original_prompt.rstrip()}\n\n"
        "Paused operator handoff resume for the same live MCP run:\n"
        "The operator has manually adjusted or inspected the robot and now requests a "
        "new agent turn. Use current public MCP state, preserve the existing run trace, "
        "and do not consume queued Steer messages as resume input. Call task-relevant "
        "MCP tools, then call done only when the public task is complete.\n\n"
        f"resume_request_packet:\n{json.dumps(public_packet, ensure_ascii=False, sort_keys=True)}\n"
    )


def _next_sdk_resume_attempt_index(run_dir: Path) -> int:
    return 1 + len(list(run_dir.glob("openai-agents-events.resume-*.jsonl")))


def _normalized_handoff_text(text: str) -> str:
    lowered = text.lower()
    for char in "`'\"“”‘’[](){}<>":
        lowered = lowered.replace(char, " ")
    return " ".join(lowered.split())


def _wait_for_terminal_phase_from_status(status_path: Path, *, timeout_s: float = 2.0) -> str:
    deadline = time.monotonic() + timeout_s
    while True:
        phase = _phase_from_status(status_path)
        if phase in {
            "finished",
            "failed",
            "stopped_by_operator",
            "human_takeover_stop",
            "emergency_stopped",
        }:
            return phase
        if time.monotonic() >= deadline:
            return phase
        time.sleep(0.05)


def _phase_from_status(status_path: Path) -> str:
    if not status_path.is_file():
        return ""
    payload = read_json_value(status_path, label="OpenAI Agents live status")
    if not isinstance(payload, dict):
        raise ValueError(
            f"OpenAI Agents live status must contain a JSON object, got {type(payload).__name__}"
        )
    return str(payload.get("phase") or "").strip().lower()


def _context_budget_failure(
    run_dir: Path,
    timing: dict[str, Any],
    profile: dict[str, Any],
) -> LiveAgentFailure | None:
    return _shared_context_budget_failure(run_dir, timing, profile)


def _compact_continuation_prompt(
    run_dir: Path,
    *,
    profile: dict[str, Any],
    context_metrics: dict[str, Any],
) -> str:
    state = _compact_continuation_state(
        run_dir,
        profile=profile,
        context_metrics=context_metrics,
    )
    profile_guidance = _compact_continuation_profile_guidance(profile)
    profile_guidance_section = f"\n\n{profile_guidance}" if profile_guidance else ""
    intent = str(state.get("intent") or "cleanup")
    task_guidance = _compact_continuation_task_guidance(intent)
    return (
        f"Continuation recovery for the same live household {intent} run.\n\n"
        "Use this compact public state packet instead of replaying the original "
        "kickoff prompt. Do not summarize progress as a final answer. "
        f"{task_guidance} "
        "Call done only after MCP-visible public state satisfies the task. "
        "The runner will count success only when MCP done produces run_result.json."
        f"{profile_guidance_section}\n\n"
        f"compact_continuation_state:\n{json.dumps(state, ensure_ascii=False, sort_keys=True)}\n"
    )


def _compact_continuation_task_guidance(intent: str) -> str:
    if intent == "map-build":
        return (
            "Continue only missing public map sweep and Runtime Metric Map evidence work. "
            "Do not pick, place, or perform cleanup manipulation for a map-build task. "
            "Use completed_waypoints and latest_done_blockers before requesting fresh MCP state."
        )
    if intent == "open-ended":
        return (
            "Preserve goal_summary and continue only the missing search, inspection, or "
            "task-relevant action. Do not switch into whole-room cleanup unless the goal asks "
            "for cleanup."
        )
    return (
        "Continue missing cleanup work in this order: first finish held entries in "
        "actionable_pending_candidates using their destination_options; then advance pending "
        "entries with their required_tool; then continue the public sweep at "
        "next_unvisited_waypoint. Do not broad re-sweep while an actionable held or pending "
        "candidate remains."
    )


def _compact_continuation_profile_guidance(profile: dict[str, Any]) -> str:
    if profile.get("raw_fpv_candidate_budget") is not None:
        return (
            "RAW-FPV continuation: if latest_done_blockers is non-empty, do not call done "
            "again until its public current values reach required or trace-reconciled progress "
            "shows a new completion chain. A heading-coverage blocker has first priority: use "
            "remaining_observes_by_waypoint and visit only a waypoint whose remaining count is "
            "positive until that blocker is resolved. Do not consume raw_fpv_revisit_waypoints "
            "while a heading-coverage blocker remains. Do not broad re-sweep exhausted "
            "waypoints; the bounded raw_fpv_revisit_waypoints pass below is the only exception. "
            "If latest_done_blockers contains insufficient_raw_fpv_overlap_probe_coverage, "
            "follow its next_waypoint_id and required_camera_adjustment exactly: navigate there, "
            "call adjust_camera(yaw_delta_deg=45, pitch_delta_deg=20) once, then observe the "
            "fresh diagonal overlap view even when the normal waypoint observe count is exhausted. "
            "If latest_done_blockers contains insufficient_raw_fpv_heading_coverage, follow "
            "its next_waypoint_id and stay at that waypoint for a complete deterministic body "
            "sweep: observe the canonical pose, then call "
            "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=90) followed by "
            "observe three consecutive times before leaving. Do not return to canonical or switch "
            "waypoints after only one relative rotation. Treat remaining_observes_by_waypoint as "
            "the public distinct-heading deficit, not a hard cap on recovery observations. "
            "After heading coverage is complete, if insufficient_grounded_cleanup_chains still "
            "remains and no held or pending candidate exists, visit raw_fpv_revisit_waypoints in "
            "order. This is a bounded public recovery pass over otherwise scan-exhausted "
            "waypoints: visit each listed waypoint at most once, call "
            "navigate_to_relative_pose(forward_m=0, lateral_m=0, yaw_delta_deg=45) once, then "
            "observe exactly one fresh diagonal view. Act only on a high-confidence candidate in "
            "that fresh observation, never copy an old source observation, bbox, or public "
            "candidate id, and stop the pass when the public chain gate is met or the list is "
            "exhausted. Do not revisit waypoints absent from that list. "
            "Prefer candidate_free_scan_waypoints in the "
            "listed most-recently-observed-first order before revisiting waypoints that already "
            "produced candidate attempts; this preserves the latest FPV context and current pose. "
            "An empty default FPV view is not evidence that the whole room is clear. Act on each "
            "fresh high-confidence visible candidate "
            "with navigate_to_visual_candidate and complete its pick/place chain. "
            + raw_fpv_edge_reframe_instruction()
            + " Respect raw_fpv_candidate_budget.remaining and do not retry entries "
            "listed in recent_failed_candidate_attempts. Do not call "
            "metric_map again when completed_waypoints already contains the public checklist."
        )
    composite = profile.get("camera_grounded_composite_tools")
    if not isinstance(composite, dict) or not bool(composite.get("enabled")):
        return ""
    tool_names = composite.get("tool_names")
    if not isinstance(tool_names, list) or "observe_camera_grounded_candidates" not in tool_names:
        return ""
    return (
        "Camera-grounded composite continuation: keep using "
        "observe_camera_grounded_candidates for remaining waypoint observations. "
        "Do not resume the older observe plus declare_visual_candidates cadence, and "
        "do not call declare_visual_candidates again for a source_observation_id "
        "already handled by observe_camera_grounded_candidates unless a public tool "
        "explicitly asks for it."
    )


def _compact_continuation_state(
    run_dir: Path,
    *,
    profile: dict[str, Any],
    context_metrics: dict[str, Any],
) -> dict[str, Any]:
    trace_events = _read_jsonl_path(run_dir / "trace.jsonl")
    goal_contract = _goal_contract_summary(trace_events)
    completed_waypoints = _completed_waypoints(trace_events)
    handled_objects = _handled_object_handles(trace_events)
    public_pending = _public_pending_object_handles(trace_events)
    blocked_candidates = _blocked_candidates(trace_events)
    recent_failures = _recent_tool_failures(trace_events)
    observe_counts = _observe_counts_by_waypoint(trace_events)
    latest_done_blockers = _latest_done_blockers(trace_events)
    latest_done_action_state = _latest_done_public_action_state(trace_events)
    budget_metrics = _raw_fpv_budget_metrics(trace_events)
    max_observes = _int_or_none(profile.get("max_observe_per_waypoint"))
    known_waypoints = _inspection_waypoint_ids(trace_events) or list(observe_counts)
    remaining_observes = remaining_observes_by_waypoint(
        known_waypoints,
        observe_counts,
        max_observes=max_observes,
    )
    reconcile_remaining_observes_with_heading_blocker(
        remaining_observes,
        latest_done_blockers,
    )
    candidate_attempt_counts = candidate_attempt_counts_by_waypoint(trace_events)
    candidate_outcomes = candidate_outcomes_by_waypoint(trace_events, known_waypoints)
    scan_priority = waypoints_by_observation_recency(trace_events)
    scan_priority.extend(
        waypoint_id for waypoint_id in known_waypoints if waypoint_id not in scan_priority
    )
    candidate_free_waypoints = [
        waypoint_id
        for waypoint_id in scan_priority
        if remaining_observes.get(waypoint_id) != 0
        and candidate_attempt_counts.get(waypoint_id, 0) == 0
    ]
    exhausted_waypoints = [
        waypoint_id for waypoint_id, remaining in remaining_observes.items() if remaining == 0
    ]
    candidate_limit = _int_or_none(profile.get("raw_fpv_candidate_budget"))
    candidate_attempted = int(budget_metrics.get("candidate_attempt_count") or 0)
    revisit_waypoints = raw_fpv_revisit_waypoints(
        trace_events,
        known_waypoints=known_waypoints,
        candidate_outcomes=candidate_outcomes,
        latest_done_blockers=latest_done_blockers,
        has_pending_candidates=bool(
            public_pending or latest_done_action_state["actionable_pending_candidates"]
        ),
    )
    return {
        "schema": "compact_agent_state_v1",
        "surface": goal_contract.get("surface") or "household-world",
        "intent": goal_contract.get("intent") or "cleanup",
        "evidence_lane": _trace_field(trace_events, "evidence_lane")
        or _trace_field(trace_events, "cleanup_profile"),
        "goal_summary": goal_contract.get("normalized_goal") or "",
        "agent_sdk_perf_profile_id": profile.get("profile_id") or "baseline",
        "completed_waypoints": completed_waypoints[-32:],
        "handled_object_handles": handled_objects[-32:],
        "public_pending_object_handles": public_pending[-32:],
        "blocked_candidates": blocked_candidates[-12:],
        "recent_tool_failures": recent_failures[-8:],
        "observe_counts_by_waypoint": observe_counts,
        "candidate_attempt_counts_by_waypoint": candidate_attempt_counts,
        "raw_fpv_waypoint_candidate_outcomes": candidate_outcomes,
        "raw_fpv_revisit_waypoints": revisit_waypoints,
        "candidate_free_scan_waypoints": candidate_free_waypoints,
        "remaining_observes_by_waypoint": remaining_observes,
        "scan_exhausted_waypoints": exhausted_waypoints,
        "raw_fpv_candidate_budget": {
            "attempted": candidate_attempted,
            "limit": candidate_limit,
            "remaining": max(0, candidate_limit - candidate_attempted)
            if candidate_limit is not None
            else None,
        },
        "recent_failed_candidate_attempts": _compact_failed_candidate_attempts(
            budget_metrics.get("failed_candidate_attempts_sample") or []
        ),
        "latest_done_blockers": latest_done_blockers,
        "actionable_pending_candidates": latest_done_action_state["actionable_pending_candidates"],
        "next_unvisited_waypoint": latest_done_action_state["next_unvisited_waypoint"],
        "unvisited_waypoint_ids": latest_done_action_state["unvisited_waypoint_ids"],
        "remaining_public_gates": _remaining_public_gates(completed_waypoints, public_pending),
        "next_requested_action": _next_requested_action(
            completed_waypoints,
            public_pending,
            actionable_pending=latest_done_action_state["actionable_pending_candidates"],
            next_unvisited_waypoint=latest_done_action_state["next_unvisited_waypoint"],
        ),
        "context_metrics": _compact_metric_group(context_metrics),
    }


def _observe_counts_by_waypoint(trace_events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        waypoint_id = str(response.get("waypoint_id") or "")
        if waypoint_id:
            counts[waypoint_id] = counts.get(waypoint_id, 0) + 1
    return dict(sorted(counts.items()))


def _latest_done_blockers(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    event_index, blockers = latest_done_completion_blockers(trace_events)
    if event_index is None:
        return []
    normalized = [
        {
            key: blocker[key]
            for key in (
                "type",
                "current",
                "required",
                "required_tool",
                "next_waypoint_id",
                "policy_id",
                "sweep_coverage_rate",
                "observed_waypoint_count",
                "total_waypoints",
                "current_distinct_heading_count",
                "required_distinct_heading_count",
                "distinct_heading_counts_by_waypoint",
                "incomplete_waypoint_ids",
                "followup_tool",
                "required_camera_adjustment",
                "candidate_free_waypoint_ids",
                "probed_candidate_free_waypoint_ids",
                "recovery_hint",
            )
            if key in blocker
        }
        for blocker in blockers
    ]
    progress_after_done = len(_successful_placement_handles(trace_events[event_index + 1 :]))
    if progress_after_done:
        _reconcile_grounded_chain_progress(normalized, progress_after_done)
    return normalized


def _reconcile_grounded_chain_progress(
    blockers: list[dict[str, Any]], progress_after_done: int
) -> None:
    for blocker in blockers:
        if blocker.get("type") != "insufficient_grounded_cleanup_chains":
            continue
        current = _int_or_none(blocker.get("current"))
        required = _int_or_none(blocker.get("required"))
        if current is None:
            continue
        blocker["current"] = (
            min(required, current + progress_after_done)
            if required
            else (current + progress_after_done)
        )
        blocker["progress_since_latest_done"] = progress_after_done
        blocker["progress_source"] = "trace_reconciled_after_done"


def _latest_done_public_action_state(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    _, blockers = latest_done_completion_blockers(trace_events)
    pending_blockers = [
        item for item in blockers if item.get("type") == "pending_cleanup_candidates"
    ]
    pending = [
        candidate
        for blocker in pending_blockers
        for candidates in [blocker.get("pending_cleanup_candidates")]
        if isinstance(candidates, list)
        for candidate in candidates
        if isinstance(candidate, dict)
    ]
    sweep = next(
        (item for item in blockers if item.get("type") == "insufficient_sweep_coverage"),
        {},
    )
    raw_unvisited = sweep.get("unvisited_waypoint_ids")
    unvisited_waypoints = (
        [str(item) for item in raw_unvisited if str(item)][:32]
        if isinstance(raw_unvisited, list)
        else []
    )
    next_waypoint = str(sweep.get("next_waypoint_id") or "")
    if not next_waypoint and unvisited_waypoints:
        next_waypoint = unvisited_waypoints[0]
    return {
        "actionable_pending_candidates": _public_actionable_pending_candidates(pending),
        "next_unvisited_waypoint": next_waypoint,
        "unvisited_waypoint_ids": unvisited_waypoints,
    }


def _public_actionable_pending_candidates(
    pending: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in pending:
        public_id = str(candidate.get("object_id") or "")
        if not public_id or public_id in seen_ids:
            continue
        seen_ids.add(public_id)
        item = {
            key: candidate[key]
            for key in (
                "object_id",
                "category",
                "state",
                "candidate_state",
                "required_tool",
            )
            if key in candidate
        }
        options = candidate.get("destination_options")
        if isinstance(options, list):
            item["destination_options"] = [
                {
                    key: option[key]
                    for key in (
                        "candidate_fixture_id",
                        "candidate_fixture_category",
                        "recommended_tool",
                        "candidate_source",
                        "waypoint_id",
                    )
                    if key in option
                }
                for option in options[:8]
                if isinstance(option, dict)
            ]
        sanitized.append(item)
        if len(sanitized) >= 12:
            break
    sanitized.sort(key=lambda item: 0 if item.get("state") == "held" else 1)
    return sanitized


def _inspection_waypoint_ids(trace_events: list[dict[str, Any]]) -> list[str]:
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "metric_map":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        raw_waypoints = response.get("inspection_waypoints")
        if not isinstance(raw_waypoints, list):
            continue
        return [
            str(item.get("waypoint_id") or "")
            for item in raw_waypoints
            if isinstance(item, dict) and item.get("waypoint_id")
        ]
    return []


def _compact_failed_candidate_attempts(
    attempts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "source_observation_id": str(item.get("source_observation_id") or ""),
            "waypoint_id": str(item.get("waypoint_id") or ""),
            "category": str(item.get("category") or ""),
            "region": str(item.get("region") or ""),
            "error_reason": str(item.get("failure_reason") or "tool_failed"),
        }
        for item in attempts[-12:]
        if isinstance(item, dict)
    ]


def _successful_placement_handles(trace_events: list[dict[str, Any]]) -> list[str]:
    handles: list[str] = []
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") not in {"place", "place_inside"}:
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        handle = str(response.get("object_id") or response.get("held_object_id") or "")
        if handle and handle not in handles:
            handles.append(handle)
    return handles


def _goal_contract_summary(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in trace_events:
        goal_contract = event.get("goal_contract")
        if isinstance(goal_contract, dict):
            return {
                "surface": goal_contract.get("surface"),
                "intent": goal_contract.get("intent"),
                "normalized_goal": goal_contract.get("normalized_goal"),
                "goal_scope": goal_contract.get("goal_scope"),
            }
    return {}


def _trace_field(trace_events: list[dict[str, Any]], field: str) -> str:
    for event in trace_events:
        value = event.get(field)
        if value:
            return str(value)
    return ""


def _completed_waypoints(trace_events: list[dict[str, Any]]) -> list[str]:
    completed: list[str] = []
    for event in trace_events:
        if event.get("event") != "response" or event.get("tool") != "observe":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is not True:
            continue
        waypoint_id = str(response.get("waypoint_id") or "")
        if waypoint_id and waypoint_id not in completed:
            completed.append(waypoint_id)
    return completed


def _handled_object_handles(trace_events: list[dict[str, Any]]) -> list[str]:
    return _successful_placement_handles(trace_events)


def _public_pending_object_handles(trace_events: list[dict[str, Any]]) -> list[str]:
    pending: list[str] = []
    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        pending_candidates = response.get("pending_cleanup_candidates")
        if not isinstance(pending_candidates, list):
            continue
        for item in pending_candidates:
            if not isinstance(item, dict):
                continue
            public_id = str(
                item.get("object_id") or item.get("public_id") or item.get("handle") or ""
            )
            if public_id and public_id not in pending:
                pending.append(public_id)
    return pending


def _blocked_candidates(trace_events: list[dict[str, Any]]) -> list[dict[str, str]]:
    blocked: list[dict[str, str]] = []
    for event in trace_events:
        if event.get("event") != "response":
            continue
        tool = str(event.get("tool") or "")
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        status = str(response.get("status") or "")
        ok = response.get("ok")
        if ok is not False and status not in {"blocked", "failed", "error"}:
            continue
        public_id = str(
            response.get("object_id")
            or response.get("candidate_id")
            or response.get("public_id")
            or response.get("source_observation_id")
            or ""
        )
        reason = str(
            response.get("error_reason")
            or response.get("failure_reason")
            or response.get("reason")
            or response.get("error")
            or status
            or "tool_failed"
        )
        item = {
            "public_id": public_id,
            "reason": reason[:160],
            "last_failure_tool": tool,
        }
        if item not in blocked:
            blocked.append(item)
    return blocked


def _recent_tool_failures(trace_events: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        ok = response.get("ok")
        status = str(response.get("status") or "")
        if ok is not False and status not in {"blocked", "failed", "error"}:
            continue
        failures.append(
            {
                "tool": str(event.get("tool") or ""),
                "public_error_class": status or "tool_failed",
                "public_target": str(
                    response.get("object_id")
                    or response.get("candidate_id")
                    or response.get("waypoint_id")
                    or response.get("source_observation_id")
                    or ""
                ),
            }
        )
    return failures


def _remaining_public_gates(completed_waypoints: list[str], pending: list[str]) -> list[str]:
    gates: list[str] = []
    if not completed_waypoints:
        gates.append("inspect public waypoint checklist with metric_map and observe waypoints")
    if pending:
        gates.append("clean public pending handles returned by done")
    gates.append("call done only after public cleanup gates are satisfied")
    return gates


def _next_requested_action(
    completed_waypoints: list[str],
    pending: list[str],
    *,
    actionable_pending: list[dict[str, Any]] | None = None,
    next_unvisited_waypoint: str = "",
) -> str:
    actionable_pending = actionable_pending or []
    if any(item.get("state") == "held" for item in actionable_pending):
        return "finish held candidates using public destination_options before other work"
    if actionable_pending or pending:
        return "clean the public pending handles before broad re-sweep"
    if next_unvisited_waypoint:
        return f"navigate_to_waypoint({next_unvisited_waypoint}), then observe"
    if not completed_waypoints:
        return "call metric_map, navigate_to_waypoint, then observe"
    return "inspect public MCP state, finish missing objects or waypoints, then call done"


def _sdk_attempt_summary(result: Any, *, attempt_index: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "attempt_index": attempt_index,
        "attempt_role": "continuation" if attempt_index else "initial",
        "phase": getattr(result, "phase", ""),
        "exit_status": getattr(result, "exit_status", None),
        "reason": getattr(result, "reason", ""),
        "provider_reason": getattr(result, "provider_reason", ""),
        "run_result_present": bool(getattr(result, "run_result_present", False)),
        "trace_id": getattr(result, "trace_id", ""),
        "provider_session_id": getattr(result, "provider_session_id", ""),
    }
    started = _float_or_none(getattr(result, "started_at_epoch", None))
    finished = _float_or_none(getattr(result, "finished_at_epoch", None))
    if started is not None:
        payload["started_at_epoch"] = started
    if finished is not None:
        payload["finished_at_epoch"] = finished
    if started is not None and finished is not None:
        payload["elapsed_s"] = _round_duration(finished - started)
    return payload


def _run_and_tee(
    command: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str],
) -> int:
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    with stdout_path.open("ab") as stdout_file:
        if stdout_path == stderr_path:
            stderr_thread = threading.Thread(
                target=_tee_stream,
                args=(proc.stderr, [stdout_file, sys.stderr.buffer]),
                daemon=True,
            )
            stdout_thread = threading.Thread(
                target=_tee_stream,
                args=(proc.stdout, [stdout_file, sys.stdout.buffer]),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            status = proc.wait()
            stdout_thread.join()
            stderr_thread.join()
            return status

        with stderr_path.open("ab") as stderr_file:
            stdout_thread = threading.Thread(
                target=_tee_stream,
                args=(proc.stdout, [stdout_file, sys.stdout.buffer]),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_tee_stream,
                args=(proc.stderr, [stderr_file, sys.stderr.buffer]),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            status = proc.wait()
            stdout_thread.join()
            stderr_thread.join()
            return status


def _task_aware_continuation_suffix(args: Any) -> str:
    task_intent = _household_intent(args)
    intent = household_intent_id_for_checker(
        task_intent=task_intent,
        open_ended_task=task_intent == "open-ended",
    )
    task = " ".join(str(getattr(args, "task", "") or "").split())
    preset = os.environ.get("ROBOCLAWS_TASK_PRESET", "")
    selected = "surface=household-world"
    if preset:
        selected += f" preset={preset}"
    elif intent != "open-ended":
        selected += f" preset={intent}"
    if intent == "open-ended":
        return (
            f"Continuation recovery for the same live household open-task run ({selected}):\n\n"
            "The previous OpenAI Agents SDK invocation ended without calling `done`, so no "
            "`run_result.json` was produced. Continue from the current household MCP server "
            "state. Preserve the operator goal"
            + (f": {task}" if task else ".")
            + " Do not switch into a room-cleanup routine unless the operator goal itself "
            "requires cleanup. First inspect public MCP state as needed, then continue only "
            "the missing search, inspection, manipulation, or completion steps needed for "
            "that goal. Call `done` when the public evidence supports task completion."
        )
    return (
        f"Continuation recovery for the same live household preset run ({selected}):\n\n"
        "The previous OpenAI Agents SDK invocation ended without calling `done`, so no "
        "`run_result.json` was produced. Continue from the current household MCP server "
        "state. Do not summarize progress as a final answer. First inspect the current "
        "runtime state through public tools, then continue only missing preset-specific "
        "steps. Call `done` only after MCP-visible task state satisfies the selected "
        "preset instructions."
    )


def _estimated_tokens_from_chars(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, round(char_count / 4))


def _read_jsonl_path(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return read_jsonl_objects(path, label="OpenAI Agents live")


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tee_stream(stream: BinaryIO, outputs: list[BinaryIO]) -> None:
    for chunk in iter(lambda: stream.readline(), b""):
        for output in outputs:
            try:
                output.write(chunk)
                output.flush()
            except BlockingIOError:
                continue


def _port_accepting(host: str, port: int, *, timeout_s: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _probe_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


if __name__ == "__main__":
    raise SystemExit(main())
