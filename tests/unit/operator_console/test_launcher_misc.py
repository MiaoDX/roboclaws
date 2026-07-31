from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import patch

from roboclaws.operator_console.launch_lifecycle import _new_run_id
from roboclaws.operator_console.launcher import (
    build_launch_argv,
    load_repo_dotenv,
    route_readiness,
)
from roboclaws.operator_console.routes import get_selection
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_MAP_BUILD,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
)
from tests.unit.operator_console.launcher_support import (
    KIMI_ENV,
    _free_port,
)


def test_new_console_run_id_is_filesystem_safe() -> None:
    run_id = _new_run_id(get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK))

    assert "/" not in run_id
    assert ":" not in run_id
    assert "::" not in run_id
    assert run_id.endswith(
        "-molmospaces-procthor-objaverse-val-0-mujoco-open-task-openai-agents-sdk"
        "-world-public-labels"
    )


def test_operator_console_sdk_map_build_does_not_select_baseline_profile(
    tmp_path: Path,
) -> None:
    route = get_selection(AGIBOT_SDK_MAP_BUILD)

    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={"context_json": str(tmp_path / "context.json")},
    )

    assert "agent_engine=openai-agents-sdk" in argv
    assert "preset=map-build" in argv
    assert not any(item.startswith("agent_sdk_perf_profile=") for item in argv)
    assert "--agent-sdk-perf-profile" not in argv


def test_provider_gate_requires_agent_key_route(tmp_path: Path, monkeypatch) -> None:
    for key in ("MM_API_KEY", "KIMI_API_KEY", "KIMI_API_KEY", "KIMI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    readiness = route_readiness(
        tmp_path,
        get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK),
        overrides={"port": _free_port()},
    )
    assert not readiness["can_start"]
    assert "KIMI_OPENAI_BASE_URL" in readiness["blocker"]
    assert "KIMI_API_KEY" in readiness["blocker"]
    assert readiness["blocker_kind"] == "needs_provider"


def test_provider_gate_auto_loads_kimi_env_from_repo_dotenv(tmp_path: Path, monkeypatch) -> None:
    for key in ("MM_API_KEY", "KIMI_API_KEY", "KIMI_API_KEY", "KIMI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "KIMI_OPENAI_BASE_URL=https://kimi.example.test/v1\nKIMI_API_KEY=from-dotenv\n",
        encoding="utf-8",
    )

    readiness = route_readiness(
        tmp_path,
        get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK),
        overrides={"port": _free_port()},
        env={},
    )
    assert readiness["can_start"] is True
    assert load_repo_dotenv(tmp_path, {})["KIMI_API_KEY"] == "from-dotenv"
    assert readiness["provider"]["provider"] == "kimi-openai-chat"


def test_provider_gate_allows_explicit_minimax_override_with_mm_key(tmp_path: Path) -> None:
    readiness = route_readiness(
        tmp_path,
        get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK),
        env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "minimax-responses"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "minimax-responses"
    assert readiness["provider"]["model"] == "MiniMax-M3"


def test_provider_gate_allows_final_openai_agents_profiles(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    minimax = route_readiness(
        tmp_path,
        route,
        env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "minimax-responses"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
    )
    assert minimax["can_start"] is True
    assert minimax["provider"]["provider"] == "minimax-responses"
    assert minimax["provider"]["driver"] == "openai-agents-sdk"
    assert minimax["provider"]["model"] == "MiniMax-M3"

    kimi = route_readiness(
        tmp_path,
        route,
        env={"KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1", "KIMI_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "kimi-openai-chat"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat"},
    )
    assert kimi["can_start"] is True
    assert kimi["provider"]["provider"] == "kimi-openai-chat"
    assert kimi["provider"]["driver"] == "openai-agents-sdk"
    assert kimi["provider"]["model"] == "kimi-k2.7-code"


def test_provider_gate_ignores_code_agent_model_alias_for_openai_agents(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    readiness = route_readiness(
        tmp_path,
        route,
        env={
            "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
            "KIMI_API_KEY": "key",
            "ROBOCLAWS_CODE_AGENT_MODEL": "kimi-k2.7-code",
        },
        overrides={"port": _free_port()},
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "kimi-openai-chat"
    assert readiness["provider"]["model"] == "kimi-k2.7-code"


def test_provider_gate_requires_kimi_base_url_and_key(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    missing_base_url = route_readiness(
        tmp_path,
        route,
        env={"KIMI_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "kimi-openai-chat"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat"},
    )

    assert missing_base_url["can_start"] is False
    assert missing_base_url["blocker_kind"] == "needs_provider"
    assert "KIMI_OPENAI_BASE_URL" in missing_base_url["blocker"]

    ready = route_readiness(
        tmp_path,
        route,
        env={"KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1", "KIMI_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "kimi-openai-chat"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat"},
    )

    assert ready["can_start"] is True
    assert ready["provider"]["provider"] == "kimi-openai-chat"


def test_provider_gate_uses_selected_openai_agents_provider(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    missing_default = route_readiness(tmp_path, route, env={})
    assert missing_default["can_start"] is False
    assert missing_default["provider"]["provider"] == "kimi-openai-chat"
    assert "KIMI_OPENAI_BASE_URL" in missing_default["blocker"]
    assert "KIMI_API_KEY" in missing_default["blocker"]

    minimax = route_readiness(
        tmp_path,
        route,
        env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "minimax-responses"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
    )
    assert minimax["can_start"] is True
    assert minimax["provider"]["provider"] == "minimax-responses"


def test_provider_gate_rejects_invalid_env_override(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        try:
            route_readiness(
                tmp_path,
                get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK),
                env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "system"},
            )
        except ValueError as exc:
            assert "unsupported provider profile override" in str(exc)
        else:  # pragma: no cover - assertion style keeps dependency surface small.
            raise AssertionError("expected invalid provider override to fail")

    with patch.dict(os.environ, {}, clear=True):
        try:
            route_readiness(
                tmp_path,
                get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK),
                env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "system"},
            )
        except ValueError as exc:
            assert "unsupported provider profile override" in str(exc)
        else:  # pragma: no cover - assertion style keeps dependency surface small.
            raise AssertionError("expected invalid Claude provider override to fail")


def test_mcp_port_gate_rejects_port_that_is_already_accepting_connections(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        readiness = route_readiness(
            tmp_path,
            route,
            overrides={"host": "127.0.0.1", "port": str(port)},
            env=KIMI_ENV,
        )

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "mcp_port_in_use"
    assert f"127.0.0.1:{port}" in readiness["blocker"]
    assert any(
        gate["id"] == "mcp_port_free" and gate["status"] == "needs_action"
        for gate in readiness["gates"]
    )


def test_openai_agents_open_task_route_uses_sdk_driver(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    argv = build_launch_argv(route, root=tmp_path, run_id="run-1")

    assert argv[:6] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-objaverse-val/0",
        "backend=mujoco",
        "agent_engine=openai-agents-sdk",
    ]
    assert not any(item.startswith("preset=") for item in argv)
    assert "evidence_lane=world-public-labels" in argv
    assert "provider_profile=kimi-openai-chat" in argv
    assert "scenario_setup=baseline" in argv
