"""Operator handoff lifecycle for household SDK runs."""

from __future__ import annotations

import json
import time
from typing import Any

from roboclaws.agents.drivers.openai_agents_budget import (
    raw_fpv_budget_failure as _raw_fpv_budget_failure,
)
from roboclaws.agents.drivers.openai_agents_live import OpenAIAgentsLiveRuntime
from roboclaws.agents.household_live_continuation import (
    _claim_operator_resume_request,
    _explicit_operator_handoff_requested,
    _failure_from_sdk_result,
    _next_sdk_resume_attempt_index,
    _resume_prompt,
    _sdk_attempt_summary,
    _wait_for_terminal_phase_from_status,
)
from roboclaws.agents.household_live_errors import LiveAgentRunFailure
from roboclaws.agents.live_runtime import LiveAgentMCPServer, LiveAgentRequest
from roboclaws.core.task_intents import household_intent_from_args as _household_intent
from roboclaws.core.task_intents import household_task_name_from_args as _household_run_id

OPERATOR_HANDOFF_REASON = "operator_handoff_requested"


class HouseholdLiveHandoffMixin:
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
                "model_visible_tool_surface": self.live_timing.get(
                    "model_visible_tool_surface", []
                ),
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
