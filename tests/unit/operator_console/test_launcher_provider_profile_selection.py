from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.launcher import (
    LaunchRequest,
    route_readiness,
    start_console_run,
)
from roboclaws.operator_console.routes import get_selection
from tests.support.b1_robot_proof import write_b1_readiness_fixtures
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
            env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
            overrides={"port": _free_port(), "provider_profile": "kimi-openai-chat"},
            env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
        )


def test_provider_gate_route_selection_overrides_ambient_provider_profile(tmp_path: Path) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    b1_overrides = write_b1_readiness_fixtures(tmp_path)

    readiness = route_readiness(
        tmp_path,
        route,
        env={
            "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
            "KIMI_API_KEY": "key",
            "ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses",
        },
        overrides={
            "port": _free_port(),
            "provider_profile": "kimi-openai-chat",
            **b1_overrides,
        },
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "kimi-openai-chat"


def test_start_console_run_uses_one_provider_profile_selection(tmp_path: Path) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    b1_overrides = write_b1_readiness_fixtures(tmp_path)
    seen_env: dict[str, str] = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args
        seen_env.update(kwargs["env"])
        return FakeProcess()

    with patch("roboclaws.operator_console.launcher.spawn_launch_plan", side_effect=fake_popen):
        state = start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                provider_profile="minimax-responses",
                overrides={"port": _free_port(), **b1_overrides},
            ),
            env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
        )

    assert seen_env["ROBOCLAWS_PROVIDER_PROFILE"] == "minimax-responses"
    assert state["provider_profile"] == "minimax-responses"
    assert "provider_profile=minimax-responses" in state["argv"]
    assert state["env_overrides"] == {
        "ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses",
    }
