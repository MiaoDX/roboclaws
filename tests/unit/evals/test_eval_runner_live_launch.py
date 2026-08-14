from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.live_runtime import live_surface_command
from roboclaws.evals.models import load_eval_sample
from roboclaws.evals.runner import run_eval_suite
from roboclaws.launch.catalog import resolve_surface_launch
from tests.unit.evals.eval_runner_support import (
    _live_surface_kwargs,
    _run_result,
    _write_product_artifacts,
)


def test_eval_runner_runs_live_agent_when_explicitly_enabled(tmp_path: Path) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        seen_kwargs.append(kwargs)
        surface_run_dir = Path(kwargs["output_dir"]) / "surface-run" / f"seed-{kwargs['seed']}"
        _write_product_artifacts(surface_run_dir, completion_status="success")
        result = _run_result(surface_run_dir, completion_status="success")
        result["eval_effective_run_dir"] = str(surface_run_dir)
        return result

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-run",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_timeout_s=12.5,
        live_stall_timeout_s=6.25,
        live_product_runner=live_product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["passed"] == 3
    assert payload["aggregate"]["blocked"] == 0
    assert seen_kwargs[0]["agent_engine"] == "openai-agents-sdk"
    assert seen_kwargs[0]["provider_profile"] == "kimi-openai-chat"
    assert seen_kwargs[0]["live_timeout_s"] == 12.5
    assert seen_kwargs[0]["live_stall_timeout_s"] == 6.25
    result = payload["results"][0]
    assert result["identity"]["runner_class"] == "live-agent"
    assert result["artifacts"]["run_result"].endswith(
        "runs/cleanup_repeated_seed7/trial-0000/surface-run/seed-7/run_result.json"
    )


def test_live_surface_command_uses_current_public_launch_axes(tmp_path: Path) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        seen_kwargs.append(kwargs)
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="success")
        return _run_result(run_dir, completion_status="success")

    run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="live-command",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    command = live_surface_command(seen_kwargs[0], output_dir=tmp_path / "surface-run")
    assert "backend=mujoco" in command
    assert "agent_engine=openai-agents-sdk" in command
    assert "provider_profile=kimi-openai-chat" in command
    assert "evidence_lane=world-public-labels" in command
    assert "run_preset=smoke" in command
    assert "preset=cleanup" in command
    assert not any(item.startswith("generated_mess_count=") for item in command)
    plan = resolve_surface_launch(command[5:])
    assert plan.agent_engine == "openai-agents-sdk"
    assert plan.dispatch_runner == "openai-agents-live"
    assert plan.backend == "mujoco"
    assert plan.evidence_mode == "smoke"


def test_live_surface_command_passes_map_build_camera_labeler(tmp_path: Path) -> None:
    sample = load_eval_sample(
        Path(__file__).resolve().parents[3]
        / "evals"
        / "household_world"
        / "samples"
        / "map_build"
        / "baseline_seed7.json"
    )
    kwargs = _live_surface_kwargs(tmp_path / "trial-0000")
    kwargs.update(
        {
            "eval_sample": sample,
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "kimi-openai-chat",
            "evidence_lane": sample.evidence_lane,
            "visual_grounding": sample.camera_labeler,
            "map_build": True,
            "task_prompt": "帮我建立这个房间的 Runtime Metric Map",
        }
    )

    command = live_surface_command(kwargs, output_dir=tmp_path / "surface-run")

    assert "preset=map-build" in command
    assert "evidence_lane=camera-grounded-labels" in command
    assert "camera_labeler=grounding-dino" in command
    assert "agent_engine=openai-agents-sdk" in command
    plan = resolve_surface_launch(command[5:])
    assert plan.intent == "map-build"
    assert plan.dispatch_runner == "openai-agents-live"
    assert plan.evidence_mode == "camera-grounded-labels"


def test_live_surface_command_uses_no_preset_public_open_task_route(tmp_path: Path) -> None:
    seen_kwargs: list[dict[str, Any]] = []

    def live_product_runner(**kwargs: Any) -> dict[str, Any]:
        seen_kwargs.append(kwargs)
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(
            run_dir,
            completion_status="success",
            include_goal_contract=True,
        )
        return _run_result(
            run_dir,
            completion_status="success",
            task_intent="open-ended",
            include_completion_claim=True,
        )

    run_eval_suite(
        "open_ended_goals",
        output_root=tmp_path,
        stamp="live-open-task-command",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        live_product_runner=live_product_runner,
    )

    command = live_surface_command(seen_kwargs[0], output_dir=tmp_path / "surface-run")
    assert "surface=household-world" in command
    assert "agent_engine=openai-agents-sdk" in command
    assert "provider_profile=kimi-openai-chat" in command
    assert "run_preset=smoke" in command
    assert not any(item.startswith("preset=") for item in command)
    assert any(item.startswith("prompt=") for item in command)
    plan = resolve_surface_launch(command[5:])
    assert plan.intent == "open-ended"
    assert plan.preset is None


@pytest.mark.parametrize(
    ("field_name", "value", "expected_error"),
    [
        ("generated_mess_count", "bad", "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", "-1", "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", "5.5", "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", 5.0, "generated_mess_count must be a non-negative integer"),
        ("generated_mess_count", True, "generated_mess_count must be a non-negative integer"),
        ("scene_index", "bad", "scene_index must be a non-negative integer"),
        ("scene_index", "-1", "scene_index must be a non-negative integer"),
        ("scene_index", "5.5", "scene_index must be a non-negative integer"),
        ("scene_index", 5.0, "scene_index must be a non-negative integer"),
        ("scene_index", True, "scene_index must be a non-negative integer"),
        ("scene_source", "", "scene_source must be a non-empty string"),
        ("scene_source", "  ", "scene_source must be a non-empty string"),
        ("scene_source", 7, "scene_source must be a non-empty string"),
        ("scene_source", True, "scene_source must be a non-empty string"),
    ],
)
def test_live_surface_command_rejects_invalid_launch_metadata(
    tmp_path: Path,
    field_name: str,
    value: object,
    expected_error: str,
) -> None:
    kwargs = _live_surface_kwargs(tmp_path / "trial-0000")
    if field_name == "generated_mess_count":
        kwargs["evidence_lane"] = "world-public-labels"
    kwargs[field_name] = value

    with pytest.raises(ValueError, match=expected_error):
        live_surface_command(kwargs, output_dir=tmp_path / "surface-run")
