#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.apple2apple_test_grid import (
    DEFAULT_MAP_BUNDLE,
    RUNTIME_MAP_PRIOR_PLACEHOLDER,
    build_apple2apple_test_grid,
    mark_grid_dry_run,
    row_rerun_command,
    write_grid_manifest,
    write_grid_report,
)
from roboclaws.household.household_runtime_contract import DEFAULT_REALWORLD_TASK
from roboclaws.launch.catalog import resolve_surface_launch
from roboclaws.launch.executor import spawn_launch_plan
from roboclaws.launch.runners import export_env_from_plan

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or execute the MolmoSpaces apple-to-apple cleanup test grid "
            "for online/offline Runtime Metric Map comparison."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/molmo/apple2apple-grid"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generated-mess-count", type=int, default=10)
    parser.add_argument("--task", default=DEFAULT_REALWORLD_TASK)
    parser.add_argument("--map-bundle", default=DEFAULT_MAP_BUNDLE)
    parser.add_argument("--runtime-map-prior", default="")
    parser.add_argument("--visual-grounding-timeout-s", default="auto")
    parser.add_argument(
        "--row",
        action="append",
        default=[],
        help="Only execute or mark matching cleanup row ids. May be repeated.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--live-wait-timeout-s", type=float, default=7200.0)
    parser.add_argument("--live-wait-poll-s", type=float, default=10.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    grid = build_apple2apple_test_grid(
        output_dir=args.output_dir,
        seed=args.seed,
        generated_mess_count=args.generated_mess_count,
        task=args.task,
        map_bundle=args.map_bundle,
        runtime_map_prior=args.runtime_map_prior,
        visual_grounding_timeout_s=args.visual_grounding_timeout_s,
    )

    if not args.execute:
        mark_grid_dry_run(grid)
        _write_outputs(grid, args.output_dir)
        print(f"apple-to-apple grid manifest: {args.output_dir / 'apple2apple_test_grid.json'}")
        print(f"apple-to-apple grid report: {args.output_dir / 'apple2apple_test_grid.html'}")
        return 0

    if args.row:
        _merge_existing_grid_state(grid, args.output_dir, selected_row_ids=set(args.row))
    if args.runtime_map_prior:
        _mark_explicit_runtime_map_prior(grid, args.runtime_map_prior)
    status = _execute_grid(grid, args)
    _write_outputs(grid, args.output_dir)
    return status


def _execute_grid(grid: dict[str, Any], args: argparse.Namespace) -> int:
    selected_rows = _selected_rows(grid, filters=set(args.row))
    if not selected_rows:
        raise SystemExit("no cleanup rows selected")

    selected_row_ids = {str(row.get("row_id") or "") for row in selected_rows}
    for row in grid.get("rows") or []:
        if str(row.get("row_id") or "") not in selected_row_ids:
            if _has_existing_row_evidence(row):
                continue
            row["status"] = "not_selected"
            row["reason"] = "row was not selected for this execution"

    prior_path = args.runtime_map_prior
    if any(row.get("requires_runtime_map_prior") for row in selected_rows) and not prior_path:
        prior_path = _execute_prior_build(grid, args)
        grid["runtime_map_prior"] = prior_path
        _replace_runtime_map_prior(grid, prior_path)

    failure_count = 0
    for row in selected_rows:
        status = _execute_row(row, args)
        if status != 0:
            failure_count += 1
            if not args.continue_on_error:
                break
    return 1 if failure_count else 0


def _execute_prior_build(grid: dict[str, Any], args: argparse.Namespace) -> str:
    setup_rows = list(grid.get("setup_rows") or [])
    if not setup_rows:
        raise RuntimeError("offline rows require a runtime-map prior but no setup row exists")
    row = setup_rows[0]
    status = _execute_row(row, args)
    prior = _latest_runtime_map(Path(row["output_dir"]), seed=args.seed)
    if prior is None:
        if status != 0:
            raise RuntimeError("offline runtime-map prior build failed")
        raise RuntimeError("runtime-map prior build produced no runtime_metric_map.json")
    if status != 0:
        row["status"] = "artifact_success"
        row["reason"] = (
            f"runtime_metric_map.json was produced; setup command exited with status {status}"
        )
    row["runtime_map_prior"] = str(prior)
    return str(prior)


def _execute_row(row: dict[str, Any], args: argparse.Namespace) -> int:
    plan = resolve_surface_launch([str(item) for item in row.get("launch_args") or []])
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in (row.get("env") or {}).items()})
    env.update(export_env_from_plan(plan))
    print("+ " + row_rerun_command(row))
    process = spawn_launch_plan(
        plan,
        cwd=REPO_ROOT,
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    status = process.wait()
    run_dir = _latest_seed_dir(Path(row["output_dir"]), seed=args.seed)
    if run_dir is not None:
        row["run_dir"] = str(run_dir)
        live_status = _wait_for_live_terminal_status(
            run_dir,
            timeout_s=args.live_wait_timeout_s,
            poll_s=args.live_wait_poll_s,
        )
        if live_status is not None:
            status = int(live_status.get("exit_status") or 0)
            row["live_status"] = live_status
    row["exit_status"] = status
    row["updated_at"] = _now()
    if run_dir is not None:
        _refresh_row_artifacts(row, run_dir)
    if status == 0:
        row["status"] = "success" if row.get("report_path") else "launched"
        row["reason"] = (
            "" if row.get("report_path") else "command returned before seed report existed"
        )
    else:
        row["status"] = "failed"
        row["reason"] = f"command exited with status {status}"
    return status


def _wait_for_live_terminal_status(
    run_dir: Path,
    *,
    timeout_s: float,
    poll_s: float,
) -> dict[str, Any] | None:
    status_path = run_dir / "live_status.json"
    if not status_path.is_file():
        return None
    deadline = _monotonic() + timeout_s
    last_status = _read_status(status_path, retry_deadline=min(deadline, _monotonic() + poll_s))
    while True:
        phase = str(last_status.get("phase") or "")
        if phase in {"finished", "failed"} and "exit_status" in last_status:
            return last_status
        if _monotonic() >= deadline:
            timed_out = dict(last_status)
            timed_out["phase"] = "failed"
            timed_out["exit_status"] = 124
            timed_out["reason"] = "live row did not reach terminal status before timeout"
            return timed_out
        _sleep(max(float(poll_s), 0.1))
        last_status = _read_status(status_path, retry_deadline=min(deadline, _monotonic() + poll_s))


def _refresh_row_artifacts(row: dict[str, Any], run_dir: Path) -> None:
    report_path = run_dir / "report.html"
    if report_path.is_file():
        row["report_path"] = str(report_path)
    run_result_path = run_dir / "run_result.json"
    if run_result_path.is_file():
        row["run_result_path"] = str(run_result_path)


def _read_status(path: Path, *, retry_deadline: float | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {"phase": "unknown"}
    while True:
        try:
            return read_json_object(path, label="apple-to-apple live status")
        except ValueError:
            if retry_deadline is None or _monotonic() >= retry_deadline:
                raise
            _sleep(0.02)


def _merge_existing_grid_state(
    grid: dict[str, Any],
    output_dir: Path,
    *,
    selected_row_ids: set[str],
) -> None:
    manifest_path = output_dir / "apple2apple_test_grid.json"
    if not manifest_path.is_file():
        return
    existing = read_json_object(manifest_path, label="apple-to-apple grid manifest")

    existing_setup_rows = _rows_by_id(existing.get("setup_rows") or [])
    grid["setup_rows"] = [
        existing_setup_rows.get(str(row.get("row_id") or ""), row)
        for row in grid.get("setup_rows") or []
    ]

    existing_rows = _rows_by_id(existing.get("rows") or [])
    merged_rows = []
    for row in grid.get("rows") or []:
        row_id = str(row.get("row_id") or "")
        if row_id not in selected_row_ids and row_id in existing_rows:
            merged_rows.append(existing_rows[row_id])
        else:
            merged_rows.append(row)
    grid["rows"] = merged_rows


def _mark_explicit_runtime_map_prior(grid: dict[str, Any], prior_path: str) -> None:
    prior = Path(prior_path)
    for row in grid.get("setup_rows") or []:
        row["runtime_map_prior"] = str(prior)
        row["updated_at"] = _now()
        if prior.is_file():
            row["status"] = "artifact_success"
            row["reason"] = (
                "using explicit runtime_map_prior; setup command was not executed by this grid"
            )
            row["run_dir"] = str(prior.parent)
            report_path = prior.parent / "report.html"
            if report_path.is_file():
                row["report_path"] = str(report_path)
            run_result_path = prior.parent / "run_result.json"
            if run_result_path.is_file():
                row["run_result_path"] = str(run_result_path)
        else:
            row["status"] = "failed"
            row["reason"] = "explicit runtime_map_prior does not exist"


def _rows_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("row_id") or ""): row for row in rows if isinstance(row, dict)}


def _has_existing_row_evidence(row: dict[str, Any]) -> bool:
    return bool(
        row.get("run_result_path")
        or row.get("report_path")
        or row.get("live_status")
        or row.get("run_dir")
        or row.get("exit_status") is not None
        or row.get("status") in {"success", "failed", "artifact_success", "launched"}
    )


def _selected_rows(grid: dict[str, Any], *, filters: set[str]) -> list[dict[str, Any]]:
    rows = list(grid.get("rows") or [])
    if not filters:
        return rows
    return [row for row in rows if str(row.get("row_id") or "") in filters]


def _replace_runtime_map_prior(grid: dict[str, Any], prior_path: str) -> None:
    for row in grid.get("rows") or []:
        launch_args = [
            (
                f"runtime_map_prior={prior_path}"
                if item == f"runtime_map_prior={RUNTIME_MAP_PRIOR_PLACEHOLDER}"
                else item
            )
            for item in row.get("launch_args") or []
        ]
        row["launch_args"] = launch_args
        row["command"] = ["just", "run::surface", *launch_args]
        row["rerun_command"] = row_rerun_command(row)


def _latest_runtime_map(output_dir: Path, *, seed: int) -> Path | None:
    seed_dir = _latest_seed_dir(output_dir, seed=seed)
    if seed_dir is None:
        return None
    path = seed_dir / "runtime_metric_map.json"
    return path if path.is_file() else None


def _latest_seed_dir(output_dir: Path, *, seed: int) -> Path | None:
    direct = output_dir / f"seed-{seed}"
    if direct.is_dir():
        return direct
    candidates = sorted(
        path
        for path in output_dir.glob(f"*/seed-{seed}")
        if path.is_dir()
        and (
            (path / "run_result.json").is_file()
            or (path / "runtime_metric_map.json").is_file()
            or (path / "report.html").is_file()
            or (path / "live_status.json").is_file()
            or (path / "tmux_session.txt").is_file()
        )
    )
    return candidates[-1] if candidates else None


def _write_outputs(grid: dict[str, Any], output_dir: Path) -> None:
    write_grid_manifest(grid, output_dir)
    write_grid_report(grid, output_dir)


def _now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _monotonic() -> float:
    import time

    return time.monotonic()


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


if __name__ == "__main__":
    raise SystemExit(main())
