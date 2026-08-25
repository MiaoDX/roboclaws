"""Fail-open Opik projection plus a deterministic telemetry test fixture."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol
from urllib.parse import urlsplit

from roboclaws.agents.experiment_telemetry import (
    TelemetryContractError,
    TelemetryState,
    TelemetryStatus,
    closed_export_record,
)


class SerializedExporter(Protocol):
    """Worker-owned exporter; implementations receive closed UTF-8 JSON only."""

    def __call__(self, payload: bytes) -> None: ...


@dataclass(frozen=True)
class ProjectionProcessorConfig:
    queue_capacity: int = 1024
    terminal_flush_s: float = 2.0

    def __post_init__(self) -> None:
        if self.queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if not 0 <= self.terminal_flush_s <= 2.0:
            raise ValueError("terminal_flush_s must be between zero and two seconds")


@dataclass(frozen=True)
class OpikTelemetryConfig:
    endpoint: str = "http://127.0.0.1:5174/api/v1/private/otel/v1/traces"
    queue_capacity: int = 512
    max_export_batch_size: int = 64
    schedule_delay_ms: int = 200
    export_timeout_s: float = 1.0
    terminal_timeout_s: float = 2.0

    def __post_init__(self) -> None:
        _validate_local_otlp_endpoint(self.endpoint, name="endpoint")
        if self.queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if not 1 <= self.max_export_batch_size <= self.queue_capacity:
            raise ValueError("max_export_batch_size must be between one and queue_capacity")
        if self.schedule_delay_ms < 1:
            raise ValueError("schedule_delay_ms must be positive")
        if not 0 < self.export_timeout_s <= 2.0:
            raise ValueError("export_timeout_s must be between zero and two seconds")
        if not 0 <= self.terminal_timeout_s <= 2.0:
            raise ValueError("terminal_timeout_s must be between zero and two seconds")


def create_local_opik_telemetry_adapter(
    *,
    identity: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
) -> OpikTelemetryAdapter | None:
    """Create the explicitly enabled localhost adapter, or return disabled."""
    values = os.environ if environ is None else environ
    origin = values.get("ROBOCLAWS_OPIK_ENDPOINT", "").strip()
    if not origin:
        return None
    return create_opik_telemetry_adapter(
        identity=identity,
        config=OpikTelemetryConfig(
            endpoint=_opik_otlp_endpoint(origin),
            export_timeout_s=0.5,
            terminal_timeout_s=0.9,
        ),
    )


def _validate_loopback_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ROBOCLAWS_OPIK_ENDPOINT must target a loopback HTTP origin")
    if parsed.username or parsed.password:
        raise ValueError("ROBOCLAWS_OPIK_ENDPOINT must not contain user information")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("ROBOCLAWS_OPIK_ENDPOINT must contain a valid port") from exc
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("ROBOCLAWS_OPIK_ENDPOINT must be a base origin without path or query")
    return origin.rstrip("/")


def _opik_otlp_endpoint(origin: str) -> str:
    return _validate_loopback_origin(origin) + "/api/v1/private/otel/v1/traces"


def _validate_local_otlp_endpoint(endpoint: str, *, name: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError(f"{name} must target a loopback HTTP(S) endpoint")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not contain user information")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} must contain a valid port") from exc
    if parsed.path != "/api/v1/private/otel/v1/traces" or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must use the pinned Opik OTLP trace path")


def opik_privacy_config() -> Any:
    """Return the fail-closed OpenInference configuration used for every adapter."""
    try:
        from openinference.instrumentation import TraceConfig
    except ImportError as exc:
        raise RuntimeError(
            "Opik telemetry requires openinference-instrumentation-openai-agents==1.3.0"
        ) from exc
    return TraceConfig(
        hide_llm_invocation_parameters=True,
        hide_llm_tools=True,
        hide_inputs=True,
        hide_outputs=True,
        hide_input_messages=True,
        hide_output_messages=True,
        hide_input_images=True,
        hide_input_text=True,
        hide_output_text=True,
        hide_embedding_vectors=True,
        hide_embeddings_vectors=True,
        hide_embeddings_text=True,
        hide_prompts=True,
        hide_choices=True,
    )


def _new_openinference_processor(tracer: Any) -> Any:
    """Isolate the pinned package's intentionally private processor import."""
    package = "openinference-instrumentation-openai-agents"
    try:
        installed = version(package)
        if installed != "1.3.0":
            raise RuntimeError(f"{package}==1.3.0 is required; found {installed}")
        from openinference.instrumentation.openai_agents._processor import (  # noqa: PLC0415
            OpenInferenceTracingProcessor,
        )
    except (ImportError, PackageNotFoundError) as exc:
        raise RuntimeError(
            "Opik telemetry requires openinference-instrumentation-openai-agents==1.3.0; "
            "run `uv sync --extra dev`"
        ) from exc
    return OpenInferenceTracingProcessor(tracer)


class _CountingExporter:
    def __init__(self, exporter: Any, adapter: OpikTelemetryAdapter) -> None:
        self._exporter = exporter
        self._adapter = adapter

    def export(self, spans: Any) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self._exporter.export(spans)
        except Exception:
            self._adapter._record_failed(len(spans))
            return SpanExportResult.FAILURE
        if result is SpanExportResult.SUCCESS:
            self._adapter._record_exported(len(spans))
        else:
            self._adapter._record_failed(len(spans))
        return result

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return bool(self._exporter.force_flush(timeout_millis))
        except Exception:
            self._adapter._record_failed(1)
            return False

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:
            self._adapter._record_failed(1)


class _IdentitySpanProcessor:
    """Attach closed run identity to each span before asynchronous export."""

    def __init__(self, attributes: Mapping[str, Any]) -> None:
        self._attributes = dict(attributes)

    def on_start(self, span: Any, parent_context: Any | None = None) -> None:
        del parent_context
        for key, value in self._attributes.items():
            span.set_attribute(key, value)

    def on_end(self, span: Any) -> None:
        del span

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


class OpikTelemetryAdapter:
    """Fail-open SDK processor backed by one bounded OpenTelemetry batch worker."""

    def __init__(self, processor: Any, batch_processor: Any, *, terminal_timeout_s: float) -> None:
        self._processor = processor
        self._batch_processor = batch_processor
        self._terminal_timeout_s = terminal_timeout_s
        self._lock = threading.Lock()
        self._closed = False
        self._submitted = 0
        self._exported = 0
        self._failed = 0

    @property
    def active(self) -> bool:
        with self._lock:
            return not self._closed

    def on_trace_start(self, trace: Any) -> None:
        self._callback("on_trace_start", trace)

    def on_trace_end(self, trace: Any) -> None:
        self._callback("on_trace_end", trace)

    def on_span_start(self, span: Any) -> None:
        self._callback("on_span_start", span)

    def on_span_end(self, span: Any) -> None:
        self._callback("on_span_end", span)

    def force_flush(self, deadline_s: float | None = None) -> TelemetryStatus:
        timeout = min(
            self._terminal_timeout_s,
            self._terminal_timeout_s if deadline_s is None else max(0.0, deadline_s),
        )
        completed = self._bounded_lifecycle(
            lambda: self._batch_processor.force_flush(timeout_millis=int(timeout * 1000)),
            timeout,
        )
        return self._status(force_degraded=not completed)

    def shutdown(self) -> TelemetryStatus:
        deadline = time.monotonic() + self._terminal_timeout_s
        with self._lock:
            if self._closed:
                return self._status_locked()
            self._closed = True
        flushed = self.force_flush(max(0.0, deadline - time.monotonic()))
        completed = self._bounded_lifecycle(
            self._batch_processor.shutdown,
            max(0.0, deadline - time.monotonic()),
        )
        return self._status(
            force_degraded=not completed or flushed.state is TelemetryState.DEGRADED
        )

    def _callback(self, method: str, value: Any) -> None:
        with self._lock:
            if self._closed:
                return
        try:
            getattr(self._processor, method)(value)
            if method in {"on_trace_end", "on_span_end"}:
                with self._lock:
                    self._submitted += 1
        except Exception:
            self._record_failed(1)

    def _record_exported(self, count: int) -> None:
        with self._lock:
            self._exported += count

    def _record_failed(self, count: int) -> None:
        with self._lock:
            self._failed += count

    def _bounded_lifecycle(self, callback: Any, timeout_s: float) -> bool:
        done = threading.Event()
        result = False

        def invoke() -> None:
            nonlocal result
            try:
                outcome = callback()
                result = outcome is not False
            except Exception:
                self._record_failed(1)
            finally:
                done.set()

        threading.Thread(target=invoke, daemon=True, name="opik-telemetry-lifecycle").start()
        return done.wait(timeout_s) and result

    def _status(self, *, force_degraded: bool = False) -> TelemetryStatus:
        with self._lock:
            return self._status_locked(force_degraded=force_degraded)

    def _status_locked(self, *, force_degraded: bool = False) -> TelemetryStatus:
        dropped = max(0, self._submitted - self._exported - self._failed)
        state = (
            TelemetryState.DEGRADED
            if force_degraded or self._failed or dropped
            else TelemetryState.READY
        )
        return TelemetryStatus(
            state,
            exported=self._exported,
            dropped=dropped,
            failed=self._failed,
        )


def create_opik_telemetry_adapter(
    *,
    identity: Mapping[str, Any],
    config: OpikTelemetryConfig | None = None,
    span_exporter: Any | None = None,
) -> OpikTelemetryAdapter:
    """Build an opt-in Opik adapter without registering global SDK state."""
    from openinference.instrumentation import OITracer
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    settings = config or OpikTelemetryConfig()
    closed_identity = closed_export_record("identity", identity)
    project_name = _opik_project_name(closed_identity)
    identity_attributes = {f"roboclaws.{key}": value for key, value in closed_identity.items()}
    if operator_session_id := closed_identity.get("operator_session_id"):
        identity_attributes["session.id"] = operator_session_id
    resource = Resource.create({**identity_attributes, "openinference.project.name": project_name})
    provider = TracerProvider(resource=resource, shutdown_on_exit=False)
    tracer = OITracer(provider.get_tracer("roboclaws.opik"), opik_privacy_config())
    processor = _new_openinference_processor(tracer)

    # Initialize counters and locking before constructing BatchSpanProcessor;
    # its worker may export immediately after startup.
    adapter = OpikTelemetryAdapter.__new__(OpikTelemetryAdapter)
    OpikTelemetryAdapter.__init__(
        adapter,
        processor,
        None,
        terminal_timeout_s=settings.terminal_timeout_s,
    )
    if span_exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        span_exporter = OTLPSpanExporter(
            endpoint=settings.endpoint,
            timeout=settings.export_timeout_s,
        )
    counting_exporter = _CountingExporter(span_exporter, adapter)
    batch = BatchSpanProcessor(
        counting_exporter,
        max_queue_size=settings.queue_capacity,
        schedule_delay_millis=settings.schedule_delay_ms,
        max_export_batch_size=settings.max_export_batch_size,
        export_timeout_millis=settings.export_timeout_s * 1000,
    )
    provider.add_span_processor(_IdentitySpanProcessor(identity_attributes))
    provider.add_span_processor(batch)
    adapter._batch_processor = batch
    return adapter


def _opik_project_name(identity: Mapping[str, Any]) -> str:
    context = identity.get("observability_context")
    eval_fields = ("suite_id", "suite_version", "sample_id", "trial_id", "repetition")
    present_eval_fields = {field for field in eval_fields if identity.get(field) not in {None, ""}}
    if context == "runtime":
        if present_eval_fields:
            raise TelemetryContractError(
                "runtime observability_context must not contain eval trial identity"
            )
        return "roboclaws-runtime"
    if context == "eval":
        missing = [field for field in eval_fields if field not in present_eval_fields]
        if missing:
            raise TelemetryContractError(
                "eval observability_context requires complete eval trial identity: "
                + ", ".join(missing)
            )
        return "roboclaws-eval"
    raise TelemetryContractError("observability_context must be exactly runtime or eval")


class DeterministicProjectionProcessor:
    """Queue closed JSON records to an injected deterministic test sink."""

    def __init__(
        self,
        exporter: SerializedExporter,
        *,
        identity: Mapping[str, Any],
        config: ProjectionProcessorConfig | None = None,
    ) -> None:
        self._exporter = exporter
        self._identity = closed_export_record("identity", identity)
        self._config = config or ProjectionProcessorConfig()
        self._queue: queue.Queue[bytes | object] = queue.Queue(self._config.queue_capacity)
        self._stop = object()
        self._lock = threading.Lock()
        self._exported = 0
        self._dropped = 0
        self._failed = 0
        self._closed = False
        self._pending = 0
        self._worker = threading.Thread(target=self._work, daemon=True, name="telemetry-projection")
        self._worker.start()

    @property
    def active(self) -> bool:
        with self._lock:
            return not self._closed

    def on_trace_start(self, trace: Any) -> None:
        del trace

    def on_trace_end(self, trace: Any) -> None:
        self._enqueue(
            {
                "event": "trace_end",
                "trace_id": _attr(trace, "trace_id"),
                "span_id": f"root-{_attr(trace, 'trace_id')}",
                "span_type": "agent",
                "workflow_name": _attr(trace, "name"),
                "status": "succeeded",
            }
        )

    def on_span_start(self, span: Any) -> None:
        del span

    def on_span_end(self, span: Any) -> None:
        self._enqueue(_span_record(span, event="span_end"))

    def force_flush(self, deadline_s: float | None = None) -> TelemetryStatus:
        deadline = time.monotonic() + min(
            self._config.terminal_flush_s,
            self._config.terminal_flush_s if deadline_s is None else max(0.0, deadline_s),
        )
        while self._pending_count() and time.monotonic() < deadline:
            time.sleep(0.001)
        if self._pending_count():
            return self._status(force_degraded=True)
        return self._status()

    def shutdown(self) -> TelemetryStatus:
        deadline = time.monotonic() + self._config.terminal_flush_s
        with self._lock:
            if self._closed:
                return self._status_locked()
            self._closed = True
        status = self.force_flush(deadline_s=max(0.0, deadline - time.monotonic()))
        if status.state is TelemetryState.DEGRADED:
            with self._lock:
                self._dropped += self._pending
                self._pending = 0
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._queue.task_done()
        if self._worker.is_alive():
            try:
                self._queue.put_nowait(self._stop)
            except queue.Full:
                pass
        self._worker.join(timeout=max(0.0, deadline - time.monotonic()))
        return self._status(force_degraded=status.state is TelemetryState.DEGRADED)

    def _enqueue(self, record: Mapping[str, Any]) -> None:
        try:
            closed = closed_export_record("span", record)
            trace_id = closed.get("trace_id")
            if not trace_id or not closed.get("span_id"):
                raise TelemetryContractError("trace_id and span_id are required")
            identity_trace_id = self._identity.get("trace_id")
            if identity_trace_id and trace_id != identity_trace_id:
                raise TelemetryContractError("span trace_id does not match run identity")
            payload = json.dumps(
                {"identity": self._identity, "span": closed},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TelemetryContractError, TypeError, ValueError):
            with self._lock:
                if self._closed:
                    return
                self._failed += 1
            return
        with self._lock:
            if self._closed:
                return
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                self._dropped += 1
            else:
                self._pending += 1

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._stop:
                    return
                try:
                    self._exporter(item)  # type: ignore[arg-type]
                except Exception:
                    with self._lock:
                        if self._pending:
                            self._failed += 1
                            self._pending -= 1
                else:
                    with self._lock:
                        if self._pending:
                            self._exported += 1
                            self._pending -= 1
                with self._lock:
                    if self._closed and not self._pending:
                        return
            finally:
                self._queue.task_done()

    def _status(self, *, force_degraded: bool = False) -> TelemetryStatus:
        with self._lock:
            return self._status_locked(force_degraded=force_degraded)

    def _status_locked(self, *, force_degraded: bool = False) -> TelemetryStatus:
        exported, dropped, failed = self._exported, self._dropped, self._failed
        state = (
            TelemetryState.DEGRADED if force_degraded or dropped or failed else TelemetryState.READY
        )
        return TelemetryStatus(state, exported=exported, dropped=dropped, failed=failed)

    def _pending_count(self) -> int:
        with self._lock:
            return self._pending


def _span_record(span: Any, *, event: str) -> dict[str, Any]:
    data = getattr(span, "span_data", None)
    exported = data.export() if data is not None and hasattr(data, "export") else {}
    if not isinstance(exported, dict):
        exported = {}
    usage = exported.get("usage") if isinstance(exported.get("usage"), dict) else {}
    error = getattr(span, "error", None)
    error_type = ""
    error_category = ""
    if error:
        error_type = type(error).__name__ if not isinstance(error, dict) else "SDKSpanError"
        error_category = "sdk_span_error"
    return {
        "event": event,
        "trace_id": _attr(span, "trace_id"),
        "span_id": _attr(span, "span_id"),
        "parent_id": _attr(span, "parent_id") or f"root-{_attr(span, 'trace_id')}",
        "started_at": _attr(span, "started_at"),
        "ended_at": _attr(span, "ended_at"),
        "span_type": str(exported.get("type") or getattr(data, "type", "") or ""),
        "span_name": str(exported.get("name") or ""),
        "model": str(exported.get("model") or ""),
        "tool_name": str(exported.get("name") or "") if exported.get("type") == "function" else "",
        "status": "failed" if error else ("succeeded" if event == "span_end" else "running"),
        "error_category": error_category,
        "error_type": error_type,
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
    }


def _attr(value: Any, name: str) -> str:
    return str(getattr(value, name, "") or "")
