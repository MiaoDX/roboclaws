from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console import workflows as console_workflows
from roboclaws.operator_console.launcher import (
    ConsoleLaunchError,
    LaunchRequest,
    _new_run_id,
    _safe_run_id_suffix,
    _terminate_process_group,
    build_launch_argv,
    build_workflow_launch_argv,
    load_repo_dotenv,
    route_readiness,
    start_console_run,
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
from tests.unit.operator_console.test_routes import _write_prior_catalog

KIMI_ENV = {
    "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
    "KIMI_API_KEY": "key",
}


def test_new_console_run_id_is_filesystem_and_docker_mount_safe() -> None:
    run_id = _new_run_id(get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK))

    assert "/" not in run_id
    assert ":" not in run_id
    assert "::" not in run_id
    assert run_id.endswith(
        "-molmospaces-procthor-objaverse-val-0-mujoco-open-task-openai-agents-sdk"
        "-world-public-labels"
    )


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


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


def test_launcher_builds_route_specific_overrides(tmp_path: Path) -> None:
    route = get_selection(AGIBOT_SDK_MAP_BUILD)
    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={
            "context_json": str(tmp_path / "context.json"),
            "real_movement_enabled": "true",
        },
    )
    assert f"output_dir={tmp_path / 'output' / 'operator-console' / 'runs' / 'run-1'}" in argv
    assert f"context_json={tmp_path / 'context.json'}" in argv
    assert "real_movement_enabled=true" in argv


def test_b1_camera_grounded_launch_includes_default_camera_labeler(tmp_path: Path) -> None:
    route = get_selection(B1_OPENAI_AGENTS_CAMERA_GROUNDED)

    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={
            "b1_alignment_artifact": "alignment.json",
            "b1_navigation_artifact": "navigation.json",
        },
    )

    assert "world=b1-map12" in argv
    assert "backend=isaaclab" in argv
    assert "evidence_lane=camera-grounded-labels" in argv
    assert "camera_labeler=grounding-dino" in argv
    assert "b1_alignment_artifact=alignment.json" in argv
    assert "b1_navigation_artifact=navigation.json" in argv


def test_cleanup_workflow_launch_argv_uses_camera_grounded_and_standard_mess_defaults(
    tmp_path: Path,
) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::"
        "camera-grounded-labels"
    )

    argv = build_workflow_launch_argv(
        route,
        workflow_id="cleanup",
        root=tmp_path,
        run_id="run-1",
    )

    assert "preset=cleanup" in argv
    assert "evidence_lane=camera-grounded-labels" in argv
    assert "camera_labeler=grounding-dino" in argv
    assert "scenario_setup=relocate-cleanup-related-objects" in argv
    assert "relocation_count=5" in argv
    assert "provider_profile=kimi-openai-chat" in argv
    assert not any(item.startswith("agent_sdk_perf_profile=") for item in argv)
    assert "--agent-sdk-perf-profile" not in argv
    assert "ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE=baseline" not in argv


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


def test_workflow_launch_allows_empty_catalog_and_accepts_explicit_runtime_prior(
    tmp_path: Path,
) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::"
        "camera-grounded-labels"
    )

    argv_without_prior = build_workflow_launch_argv(
        route,
        workflow_id="cleanup",
        root=tmp_path,
        run_id="run-1",
    )

    assert not any(item.startswith("runtime_map_prior=") for item in argv_without_prior)

    prior = tmp_path / "runtime_map_prior_snapshot.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    argv = build_workflow_launch_argv(
        route,
        workflow_id="cleanup",
        root=tmp_path,
        run_id="run-2",
        overrides={"runtime_map_prior": str(prior)},
    )

    assert f"runtime_map_prior={prior}" in argv
    assert "scenario_setup=relocate-cleanup-related-objects" in argv


def test_workflow_launch_uses_accepted_catalog_prior_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::"
        "camera-grounded-labels"
    )
    prior = tmp_path / "runtime_map_prior_snapshot.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    catalog = tmp_path / "recommended_runtime_map_priors.json"
    _write_prior_catalog(catalog, prior)
    monkeypatch.setattr(console_workflows, "RECOMMENDED_PRIOR_CATALOG_PATH", catalog)

    argv = build_workflow_launch_argv(
        route,
        workflow_id="cleanup",
        root=tmp_path,
        run_id="run-1",
    )

    assert f"runtime_map_prior={prior}" in argv
    assert "scenario_setup=relocate-cleanup-related-objects" in argv


def test_workflow_launch_explicit_prior_override_wins_over_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::"
        "camera-grounded-labels"
    )
    catalog_prior = tmp_path / "catalog_prior.json"
    catalog_prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    override_prior = tmp_path / "override_prior.json"
    override_prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    catalog = tmp_path / "recommended_runtime_map_priors.json"
    _write_prior_catalog(catalog, catalog_prior)
    monkeypatch.setattr(console_workflows, "RECOMMENDED_PRIOR_CATALOG_PATH", catalog)

    argv = build_workflow_launch_argv(
        route,
        workflow_id="cleanup",
        root=tmp_path,
        run_id="run-1",
        overrides={"runtime_map_prior": str(override_prior)},
    )

    assert f"runtime_map_prior={override_prior}" in argv
    assert f"runtime_map_prior={catalog_prior}" not in argv


def test_workflow_launch_rejects_nonexistent_runtime_prior_override(tmp_path: Path) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::"
        "camera-grounded-labels"
    )

    with pytest.raises(ConsoleLaunchError, match="runtime_map_prior path does not exist"):
        build_workflow_launch_argv(
            route,
            workflow_id="cleanup",
            root=tmp_path,
            run_id="run-1",
            overrides={"runtime_map_prior": str(tmp_path / "missing.json")},
        )


def test_launcher_replaces_route_default_overrides(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={
            "seed": "9",
            "scenario_setup": "relocate-cleanup-related-objects",
            "relocation_count": "2",
        },
    )

    assert "seed=7" not in argv
    assert "relocation_count=5" not in argv
    assert "seed=9" in argv
    assert "scenario_setup=relocate-cleanup-related-objects" in argv
    assert "relocation_count=2" in argv
    assert not any(item.startswith("generated_mess_count=") for item in argv)


def test_launcher_rejects_loose_object_relocation_override(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_CLEANUP)

    with pytest.raises(ConsoleLaunchError, match="unsupported scenario_setup"):
        build_launch_argv(
            route,
            root=tmp_path,
            run_id="run-1",
            overrides={"scenario_setup": "relocate-loose-objects"},
        )


def test_launcher_rejects_old_public_generated_mess_override(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_CLEANUP)

    with pytest.raises(ConsoleLaunchError, match="generated_mess_count is no longer"):
        build_launch_argv(
            route,
            root=tmp_path,
            run_id="run-1",
            overrides={"generated_mess_count": "2"},
        )


def test_launcher_drops_relocation_count_for_baseline_setup(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_CLEANUP)
    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={
            "scenario_setup": "baseline",
            "relocation_count": "2",
        },
    )

    assert "scenario_setup=baseline" in argv
    assert not any(item.startswith("relocation_count=") for item in argv)
    assert not any(item.startswith("generated_mess_count=") for item in argv)


def test_launcher_passes_operator_message_path_for_steer_routes(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    path = tmp_path / "operator_messages.jsonl"

    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={"operator_messages_path": str(path)},
    )

    assert f"operator_messages_path={path}" in argv


def test_launcher_passes_operator_resume_request_path_for_resumable_routes(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    path = tmp_path / "operator_resume_requests.jsonl"

    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        overrides={"operator_resume_requests_path": str(path)},
    )

    assert f"operator_resume_requests_path={path}" in argv


def test_launcher_holds_lock_before_spawning_process(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    seen_lock_owner = ""
    seen_env: dict[str, str] = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args
        state = ResourceLock(tmp_path, route.lock_name).read()
        nonlocal seen_lock_owner
        seen_lock_owner = state.owner_run_id
        seen_env.update(kwargs["env"])
        return FakeProcess()

    with patch("roboclaws.operator_console.launcher.subprocess.Popen", side_effect=fake_popen):
        state = start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                intent_id="open-ended",
                prompt="收拾桌面上的杯子",
                next_goal_packet={"schema": "operator_console_next_goal_packet_v1"},
                provider_profile="minimax-responses",
                env_overrides={
                    "ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses",
                },
                overrides={"port": _free_port()},
            ),
            env={"MM_BASE_URL": "https://minimax.example/v1", "MM_API_KEY": "key"},
        )

    assert seen_lock_owner == state["run_id"]
    assert seen_env["ROBOCLAWS_PROVIDER_PROFILE"] == "minimax-responses"
    assert state["env_overrides"] == {
        "ROBOCLAWS_PROVIDER_PROFILE": "minimax-responses",
    }
    assert state["selected_intent"] == "open-ended"
    assert state["next_goal_packet"] == {"schema": "operator_console_next_goal_packet_v1"}
    assert state["prompt_preview"]["operator_prompt"] == "收拾桌面上的杯子"
    assert state["prompt_preview"]["source"] == "household-world"
    assert (
        "This run is surface=household-world intent=open-ended"
        in (state["prompt_preview"]["agent_kickoff_prompt"])
    )
    assert "收拾桌面上的杯子" in state["agent_kickoff_prompt"]
    assert "continuation_packet" not in state
    assert not any(item.startswith("intent=") for item in state["argv"])
    assert not any(item.startswith("preset=") for item in state["argv"])
    assert "prompt=收拾桌面上的杯子" in state["argv"]
    assert state["operator_session_id"].startswith("session-")
    assert any(item.startswith("operator_messages_path=") for item in state["argv"])
    assert not (console_output_root(tmp_path) / "runs.jsonl").exists()
    lock = ResourceLock(tmp_path, route.lock_name).read()
    assert lock.pid == 12345
    state_path = console_output_root(tmp_path) / "runs" / state["run_id"] / "operator_state.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["lock"]["owner_run_id"] == state["run_id"]


def test_launcher_uses_new_run_id_when_existing_run_dir_would_be_reused(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    base_run_id = f"20260620-101112-{_safe_run_id_suffix(route.id)}"
    existing_run_dir = console_output_root(tmp_path) / "runs" / base_run_id
    existing_run_dir.mkdir(parents=True)
    existing_state_path = existing_run_dir / "operator_state.json"
    existing_state_path.write_text("{corrupt-existing-state", encoding="utf-8")

    class FakeProcess:
        pid = 12345

    with (
        patch("roboclaws.operator_console.launcher.time.strftime") as strftime_mock,
        patch("roboclaws.operator_console.launcher.subprocess.Popen", return_value=FakeProcess()),
    ):
        strftime_mock.side_effect = lambda fmt, *args: (
            "20260620-101112" if fmt == "%Y%m%d-%H%M%S" else "2026-06-20T10:11:12Z"
        )
        state = start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                intent_id="open-ended",
                overrides={"port": _free_port()},
            ),
            env=KIMI_ENV,
        )

    assert state["run_id"] == f"{base_run_id}-2"
    assert existing_state_path.read_text(encoding="utf-8") == "{corrupt-existing-state"
    state_path = console_output_root(tmp_path) / "runs" / state["run_id"] / "operator_state.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["run_id"] == state["run_id"]
    assert ResourceLock(tmp_path, route.lock_name).read().owner_run_id == state["run_id"]


def test_launcher_fails_when_run_id_reservation_is_exhausted(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    base_run_id = f"20260620-101112-{_safe_run_id_suffix(route.id)}"
    runs_dir = console_output_root(tmp_path) / "runs"
    runs_dir.mkdir(parents=True)
    for suffix in ("", *(f"-{index}" for index in range(2, 100))):
        (runs_dir / f"{base_run_id}{suffix}").mkdir()

    with (
        patch("roboclaws.operator_console.launcher.time.strftime", return_value="20260620-101112"),
        patch("roboclaws.operator_console.launcher.subprocess.Popen") as popen,
        pytest.raises(
            ConsoleLaunchError, match="could not allocate unique operator-console run id"
        ),
    ):
        start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                intent_id="open-ended",
                overrides={"port": _free_port()},
            ),
            env=KIMI_ENV,
        )

    popen.assert_not_called()
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_launcher_removes_empty_reserved_run_dir_when_lock_acquire_fails(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = f"20260620-101112-{_safe_run_id_suffix(route.id)}"
    run_dir = console_output_root(tmp_path) / "runs" / run_id

    def fail_acquire(self, *, run_id, pid=None):  # noqa: ANN001, ANN202
        del self, run_id, pid
        raise RuntimeError("lock unavailable")

    with (
        patch("roboclaws.operator_console.launcher.time.strftime", return_value="20260620-101112"),
        patch("roboclaws.operator_console.launcher.ResourceLock.acquire", fail_acquire),
        patch("roboclaws.operator_console.launcher.subprocess.Popen") as popen,
        pytest.raises(RuntimeError, match="lock unavailable"),
    ):
        start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                intent_id="open-ended",
                overrides={"port": _free_port()},
            ),
            env=KIMI_ENV,
        )

    popen.assert_not_called()
    assert not run_dir.exists()


def test_launcher_removes_empty_reserved_run_dir_when_argv_build_fails(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = f"20260620-101112-{_safe_run_id_suffix(route.id)}"
    run_dir = console_output_root(tmp_path) / "runs" / run_id

    with (
        patch("roboclaws.operator_console.launcher.time.strftime", return_value="20260620-101112"),
        patch(
            "roboclaws.operator_console.launcher.build_launch_argv",
            side_effect=ConsoleLaunchError("bad argv"),
        ),
        patch("roboclaws.operator_console.launcher.subprocess.Popen") as popen,
        pytest.raises(ConsoleLaunchError, match="bad argv"),
    ):
        start_console_run(
            tmp_path,
            LaunchRequest(
                selection_id_override=route.id,
                intent_id="open-ended",
                overrides={"port": _free_port()},
            ),
            env=KIMI_ENV,
        )

    popen.assert_not_called()
    assert not run_dir.exists()


def test_launcher_rejects_missing_canonical_selection_identity(tmp_path: Path) -> None:
    with pytest.raises(ConsoleLaunchError, match="launch requires"):
        start_console_run(
            tmp_path,
            LaunchRequest(overrides={"port": _free_port()}),
            env=KIMI_ENV,
        )


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


def test_stop_console_run_targets_nested_live_attempt(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    wrapper_pid = 123450
    server_pid = 123451
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    attempt_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": wrapper_pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text(f"{server_pid}\n", encoding="utf-8")
    (attempt_dir / "tmux_session.txt").write_text("roboclaws-test\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=wrapper_pid)

    killed_pids: list[int] = []
    tmux_commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003, ANN202
        del kwargs
        tmux_commands.append(list(command))

        class Result:
            returncode = 0

        return Result()

    with (
        patch("roboclaws.operator_console.launcher._process_parent_pid") as parent_pid,
        patch("roboclaws.operator_console.launcher._descendant_pids") as descendant_pids,
        patch("roboclaws.operator_console.launcher.os.getpgid", side_effect=lambda pid: pid),
        patch("roboclaws.operator_console.launcher.os.killpg") as killpg,
        patch("roboclaws.operator_console.launcher.subprocess.run", side_effect=fake_run),
    ):
        parent_pid.return_value = wrapper_pid
        descendant_pids.return_value = [server_pid]
        killpg.side_effect = lambda pid, signal: killed_pids.append(pid)
        state = stop_console_run(tmp_path, run_id)

    assert state["phase"] == "stopped_by_operator"
    assert state["display_run_dir"] == str(attempt_dir.resolve())
    assert server_pid in killed_pids
    assert wrapper_pid in killed_pids
    assert ["tmux", "kill-session", "-t", "roboclaws-test"] in tmux_commands
    live_status = json.loads((attempt_dir / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["phase"] == "stopped_by_operator"
    assert live_status["exit_status"] == 130
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_stop_console_run_releases_failed_terminal_lock_without_relabeling_failure(
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

    with (
        patch("roboclaws.operator_console.launcher._stop_live_child_run") as stop_child,
        patch("roboclaws.operator_console.launcher._terminate_process_group") as stop_wrapper,
    ):
        state = stop_console_run(tmp_path, run_id)

    assert state["phase"] == "failed"
    assert state["terminal_reason"] == "cleanup checker exited with status 1"
    assert state["display_run_dir"] == str(attempt_dir.resolve())
    stop_child.assert_called_once_with(attempt_dir.resolve())
    stop_wrapper.assert_called_once_with(123450)
    assert ResourceLock(tmp_path, route.lock_name).read().held is False
    live_status = json.loads((attempt_dir / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["phase"] == "failed"
    assert live_status["exit_status"] == 1


def test_stop_console_run_stops_docker_container_bound_to_attempt_workspace(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    wrapper_pid = 123450
    server_pid = 123451
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    workspace = attempt_dir / "agent-docker-workspace"
    workspace.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": wrapper_pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    (attempt_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text(f"{server_pid}\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=wrapper_pid)

    docker_stops: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003, ANN202
        del kwargs

        class Result:
            returncode = 0
            stdout = ""

        result = Result()
        if command == ["docker", "ps", "-q"]:
            result.stdout = "container-a\ncontainer-b\n"
        elif command[:4] == ["docker", "inspect", "--format", "{{json .Mounts}}"]:
            container_id = command[4]
            source = workspace if container_id == "container-b" else tmp_path / "other"
            result.stdout = json.dumps([{"Source": str(source.resolve())}])
        elif command[:2] == ["docker", "stop"]:
            docker_stops.append(list(command))
        return result

    with (
        patch("roboclaws.operator_console.launcher._process_parent_pid", return_value=wrapper_pid),
        patch("roboclaws.operator_console.launcher._descendant_pids", return_value=[server_pid]),
        patch("roboclaws.operator_console.launcher.os.getpgid", side_effect=lambda pid: pid),
        patch("roboclaws.operator_console.launcher.os.killpg"),
        patch("roboclaws.operator_console.launcher.subprocess.run", side_effect=fake_run),
    ):
        stop_console_run(tmp_path, run_id)

    assert docker_stops == [["docker", "stop", "--time", "5", "container-b"]]


def test_stop_console_run_rejects_corrupt_docker_mount_source_before_state_rewrite(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "wrapper-run"
    wrapper_pid = 123450
    server_pid = 123451
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    attempt_dir = run_dir / "0608_1807" / "seed-7"
    workspace = attempt_dir / "agent-docker-workspace"
    workspace.mkdir(parents=True)
    state_path = run_dir / "operator_state.json"
    state_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "pid": wrapper_pid,
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )
    live_status_path = attempt_dir / "live_status.json"
    live_status_path.write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (attempt_dir / "server.pid").write_text(f"{server_pid}\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=wrapper_pid)

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003, ANN202
        del kwargs

        class Result:
            returncode = 0
            stdout = ""

        result = Result()
        if command == ["docker", "ps", "-q"]:
            result.stdout = "container-a\n"
        elif command[:4] == ["docker", "inspect", "--format", "{{json .Mounts}}"]:
            result.stdout = "{bad-mounts"
        return result

    with (
        patch("roboclaws.operator_console.launcher._process_parent_pid", return_value=wrapper_pid),
        patch("roboclaws.operator_console.launcher._descendant_pids", return_value=[server_pid]),
        patch("roboclaws.operator_console.launcher.os.getpgid", side_effect=lambda pid: pid),
        patch("roboclaws.operator_console.launcher.os.killpg"),
        patch("roboclaws.operator_console.launcher.subprocess.run", side_effect=fake_run),
        pytest.raises(ConsoleLaunchError, match="operator stop source error") as exc_info,
    ):
        stop_console_run(tmp_path, run_id)

    assert "docker inspect mounts for container-a contain invalid JSON" in str(exc_info.value)
    assert json.loads(state_path.read_text(encoding="utf-8"))["phase"] == "starting"
    assert json.loads(live_status_path.read_text(encoding="utf-8"))["phase"] == "running-sdk"
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


def test_terminate_process_group_falls_back_to_single_pid_when_group_lookup_fails() -> None:
    signals: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            raise ProcessLookupError
        signals.append((pid, sig))

    with (
        patch(
            "roboclaws.operator_console.launcher.os.getpgid",
            side_effect=ProcessLookupError,
        ),
        patch(
            "roboclaws.operator_console.launcher.os.killpg",
            side_effect=ProcessLookupError,
        ),
        patch("roboclaws.operator_console.launcher.os.kill", side_effect=fake_kill),
    ):
        _terminate_process_group(12345)

    assert signals == [(12345, 15)]


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
