from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_script_module():
    path = Path("scripts/dev/benchmark_model_matrix.py")
    spec = importlib.util.spec_from_file_location("benchmark_model_matrix", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_cases_cover_routes_and_wire_formats() -> None:
    script = _load_script_module()

    cases = {case.case_id: case for case in script.default_cases()}

    assert set(cases) == {
        "custom-responses:custom:responses",
        "minimax-responses:MiniMax-M3:responses",
        "kimi:kimi-k2.7-code:chat",
    }
    assert {case.wire_api for case in cases.values()} == {"openai-chat", "openai-responses"}


def test_custom_case_reads_environment_configuration(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_RESPONSES_BASE_URL", "https://custom.example/v1")
    monkeypatch.setenv("CUSTOM_RESPONSES_MODEL", "opaque-model")
    script = _load_script_module()

    cases = {case.case_id: case for case in script.default_cases()}

    custom = cases["custom-responses:custom:responses"]
    assert custom.base_url == "https://custom.example/v1"
    assert custom.model == "custom"
    assert custom.request_model == "opaque-model"
    assert custom.api_key_env == "CUSTOM_RESPONSES_API_KEY"


def test_kimi_case_reads_registry_env(monkeypatch) -> None:
    monkeypatch.setenv("KIMI_OPENAI_BASE_URL", "https://kimi.example/v1")
    script = _load_script_module()

    cases = {case.case_id: case for case in script.default_cases()}

    case = cases["kimi:kimi-k2.7-code:chat"]
    assert case.base_url == "https://kimi.example/v1"
    assert case.api_key_env == "KIMI_API_KEY"


def test_load_dotenv_uses_explicit_file_and_preserves_existing_env(
    tmp_path: Path, monkeypatch
) -> None:
    script = _load_script_module()
    dotenv = tmp_path / "matrix.env"
    dotenv.write_text('CUSTOM_RESPONSES_API_KEY="from file"\nKEEP=from-file\n', encoding="utf-8")
    monkeypatch.delenv("CUSTOM_RESPONSES_API_KEY", raising=False)
    monkeypatch.setenv("KEEP", "host")

    script.load_dotenv(dotenv)

    assert script.os.environ["CUSTOM_RESPONSES_API_KEY"] == "from file"
    assert script.os.environ["KEEP"] == "host"


def test_endpoint_urls_normalize_wire_api_suffixes() -> None:
    script = _load_script_module()

    assert (
        script.endpoint_url("http://example.test", "openai-chat")
        == "http://example.test/v1/chat/completions"
    )
    assert (
        script.endpoint_url("http://example.test/v1", "openai-responses")
        == "http://example.test/v1/responses"
    )
    assert (
        script.endpoint_url("http://example.test/anthropic", "anthropic-messages")
        == "http://example.test/anthropic/v1/messages"
    )


def test_payloads_match_wire_format(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_RESPONSES_MODEL", "opaque-model")
    script = _load_script_module()
    cases = {case.case_id: case for case in script.default_cases()}

    chat_payload = script.payload_for_case(
        cases["kimi:kimi-k2.7-code:chat"],
        prompt="ping",
        max_tokens=8,
    )
    responses_payload = script.payload_for_case(
        cases["custom-responses:custom:responses"],
        prompt="ping",
        max_tokens=8,
    )
    kimi_payload = script.payload_for_case(
        cases["kimi:kimi-k2.7-code:chat"],
        prompt="ping",
        max_tokens=8,
    )

    assert chat_payload["messages"] == [{"role": "user", "content": "ping"}]
    assert chat_payload["max_tokens"] == 8
    assert "input" not in chat_payload
    assert "thinking" not in chat_payload
    assert responses_payload["input"] == "ping"
    assert responses_payload["model"] == cases["custom-responses:custom:responses"].request_model
    assert responses_payload["max_output_tokens"] == 8
    assert responses_payload["reasoning"] == {"effort": "medium"}
    assert "messages" not in responses_payload
    assert "thinking" not in kimi_payload


def test_custom_benchmark_artifact_redacts_private_configuration(monkeypatch) -> None:
    canary_url = "https://private-benchmark-canary.example/v1"
    canary_key = "benchmark-key-canary-123456"
    canary_model = "benchmark-model-canary-654321"
    monkeypatch.setenv("CUSTOM_RESPONSES_BASE_URL", canary_url)
    monkeypatch.setenv("CUSTOM_RESPONSES_API_KEY", canary_key)
    monkeypatch.setenv("CUSTOM_RESPONSES_MODEL", canary_model)
    script = _load_script_module()
    case = {case.case_id: case for case in script.default_cases()}[
        "custom-responses:custom:responses"
    ]

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return json.dumps(
                {
                    "model": canary_model,
                    "output_text": f"ok {canary_url} {canary_key} {canary_model}",
                }
            ).encode()

    monkeypatch.setattr(script.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    result = script.run_case(
        case,
        layer="health",
        prompt="ping",
        iterations=1,
        max_tokens=8,
        timeout_s=1.0,
    )
    args = script.parse_args(["--iterations", "1"])
    serialized = json.dumps(script.result_payload([result], args=args))

    assert result.model == "custom"
    assert result.response_model == "custom"
    for canary in (canary_url, canary_key, canary_model):
        assert canary not in serialized


def test_default_token_budget_leaves_room_for_reasoning() -> None:
    script = _load_script_module()

    assert script.DEFAULT_MAX_TOKENS >= 512
    assert script.DEFAULT_FIRST_CONTENT_MAX_TOKENS >= 256
    assert script.DEFAULT_THROUGHPUT_MAX_TOKENS >= 2048
    assert script.DEFAULT_STREAM_THROUGHPUT_MAX_TOKENS >= 4096
    assert script.DEFAULT_AGENT_CASE_MAX_TOKENS >= 512
    assert "2500 words" in script.DEFAULT_STREAM_THROUGHPUT_PROMPT
    assert script.DEFAULT_LAYERS == ("health", "throughput")
    assert "first-content" in script.LAYER_CHOICES
    assert "stream-throughput" in script.LAYER_CHOICES
    assert "agent-case" in script.LAYER_CHOICES


def test_headers_include_kimi_coding_user_agent() -> None:
    script = _load_script_module()
    cases = {case.case_id: case for case in script.default_cases()}

    headers = script.headers_for_case(cases["kimi:kimi-k2.7-code:chat"], api_key="secret")

    assert headers["Authorization"] == "Bearer secret"
    assert "x-api-key" not in headers
    assert "anthropic-version" not in headers
    assert headers["User-Agent"] == "claude-code/1.0.0"


def test_missing_key_skips_without_secret_values() -> None:
    script = _load_script_module()
    case = script.MatrixCase(
        case_id="sample-openai-chat:sample-chat-model:openai-chat",
        provider_id="sample-openai-chat",
        provider_label="Sample provider",
        model="sample-chat-model",
        wire_api="openai-chat",
        api_key_env="SAMPLE_API_KEY",
        base_url="https://provider.example/v1",
    )

    result = script.run_case(
        case,
        layer="health",
        prompt="ping",
        iterations=1,
        max_tokens=8,
        timeout_s=1.0,
        env={"SAMPLE_BASE_URL": "https://secret.example"},
    )

    assert result.status == "SKIP"
    assert result.skipped_reason == "missing SAMPLE_API_KEY"
    assert "secret.example" not in str(result)


def test_result_payload_counts_statuses() -> None:
    script = _load_script_module()
    args = script.parse_args(["--iterations", "1"])

    payload = script.result_payload(
        [
            script.CaseResult(
                case_id="a",
                provider_id="p",
                provider_label="P",
                model="m",
                wire_api="openai-chat",
                layer="health",
                agent_case_id="",
                agent_case_label="",
                agent_case_source="",
                expected_support="native",
                status="PASS",
                api_key_env="KEY",
                api_key_alt_env="",
                base_url_configured=True,
                iterations=1,
                max_tokens=512,
                success_count=1,
                failure_count=0,
            ),
            script.CaseResult(
                case_id="b",
                provider_id="p",
                provider_label="P",
                model="m",
                wire_api="openai-responses",
                layer="throughput",
                agent_case_id="",
                agent_case_label="",
                agent_case_source="",
                expected_support="probe",
                status="FAIL",
                api_key_env="KEY",
                api_key_alt_env="",
                base_url_configured=True,
                iterations=1,
                max_tokens=2048,
                success_count=0,
                failure_count=1,
            ),
        ],
        args=args,
    )

    assert payload["benchmark"] == "roboclaws_model_matrix_wire_support_v1"
    assert payload["layers"] == ["health", "throughput"]
    assert payload["first_content_max_tokens"] >= 256
    assert payload["throughput_max_tokens"] >= 2048
    assert payload["stream_throughput_max_tokens"] >= 4096
    assert payload["agent_case_max_tokens"] >= 512
    assert payload["prompts"]["agent-case"]
    assert payload["status_counts"]["PASS"] == 1
    assert payload["status_counts"]["FAIL"] == 1
    assert payload["status_counts"]["SKIP"] == 0


def test_usage_tokens_and_tps_prefer_provider_usage() -> None:
    script = _load_script_module()
    case = {case.case_id: case for case in script.default_cases()}["kimi:kimi-k2.7-code:chat"]

    result = script.summarize_case(
        case,
        layer="throughput",
        trials=(
            script.TrialResult(
                index=1,
                layer="throughput",
                status="PASS",
                elapsed_s=2.0,
                response_model="sample-chat-model",
                output_preview="ok " * 40,
                output_chars=300,
                measured_output_tokens=200,
                output_token_count_source="provider_usage",
                output_tokens_per_s=100.0,
                output_chars_per_s=150.0,
                first_content_s=0.2,
                decode_s=1.8,
                decode_output_tokens_per_s=111.111,
                decode_output_chars_per_s=166.667,
                completion_tokens=200,
            ),
        ),
        iterations=1,
        max_tokens=2048,
        base_url_configured=True,
    )

    assert result.layer == "throughput"
    assert result.max_tokens == 2048
    assert result.median_output_tokens_per_s == 100.0
    assert result.median_output_chars_per_s == 150.0
    assert result.median_decode_output_tokens_per_s == 111.111
    assert result.median_first_content_s == 0.2
    assert result.median_decode_s == 1.8
    assert result.output_token_count_source == "provider_usage"
    assert result.output_preview.startswith("ok")


def test_stream_throughput_skips_non_chat_wire() -> None:
    script = _load_script_module()
    case = {case.case_id: case for case in script.default_cases()}[
        "custom-responses:custom:responses"
    ]

    result = script.run_case(
        case,
        layer="stream-throughput",
        prompt="ping",
        iterations=1,
        max_tokens=8,
        timeout_s=1.0,
        env={"CUSTOM_RESPONSES_API_KEY": "secret"},
    )

    assert result.status == "SKIP"
    assert "OpenAI Chat streaming" in result.skipped_reason


def test_max_tokens_for_layer_uses_stream_budget() -> None:
    script = _load_script_module()
    args = script.parse_args(
        [
            "--first-content-max-tokens",
            "16",
            "--stream-throughput-max-tokens",
            "8192",
            "--stream-throughput-prompt",
            "stream",
            "--agent-case-max-tokens",
            "777",
        ]
    )

    assert script._max_tokens_for_layer(args, "health") == script.DEFAULT_MAX_TOKENS
    assert script._max_tokens_for_layer(args, "first-content") == 16
    assert script._max_tokens_for_layer(args, "throughput") == (
        script.DEFAULT_THROUGHPUT_MAX_TOKENS
    )
    assert script._max_tokens_for_layer(args, "stream-throughput") == 8192
    assert script._max_tokens_for_layer(args, "agent-case") == 777
    assert script._prompt_for_layer(args, "stream-throughput") == "stream"


def test_first_content_stream_payload_omits_usage_tail(monkeypatch) -> None:
    script = _load_script_module()
    case = script.MatrixCase(
        case_id="sample-openai-chat:sample-chat-model:openai-chat",
        provider_id="sample-openai-chat",
        provider_label="Sample provider",
        model="sample-chat-model",
        wire_api="openai-chat",
        api_key_env="SAMPLE_API_KEY",
        base_url="https://provider.example/v1",
    )
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        headers = {"content-type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(
                [
                    b"event: message\n",
                    b'data: {"model":"sample-chat-model","choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["payload"] = script.json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    result = script.run_trial(
        case,
        index=1,
        layer="first-content",
        prompt="stream",
        max_tokens=8,
        timeout_s=1.0,
        api_key="secret",
    )

    payload = captured["payload"]
    assert payload["stream"] is True
    assert "stream_options" not in payload
    assert result.status == "PASS"
    assert result.first_content_s is not None


def test_stream_throughput_payload_requests_usage_tail(monkeypatch) -> None:
    script = _load_script_module()
    case = script.MatrixCase(
        case_id="sample-openai-chat:sample-chat-model:openai-chat",
        provider_id="sample-openai-chat",
        provider_label="Sample provider",
        model="sample-chat-model",
        wire_api="openai-chat",
        api_key_env="SAMPLE_API_KEY",
        base_url="https://provider.example/v1",
    )
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        headers = {"content-type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(
                [
                    b'data: {"model":"sample-chat-model","choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["payload"] = script.json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    result = script.run_trial(
        case,
        index=1,
        layer="stream-throughput",
        prompt="stream",
        max_tokens=8,
        timeout_s=1.0,
        api_key="secret",
    )

    payload = captured["payload"]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert result.status == "PASS"
    assert result.first_content_s is not None


def test_stream_trial_rejects_malformed_provider_event_json(monkeypatch) -> None:
    script = _load_script_module()
    case = script.MatrixCase(
        case_id="sample-openai-chat:sample-chat-model:openai-chat",
        provider_id="sample-openai-chat",
        provider_label="Sample provider",
        model="sample-chat-model",
        wire_api="openai-chat",
        api_key_env="SAMPLE_API_KEY",
        base_url="https://provider.example/v1",
    )

    class _Response:
        status = 200
        headers = {"content-type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(
                [
                    b"event: message\n",
                    b"data: {not-json}\n",
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setattr(script.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())

    result = script.run_trial(
        case,
        index=1,
        layer="stream-throughput",
        prompt="stream",
        max_tokens=8,
        timeout_s=1.0,
        api_key="secret",
    )

    assert result.status == "FAIL"
    assert result.error_type == "ModelMatrixStreamSourceError"
    assert "model-matrix provider stream source must contain valid JSON object" in result.error


def test_stream_trial_rejects_non_object_provider_event_json(monkeypatch) -> None:
    script = _load_script_module()
    case = script.MatrixCase(
        case_id="sample-openai-chat:sample-chat-model:openai-chat",
        provider_id="sample-openai-chat",
        provider_label="Sample provider",
        model="sample-chat-model",
        wire_api="openai-chat",
        api_key_env="SAMPLE_API_KEY",
        base_url="https://provider.example/v1",
    )

    class _Response:
        status = 200
        headers = {"content-type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(
                [
                    b"data: []\n",
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setattr(script.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())

    result = script.run_trial(
        case,
        index=1,
        layer="stream-throughput",
        prompt="stream",
        max_tokens=8,
        timeout_s=1.0,
        api_key="secret",
    )

    assert result.status == "FAIL"
    assert result.error_type == "ModelMatrixStreamSourceError"
    assert "model-matrix provider stream source must contain a JSON object" in result.error


def test_non_stream_trial_rejects_bad_provider_response_json(monkeypatch) -> None:
    script = _load_script_module()
    case = script.MatrixCase(
        case_id="sample-openai-chat:sample-chat-model:openai-chat",
        provider_id="sample-openai-chat",
        provider_label="Sample provider",
        model="sample-chat-model",
        wire_api="openai-chat",
        api_key_env="SAMPLE_API_KEY",
        base_url="https://provider.example/v1",
    )

    class _Response:
        status = 200
        headers = {"content-type": "application/json"}

        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    bodies = iter((b"{not-json}", b"[]"))

    def fake_urlopen(_request, timeout):  # noqa: ANN001
        assert timeout == 1.0
        return _Response(next(bodies))

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    malformed = script.run_trial(
        case,
        index=1,
        layer="health",
        prompt="ping",
        max_tokens=8,
        timeout_s=1.0,
        api_key="secret",
    )
    non_object = script.run_trial(
        case,
        index=2,
        layer="health",
        prompt="ping",
        max_tokens=8,
        timeout_s=1.0,
        api_key="secret",
    )

    assert malformed.status == "FAIL"
    assert malformed.error_type == "ValueError"
    assert "model-matrix provider response source must contain valid JSON object" in (
        malformed.error or ""
    )
    assert "sample-openai-chat:sample-chat-model:openai-chat health" in (malformed.error or "")
    assert non_object.status == "FAIL"
    assert non_object.error_type == "ValueError"
    assert "model-matrix provider response source must contain a JSON object" in (
        non_object.error or ""
    )
    assert "sample-openai-chat:sample-chat-model:openai-chat health" in (non_object.error or "")


def test_agent_cases_are_selectable_and_do_not_store_full_prompt() -> None:
    script = _load_script_module()

    selected = script.selected_agent_cases(case_ids={"sdk-speedup-verdict"})

    assert [case.case_id for case in selected] == ["sdk-speedup-verdict"]
    assert "raw prompts" in selected[0].prompt
    assert len(selected[0].prompt) > 240


def test_agent_case_summary_carries_case_metadata() -> None:
    script = _load_script_module()
    case = {case.case_id: case for case in script.default_cases()}["kimi:kimi-k2.7-code:chat"]
    agent_case = script.selected_agent_cases(case_ids={"cleanup-worklist-plan"})[0]

    result = script.summarize_case(
        case,
        layer="agent-case",
        trials=(
            script.TrialResult(
                index=1,
                layer="agent-case",
                status="PASS",
                elapsed_s=2.0,
                agent_case_id=agent_case.case_id,
                agent_case_label=agent_case.label,
                output_preview="actions...",
                output_chars=300,
                measured_output_tokens=120,
                output_token_count_source="estimated_chars_div_4",
                output_tokens_per_s=60.0,
            ),
        ),
        iterations=1,
        max_tokens=768,
        base_url_configured=True,
        agent_case=agent_case,
    )

    assert result.agent_case_id == "cleanup-worklist-plan"
    assert result.agent_case_label
    assert result.agent_case_source == "embedded://cleanup-worklist-plan"
    assert result.output_preview == "actions..."


def test_measured_output_tokens_falls_back_to_char_estimate() -> None:
    script = _load_script_module()

    count, source = script.measured_output_token_count(output="a" * 40, completion_tokens=None)

    assert count == 10
    assert source == "estimated_chars_div_4"


def test_trial_results_store_preview_not_full_output() -> None:
    script = _load_script_module()

    trial = script.TrialResult(
        index=1,
        layer="throughput",
        status="PASS",
        elapsed_s=1.0,
        output_preview="preview",
        output_chars=4000,
    )

    assert "output" not in script.asdict(trial)
    assert script.asdict(trial)["output_preview"] == "preview"
