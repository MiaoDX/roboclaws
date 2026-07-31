from __future__ import annotations

import argparse
import datetime as dt
import os
import signal
import socket
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Sequence

RunRow = Callable[[dict[str, Any], dict[str, Any]], None]
RowBlockers = Callable[[dict[str, Any], dict[str, Any]], list[dict[str, str]]]
WriteRowResult = Callable[[dict[str, Any]], None]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def run_local_command(
    command: Sequence[str],
    *,
    cwd: os.PathLike[str] | str,
    env: dict[str, str],
    timeout_s: float | None,
) -> tuple[int, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        stdout, stderr = process.communicate()
        return (
            124,
            _timeout_output(exc.stdout, stdout),
            _timeout_output(exc.stderr, stderr),
            True,
        )
    return process.returncode, stdout, stderr, False


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5.0)


def _timeout_output(partial: str | bytes | None, final: str) -> str:
    if partial is None:
        return final
    if isinstance(partial, bytes):
        partial = partial.decode(errors="replace")
    return final if final.startswith(partial) else partial + final


def execute_local_rows(
    manifest: dict[str, Any],
    *,
    run_row: RunRow,
    row_blockers: RowBlockers,
    write_row_result: WriteRowResult,
    row_ids: Sequence[str] = (),
    max_parallel: int = 1,
    shard_id: str = "local-main",
) -> None:
    selected = _execution_rows(manifest, row_ids=row_ids)
    pending = {row["row_id"]: row for row in selected if row.get("status") != "skipped_by_budget"}
    rows_by_id = {row["row_id"]: row for row in manifest.get("rows") or []}
    active_groups: set[str] = set()
    futures: dict[Future[None], tuple[str, str]] = {}
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    worker_count = max(1, int(max_parallel))

    execution_target = os.environ.get("ROBOCLAWS_EVAL_EXECUTION_TARGET", "local")
    worker_pool = os.environ.get("ROBOCLAWS_EVAL_WORKER_POOL", "local")
    _validate_execution_target(selected, execution_target=execution_target)
    manifest["execution"] = {
        "execution_target": execution_target,
        "worker_pool": worker_pool,
        "shard_id": shard_id,
        "max_parallel": worker_count,
        "row_ids": [row["row_id"] for row in selected],
    }

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="eval-row") as pool:
        while pending or futures:
            _mark_failed_dependencies(
                pending,
                rows_by_id=rows_by_id,
                running_ids={row_id for row_id, _group in futures.values()},
                write_row_result=write_row_result,
                shard_id=shard_id,
                worker_id=worker_id,
                execution_target=execution_target,
                worker_pool=worker_pool,
            )
            submitted = _submit_ready_rows(
                pool,
                pending,
                futures=futures,
                active_groups=active_groups,
                rows_by_id=rows_by_id,
                manifest=manifest,
                run_row=run_row,
                row_blockers=row_blockers,
                write_row_result=write_row_result,
                shard_id=shard_id,
                worker_id=worker_id,
                execution_target=execution_target,
                worker_pool=worker_pool,
                slots=worker_count - len(futures),
            )
            if futures:
                completed, _pending_futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    _row_id, group = futures.pop(future)
                    if group:
                        active_groups.discard(group)
                    future.result()
                continue
            if pending and not submitted:
                _mark_unresolvable_dependencies(
                    pending,
                    rows_by_id=rows_by_id,
                    write_row_result=write_row_result,
                    shard_id=shard_id,
                    worker_id=worker_id,
                    execution_target=execution_target,
                    worker_pool=worker_pool,
                )


def _validate_execution_target(
    rows: Sequence[dict[str, Any]],
    *,
    execution_target: str,
) -> None:
    for row in rows:
        axes = row.get("axes") or {}
        provider_profile = str(axes.get("provider_profile") or "")
        if not provider_profile:
            continue
        allowed_targets = row.get("allowed_execution_targets")
        if not isinstance(allowed_targets, list) or not allowed_targets:
            raise ValueError(
                f"provider row {row['row_id']!r} must declare allowed_execution_targets"
            )
        if execution_target not in allowed_targets:
            raise ValueError(
                f"provider row {row['row_id']!r} using {provider_profile!r} cannot run on "
                f"execution target {execution_target!r}; allowed targets: "
                + ", ".join(str(target) for target in allowed_targets)
            )


def _execution_rows(manifest: dict[str, Any], *, row_ids: Sequence[str]) -> list[dict[str, Any]]:
    selected = [row for row in manifest.get("rows") or [] if row.get("selected")]
    if not row_ids:
        return selected
    requested = list(dict.fromkeys(str(row_id) for row_id in row_ids if str(row_id)))
    selected_by_id = {str(row["row_id"]): row for row in selected}
    missing = [row_id for row_id in requested if row_id not in selected_by_id]
    if missing:
        raise ValueError("frozen manifest does not contain selected row(s): " + ", ".join(missing))
    return [selected_by_id[row_id] for row_id in requested]


def _submit_ready_rows(
    pool: ThreadPoolExecutor,
    pending: dict[str, dict[str, Any]],
    *,
    futures: dict[Future[None], tuple[str, str]],
    active_groups: set[str],
    rows_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    run_row: RunRow,
    row_blockers: RowBlockers,
    write_row_result: WriteRowResult,
    shard_id: str,
    worker_id: str,
    execution_target: str,
    worker_pool: str,
    slots: int,
) -> int:
    submitted = 0
    running_ids = {row_id for row_id, _group in futures.values()}
    for row_id, row in list(pending.items()):
        if submitted >= slots:
            break
        group = str(row.get("concurrency_group") or "")
        if group and group in active_groups:
            continue
        if not _dependencies_passed(row, rows_by_id=rows_by_id, running_ids=running_ids):
            continue
        pending.pop(row_id)
        if group:
            active_groups.add(group)
        future = pool.submit(
            _execute_one,
            row,
            manifest=manifest,
            run_row=run_row,
            row_blockers=row_blockers,
            write_row_result=write_row_result,
            shard_id=shard_id,
            worker_id=worker_id,
            execution_target=execution_target,
            worker_pool=worker_pool,
        )
        futures[future] = (row_id, group)
        running_ids.add(row_id)
        submitted += 1
    return submitted


def _dependencies_passed(
    row: dict[str, Any],
    *,
    rows_by_id: dict[str, dict[str, Any]],
    running_ids: set[str],
) -> bool:
    for dependency_id in row.get("depends_on") or []:
        dependency = rows_by_id.get(str(dependency_id))
        if dependency is None or str(dependency_id) in running_ids:
            return False
        if dependency.get("status") != "ran" or dependency.get("outcome") != "passed":
            return False
    return True


def _mark_failed_dependencies(
    pending: dict[str, dict[str, Any]],
    *,
    rows_by_id: dict[str, dict[str, Any]],
    running_ids: set[str],
    write_row_result: WriteRowResult,
    shard_id: str,
    worker_id: str,
    execution_target: str,
    worker_pool: str,
) -> None:
    for row_id, row in list(pending.items()):
        failure = _terminal_dependency_failure(
            row,
            rows_by_id=rows_by_id,
            pending_ids=set(pending),
            running_ids=running_ids,
        )
        if failure is None:
            continue
        pending.pop(row_id)
        _mark_dependency_blocked(
            row,
            detail=failure,
            write_row_result=write_row_result,
            shard_id=shard_id,
            worker_id=worker_id,
            execution_target=execution_target,
            worker_pool=worker_pool,
        )


def _terminal_dependency_failure(
    row: dict[str, Any],
    *,
    rows_by_id: dict[str, dict[str, Any]],
    pending_ids: set[str],
    running_ids: set[str],
) -> str | None:
    for dependency_id in row.get("depends_on") or []:
        dependency_id = str(dependency_id)
        dependency = rows_by_id.get(dependency_id)
        if dependency is None:
            return f"required dependency row {dependency_id!r} is missing from the manifest"
        if dependency_id in pending_ids or dependency_id in running_ids:
            continue
        if dependency.get("status") == "ran" and dependency.get("outcome") == "passed":
            continue
        return (
            f"required dependency row {dependency_id!r} did not pass "
            f"(status={dependency.get('status')!r}, outcome={dependency.get('outcome')!r})"
        )
    return None


def _mark_unresolvable_dependencies(
    pending: dict[str, dict[str, Any]],
    *,
    rows_by_id: dict[str, dict[str, Any]],
    write_row_result: WriteRowResult,
    shard_id: str,
    worker_id: str,
    execution_target: str,
    worker_pool: str,
) -> None:
    pending_ids = set(pending)
    for row_id, row in list(pending.items()):
        dependencies = [str(value) for value in row.get("depends_on") or []]
        unresolved = [
            dependency_id
            for dependency_id in dependencies
            if dependency_id in pending_ids
            or dependency_id not in rows_by_id
            or rows_by_id[dependency_id].get("outcome") != "passed"
        ]
        pending.pop(row_id)
        detail = "dependency graph cannot make progress"
        if unresolved:
            detail += ": " + ", ".join(unresolved)
        _mark_dependency_blocked(
            row,
            detail=detail,
            write_row_result=write_row_result,
            shard_id=shard_id,
            worker_id=worker_id,
            execution_target=execution_target,
            worker_pool=worker_pool,
        )


def _execute_one(
    row: dict[str, Any],
    *,
    manifest: dict[str, Any],
    run_row: RunRow,
    row_blockers: RowBlockers,
    write_row_result: WriteRowResult,
    shard_id: str,
    worker_id: str,
    execution_target: str,
    worker_pool: str,
) -> None:
    started = time.monotonic()
    _start_attempt(
        row,
        shard_id=shard_id,
        worker_id=worker_id,
        execution_target=execution_target,
        worker_pool=worker_pool,
    )
    try:
        blockers = row_blockers(row, manifest)
        if blockers:
            row["status"] = "blocked"
            row["outcome"] = "blocked"
            row["blocker_category"] = blockers[0]["category"]
            row["blockers"] = blockers
            return
        run_row(row, manifest)
    except Exception as exc:  # the row result must survive harness/runtime exceptions
        row["status"] = "ran"
        row["outcome"] = "failed"
        row["exit_code"] = 1
        row["failure_class"] = "harness_bug_unclassified"
        row["failure_detail"] = f"row execution raised {type(exc).__name__}: {exc}"
    finally:
        _finish_attempt(row, started=started)
        write_row_result(row)


def _start_attempt(
    row: dict[str, Any],
    *,
    shard_id: str,
    worker_id: str,
    execution_target: str,
    worker_pool: str,
) -> None:
    row["attempt"] = int(row.get("attempt") or 0) + 1
    row["execution_target"] = execution_target
    row["worker_pool"] = worker_pool
    row["shard_id"] = shard_id
    row["worker_id"] = worker_id
    row["started_at"] = _utc_now()


def _finish_attempt(row: dict[str, Any], *, started: float) -> None:
    row["finished_at"] = _utc_now()
    row["duration_s"] = round(max(0.0, time.monotonic() - started), 3)


def _mark_dependency_blocked(
    row: dict[str, Any],
    *,
    detail: str,
    write_row_result: WriteRowResult,
    shard_id: str,
    worker_id: str,
    execution_target: str,
    worker_pool: str,
) -> None:
    started = time.monotonic()
    _start_attempt(
        row,
        shard_id=shard_id,
        worker_id=worker_id,
        execution_target=execution_target,
        worker_pool=worker_pool,
    )
    row["status"] = "blocked"
    row["outcome"] = "blocked"
    row["blocker_category"] = "dependency_blocked"
    row["blockers"] = [{"category": "dependency_blocked", "detail": detail}]
    _finish_attempt(row, started=started)
    write_row_result(row)


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
