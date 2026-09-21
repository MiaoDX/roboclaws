"""Bounded subprocess execution for showcase rows."""

from __future__ import annotations

import os
import signal
import subprocess


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
