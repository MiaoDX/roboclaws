"""Bounded subprocess execution for showcase rows."""

from __future__ import annotations

import math
import os
import signal
import subprocess
from typing import Any


def run_showcase_command(
    command: list[str], *, timeout_s: int
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run one row in its own process group so a timeout cannot orphan a server."""

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_group(process)
        stdout, stderr = process.communicate()
        return (
            subprocess.CompletedProcess(
                command,
                124,
                _merge_timeout_output(exc.stdout, stdout),
                _merge_timeout_output(exc.stderr, stderr),
            ),
            True,
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr), False


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if process.poll() is None:
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    if process.poll() is None:
        process.wait(timeout=5.0)


def _merge_timeout_output(partial: str | bytes | None, final: str) -> str:
    if partial is None:
        return final
    if isinstance(partial, bytes):
        partial = partial.decode(errors="replace")
    return final if final.startswith(partial) else partial + final


def row_execution_timeout_s(row: dict[str, Any], samples: list[Any] | None = None) -> int:
    """Keep a whole-row process deadline distinct from each live trial's cap."""
    from roboclaws.evals.suite_loading import load_suite

    if samples is None:
        _, samples = load_suite(row["suite"])
    selected = [s for s in samples if not row.get("sample_id") or s.sample_id == row["sample_id"]]
    trials = sum(1 if row.get("repetition_index") is not None else s.trial_count for s in selected)
    live = row["execution_mode"] != "deterministic"
    minimum = math.ceil(row["timeout_s"] * (trials if live else 1)) + 30
    value = row.get("execution_timeout_s")
    if value is None:
        if live and trials > 1:
            raise ValueError(
                f"showcase row {row['id']} requires execution_timeout_s for {trials} live trials"
            )
        return minimum
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(
            f"showcase row {row['id']} execution_timeout_s must be an integer >= {minimum} "
            "to cover selected trial caps and report margin"
        )
    return value
