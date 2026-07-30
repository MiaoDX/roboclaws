from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.launcher import (
    route_readiness,
    stop_console_run,
)
from roboclaws.operator_console.locks import ResourceLock
from roboclaws.operator_console.paths import console_output_root
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


def test_launcher_readiness_layers_isaac_and_agibot_gates(tmp_path: Path) -> None:
    map_bundle = tmp_path / "b1-map-bundle"
    map_bundle.mkdir()
    isaac_scene = tmp_path / "b1-scene.usd"
    isaac_scene.write_text("#usda 1.0\n", encoding="utf-8")
    b1_map12 = route_readiness(
        tmp_path,
        get_selection(B1_OPENAI_AGENTS_OPEN_TASK),
        overrides={
            "port": _free_port(),
            "map_bundle": str(map_bundle),
            "isaac_scene_usd_path": str(isaac_scene),
        },
        env=KIMI_ENV,
    )
    assert b1_map12["can_start"] is True
    assert b1_map12["blocker_kind"] == ""
    assert {gate["id"] for gate in b1_map12["gates"]} == {
        "provider_key",
        "mcp_port_free",
    }

    context_path = tmp_path / "context.json"
    context_path.write_text("{}", encoding="utf-8")
    runner_script = tmp_path / "runner.py"
    runner_script.write_text("# synthetic runner\n", encoding="utf-8")
    map_artifact_dir = tmp_path / "agibot-map"
    map_artifact_dir.mkdir()
    agibot_overrides = {
        "context_json": str(context_path),
        "runner_script": str(runner_script),
        "runner_python": os.sys.executable,
        "agibot_map_artifact_dir": str(map_artifact_dir),
    }
    agibot = route_readiness(
        tmp_path,
        get_selection(AGIBOT_SDK_MAP_BUILD),
        overrides={**agibot_overrides, "port": _free_port()},
        gates={"localization_ready": True, "run_enabled": False, "estop_ready": True},
        env=KIMI_ENV,
    )
    assert agibot["can_start"] is True
    run_gate = next(gate for gate in agibot["gates"] if gate["id"] == "run_enabled")
    assert run_gate["severity"] == "capability"
    assert run_gate["blocks_start"] is False
    assert "Dry-run launch can start" in run_gate["message"]

    movement = route_readiness(
        tmp_path,
        get_selection(AGIBOT_SDK_MAP_BUILD),
        overrides={
            **agibot_overrides,
            "port": _free_port(),
            "real_movement_enabled": "true",
        },
        gates={"localization_ready": True, "run_enabled": False, "estop_ready": True},
        env=KIMI_ENV,
    )
    assert movement["can_start"] is False
    assert movement["blocker_kind"] == "needs_real_movement_gate"
    assert "Real movement is enabled" in movement["blocker"]


def test_optional_world_readiness_never_returns_private_dependency_roots(tmp_path: Path) -> None:
    private_root = tmp_path / "private-optional-world-canary"
    readiness = route_readiness(
        tmp_path,
        get_selection(B1_OPENAI_AGENTS_OPEN_TASK),
        overrides={
            "port": _free_port(),
            "map_bundle": str(private_root / "missing-map"),
            "isaac_scene_usd_path": str(private_root / "missing-scene.usd"),
        },
        env=KIMI_ENV,
    )

    serialized = json.dumps(readiness, sort_keys=True)
    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "optional_world_dependency"
    assert readiness["optional_world_dependencies"]["invalid"] == [
        "map_bundle",
        "isaac_scene_usd_path",
    ]
    assert str(private_root) not in serialized


def test_readiness_exposes_attachable_run_for_held_backend_lock(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "existing-run"
    pid = os.getpid()
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "pid": pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=pid)

    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=KIMI_ENV)

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "locked"
    assert "Attach to the existing run" in readiness["blocker"]
    assert readiness["attachable_run"] == {
        "run_id": run_id,
        "selection_id": route.id,
        "route_label": route.label,
        "phase": "running",
        "run_dir": str(run_dir),
        "display_run_dir": str(run_dir.resolve()),
        "backend_lock": route.lock_name,
        "pid": pid,
        "started_at": "",
    }


def test_readiness_keeps_stale_wrapper_lock_attachable_when_child_live_run_is_active(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 99999999,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk", "started_at_epoch": 2.0}),
        encoding="utf-8",
    )
    (attempt_dir / "driver.log").write_text("running\n", encoding="utf-8")
    lock = ResourceLock(tmp_path, route.lock_name)
    lock.acquire(run_id=run_id, pid=99999999)

    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=KIMI_ENV)

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "locked"
    assert "Attach to the existing run" in readiness["blocker"]
    assert readiness["attachable_run"]["run_id"] == run_id
    assert readiness["attachable_run"]["phase"] == "running-sdk"
    assert readiness["attachable_run"]["display_run_dir"] == str(attempt_dir.resolve())


def test_readiness_releases_terminal_failed_lock_instead_of_attaching_dead_run(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "failed-wrapper-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0609_1025" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 123450,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps(
            {
                "phase": "failed",
                "exit_status": 1,
                "reason": "cleanup checker exited with status 1",
            }
        ),
        encoding="utf-8",
    )
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=123450)

    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=KIMI_ENV)

    assert readiness["can_start"] is True
    assert readiness["blocker_kind"] == ""
    assert readiness["attachable_run"] is None
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_readiness_blocks_on_malformed_lock_owner_state_source(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "corrupt-wrapper-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text("{bad-state", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=KIMI_ENV)

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "source_error"
    assert "Backend lock owner source error" in readiness["blocker"]
    assert "operator_state.json contains invalid JSON" in readiness["blocker"]
    assert readiness["attachable_run"] is None
    assert ResourceLock(tmp_path, route.lock_name).read().held is True


def test_readiness_blocks_on_malformed_lock_owner_live_status_source(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "corrupt-live-status-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0619_1900" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 99999999,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text("[1]", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=KIMI_ENV)

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "source_error"
    assert "live_status.json must contain a JSON object" in readiness["blocker"]
    assert readiness["attachable_run"] is None
    assert ResourceLock(tmp_path, route.lock_name).read().held is True


def test_stop_console_run_rejects_malformed_operator_state_source(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "corrupt-stop-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    run_dir.mkdir(parents=True)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("{bad-state", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with pytest.raises(ConsoleLaunchError, match="operator stop source error") as exc_info:
        stop_console_run(tmp_path, run_id)

    assert "operator_state.json" in str(exc_info.value)
    assert "contains invalid JSON" in str(exc_info.value)
    assert state_path.read_text(encoding="utf-8") == "{bad-state"
    assert ResourceLock(tmp_path, route.lock_name).read().held is True


@pytest.mark.parametrize(
    ("source_text", "expected_reason"),
    [
        ("{bad-live-status", "contains invalid JSON"),
        ("[]\n", "must contain a JSON object"),
    ],
)
def test_stop_console_run_rejects_bad_live_status_source_before_stop(
    tmp_path: Path,
    source_text: str,
    expected_reason: str,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "corrupt-live-status-stop-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0619_1030" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": 123450,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    status_path = attempt_dir / "live_status.json"
    status_path.write_text(source_text, encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=123450)

    with (
        patch("roboclaws.operator_console.launcher._stop_live_child_run") as stop_child,
        patch("roboclaws.operator_console.launcher._terminate_process_group") as stop_wrapper,
        pytest.raises(ConsoleLaunchError, match="operator stop source error") as exc_info,
    ):
        stop_console_run(tmp_path, run_id)

    assert "live_status.json" in str(exc_info.value)
    assert expected_reason in str(exc_info.value)
    assert status_path.read_text(encoding="utf-8") == source_text
    stop_child.assert_not_called()
    stop_wrapper.assert_not_called()
    assert ResourceLock(tmp_path, route.lock_name).read().held is True


def test_provider_gate_blocks_raw_fpv_when_route_image_transport_unknown(tmp_path: Path) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::open-task::openai-agents-sdk::camera-raw-fpv"
    )

    readiness = route_readiness(
        tmp_path,
        route,
        env={"MM_BASE_URL": "https://minimax.example.test/v1", "MM_API_KEY": "key"},
        overrides={"port": _free_port(), "provider_profile": "minimax-responses"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
    )

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "unavailable"
    assert "verified image transport" in readiness["blocker"]


def test_provider_gate_blocks_when_evidence_lane_provider_lookup_fails(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    with patch(
        "roboclaws.operator_console.launcher.evidence_lane_compatibility",
        side_effect=KeyError("missing-provider"),
    ):
        readiness = route_readiness(
            tmp_path,
            route,
            env={"KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1", "KIMI_API_KEY": "key"},
            overrides={"port": _free_port()},
        )

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "needs_provider"
    assert readiness["provider"]["ok"] is False
    assert "provider/evidence-lane compatibility lookup failed" in readiness["blocker"]
    assert "missing-provider" in readiness["blocker"]


def test_provider_gate_blocks_unknown_openai_agents_model_env(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    readiness = route_readiness(
        tmp_path,
        route,
        env={
            "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
            "KIMI_API_KEY": "key",
            "ROBOCLAWS_OPENAI_AGENTS_MODEL": "not-in-provider-catalog",
        },
        overrides={"port": _free_port()},
    )

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "needs_provider"
    assert readiness["provider"]["ok"] is False
    assert "OpenAI Agents SDK setting model is unknown" in readiness["blocker"]
    assert "not-in-provider-catalog" in readiness["blocker"]


def test_provider_gate_blocks_incompatible_openai_agents_model_env(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)

    readiness = route_readiness(
        tmp_path,
        route,
        env={
            "MM_BASE_URL": "https://minimax.example.test/v1",
            "MM_API_KEY": "key",
            "ROBOCLAWS_OPENAI_AGENTS_MODEL": "kimi-k2.7-code",
        },
        overrides={"port": _free_port(), "provider_profile": "minimax-responses"},
        env_overrides={"ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses"},
    )

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "needs_provider"
    assert readiness["provider"]["ok"] is False
    assert "OpenAI Agents SDK setting model is incompatible" in readiness["blocker"]
    assert "provider_profile 'minimax-responses'" in readiness["blocker"]
