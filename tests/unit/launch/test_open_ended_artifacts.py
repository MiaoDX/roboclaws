from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.launch.open_ended_artifacts import validate_open_ended_artifacts


def test_open_ended_artifact_checker_accepts_single_run_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "seed-7"
    _write_open_ended_run(run_dir)

    assert validate_open_ended_artifacts(run_dir / "run_result.json") == (run_dir,)


def test_open_ended_artifact_checker_accepts_seed_run_root(tmp_path: Path) -> None:
    _write_open_ended_run(tmp_path / "seed-7")
    _write_open_ended_run(tmp_path / "seed-8")

    assert validate_open_ended_artifacts(tmp_path) == (
        tmp_path / "seed-7",
        tmp_path / "seed-8",
    )


def test_open_ended_artifact_checker_accepts_cwd_relative_declared_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = Path("output/evals/open-ended/seed-7")
    _write_open_ended_run(run_dir, declared_goal_contract=run_dir / "goal_contract.json")

    assert validate_open_ended_artifacts(run_dir) == (run_dir,)


def test_open_ended_artifact_checker_rejects_mismatched_goal_contract(tmp_path: Path) -> None:
    run_dir = tmp_path / "seed-7"
    _write_open_ended_run(run_dir, artifact_goal="different goal")

    with pytest.raises(RuntimeError, match="goal_contract does not match artifact"):
        validate_open_ended_artifacts(run_dir)


def _write_open_ended_run(
    run_dir: Path,
    *,
    artifact_goal: str = "find a drink",
    declared_goal_contract: Path | str = "goal_contract.json",
) -> None:
    run_dir.mkdir(parents=True)
    run_contract = {
        "schema": "roboclaws_goal_contract_v1",
        "surface": "household-world",
        "intent": "open-ended",
        "goal_scope": "agent-declared",
        "normalized_goal": "find a drink",
    }
    artifact_contract = dict(run_contract, normalized_goal=artifact_goal)
    (run_dir / "goal_contract.json").write_text(json.dumps(artifact_contract) + "\n")
    (run_dir / "report.html").write_text("<html>report</html>\n")
    (run_dir / "trace.jsonl").write_text('{"event": "response", "tool": "done"}\n')
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task_intent": "open-ended",
                "goal_contract": run_contract,
                "agent_completion_claim": {
                    "schema": "roboclaws_agent_completion_claim_v1",
                    "completion_summary": "done",
                },
                "artifacts": {"goal_contract": str(declared_goal_contract)},
            }
        )
        + "\n"
    )
