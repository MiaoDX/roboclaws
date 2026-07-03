from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from roboclaws.household.agibot_contract_rehearsal import (
    run_molmospaces_agibot_prehardware_rehearsal,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def _trace_agent_run(*args: str) -> list[str]:
    binary = _just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "agent::run", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().split("\t")


def test_agibot_molmospaces_sim_route_passes_open_evidence_refresh_prompt() -> None:
    prompt = "基于已有 Runtime Metric Map 做开放巡检"

    route = _trace_agent_run(
        "household-world",
        "direct-runner",
        "camera-grounded-labels",
        "task_intent=map-build",
        "backend=agibot_molmospaces_sim",
        "runtime=fixture",
        "camera_labeler=grounding-dino",
        f"prompt={prompt}",
    )

    assert "--task-prompt" in route
    assert prompt in route


def test_agibot_molmospaces_sim_rehearsal_records_open_evidence_refresh_prompt(
    tmp_path: Path,
) -> None:
    prompt = (
        "基于当前已有 Runtime Metric Map，自主选择 3 个最值得复核的 public semantic anchor "
        "或 inspection waypoint。"
    )
    run_dir = tmp_path / "map-evidence-refresh"

    result = run_molmospaces_agibot_prehardware_rehearsal(
        run_dir=run_dir,
        intent="map-build",
        profile="camera-grounded-labels",
        task_prompt=prompt,
        generated_mess_count=5,
        camera_labeler="sim",
    )

    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    runtime_export = json.loads(
        (run_dir / "runtime" / "runtime_export.json").read_text(encoding="utf-8")
    )

    assert result["task_prompt"] == prompt
    assert run_result["task_prompt"] == prompt
    assert runtime_export["task_prompt"] == prompt
    assert run_result["task_name"] == "household-world"
    assert run_result["task_intent"] == "map-build"
    assert run_result["simulated"] is True
    assert run_result["physical_robot"] is False
