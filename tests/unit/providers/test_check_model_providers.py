from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("profile", ["codex-responses", "kimi-openai-chat", "qwen-tp-responses"])
def test_retired_probe_cannot_report_empty_success(profile: str) -> None:
    script = _load_script_module()
    args = script.parse_args(["--probe", profile, "--require-all"])
    with pytest.raises(ValueError, match="unknown provider probe"):
        script.select_probes(args)


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


def test_provider_probe_defaults_cover_active_routes() -> None:
    script = _load_script_module()

    probes = {probe.probe_id: probe for probe in script.build_provider_probes()}

    assert set(probes) == {
        "provider:mimo-responses",
        "provider:mimo-tp-openai-chat",
        "provider:minimax-responses-m3",
    }


def test_provider_probe_defaults_exclude_unavailable_official_openai_route() -> None:
    script = _load_script_module()

    probes = {probe.probe_id: probe for probe in script.build_provider_probes()}

    assert "provider:openai-responses" not in probes
    assert all(probe.api_key_env != "OPENAI_API_KEY" for probe in probes.values())


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


@pytest.mark.parametrize("flags", [[], ["--require-all"]])
def test_missing_required_provider_fails_with_or_without_require_all(monkeypatch, flags) -> None:
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

    assert script.main(["--mode", "agents-sdk", "--dotenv", "", *flags]) == 1


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
    assert probes["agents-sdk:mimo-responses"].max_tokens >= 256
    assert probes["agents-sdk:mimo-tp-openai-chat"].model == "mimo-v2.6-pro"


def test_mimo_tp_agents_sdk_probe_uses_chat_transport(
    monkeypatch,
) -> None:
    script = _load_script_module()
    captured: dict[str, object] = {}
    monkeypatch.setenv("MIMO_TP_KEY", "fake-mimo-key")

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
        "agents-sdk:mimo-tp-openai-chat"
    ]

    result = script.run_probe(
        probe,
        prompt="Health check. Reply exactly ok.",
        timeout_s=1.0,
    )

    assert result.status == "PASS"
    assert result.ok is True
    assert captured["model"] == "mimo-v2.6-pro"
    assert "extra_headers" not in captured["model_settings"]
    assert "extra_body" not in captured["model_settings"]


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
        "agents-sdk:mimo-tp-openai-chat",
        "agents-sdk:minimax-responses",
    }
    public_routes = {
        "mimo-tp-openai-chat",
        "minimax-responses",
    }
    assert all(probe.route_id in public_routes for probe in selected)


def test_public_profile_rejects_explicit_internal_route() -> None:
    script = _load_script_module()
    args = script.parse_args(["--profile", "agents-sdk-public", "--probe", "mimo-responses"])
    with pytest.raises(ValueError, match="unknown provider probe"):
        script.select_probes(args)


@pytest.mark.parametrize("status", ["FAIL", "SKIP", "UNSUPPORTED"])
def test_only_passing_probe_is_ok(status: str) -> None:
    script = _load_script_module()
    result = script.ProbeResult(
        probe_id="agents-sdk:minimax-responses",
        mode="agents-sdk",
        wire_api="responses",
        model="MiniMax-M3",
        status=status,
        elapsed_s=0.0,
    )
    assert result.ok is False
