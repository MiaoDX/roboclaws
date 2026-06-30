from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roboclaws.operator_console.launcher import route_readiness
from roboclaws.operator_console.paths import console_output_root
from roboclaws.operator_console.routes import get_selection
from roboclaws.operator_console.runtime_inventory import (
    runtime_blockers_payload,
    runtime_inventory_payload,
)

CODEX_ENV = {
    "CODEX_BASE_URL": "https://codex.example.test/v1",
    "CODEX_API_KEY": "key",
}
MUJOCO_OPENAI_AGENTS_OPEN_TASK = (
    "molmospaces/procthor-objaverse-val/0::mujoco::open-task::openai-agents-sdk::"
    "world-public-labels"
)


def test_runtime_inventory_lists_eval_harness_sdk_live_row(tmp_path: Path) -> None:
    row_dir = (
        tmp_path
        / "output"
        / "eval-harness"
        / "focused"
        / "rows"
        / "openai-agents-sdk-cleanup-camera-raw-fpv-live-product"
    )
    open_task_row_dir = (
        tmp_path
        / "output"
        / "eval-harness"
        / "focused"
        / "rows"
        / "openai-agents-sdk-open-task-live-eval"
    )
    run_dir = row_dir / "run" / "0615_1225" / "seed-7"
    run_dir.mkdir(parents=True)
    open_task_run_dir = open_task_row_dir / "run" / "0615_1226" / "seed-7"
    open_task_run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk", "started_at_epoch": 1.0}),
        encoding="utf-8",
    )
    (open_task_run_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk", "started_at_epoch": 1.0}),
        encoding="utf-8",
    )
    (run_dir / "tmux_session.txt").write_text(
        "roboclaws-molmo-openai-agents-sdk-0615_1225-run-p18788-seed-7\n",
        encoding="utf-8",
    )
    (run_dir / "visual_backend_slot.json").write_text(
        json.dumps(
            {
                "slot_id": 1,
                "path": str(tmp_path / "output" / "molmo" / "visual-backend-slots" / "slot-1.json"),
                "pid": os.getpid(),
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "driver.log").write_text(
        "Authorization: Bearer SECRET_TOKEN_VALUE\nCODEX_API_KEY=secret-key-value\n",
        encoding="utf-8",
    )
    manifest = {
        "rows": [
            {
                "row_id": "openai-agents-sdk-cleanup-camera-raw-fpv-live-product",
                "row_kind": "live_agent_eval",
                "row_dir": str(row_dir),
                "status": "ran",
                "outcome": "passed",
                "axes": {
                    "world": "molmospaces/val_0",
                    "backend": "mujoco",
                    "intent": "cleanup",
                    "preset": "cleanup",
                    "agent_engine": "openai-agents-sdk",
                    "evidence_lane": "camera-raw-fpv",
                },
            },
            {
                "row_id": "openai-agents-sdk-open-task-live-eval",
                "row_kind": "live_agent_eval",
                "row_dir": str(open_task_row_dir),
                "status": "ran",
                "outcome": "passed",
                "axes": {
                    "world": "molmospaces/val_0",
                    "backend": "mujoco",
                    "intent": "open-ended",
                    "agent_engine": "openai-agents-sdk",
                    "evidence_lane": "world-public-labels",
                },
            },
        ]
    }
    (tmp_path / "output" / "eval-harness" / "focused" / "eval_harness.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    payload = runtime_inventory_payload(tmp_path, ports=[18788])

    task = next(
        item
        for item in payload["tasks"]
        if item["id"] == "eval-row:openai-agents-sdk-cleanup-camera-raw-fpv-live-product"
    )
    assert task["owner"] == "eval-harness"
    assert task["status"] == "running"
    assert task["row_id"] == "openai-agents-sdk-cleanup-camera-raw-fpv-live-product"
    assert task["route_id"] == (
        "molmospaces/val_0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )
    open_task = next(
        item
        for item in payload["tasks"]
        if item["id"] == "eval-row:openai-agents-sdk-open-task-live-eval"
    )
    assert open_task["route_id"] == (
        "molmospaces/val_0::mujoco::open-task::openai-agents-sdk::world-public-labels"
    )
    assert any(resource["kind"] == "tmux_session" for resource in task["resources"])
    assert any(resource["kind"] == "visual_slot" for resource in task["resources"])
    assert not any(action["label"] == "Attach" for action in task["actions"])
    assert not any(action["type"] == "api_post" for action in task["actions"])
    artifacts = {item["label"]: item for item in task["artifacts"]}
    assert artifacts["Driver log"]["path"] == str(run_dir / "driver.log")
    assert artifacts["Driver log"]["href"] == ""
    assert artifacts["Eval harness manifest"]["href"] == ""
    assert not any(action["label"] == "Open Log" for action in task["actions"])
    assert "SECRET_TOKEN_VALUE" not in json.dumps(task)
    assert "secret-key-value" not in json.dumps(task)


def test_runtime_inventory_surfaces_invalid_operator_state_json(tmp_path: Path) -> None:
    state_path = console_output_root(tmp_path) / "runs" / "bad-run" / "operator_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{", encoding="utf-8")

    payload = runtime_inventory_payload(tmp_path)
    blockers = runtime_blockers_payload(tmp_path)

    task = next(item for item in payload["tasks"] if item["owner"] == "operator-console")
    assert task["id"] == (
        "source-error:operator-console:output/operator-console/runs/bad-run/operator_state.json"
    )
    assert task["status"] == "source_error"
    assert task["error_reason"] == "invalid_json"
    assert "operator_state.json is not readable JSON" in task["message"]
    assert task["resources"] == [
        {
            "kind": "source_error",
            "label": task["message"],
            "path": str(state_path),
            "active": False,
            "error_reason": "invalid_json",
        }
    ]
    assert task["artifacts"][0]["href"].endswith(
        "/output/operator-console/runs/bad-run/operator_state.json"
    )
    assert payload["summary"]["by_status"]["source_error"] == 1
    assert payload["summary"]["active"] == 0
    assert [item["id"] for item in blockers["tasks"]] == [task["id"]]
    assert blockers["summary"]["active"] == 0


def test_runtime_inventory_surfaces_invalid_eval_harness_manifest_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "output" / "eval-harness" / "focused" / "eval_harness.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("[1]", encoding="utf-8")

    payload = runtime_inventory_payload(tmp_path)
    blockers = runtime_blockers_payload(tmp_path)

    task = next(item for item in payload["tasks"] if item["owner"] == "eval-harness")
    assert task["id"] == "source-error:eval-harness:output/eval-harness/focused/eval_harness.json"
    assert task["status"] == "source_error"
    assert task["error_reason"] == "invalid_json_object"
    assert task["message"] == "eval_harness.json must contain a JSON object"
    assert task["resources"][0]["kind"] == "source_error"
    assert task["resources"][0]["active"] is False
    assert payload["summary"]["active"] == 0
    assert [item["id"] for item in blockers["tasks"]] == [task["id"]]
    assert blockers["summary"]["active"] == 0


def test_runtime_inventory_surfaces_invalid_visual_backend_slot_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", "0")

    payload = runtime_inventory_payload(tmp_path)
    blockers = runtime_blockers_payload(tmp_path)

    task = next(item for item in payload["tasks"] if item["owner"] == "molmo-live")
    assert task["id"] == "source-error:molmo-live:visual-backend-slot-config"
    assert task["status"] == "source_error"
    assert task["error_reason"] == "invalid_config"
    assert "ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS must be a positive integer" in task["message"]
    assert task["resources"] == [
        {
            "kind": "source_error",
            "label": task["message"],
            "path": str(tmp_path / "output" / "molmo" / "visual-backend-slots"),
            "active": False,
            "error_reason": "invalid_config",
        }
    ]
    assert [item["id"] for item in blockers["tasks"]] == [task["id"]]
    assert blockers["summary"]["active"] == 0


def test_runtime_inventory_surfaces_corrupt_docker_mount_metadata(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='roboclaws-test'\n", encoding="utf-8")
    (tmp_path / "roboclaws").mkdir()

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:  # noqa: ANN003
        del kwargs
        if command[:3] == ["docker", "ps", "--format"]:
            return SimpleNamespace(
                returncode=0,
                stdout="container-a\tworker-a\troboclaws-worker\tUp 1 minute\n",
            )
        if command[:4] == ["docker", "inspect", "--format", "{{json .Mounts}}"]:
            return SimpleNamespace(returncode=0, stdout="{bad-mounts")
        return SimpleNamespace(returncode=1, stdout="")

    with patch("roboclaws.operator_console.runtime_inventory.subprocess.run", side_effect=fake_run):
        payload = runtime_inventory_payload(tmp_path, ports=[])
        blockers = runtime_blockers_payload(tmp_path, ports=[])

    task = next(item for item in payload["tasks"] if item["owner"] == "docker")
    assert task["id"] == "source-error:docker:container-a:mounts"
    assert task["status"] == "source_error"
    assert task["error_reason"] == "invalid_docker_mounts"
    assert "docker inspect mounts for container-a are unreadable: invalid_json" in task["message"]
    assert task["resources"][0]["kind"] == "source_error"
    assert task["resources"][0]["active"] is False
    assert task["resources"][0]["container_id"] == "container-a"
    assert [item["id"] for item in blockers["tasks"]] == [task["id"]]


def test_runtime_inventory_lists_repo_mounted_docker_container(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='roboclaws-test'\n", encoding="utf-8")
    (tmp_path / "roboclaws").mkdir()

    def fake_run(command: list[str], **kwargs) -> SimpleNamespace:  # noqa: ANN003
        del kwargs
        if command[:3] == ["docker", "ps", "--format"]:
            return SimpleNamespace(
                returncode=0,
                stdout="container-a\tworker-a\troboclaws-worker\tUp 1 minute\n",
            )
        if command[:4] == ["docker", "inspect", "--format", "{{json .Mounts}}"]:
            mounts = [{"Source": str((tmp_path / "output" / "run").resolve())}]
            return SimpleNamespace(returncode=0, stdout=json.dumps(mounts))
        return SimpleNamespace(returncode=1, stdout="")

    with patch("roboclaws.operator_console.runtime_inventory.subprocess.run", side_effect=fake_run):
        payload = runtime_inventory_payload(tmp_path)

    task = next(item for item in payload["tasks"] if item["owner"] == "docker")
    assert task["id"] == "docker:container-a"
    assert task["status"] == "running"
    assert task["resources"][0]["kind"] == "docker_container"
    assert task["resources"][0]["container_id"] == "container-a"


def test_runtime_blockers_payload_omits_terminal_history(tmp_path: Path) -> None:
    active_row_dir = tmp_path / "output" / "eval-harness" / "focused" / "rows" / "active-live"
    active_run_dir = active_row_dir / "run" / "0615_1225" / "seed-7"
    active_run_dir.mkdir(parents=True)
    (active_run_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (active_run_dir / "visual_backend_slot.json").write_text(
        json.dumps({"slot_id": 1, "pid": os.getpid()}),
        encoding="utf-8",
    )

    terminal_row_dir = tmp_path / "output" / "eval-harness" / "focused" / "rows" / "terminal-live"
    terminal_run_dir = terminal_row_dir / "run" / "0615_1226" / "seed-7"
    terminal_run_dir.mkdir(parents=True)
    (terminal_run_dir / "live_status.json").write_text(
        json.dumps({"phase": "finished"}),
        encoding="utf-8",
    )
    (terminal_run_dir / "run_result.json").write_text(
        json.dumps({"status": "passed"}),
        encoding="utf-8",
    )

    (tmp_path / "output" / "eval-harness" / "focused" / "eval_harness.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "row_id": "active-live",
                        "row_kind": "live_agent_eval",
                        "row_dir": str(active_row_dir),
                        "status": "ran",
                        "axes": {
                            "world": "molmospaces/val_0",
                            "backend": "mujoco",
                            "intent": "cleanup",
                            "preset": "cleanup",
                            "agent_engine": "openai-agents-sdk",
                            "evidence_lane": "world-public-labels",
                        },
                    },
                    {
                        "row_id": "terminal-live",
                        "row_kind": "live_agent_eval",
                        "row_dir": str(terminal_row_dir),
                        "status": "ran",
                        "outcome": "passed",
                        "axes": {
                            "world": "molmospaces/val_0",
                            "backend": "mujoco",
                            "intent": "cleanup",
                            "preset": "cleanup",
                            "agent_engine": "openai-agents-sdk",
                            "evidence_lane": "world-public-labels",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    inventory = runtime_inventory_payload(tmp_path, ports=[18788])
    blockers = runtime_blockers_payload(tmp_path, ports=[18788])

    assert {task["id"] for task in inventory["tasks"]} >= {
        "eval-row:active-live",
        "eval-row:terminal-live",
    }
    assert [task["id"] for task in blockers["tasks"]] == ["eval-row:active-live"]
    assert blockers["summary"]["active"] == 1
    assert blockers["summary"]["total"] == 1


def test_runtime_inventory_surfaces_invalid_nested_runtime_json_resources(
    tmp_path: Path,
) -> None:
    row_dir = tmp_path / "output" / "eval-harness" / "focused" / "rows" / "bad-nested-live"
    run_dir = row_dir / "run" / "0615_1225" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text("{", encoding="utf-8")
    (run_dir / "visual_backend_slot.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "output" / "eval-harness" / "focused" / "eval_harness.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "row_id": "bad-nested-live",
                        "row_kind": "live_agent_eval",
                        "row_dir": str(row_dir),
                        "status": "ran",
                        "axes": {
                            "world": "molmospaces/val_0",
                            "backend": "mujoco",
                            "intent": "cleanup",
                            "preset": "cleanup",
                            "agent_engine": "openai-agents-sdk",
                            "evidence_lane": "world-public-labels",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = runtime_inventory_payload(tmp_path)
    blockers = runtime_blockers_payload(tmp_path)

    task = next(item for item in payload["tasks"] if item["id"] == "eval-row:bad-nested-live")
    source_resources = [
        resource for resource in task["resources"] if resource["kind"] == "source_error"
    ]
    assert task["owner"] == "eval-harness"
    assert task["status"] == "stale"
    assert [resource["error_reason"] for resource in source_resources] == [
        "invalid_json_object",
        "invalid_json",
    ]
    assert all(resource["active"] is False for resource in source_resources)
    assert "visual_backend_slot.json must contain a JSON object" in {
        resource["label"] for resource in source_resources
    }
    assert any(
        "live_status.json is not readable JSON" in resource["label"]
        for resource in source_resources
    )
    assert [item["id"] for item in blockers["tasks"]] == ["eval-row:bad-nested-live"]
    assert blockers["summary"]["active"] == 0


def test_runtime_inventory_marks_dead_eval_harness_live_row_stale(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    row_dir = tmp_path / "output" / "eval-harness" / "focused" / "rows" / "codex-cleanup-live"
    run_dir = row_dir / "run" / "0615_1225" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (run_dir / "tmux_session.txt").write_text(
        "roboclaws-molmo-openai-agents-sdk-dead\n",
        encoding="utf-8",
    )
    (run_dir / "server.pid").write_text("99999999\n", encoding="utf-8")
    (run_dir / "visual_backend_slot.json").write_text(
        json.dumps({"slot_id": 1, "pid": 99999999, "port": free_tcp_port}),
        encoding="utf-8",
    )
    (tmp_path / "output" / "eval-harness" / "focused" / "eval_harness.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "row_id": "codex-cleanup-live",
                        "row_kind": "live_agent_eval",
                        "row_dir": str(row_dir),
                        "status": "ran",
                        "axes": {
                            "world": "molmospaces/val_0",
                            "backend": "mujoco",
                            "intent": "cleanup",
                            "preset": "cleanup",
                            "agent_engine": "openai-agents-sdk",
                            "evidence_lane": "world-public-labels",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = runtime_inventory_payload(tmp_path, ports=[free_tcp_port])

    task = next(item for item in payload["tasks"] if item["id"] == "eval-row:codex-cleanup-live")
    assert task["status"] == "stale"
    assert payload["summary"]["active"] == 0
    assert all(resource.get("active") is False for resource in task["resources"])
    assert not any(
        action["label"] in {"Attach", "Copy Stop Command"} for action in task.get("actions", [])
    )


def test_runtime_inventory_exposes_direct_stop_only_for_operator_runs(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "operator-run"
    run_dir = console_output_root(tmp_path) / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "pid": os.getpid(),
                "backend_lock": route.lock_name,
                "run_dir": str(run_dir),
            }
        ),
        encoding="utf-8",
    )

    payload = runtime_inventory_payload(tmp_path)

    task = next(item for item in payload["tasks"] if item["id"] == f"operator-run:{run_id}")
    assert task["owner"] == "operator-console"
    artifacts = {item["label"]: item for item in task["artifacts"]}
    assert artifacts["Operator state"]["href"].startswith("/artifacts/output/operator-console/")
    assert any(
        action["type"] == "api_post" and action["label"] == "Stop" for action in task["actions"]
    )


def test_readiness_names_background_eval_owner_before_start(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    row_dir = tmp_path / "output" / "eval-harness" / "focused" / "rows" / "codex-cleanup-live"
    run_dir = row_dir / "run" / "0615_1225" / "seed-7"
    run_dir.mkdir(parents=True)
    (run_dir / "live_status.json").write_text(
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    (run_dir / "visual_backend_slot.json").write_text(
        json.dumps({"slot_id": 1, "pid": os.getpid()}),
        encoding="utf-8",
    )
    (tmp_path / "output" / "eval-harness" / "focused" / "eval_harness.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "row_id": "codex-cleanup-live",
                        "row_kind": "live_agent_eval",
                        "row_dir": str(row_dir),
                        "status": "ran",
                        "axes": {
                            "world": "molmospaces/val_0",
                            "backend": "mujoco",
                            "intent": "cleanup",
                            "preset": "cleanup",
                            "agent_engine": "openai-agents-sdk",
                            "evidence_lane": "world-public-labels",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": "18788"},
        env=CODEX_ENV,
    )

    assert readiness["can_start"] is False
    assert readiness["blocker_kind"] == "background_task"
    assert "Background task eval-row:codex-cleanup-live" in readiness["blocker"]
    assert readiness["background_blockers"][0]["owner"] == "eval-harness"
