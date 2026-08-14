"""Run package-owned MolmoSpaces scene source preparation worklists."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.worlds.molmospaces.worklist_alignment import (
    align_rows_to_worklist,
    load_next_flow_worklist,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_PREP_PATH = Path("output/scene-sampler-readiness/scene_sampler_source_prep.json")
DEFAULT_WORKLIST_PATH = Path("output/scene-sampler-readiness/scene_sampler_next_flow_worklist.json")
DEFAULT_OUTPUT_PATH = Path("output/scene-sampler-scanner/source_prep_run.json")
SOURCE_PREP_RUN_SCHEMA = "molmospaces_scene_sampler_source_prep_run_v1"
RunCommand = Callable[..., Any]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_source_prep(
        prep_path=args.prep,
        worklist_path=args.worklist,
        output_path=args.output,
        sources=tuple(args.sources),
        worlds=tuple(args.worlds),
        execute=bool(args.execute),
        run_command=subprocess.run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == "failed" else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record or execute the manual MolmoSpaces source-prep commands emitted by "
            "scene_sampler_source_prep.json. Dry-run is the default; pass --execute to run "
            "install commands."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--prep", type=Path, default=DEFAULT_PREP_PATH)
    parser.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        default=[],
        metavar="SCENE_SOURCE",
        help="Only include install candidates for this scene_source. May be repeated.",
    )
    parser.add_argument(
        "--world",
        action="append",
        dest="worlds",
        default=[],
        metavar="WORLD_ID",
        help="Only include this source-aware world id. May be repeated.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute install commands. Without this flag, commands are recorded only.",
    )
    return parser.parse_args(argv)


def run_source_prep(
    *,
    prep_path: Path,
    output_path: Path,
    worklist_path: Path | None = None,
    sources: tuple[str, ...] = (),
    worlds: tuple[str, ...] = (),
    execute: bool = False,
    run_command: RunCommand = subprocess.run,
) -> dict[str, Any]:
    prep = _load_prep(prep_path)
    rows = [
        _prep_candidate(candidate, execute=execute, run_command=run_command)
        for candidate in _iter_install_candidates(prep, sources=sources, worlds=worlds)
    ]
    failed_count = sum(1 for row in rows if row["status"] == "failed")
    executed_count = sum(1 for row in rows if row["status"] in {"passed", "failed"})
    if failed_count:
        status = "failed"
    elif execute and rows:
        status = "success"
    elif rows:
        status = "dry_run"
    else:
        status = "no_candidates"
    worklist = (
        load_next_flow_worklist(worklist_path) if worklist_path and worklist_path.exists() else None
    )
    if worklist is not None:
        worklist["worklist_path"] = str(worklist_path)
    result = {
        "schema": SOURCE_PREP_RUN_SCHEMA,
        "status": status,
        "execute": execute,
        "prep_path": str(prep_path),
        "output_path": str(output_path),
        "download_policy": "manual_operator_only",
        "candidate_count": len(rows),
        "executed_candidate_count": executed_count,
        "failed_candidate_count": failed_count,
        "sources": _source_prep_run_summaries(rows),
        "worklist_alignment": align_rows_to_worklist(
            worklist,
            runner="source_prep",
            rows=rows,
            sources=sources,
            worlds=worlds,
        ),
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _load_prep(prep_path: Path) -> dict[str, Any]:
    payload = read_json_object(prep_path, label="scene sampler source prep")
    if payload.get("schema") != "molmospaces_scene_sampler_source_prep_v1":
        raise ValueError(f"source prep schema mismatch: {payload.get('schema')!r}")
    return payload


def _iter_install_candidates(
    prep: dict[str, Any],
    *,
    sources: tuple[str, ...],
    worlds: tuple[str, ...],
) -> list[dict[str, Any]]:
    source_filter = set(sources)
    world_filter = set(worlds)
    rows: list[dict[str, Any]] = []
    for source, source_payload in sorted((prep.get("sources") or {}).items()):
        if source_filter and source not in source_filter:
            continue
        for candidate in source_payload.get("install_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            world_id = str(candidate.get("world_id") or "")
            if world_filter and world_id not in world_filter:
                continue
            rows.append(candidate)
    return rows


def _prep_candidate(
    candidate: dict[str, Any],
    *,
    execute: bool,
    run_command: RunCommand,
) -> dict[str, Any]:
    row = _candidate_row_base(candidate)
    command = str(candidate.get("install_command") or "")
    if not execute:
        return {
            **row,
            "status": "dry_run_ready",
            "skip_reason": "execute_flag_not_set",
            "commands": [
                {
                    "name": "install_scene_assets",
                    "command": command,
                    "status": "dry_run",
                }
            ],
        }
    command_result = _run_shell_command(
        "install_scene_assets",
        command,
        run_command=run_command,
    )
    if command_result["returncode"] != 0:
        return {
            **row,
            "status": "failed",
            "failed_command": "install_scene_assets",
            "commands": [command_result],
        }
    return {
        **row,
        "status": "passed",
        "commands": [command_result],
    }


def _candidate_row_base(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": candidate.get("scene_source", ""),
        "scene_index": candidate.get("scene_index"),
        "world_id": candidate.get("world_id", ""),
        "primary_path": candidate.get("primary_path", ""),
        "path_status": candidate.get("path_status", ""),
        "missing_paths": candidate.get("missing_paths") or [],
    }


def _source_prep_run_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("scene_source") or "unknown")
        summary = summaries.setdefault(
            source,
            {
                "scene_source": source,
                "status": "no_candidates",
                "candidate_count": 0,
                "executed_candidate_count": 0,
                "failed_candidate_count": 0,
                "world_ids": [],
            },
        )
        summary["candidate_count"] += 1
        if row.get("status") in {"passed", "failed"}:
            summary["executed_candidate_count"] += 1
        if row.get("status") == "failed":
            summary["failed_candidate_count"] += 1
        world_id = str(row.get("world_id") or "")
        if world_id:
            summary["world_ids"].append(world_id)
    for summary in summaries.values():
        summary["status"] = _source_status(summary)
    return dict(sorted(summaries.items()))


def _source_status(summary: dict[str, Any]) -> str:
    if int(summary.get("failed_candidate_count") or 0):
        return "failed"
    if int(summary.get("executed_candidate_count") or 0):
        return "executed"
    if int(summary.get("candidate_count") or 0):
        return "dry_run_ready"
    return "no_candidates"


def _run_shell_command(name: str, command: str, *, run_command: RunCommand) -> dict[str, Any]:
    if not command.strip():
        return {
            "name": name,
            "command": command,
            "shell": True,
            "returncode": 127,
            "stdout_tail": "",
            "stderr_tail": "empty command",
        }
    completed = run_command(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        shell=True,
    )
    return {
        "name": name,
        "command": command,
        "shell": True,
        "returncode": int(getattr(completed, "returncode", 0)),
        "stdout_tail": _tail(getattr(completed, "stdout", "")),
        "stderr_tail": _tail(getattr(completed, "stderr", "")),
    }


def _tail(value: str, *, limit: int = 4000) -> str:
    return value[-limit:]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
