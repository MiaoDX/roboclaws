from __future__ import annotations

from pathlib import Path

from roboclaws.evals.harness.rows import candidate_rows
from roboclaws.evals.harness.runner import _row_blockers
from roboclaws.evals.live_runtime import live_surface_env
from roboclaws.evals.runner import run_eval_suite


def test_eval_environment_carries_private_delivery_identity() -> None:
    env = live_surface_env(
        {
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "profile",
            "skill_delivery_cell": "dynamic-routed",
            "model_visible_tool_surface": ["metric_map", "done"],
        },
        base_env={},
    )
    assert env["ROBOCLAWS_EVAL_SKILL_DELIVERY_CELL"] == "dynamic-routed"
    assert env["ROBOCLAWS_EVAL_MODEL_VISIBLE_TOOL_SURFACE"] == '["metric_map","done"]'


def test_sandbox_eval_records_blocked_without_product_launch(tmp_path: Path) -> None:
    called = False

    def product_runner(**_kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("sandbox blocked row must not launch product")

    run = run_eval_suite(
        "cleanup_capability",
        output_root=tmp_path,
        stamp="sandbox-blocked",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        live_execution="run",
        skill_delivery_cell="sandbox-skills",
        live_product_runner=product_runner,
    )
    assert called is False
    for result in run.bundle["results"]:
        assert result["status"] == "blocked"
        assert result["identity"]["runtime"]["skill_delivery_cell"] == "sandbox-skills"
        assert (
            "sdk_missing_sandbox_agent_or_skills" in result["grader_outputs"]["runner"]["message"]
        )


def test_harness_freezes_exactly_five_delivery_cells(tmp_path: Path) -> None:
    rows = candidate_rows(output_dir=tmp_path, explicit_axes={})
    delivery_rows = [row for row in rows if row["skill_delivery_cell"]]
    assert {row["skill_delivery_cell"] for row in delivery_rows} == {
        "no-skill",
        "static-full",
        "dynamic-full",
        "dynamic-routed",
        "sandbox-skills",
    }
    assert len(delivery_rows) == 5
    for row in delivery_rows:
        identity = row["skill_delivery_identity"]
        assert identity["requested_cell"] == row["skill_delivery_cell"]
        assert identity["content_sha256"]
        assert identity["index_sha256"]
        assert identity["sdk_version"]
        assert identity["model_visible_tool_surface"]
        assert identity["sandbox_posture"]["network"] == "disabled"
    sandbox = next(row for row in delivery_rows if row["skill_delivery_cell"] == "sandbox-skills")
    assert "sandbox_skills" in sandbox["requires"]
    blockers = _row_blockers(sandbox, {"output_dir": str(tmp_path)})
    assert blockers == [
        {"category": "environment_blocked", "detail": "sdk_missing_sandbox_agent_or_skills"}
    ]
