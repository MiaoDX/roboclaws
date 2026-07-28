"""Open-ended household task artifact validation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

GOAL_CONTRACT_SCHEMA = "roboclaws_goal_contract_v1"
COMPLETION_CLAIM_SCHEMA = "roboclaws_agent_completion_claim_v1"


def validate_open_ended_artifacts(path: Path) -> tuple[Path, ...]:
    """Validate open-ended run artifacts without applying cleanup scoring gates."""

    run_results = _run_result_paths(path)
    for run_result_path in run_results:
        _validate_open_ended_run(run_result_path)
    return tuple(run_result.parent for run_result in run_results)


def _validate_open_ended_run(run_result_path: Path) -> None:
    run_dir = run_result_path.parent
    run_result = read_json_object(run_result_path, label="open-ended run_result")
    for artifact_name in ("report.html", "trace.jsonl", "goal_contract.json"):
        artifact_path = run_dir / artifact_name
        if not artifact_path.is_file():
            raise RuntimeError(f"open-ended live run finished without {artifact_path}")
    goal_contract = _dict_value(run_result, "goal_contract")
    if goal_contract.get("schema") != GOAL_CONTRACT_SCHEMA:
        raise RuntimeError("open-ended run_result is missing goal_contract")
    if goal_contract.get("intent") != "open-ended":
        raise RuntimeError("open-ended run_result goal_contract has non-open-ended intent")
    goal_contract_path = _artifact_path(
        run_dir,
        run_result,
        "goal_contract",
        fallback="goal_contract.json",
    )
    goal_contract_artifact = read_json_object(
        goal_contract_path,
        label="open-ended goal_contract",
    )
    if goal_contract_artifact != goal_contract:
        raise RuntimeError("open-ended run_result goal_contract does not match artifact")
    claim = _dict_value(run_result, "agent_completion_claim")
    if claim.get("schema") != COMPLETION_CLAIM_SCHEMA:
        raise RuntimeError("open-ended run_result is missing agent_completion_claim")
    if not str(claim.get("completion_summary") or "").strip():
        raise RuntimeError("open-ended agent_completion_claim is missing completion_summary")


def _run_result_paths(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (path,)
    direct = path / "run_result.json"
    if direct.is_file():
        return (direct,)
    run_results = tuple(sorted(path.glob("seed-*/run_result.json")))
    if run_results:
        return run_results
    raise RuntimeError(f"open-ended run finished without run_result.json under {path}")


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _artifact_path(base: Path, run_result: dict[str, Any], name: str, *, fallback: str) -> Path:
    artifacts = _dict_value(run_result, "artifacts")
    raw_path = str(artifacts.get(name) or fallback)
    path = Path(raw_path)
    return path if path.is_absolute() else base / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate open-ended household task artifacts without cleanup scoring."
    )
    parser.add_argument("path", type=Path, help="Run directory, run root, or run_result.json")
    args = parser.parse_args(argv)
    checked = validate_open_ended_artifacts(args.path)
    for run_dir in checked:
        print(f"open-ended artifacts ok: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
