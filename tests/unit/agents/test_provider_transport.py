from __future__ import annotations

import uuid
from pathlib import Path

from roboclaws.agents.drivers.openai_agents_profile_runtime import (
    _sdk_model_settings_for_profile,
)
from roboclaws.agents.provider_transport import (
    CODEX_WINDOW_ID_HEADER,
    compatible_model_settings,
    provider_default_headers,
)


def test_codex_window_id_is_stable_per_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    first = provider_default_headers("codex-responses", session_seed=run_dir)
    resumed = provider_default_headers("codex-responses", session_seed=run_dir)
    other = provider_default_headers(
        "codex-responses",
        session_seed=tmp_path / "other-run",
    )

    assert first == resumed
    assert first != other
    thread_id, generation = first[CODEX_WINDOW_ID_HEADER].rsplit(":", 1)
    assert uuid.UUID(thread_id)
    assert generation == "0"


def test_non_codex_routes_do_not_receive_codex_headers(tmp_path: Path) -> None:
    for profile in ("mimo-responses", "minimax-responses", "kimi-openai-chat"):
        assert provider_default_headers(profile, session_seed=tmp_path) == {}


def test_codex_model_settings_omit_unsupported_truncation() -> None:
    settings = {"store": False, "truncation": "auto"}

    assert compatible_model_settings("codex-responses", settings) == {"store": False}
    assert compatible_model_settings("mimo-responses", settings) == settings
    assert settings["truncation"] == "auto"


def test_codex_product_profile_omits_unsupported_truncation() -> None:
    settings = _sdk_model_settings_for_profile(
        {
            "provider_profile": "codex-responses",
            "wire_api": "responses",
            "model_thinking_mode": "default",
        }
    )

    assert "truncation" not in settings
