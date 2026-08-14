from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import parse_json_object_text


def run_json_worker_once(
    *,
    worker_name: str,
    python_executable: Path,
    missing_runtime_hint: str,
    state_path: Path,
    command: str,
    args: tuple[str, ...],
    env: dict[str, str],
    timeout_s: float,
    worker_module: str,
) -> dict[str, Any]:
    if not python_executable.is_file():
        raise RuntimeError(
            f"{worker_name} Python runtime is missing: {python_executable}. {missing_runtime_hint}"
        )
    worker_command = worker_command_args(
        python_executable=python_executable,
        worker_module=worker_module,
        state_path=state_path,
        command=command,
        args=args,
    )
    try:
        completed = subprocess.run(
            worker_command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{worker_name} subprocess worker timed out ({command}, {timeout_s:g}s)"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"{worker_name} subprocess worker failed "
            f"({command}, exit {completed.returncode}): {completed.stderr.strip()}"
        )
    return parse_last_json_object(completed.stdout, worker_name=worker_name)


def worker_command_args(
    *,
    python_executable: Path,
    state_path: Path,
    command: str,
    args: tuple[str, ...],
    worker_module: str,
) -> list[str]:
    return [
        str(python_executable),
        "-m",
        worker_module,
        "--state-path",
        str(state_path),
        command,
        *args,
    ]


def parse_last_json_object(stdout: str, *, worker_name: str = "subprocess") -> dict[str, Any]:
    for line_number, line in _candidate_json_object_lines(stdout):
        line = line.strip()
        try:
            return parse_worker_json_object_line(
                line,
                worker_name=worker_name,
                source=f"stdout:{line_number}",
            )
        except ValueError as exc:
            if line.startswith("[") and isinstance(exc.__cause__, json.JSONDecodeError):
                continue
            raise RuntimeError(str(exc)) from exc
    raise RuntimeError(f"{worker_name} worker returned no JSON object: {stdout!r}")


def parse_worker_json_object_line(
    line: str,
    *,
    worker_name: str = "subprocess",
    source: str,
) -> dict[str, Any]:
    return parse_json_object_text(
        line.strip(),
        label=f"{worker_name} worker stdout row",
        source=source,
    )


def _candidate_json_object_lines(stdout: str) -> list[tuple[int, str]]:
    return [
        (line_number, line)
        for line_number, line in reversed(list(enumerate(stdout.splitlines(), start=1)))
        if _line_starts_like_json_value(line)
    ]


def _line_starts_like_json_value(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("{", "["))


def read_process_stderr(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    try:
        return process.stderr.read()
    except Exception:
        return ""


def worker_timeout_s(
    *,
    command: str,
    override_env_var: str,
    command_timeouts: dict[str, float],
    default_timeout_s: float,
) -> float:
    override = os.environ.get(override_env_var)
    if override not in {None, ""}:
        return _positive_timeout_value(override, override_env_var)
    return command_timeouts.get(command, default_timeout_s)


def worker_env(
    *,
    defaults: dict[str, str] | None = None,
    remove: tuple[str, ...] = (),
) -> dict[str, str]:
    env = os.environ.copy()
    for key in remove:
        env.pop(key, None)
    for key, value in (defaults or {}).items():
        env.setdefault(key, value)
    return env


def _positive_timeout_value(value: Any, setting_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{setting_name} must be a positive finite number of seconds, got {value!r}"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(
            f"{setting_name} must be a positive finite number of seconds, got {value!r}"
        )
    return parsed
