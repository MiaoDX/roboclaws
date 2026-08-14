"""Dependency-free telemetry contracts and OpenAI Agents SDK trace routing."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from types import TracebackType
from typing import Any, Protocol, Self
from urllib.parse import urlsplit


class TelemetryContractError(ValueError):
    """Raised when data does not satisfy the closed export contract."""


class TelemetryState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_PUBLIC_IDENTITY = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


@dataclass(frozen=True)
class PromptIdentity:
    """Closed identity of one repo-rendered kickoff prompt; never its body."""

    template_name: str
    template_version: str
    variable_schema: str
    source_git_sha: str
    skill_sha256: str
    rendered_sha256: str

    def __post_init__(self) -> None:
        for name in ("template_name", "template_version", "variable_schema"):
            if not _PUBLIC_IDENTITY.fullmatch(str(getattr(self, name))):
                raise TelemetryContractError(f"prompt {name} must be a public identity label")
        if not _GIT_SHA.fullmatch(self.source_git_sha):
            raise TelemetryContractError("prompt source_git_sha must be a Git SHA")
        for name in ("skill_sha256", "rendered_sha256"):
            if not _SHA256.fullmatch(str(getattr(self, name))):
                raise TelemetryContractError(f"prompt {name} must be a lowercase SHA-256")

    def projection(self) -> dict[str, str]:
        return {
            "prompt_template_name": self.template_name,
            "prompt_template_version": self.template_version,
            "prompt_variable_schema": self.variable_schema,
            "prompt_source_git_sha": self.source_git_sha,
            "prompt_skill_sha256": self.skill_sha256,
            "prompt_rendered_sha256": self.rendered_sha256,
        }


@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    operator_session_id: str = ""
    trace_id: str = ""
    git_sha: str = ""
    surface: str = ""
    world: str = ""
    backend: str = ""
    intent: str = ""
    agent_engine: str = "openai-agents-sdk"
    provider_profile: str = ""
    suite_id: str = ""
    suite_version: str = ""
    sample_id: str = ""
    sample_digest: str = ""
    trial_id: str = ""
    repetition: int | None = None
    prompt_identity: PromptIdentity | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise TelemetryContractError("run_id is required")
        if self.repetition is not None and self.repetition < 0:
            raise TelemetryContractError("repetition must be non-negative")

    def projection(self) -> dict[str, Any]:
        return closed_export_record("identity", vars(self))


@dataclass(frozen=True)
class Score:
    name: str
    value: float | str | bool
    version: str = ""
    status: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise TelemetryContractError("score name is required")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise TelemetryContractError("score value must be finite")


@dataclass(frozen=True)
class ArtifactLink:
    label: str
    relative_path: str
    digest: str
    schema_version: str
    url: str = ""

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if not self.label.strip() or not self.digest.strip() or not self.schema_version.strip():
            raise TelemetryContractError("artifact label, digest, and schema_version are required")
        if (
            not self.relative_path
            or path.is_absolute()
            or path.as_posix() != self.relative_path
            or not path.parts
            or ".." in path.parts
        ):
            raise TelemetryContractError("artifact path must be normalized and relative")


@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    error_category: str = ""
    error_type: str = ""


@dataclass(frozen=True)
class TelemetryStatus:
    state: TelemetryState
    exported: int = 0
    dropped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class RunTelemetry:
    identity: RunIdentity
    local_handle: object


class LocalEvidenceFacade(Protocol):
    """Delegates to existing artifact owners; it does not persist a second store."""

    def start_run(self, identity: RunIdentity) -> object: ...

    def record_scores(self, handle: object, scores: Sequence[Score]) -> None: ...

    def link_artifacts(self, handle: object, artifacts: Sequence[ArtifactLink]) -> None: ...

    def finish_run(self, handle: object, outcome: RunOutcome) -> None: ...


class ExperimentTelemetry:
    """Small mandatory-local contract; external projection is a one-way side effect."""

    def __init__(self, local_evidence: LocalEvidenceFacade) -> None:
        self._local = local_evidence

    def start_run(self, identity: RunIdentity) -> RunTelemetry:
        return RunTelemetry(identity, self._local.start_run(identity))

    def record_scores(self, run: RunTelemetry, scores: Sequence[Score]) -> None:
        self._local.record_scores(run.local_handle, scores)

    def link_artifacts(self, run: RunTelemetry, artifacts: Sequence[ArtifactLink]) -> None:
        self._local.link_artifacts(run.local_handle, artifacts)

    def finish_run(self, run: RunTelemetry, outcome: RunOutcome) -> None:
        self._local.finish_run(run.local_handle, outcome)

    def flush(self, deadline_s: float) -> TelemetryStatus:
        del deadline_s
        return TelemetryStatus(TelemetryState.DISABLED)


_PROMPT_IDENTITY_FIELDS = frozenset(
    {
        "prompt_template_name",
        "prompt_template_version",
        "prompt_variable_schema",
        "prompt_source_git_sha",
        "prompt_skill_sha256",
        "prompt_rendered_sha256",
    }
)
_IDENTITY_FIELDS = frozenset(field.name for field in RunIdentity.__dataclass_fields__.values()) | (
    _PROMPT_IDENTITY_FIELDS
)
_SPAN_FIELDS = frozenset(
    {
        "event",
        "trace_id",
        "span_id",
        "parent_id",
        "started_at",
        "ended_at",
        "duration_s",
        "span_type",
        "span_name",
        "workflow_name",
        "model",
        "provider_profile",
        "tool_name",
        "mcp_server",
        "status",
        "error_category",
        "error_type",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    }
)
_PRIVATE_MARKERS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "endpoint",
        "grader_internal",
        "headers",
        "holdout",
        "input",
        "map_data",
        "output",
        "private_truth",
        "raw_image",
        "request",
        "response",
        "secret",
        "tool_arguments",
        "tool_result",
    }
)
_SECRET_VALUE = re.compile(r"(?i)(bearer\s+|sk-[a-z0-9_-]{8,}|api[_-]?key\s*[=:])")


def closed_export_record(kind: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy one record for an external exporter.

    Unexpected fields are rejected, not recursively sanitized, so callers cannot
    accidentally smuggle private payloads through arbitrary metadata.
    """

    exported = dict(values)
    prompt_identity = exported.pop("prompt_identity", None)
    if prompt_identity is not None:
        if kind != "identity" or not isinstance(prompt_identity, PromptIdentity):
            raise TelemetryContractError("prompt_identity must be a PromptIdentity")
        prompt_projection = prompt_identity.projection()
        if prompt_projection.keys() & exported.keys():
            raise TelemetryContractError("prompt identity fields must have one canonical source")
        exported.update(prompt_projection)
    allowed = _IDENTITY_FIELDS if kind == "identity" else _SPAN_FIELDS if kind == "span" else None
    if allowed is None:
        raise TelemetryContractError(f"unsupported export record kind: {kind}")
    keys = {str(key) for key in exported}
    denied = sorted(keys & _PRIVATE_MARKERS)
    unexpected = sorted(keys - allowed)
    if denied or unexpected:
        detail = denied or unexpected
        raise TelemetryContractError(f"export fields are not allowlisted: {', '.join(detail)}")
    return {key: _closed_scalar(value, key=key) for key, value in exported.items() if value != ""}


def validated_artifact_projection(
    artifact: ArtifactLink, *, allowed_origins: Sequence[str]
) -> dict[str, str]:
    result = {
        "label": artifact.label,
        "relative_path": artifact.relative_path,
        "digest": artifact.digest,
        "schema_version": artifact.schema_version,
    }
    if artifact.url:
        parsed = urlsplit(artifact.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if (
            parsed.scheme != "https"
            or origin not in allowed_origins
            or parsed.query
            or parsed.fragment
        ):
            raise TelemetryContractError("artifact URL must use an allowed HTTPS origin")
        if not parsed.path or parsed.path == "/":
            raise TelemetryContractError("artifact URL must identify an artifact")
        result["url"] = artifact.url
    return result


def closed_score_records(
    scores: Sequence[Score], *, allowed_names: Sequence[str]
) -> list[dict[str, Any]]:
    allowed = frozenset(allowed_names)
    records: list[dict[str, Any]] = []
    for score in scores:
        if score.name not in allowed:
            raise TelemetryContractError(f"score is not allowlisted: {score.name}")
        records.append(
            {
                key: value
                for key, value in {
                    "name": _closed_scalar(score.name, key="score.name"),
                    "value": _closed_scalar(score.value, key="score.value"),
                    "version": _closed_scalar(score.version, key="score.version"),
                    "status": _closed_scalar(score.status, key="score.status"),
                }.items()
                if value != ""
            }
        )
    return records


def _closed_scalar(value: Any, *, key: str) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and (
            len(value.encode("utf-8")) > 512
            or value.startswith(("/", "file://"))
            or "://" in value
            or "\n" in value
            or _SECRET_VALUE.search(value)
        ):
            raise TelemetryContractError(f"{key} contains a forbidden or oversized value")
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TelemetryContractError(f"{key} must be a finite scalar")


class TraceSink(Protocol):
    active: bool

    def on_trace_start(self, trace: Any) -> None: ...
    def on_trace_end(self, trace: Any) -> None: ...
    def on_span_start(self, span: Any) -> None: ...
    def on_span_end(self, span: Any) -> None: ...
    def force_flush(self) -> None: ...
    def shutdown(self) -> None: ...


class CompositeTraceSink:
    """Fan SDK callbacks out to run-owned sinks without coupling their failures."""

    def __init__(self, *sinks: TraceSink) -> None:
        self.sinks = tuple(sinks)

    @property
    def active(self) -> bool:
        return any(sink.active for sink in self.sinks)

    def on_trace_start(self, trace: Any) -> None:
        self._call("on_trace_start", trace)

    def on_trace_end(self, trace: Any) -> None:
        self._call("on_trace_end", trace)

    def on_span_start(self, span: Any) -> None:
        self._call("on_span_start", span)

    def on_span_end(self, span: Any) -> None:
        self._call("on_span_end", span)

    def force_flush(self) -> None:
        self._call("force_flush")

    def shutdown(self) -> None:
        self._call("shutdown")

    def _call(self, method: str, *args: Any) -> None:
        for sink in self.sinks:
            if not sink.active and method not in {"force_flush", "shutdown"}:
                continue
            try:
                getattr(sink, method)(*args)
            except Exception:
                # One telemetry destination must never suppress another.
                continue


class LocalTraceRouter:
    """One global SDK processor that routes callbacks to run-owned sinks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bound_sink: ContextVar[TraceSink | None] = ContextVar("trace_sink", default=None)
        self._trace_sinks: dict[str, TraceSink] = {}

    @contextmanager
    def bind(self, sink: TraceSink):
        token = self._bound_sink.set(sink)
        try:
            yield
        finally:
            self._bound_sink.reset(token)

    def on_trace_start(self, trace: Any) -> None:
        sink = self._bound_sink.get()
        trace_id = str(getattr(trace, "trace_id", "") or "")
        if sink is None or not sink.active or not trace_id:
            return
        with self._lock:
            self._trace_sinks[trace_id] = sink
            sink.on_trace_start(trace)

    def on_trace_end(self, trace: Any) -> None:
        trace_id = str(getattr(trace, "trace_id", "") or "")
        with self._lock:
            sink = self._trace_sinks.pop(trace_id, None)
            if sink is not None and sink.active:
                sink.on_trace_end(trace)

    def on_span_start(self, span: Any) -> None:
        self._route_span(span, "on_span_start")

    def on_span_end(self, span: Any) -> None:
        self._route_span(span, "on_span_end")

    def _route_span(self, span: Any, method: str) -> None:
        trace_id = str(getattr(span, "trace_id", "") or "")
        with self._lock:
            sink = self._trace_sinks.get(trace_id)
            if sink is not None and sink.active:
                getattr(sink, method)(span)

    def force_flush(self) -> None:
        with self._lock:
            sinks = set(self._trace_sinks.values())
        for sink in sinks:
            if sink.active:
                sink.force_flush()

    def close_sink(self, sink: TraceSink) -> None:
        with self._lock:
            stale = [
                trace_id for trace_id, candidate in self._trace_sinks.items() if candidate is sink
            ]
            for trace_id in stale:
                self._trace_sinks.pop(trace_id, None)

    def shutdown(self) -> None:
        with self._lock:
            sinks = set(self._trace_sinks.values())
            self._trace_sinks.clear()
        for sink in sinks:
            sink.shutdown()


class TelemetryRuntime:
    """Process-level SDK lifecycle; initialization replaces processors once."""

    def __init__(self, external_processor: Any | None = None) -> None:
        self.router = LocalTraceRouter()
        self.external_processor = external_processor
        self._lock = threading.Lock()
        self._initialized = False
        self._set_calls = 0

    @property
    def set_calls(self) -> int:
        return self._set_calls

    def initialize(self, setter: Callable[[list[Any]], None] | None = None) -> bool:
        with self._lock:
            if self._initialized:
                return False
            if setter is None:
                from agents import set_trace_processors

                setter = set_trace_processors
            processors = [self.router]
            if self.external_processor is not None:
                processors.append(self.external_processor)
            setter(processors)
            self._set_calls += 1
            self._initialized = True
            return True

    def flush(self, deadline_s: float) -> TelemetryStatus:
        return self._bounded_call(self.router.force_flush, deadline_s)

    def shutdown(self, deadline_s: float) -> TelemetryStatus:
        return self._bounded_call(self.router.shutdown, deadline_s)

    @staticmethod
    def _bounded_call(callback: Callable[[], None], deadline_s: float) -> TelemetryStatus:
        if deadline_s < 0:
            raise TelemetryContractError("deadline_s must be non-negative")
        done = threading.Event()
        failed: list[BaseException] = []

        def run() -> None:
            try:
                callback()
            except BaseException as exc:  # processor failures are non-fatal
                failed.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=run, daemon=True, name="telemetry-bounded-lifecycle")
        thread.start()
        finished = done.wait(deadline_s)
        if not finished:
            return TelemetryStatus(TelemetryState.DEGRADED, dropped=1)
        if failed:
            return TelemetryStatus(TelemetryState.DEGRADED, failed=1)
        return TelemetryStatus(TelemetryState.READY)


SDK_TELEMETRY_RUNTIME = TelemetryRuntime()


class BoundTraceSink:
    """Context helper that closes a run sink after a bounded local flush."""

    def __init__(self, runtime: TelemetryRuntime, sink: TraceSink, deadline_s: float = 2.0) -> None:
        self.runtime = runtime
        self.sink = sink
        self.deadline_s = deadline_s
        self.flush_status = TelemetryStatus(TelemetryState.DISABLED)
        self.shutdown_status = TelemetryStatus(TelemetryState.DISABLED)
        self._binding: Any = None

    def __enter__(self) -> Self:
        self._binding = self.runtime.router.bind(self.sink)
        self._binding.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._binding is not None:
            self._binding.__exit__(exc_type, exc, traceback)
        self.runtime.router.close_sink(self.sink)
        per_operation_deadline = self.deadline_s / 2
        self.flush_status = self.runtime._bounded_call(
            self.sink.force_flush, per_operation_deadline
        )
        self.shutdown_status = self.runtime._bounded_call(
            self.sink.shutdown, per_operation_deadline
        )
