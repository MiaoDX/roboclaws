from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.launch_contract import ConsoleLaunchError
from roboclaws.operator_console.launcher import (
    build_launch_args,
)
from roboclaws.operator_console.redaction import redact_text
from roboclaws.operator_console.routes import (
    get_selection,
    list_console_combinations,
    validate_supported_routes_against_catalog,
)
from roboclaws.operator_console.server import (
    main as operator_console_main,
)
from roboclaws.operator_console.state import (
    redacted_artifact_text,
)
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
from tests.unit.operator_console.operator_console_support import (
    _console_server,
    _just_bin,
)


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
    argv = build_launch_args(
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

    assert argv[:5] == [
        "surface=household-world",
        "world=molmospaces/procthor-objaverse-val/0",
        "backend=mujoco",
        "preset=cleanup",
        "agent_engine=openai-agents-sdk",
    ]
    assert "preset=cleanup" in argv
    assert "evidence_lane=world-public-labels" in argv
    assert "provider_profile=kimi-openai-chat" in argv
    assert "prompt=pick up the mug; rm -rf /" in argv
    assert "scenario_setup=relocate-cleanup-related-objects" in argv
    assert "relocation_count=2" in argv
    assert not any(item.startswith("generated_mess_count=") for item in argv)
    assert not any("OpenClaw" in item or "claude" in item for item in argv)

    open_ended = build_launch_args(
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

    default_open_ended = build_launch_args(
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
        build_launch_args(disabled, root=tmp_path, run_id="run-2", prompt="custom")

    with pytest.raises(ConsoleLaunchError, match="unsupported route parameter"):
        build_launch_args(route, root=tmp_path, run_id="run-3", overrides={"shell": "true"})


def test_redaction_removes_secret_values_and_headers(tmp_path: Path) -> None:
    text = (
        "Authorization: Bearer live-token\n"
        "KIMI_API_KEY=secret-key\n"
        "api_key: secret-key\n"
        "base https://secret.example/v1"
    )
    redacted = redact_text(
        text,
        env={"KIMI_API_KEY": "secret-key", "KIMI_OPENAI_BASE_URL": "https://secret.example/v1"},
    )
    assert "secret-key" not in redacted
    assert "live-token" not in redacted
    assert "https://secret.example/v1" not in redacted

    artifact = tmp_path / "driver.log"
    artifact.write_text("Authorization: Bearer live-token\n", encoding="utf-8")
    assert "live-token" not in redacted_artifact_text(artifact)


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
    assert run_server.call_args.kwargs["include_optional_worlds"] is False


def test_operator_console_cli_can_include_optional_worlds() -> None:
    with patch("roboclaws.operator_console.server.run_server") as run_server:
        assert operator_console_main(["--include-optional-worlds"]) == 0

    assert run_server.call_args.kwargs["include_optional_worlds"] is True


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
    assert "agibot-g2/map-12" not in worlds
    assert "b1-map12" not in worlds
    assert not any(route_id.startswith("agibot-g2/map-12::") for route_id in routes)
    assert not any(route_id.startswith("b1-map12::") for route_id in routes)
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
    assert not any(
        "::isaaclab::" in route_id for route_id in routes if route_id.startswith("molmospaces/")
    )


def test_operator_console_optional_world_opt_in_exposes_validation_routes(tmp_path: Path) -> None:
    with _console_server(tmp_path, include_optional_worlds=True) as (host, port):
        with urllib.request.urlopen(f"http://{host}:{port}/api/routes") as response:
            payload = json.loads(response.read().decode("utf-8"))

    world_ids = {world["id"] for world in payload["worlds"]}
    route_ids = {route["id"] for route in payload["combinations"]}
    assert {"agibot-g2/map-12", "b1-map12"} <= world_ids
    assert AGIBOT_SDK_MAP_BUILD in route_ids
    assert B1_OPENAI_AGENTS_MAP_BUILD in route_ids
