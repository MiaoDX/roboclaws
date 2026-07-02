from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launcher import (
    ConsoleLaunchError,
    LaunchRequest,
    route_readiness,
    start_console_run,
)
from roboclaws.operator_console.routes import get_selection
from tests.support.b1_robot_proof import write_b1_robot_proof_artifacts
from tests.unit.operator_console.conftest import (
    B1_OPENAI_AGENTS_OPEN_TASK,  # noqa: F401  re-exported for tests
)


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def test_provider_gate_rejects_conflicting_provider_profile_env_override(tmp_path: Path) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)

    with pytest.raises(ConsoleLaunchError, match="conflicting provider profile selection"):
        route_readiness(
            tmp_path,
            route,
            env={"XM_LLM_API_KEY": "key"},
            overrides={"port": _free_port(), "provider_profile": "codex-router-responses"},
            env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "mimo-mify-responses"},
        )


def test_provider_gate_route_selection_overrides_ambient_provider_profile(tmp_path: Path) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    write_b1_robot_proof_artifacts(tmp_path)

    readiness = route_readiness(
        tmp_path,
        route,
        env={
            "CODEX_BASE_URL": "https://codex.example.test/v1",
            "CODEX_API_KEY": "key",
            "ROBOCLAWS_PROVIDER_PROFILE": "mimo-mify-responses",
        },
        overrides={
            "port": _free_port(),
            "provider_profile": "codex-router-responses",
        },
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "codex-router-responses"


def test_start_console_run_uses_one_provider_profile_selection(tmp_path: Path) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    write_b1_robot_proof_artifacts(tmp_path)
    seen_env: dict[str, str] = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args
        seen_env.update(kwargs["env"])
        return FakeProcess()

    with patch("roboclaws.operator_console.launcher.subprocess.Popen", side_effect=fake_popen):
        state = start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                provider_profile="mimo-mify-responses",
                overrides={"port": _free_port()},
            ),
            env={"XM_LLM_API_KEY": "key"},
        )

    assert seen_env["ROBOCLAWS_PROVIDER_PROFILE"] == "mimo-mify-responses"
    assert state["provider_profile"] == "mimo-mify-responses"
    assert "provider_profile=mimo-mify-responses" in state["argv"]
    assert state["env_overrides"] == {
        "ROBOCLAWS_PROVIDER_PROFILE": "mimo-mify-responses",
    }
