from __future__ import annotations

import json

import pytest

from roboclaws.agents.provider_registry import (
    MODEL_CAP_TEXT,
    PROVIDER_PROFILE_CUSTOM_RESPONSES,
    ROUTE_CAP_UNKNOWN,
    _main,
    default_provider_profile,
    model_aliases,
    openai_agents_runtime_settings,
    provider_readiness,
    provider_route_spec,
    provider_route_specs,
    resolve_model,
    resolve_route_model,
    route_capabilities_for_engine,
    supported_provider_profiles,
)

EXPECTED_PROFILES = ("custom-responses", "minimax-responses", "kimi-openai-chat")


def test_openai_agents_registry_has_exact_public_profile_set() -> None:
    assert supported_provider_profiles("openai-agents-sdk") == EXPECTED_PROFILES
    assert tuple(route.route_id for route in provider_route_specs()) == EXPECTED_PROFILES
    assert default_provider_profile("openai-agents-sdk") is None


@pytest.mark.parametrize(
    "deleted",
    [
        "codex-router-responses",
        "mimo-mify-responses",
        "mimo-tp-openai-chat",
        "mimo-inside-openai-chat",
        "mimo-tp-anthropic",
        "mimo-mify-anthropic",
    ],
)
def test_deleted_provider_profiles_do_not_resolve(deleted: str) -> None:
    with pytest.raises(KeyError):
        provider_route_spec(deleted)


def test_deleted_model_aliases_are_absent() -> None:
    aliases = model_aliases()
    for deleted in (
        "nvidia",
        "nvidia-nano-vl",
        "mimo",
        "mimo-v2.5",
        "mimo-1000",
        "mimo-mify-v2.5-pro",
        "gpt-5.5",
        "gpt-5.6-sol",
    ):
        assert deleted not in aliases


def test_kimi_is_only_chat_profile() -> None:
    chat_routes = [
        route for route in provider_route_specs() if route.wire_api == "chat-completions"
    ]
    assert [route.public_profile for route in chat_routes] == ["kimi-openai-chat"]
    assert resolve_model(chat_routes[0].default_model_id).family == "kimi"


def test_custom_responses_uses_required_environment_and_opaque_model() -> None:
    route = provider_route_spec(PROVIDER_PROFILE_CUSTOM_RESPONSES)
    assert route.required_env_keys == (
        "CUSTOM_RESPONSES_BASE_URL",
        "CUSTOM_RESPONSES_API_KEY",
        "CUSTOM_RESPONSES_MODEL",
    )
    model = resolve_route_model(route.route_id, "opaque-deployment-model-2026-07")
    assert model.model_id == "custom"
    assert model.family == "custom"
    assert model.model_capabilities == frozenset({MODEL_CAP_TEXT})
    assert model.aliases == ()
    assert route_capabilities_for_engine(route, "openai-agents-sdk") == {
        "image_transport": ROUTE_CAP_UNKNOWN,
        "tool_call_transport": "supported",
    }


def test_custom_readiness_requires_url_key_and_model() -> None:
    missing = provider_readiness(
        agent_engine="openai-agents-sdk", provider_profile="custom-responses", env={}
    )
    assert missing["ok"] is False
    assert missing["missing_env"] == [
        "CUSTOM_RESPONSES_BASE_URL",
        "CUSTOM_RESPONSES_API_KEY",
        "CUSTOM_RESPONSES_MODEL",
    ]

    ready = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile="custom-responses",
        env={
            "CUSTOM_RESPONSES_BASE_URL": "https://custom.example/v1",
            "CUSTOM_RESPONSES_API_KEY": "secret",
            "CUSTOM_RESPONSES_MODEL": "opaque-model",
        },
    )
    assert ready["ok"] is True
    assert ready["model"] == "custom"
    assert ready["model_family"] == "custom"
    assert ready["model_capabilities"] == ["text"]


def test_openai_agents_settings_require_explicit_profile() -> None:
    with pytest.raises(ValueError, match="provider_profile is required"):
        openai_agents_runtime_settings(
            provider_profile=None,
            request_provider_profile=None,
            model=None,
            request_model=None,
            base_url=None,
            api_key=None,
            env={},
        )


def test_custom_runtime_settings_resolve_environment_model() -> None:
    settings = openai_agents_runtime_settings(
        provider_profile="custom-responses",
        request_provider_profile=None,
        model=None,
        request_model=None,
        base_url=None,
        api_key=None,
        env={
            "CUSTOM_RESPONSES_BASE_URL": "https://custom.example/v1/",
            "CUSTOM_RESPONSES_API_KEY": "secret",
            "CUSTOM_RESPONSES_MODEL": "opaque-model",
        },
    )
    assert settings["provider_profile"] == "custom-responses"
    assert settings["wire_api"] == "responses"
    assert settings["base_url"] == "https://custom.example/v1/"
    assert settings["api_key"] == "secret"
    assert settings["model"] == "custom"
    assert settings["request_model"] == "opaque-model"


def test_named_profile_rejects_non_catalog_model() -> None:
    with pytest.raises(KeyError):
        resolve_route_model("kimi-openai-chat", "arbitrary-kimi-suffix")


def test_registry_cli_json_contains_only_final_profiles(tmp_path) -> None:
    output = tmp_path / "providers.json"
    assert _main(["json", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    route_ids = [route["route_id"] for route in payload["provider_routes"]]
    assert route_ids == list(EXPECTED_PROFILES)
