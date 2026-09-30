from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.agents.household_live_config import EVAL_SKILL_NAME_ENV
from roboclaws.evals.harness.rows import candidate_rows
from roboclaws.evals.live_runtime import live_surface_env
from roboclaws.evals.runner import run_eval_suite


def test_eval_environment_carries_private_delivery_identity() -> None:
    env = live_surface_env(
        {
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "profile",
            "skill_delivery_cell": "no-skill",
            "model_visible_tool_surface": ["metric_map", "done"],
            "skill_name": "example",
        },
        base_env={},
    )
    assert env["ROBOCLAWS_EVAL_SKILL_DELIVERY_CELL"] == "no-skill"
    assert env["ROBOCLAWS_EVAL_MODEL_VISIBLE_TOOL_SURFACE"] == '["metric_map","done"]'
    assert env[EVAL_SKILL_NAME_ENV] == "example"


def test_live_surface_env_carries_task_kind() -> None:
    env = live_surface_env(
        {"task_kind": "long-horizon"},
        base_env={},
    )
    assert env["ROBOCLAWS_EVAL_TASK_KIND"] == "long-horizon"


@pytest.mark.parametrize("cell", ["dynamic-full", "dynamic-routed", "sandbox-skills"])
def test_retired_eval_rejected_before_product_launch(tmp_path: Path, cell) -> None:
    def product_runner(**_kwargs):
        raise AssertionError("retired delivery must not launch product")

    with pytest.raises(ValueError, match="retired skill_delivery_cell"):
        run_eval_suite(
            "cleanup_capability",
            output_root=tmp_path,
            agent_engine="openai-agents-sdk",
            provider_profile="minimax-responses",
            live_execution="run",
            skill_delivery_cell=cell,
            live_product_runner=product_runner,
        )
    with pytest.raises(ValueError, match="retired skill_delivery_cell"):
        live_surface_env({"skill_delivery_cell": cell}, base_env={})


def test_harness_has_only_product_and_explicit_control(tmp_path: Path) -> None:
    rows = candidate_rows(output_dir=tmp_path, explicit_axes={})
    delivery_rows = [row for row in rows if row["skill_delivery_cell"]]
    assert {row["skill_delivery_cell"] for row in delivery_rows} == {"no-skill", "static-full"}
    for row in delivery_rows:
        identity = row["skill_delivery_identity"]
        assert identity["requested_cell"] == row["skill_delivery_cell"]
        assert identity["content_sha256"] and identity["sdk_version"]
        assert identity["model_visible_tool_surface"]
        assert "sandbox_skills" not in row["requires"]
