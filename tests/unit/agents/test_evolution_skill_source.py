from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.household_live_config import (
    EVAL_SKILL_SOURCE_ROOT_ENV,
    eval_skill_source_root,
)
from roboclaws.evals.live_runtime import live_surface_env


def test_frozen_candidate_root_reaches_trusted_robot_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = (tmp_path / "candidate").resolve()
    candidate.mkdir()
    (candidate / "candidate.json").write_text(
        json.dumps(
            {
                "schema": "eval_evolution_materialized_candidate_v1",
                "target_kind": "skill",
                "workspace": str(candidate),
                "identity_frozen": True,
            }
        ),
        encoding="utf-8",
    )
    env = live_surface_env(
        {
            "agent_engine": "openai-agents-sdk",
            "skill_source_root": str(candidate),
        },
        base_env={},
    )
    assert env[EVAL_SKILL_SOURCE_ROOT_ENV] == str(candidate)
    monkeypatch.setenv(EVAL_SKILL_SOURCE_ROOT_ENV, str(candidate))
    assert eval_skill_source_root(tmp_path / "repo") == candidate


def test_candidate_root_without_frozen_identity_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "candidate.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(EVAL_SKILL_SOURCE_ROOT_ENV, str(candidate))
    with pytest.raises(ValueError, match="frozen candidate identity"):
        eval_skill_source_root(tmp_path / "repo")
