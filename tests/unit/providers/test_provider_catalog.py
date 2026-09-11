from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.provider_registry import (
    _main,
    openai_agents_runtime_settings,
    provider_readiness,
)
from roboclaws.core.dotenv import load_dotenv_file
from roboclaws.core.provider_catalog import (
    MODEL_CAP_TEXT,
    PROVIDER_PROFILE_CODEX_RESPONSES,
    PROVIDER_PROFILE_MIMO_RESPONSES,
    ROUTE_CAP_SUPPORTED,
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

REPO_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_PROFILES = (
    "codex-responses",
    "mimo-responses",
    "mimo-tp-openai-chat",
    "minimax-responses",
    "kimi-openai-chat",
    "qwen-tp-responses",
)


def test_openai_agents_registry_has_exact_public_profile_set() -> None:
    assert supported_provider_profiles("openai-agents-sdk") == EXPECTED_PROFILES
    assert tuple(route.route_id for route in provider_route_specs()) == EXPECTED_PROFILES
    assert default_provider_profile("openai-agents-sdk") is None


def test_env_example_tracks_active_provider_environment_contract() -> None:
    env_example = load_dotenv_file(REPO_ROOT / ".env.example", {})
    required_keys = {key for route in provider_route_specs() for key in route.required_env_keys}
    template_provider_keys = {
        key
        for key in env_example
        if key.endswith(("_API_KEY", "_BASE_URL", "_MODEL"))
        or key in {"MIMO_TP_KEY", "QWEN_TP_KEY"}
    }

    assert template_provider_keys == required_keys
    assert all(env_example[key] == "" for key in required_keys)
    assert (
        not {
            "MIMO_ANTHROPIC_BASE_URL",
            "NVIDIA_BASE_URL",
            "NV_API_KEY",
            "XM_LLM_ANTHROPIC_BASE_URL",
        }
        & env_example.keys()
    )


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
        "kimi",
        "kimi-k2.7-code",
        "k2.7-code",
        "kimi-code",
    ):
        assert deleted not in aliases
        with pytest.raises(KeyError):
            resolve_model(deleted)


def test_named_chat_profiles_have_catalog_models() -> None:
    chat_routes = [
        route for route in provider_route_specs() if route.wire_api == "chat-completions"
    ]
    assert [route.public_profile for route in chat_routes] == [
        "mimo-tp-openai-chat",
        "kimi-openai-chat",
    ]
    assert [resolve_model(route.default_model_id).family for route in chat_routes] == [
        "mimo",
        "kimi",
    ]


def test_mimo_tp_chat_readiness_uses_public_endpoint_credentials() -> None:
    route = provider_route_spec("mimo-tp-openai-chat")
    assert route.required_env_keys == ("MIMO_OPENAI_BASE_URL", "MIMO_TP_KEY")
    assert route.compatible_model_ids == ("mimo-v2.5-pro",)
    readiness = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile=route.route_id,
        env={
            "MIMO_OPENAI_BASE_URL": "https://mimo.example/v1",
            "MIMO_TP_KEY": "secret",
        },
    )
    assert readiness["ok"] is True
    assert readiness["model"] == "mimo-v2.5-pro"
    assert readiness["wire_api"] == "chat-completions"


def test_mimo_tp_chat_accepts_explicit_pro_model() -> None:
    settings = openai_agents_runtime_settings(
        provider_profile="mimo-tp-openai-chat",
        request_provider_profile=None,
        model="mimo-v2.5-pro",
        request_model="mimo-v2.5-pro",
        base_url=None,
        api_key=None,
        env={
            "MIMO_OPENAI_BASE_URL": "https://mimo.example/v1",
            "MIMO_TP_KEY": "secret",
        },
    )

    assert settings["model"] == "mimo-v2.5-pro"
    assert settings["request_model"] == "mimo-v2.5-pro"


def test_qwen_tp_responses_readiness_uses_public_endpoint_credentials() -> None:
    route = provider_route_spec("qwen-tp-responses")
    assert route.required_env_keys == ("QWEN_TP_BASE_URL", "QWEN_TP_KEY")
    assert route.compatible_model_ids == ("qwen3.8-max", "qwen3.8-flash")
    readiness = provider_readiness(
        agent_engine="openai-agents-sdk",
        provider_profile=route.route_id,
        env={
            "QWEN_TP_BASE_URL": "https://qwen.example/compatible-mode/v1",
            "QWEN_TP_KEY": "secret",
        },
    )
    assert readiness["ok"] is True
    assert readiness["model"] == "qwen3.8-max"
    assert readiness["wire_api"] == "responses"
    assert readiness["route_capabilities"] == {
        "image_transport": ROUTE_CAP_SUPPORTED,
        "tool_call_transport": ROUTE_CAP_SUPPORTED,
    }


def test_qwen_tp_responses_accepts_flash_and_rejects_foreign_model() -> None:
    resolved = resolve_route_model("qwen-tp-responses", "qwen3.8-flash")
    assert resolved.model_id == "qwen3.8-flash"
    assert resolved.family == "qwen"
    assert resolved.supports_image_input is True
    with pytest.raises(ValueError, match="incompatible"):
        resolve_route_model("qwen-tp-responses", "k3")


def test_mimo_responses_rejects_non_pro_model() -> None:
    with pytest.raises(ValueError, match="mimo-v2.5-pro"):
        resolve_route_model("mimo-responses", "mimo-v2.5")


@pytest.mark.parametrize("model", ("mimo-v2.5-pro", "xiaomi/mimo-v2.5-pro"))
def test_mimo_responses_accepts_provider_qualified_wire_model(model: str) -> None:
    resolved = resolve_route_model("mimo-responses", model)
    assert resolved.model_id == "mimo"


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
    model = resolve_route_model(
        route.route_id,
        "mimo-v2.5-pro" if profile == "mimo-responses" else "opaque-deployment-model-2026-07",
    )
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
            f"{env_prefix}_MODEL": "mimo-v2.5-pro"
            if profile == "mimo-responses"
            else "opaque-model",
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
