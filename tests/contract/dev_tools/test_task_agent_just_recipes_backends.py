from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.contract.dev_tools.task_agent_just_recipes_support import (
    HOUSEHOLD_AGENT_SERVER_MODULE,
    REPO_ROOT,
    agibot_dependency_overrides,
    assert_household_map_build_run_fails,
    trace_household_cleanup_run,
    trace_household_map_build_run,
)


def test_map_build_routes_agibot_backend_to_physical_pilot_cli(tmp_path: Path) -> None:
    route = trace_household_map_build_run(
        "direct",
        "camera-grounded-labels",
        "camera_labeler=grounding-dino",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
        "context_json=tests/fixtures/agibot_map_context.completed.json",
        "waypoint_id=wp_sofa_front",
        "output_dir=output/agibot/map-build",
    )

    assert route[:8] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        "output/agibot/map-build",
        "--context-json",
        "tests/fixtures/agibot_map_context.completed.json",
    ]
    assert "--waypoint-id" in route
    assert "wp_sofa_front" in route
    assert "agibot-g2-cleanup" not in " ".join(route)


def test_map_build_sdk_routes_agibot_backend_to_live_runner(tmp_path: Path) -> None:
    route = trace_household_map_build_run(
        "openai-agents-sdk",
        "camera-grounded-labels",
        "provider_profile=kimi-openai-chat",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
        "context_json=tests/fixtures/agibot_map_context.completed.json",
        "run_dir=output/agibot/map-build-sdk/test-run",
        "policy=openai_agents_agibot_map_build",
        "camera_labeler=grounding-dino",
        "visual_grounding_timeout_s=12.5",
    )

    assert route[:4] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.agents.household_live_runner",
    ]
    assert "--repo-root" in route
    assert str(REPO_ROOT) in route
    assert "--run-dir" in route
    assert "output/agibot/map-build-sdk/test-run" in route
    assert "--server-arg=--context-json" in route
    assert "--server-arg=tests/fixtures/agibot_map_context.completed.json" in route
    assert "--server-arg=--evidence-lane" in route
    assert "--server-arg=camera-grounded-labels" in route
    assert "--server-arg=--visual-grounding" in route
    assert "--server-arg=grounding-dino" in route
    assert "--server-arg=--visual-grounding-timeout-s" in route
    assert "--server-arg=12.5" in route
    assert "--backend" in route
    assert "agibot_gdk" in route
    assert "--policy" in route
    assert "openai_agents_agibot_map_build" in route


def test_household_cleanup_routes_agibot_backend_to_physical_pilot_cli(tmp_path: Path) -> None:
    route = trace_household_cleanup_run(
        "direct",
        "world-public-labels",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
    )

    assert route[:6] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        "output/household/household-world/cleanup/direct-world-public-labels",
    ]
    assert "--runner-python" in route
    assert "--runner-script" in route
    assert "--agibot-map-artifact-dir" in route


def test_household_cleanup_routes_agibot_backend_override_to_cleanup_pilot_cli(
    tmp_path: Path,
) -> None:
    route = trace_household_cleanup_run(
        "direct",
        "world-public-labels",
        "backend=agibot_gdk",
        *agibot_dependency_overrides(tmp_path),
        "context_json=tests/fixtures/agibot_map_context.completed.json",
        "waypoint_id=wp_sofa_front",
        "output_dir=output/agibot/cleanup",
    )

    assert route[:10] == [
        "cmd",
        ".venv/bin/python",
        "-m",
        "roboclaws.household.agibot_physical_pilot",
        "--output-dir",
        "output/agibot/cleanup",
        "--context-json",
        "tests/fixtures/agibot_map_context.completed.json",
        "--waypoint-id",
        "wp_sofa_front",
    ]
    assert "--runner-python" in route
    assert "--runner-script" in route
    assert "--agibot-map-artifact-dir" in route
    assert str(tmp_path / "agibot_map") in route


def test_live_cleanup_server_entrypoint_accepts_agibot_shared_mcp_backend() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            HOUSEHOLD_AGENT_SERVER_MODULE,
            "household-world",
            "--help",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "agibot_gdk" in result.stdout
    assert "--context-json" in result.stdout
    assert "--real-movement-enabled" in result.stdout


def test_agibot_sdk_map_build_route_requires_context_json(tmp_path: Path) -> None:
    stderr = assert_household_map_build_run_fails(
        "openai-agents-sdk",
        "camera-grounded-labels",
        "provider_profile=kimi-openai-chat",
        "backend=agibot_gdk",
        "camera_labeler=grounding-dino",
        *agibot_dependency_overrides(tmp_path),
    )

    assert (
        "backend=agibot_gdk surface=household-world task_intent=map-build "
        "openai-agents-sdk requires context_json" in stderr
    )
