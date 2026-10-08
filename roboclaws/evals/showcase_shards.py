"""Eval-layer case sharding for the existing showcase executor and result bundles."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.core.provider_catalog import resolve_route_model
from roboclaws.evals.models import EvalResult
from roboclaws.evals.result_persistence import persist_results
from roboclaws.evals.showcase import (
    execute_manifest,
    manifest_digest,
    validate_manifest,
    write_atomic,
)
from roboclaws.evals.showcase_acceptance import validate_result_identities
from roboclaws.evals.showcase_process import row_execution_timeout_s
from roboclaws.evals.suite_loading import load_suite

PLAN_SCHEMA = "roboclaws_showcase_shard_plan_v1"
EXTERNAL_PROVIDERS = {"minimax-responses": "minimax", "mimo-tp-openai-chat": "mimo"}
SETUP_TIMEOUT_S = 1200
UPLOAD_TIMEOUT_S = 300


def repository_revision() -> str:
    """Frozen execution cannot silently include uncommitted code or case changes."""
    status = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    if status.strip():
        raise ValueError("showcase sharding requires a clean committed checkout")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def build_shard_plan(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_manifest(manifest)
    revision = repository_revision()
    shards = []
    contents = {}
    for row in manifest["rows"]:
        if row["execution_mode"] == "deterministic":
            continue
        _validate_external_row(row)
        suite, samples = load_suite(row["suite"])
        contents[row["id"]] = [suite.to_dict(), [sample.to_dict() for sample in samples]]
        for sample in samples:
            if sample.sample_id not in row["sample_ids"]:
                continue
            if sample.artifact_dependencies:
                raise ValueError(
                    "case sharding requires independent cases without artifact dependencies"
                )
            repetitions = (
                [row["repetition_index"]]
                if row.get("repetition_index") is not None
                else range(sample.trial_count)
            )
            for repetition in repetitions:
                shard = {
                    "id": f"showcase-case-{len(shards):03d}",
                    "row_id": row["id"],
                    "sample_id": sample.sample_id,
                    "repetition_index": repetition,
                    "provider": EXTERNAL_PROVIDERS[row["provider_profile"]],
                }
                selected = shard_row(row, shard)
                deadline = row_execution_timeout_s(selected, [sample])
                shard["execution_timeout_s"] = deadline
                shard["timeout_minutes"] = math.ceil(
                    (SETUP_TIMEOUT_S + deadline + UPLOAD_TIMEOUT_S) / 60
                )
                if shard["timeout_minutes"] > 360:
                    raise ValueError("case deadline exceeds the hosted six-hour job limit")
                shards.append(shard)
    if not shards:
        raise ValueError("showcase sharding requires at least one external case")
    rows = {row["id"]: row for row in manifest["rows"]}
    return {
        "schema": PLAN_SCHEMA,
        "commit": revision,
        "contract_sha256": manifest_digest({"manifest": manifest, "contents": contents}),
        "setup_timeout_s": SETUP_TIMEOUT_S,
        "upload_timeout_s": UPLOAD_TIMEOUT_S,
        "max_parallel": 2,
        "trial_retries": 0,
        "shards": shards,
        "envelope": {
            "cases": len(shards),
            "decision_calls": sum(rows[s["row_id"]]["decision_call_budget"] for s in shards),
            "provider_tokens": sum(rows[s["row_id"]]["total_token_budget"] for s in shards),
            "trial_runtime_s": sum(rows[s["row_id"]]["timeout_s"] for s in shards),
            "runner_minutes": sum(s["timeout_minutes"] for s in shards),
        },
    }


def _validate_external_row(row: dict[str, Any]) -> None:
    if (
        row["provider_profile"] not in EXTERNAL_PROVIDERS
        or row["agent_engine"] != "openai-agents-sdk"
        or row["execution_mode"] != "manual_live_only"
    ):
        raise ValueError("hosted shards require an explicit external SDK provider")
    if not row.get("total_token_budget") or not row.get("model"):
        raise ValueError("hosted shards require explicit model and total_token_budget")
    try:
        spec = resolve_route_model(row["provider_profile"], row["model"])
    except KeyError as exc:
        raise ValueError(f"unknown shard model: {row['model']}") from exc
    if not spec.context_window_tokens or spec.model_id != row["model"]:
        raise ValueError("hosted shards require a canonical model with a known token bound")


def shard_row(row: dict[str, Any], shard: dict[str, Any]) -> dict[str, Any]:
    """Narrow execution only; full acceptance continues to use the original row."""
    selected = {
        **row,
        "sample_ids": [shard["sample_id"]],
        "sample_id": shard["sample_id"],
        "repetition_index": shard["repetition_index"],
    }
    selected.pop("cohort_acceptance", None)
    selected.pop("execution_timeout_s", None)
    return selected


def validate_plan(manifest: dict[str, Any], plan: dict[str, Any]) -> None:
    if plan != build_shard_plan(manifest):
        raise ValueError("shard plan differs from current code, case content, models or budgets")


def execute_shard(manifest, plan, *, shard_id: str, output_dir: Path, live_execution: str):
    validate_plan(manifest, plan)
    shard = next((s for s in plan["shards"] if s["id"] == shard_id), None)
    if shard is None:
        raise ValueError(f"unknown shard id: {shard_id}")
    row = next(row for row in manifest["rows"] if row["id"] == shard["row_id"])
    output_dir.mkdir(parents=True, exist_ok=False)
    receipt = {"plan_sha256": manifest_digest(plan), "shard": shard}
    write_atomic(output_dir / "shard.json", receipt)
    index = execute_manifest(
        {**manifest, "rows": [shard_row(row, shard)]},
        output_dir=output_dir,
        live_execution=live_execution,
    )
    return index


def _read_shard(row, shard, directory):
    index = json.loads((directory / "execution.json").read_text())
    attempts = index.get("attempts", [])
    paths = index.get("results", {})
    if len(attempts) != 1 or attempts[0].get("id") != row["id"]:
        raise ValueError("shard execution must contain exactly its selected row attempt")
    if not paths:
        return None
    if set(paths) != {row["id"]} or attempts[0].get("state") != "completed":
        raise ValueError("shard execution result disagrees with its attempt")
    path = Path(paths[row["id"]])
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("shard result must remain within its evidence directory")
    packet = json.loads(path.read_text())
    trials = packet.get("results", [])
    if len(trials) != 1:
        raise ValueError("each shard must contain exactly one trial, without reruns")
    result = EvalResult.from_mapping(trials[0])
    _validate_shard_result(row, shard, directory, result)
    return result


def _validate_shard_result(row, shard, directory, result):
    for artifact in result.artifacts.values():
        if isinstance(artifact, str) and Path(artifact).is_file():
            if not Path(artifact).resolve().is_relative_to(directory.resolve()):
                raise ValueError("shard artifacts must remain within their evidence directory")
    verdict, reason = validate_result_identities(
        shard_row(row, shard), [result.identity], {"total": 1}, "passed", None
    )
    if verdict != "passed":
        raise ValueError(f"shard result identity mismatch: {reason}")
    budgets = result.identity["budgets"]
    required_budgets = {
        "time_s": row["timeout_s"],
        "stall_timeout_s": row.get("stall_timeout_s", row["timeout_s"]),
        "decision_calls": row["decision_call_budget"],
        "total_tokens": row["total_token_budget"],
        "retry": 0,
    }
    if any(budgets.get(key) != value for key, value in required_budgets.items()):
        raise ValueError("shard result budgets differ from the frozen case bounds")
    if result.identity["runtime"].get("skill_delivery_cell") != "static-full":
        raise ValueError("shard result must use the static-full product Skill")


def merge_shards(manifest, plan, *, shard_dirs: list[Path], output_dir: Path):
    """Rebuild canonical eval bundles; missing shards block the entire affected row."""
    validate_plan(manifest, plan)
    if any(
        not directory.resolve().is_relative_to(output_dir.parent.resolve())
        for directory in shard_dirs
    ):
        raise ValueError("shard directories must share the merged output's evidence root")
    expected = {shard["id"]: shard for shard in plan["shards"]}
    rows = {row["id"]: row for row in manifest["rows"]}
    observed = set()
    collected: dict[str, list[EvalResult]] = {}
    for directory in shard_dirs:
        receipt_path = directory / "shard.json"
        if not receipt_path.is_file():
            continue
        receipt = json.loads(receipt_path.read_text())
        shard = receipt.get("shard", {})
        shard_id = shard.get("id")
        if (
            receipt.get("plan_sha256") != manifest_digest(plan)
            or shard_id not in expected
            or shard != expected[shard_id]
            or shard_id in observed
        ):
            raise ValueError("duplicate, unexpected or incompatible shard evidence")
        observed.add(shard_id)
        if not (directory / "execution.json").is_file():
            continue
        result = _read_shard(rows[shard["row_id"]], shard, directory)
        if result is not None:
            collected.setdefault(shard["row_id"], []).append(result)
    output_dir.mkdir(parents=True, exist_ok=False)
    return _persist_merged_rows(manifest, plan, collected, output_dir)


def _persist_merged_rows(manifest, plan, collected, output_dir):
    index: dict[str, Any] = {
        "schema": "roboclaws_showcase_execution_v1",
        "results": {},
        "attempts": [],
    }
    for row in manifest["rows"]:
        expected = [s for s in plan["shards"] if s["row_id"] == row["id"]]
        if not expected:
            continue
        results = collected.get(row["id"], [])
        complete = len(results) == len(expected)
        index["attempts"].append(
            {
                "id": row["id"],
                "state": "completed" if complete else "blocked",
                "reason": None if complete else "incomplete_shard_set",
                "agent_engine": row["agent_engine"],
                "provider_profile": row["provider_profile"],
            }
        )
        if complete:
            suite, _ = load_suite(row["suite"])
            _, path, _ = persist_results(
                suite=suite,
                results=sorted(
                    results, key=lambda r: (r.identity["sample_id"], r.identity["repetition_index"])
                ),
                output_dir=output_dir / "evals" / row["id"],
                budget=row["budget"],
                selection={"showcase_shard_plan_sha256": manifest_digest(plan)},
                artifact_link_root=output_dir.parent,
            )
            index["results"][row["id"]] = str(path)
    write_atomic(output_dir / "execution.json", index)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "execute", "merge"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--shard-id")
    parser.add_argument("--shard-dir", type=Path, action="append", default=[])
    parser.add_argument("--live-execution", choices=("blocked", "run"), default="blocked")
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    if args.mode == "plan":
        plan = build_shard_plan(manifest)
        if args.output.exists():
            parser.error("refusing to overwrite an existing shard plan")
        write_atomic(args.output, plan)
        print(json.dumps(plan))
        return 0
    if not args.plan:
        parser.error("--plan is required for execute and merge")
    plan = json.loads(args.plan.read_text())
    if args.mode == "execute":
        if not args.shard_id:
            parser.error("--shard-id is required for execute")
        execute_shard(
            manifest,
            plan,
            shard_id=args.shard_id,
            output_dir=args.output,
            live_execution=args.live_execution,
        )
    else:
        merge_shards(manifest, plan, shard_dirs=args.shard_dir, output_dir=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
