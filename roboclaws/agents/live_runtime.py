"""Provider-neutral contract for live-agent runtime turns."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from roboclaws.agents.live_status import LiveAgentFailure
from roboclaws.core.json_sources import json_source_type_name, read_json_object


@dataclass(frozen=True)
class LiveAgentMCPServer:
    """The MCP server endpoint exposed to a live agent runtime."""

    name: str
    url: str
    transport: str = "streamable_http"


@dataclass(frozen=True)
class LiveAgentRequest:
    """Inputs that are owned by the launcher/runtime boundary, not the task strategy."""

    run_id: str
    skill_name: str
    kickoff_prompt: str
    mcp_server: LiveAgentMCPServer
    run_dir: Path
    model: str = ""
    provider_profile: str = ""
    max_turns: int | None = None
    one_turn: bool = True
    timeout_s: float | None = None
    idle_timeout_s: float | None = None
    artifact_paths: Mapping[str, Path] = field(default_factory=dict)
    session_token: str = ""
    resume_token: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("LiveAgentRequest.run_id is required")
        if not self.skill_name:
            raise ValueError("LiveAgentRequest.skill_name is required")
        if not self.mcp_server.name:
            raise ValueError("LiveAgentRequest.mcp_server.name is required")
        if not self.mcp_server.url:
            raise ValueError("LiveAgentRequest.mcp_server.url is required")
        if self.max_turns is not None and self.max_turns < 1:
            raise ValueError("LiveAgentRequest.max_turns must be >= 1")
        if self.timeout_s is not None and self.timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        if self.idle_timeout_s is not None and self.idle_timeout_s < 0:
            raise ValueError("idle_timeout_s must be non-negative")
        object.__setattr__(self, "run_dir", Path(self.run_dir))
        object.__setattr__(
            self,
            "artifact_paths",
            {name: Path(path) for name, path in self.artifact_paths.items()},
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def artifact_path(self, name: str, default_filename: str) -> Path:
        """Return an artifact path, falling back to a file inside ``run_dir``."""

        if name in self.artifact_paths:
            return self.artifact_paths[name]
        return self.run_dir / default_filename


@dataclass(frozen=True)
class LiveAgentResult:
    """Normalized result that separates launcher status from task completion."""

    phase: str
    exit_status: int | None = None
    reason: str = ""
    provider_reason: str = ""
    retryable: bool | None = None
    resume_available: bool | None = None
    detail: str = ""
    started_at_epoch: float | None = None
    finished_at_epoch: float | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    timing: Mapping[str, Any] = field(default_factory=dict)
    artifact_paths: Mapping[str, Path] = field(default_factory=dict)
    provider_session_id: str = ""
    trace_id: str = ""
    run_result_present: bool = False
    task_completion: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_failure(
        cls,
        *,
        phase: str,
        exit_status: int,
        failure: LiveAgentFailure,
        started_at_epoch: float | None = None,
        finished_at_epoch: float | None = None,
        artifact_paths: Mapping[str, Path] | None = None,
    ) -> LiveAgentResult:
        return cls(
            phase=phase,
            exit_status=exit_status,
            reason=failure.reason,
            provider_reason=failure.provider_reason,
            retryable=failure.retryable,
            resume_available=failure.resume_available,
            detail=failure.detail,
            started_at_epoch=started_at_epoch,
            finished_at_epoch=finished_at_epoch,
            artifact_paths=artifact_paths or {},
        )

    @classmethod
    def from_live_status(
        cls,
        payload: Mapping[str, Any],
        *,
        artifact_paths: Mapping[str, Path] | None = None,
        run_result: Mapping[str, Any] | None = None,
    ) -> LiveAgentResult:
        return cls(
            phase=str(payload.get("phase") or payload.get("status") or "unknown"),
            exit_status=_int_or_none(payload.get("exit_status")),
            reason=str(payload.get("reason") or ""),
            provider_reason=str(payload.get("provider_reason") or ""),
            retryable=_bool_or_none(payload.get("retryable")),
            resume_available=_bool_or_none(payload.get("resume_available")),
            detail=str(payload.get("detail") or ""),
            started_at_epoch=_float_or_none(payload.get("started_at_epoch")),
            finished_at_epoch=_float_or_none(payload.get("finished_at_epoch")),
            artifact_paths=artifact_paths or {},
            provider_session_id=str(payload.get("provider_session_id") or ""),
            trace_id=str(payload.get("trace_id") or ""),
            run_result_present=bool(run_result),
            task_completion=_task_completion_fields(run_result or {}),
        )

    def to_live_status_payload(self) -> dict[str, Any]:
        """Return the stable ``live_status.json``-compatible status fields."""

        payload: dict[str, Any] = {"phase": self.phase}
        for key, value in (
            ("started_at_epoch", self.started_at_epoch),
            ("finished_at_epoch", self.finished_at_epoch),
            ("exit_status", self.exit_status),
            ("retryable", self.retryable),
            ("resume_available", self.resume_available),
        ):
            if value is not None:
                payload[key] = value
        for key, value in (
            ("reason", self.reason),
            ("provider_reason", self.provider_reason),
            ("detail", self.detail),
            ("provider_session_id", self.provider_session_id),
            ("trace_id", self.trace_id),
        ):
            if value:
                payload[key] = value
        return payload


def live_agent_result_from_artifacts(
    run_dir: Path,
    *,
    status_path: Path | None = None,
) -> LiveAgentResult:
    """Load the normalized result surface from existing live-run artifacts."""

    run_dir = Path(run_dir)
    status_path = status_path or run_dir / "live_status.json"
    artifact_paths = live_agent_artifacts(run_dir, status_path=status_path)
    status_payload = _read_json(status_path)
    run_result_payload = _read_json(run_dir / "run_result.json")
    return LiveAgentResult.from_live_status(
        status_payload,
        artifact_paths=artifact_paths,
        run_result=run_result_payload,
    )


def live_agent_artifacts(
    run_dir: Path,
    *,
    status_path: Path | None = None,
) -> dict[str, Path]:
    """Return known live-agent artifacts that exist in ``run_dir``."""

    run_dir = Path(run_dir)
    candidates = {
        "live_status": status_path or run_dir / "live_status.json",
        "run_result": run_dir / "run_result.json",
        "trace": run_dir / "trace.jsonl",
        "report": run_dir / "report.html",
        "checker_log": run_dir / "checker.log",
        "codex_events": run_dir / "codex-events.jsonl",
        "claude_events": run_dir / "claude-events.jsonl",
        "openai_agents_events": run_dir / "openai-agents-events.jsonl",
        "openai_agents_trace": run_dir / "openai-agents-trace.json",
        "openai_agents_spans": run_dir / "openai-agents-spans.jsonl",
        "openai_agents_skill_context": run_dir / "openai-agents-skill-context.json",
    }
    return {name: path for name, path in candidates.items() if path.exists()}


def _task_completion_fields(run_result: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in (
        "task",
        "task_name",
        "ok",
        "success",
        "cleanup_success",
        "runtime_map_success",
        "terminate_reason",
    ):
        if key in run_result:
            fields[key] = run_result[key]
    return fields


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json_object(path, label="live-agent artifact")
    except ValueError as exc:
        cause = exc.__cause__
        if not isinstance(cause, json.JSONDecodeError):
            raise ValueError(
                f"live-agent artifact source {path}: non-object JSON: {json_source_type_name(path)}"
            ) from exc
        raise ValueError(
            f"live-agent artifact source {path}: invalid JSON at line {cause.lineno} "
            f"column {cause.colno}: {cause.msg}"
        ) from exc
    except OSError as exc:
        raise ValueError(f"live-agent artifact source {path}: cannot be read: {exc}") from exc


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


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
