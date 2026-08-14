from __future__ import annotations

import json

import pytest

from roboclaws.agents.provider_registry import (
    _main,
    openai_agents_runtime_settings,
    provider_readiness,
)
from roboclaws.core.provider_catalog import (
    MODEL_CAP_TEXT,
    PROVIDER_PROFILE_CODEX_RESPONSES,
    PROVIDER_PROFILE_MIMO_RESPONSES,
    ROUTE_CAP_UNKNOWN,
    default_provider_profile,
    model_aliases,
    provider_route_spec,
    provider_route_specs,
    resolve_model,
    resolve_route_model,
    route_capabilities_for_engine,
    supported_provider_profiles,
)

EXPECTED_PROFILES = (
    "codex-responses",
    "mimo-responses",
    "minimax-responses",
    "kimi-openai-chat",
)


def test_openai_agents_registry_has_exact_public_profile_set() -> None:
    assert supported_provider_profiles("openai-agents-sdk") == EXPECTED_PROFILES
    assert tuple(route.route_id for route in provider_route_specs()) == EXPECTED_PROFILES
    assert default_provider_profile("openai-agents-sdk") is None


@pytest.mark.parametrize("agent_engine", ("codex-cli", "claude-code", "future-engine"))
def test_unknown_agent_engines_share_one_readiness_error(agent_engine: str) -> None:
    readiness = provider_readiness(
        agent_engine=agent_engine,
        provider_profile="kimi-openai-chat",
        env={},
    )

    assert readiness["ok"] is False
    assert readiness["message"] == (
        f"unsupported agent_engine '{agent_engine}'; expected direct-runner|openai-agents-sdk"
    )
    assert "route_status" not in readiness


@pytest.mark.parametrize(
    "deleted",
    [
        "retired-responses-route",
        "retired-chat-route",
        "retired-anthropic-route",
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
    ):
        assert deleted not in aliases


def test_kimi_is_only_chat_profile() -> None:
    chat_routes = [
        route for route in provider_route_specs() if route.wire_api == "chat-completions"
    ]
    assert [route.public_profile for route in chat_routes] == ["kimi-openai-chat"]
    assert resolve_model(chat_routes[0].default_model_id).family == "kimi"


@pytest.mark.parametrize(
    ("profile", "env_prefix", "public_model"),
    [
        (PROVIDER_PROFILE_CODEX_RESPONSES, "CODEX_RESPONSES", "codex"),
        (PROVIDER_PROFILE_MIMO_RESPONSES, "MIMO_RESPONSES", "mimo"),
    ],
)
def test_opaque_responses_routes_use_required_environment_and_public_model(
    profile: str,
    env_prefix: str,
    public_model: str,
) -> None:
    route = provider_route_spec(profile)
    assert route.required_env_keys == (
        f"{env_prefix}_BASE_URL",
        f"{env_prefix}_API_KEY",
        f"{env_prefix}_MODEL",
    )
    model = resolve_route_model(route.route_id, "opaque-deployment-model-2026-07")
    assert model.model_id == public_model
    assert model.family == public_model
    assert model.model_capabilities == frozenset({MODEL_CAP_TEXT})
    assert model.aliases == ()
    assert route_capabilities_for_engine(route, "openai-agents-sdk") == {
        "image_transport": ROUTE_CAP_UNKNOWN,
        "tool_call_transport": "supported",
    }


@pytest.mark.parametrize(
    ("profile", "env_prefix", "public_model"),
    [
        ("codex-responses", "CODEX_RESPONSES", "codex"),
        ("mimo-responses", "MIMO_RESPONSES", "mimo"),
    ],
)
def test_opaque_readiness_requires_url_key_and_model(
    profile: str,
    env_prefix: str,
    public_model: str,
) -> None:
    missing = provider_readiness(agent_engine="openai-agents-sdk", provider_profile=profile, env={})
    assert missing["ok"] is False
    assert missing["missing_env"] == [
        f"{env_prefix}_BASE_URL",
        f"{env_prefix}_API_KEY",
        f"{env_prefix}_MODEL",
    ]
    assert all(key in missing["message"] for key in missing["missing_env"])

    ready = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile=profile,
        env={
            f"{env_prefix}_BASE_URL": "https://provider.example/v1",
            f"{env_prefix}_API_KEY": "secret",
            f"{env_prefix}_MODEL": "opaque-model",
        },
    )
    assert ready["ok"] is True
    assert ready["model"] == public_model
    assert ready["model_family"] == public_model
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


@pytest.mark.parametrize(
    ("profile", "env_prefix", "public_model"),
    [
        ("codex-responses", "CODEX_RESPONSES", "codex"),
        ("mimo-responses", "MIMO_RESPONSES", "mimo"),
    ],
)
def test_opaque_runtime_settings_resolve_environment_model(
    profile: str,
    env_prefix: str,
    public_model: str,
) -> None:
    settings = openai_agents_runtime_settings(
        provider_profile=profile,
        request_provider_profile=None,
        model=None,
        request_model=None,
        base_url=None,
        api_key=None,
        env={
            f"{env_prefix}_BASE_URL": "https://provider.example/v1/",
            f"{env_prefix}_API_KEY": "secret",
            f"{env_prefix}_MODEL": "opaque-model",
        },
    )
    assert settings["provider_profile"] == profile
    assert settings["wire_api"] == "responses"
    assert settings["base_url"] == "https://provider.example/v1/"
    assert settings["api_key"] == "secret"
    assert settings["model"] == public_model
    assert settings["request_model"] == "opaque-model"
    assert settings["request_model_env"] == f"{env_prefix}_MODEL"


def test_named_profile_rejects_non_catalog_model() -> None:
    with pytest.raises(KeyError):
        resolve_route_model("kimi-openai-chat", "arbitrary-kimi-suffix")


def test_registry_cli_json_contains_only_final_profiles(tmp_path) -> None:
    output = tmp_path / "providers.json"
    assert _main(["json", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    route_ids = [route["route_id"] for route in payload["provider_routes"]]
    assert route_ids == list(EXPECTED_PROFILES)
