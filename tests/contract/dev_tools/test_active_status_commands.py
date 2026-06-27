from __future__ import annotations

import json
import shlex
from pathlib import Path

from roboclaws.agents.provider_registry import (
    ROUTE_CAP_SUPPORTED,
    provider_route_spec,
    route_capabilities_for_engine,
)
from roboclaws.launch.catalog import resolve_surface_launch

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_open_ended_status_rerun_command_uses_current_provider_profile() -> None:
    text = (
        REPO_ROOT / "docs" / "status" / "active" / "open-ended-household-default-architecture.md"
    ).read_text(encoding="utf-8")
    command = text.split("Next command/artifact: re-run", 1)[1].split("`", 2)[1]
    argv = shlex.split(command)

    assert argv[:2] == ["just", "run::surface"]
    plan = resolve_surface_launch(argv[2:])
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.provider_profile == "codex-router-responses"
    assert plan.intent == "open-ended"


def test_raw_fpv_live_caps_use_current_retry_provider_profile() -> None:
    caps_path = REPO_ROOT / "docs" / "status" / "active" / "agent-sdk-raw-fpv-live-caps.json"
    caps = json.loads(caps_path.read_text(encoding="utf-8"))

    provider_profile = caps["provider_profile"]
    selected_route = caps["route_gate"]["selected"]
    next_action = caps["outcome"]["next"]

    assert provider_profile == "codex-router-responses"
    assert selected_route["provider_profile"] == provider_profile
    assert "codex-router-responses" in next_action
    assert "codex-env upstream availability recovers" not in next_action

    plan = resolve_surface_launch(
        [
            f"surface={caps['surface']}",
            f"world={caps['world']}",
            f"backend={caps['backend']}",
            "preset=cleanup",
            "agent_engine=openai-agents-sdk",
            f"provider_profile={provider_profile}",
            f"evidence_lane={caps['evidence_lane']}",
            f"seed={caps['seed']}",
            f"scenario_setup={caps['scenario_setup']}",
            f"relocation_count={caps['relocation_count']}",
        ]
    )
    route = provider_route_spec(provider_profile)

    assert plan.intent == "cleanup"
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.provider_profile == provider_profile
    assert route_capabilities_for_engine(route, "openai-agents-sdk")["image_transport"] == (
        ROUTE_CAP_SUPPORTED
    )


def test_live_agent_runtime_policy_uses_current_codex_retry_route() -> None:
    policy_paths = [
        REPO_ROOT / "docs" / "status" / "active" / "live-agent-runtime-sdk-spike.md",
        REPO_ROOT / "docs" / "plans" / "live-agent-runtime-sdk-perf-followups.md",
    ]
    policy_text = "\n".join(path.read_text(encoding="utf-8") for path in policy_paths)

    assert "codex-router-responses" in policy_text
    assert "retry GPT `codex-env`" not in policy_text
    assert "codex-env` upstream availability changes" not in policy_text
    assert "`codex-env`\n  recovers enough to retry P/AA" not in policy_text


def test_adaptive_inspection_live_proof_command_uses_current_map_build_route() -> None:
    plan_text = (
        REPO_ROOT / "docs" / "plans" / "2026-06-11-live-agent-adaptive-inspection-triggerability.md"
    ).read_text(encoding="utf-8")
    live_proof = plan_text.split("### Live-Proven", 1)[1]
    command_block = live_proof.split("```bash", 1)[1].split("```", 1)[0]
    command = " ".join(
        line.strip().rstrip("\\")
        for line in command_block.splitlines()
        if line.strip() and not line.strip().startswith("VISUAL_GROUNDING_")
    )
    argv = shlex.split(command)

    assert argv[:2] == ["just", "run::surface"]
    assert "map_mode=minimal" not in command
    plan = resolve_surface_launch(argv[2:])

    assert plan.intent == "map-build"
    assert plan.preset == "map-build"
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.provider_profile == "codex-router-responses"
    assert "camera_labeler=grounding-dino" in plan.overrides
