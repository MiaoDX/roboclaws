from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from aiohttp import ClientSession, web

from roboclaws.agents.provider_timing_proxy import (
    ProviderTimingProxyConfig,
    _read_ready_payload,
    free_local_port,
    main,
    replace_base_url_origin,
    serve_provider_timing_proxy,
    start_provider_timing_proxy,
)
from roboclaws.reports.live_performance import privacy_findings_for_run_dir

REQUEST_BODY = b"secret prompt text"
RESPONSE_BODY = b"data: first\n\ndata: second\n\n"


def test_replace_base_url_origin_preserves_upstream_path() -> None:
    assert (
        replace_base_url_origin(
            "https://provider.example.test/v1",
            bind_url="http://127.0.0.1:18888",
        )
        == "http://127.0.0.1:18888/v1"
    )


def test_provider_timing_proxy_streams_counts_bytes_and_redacts(tmp_path: Path) -> None:
    asyncio.run(_proxy_streaming_case(tmp_path))


def test_start_provider_timing_proxy_rejects_invalid_bind_port_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_TIMING_PROXY_BIND_PORT", "abc")

    try:
        asyncio.run(
            start_provider_timing_proxy(
                repo_root=Path(__file__).resolve().parents[3],
                run_dir=tmp_path,
                upstream_base_url="https://provider.example.test/v1",
                agent_engine="codex-cli",
                provider_profile="kimi-openai-chat",
            )
        )
    except RuntimeError as exc:
        assert str(exc) == (
            "ROBOCLAWS_TIMING_PROXY_BIND_PORT must be an integer port from 0 to 65535; got 'abc'"
        )
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected invalid bind-port env to fail before proxy launch")

    assert not (tmp_path / "provider_timing_proxy.ready.json").exists()


def test_start_provider_timing_proxy_rejects_out_of_range_bind_port_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_TIMING_PROXY_BIND_PORT", "70000")

    try:
        asyncio.run(
            start_provider_timing_proxy(
                repo_root=Path(__file__).resolve().parents[3],
                run_dir=tmp_path,
                upstream_base_url="https://provider.example.test/v1",
                agent_engine="codex-cli",
                provider_profile="kimi-openai-chat",
            )
        )
    except RuntimeError as exc:
        assert str(exc) == (
            "ROBOCLAWS_TIMING_PROXY_BIND_PORT must be an integer port from 0 to 65535; got 70000"
        )
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected out-of-range bind-port env to fail before proxy launch")

    assert not (tmp_path / "provider_timing_proxy.ready.json").exists()


def test_provider_timing_proxy_cli_rejects_out_of_range_bind_port(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--upstream-base-url",
                "https://provider.example.test/v1",
                "--metrics-path",
                str(tmp_path / "metrics.jsonl"),
                "--bind-port",
                "70000",
            ]
        )
        == 1
    )

    assert not (tmp_path / "metrics.jsonl").exists()


def test_provider_timing_proxy_ready_source_missing_is_not_ready(tmp_path: Path) -> None:
    assert _read_ready_payload(tmp_path / "missing.ready.json") == {}


def test_provider_timing_proxy_ready_source_rejects_malformed_json(tmp_path: Path) -> None:
    ready_path = tmp_path / "provider_timing_proxy.ready.json"
    ready_path.write_text("{not-json", encoding="utf-8")

    try:
        _read_ready_payload(ready_path)
    except ValueError as exc:
        assert str(exc) == (
            f"provider timing proxy ready source must contain valid JSON object: {ready_path}"
        )
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected malformed provider timing proxy ready source to fail")


def test_provider_timing_proxy_ready_source_rejects_non_object_json(tmp_path: Path) -> None:
    ready_path = tmp_path / "provider_timing_proxy.ready.json"
    ready_path.write_text('["ready"]', encoding="utf-8")

    try:
        _read_ready_payload(ready_path)
    except ValueError as exc:
        assert str(exc) == (
            f"provider timing proxy ready source must contain a JSON object: {ready_path}"
        )
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected non-object provider timing proxy ready source to fail")


def test_start_provider_timing_proxy_fails_on_invalid_ready_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeProcess:
        stderr = None

        def __init__(self) -> None:
            self.terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            raise AssertionError("unexpected process kill")

    fake_process = FakeProcess()
    ready_path = tmp_path / "provider_timing_proxy.ready.json"

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        ready_path.write_text("[1]", encoding="utf-8")
        return fake_process

    monkeypatch.setattr(
        "roboclaws.agents.provider_timing_proxy.subprocess.Popen",
        fake_popen,
    )

    try:
        asyncio.run(
            start_provider_timing_proxy(
                repo_root=Path(__file__).resolve().parents[3],
                run_dir=tmp_path,
                upstream_base_url="https://provider.example.test/v1",
                agent_engine="codex-cli",
                provider_profile="kimi-openai-chat",
                startup_timeout_s=1,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == (
            "provider timing proxy ready source is invalid: "
            f"provider timing proxy ready source must contain a JSON object: {ready_path}"
        )
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected invalid provider timing proxy ready source to fail")

    assert fake_process.terminated is True


async def _proxy_streaming_case(tmp_path: Path) -> None:
    proxy_stop = asyncio.Event()
    upstream_port = free_local_port()
    proxy_port = free_local_port()
    received: dict[str, object] = {}

    upstream_runner = await _start_streaming_upstream(upstream_port, received)
    ready_path = tmp_path / "run" / "provider_timing_proxy.ready.json"
    proxy_task = asyncio.create_task(
        serve_provider_timing_proxy(
            _proxy_config(
                tmp_path=tmp_path,
                upstream_port=upstream_port,
                proxy_port=proxy_port,
            ),
            ready_path=ready_path,
            stop_event=proxy_stop,
        )
    )
    await _wait_for_port(proxy_port)
    assert _read_ready_payload(ready_path)["bind_url"] == f"http://127.0.0.1:{proxy_port}"

    response_body, first_chunk_seen = await _read_streamed_proxy_response(proxy_port)

    proxy_stop.set()
    await proxy_task
    await upstream_runner.cleanup()

    assert response_body == RESPONSE_BODY
    assert first_chunk_seen
    _assert_received_request(received)
    _assert_proxy_metrics(tmp_path)


async def _start_streaming_upstream(
    upstream_port: int,
    received: dict[str, object],
) -> web.AppRunner:
    async def handle(request: web.Request) -> web.StreamResponse:
        body = await request.read()
        received["body"] = body.decode("utf-8")
        received["authorization"] = request.headers.get("authorization")
        response = web.StreamResponse(
            status=200,
            headers={
                "content-type": "text/event-stream",
                "x-request-id": "safe-upstream-id",
            },
        )
        await response.prepare(request)
        await response.write(b"data: first\n\n")
        await asyncio.sleep(0.05)
        await response.write(b"data: second\n\n")
        await response.write_eof()
        return response

    upstream_runner = web.AppRunner(web.Application())
    upstream_runner.app.router.add_post("/v1/responses", handle)
    upstream_runner.app.router.add_post("/v1/v1/responses", _unexpected_upstream_path)
    await upstream_runner.setup()
    upstream_site = web.TCPSite(upstream_runner, "127.0.0.1", upstream_port)
    await upstream_site.start()
    return upstream_runner


def _proxy_config(
    *,
    tmp_path: Path,
    upstream_port: int,
    proxy_port: int,
) -> ProviderTimingProxyConfig:
    return ProviderTimingProxyConfig(
        upstream_base_url=f"http://127.0.0.1:{upstream_port}/v1",
        metrics_path=tmp_path / "run" / "provider_request_metrics.jsonl",
        bind_port=proxy_port,
        agent_engine="codex-cli",
        provider_profile="kimi-openai-chat",
        model="gpt-5.5",
    )


async def _read_streamed_proxy_response(proxy_port: int) -> tuple[bytes, bool]:
    first_chunk_at: float | None = None
    chunks: list[bytes] = []
    async with ClientSession() as session:
        async with session.post(
            f"http://127.0.0.1:{proxy_port}/v1/responses",
            data=REQUEST_BODY,
            headers={"authorization": "Bearer sk-test-secret"},
        ) as response:
            async for chunk in response.content.iter_chunked(64):
                if first_chunk_at is None:
                    first_chunk_at = time.monotonic()
                chunks.append(chunk)
    return b"".join(chunks), first_chunk_at is not None


def _assert_received_request(received: dict[str, object]) -> None:
    assert received["body"] == "secret prompt text"
    assert received["authorization"] == "Bearer sk-test-secret"


def _assert_proxy_metrics(tmp_path: Path) -> None:
    metrics_path = tmp_path / "run" / "provider_request_metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "roboclaws_provider_request_metric_v1"
    assert row["agent_engine"] == "codex-cli"
    assert row["provider_profile"] == "kimi-openai-chat"
    assert row["method"] == "POST"
    assert row["path"] == "/v1/responses"
    assert row["status_code"] == 200
    assert row["request_body_bytes"] == len(REQUEST_BODY)
    assert row["response_body_bytes"] == len(RESPONSE_BODY)
    assert row["streaming"] is True
    assert row["provider_request_id"] == "safe-upstream-id"
    assert row["duration_s"] >= row["time_to_first_byte_s"] >= 0
    assert row["stream_duration_s"] >= 0
    assert "secret prompt text" not in metrics_path.read_text(encoding="utf-8")
    assert "sk-test-secret" not in metrics_path.read_text(encoding="utf-8")
    assert "data: first" not in metrics_path.read_text(encoding="utf-8")
    assert privacy_findings_for_run_dir(tmp_path / "run") == []


async def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.02)
            continue
        writer.close()
        await writer.wait_closed()
        reader.feed_eof()
        return
    raise AssertionError(f"port {port} did not open")


async def _unexpected_upstream_path(_request: web.Request) -> web.Response:
    return web.Response(status=599, text="unexpected duplicated upstream path")
