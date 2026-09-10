from __future__ import annotations

from roboclaws.core.provider_catalog import provider_route_specs
from roboclaws.operator_console.redaction import redact_text


def test_redacts_env_values_authorization_and_api_key_patterns() -> None:
    text = (
        "Authorization: Bearer live-secret-token\n"
        "api_key=visible-secret\n"
        "base=https://secret.internal/v1\n"
        "codex=https://codex.secret/v1 codex-secret codex-private-model\n"
        "mimo=https://mimo.secret/v1 mimo-secret mimo-private-model\n"
        "sk-abcdefghijklmnopqrstuvwxyz\n"
    )
    redacted = redact_text(
        text,
        env={
            "MM_BASE_URL": "https://secret.internal/v1",
            "KIMI_API_KEY": "visible-secret",
            "CODEX_RESPONSES_API_KEY": "codex-secret",
            "CODEX_RESPONSES_BASE_URL": "https://codex.secret/v1",
            "CODEX_RESPONSES_MODEL": "codex-private-model",
            "MIMO_RESPONSES_API_KEY": "mimo-secret",
            "MIMO_RESPONSES_BASE_URL": "https://mimo.secret/v1",
            "MIMO_RESPONSES_MODEL": "mimo-private-model",
            "KIMI_OPENAI_BASE_URL": "https://kimi.secret/v1",
        },
    )
    assert "live-secret-token" not in redacted
    assert "visible-secret" not in redacted
    assert "codex-secret" not in redacted
    assert "mimo-secret" not in redacted
    assert "https://secret.internal/v1" not in redacted
    assert "https://codex.secret/v1" not in redacted
    assert "https://mimo.secret/v1" not in redacted
    assert "https://kimi.secret/v1" not in redacted
    assert "codex-private-model" not in redacted
    assert "mimo-private-model" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert redacted.count("[REDACTED]") >= 4


def test_redacts_every_catalog_provider_environment_value() -> None:
    env = {
        key: f"provider-secret-{index}-{key.lower()}"
        for index, key in enumerate(
            key for route in provider_route_specs() for key in route.required_env_keys
        )
    }

    redacted = redact_text(" ".join(env.values()), env=env)

    assert all(value not in redacted for value in env.values())
