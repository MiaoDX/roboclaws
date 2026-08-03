"""Lifecycle orchestration for household OpenAI Agents SDK runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO

from roboclaws.agents.drivers import household_live as household_live_driver
from roboclaws.agents.drivers.household_live import (
    HouseholdLiveRunLease,
    acquire_household_live_run_lease,
    household_server_argv,
)
from roboclaws.agents.drivers.openai_agents_artifact_metrics import (
    openai_agents_event_metrics as _openai_agents_event_metrics,
)
from roboclaws.agents.drivers.openai_agents_artifact_metrics import (
    openai_agents_span_metrics as _openai_agents_span_metrics,
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
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    camera_grounded_composite_tools_enabled_for_run,
)
from roboclaws.agents.drivers.openai_agents_perf_profile import (
    resolve_agent_sdk_perf_profile as _resolve_agent_sdk_perf_profile,
)
from roboclaws.agents.household_live_config import (
    _estimated_tokens_from_chars,
    _load_agent_sdk_skill_context,
    _skill_context_timing_summary,
    _stable_prefix_packet,
)
from roboclaws.agents.household_live_continuation import (
    IncompleteTurnRecoveryPolicy,
    _continuation_recovery_reason,
    _is_context_budget_result,
    _is_turn_budget_result,
    _kickoff_prompt_source,
    _profiled_kickoff_prompt,
    _sdk_attempt_summary,
    _task_aware_continuation_suffix,
)
from roboclaws.agents.household_live_errors import LiveAgentRunFailure
from roboclaws.agents.household_live_handoff import HouseholdLiveHandoffMixin
from roboclaws.agents.live_status_writer import LiveRunStatusWriter
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
from roboclaws.core.evaluation import checker_flags_for_household_intent
from roboclaws.core.live_performance import (
    extract_model_call_metrics,
    write_model_call_metrics_jsonl,
)
from roboclaws.core.open_ended_artifacts import validate_open_ended_artifacts
from roboclaws.core.robot_view_capture import ROBOT_VIEW_CAPTURE_POLICY_FULL
from roboclaws.core.task_intents import (
    household_intent_from_args as _household_intent,
)
from roboclaws.core.task_intents import (
    household_task_name_from_args as _household_run_id,
)

CHECKER_MODULE = "roboclaws.household.cleanup_validation_cli"
REPORT_RERUN_COMMAND_ENV = "ROBOCLAWS_REPORT_RERUN_COMMAND"


class LiveOpenAIAgentsHouseholdRunner(HouseholdLiveHandoffMixin):
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

        probe_host = household_live_driver.probe_host(self.args.host)
        if household_live_driver.port_accepting(probe_host, self.args.port):
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
        probe_host = household_live_driver.probe_host(self.args.host)
        deadline = time.monotonic() + self.args.server_startup_timeout_s
        while time.monotonic() < deadline:
            if self.server_proc.poll() is not None:
                raise RuntimeError("cleanup MCP server exited before becoming ready")
            if household_live_driver.port_accepting(probe_host, self.args.port):
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
        checker_policy_args = checker_flags_for_household_intent(
            intent_id=task_intent or "cleanup",
            profile=checker_profile,
            min_generated_mess_count=self.args.min_generated_mess_count,
        )
        checker_args = [
            str(self.args.repo_root / ".venv/bin/python"),
            "-m",
            CHECKER_MODULE,
            "--expect-task",
            self.args.task,
            "--expect-task-name",
            task_name,
            "--expect-backend",
            self.args.backend,
            "--expect-policy",
            self.args.policy,
            *([] if checker_profile == "smoke" else ["--expect-profile", checker_profile]),
            "--expect-mcp-server",
            "household_world",
            "--min-generated-mess-count",
            self.args.min_generated_mess_count,
            *checker_policy_args,
            *checker_visual_args,
        ]
        checker_args.append(str(run_result))

        try:
            status = household_live_driver.run_and_tee(
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
            target=household_live_driver.tee_stream,
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
