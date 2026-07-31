from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console import workflows as console_workflows
from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.launch_lifecycle import _safe_run_id_suffix
from roboclaws.operator_console.launcher import (
    LaunchRequest,
    build_launch_argv,
    build_workflow_launch_argv,
    start_console_run,
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
from tests.unit.operator_console.test_routes import _write_prior_catalog


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

    with patch("roboclaws.operator_console.launcher.spawn_launch_plan", side_effect=fake_popen):
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
        patch("roboclaws.operator_console.launch_lifecycle.time.strftime") as strftime_mock,
        patch("roboclaws.operator_console.launcher.spawn_launch_plan", return_value=FakeProcess()),
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
        patch(
            "roboclaws.operator_console.launch_lifecycle.time.strftime",
            return_value="20260620-101112",
        ),
        patch("roboclaws.operator_console.launcher.spawn_launch_plan") as popen,
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
        patch(
            "roboclaws.operator_console.launch_lifecycle.time.strftime",
            return_value="20260620-101112",
        ),
        patch("roboclaws.operator_console.launcher.ResourceLock.acquire", fail_acquire),
        patch("roboclaws.operator_console.launcher.spawn_launch_plan") as popen,
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
        patch(
            "roboclaws.operator_console.launch_lifecycle.time.strftime",
            return_value="20260620-101112",
        ),
        patch(
            "roboclaws.operator_console.launcher.build_launch_argv",
            side_effect=ConsoleLaunchError("bad argv"),
        ),
        patch("roboclaws.operator_console.launcher.spawn_launch_plan") as popen,
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
