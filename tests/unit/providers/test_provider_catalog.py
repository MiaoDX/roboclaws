from __future__ import annotations

from unittest.mock import patch

import pytest

from roboclaws.agents.provider_registry import (
    ROUTE_BLOCKED,
    ROUTE_CAP_UNKNOWN,
    ROUTE_EXPERIMENTAL,
    ROUTE_HEALTHY,
    _main,
    default_enabled_models,
    default_enabled_provider_routes,
    model_aliases,
    normalize_provider_route,
    openai_agents_runtime_settings,
    openclaw_model_id,
    provider_readiness,
    provider_route_spec,
    required_env_keys,
    resolve_model,
    resolve_route_model,
    route_base_url,
    route_capabilities_for_engine,
)
from roboclaws.core.provider_factory import create_provider
from roboclaws.core.providers.kimi import KimiCodingProvider
from roboclaws.core.providers.openai import MimoProvider, NvidiaProvider


def test_resolve_model_records_alias_env_and_capabilities() -> None:
    meta = resolve_model("kimi")

    assert meta.model_id == "kimi-k2.7-code"
    assert meta.family == "kimi"
    assert meta.direct_provider_adapter == "kimi-coding"
    assert meta.direct_required_env_keys == ("KIMI_API_KEY",)
    assert meta.supports_image_input is True


def test_provider_registry_exposes_aliases_without_duplicate_source() -> None:
    aliases = model_aliases()

    assert aliases["nvidia"] == "meta/llama-4-maverick-17b-128e-instruct"
    assert aliases["mimo"] == "mimo-v2.5"
    assert aliases["mimo-v2.5"] == "mimo-v2.5"
    assert aliases["mimo-ultraspeed"] == "mimo-1000"
    assert aliases["mimo-mify-v2.5-pro"] == "xiaomi/mimo-v2.5-pro"
    assert aliases["kimi-code"] == "kimi-k2.7-code"
    assert "mimo-" + "omni" not in aliases
    assert "mimo-v2-" + "omni" not in aliases


def test_provider_registry_reports_required_env_keys() -> None:
    assert required_env_keys("nvidia") == ("NVIDIA_API_KEY", "NV_API_KEY")
    assert required_env_keys("mimo") == ("MIMO_TP_KEY",)


def test_provider_factory_routes_through_catalog(monkeypatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("MIMO_TP_KEY", "test-key")

    with patch("roboclaws.core.provider_factory.KimiCodingProvider.__init__", return_value=None):
        assert isinstance(create_provider("kimi"), KimiCodingProvider)
    with patch("roboclaws.core.provider_factory.NvidiaProvider.__init__", return_value=None):
        assert isinstance(create_provider("nvidia"), NvidiaProvider)
    with patch("roboclaws.core.provider_factory.MimoProvider.__init__", return_value=None):
        assert isinstance(create_provider("mimo"), MimoProvider)


def test_catalog_reports_all_real_models_image_capable() -> None:
    # mimo-v2.5 has native vision; every non-mock catalog model is image-capable.
    assert resolve_model("mimo_openai/mimo-v2.5").supports_image_input is True
    assert resolve_model("mimo_anthropic/mimo-v2.5").supports_image_input is True
    assert resolve_model("anthropic_kimi/k2p5").supports_image_input is True


def test_catalog_returns_openclaw_model_identifier() -> None:
    assert openclaw_model_id("mimo-v2.5") == "mimo_openai/mimo-v2.5"
    assert openclaw_model_id("kimi-k2-5") == "anthropic_kimi/k2p5"


def test_registry_marks_mify_responses_sdk_only() -> None:
    route = provider_route_spec("mimo-mify-responses")

    assert route.supported_engines == ("openai-agents-sdk",)
    assert route.wire_api == "responses"
    assert route.default_model_id == "xiaomi/mimo-v2.5-pro"
    assert route.compatible_model_ids == ("xiaomi/mimo-v2.5-pro",)
    assert route.status_for_engine("openai-agents-sdk") == ROUTE_HEALTHY


def test_kimi_openai_chat_defaults_to_current_code_model() -> None:
    route = provider_route_spec("kimi-openai-chat")
    model = resolve_model(route.default_model_id)

    assert route.default_model_id == "kimi-k2.7-code"
    assert route.status_for_engine("openai-agents-sdk") == ROUTE_EXPERIMENTAL
    assert route.default_use is True
    assert model.default_use is True
    assert "thinking-only" in route.default_use_note
    assert "canonical" in route.default_use_note
    assert "arbitrary K2.7 suffixes" in model.default_use_note


def test_default_enabled_routes_use_only_mify_for_mimo() -> None:
    routes = default_enabled_provider_routes()
    route_ids = {route.route_id for route in routes}
    public_profiles = {route.public_profile for route in routes}
    model_ids = {model.model_id for model in default_enabled_models()}

    assert {
        "codex-router-responses",
        "mimo-mify-responses",
        "minimax-responses",
        "kimi-openai-chat",
    } <= route_ids
    assert {
        "codex-router-responses",
        "mimo-mify-responses",
        "minimax-responses",
        "kimi-openai-chat",
    } <= public_profiles
    assert {
        "gpt-5.6-sol",
        "xiaomi/mimo-v2.5-pro",
        "MiniMax-M3",
        "kimi-k2.7-code",
    } <= model_ids
    assert "mimo-v2.5" not in model_ids
    assert "mimo-1000" not in model_ids
    assert "MiniMax-M2.7-highspeed" not in model_ids
    assert "kimi-k2.7-code-highspeed" not in model_ids


def test_mimo_inside_is_paused_but_remains_available_for_diagnostics() -> None:
    route = provider_route_spec("mimo-inside-openai-chat")

    assert route.default_model_id == "mimo-1000"
    assert route.default_use is False
    assert route.supported_engines == ("openai-agents-sdk",)
    assert route.base_url_env == "MIMO_BASE_URL"
    assert route.api_key_env == "MIMO_API_KEY"
    assert route.required_env_keys == ("MIMO_BASE_URL", "MIMO_API_KEY")
    assert route.status_for_engine("openai-agents-sdk") == ROUTE_BLOCKED


def test_mimo_token_plan_is_paused_but_remains_available_for_diagnostics() -> None:
    route = provider_route_spec("mimo-tp-openai-chat")

    assert route.default_model_id == "mimo-v2.5"
    assert route.default_use is False
    assert route.supported_engines == ("openai-agents-sdk",)
    assert route.status_for_engine("openai-agents-sdk") == ROUTE_HEALTHY
    assert resolve_route_model(route.route_id, None).model_id == "mimo-v2.5"


def test_codex_router_defaults_to_gpt_56_sol_and_keeps_gpt_55_compatible() -> None:
    route = provider_route_spec("codex-router-responses")

    assert route.default_model_id == "gpt-5.6-sol"
    assert route.compatible_model_ids == ("gpt-5.6-sol", "gpt-5.5")
    assert resolve_route_model(route.route_id, None).model_id == "gpt-5.6-sol"
    assert resolve_route_model(route.route_id, "gpt-5.5").model_id == "gpt-5.5"


def test_mimo_inside_readiness_requires_base_url_and_api_key() -> None:
    missing_base_url = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="mimo-inside-openai-chat",
        env={"MIMO_API_KEY": "key"},
    )

    assert missing_base_url["ok"] is False
    assert missing_base_url["missing_env"] == ["MIMO_BASE_URL"]
    assert "MIMO_BASE_URL and MIMO_API_KEY" in missing_base_url["message"]

    ready = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="mimo-inside-openai-chat",
        env={"MIMO_BASE_URL": "https://inside.example/v1", "MIMO_API_KEY": "key"},
    )

    assert ready["ok"] is True
    assert ready["missing_env"] == []
    assert ready["model"] == "mimo-1000"


def test_provider_route_aliases_normalize_to_public_profiles() -> None:
    assert provider_route_spec("mimo-mify-responses").public_profile == "mimo-mify-responses"
    assert provider_route_spec("mimo-mify-responses").route_id == "mimo-mify-responses"
    assert provider_route_spec("mimo-inside-openai-chat").route_id == "mimo-inside-openai-chat"
    assert provider_route_spec("mimo-mify-anthropic").route_id == "mimo-mify-anthropic"
    assert normalize_provider_route("minimax-responses") == "minimax-responses"


def test_provider_routes_accept_adjacent_base_url_env_overrides() -> None:
    assert provider_route_spec("mimo-tp-anthropic").base_url_env == "MIMO_ANTHROPIC_BASE_URL"
    assert (
        route_base_url(
            provider_route_spec("mimo-tp-anthropic"),
            env={"MIMO_ANTHROPIC_BASE_URL": "https://mimo.example/anthropic"},
        )
        == "https://mimo.example/anthropic"
    )


def test_mify_anthropic_route_rejects_conflicting_base_url_envs() -> None:
    route = provider_route_spec("mimo-mify-anthropic")

    assert (
        route_base_url(
            route,
            env={
                "XM_LLM_BASE_URL": "https://api.llm.example/v1",
                "XM_LLM_ANTHROPIC_BASE_URL": "https://api.llm.example/anthropic",
            },
        )
        == "https://api.llm.example/anthropic"
    )
    with pytest.raises(
        ValueError,
        match="conflicting provider route base_url for mimo-mify-anthropic",
    ) as exc_info:
        route_base_url(
            route,
            env={
                "XM_LLM_BASE_URL": "https://api.llm.example/v1",
                "XM_LLM_ANTHROPIC_BASE_URL": "https://anthropic.example",
            },
        )
    assert "XM_LLM_ANTHROPIC_BASE_URL='https://anthropic.example'" in str(exc_info.value)
    assert "XM_LLM_BASE_URL derives 'https://api.llm.example/anthropic'" in str(exc_info.value)


def test_mify_anthropic_readiness_reports_retired_claude_engine() -> None:
    readiness = provider_readiness(
        agent_engine="claude-code",
        provider_profile="mimo-mify-anthropic",
        env={
            "XM_LLM_API_KEY": "key",
            "XM_LLM_BASE_URL": "https://api.llm.example/v1",
            "XM_LLM_ANTHROPIC_BASE_URL": "https://anthropic.example",
        },
    )

    assert readiness["ok"] is False
    assert readiness["missing_env"] == []
    assert readiness["route_status"] == "retired"
    assert "unsupported agent_engine 'claude-code'" in readiness["message"]


def test_registry_keeps_raw_fpv_transport_separate_from_model_modality() -> None:
    route = provider_route_spec("minimax-responses")
    model = resolve_model("MiniMax-M3")

    assert model.supports_image_input is True
    assert route.default_model_id == "MiniMax-M3"
    assert route.default_use is True
    assert route.supported_engines == ("openai-agents-sdk",)
    assert route.status_for_engine("openai-agents-sdk") == ROUTE_HEALTHY
    assert route_capabilities_for_engine(route, "openai-agents-sdk")["image_transport"] == (
        ROUTE_CAP_UNKNOWN
    )
    assert route.status_note == "OpenAI Agents SDK structured cleanup works."


def test_provider_readiness_reports_status_and_missing_env() -> None:
    readiness = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="mimo-mify-responses",
        env={},
    )

    assert readiness["provider"] == "mimo-mify-responses"
    assert readiness["route_status"] == ROUTE_HEALTHY
    assert readiness["missing_env"] == ["XM_LLM_API_KEY"]


def test_provider_readiness_rejects_unknown_model_override() -> None:
    readiness = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="codex-router-responses",
        model="not-in-provider-catalog",
        env={"CODEX_BASE_URL": "https://codex.example.test/v1", "CODEX_API_KEY": "key"},
    )

    assert readiness["ok"] is False
    assert readiness["missing_env"] == []
    assert readiness["model"] == "not-in-provider-catalog"
    assert "unknown model 'not-in-provider-catalog'" in readiness["message"]
    assert "provider_profile codex-router-responses" in readiness["message"]


def test_provider_readiness_rejects_route_incompatible_model_override() -> None:
    readiness = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="minimax-responses",
        model="gpt-5.5",
        env={"MM_API_KEY": "key"},
    )

    assert readiness["ok"] is False
    assert readiness["missing_env"] == []
    assert readiness["model"] == "gpt-5.5"
    assert readiness["model_family"] == "unknown"
    assert (
        "model 'gpt-5.5' is incompatible with provider_profile 'minimax-responses'"
        in (readiness["message"])
    )
    assert "expected one of MiniMax-M3" in readiness["message"]


def test_provider_route_model_rejects_kimi_non_catalog_suffix() -> None:
    with pytest.raises(KeyError):
        resolve_route_model("kimi-openai-chat", "kimi-k2.7-code-highspeed")


def test_provider_route_model_rejects_same_family_wrong_route_model() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "model 'mimo-1000' is incompatible with provider_profile "
            "'mimo-mify-responses'; expected one of xiaomi/mimo-v2.5-pro"
        ),
    ):
        resolve_route_model("mimo-mify-responses", "mimo-1000")


def test_provider_readiness_rejects_unknown_provider_profile() -> None:
    readiness = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="not-a-provider-route",
        env={"CODEX_BASE_URL": "https://codex.example.test/v1", "CODEX_API_KEY": "key"},
    )

    assert readiness["ok"] is False
    assert readiness["provider_profile"] == "not-a-provider-route"
    assert readiness["missing_env"] == []
    assert "provider_profile 'not-a-provider-route' is unknown" in readiness["message"]
    assert "agent_engine 'openai-agents-sdk'" in readiness["message"]


def test_openai_agents_runtime_settings_reject_unknown_model_override() -> None:
    with pytest.raises(
        ValueError,
        match="OpenAI Agents SDK setting model is unknown, got 'not-in-provider-catalog'",
    ):
        openai_agents_runtime_settings(
            provider_profile="codex-router-responses",
            request_provider_profile=None,
            model="not-in-provider-catalog",
            request_model=None,
            base_url=None,
            api_key=None,
            env={"CODEX_BASE_URL": "https://codex.example.test/v1", "CODEX_API_KEY": "key"},
        )


def test_openai_agents_runtime_settings_reject_route_incompatible_model_override() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "OpenAI Agents SDK setting model is incompatible: model 'gpt-5.5' "
            "is incompatible with provider_profile 'minimax-responses'"
        ),
    ):
        openai_agents_runtime_settings(
            provider_profile="minimax-responses",
            request_provider_profile=None,
            model="gpt-5.5",
            request_model=None,
            base_url=None,
            api_key=None,
            env={"MM_API_KEY": "key"},
        )


def test_provider_registry_cli_dispatches_route_and_json_commands(
    tmp_path,
    capsys,
) -> None:
    output = tmp_path / "providers.json"

    assert _main(["json", "--output", str(output)]) == 0
    assert "codex-router-responses" in output.read_text(encoding="utf-8")
    assert _main(["default-model", "minimax-responses"]) == 0
    assert capsys.readouterr().out.strip() == "MiniMax-M3"
    with pytest.raises(SystemExit):
        _main(["model-id", "kimi-code-highspeed"])
    assert "unknown model" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _main(["provider-model-id", "kimi-openai-chat", "kimi-k2.7-code-highspeed"])
    assert "unknown provider/model id 'kimi-k2.7-code-highspeed'" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _main(["provider-model-id", "minimax-responses", "gpt-5.5"])
    assert "incompatible with provider_profile 'minimax-responses'" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        _main(["public-profile", "not-a-provider-route"])
    captured = capsys.readouterr()
    assert "provider_profile 'not-a-provider-route' is unknown" in captured.err
    assert "Traceback" not in captured.err
    assert _main(["supports-engine", "minimax-responses", "openai-agents-sdk"]) == 0
    assert _main(["supports-engine", "mimo-tp-openai-chat", "codex-cli"]) == 1
