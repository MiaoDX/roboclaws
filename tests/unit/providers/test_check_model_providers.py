from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_script_module():
    path = Path("scripts/dev/check_model_providers.py")
    spec = importlib.util.spec_from_file_location("check_model_providers", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_provider_health_defaults_leave_room_for_reasoning_tokens() -> None:
    script = _load_script_module()

    assert script.DEFAULT_RESPONSES_MAX_OUTPUT_TOKENS >= 256
    assert script.DEFAULT_CHAT_MAX_TOKENS >= 128


def test_provider_probe_defaults_cover_kimi_and_payload() -> None:
    script = _load_script_module()

    probes = {probe.probe_id: probe for probe in script.build_provider_probes()}

    assert set(probes) == {
        "provider:codex-responses",
        "provider:mimo-responses",
        "provider:minimax-responses-m3",
        "provider:kimi-coding-chat",
    }
    kimi = probes["provider:kimi-coding-chat"]
    payload = script.kimi_coding_payload(
        prompt="Health check. Reply exactly ok.",
        model=kimi.model,
        max_tokens=kimi.max_tokens,
    )
    assert payload["max_tokens"] >= 128
    assert payload["stream"] is False
    assert "thinking" not in payload
    assert "temperature" not in payload


def test_provider_probe_defaults_exclude_unavailable_official_openai_route() -> None:
    script = _load_script_module()

    probes = {probe.probe_id: probe for probe in script.build_provider_probes()}

    assert "provider:openai-responses" not in probes
    assert all(probe.api_key_env != "OPENAI_API_KEY" for probe in probes.values())


def test_codex_probes_do_not_apply_private_transport_headers(monkeypatch) -> None:
    script = _load_script_module()
    captured: dict[str, object] = {}
    monkeypatch.setenv("CODEX_RESPONSES_API_KEY", "fake-codex-key")
    monkeypatch.setenv("CODEX_RESPONSES_BASE_URL", "https://codex.example/v1")
    monkeypatch.setenv("CODEX_RESPONSES_MODEL", "opaque-model")

    class FakeModelSettings:
        def __init__(self, **_kwargs) -> None:
            pass

    class FakeAgent:
        def __init__(self, **_kwargs) -> None:
            pass

    class FakeRunner:
        @staticmethod
        def run_sync(*_args, **_kwargs):
            return type("Result", (), {"final_output": "ok"})()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs) -> None:
            captured["async_client"] = kwargs

    class FakeResponsesModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["request_model"] = model
            captured["model_client"] = openai_client

    class FakeResponses:
        @staticmethod
        def create(**_kwargs):
            return type("Response", (), {"status": "completed", "output_text": "ok"})()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured["sync_client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setitem(
        sys.modules,
        "agents",
        type(
            "FakeAgentsModule",
            (),
            {
                "Agent": FakeAgent,
                "ModelSettings": FakeModelSettings,
                "OpenAIChatCompletionsModel": object,
                "OpenAIResponsesModel": FakeResponsesModel,
                "Runner": FakeRunner,
                "set_tracing_disabled": staticmethod(lambda *_args, **_kwargs: None),
            },
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "openai",
        type(
            "FakeOpenAIModule",
            (),
            {"AsyncOpenAI": FakeAsyncOpenAI, "OpenAI": FakeOpenAI},
        ),
    )

    agent_probe = {probe.probe_id: probe for probe in script.build_agent_sdk_probes()}[
        "agents-sdk:codex-responses"
    ]
    raw_probe = {probe.probe_id: probe for probe in script.build_provider_probes()}[
        "provider:codex-responses"
    ]

    assert script.run_probe(agent_probe, prompt="ok", timeout_s=1.0).status == "PASS"
    assert script.run_probe(raw_probe, prompt="ok", timeout_s=1.0).status == "PASS"
    assert agent_probe.model == "codex"
    assert raw_probe.model == "codex"
    assert captured["request_model"] == "opaque-model"
    for client_key in ("async_client", "sync_client"):
        assert "default_headers" not in captured[client_key]


def test_mimo_probe_results_redact_endpoint_key_and_request_model(monkeypatch) -> None:
    script = _load_script_module()
    canary_url = "https://private-route-canary.example/v1"
    canary_key = "custom-key-canary-123456"
    canary_model = "private-model-canary-654321"
    monkeypatch.setenv("MIMO_RESPONSES_BASE_URL", canary_url)
    monkeypatch.setenv("MIMO_RESPONSES_API_KEY", canary_key)
    monkeypatch.setenv("MIMO_RESPONSES_MODEL", canary_model)
    probe = {probe.probe_id: probe for probe in script.build_provider_probes()}[
        "provider:mimo-responses"
    ]

    monkeypatch.setattr(
        script,
        "_run_responses_probe",
        lambda *_args, **_kwargs: f"ok {canary_url} {canary_key} {canary_model}",
    )
    passed = script.run_probe(probe, prompt="ok", timeout_s=1.0)
    monkeypatch.setattr(
        script,
        "_run_responses_probe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"failed {canary_url} {canary_key} {canary_model}")
        ),
    )
    failed = script.run_probe(probe, prompt="ok", timeout_s=1.0)

    serialized = json.dumps([passed.__dict__, failed.__dict__])
    assert passed.model == "mimo"
    assert failed.model == "mimo"
    for canary in (canary_url, canary_key, canary_model):
        assert canary not in serialized


def test_require_all_fails_on_skipped_probe(monkeypatch) -> None:
    script = _load_script_module()
    monkeypatch.delenv("MM_API_KEY", raising=False)
    monkeypatch.setattr(
        script,
        "build_agent_sdk_probes",
        lambda responses_max_tokens, chat_max_tokens: [
            script.ProbeSpec(
                probe_id="agents-sdk:minimax-responses",
                mode="agents-sdk",
                route_id="minimax-responses",
                wire_api=script.WIRE_RESPONSES,
                model="MiniMax-M3",
                api_key_env="MM_API_KEY",
                base_url="https://api.minimaxi.com/v1",
                max_tokens=responses_max_tokens,
            )
        ],
    )
    monkeypatch.setattr(script, "build_provider_probes", lambda **_kwargs: [])

    assert script.main(["--mode", "agents-sdk", "--dotenv", "", "--require-all"]) == 1


def test_load_dotenv_uses_explicit_file_and_preserves_existing_env(
    tmp_path: Path, monkeypatch
) -> None:
    script = _load_script_module()
    dotenv = tmp_path / "providers.env"
    dotenv.write_text('MM_API_KEY="from file"\nKEEP=from-file\n', encoding="utf-8")
    monkeypatch.delenv("MM_API_KEY", raising=False)
    monkeypatch.setenv("KEEP", "host")

    script.load_dotenv(dotenv)

    assert script.os.environ["MM_API_KEY"] == "from file"
    assert script.os.environ["KEEP"] == "host"


def test_agents_sdk_probe_defaults_use_larger_responses_budget() -> None:
    script = _load_script_module()

    probes = {probe.probe_id: probe for probe in script.build_agent_sdk_probes()}

    assert probes["agents-sdk:minimax-responses"].max_tokens >= 256
    assert probes["agents-sdk:codex-responses"].max_tokens >= 256
    assert probes["agents-sdk:mimo-responses"].max_tokens >= 256
    assert probes["agents-sdk:kimi-openai-chat"].model == "kimi-k2.7-code"
    assert not probes["agents-sdk:kimi-openai-chat"].unsupported_reason


def test_kimi_agents_sdk_probe_uses_coding_agent_user_agent_header(
    monkeypatch,
) -> None:
    script = _load_script_module()
    captured: dict[str, object] = {}
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")

    class FakeModelSettings:
        def __init__(self, **kwargs) -> None:
            captured["model_settings"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured["agent"] = kwargs

    class FakeRunner:
        @staticmethod
        def run_sync(*_args, **_kwargs):
            return type("Result", (), {"final_output": "ok"})()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

    class FakeChatModel:
        def __init__(self, model: str, *, openai_client: object) -> None:
            captured["model"] = model
            captured["model_client"] = openai_client

    monkeypatch.setitem(
        sys.modules,
        "agents",
        type(
            "FakeAgentsModule",
            (),
            {
                "Agent": FakeAgent,
                "ModelSettings": FakeModelSettings,
                "OpenAIChatCompletionsModel": FakeChatModel,
                "OpenAIResponsesModel": object,
                "Runner": FakeRunner,
                "set_tracing_disabled": staticmethod(lambda *_args, **_kwargs: None),
            },
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "openai",
        type("FakeOpenAIModule", (), {"AsyncOpenAI": FakeAsyncOpenAI}),
    )
    probe = {probe.probe_id: probe for probe in script.build_agent_sdk_probes()}[
        "agents-sdk:kimi-openai-chat"
    ]

    result = script.run_probe(
        probe,
        prompt="Health check. Reply exactly ok.",
        timeout_s=1.0,
    )

    assert result.status == "PASS"
    assert result.ok is True
    assert captured["model"] == "kimi-k2.7-code"
    assert captured["model_settings"]["extra_headers"] == {"User-Agent": "claude-code/1.0.0"}
    assert "extra_body" not in captured["model_settings"]


def _install_fake_httpx(monkeypatch, *, response_text: str, status_error: Exception | None = None):
    captured: dict[str, object] = {}

    class FakeResponse:
        text = response_text

        @staticmethod
        def raise_for_status() -> None:
            if status_error is not None:
                raise status_error

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        @staticmethod
        def post(*_args, **kwargs):
            captured["post"] = kwargs
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", type("FakeHttpxModule", (), {"Client": FakeClient}))
    return captured


def test_kimi_provider_probe_validates_provider_response_source(monkeypatch) -> None:
    script = _load_script_module()
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    probe = {probe.probe_id: probe for probe in script.build_provider_probes()}[
        "provider:kimi-coding-chat"
    ]
    _install_fake_httpx(monkeypatch, response_text='["not-an-object"]')

    result = script.run_probe(probe, prompt="Health check. Reply exactly ok.", timeout_s=1.0)

    assert result.status == "FAIL"
    assert result.error_type == "ValueError"
    assert "Kimi coding provider response source must contain a JSON object" in result.error
    assert "provider:kimi-coding-chat" in result.error


def test_kimi_provider_probe_validates_response_message_shape(monkeypatch) -> None:
    script = _load_script_module()
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    probe = {probe.probe_id: probe for probe in script.build_provider_probes()}[
        "provider:kimi-coding-chat"
    ]
    _install_fake_httpx(monkeypatch, response_text=json.dumps({"choices": [{"message": []}]}))

    result = script.run_probe(probe, prompt="Health check. Reply exactly ok.", timeout_s=1.0)

    assert result.status == "FAIL"
    assert result.error_type == "RuntimeError"
    assert "choices[0].message must be a JSON object" in result.error
    assert "provider:kimi-coding-chat" in result.error


def test_kimi_provider_probe_reads_reasoning_content_from_valid_response(monkeypatch) -> None:
    script = _load_script_module()
    monkeypatch.setenv("KIMI_API_KEY", "fake-kimi-key")
    probe = {probe.probe_id: probe for probe in script.build_provider_probes()}[
        "provider:kimi-coding-chat"
    ]
    captured = _install_fake_httpx(
        monkeypatch,
        response_text=json.dumps({"choices": [{"message": {"reasoning_content": "ok"}}]}),
    )

    result = script.run_probe(probe, prompt="Health check. Reply exactly ok.", timeout_s=1.0)

    assert result.status == "PASS"
    assert result.output == "ok"
    assert captured["post"]["headers"]["User-Agent"] == "claude-code/1.0.0"


def test_select_probe_can_limit_by_route_or_probe_id() -> None:
    script = _load_script_module()
    args = script.parse_args(["--mode", "all", "--probe", "minimax-responses"])

    selected = script.select_probes(args)

    assert {probe.probe_id for probe in selected} == {
        "agents-sdk:minimax-responses",
        "provider:minimax-responses-m3",
    }


def test_agents_sdk_public_profile_excludes_internal_routes() -> None:
    script = _load_script_module()
    args = script.parse_args(["--profile", "agents-sdk-public"])

    selected = script.select_probes(args)

    assert {probe.probe_id for probe in selected} == {
        "agents-sdk:codex-responses",
        "agents-sdk:mimo-responses",
        "agents-sdk:minimax-responses",
        "agents-sdk:kimi-openai-chat",
    }
    public_routes = {
        "codex-responses",
        "mimo-responses",
        "minimax-responses",
        "kimi-openai-chat",
    }
    assert all(probe.route_id in public_routes for probe in selected)


def test_select_probe_can_limit_kimi_route_across_sdk_and_provider_probes() -> None:
    script = _load_script_module()
    args = script.parse_args(["--mode", "all", "--probe", "kimi-openai-chat"])

    selected = script.select_probes(args)

    assert {probe.probe_id for probe in selected} == {
        "agents-sdk:kimi-openai-chat",
        "provider:kimi-coding-chat",
    }
