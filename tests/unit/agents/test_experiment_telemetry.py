from __future__ import annotations

import time
from contextvars import copy_context
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any

import pytest

from roboclaws.agents.experiment_telemetry import (
    ArtifactLink,
    BoundTraceSink,
    CompositeTraceSink,
    ExperimentTelemetry,
    RunIdentity,
    RunOutcome,
    RunStatus,
    Score,
    TelemetryContractError,
    TelemetryRuntime,
    TelemetryState,
    closed_export_record,
    closed_score_records,
    validated_artifact_projection,
)


@dataclass
class _CanonicalOwner:
    calls: list[tuple[str, object]] = field(default_factory=list)

    def start_run(self, identity: RunIdentity) -> object:
        handle = {"run_id": identity.run_id}
        self.calls.append(("start", identity))
        return handle

    def record_scores(self, handle: object, scores: list[Score]) -> None:
        self.calls.append(("scores", (handle, scores)))

    def link_artifacts(self, handle: object, artifacts: list[ArtifactLink]) -> None:
        self.calls.append(("artifacts", (handle, artifacts)))

    def finish_run(self, handle: object, outcome: RunOutcome) -> None:
        self.calls.append(("finish", (handle, outcome)))


def test_experiment_telemetry_is_a_facade_over_canonical_local_owner() -> None:
    owner = _CanonicalOwner()
    telemetry = ExperimentTelemetry(owner)
    run = telemetry.start_run(RunIdentity(run_id="run-1", trial_id="trial-1"))
    telemetry.record_scores(run, [Score("restoration", 0.8, version="v1", status="passed")])
    telemetry.link_artifacts(
        run,
        [ArtifactLink("report", "report.html", "sha256:abc", "report-v1")],
    )
    telemetry.finish_run(run, RunOutcome(RunStatus.SUCCEEDED))

    assert [name for name, _ in owner.calls] == ["start", "scores", "artifacts", "finish"]
    assert telemetry.flush(0.01).state is TelemetryState.DISABLED


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("identity", {"run_id": "run", "api_key": "sk-malicious-secret"}),
        ("identity", {"run_id": "run", "provider_profile": "sk-malicious-secret"}),
        ("span", {"event": "span_end", "endpoint": "https://provider.invalid/v1"}),
        ("span", {"event": "span_end", "model": "https://provider.invalid/v1"}),
        ("span", {"event": "span_end", "private_truth": {"mess": "hidden"}}),
        ("span", {"event": "span_end", "tool_arguments": {"target": "private"}}),
        ("span", {"event": "span_end", "tool_result": {"image": "base64"}}),
        ("span", {"event": "span_end", "span_name": "/home/operator/private.json"}),
        ("span", {"event": "span_end", "raw_image": "x" * 200_000}),
        ("span", {"event": "span_end", "map_data": [[0] * 1000] * 1000}),
        ("span", {"event": "span_end", "span_name": "x" * 10_000}),
    ],
)
def test_closed_export_contract_denies_malicious_data(kind: str, payload: dict[str, Any]) -> None:
    with pytest.raises(TelemetryContractError):
        closed_export_record(kind, payload)


def test_closed_export_contract_keeps_only_typed_public_scalars() -> None:
    assert closed_export_record(
        "span",
        {
            "event": "span_end",
            "trace_id": "trace-1",
            "span_type": "tool",
            "tool_name": "observe",
            "input_tokens": 12,
            "cached_input_tokens": 4,
            "reasoning_tokens": 2,
            "status": "ok",
        },
    ) == {
        "event": "span_end",
        "trace_id": "trace-1",
        "span_type": "tool",
        "tool_name": "observe",
        "input_tokens": 12,
        "cached_input_tokens": 4,
        "reasoning_tokens": 2,
        "status": "ok",
    }


def test_artifact_links_are_relative_and_origin_allowlisted() -> None:
    artifact = ArtifactLink(
        "report",
        "runs/run-1/report.html",
        "sha256:abc",
        "report-v1",
        "https://artifacts.internal/runs/run-1/report.html",
    )
    assert (
        validated_artifact_projection(artifact, allowed_origins=["https://artifacts.internal"])[
            "url"
        ]
        == artifact.url
    )

    with pytest.raises(TelemetryContractError):
        ArtifactLink("map", "/private/map.json", "sha256:def", "map-v1")
    with pytest.raises(TelemetryContractError):
        ArtifactLink("map", "runs//map.json", "sha256:def", "map-v1")
    with pytest.raises(TelemetryContractError):
        ArtifactLink("map", ".", "sha256:def", "map-v1")
    with pytest.raises(TelemetryContractError):
        validated_artifact_projection(artifact, allowed_origins=["https://different.internal"])


def test_score_projection_requires_an_explicit_allowlist() -> None:
    scores = [Score("restoration", 0.8, version="v1", status="passed")]
    assert closed_score_records(scores, allowed_names=["restoration"]) == [
        {"name": "restoration", "value": 0.8, "version": "v1", "status": "passed"}
    ]
    with pytest.raises(TelemetryContractError):
        closed_score_records(scores, allowed_names=["latency"])


class _Item:
    def __init__(self, trace_id: str, span_id: str = "") -> None:
        self.trace_id = trace_id
        self.span_id = span_id


@dataclass(eq=False)
class _Sink:
    name: str
    active: bool = True
    events: list[tuple[str, str]] = field(default_factory=list)

    def on_trace_start(self, trace: Any) -> None:
        self.events.append(("trace_start", trace.trace_id))

    def on_trace_end(self, trace: Any) -> None:
        self.events.append(("trace_end", trace.trace_id))

    def on_span_start(self, span: Any) -> None:
        self.events.append(("span_start", span.span_id))

    def on_span_end(self, span: Any) -> None:
        self.events.append(("span_end", span.span_id))

    def force_flush(self) -> None:
        return None

    def shutdown(self) -> None:
        self.active = False


def _emit_trace(runtime: TelemetryRuntime, trace_id: str, span_id: str) -> None:
    trace = _Item(trace_id)
    span = _Item(trace_id, span_id)
    runtime.router.on_trace_start(trace)
    runtime.router.on_span_start(span)
    runtime.router.on_span_end(span)
    runtime.router.on_trace_end(trace)


def test_one_processor_routes_two_runs_and_continuation_without_duplicates() -> None:
    installed: list[list[Any]] = []
    runtime = TelemetryRuntime()
    assert runtime.initialize(installed.append) is True
    assert runtime.initialize(installed.append) is False
    assert len(installed) == 1
    assert installed[0] == [runtime.router]

    first = _Sink("first")
    with BoundTraceSink(runtime, first):
        _emit_trace(runtime, "trace-run-1", "span-1")
        _emit_trace(runtime, "trace-run-1-continuation", "span-2")
    runtime.router.on_span_end(_Item("trace-run-1", "late-span"))

    second = _Sink("second")
    with BoundTraceSink(runtime, second):
        _emit_trace(runtime, "trace-run-2", "span-3")

    assert first.events == [
        ("trace_start", "trace-run-1"),
        ("span_start", "span-1"),
        ("span_end", "span-1"),
        ("trace_end", "trace-run-1"),
        ("trace_start", "trace-run-1-continuation"),
        ("span_start", "span-2"),
        ("span_end", "span-2"),
        ("trace_end", "trace-run-1-continuation"),
    ]
    assert second.events == [
        ("trace_start", "trace-run-2"),
        ("span_start", "span-3"),
        ("span_end", "span-3"),
        ("trace_end", "trace-run-2"),
    ]


def test_closing_sink_removes_unfinished_trace_mapping() -> None:
    runtime = TelemetryRuntime()
    sink = _Sink("interrupted")
    trace = _Item("unfinished-trace")
    with BoundTraceSink(runtime, sink):
        runtime.router.on_trace_start(trace)
    runtime.router.on_span_end(_Item("unfinished-trace", "late-span"))

    assert sink.events == [("trace_start", "unfinished-trace")]
    assert runtime.router._trace_sinks == {}  # noqa: SLF001 - closed-sink retention proof


def test_async_contexts_keep_run_sink_bindings_isolated() -> None:
    runtime = TelemetryRuntime()
    first = _Sink("first")
    second = _Sink("second")

    with runtime.router.bind(first):
        first_context = copy_context()
    with runtime.router.bind(second):
        second_context = copy_context()

    first_context.run(_emit_trace, runtime, "trace-1", "span-1")
    second_context.run(_emit_trace, runtime, "trace-2", "span-2")

    assert [value for _, value in first.events] == ["trace-1", "span-1", "span-1", "trace-1"]
    assert [value for _, value in second.events] == ["trace-2", "span-2", "span-2", "trace-2"]


def test_close_waits_for_inflight_callback_before_sink_shutdown() -> None:
    entered = Event()
    release = Event()

    class BlockingSink(_Sink):
        def on_span_end(self, span: Any) -> None:
            entered.set()
            assert release.wait(1)
            super().on_span_end(span)

    runtime = TelemetryRuntime()
    sink = BlockingSink("blocking")
    binding = runtime.router.bind(sink)
    binding.__enter__()
    runtime.router.on_trace_start(_Item("trace"))
    callback = Thread(target=runtime.router.on_span_end, args=(_Item("trace", "span"),))
    callback.start()
    assert entered.wait(1)

    closed = Event()

    def close() -> None:
        runtime.router.close_sink(sink)
        sink.shutdown()
        closed.set()

    closer = Thread(target=close)
    closer.start()
    assert not closed.wait(0.01)
    release.set()
    callback.join(1)
    closer.join(1)
    binding.__exit__(None, None, None)

    assert closed.is_set()
    assert sink.events[-1] == ("span_end", "span")
    runtime.router.on_span_end(_Item("trace", "late"))
    assert sink.events[-1] == ("span_end", "span")


@pytest.mark.parametrize("api_key", [None, "present-but-must-not-enable-remote-tracing"])
def test_real_sdk_startup_replaces_remote_backend_exporter(
    monkeypatch: pytest.MonkeyPatch, api_key: str | None
) -> None:
    from agents import custom_span, set_trace_processors, trace
    from agents.tracing.processors import BackendSpanExporter
    from agents.tracing.setup import get_trace_provider

    if api_key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", api_key)
    remote_exports: list[object] = []
    monkeypatch.setattr(
        BackendSpanExporter,
        "export",
        lambda self, items: remote_exports.extend(items),
    )
    provider = get_trace_provider()
    original_processors = list(
        provider._multi_processor._processors  # noqa: SLF001 - SDK lifecycle contract proof
    )
    try:
        runtime = TelemetryRuntime()
        assert runtime.initialize() is True
        with trace("phase-0-startup-proof"):
            with custom_span("no-remote-export"):
                pass

        processors = list(
            provider._multi_processor._processors  # noqa: SLF001 - SDK lifecycle contract proof
        )
        assert processors == [runtime.router]
        assert all("BackendSpanExporter" not in repr(processor) for processor in processors)
        assert remote_exports == []
        assert runtime.set_calls == 1
    finally:
        set_trace_processors(original_processors)


def test_flush_and_shutdown_are_bounded() -> None:
    runtime = TelemetryRuntime()

    def slow() -> None:
        time.sleep(0.1)

    started = time.monotonic()
    status = runtime._bounded_call(slow, 0.005)  # noqa: SLF001 - bounded lifecycle spike
    assert time.monotonic() - started < 0.08
    assert status == status.__class__(TelemetryState.DEGRADED, dropped=1)

    runtime.router.shutdown = slow  # type: ignore[method-assign]
    started = time.monotonic()
    status = runtime.shutdown(0.005)
    assert time.monotonic() - started < 0.08
    assert status == status.__class__(TelemetryState.DEGRADED, dropped=1)


def test_bound_sink_exposes_lifecycle_failure_without_raising() -> None:
    class FailingSink(_Sink):
        def force_flush(self) -> None:
            raise RuntimeError("private flush detail")

        def shutdown(self) -> None:
            raise RuntimeError("private shutdown detail")

    binding = BoundTraceSink(TelemetryRuntime(), FailingSink("failing"))
    with binding:
        pass

    assert binding.flush_status.state is TelemetryState.DEGRADED
    assert binding.flush_status.failed == 1
    assert binding.shutdown_status.state is TelemetryState.DEGRADED
    assert binding.shutdown_status.failed == 1


def test_composite_trace_sink_isolates_destinations() -> None:
    class Sink:
        active = True

        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.events: list[str] = []

        def on_trace_start(self, trace: object) -> None:
            if self.fail:
                raise RuntimeError("collector unavailable")
            self.events.append("trace_start")

        def on_trace_end(self, trace: object) -> None:
            self.events.append("trace_end")

        def on_span_start(self, span: object) -> None:
            self.events.append("span_start")

        def on_span_end(self, span: object) -> None:
            self.events.append("span_end")

        def force_flush(self) -> None:
            self.events.append("flush")

        def shutdown(self) -> None:
            self.events.append("shutdown")

    broken = Sink(fail=True)
    local = Sink()
    sink = CompositeTraceSink(broken, local)

    sink.on_trace_start(object())
    sink.force_flush()
    sink.shutdown()

    assert local.events == ["trace_start", "flush", "shutdown"]
