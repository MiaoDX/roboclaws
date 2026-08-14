"""Host-level runtime probes used by the operator-console inventory."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from roboclaws.household.household_mcp_endpoint import DEFAULT_MCP_PORT
from roboclaws.operator_console.runtime_compat import float_or_none

LIVE_MARKERS = (
    "live_status.json",
    "run_result.json",
    "driver.log",
    "tmux_session.txt",
    "server.pid",
    "report.html",
)


def _latest_paths(paths: Any, *, limit: int) -> list[Path]:
    existing = [path for path in paths if path.is_file()]
    existing.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return existing[:limit]


def _has_live_markers(path: Path) -> bool:
    return any((path / marker).exists() for marker in LIVE_MARKERS)


def _tmux_session_name(display_run_dir: Path | None) -> str:
    if display_run_dir is None:
        return ""
    path = display_run_dir / "tmux_session.txt"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _server_pid(display_run_dir: Path | None) -> int | None:
    if display_run_dir is None:
        return None
    path = display_run_dir / "server.pid"
    if not path.is_file():
        return None
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def _repo_tmux_session(name: str) -> bool:
    return name.startswith(("roboclaws-molmo-", "roboclaws-agibot-", "roboclaws-"))


def _tmux_session_exists(name: str) -> bool:
    if not name:
        return False
    result = _run_command(["tmux", "has-session", "-t", name])
    return result is not None and result.returncode == 0


def _tcp_port_free(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return False
    except OSError:
        return True


def _listening_pid(port: int) -> int | None:
    result = _run_command(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"])
    if result is None:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            return int(line[1:])
    return None


def _run_command(command: list[str]) -> Any | None:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _path_is_repo_relevant(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _host_probe_enabled(root: Path) -> bool:
    """Skip host probes when not running from a repo root."""

    return (root / "pyproject.toml").is_file() and (root / "roboclaws").is_dir()


def _resolve_under_root(root: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve()
    except OSError:
        return path


def _relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return ""


def _same_host(left: str, right: str) -> bool:
    normalize = {"0.0.0.0": "127.0.0.1", "::": "127.0.0.1", "localhost": "127.0.0.1"}
    return normalize.get(left, left) == normalize.get(right, right)


def _parse_port(value: str) -> int:
    try:
        port = int(str(value).strip())
    except ValueError:
        return DEFAULT_MCP_PORT
    if not 1 <= port <= 65535:
        return DEFAULT_MCP_PORT
    return port


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _age_seconds(started_at_epoch: float | None) -> float | None:
    if started_at_epoch is None:
        return None
    return max(0.0, time.time() - started_at_epoch)


def _recent_epoch(value: Any, *, window_s: float) -> bool:
    epoch = float_or_none(value)
    return bool(epoch and time.time() - epoch <= window_s)


def _dedupe_ints(values: list[int]) -> list[int]:
    output: list[int] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
