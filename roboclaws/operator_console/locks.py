"""File locks for live operator-console backend resources."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.operator_console.paths import console_output_root


def pid_is_active(pid: Any) -> bool:
    try:
        parsed_pid = int(pid)
    except (TypeError, ValueError):
        return False
    if parsed_pid <= 0:
        return False
    try:
        os.kill(parsed_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class LockState:
    name: str
    path: Path
    held: bool
    owner_run_id: str = ""
    pid: int | None = None
    acquired_at: float | None = None
    stale: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "held": self.held,
            "owner_run_id": self.owner_run_id,
            "pid": self.pid,
            "acquired_at": self.acquired_at,
            "stale": self.stale,
        }


class ResourceLockError(RuntimeError):
    """Raised when a route backend lock is unavailable."""


class ResourceLock:
    """Atomic JSON lock for one backend resource."""

    def __init__(self, root: Path, name: str) -> None:
        self.name = name
        self.path = console_output_root(root) / "locks" / f"{name}.json"

    def read(self) -> LockState:
        if not self.path.exists():
            return LockState(name=self.name, path=self.path, held=False)
        try:
            payload = read_json_object(self.path, label="operator resource lock")
        except (OSError, ValueError):
            return LockState(name=self.name, path=self.path, held=True, stale=True)
        pid = payload.get("pid")
        stale = False
        if isinstance(pid, int) and pid > 0:
            stale = not pid_is_active(pid)
        return LockState(
            name=self.name,
            path=self.path,
            held=True,
            owner_run_id=str(payload.get("run_id") or ""),
            pid=pid if isinstance(pid, int) else None,
            acquired_at=_float_or_none(payload.get("acquired_at")),
            stale=stale,
        )

    def acquire(self, *, run_id: str, pid: int | None = None) -> LockState:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": run_id, "pid": pid, "acquired_at": time.time()}
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags, 0o644)
        except FileExistsError as exc:
            state = self.read()
            if state.stale:
                self.release(run_id=state.owner_run_id, force=True)
                return self.acquire(run_id=run_id, pid=pid)
            raise ResourceLockError(
                "Backend lock is held by another run. Open that run or wait for it to finish."
            ) from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
        return self.read()

    def update_pid(self, *, run_id: str, pid: int) -> LockState:
        state = self.read()
        if not state.held:
            raise ResourceLockError(f"lock {self.name} is not held")
        if state.owner_run_id != run_id:
            raise ResourceLockError(f"lock {self.name} is owned by {state.owner_run_id}")
        payload = {
            "run_id": run_id,
            "pid": pid,
            "acquired_at": state.acquired_at or time.time(),
        }
        self.path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return self.read()

    def release(self, *, run_id: str, force: bool = False) -> None:
        state = self.read()
        if not state.held:
            return
        if not force and state.owner_run_id and state.owner_run_id != run_id:
            raise ResourceLockError(f"lock {self.name} is owned by {state.owner_run_id}")
        self.path.unlink(missing_ok=True)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
