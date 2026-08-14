"""Run package-owned MolmoSpaces scene scanner execution plans."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.launch.catalog import resolve_surface_launch
from roboclaws.launch.executor import spawn_launch_plan
from roboclaws.launch.runners import export_env_from_plan
from roboclaws.worlds.molmospaces.worklist_alignment import (
    align_rows_to_worklist,
    load_next_flow_worklist,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PLAN_PATH = Path("output/scene-sampler-readiness/scene_sampler_scanner_execution_plan.json")
DEFAULT_WORKLIST_PATH = Path("output/scene-sampler-readiness/scene_sampler_next_flow_worklist.json")
DEFAULT_OUTPUT_PATH = Path("output/scene-sampler-scanner/scanner_run.json")
SCANNER_RUN_SCHEMA = "molmospaces_scene_sampler_scanner_run_v1"
RunCommand = Callable[..., Any]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_scanner_plan(
        plan_path=args.plan,
        worklist_path=args.worklist,
        output_path=args.output,
        sources=tuple(args.sources),
        worlds=tuple(args.worlds),
        dry_run=bool(args.dry_run),
        run_command=subprocess.run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == "failed" else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the source-aware MolmoSpaces scanner execution plan. "
            "Blocked candidates are never run; ready candidates run preview then "
            "map-build product-smoke commands."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        default=[],
        metavar="SCENE_SOURCE",
        help="Only include candidates for this scene_source. May be passed multiple times.",
    )
    parser.add_argument(
        "--world",
        action="append",
        dest="worlds",
        default=[],
        metavar="WORLD_ID",
        help="Only include this source-aware world id. May be passed multiple times.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Record runnable rows without executing preview or map-build commands.",
    )
    return parser.parse_args(argv)


def run_scanner_plan(
    *,
    plan_path: Path,
    output_path: Path,
    worklist_path: Path | None = None,
    sources: tuple[str, ...] = (),
    worlds: tuple[str, ...] = (),
    dry_run: bool = False,
    run_command: RunCommand = subprocess.run,
) -> dict[str, Any]:
    plan = _load_plan(plan_path)
    rows = [
        _run_candidate(
            candidate,
            dry_run=dry_run,
            run_command=run_command,
        )
        for candidate in _iter_candidates(plan, sources=sources, worlds=worlds)
    ]
    failed_count = sum(1 for row in rows if row["status"] == "failed")
    ready_count = sum(1 for row in rows if row["scanner_status"] == "ready_for_product_smoke")
    executed_count = sum(1 for row in rows if row["status"] in {"passed", "failed"})
    if failed_count:
        status = "failed"
    elif dry_run and ready_count:
        status = "dry_run"
    elif ready_count == 0:
        status = "no_ready_candidates"
    else:
        status = "success"
    worklist = (
        load_next_flow_worklist(worklist_path) if worklist_path and worklist_path.exists() else None
    )
    if worklist is not None:
        worklist["worklist_path"] = str(worklist_path)
    result = {
        "schema": SCANNER_RUN_SCHEMA,
        "status": status,
        "dry_run": dry_run,
        "plan_path": str(plan_path),
        "output_path": str(output_path),
        "download_policy": "manual_operator_only",
        "candidate_count": len(rows),
        "ready_candidate_count": ready_count,
        "executed_candidate_count": executed_count,
        "skipped_candidate_count": sum(1 for row in rows if row["status"].startswith("skipped_")),
        "failed_candidate_count": failed_count,
        "sources": _source_run_summaries(rows),
        "worklist_alignment": align_rows_to_worklist(
            worklist,
            runner="scanner",
            rows=rows,
            sources=sources,
            worlds=worlds,
        ),
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _load_plan(plan_path: Path) -> dict[str, Any]:
    payload = read_json_object(plan_path, label="scene sampler scanner execution plan")
    if payload.get("schema") != "molmospaces_scene_sampler_scanner_execution_plan_v1":
        raise ValueError(f"scanner execution plan schema mismatch: {payload.get('schema')!r}")
    return payload


def _iter_candidates(
    plan: dict[str, Any],
    *,
    sources: tuple[str, ...],
    worlds: tuple[str, ...],
) -> list[dict[str, Any]]:
    source_filter = set(sources)
    world_filter = set(worlds)
    candidates: list[dict[str, Any]] = []
    for source, source_payload in sorted((plan.get("sources") or {}).items()):
        if source_filter and source not in source_filter:
            continue
        for candidate in source_payload.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            world_id = str(candidate.get("world_id") or "")
            if world_filter and world_id not in world_filter:
                continue
            candidates.append(candidate)
    return candidates


def _run_candidate(
    candidate: dict[str, Any],
    *,
    dry_run: bool,
    run_command: RunCommand,
) -> dict[str, Any]:
    row = _candidate_row_base(candidate)
    if candidate.get("scanner_status") != "ready_for_product_smoke":
        return {
            **row,
            "status": "skipped_blocked_candidate",
            "skip_reason": candidate.get("scanner_status") or "not_ready",
            "commands": [],
        }
    preview_command = str(candidate.get("preview_command") or "")
    map_build_command = str(candidate.get("map_build_product_smoke_command") or "")
    if dry_run:
        return {
            **row,
            "status": "dry_run_ready",
            "skip_reason": "dry_run_requested",
            "commands": [
                {"name": "preview", "command": preview_command, "status": "dry_run"},
                {
                    "name": "map_build_product_smoke",
                    "command": map_build_command,
                    "status": "dry_run",
                },
            ],
        }
    command_results = [
        _run_shell_words("preview", preview_command, run_command=run_command),
    ]
    if command_results[-1]["returncode"] == 0:
        command_results.append(_run_map_build(candidate, command=map_build_command))
    if command_results[-1]["returncode"] != 0:
        return {
            **row,
            "status": "failed",
            "failed_command": command_results[-1]["name"],
            "commands": command_results,
        }
    return {
        **row,
        "status": "passed",
        "commands": command_results,
    }


def _candidate_row_base(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_family": candidate.get("scene_family", ""),
        "scene_split": candidate.get("scene_split", ""),
        "scene_source": candidate.get("scene_source", ""),
        "scene_index": candidate.get("scene_index"),
        "world_id": candidate.get("world_id", ""),
        "scanner_status": candidate.get("scanner_status", ""),
        "admission_status": candidate.get("admission_status", ""),
        "readiness_status": candidate.get("readiness_status", ""),
        "lanes": candidate.get("lanes") or [],
        "failure_class": candidate.get("failure_class", ""),
        "blocked_reason": candidate.get("blocked_reason", ""),
        "selected_reason": candidate.get("selected_reason", ""),
        "room_count": candidate.get("room_count", 0),
        "waypoint_count": candidate.get("waypoint_count", 0),
        "category_provenance": candidate.get("category_provenance", ""),
        "preview_statuses": candidate.get("preview_statuses", {}),
        "passed_gates": candidate.get("passed_gates") or [],
        "required_gates": candidate.get("required_gates") or [],
        "missing_gates": candidate.get("missing_gates") or [],
        "missing_paths": candidate.get("missing_paths") or [],
        "candidate_file": candidate.get("candidate_file") or {},
        "primary_path": candidate.get("primary_path", ""),
        "path_status": candidate.get("path_status", ""),
        "next_action": candidate.get("next_action", ""),
    }


def _source_run_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("scene_source") or "unknown")
        summary = summaries.setdefault(
            source,
            {
                "scene_source": source,
                "status": "no_candidates",
                "candidate_count": 0,
                "ready_candidate_count": 0,
                "executed_candidate_count": 0,
                "skipped_candidate_count": 0,
                "failed_candidate_count": 0,
                "world_ids": [],
            },
        )
        summary["candidate_count"] += 1
        if row.get("scanner_status") == "ready_for_product_smoke":
            summary["ready_candidate_count"] += 1
        if row.get("status") in {"passed", "failed"}:
            summary["executed_candidate_count"] += 1
        if str(row.get("status") or "").startswith("skipped_"):
            summary["skipped_candidate_count"] += 1
        if row.get("status") == "failed":
            summary["failed_candidate_count"] += 1
        world_id = str(row.get("world_id") or "")
        if world_id:
            summary["world_ids"].append(world_id)
    for summary in summaries.values():
        summary["status"] = _source_run_status(summary)
    return dict(sorted(summaries.items()))


def _source_run_status(summary: dict[str, Any]) -> str:
    if int(summary.get("failed_candidate_count") or 0):
        return "failed"
    if int(summary.get("executed_candidate_count") or 0):
        return "executed"
    if int(summary.get("ready_candidate_count") or 0):
        return "ready_not_executed"
    if int(summary.get("candidate_count") or 0):
        return "no_ready_candidates"
    return "no_candidates"


def _run_shell_words(name: str, command: str, *, run_command: RunCommand) -> dict[str, Any]:
    if not command.strip():
        return {
            "name": name,
            "command": command,
            "argv": [],
            "returncode": 127,
            "stdout_tail": "",
            "stderr_tail": "empty command",
        }
    argv = shlex.split(command)
    completed = run_command(
        argv,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "name": name,
        "command": command,
        "argv": argv,
        "returncode": int(completed.returncode),
        "stdout_tail": _tail_text(str(completed.stdout or "")),
        "stderr_tail": _tail_text(str(completed.stderr or "")),
    }


def _run_map_build(candidate: dict[str, Any], *, command: str) -> dict[str, Any]:
    raw_launch_args = candidate.get("launch_args")
    if (
        not isinstance(raw_launch_args, list)
        or not raw_launch_args
        or not all(isinstance(item, str) and item.strip() for item in raw_launch_args)
    ):
        return {
            "name": "map_build_product_smoke",
            "command": command,
            "argv": [],
            "returncode": 2,
            "stdout_tail": "",
            "stderr_tail": "candidate launch_args must be a non-empty list of strings",
        }

    launch_args = list(raw_launch_args)
    public_argv = ["just", "run::surface", *launch_args]
    try:
        plan = resolve_surface_launch(launch_args)
    except ValueError as exc:
        return {
            "name": "map_build_product_smoke",
            "command": command,
            "argv": public_argv,
            "returncode": 2,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }

    env = os.environ.copy()
    env.update(export_env_from_plan(plan))
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr,
    ):
        process = spawn_launch_plan(
            plan,
            cwd=REPO_ROOT,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
        returncode = process.wait()
        stdout.seek(0)
        stderr.seek(0)
        stdout_text = stdout.read()
        stderr_text = stderr.read()
    return {
        "name": "map_build_product_smoke",
        "command": command,
        "argv": public_argv,
        "returncode": int(returncode),
        "stdout_tail": _tail_text(stdout_text),
        "stderr_tail": _tail_text(stderr_text),
    }


def _tail_text(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


if __name__ == "__main__":
    raise SystemExit(main())
