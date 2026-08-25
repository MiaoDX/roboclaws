from __future__ import annotations

import json
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest
from agents.tracing import AgentSpanData, FunctionSpanData, GenerationSpanData
from openinference.semconv.trace import SpanAttributes
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from roboclaws.agents.experiment_telemetry import (
    TelemetryContractError,
    TelemetryRuntime,
    TelemetryState,
)
from roboclaws.agents.opik_telemetry import (
    DeterministicProjectionProcessor,
    OpikTelemetryAdapter,
    OpikTelemetryConfig,
    ProjectionProcessorConfig,
    _new_openinference_processor,
    _opik_otlp_endpoint,
    create_local_opik_telemetry_adapter,
    create_opik_telemetry_adapter,
    opik_privacy_config,
)


def test_local_opik_adapter_is_disabled_without_explicit_endpoint() -> None:
    assert (
        create_local_opik_telemetry_adapter(
            identity={"run_id": "run-1", "observability_context": "runtime"}, environ={}
        )
        is None
    )


def test_local_opik_adapter_rejects_remote_or_non_otlp_endpoint() -> None:
    with pytest.raises(ValueError, match="must target a loopback"):
        create_local_opik_telemetry_adapter(
            identity={"run_id": "run-1", "observability_context": "runtime"},
            environ={"ROBOCLAWS_OPIK_ENDPOINT": "https://opik.example"},
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://opik.example/v1/traces",
        "http://0.0.0.0:6006/v1/traces",
        "http://192.0.2.10:6006/v1/traces",
    ],
)
def test_opik_config_rejects_non_loopback_endpoint(endpoint: str) -> None:
    with pytest.raises(ValueError, match="must target a loopback"):
        OpikTelemetryConfig(endpoint=endpoint)


def test_opik_config_accepts_loopback_otlp_endpoints() -> None:
    for endpoint in (
        "http://127.0.0.1:5174/api/v1/private/otel/v1/traces",
        "http://localhost:5174/api/v1/private/otel/v1/traces",
        "http://[::1]:5174/api/v1/private/otel/v1/traces",
    ):
        assert OpikTelemetryConfig(endpoint=endpoint).endpoint == endpoint
    assert _opik_otlp_endpoint("http://127.0.0.1:5174/") == (
        "http://127.0.0.1:5174/api/v1/private/otel/v1/traces"
    )
    with pytest.raises(ValueError, match="base origin"):
        create_local_opik_telemetry_adapter(
            identity={"run_id": "run-1", "observability_context": "runtime"},
            environ={"ROBOCLAWS_OPIK_ENDPOINT": "http://127.0.0.1:5174/path"},
        )


@dataclass
class _Data:
    type: str
    name: str
    model: str = ""
    usage: dict[str, int] | None = None

    def export(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "model": self.model,
            "usage": self.usage or {},
            "input": "must-not-cross-the-seam",
            "output": "must-not-cross-the-seam",
        }


@dataclass
class _Item:
    trace_id: str
    span_id: str = ""
    parent_id: str = ""
    name: str = ""
    span_data: _Data | None = None
    error: object | None = None
    started_at: str = "2026-08-07T00:00:00Z"
    ended_at: str = "2026-08-07T00:00:01Z"


def _hierarchy(adapter: DeterministicProjectionProcessor) -> None:
    trace = _Item("trace-1", name="robot-run")
    agent = _Item("trace-1", "agent-1", span_data=_Data("agent", "cleanup-agent"))
    llm = _Item(
        "trace-1",
        "llm-1",
        "agent-1",
        span_data=_Data(
            "generation",
            "",
            model="fake-model",
            usage={
                "input_tokens": 20,
                "cached_input_tokens": 4,
                "output_tokens": 8,
                "reasoning_tokens": 2,
            },
        ),
    )
    tool = _Item(
        "trace-1",
        "tool-1",
        "llm-1",
        span_data=_Data("function", "observe"),
        error=RuntimeError("private provider URL https://provider.invalid"),
    )
    adapter.on_trace_start(trace)
    for span in (agent, llm, tool):
        adapter.on_span_start(span)
        adapter.on_span_end(span)
    adapter.on_trace_end(trace)


def test_deterministic_collector_gets_one_closed_correlated_hierarchy() -> None:
    payloads: list[bytes] = []
    adapter = DeterministicProjectionProcessor(
        payloads.append,
        identity={
            "run_id": "run-1",
            "operator_session_id": "operator-1",
            "trial_id": "trial-1",
            "trace_id": "trace-1",
            "git_sha": "abc123",
        },
    )
    _hierarchy(adapter)
    status = adapter.shutdown()

    records = [json.loads(payload) for payload in payloads]
    spans = [record["span"] for record in records]
    ended = [span for span in spans if span["event"] == "span_end"]
    assert status == status.__class__(TelemetryState.READY, exported=4)
    assert len({span["span_id"] for span in spans}) == 4
    assert {span["span_type"] for span in ended} == {"agent", "generation", "function"}
    assert len({span["span_id"] for span in ended}) == 3
    assert {span.get("parent_id", "") for span in ended} == {
        "root-trace-1",
        "agent-1",
        "llm-1",
    }
    assert all(record["identity"]["run_id"] == "run-1" for record in records)
    assert all(record["identity"]["trial_id"] == "trial-1" for record in records)
    assert next(span for span in ended if span["span_type"] == "generation") == {
        "cached_input_tokens": 4,
        "ended_at": "2026-08-07T00:00:01Z",
        "event": "span_end",
        "input_tokens": 20,
        "model": "fake-model",
        "output_tokens": 8,
        "parent_id": "agent-1",
        "reasoning_tokens": 2,
        "span_id": "llm-1",
        "span_type": "generation",
        "started_at": "2026-08-07T00:00:00Z",
        "status": "succeeded",
        "trace_id": "trace-1",
    }
    tool_record = next(span for span in ended if span["span_type"] == "function")
    assert tool_record["status"] == "failed"
    assert tool_record["error_category"] == "sdk_span_error"
    assert tool_record["error_type"] == "RuntimeError"
    serialized = b"\n".join(payloads)
    for forbidden in (b"must-not-cross", b'input"', b'output"', b"tool_arguments"):
        assert forbidden not in serialized


def test_runtime_composes_local_router_and_external_processor_once() -> None:
    adapter = DeterministicProjectionProcessor(lambda payload: None, identity={"run_id": "run-1"})
    installed: list[list[Any]] = []
    runtime = TelemetryRuntime(external_processor=adapter)
    assert runtime.initialize(installed.append) is True
    assert runtime.initialize(installed.append) is False
    assert installed == [[runtime.router, adapter]]
    assert runtime.set_calls == 1
    adapter.shutdown()


def test_runtime_composes_real_opik_adapter_once() -> None:
    adapter = create_opik_telemetry_adapter(
        identity={"run_id": "run-1", "observability_context": "runtime"},
        span_exporter=InMemorySpanExporter(),
    )
    installed: list[list[Any]] = []
    runtime = TelemetryRuntime(external_processor=adapter)
    assert runtime.initialize(installed.append) is True
    assert runtime.initialize(installed.append) is False
    assert installed == [[runtime.router, adapter]]
    assert runtime.set_calls == 1
    adapter.shutdown()


def test_failure_is_counted_once_without_retry_and_local_routing_survives() -> None:
    attempts = 0

    def fail(payload: bytes) -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("private endpoint detail")

    adapter = DeterministicProjectionProcessor(fail, identity={"run_id": "run-1"})
    _hierarchy(adapter)
    status = adapter.shutdown()
    assert attempts == 4
    assert status.exported == 0
    assert status.dropped == 0
    assert status.failed == 4
    assert status.state is TelemetryState.DEGRADED


def test_missing_or_cross_run_span_identity_is_rejected() -> None:
    payloads: list[bytes] = []
    adapter = DeterministicProjectionProcessor(
        payloads.append,
        identity={"run_id": "run-1", "trace_id": "trace-1"},
    )
    adapter.on_span_end(_Item("", "span-1", span_data=_Data("agent", "missing-trace")))
    adapter.on_span_end(_Item("trace-2", "span-2", span_data=_Data("agent", "wrong-trace")))
    status = adapter.shutdown()

    assert payloads == []
    assert status == status.__class__(TelemetryState.DEGRADED, failed=2)


def test_queue_full_drops_are_counted_and_callbacks_remain_nonblocking() -> None:
    def slow(payload: bytes) -> None:
        time.sleep(0.02)

    adapter = DeterministicProjectionProcessor(
        slow,
        identity={"run_id": "run-1"},
        config=ProjectionProcessorConfig(queue_capacity=1, terminal_flush_s=0.05),
    )
    span = _Item("trace-1", "span-1", span_data=_Data("agent", "agent"))
    latencies_ms = []
    for _ in range(500):
        started = time.perf_counter_ns()
        adapter.on_span_end(span)
        latencies_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    status = adapter.shutdown()
    p99 = statistics.quantiles(latencies_ms, n=100)[98]
    assert p99 <= 5.0
    assert status.dropped > 0
    assert status.exported + status.failed + status.dropped == 500


def test_terminal_flush_is_bounded_to_two_seconds() -> None:
    release = threading.Event()

    def blocked(payload: bytes) -> None:
        release.wait()

    adapter = DeterministicProjectionProcessor(
        blocked,
        identity={"run_id": "run-1"},
        config=ProjectionProcessorConfig(queue_capacity=1, terminal_flush_s=0.02),
    )
    adapter.on_span_end(_Item("trace", "span", span_data=_Data("agent", "agent")))
    started = time.monotonic()
    status = adapter.shutdown()
    elapsed = time.monotonic() - started
    assert elapsed < 0.08
    assert status.state is TelemetryState.DEGRADED
    assert status.dropped == 1

    adapter.on_span_end(_Item("trace", "late", span_data=_Data("agent", "late")))
    assert adapter.shutdown() == status
    release.set()
    adapter._worker.join(timeout=0.2)
    assert not adapter._worker.is_alive()


def test_opik_privacy_config_is_fail_closed() -> None:
    config = opik_privacy_config()
    assert config.hide_llm_invocation_parameters is True
    assert config.hide_llm_tools is True
    assert config.hide_inputs is True
    assert config.hide_outputs is True
    assert config.hide_input_messages is True
    assert config.hide_output_messages is True
    assert config.hide_input_images is True
    assert config.hide_input_text is True
    assert config.hide_output_text is True
    assert config.hide_embedding_vectors is True
    assert config.hide_embeddings_vectors is True
    assert config.hide_embeddings_text is True
    assert config.hide_prompts is True
    assert config.hide_choices is True
    assert config.mask(SpanAttributes.INPUT_VALUE, "private input") == "__REDACTED__"
    assert config.mask(SpanAttributes.OUTPUT_VALUE, "private output") == "__REDACTED__"
    assert config.mask(SpanAttributes.LLM_INVOCATION_PARAMETERS, "private config") is None


def test_private_processor_import_is_pinned_and_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("roboclaws.agents.opik_telemetry.version", lambda package: "1.3.1")
    with pytest.raises(RuntimeError, match="1.3.0 is required; found 1.3.1"):
        _new_openinference_processor(object())


def test_real_openinference_hierarchy_is_sanitized_and_resource_is_closed() -> None:
    exporter = InMemorySpanExporter()
    adapter = create_opik_telemetry_adapter(
        identity={
            "run_id": "run-1",
            "observability_context": "eval",
            "operator_session_id": "session-1",
            "suite_id": "suite-1",
            "suite_version": "1",
            "sample_id": "sample-1",
            "trial_id": "trial-1",
            "repetition": 2,
            "prompt_template_name": "household-cleanup-kickoff",
            "prompt_template_version": "v1",
            "prompt_variable_schema": "household-cleanup-kickoff-variables/v1",
            "prompt_source_git_sha": "a" * 40,
            "prompt_skill_sha256": "b" * 64,
            "prompt_rendered_sha256": "c" * 64,
        },
        config=OpikTelemetryConfig(schedule_delay_ms=10),
        span_exporter=exporter,
    )
    trace = _Item("trace-1", name="robot-run")
    spans = [
        _Item("trace-1", "agent-1", span_data=AgentSpanData("cleanup-agent")),
        _Item(
            "trace-1",
            "llm-1",
            "agent-1",
            span_data=GenerationSpanData(
                input=[{"role": "user", "content": "private prompt"}],
                output=[{"role": "assistant", "content": "private choice"}],
                model="fake-model",
                model_config={"secret": "private invocation"},
                usage={"input_tokens": 20, "output_tokens": 8},
            ),
        ),
        _Item(
            "trace-1",
            "tool-1",
            "llm-1",
            span_data=FunctionSpanData("observe", "private args", "private result"),
        ),
    ]
    adapter.on_trace_start(trace)
    for span in spans:
        adapter.on_span_start(span)
    for span in reversed(spans):
        adapter.on_span_end(span)
    adapter.on_trace_end(trace)
    status = adapter.shutdown()

    exported = exporter.get_finished_spans()
    assert status.state is TelemetryState.READY
    assert status.exported == 4
    assert {span.name for span in exported} == {
        "cleanup-agent",
        "generation",
        "observe",
        "robot-run",
    }
    by_name = {span.name: span for span in exported}
    assert by_name["cleanup-agent"].parent.span_id == by_name["robot-run"].context.span_id
    assert by_name["generation"].parent.span_id == by_name["cleanup-agent"].context.span_id
    assert by_name["observe"].parent.span_id == by_name["generation"].context.span_id
    assert by_name["generation"].attributes[SpanAttributes.LLM_MODEL_NAME] == "fake-model"
    assert by_name["generation"].attributes[SpanAttributes.LLM_TOKEN_COUNT_PROMPT] == 20
    assert by_name["generation"].attributes[SpanAttributes.LLM_TOKEN_COUNT_COMPLETION] == 8
    resources = [dict(span.resource.attributes) for span in exported]
    assert all(resource["roboclaws.run_id"] == "run-1" for resource in resources)
    assert all(resource["roboclaws.trial_id"] == "trial-1" for resource in resources)
    assert all(resource["roboclaws.repetition"] == 2 for resource in resources)
    assert all(resource["roboclaws.prompt_rendered_sha256"] == "c" * 64 for resource in resources)
    assert all(resource["openinference.project.name"] == "roboclaws-eval" for resource in resources)
    assert all(span.attributes["roboclaws.run_id"] == "run-1" for span in exported)
    assert all(span.attributes["roboclaws.trial_id"] == "trial-1" for span in exported)
    assert all(span.attributes["roboclaws.prompt_rendered_sha256"] == "c" * 64 for span in exported)
    assert all(span.attributes["session.id"] == "session-1" for span in exported)
    serialized = repr([(span.attributes, span.resource.attributes) for span in exported])
    for forbidden in (
        "private prompt",
        "private choice",
        "private args",
        "private result",
        "private invocation",
        "PRIVATE KICKOFF BODY",
    ):
        assert forbidden not in serialized


def test_opik_identity_explicitly_denies_prompt_body_content() -> None:
    with pytest.raises(Exception, match="not allowlisted"):
        create_opik_telemetry_adapter(
            identity={"run_id": "run-1", "prompt_body": "PRIVATE KICKOFF BODY"},
            span_exporter=InMemorySpanExporter(),
        )


def test_opik_factory_rejects_nonclosed_resource_identity() -> None:
    with pytest.raises(Exception, match="not allowlisted"):
        create_opik_telemetry_adapter(
            identity={"run_id": "run-1", "api_key": "sk-private-value"},
            span_exporter=InMemorySpanExporter(),
        )


@pytest.mark.parametrize(
    ("identity", "message"),
    [
        ({"run_id": "run-1"}, "observability_context"),
        ({"run_id": "run-1", "observability_context": "invalid"}, "observability_context"),
        (
            {
                "run_id": "run-1",
                "observability_context": "runtime",
                "trial_id": "trial-1",
            },
            "must not contain eval trial identity",
        ),
        (
            {"run_id": "run-1", "observability_context": "eval", "suite_id": "suite-1"},
            "requires complete eval trial identity",
        ),
    ],
)
def test_opik_project_routing_rejects_invalid_context(
    identity: dict[str, object], message: str
) -> None:
    with pytest.raises(TelemetryContractError, match=message):
        create_opik_telemetry_adapter(identity=identity, span_exporter=InMemorySpanExporter())


@pytest.mark.parametrize(
    "failure",
    [
        ConnectionRefusedError("collector refused connection"),
        TimeoutError("collector timed out"),
        SpanExportResult.FAILURE,
    ],
    ids=["connection-refused", "timeout", "server-error"],
)
def test_export_failures_are_fail_open_and_credibly_counted(failure: object) -> None:
    class FailingExporter(InMemorySpanExporter):
        def export(self, spans: Any) -> SpanExportResult:
            del spans
            if isinstance(failure, BaseException):
                raise failure
            return failure  # type: ignore[return-value]

    adapter = create_opik_telemetry_adapter(
        identity={"run_id": "run-1", "observability_context": "runtime"},
        config=OpikTelemetryConfig(schedule_delay_ms=10),
        span_exporter=FailingExporter(),
    )
    trace = _Item("trace-1", name="robot-run")
    adapter.on_trace_start(trace)
    adapter.on_trace_end(trace)
    status = adapter.shutdown()
    assert status.state is TelemetryState.DEGRADED
    assert status.exported == 0
    assert status.dropped == 0
    assert status.failed == 1


def test_callback_and_lifecycle_exceptions_are_fail_open() -> None:
    class BrokenProcessor:
        def on_span_end(self, span: Any) -> None:
            raise ValueError("private callback detail")

    class BrokenBatch:
        def force_flush(self, timeout_millis: int) -> bool:
            raise ConnectionError("private flush detail")

        def shutdown(self) -> None:
            raise RuntimeError("private shutdown detail")

    adapter = OpikTelemetryAdapter(BrokenProcessor(), BrokenBatch(), terminal_timeout_s=0.1)
    adapter.on_span_end(object())
    status = adapter.shutdown()
    assert status.state is TelemetryState.DEGRADED
    assert status.failed == 3


def test_callbacks_after_opik_shutdown_are_ignored() -> None:
    exporter = InMemorySpanExporter()
    adapter = create_opik_telemetry_adapter(
        identity={"run_id": "run-1", "observability_context": "runtime"},
        span_exporter=exporter,
    )
    initial = adapter.shutdown()
    adapter.on_trace_start(_Item("late", name="late-private"))
    adapter.on_trace_end(_Item("late", name="late-private"))
    assert adapter.shutdown() == initial
    assert exporter.get_finished_spans() == ()


def test_opik_shutdown_is_bounded_when_exporter_blocks() -> None:
    release = threading.Event()

    class BlockingExporter(InMemorySpanExporter):
        def export(self, spans: Any) -> SpanExportResult:
            release.wait()
            return super().export(spans)

    adapter = create_opik_telemetry_adapter(
        identity={"run_id": "run-1", "observability_context": "runtime"},
        config=OpikTelemetryConfig(
            schedule_delay_ms=10,
            export_timeout_s=0.01,
            terminal_timeout_s=0.02,
        ),
        span_exporter=BlockingExporter(),
    )
    trace = _Item("trace-1", name="robot-run")
    adapter.on_trace_start(trace)
    adapter.on_trace_end(trace)
    started = time.monotonic()
    status = adapter.shutdown()
    assert time.monotonic() - started < 0.08
    assert status.state is TelemetryState.DEGRADED
    assert status.dropped == 1
    release.set()


def test_real_opik_queue_pressure_reports_dropped_spans() -> None:
    release = threading.Event()

    class BlockingExporter(InMemorySpanExporter):
        def export(self, spans: Any) -> SpanExportResult:
            release.wait()
            return super().export(spans)

    adapter = create_opik_telemetry_adapter(
        identity={"run_id": "run-1", "observability_context": "runtime"},
        config=OpikTelemetryConfig(
            queue_capacity=1,
            max_export_batch_size=1,
            schedule_delay_ms=1,
            export_timeout_s=0.01,
            terminal_timeout_s=0.02,
        ),
        span_exporter=BlockingExporter(),
    )
    for index in range(50):
        trace = _Item(f"trace-{index}", name="robot-run")
        adapter.on_trace_start(trace)
        adapter.on_trace_end(trace)

    status = adapter.shutdown()
    assert status.state is TelemetryState.DEGRADED
    assert status.dropped > 0
    assert status.exported + status.failed + status.dropped == 50
    release.set()
