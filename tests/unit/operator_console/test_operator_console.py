from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launcher import (
    ConsoleLaunchError,
    build_launch_argv,
    route_readiness,
)
from roboclaws.operator_console.locks import ResourceLock, ResourceLockError
from roboclaws.operator_console.prompt_preview import (
    PromptPreviewRequest,
    build_prompt_preview,
)
from roboclaws.operator_console.redaction import redact_text
from roboclaws.operator_console.routes import (
    get_selection,
    list_console_combinations,
    validate_supported_routes_against_catalog,
)
from roboclaws.operator_console.server import (
    ConsoleRequestHandler,
    _registered_preview_asset_names,
)
from roboclaws.operator_console.server import (
    main as operator_console_main,
)
from roboclaws.operator_console.state import (
    derive_operator_state,
    redacted_artifact_text,
)
from tests.support.b1_robot_proof import write_b1_robot_proof_artifacts
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_CLEANUP,
    AGIBOT_SDK_MAP_BUILD,
    AGIBOT_SDK_OPEN_TASK,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_CLEANUP,
    B1_OPENAI_AGENTS_MAP_BUILD,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)

CODEX_ENV = {
    "CODEX_BASE_URL": "https://codex.example.test/v1",
    "CODEX_API_KEY": "key",
}


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def _just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local" / "bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def test_console_route_registry_exposes_agent_routes_and_explains_disabled_routes() -> None:
    routes = list_console_combinations()
    supported = [route for route in routes if route.enabled]
    disabled = {route.id: route.disabled_reason for route in routes if not route.enabled}

    assert {route.id for route in supported} >= {
        MUJOCO_OPENAI_AGENTS_OPEN_TASK,
        MUJOCO_OPENAI_AGENTS_OPEN_TASK,
        AGIBOT_SDK_MAP_BUILD,
        MUJOCO_SDK_MAP_BUILD,
        B1_OPENAI_AGENTS_MAP_BUILD,
        B1_OPENAI_AGENTS_OPEN_TASK,
        B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    }
    assert {route.agent_engine_id for route in supported} >= {
        "openai-agents-sdk",
        "openai-agents-sdk",
        "openai-agents-sdk",
    }
    assert {route.lock_name for route in supported} == {
        "molmospaces_mujoco",
        "isaac_gpu",
        "agibot_g2",
    }
    assert "Physical manipulation is not active" in disabled[AGIBOT_SDK_CLEANUP]
    assert "Physical open task is not product-proven yet" in disabled[AGIBOT_SDK_OPEN_TASK]
    assert "Digital-twin cleanup is not product-proven yet" in disabled[B1_OPENAI_AGENTS_CLEANUP]
    validate_supported_routes_against_catalog()


def test_console_routes_endpoint_exposes_workflows_and_prior_catalog(tmp_path: Path) -> None:
    with _console_server(tmp_path) as (host, port):
        with urllib.request.urlopen(f"http://{host}:{port}/api/routes") as response:
            payload = json.loads(response.read().decode("utf-8"))

    workflows = {workflow["id"]: workflow for workflow in payload["workflows"]}
    scene = next(
        world
        for world in payload["worlds"]
        if world["id"] == "molmospaces/procthor-objaverse-val/0"
    )
    scene_workflows = {workflow["id"]: workflow for workflow in scene["workflow_actions"]}

    assert payload["recommended_priors"] == []
    assert tuple(workflows) == ("build-map", "open-task", "cleanup")
    assert workflows["cleanup"]["allows_prior_override"] is True
    assert workflows["cleanup"]["requires_runtime_map_prior"] is False
    assert scene_workflows["open-task"]["default_route_id"].endswith("::camera-grounded-labels")
    assert scene_workflows["cleanup"]["enabled"] is True
    assert scene_workflows["cleanup"]["allows_prior_override"] is True


def test_console_route_payload_supports_backend_specific_ui_metadata() -> None:
    mujoco = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK).to_payload()
    b1 = get_selection(B1_OPENAI_AGENTS_OPEN_TASK).to_payload()
    agibot = get_selection(AGIBOT_SDK_MAP_BUILD).to_payload()

    assert mujoco["field_groups"] == ["common"]
    assert set(mujoco["view_modes"]) == {"overview", "fpv", "map", "grounding", "chase", "outputs"}
    assert "grounding" not in mujoco["backend_view_modes"]

    assert b1["field_groups"] == ["common"]
    assert "grounding" in b1["view_modes"]
    assert "grounding" in b1["backend_view_modes"]

    assert agibot["field_groups"] == ["common", "agibot", "agibot_gates"]
    assert "grounding" in agibot["view_modes"]
    assert "chase" not in agibot["backend_view_modes"]


def test_console_prompt_gating_and_argv_construction_are_fixed_argv(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_CLEANUP)
    argv = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1",
        prompt="pick up the mug; rm -rf /",
        overrides={
            "seed": "8",
            "scenario_setup": "relocate-cleanup-related-objects",
            "relocation_count": "2",
        },
    )

    assert argv[:7] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-objaverse-val/0",
        "backend=mujoco",
        "preset=cleanup",
        "agent_engine=openai-agents-sdk",
    ]
    assert "preset=cleanup" in argv
    assert "evidence_lane=world-public-labels" in argv
    assert "provider_profile=codex-router-responses" in argv
    assert "prompt=pick up the mug; rm -rf /" in argv
    assert "scenario_setup=relocate-cleanup-related-objects" in argv
    assert "relocation_count=2" in argv
    assert not any(item.startswith("generated_mess_count=") for item in argv)
    assert not any("OpenClaw" in item or "claude" in item for item in argv)

    open_ended = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1-open-ended",
        intent="open-ended",
        prompt="pick up the mug; rm -rf /",
    )
    assert not any(item.startswith("intent=") for item in open_ended)
    assert not any(item.startswith("preset=") for item in open_ended)
    assert "scenario_setup=baseline" in open_ended
    assert not any(item.startswith("relocation_count=") for item in open_ended)
    assert not any(item.startswith("generated_mess_count=") for item in open_ended)

    default_open_ended = build_launch_argv(
        route,
        root=tmp_path,
        run_id="run-1-open-ended-default",
        intent="open-ended",
    )
    assert not any(item.startswith("intent=") for item in default_open_ended)
    assert not any(item.startswith("preset=") for item in default_open_ended)
    assert "prompt=在这个场景中完成开放性导航任务，并报告你看到的证据。" in default_open_ended

    disabled = get_selection(AGIBOT_SDK_CLEANUP)
    with pytest.raises(ConsoleLaunchError, match="cannot accept a custom prompt"):
        build_launch_argv(disabled, root=tmp_path, run_id="run-2", prompt="custom")

    with pytest.raises(ConsoleLaunchError, match="unsupported route parameter"):
        build_launch_argv(route, root=tmp_path, run_id="run-3", overrides={"shell": "true"})


def test_operator_console_prompt_preview_endpoint_renders_agent_kickoff_prompt(
    tmp_path: Path,
) -> None:
    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/prompt-preview",
            method="POST",
            data=json.dumps(
                {
                    "world_id": "molmospaces/procthor-objaverse-val/0",
                    "backend_id": "mujoco",
                    "intent_id": "open-ended",
                    "agent_engine_id": "openai-agents-sdk",
                    "provider_profile": "codex-router-responses",
                    "evidence_lane": "world-public-labels",
                    "scenario_setup": "baseline",
                    "prompt": "只收拾桌面上的杯子",
                    "overrides": {},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["operator_prompt"] == "只收拾桌面上的杯子"
    assert payload["source"] == "household-world"
    assert payload["intent"] == "open-ended"
    assert "prompt_mode" not in payload
    assert (
        "This run is surface=household-world intent=open-ended" in payload["agent_kickoff_prompt"]
    )
    assert "只收拾桌面上的杯子" in payload["agent_kickoff_prompt"]
    assert "household-world skill instructions" in payload["agent_kickoff_prompt"]
    assert payload["wrapper_notes"] == []


@pytest.mark.parametrize(
    ("request_fields", "expected_error"),
    [
        (
            {
                "agent_engine_id": "openai-agents-sdk",
                "evidence_lane": "camera-raw-fpv",
                "overrides": {},
                "env_overrides": {"ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "many"},
            },
            "raw_fpv_candidate_budget must be an integer",
        ),
        (
            {
                "agent_engine_id": "openai-agents-sdk",
                "evidence_lane": "world-public-labels",
                "overrides": {"relocation_count": "abc"},
            },
            "relocation_count must be an integer",
        ),
    ],
)
def test_operator_console_prompt_preview_endpoint_rejects_invalid_numeric_inputs(
    tmp_path: Path,
    request_fields: dict[str, object],
    expected_error: str,
) -> None:
    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/prompt-preview",
            method="POST",
            data=json.dumps(
                {
                    "world_id": "molmospaces/procthor-objaverse-val/0",
                    "backend_id": "mujoco",
                    "intent_id": "cleanup",
                    "provider_profile": "codex-router-responses",
                    "scenario_setup": "relocate-cleanup-related-objects",
                    "prompt": "收拾杯子",
                    **request_fields,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 400
    assert expected_error in payload["error"]


@pytest.mark.parametrize(
    ("env_overrides", "expected_error"),
    [
        (
            {"ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "-1"},
            "max_observe_per_waypoint must be non-negative",
        ),
        (
            {"ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET": "-1"},
            "done_retry_budget must be non-negative",
        ),
    ],
)
def test_prompt_preview_rejects_invalid_openai_agents_numeric_env_values(
    env_overrides: dict[str, str],
    expected_error: str,
) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )

    with pytest.raises(ValueError, match=expected_error):
        build_prompt_preview(
            route,
            PromptPreviewRequest(
                prompt="收拾杯子",
                env_overrides=env_overrides,
            ),
        )


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"relocation_count": "abc"}, "relocation_count must be an integer"),
        ({"relocation_count": "-3"}, "relocation_count must be non-negative"),
    ],
)
def test_prompt_preview_rejects_invalid_relocation_count(
    overrides: dict[str, str],
    expected_error: str,
) -> None:
    route = get_selection(MUJOCO_SDK_CLEANUP)

    with pytest.raises(ValueError, match=expected_error):
        build_prompt_preview(
            route,
            PromptPreviewRequest(
                prompt="收拾杯子",
                overrides={
                    "scenario_setup": "relocate-cleanup-related-objects",
                    **overrides,
                },
            ),
        )


def test_prompt_preview_uses_valid_openai_agents_numeric_env_overrides() -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )

    payload = build_prompt_preview(
        route,
        PromptPreviewRequest(
            prompt="收拾杯子",
            overrides={"relocation_count": "4"},
            env_overrides={
                "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "3",
                "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "2",
                "ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET": "0",
            },
        ),
    )

    assert "run budget of 3 raw-FPV candidate attempts" in payload["agent_kickoff_prompt"]
    assert (
        "every waypoint must complete 2 materially distinct robot-body headings"
        in payload["agent_kickoff_prompt"]
    )
    assert "retry done at most 0 time(s)" in payload["agent_kickoff_prompt"]


def test_prompt_preview_keeps_existing_prompt_minimums_for_zero_budget_env() -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )

    payload = build_prompt_preview(
        route,
        PromptPreviewRequest(
            prompt="收拾杯子",
            env_overrides={
                "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "0",
                "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "0",
            },
        ),
    )

    assert "run budget of 1 raw-FPV candidate attempts" in payload["agent_kickoff_prompt"]
    assert (
        "every waypoint must complete 1 materially distinct robot-body headings"
        in payload["agent_kickoff_prompt"]
    )


def test_console_readiness_omits_isaac_marker_diagnostic_but_keeps_locks_blocking(
    tmp_path: Path,
) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    write_b1_robot_proof_artifacts(tmp_path)
    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=CODEX_ENV)
    assert readiness["can_start"] is True
    assert readiness["blocker_kind"] == ""
    assert {gate["id"] for gate in readiness["gates"]} == {
        "provider_key",
        "mcp_port_free",
    }

    lock = ResourceLock(tmp_path, route.lock_name)
    lock.acquire(run_id="active", pid=os.getpid())
    readiness = route_readiness(tmp_path, route, overrides={"port": _free_port()}, env=CODEX_ENV)
    assert readiness["can_start"] is False
    assert "Backend lock is held" in readiness["blocker"]


def test_console_readiness_uses_provider_profile_override(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port(), "provider_profile": "mimo-mify-responses"},
        env={"XM_LLM_API_KEY": "key"},
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "mimo-mify-responses"
    assert readiness["provider"]["model"] == "xiaomi/mimo-v2.5"


def test_console_readiness_uses_sdk_mify_provider_profile_override(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    readiness = route_readiness(
        tmp_path,
        route,
        overrides={"port": _free_port(), "provider_profile": "mimo-mify-responses"},
        env={"XM_LLM_API_KEY": "key"},
    )

    assert readiness["can_start"] is True
    assert readiness["provider"]["provider"] == "mimo-mify-responses"
    assert readiness["provider"]["model"] == "xiaomi/mimo-v2.5"


def test_resource_lock_prevents_conflicting_starts(tmp_path: Path) -> None:
    lock = ResourceLock(tmp_path, "molmospaces_mujoco")
    first = lock.acquire(run_id="run-a", pid=os.getpid())
    assert first.held is True
    assert first.owner_run_id == "run-a"

    with pytest.raises(ResourceLockError):
        lock.acquire(run_id="run-b", pid=os.getpid())

    lock.release(run_id="run-a")
    assert lock.read().held is False


def test_operator_state_derives_public_fields_and_artifact_links(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
                "started_at_epoch": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "tool_name": "navigate_to_object",
                "ok": True,
                "reasoning": "public reason",
                "observation_summary": "mug visible",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task": "household-cleanup",
                "backend": "molmospaces_subprocess",
                "cleanup_success": True,
                "private_manifest": {"must_not": "surface"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK))

    assert state["run_id"] == "run-a"
    assert state["latest_tool_call"]["name"] == "navigate_to_object"
    assert state["latest_public_decision_evidence"]["observation_summary"] == "mug visible"
    assert state["checker_status"]["status"] == "passed"
    assert "private_manifest" not in state["public_run_result"]
    assert any(item["label"] == "Report" for item in state["artifact_paths"])
    report_link = next(item for item in state["artifact_paths"] if item["label"] == "Report")
    assert report_link["href"].startswith("/artifacts/")
    assert "?v=" in report_link["href"]


def test_redaction_removes_secret_values_and_headers(tmp_path: Path) -> None:
    text = (
        "Authorization: Bearer live-token\n"
        "CODEX_API_KEY=secret-key\n"
        "api_key: secret-key\n"
        "base https://secret.example/v1"
    )
    redacted = redact_text(
        text,
        env={"CODEX_API_KEY": "secret-key", "CODEX_BASE_URL": "https://secret.example/v1"},
    )
    assert "secret-key" not in redacted
    assert "live-token" not in redacted
    assert "https://secret.example/v1" not in redacted

    artifact = tmp_path / "driver.log"
    artifact.write_text("Authorization: Bearer live-token\n", encoding="utf-8")
    assert "live-token" not in redacted_artifact_text(artifact)


def test_operator_console_serves_only_operator_output_artifacts(tmp_path: Path) -> None:
    output_artifact = (
        tmp_path / "output" / "operator-console" / "runs" / "run-a" / "console-launch.log"
    )
    output_artifact.parent.mkdir(parents=True)
    output_artifact.write_text("Authorization: Bearer live-token\nvisible tail\n", encoding="utf-8")
    repo_file = tmp_path / "README.md"
    repo_file.write_text("repo source should not be an artifact\n", encoding="utf-8")

    output_rel = output_artifact.relative_to(tmp_path).as_posix()
    repo_rel = repo_file.relative_to(tmp_path).as_posix()

    with _console_server(tmp_path) as (host, port):
        artifact_url = f"http://{host}:{port}/artifacts/{urllib.parse.quote(output_rel)}"
        with urllib.request.urlopen(artifact_url) as response:
            assert response.read().decode("utf-8") == output_artifact.read_text(encoding="utf-8")

        raw_url = f"http://{host}:{port}/api/raw/{urllib.parse.quote(output_rel)}"
        with urllib.request.urlopen(raw_url) as response:
            redacted = response.read().decode("utf-8")

        repo_url = f"http://{host}:{port}/artifacts/{urllib.parse.quote(repo_rel)}"
        with pytest.raises(urllib.error.HTTPError) as repo_error:
            urllib.request.urlopen(repo_url)
        raw_repo_url = f"http://{host}:{port}/api/raw/{urllib.parse.quote(repo_rel)}"
        with pytest.raises(urllib.error.HTTPError) as raw_repo_error:
            urllib.request.urlopen(raw_repo_url)

        escape_url = (
            f"http://{host}:{port}/artifacts/"
            f"{urllib.parse.quote('output/operator-console/../README.md')}"
        )
        with pytest.raises(urllib.error.HTTPError) as escape_error:
            urllib.request.urlopen(escape_url)
        raw_escape_url = (
            f"http://{host}:{port}/api/raw/"
            f"{urllib.parse.quote('output/operator-console/../README.md')}"
        )
        with pytest.raises(urllib.error.HTTPError) as raw_escape_error:
            urllib.request.urlopen(raw_escape_url)

    assert "live-token" not in redacted
    assert "visible tail" in redacted
    assert repo_error.value.code == 404
    assert raw_repo_error.value.code == 404
    assert escape_error.value.code == 404
    assert raw_escape_error.value.code == 404


def test_just_console_run_recipe_is_public_and_uses_public_bind_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    summary_result = subprocess.run(
        [_just_bin(), "--summary"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = set(summary_result.stdout.split())
    assert "console::run" in summary

    dry_run_result = subprocess.run(
        [_just_bin(), "--dry-run", "console::run"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    dry_run_output = dry_run_result.stdout + dry_run_result.stderr
    assert '-m roboclaws.operator_console --host "0.0.0.0" --port "8765"' in dry_run_output


def test_operator_console_cli_defaults_to_all_interfaces() -> None:
    with patch("roboclaws.operator_console.server.run_server") as run_server:
        assert operator_console_main([]) == 0

    assert run_server.call_args.args[1] == "0.0.0.0"
    assert run_server.call_args.args[2] == 8765


def test_operator_console_static_assets_are_not_cached(tmp_path: Path) -> None:
    with _console_server(tmp_path) as (host, port):
        with urllib.request.urlopen(f"http://{host}:{port}/styles.css") as response:
            assert response.headers["Cache-Control"] == "no-store, max-age=0"
            assert response.headers["Content-Type"] == "text/css; charset=utf-8"
        request = urllib.request.Request(f"http://{host}:{port}/styles.css", method="HEAD")
        with urllib.request.urlopen(request) as response:
            assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_operator_console_routes_endpoint_exposes_evidence_lane_matrix(tmp_path: Path) -> None:
    with _console_server(tmp_path) as (host, port):
        with urllib.request.urlopen(f"http://{host}:{port}/api/routes") as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert [lane["id"] for lane in payload["evidence_lanes"]] == [
        "world-public-labels",
        "camera-grounded-labels",
        "camera-raw-fpv",
    ]
    routes = {route["id"]: route for route in payload["combinations"]}
    worlds = {world["id"]: world for world in payload["worlds"]}
    world_id = "molmospaces/procthor-objaverse-val/10"
    route_id = f"{world_id}::mujoco::map-build::openai-agents-sdk::world-public-labels"
    assert world_id in worlds
    assert worlds[world_id]["preview_assets"]["map"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-map.png"
    )
    assert worlds[world_id]["preview_assets"]["topdown"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-topdown.png"
    )
    assert worlds[world_id]["preview_assets"]["chase"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-chase.png"
    )
    assert worlds["b1-map12"]["preview_assets"]["fpv"]["href"] == "/previews/b1-map12-fpv.png"
    assert worlds["b1-map12"]["preview_assets"]["map"]["href"] == "/previews/b1-map12-map.png"
    assert worlds["b1-map12"]["preview_assets"]["chase"]["href"] == ("/previews/b1-map12-chase.png")
    assert worlds["b1-map12"]["preview_assets"]["topdown"]["href"] == (
        "/previews/b1-map12-topdown.png"
    )
    assert (
        worlds[world_id]["preview_assets"]["topdown"]["href"]
        != (worlds[world_id]["preview_assets"]["map"]["href"])
    )
    assert routes[route_id]["preview_assets"]["fpv"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-fpv.png"
    )
    assert routes[route_id]["preview_assets"]["chase"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-chase.png"
    )
    assert routes[route_id]["preview_assets"]["topdown"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-topdown.png"
    )
    if "ai2thor/FloorPlan201" in worlds:
        assert "topdown" not in worlds["ai2thor/FloorPlan201"]["preview_assets"]
    assert routes[
        "molmospaces/procthor-objaverse-val/0::mujoco::map-build::openai-agents-sdk::camera-grounded-labels"
    ]["enabled"]
    assert routes[B1_OPENAI_AGENTS_CAMERA_GROUNDED]["enabled"]
    assert (
        "camera_labeler=grounding-dino" in routes[B1_OPENAI_AGENTS_CAMERA_GROUNDED]["argv_preview"]
    )
    assert not any(
        "::isaaclab::" in route_id for route_id in routes if route_id.startswith("molmospaces/")
    )


def test_operator_console_serves_scene_preview_assets(tmp_path: Path) -> None:
    registered_previews = _registered_preview_asset_names()
    _assert_registered_scene_preview_assets(registered_previews)

    with _console_server(tmp_path) as (host, port):
        base_url = f"http://{host}:{port}"
        _assert_scene_preview_png_assets(base_url)
        _assert_scene_preview_json_assets(base_url)
        _assert_scene_preview_rejects_invalid_paths(base_url)


def _assert_registered_scene_preview_assets(registered_previews: set[str]) -> None:
    assert "molmospaces-procthor-objaverse-val-10-map.png" in registered_previews
    assert "molmospaces-procthor-objaverse-val-10-preview.json" in registered_previews
    assert "molmospaces-procthor-10k-val-11-map.png" in registered_previews
    assert "molmospaces-procthor-10k-val-11-preview.json" in registered_previews
    assert "b1-map12-map.png" in registered_previews
    assert "b1-map12-topdown.png" in registered_previews
    assert "b1-map12-fpv.png" in registered_previews
    assert "b1-map12-chase.png" in registered_previews
    assert "b1-map12-preview.json" in registered_previews
    assert "molmospaces-val_6-map.png" not in registered_previews
    assert "molmospaces-val_8-map.png" not in registered_previews


def _assert_scene_preview_png_assets(base_url: str) -> None:
    for asset_name in (
        "molmospaces-procthor-objaverse-val-10-map.png",
        "molmospaces-procthor-objaverse-val-10-topdown.png",
        "molmospaces-procthor-objaverse-val-10-chase.png",
        "molmospaces-procthor-10k-val-11-map.png",
        "molmospaces-procthor-10k-val-11-topdown.png",
        "molmospaces-procthor-10k-val-11-chase.png",
        "b1-map12-fpv.png",
        "b1-map12-map.png",
        "b1-map12-chase.png",
        "b1-map12-topdown.png",
    ):
        with urllib.request.urlopen(f"{base_url}/previews/{asset_name}") as response:
            assert response.headers["Content-Type"] == "image/png"
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"


def _assert_scene_preview_json_assets(base_url: str) -> None:
    with urllib.request.urlopen(
        f"{base_url}/previews/molmospaces-procthor-objaverse-val-10-preview.json"
    ) as response:
        preview = json.loads(response.read().decode("utf-8"))
        assert preview["views"]["chase"]["view"] == "chase_camera"
    with urllib.request.urlopen(f"{base_url}/previews/b1-map12-preview.json") as response:
        preview = json.loads(response.read().decode("utf-8"))
        assert preview["renderer"] == "b1_map12_static_gaussian_topdown_with_isaac_runtime_camera"
        assert preview["views"]["fpv"]["view"] == "raw_fpv"
        assert preview["views"]["map"]["view"] == "base_metric_map_preview"
        assert preview["views"]["chase"]["view"] == "chase_camera"
        assert preview["views"]["topdown"]["view"] == "topdown_scene_render"


def _assert_scene_preview_rejects_invalid_paths(base_url: str) -> None:
    for path in (
        "/previews/../app.js",
        "/previews/molmospaces-val_6-map.png",
        "/asset-previews/maps/../README.md",
    ):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{base_url}{path}")
        assert exc_info.value.code == 404


def test_operator_console_latest_run_endpoint_returns_artifact_backed_history(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "latest-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps({"run_id": run_id, "route": route.to_payload(), "phase": "finished"}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        with urllib.request.urlopen(f"http://{host}:{port}/api/runs/latest") as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["run_id"] == run_id
    assert payload["selection_id"] == route.id
    assert payload["run_dir"] == str(run_dir.resolve())


def test_operator_console_next_goal_autostarts_ready_followup(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "parent-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "operator_session_id": "session-test",
                "selected_intent": "open-ended",
                "route": route.to_payload(),
                "phase": "finished",
                "backend_lock": route.lock_name,
                "provider_profile": "minimax-responses",
                "mcp_host": "127.0.0.1",
                "mcp_port": 19888,
            }
        ),
        encoding="utf-8",
    )
    session_dir = tmp_path / "output" / "operator-console" / "sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "session-test.json").write_text(
        json.dumps(
            {
                "schema": "operator_console_session_v1",
                "operator_session_id": "session-test",
                "created_at_epoch": 1,
                "created_at": "2026-06-09T00:00:00Z",
                "active_run_id": run_id,
                "run_ids": [run_id],
                "message_ids": [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps({"cleanup_success": True}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")

    launched: dict[str, object] = {}

    def fake_start(root, request):  # noqa: ANN001, ANN202
        launched["root"] = root
        launched["request"] = request
        return {"run_id": "child-run"}

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/next-goal",
            method="POST",
            data=json.dumps({"prompt": "Run the next sweep"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with patch("roboclaws.operator_console.server.start_console_run", fake_start):
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

    assert payload["status"] == "started"
    assert payload["started_run"]["run_id"] == "child-run"
    launch_request = launched["request"]
    assert launch_request.selection_id_override == route.id
    assert launch_request.intent_id == "open-ended"
    assert launch_request.operator_session_id == "session-test"
    assert launch_request.parent_run_id == run_id
    assert launch_request.overrides == {
        "host": "127.0.0.1",
        "port": "19888",
        "provider_profile": "minimax-responses",
    }
    assert launch_request.next_goal_packet["operator_session_id"] == "session-test"
    assert launch_request.next_goal_packet["parent_run_id"] == run_id
    assert "parent_public_summary" in launch_request.next_goal_packet


def test_operator_console_resume_endpoint_records_paused_handoff_request(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "paused-handoff-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "operator_session_id": "session-test",
                "selected_intent": "open-ended",
                "route": route.to_payload(),
                "phase": "paused",
                "reason": "operator_handoff_requested",
                "resume_available": True,
                "backend_lock": route.lock_name,
            }
        ),
        encoding="utf-8",
    )
    session_dir = tmp_path / "output" / "operator-console" / "sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "session-test.json").write_text(
        json.dumps(
            {
                "schema": "operator_console_session_v1",
                "operator_session_id": "session-test",
                "created_at_epoch": 1,
                "created_at": "2026-06-09T00:00:00Z",
                "active_run_id": run_id,
                "run_ids": [run_id],
                "message_ids": [],
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/resume",
            method="POST",
            data=json.dumps({"prompt": "Manual control finished; continue."}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["command_type"] == "resume_with_prompt"
    assert payload["status"] == "queued"
    assert payload["delivery"]["transport"] == "runner_owned_paused_handoff_resume"
    assert payload["resume_request_packet"]["schema"] == (
        "operator_console_resume_request_packet_v1"
    )
    rows = (run_dir / "operator_resume_requests.jsonl").read_text(encoding="utf-8")
    assert "Manual control finished; continue." in rows


def _write_running_operator_control_state(tmp_path: Path, route, run_id: str) -> Path:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _operator_control_request(host: str, port: int, run_id: str, body: dict[str, object]):
    return urllib.request.Request(
        f"http://{host}:{port}/api/runs/{run_id}/control",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _post_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: dict[str, object],
) -> dict[str, object]:
    request = _operator_control_request(host, port, run_id, body)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _blocked_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: dict[str, object],
) -> dict[str, object]:
    request = _operator_control_request(host, port, run_id, body)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request)
    return json.loads(exc_info.value.read().decode("utf-8"))


def _blocked_raw_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: str,
) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://{host}:{port}/api/runs/{run_id}/control",
        method="POST",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request)
    assert exc_info.value.code == 400
    return json.loads(exc_info.value.read().decode("utf-8"))


@contextmanager
def _console_server(root: Path):
    handler = partial(ConsoleRequestHandler, root=root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _exercise_allowlisted_operator_control(
    root: Path, run_id: str
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "navigate_to_relative_pose"
        assert arguments == {"forward_m": 0.25, "lateral_m": 0.0, "yaw_delta_deg": 0.0}
        return {
            "ok": True,
            "tool": action,
            "status": "ok",
            "frame_id": "base_link",
            "applied_delta": dict(arguments),
            "requires_reobserve": True,
        }

    with _console_server(root) as (host, port):
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            payload = _post_operator_control_payload(
                host,
                port,
                run_id,
                {
                    "action": "navigate_to_relative_pose",
                    "forward_m": 0.25,
                    "lateral_m": 0.0,
                    "yaw_delta_deg": 0.0,
                },
            )

        blocked_payload = _blocked_operator_control_payload(
            host,
            port,
            run_id,
            {"action": "shell", "command": "whoami"},
        )
        large_payload = _blocked_operator_control_payload(
            host,
            port,
            run_id,
            {
                "action": "navigate_to_relative_pose",
                "forward_m": 2.0,
            },
        )

    return payload, blocked_payload, large_payload


def _assert_allowlisted_operator_control_response(
    payload: dict[str, object],
    blocked_payload: dict[str, object],
    large_payload: dict[str, object],
) -> None:
    assert payload["ok"] is True
    assert payload["actor"] == "operator"
    assert payload["action"] == "navigate_to_relative_pose"
    assert payload["operator_interventions"]["count"] == 1
    assert payload["response"]["requires_reobserve"] is True
    assert blocked_payload["error"] == "unsupported control action: shell"
    assert large_payload["error"] == "relative movement request exceeds console limits"


def _assert_operator_control_artifacts(tmp_path: Path, run_dir: Path, route) -> None:
    rows = [
        json.loads(line)
        for line in (run_dir / "operator_control.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in rows] == ["request", "response"]
    assert {row["actor"] for row in rows} == {"operator"}
    persisted = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    assert persisted["operator_interventions"]["assisted"] is True
    assert persisted["operator_interventions"]["autonomous_behavior_proof"] is False
    interventions = json.loads(
        (run_dir / "operator_interventions.json").read_text(encoding="utf-8")
    )
    assert interventions["count"] == 1
    assert interventions["events"][0]["action"] == "navigate_to_relative_pose"
    state = derive_operator_state(tmp_path, run_dir, route)
    assert state["operator_interventions"]["count"] == 1
    assert any(item["label"] == "Operator Control" for item in state["artifact_paths"])
    assert any(item["label"] == "Operator Interventions" for item in state["artifact_paths"])


def test_operator_console_control_endpoint_is_allowlisted_and_records_operator_rows(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "control-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)

    payload, blocked_payload, large_payload = _exercise_allowlisted_operator_control(
        tmp_path,
        run_id,
    )

    _assert_allowlisted_operator_control_response(payload, blocked_payload, large_payload)
    _assert_operator_control_artifacts(tmp_path, run_dir, route)


def test_operator_console_control_endpoint_rejects_malformed_request_body(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-control-body-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_raw_operator_control_payload(host, port, run_id, "{not-json")

    assert (
        payload["error"] == "operator console request body source must contain valid JSON object: "
        "POST /api/runs/malformed-control-body-run/control"
    )
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_non_object_request_body(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-control-body-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_raw_operator_control_payload(host, port, run_id, "[]")

    assert (
        payload["error"] == "operator console request body source must contain a JSON object: "
        "POST /api/runs/non-object-control-body-run/control"
    )
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_malformed_control_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-control-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    (run_dir / "operator_control.jsonl").write_text("\n{not-json}\n", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator control source contains invalid JSON" in payload["error"]
    assert "operator_control.jsonl:2" in payload["error"]
    assert (run_dir / "operator_control.jsonl").read_text(encoding="utf-8") == "\n{not-json}\n"


def test_operator_console_control_endpoint_rejects_non_object_control_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-control-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    (run_dir / "operator_control.jsonl").write_text("[]\n", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator control source row must be an object" in payload["error"]
    assert "operator_control.jsonl:1" in payload["error"]
    assert (run_dir / "operator_control.jsonl").read_text(encoding="utf-8") == "[]\n"


def test_operator_console_control_endpoint_rejects_malformed_operator_state_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-control-state-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("{not-json", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator state source contains invalid JSON" in payload["error"]
    assert "operator_state.json" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "{not-json"
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_non_object_operator_state_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-control-state-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("[]\n", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert "operator state source must be a JSON object" in payload["error"]
    assert "operator_state.json" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "[]\n"
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_does_not_overwrite_corrupt_state_after_tool_call(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "corrupt-control-state-after-call-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)
    state_path = run_dir / "operator_state.json"

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "observe"
        assert arguments == {}
        state_path.write_text("{corrupt-after-call", encoding="utf-8")
        return {"ok": True, "tool": action, "status": "ok"}

    with _console_server(tmp_path) as (host, port):
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            payload = _blocked_operator_control_payload(
                host,
                port,
                run_id,
                {"action": "observe"},
            )

    assert "operator state source contains invalid JSON" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "{corrupt-after-call"
    rows = [
        json.loads(line)
        for line in (run_dir / "operator_control.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in rows] == ["request", "response"]
    assert not (run_dir / "operator_interventions.json").exists()


def test_operator_console_control_endpoint_allows_paused_operator_handoff(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "handoff-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "paused",
                "reason": "operator_handoff_requested",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "observe"
        assert arguments == {}
        return {
            "ok": True,
            "tool": action,
            "status": "ok",
            "visible_object_detections": [],
        }

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/control",
            method="POST",
            data=json.dumps({"action": "observe"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

    assert payload["ok"] is True
    state = derive_operator_state(tmp_path, run_dir, route)
    assert state["phase"] == "paused"
    assert state["controls"]["relative_navigation_control_available"] is True
    assert state["controls"]["next_goal_available"] is False
    assert state["latest_operator_control"]["action"] == "observe"


def test_operator_console_control_endpoint_waits_for_mcp_ready(
    tmp_path: Path,
) -> None:
    route = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    run_id = "starting-control-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "starting",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_operator_control_payload(host, port, run_id, {"action": "observe"})

    assert payload["error"] == "manual control is waiting for the MCP endpoint to become ready"
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_unsupported_route(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_SDK_MAP_BUILD)
    run_id = "map-build-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/control",
            method="POST",
            data=json.dumps({"action": "observe"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 409
    assert payload["error"] == "route does not support relative navigation control"


def test_operator_console_control_endpoint_rejects_terminal_run(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "finished-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "finished",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/control",
            method="POST",
            data=json.dumps({"action": "observe"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 409
    assert payload["error"] == "terminal run cannot be controlled"


def test_operator_console_stop_endpoint_decodes_browser_encoded_run_id(tmp_path: Path) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = (
        "20260610-224107-molmospaces-procthor-objaverse-val-0-mujoco-open-task-"
        "openai-agents-sdk-world-public-labels"
    )
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    attempt_dir = run_dir / "0610_2241" / "seed-7"
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
        json.dumps({"phase": "running-sdk"}),
        encoding="utf-8",
    )
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{urllib.parse.quote(run_id, safe='')}/stop",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with (
            patch("roboclaws.operator_console.launcher._stop_live_child_run"),
            patch("roboclaws.operator_console.launcher._terminate_process_group"),
        ):
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))

    assert payload["run_id"] == run_id
    assert payload["phase"] == "stopped_by_operator"
    assert ResourceLock(tmp_path, route.lock_name).read().held is False


def test_operator_console_stop_endpoint_rejects_non_object_operator_state_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-stop-state-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    state_path = run_dir / "operator_state.json"
    state_path.write_text("[]\n", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/stop",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 400
    assert "operator stop source error" in payload["error"]
    assert "operator_state.json must contain a JSON object" in payload["error"]
    assert state_path.read_text(encoding="utf-8") == "[]\n"
    assert ResourceLock(tmp_path, route.lock_name).read().held is True


def test_operator_console_stop_endpoint_rejects_malformed_live_status_source(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-live-status-stop-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    attempt_dir = run_dir / "0619_1112" / "seed-7"
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
    status_path = attempt_dir / "live_status.json"
    status_path.write_text("{bad-live-status", encoding="utf-8")
    ResourceLock(tmp_path, route.lock_name).acquire(run_id=run_id, pid=99999999)

    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/runs/{run_id}/stop",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with (
            patch("roboclaws.operator_console.launcher._stop_live_child_run") as stop_child,
            patch("roboclaws.operator_console.launcher._terminate_process_group") as stop_wrapper,
            pytest.raises(urllib.error.HTTPError) as exc_info,
        ):
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 400
    assert "operator stop source error" in payload["error"]
    assert "live_status.json contains invalid JSON" in payload["error"]
    assert status_path.read_text(encoding="utf-8") == "{bad-live-status"
    stop_child.assert_not_called()
    stop_wrapper.assert_not_called()
    assert ResourceLock(tmp_path, route.lock_name).read().held is True
