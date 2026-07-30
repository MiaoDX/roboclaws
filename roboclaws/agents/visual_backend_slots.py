"""Slot leases for bounded local MolmoSpaces live-agent backend concurrency."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

MOLMO_MAX_VISUAL_BACKENDS_ENV = "ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS"
DEFAULT_MOLMO_MAX_VISUAL_BACKENDS = 1
DEFAULT_SLOT_ROOT = Path("output/molmo/visual-backend-slots")
MOLMOSPACES_SUBPROCESS_BACKEND = "molmospaces_subprocess"


class VisualBackendSlotError(RuntimeError):
    """Raised when no visual backend slot can be leased."""

    def __init__(self, message: str, *, active_slots: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.active_slots = active_slots or []


@dataclass(frozen=True)
class VisualBackendSlotState:
    slot_id: int
    path: Path
    held: bool
    stale: bool = False
    run_id: str = ""
    pid: int | None = None
    backend: str = ""
    port: int | None = None
    output_dir: str = ""
    status_path: str = ""
    owner: str = ""
    acquired_at: float | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "path": str(self.path),
            "held": self.held,
            "stale": self.stale,
            "run_id": self.run_id,
            "pid": self.pid,
            "backend": self.backend,
            "port": self.port,
            "output_dir": self.output_dir,
            "status_path": self.status_path,
            "owner": self.owner,
            "acquired_at": self.acquired_at,
        }


@dataclass
class VisualBackendSlotLease:
    state: VisualBackendSlotState

    def release(self) -> None:
        release_visual_backend_slot(
            self.state.path,
            run_id=self.state.run_id,
            pid=self.state.pid,
        )

    def to_payload(self) -> dict[str, Any]:
        return self.state.to_payload()

    def __enter__(self) -> VisualBackendSlotLease:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.release()


def molmo_visual_slot_limit(env: dict[str, str] | None = None) -> int:
    env_map = os.environ if env is None else env
    raw = str(env_map.get(MOLMO_MAX_VISUAL_BACKENDS_ENV) or "").strip()
    if not raw:
        return DEFAULT_MOLMO_MAX_VISUAL_BACKENDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise VisualBackendSlotError(
            f"{MOLMO_MAX_VISUAL_BACKENDS_ENV} must be a positive integer, got {raw!r}"
        ) from exc
    if value <= 0:
        raise VisualBackendSlotError(
            f"{MOLMO_MAX_VISUAL_BACKENDS_ENV} must be a positive integer, got {raw!r}"
        )
    return value


def _visual_slot_limit(max_slots: int | None) -> int:
    if max_slots is None:
        return molmo_visual_slot_limit()
    if isinstance(max_slots, bool) or max_slots <= 0:
        raise VisualBackendSlotError(f"max_slots must be a positive integer, got {max_slots!r}")
    return max_slots


def visual_backend_slot_root(repo_root: str | Path = ".") -> Path:
    return Path(repo_root) / DEFAULT_SLOT_ROOT


def list_visual_backend_slots(
    *,
    repo_root: str | Path = ".",
    max_slots: int | None = None,
) -> list[VisualBackendSlotState]:
    root = visual_backend_slot_root(repo_root)
    limit = _visual_slot_limit(max_slots)
    return [
        _read_slot(root / _slot_filename(slot_id), slot_id=slot_id)
        for slot_id in range(1, limit + 1)
    ]


def acquire_visual_backend_slot(
    *,
    repo_root: str | Path = ".",
    run_id: str,
    pid: int,
    backend: str,
    port: int,
    output_dir: str | Path,
    status_path: str | Path,
    owner: str,
    max_slots: int | None = None,
) -> VisualBackendSlotLease:
    root = visual_backend_slot_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    limit = _visual_slot_limit(max_slots)
    active: list[dict[str, Any]] = []
    for slot_id in range(1, limit + 1):
        path = root / _slot_filename(slot_id)
        state = _read_slot(path, slot_id=slot_id)
        if state.held and state.stale:
            release_visual_backend_slot(path, run_id=state.run_id, pid=state.pid, force=True)
            state = _read_slot(path, slot_id=slot_id)
        if state.held:
            active.append(state.to_payload())
            continue
        payload = {
            "slot_id": slot_id,
            "run_id": run_id,
            "pid": pid,
            "backend": backend,
            "port": int(port),
            "output_dir": str(output_dir),
            "status_path": str(status_path),
            "owner": owner,
            "acquired_at": time.time(),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags, 0o644)
        except FileExistsError:
            raced = _read_slot(path, slot_id=slot_id)
            if raced.held:
                active.append(raced.to_payload())
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        return VisualBackendSlotLease(_read_slot(path, slot_id=slot_id))
    raise VisualBackendSlotError(
        f"all {limit} MolmoSpaces visual backend slot(s) are held",
        active_slots=active,
    )


def release_visual_backend_slot(
    path: str | Path,
    *,
    run_id: str = "",
    pid: int | None = None,
    force: bool = False,
) -> None:
    slot_path = Path(path)
    state = _read_slot(slot_path, slot_id=_slot_id_from_path(slot_path))
    if not state.held:
        return
    if not force:
        if run_id and state.run_id and state.run_id != run_id:
            raise VisualBackendSlotError(f"slot {state.slot_id} is owned by {state.run_id}")
        if pid is not None and state.pid is not None and state.pid != pid:
            raise VisualBackendSlotError(f"slot {state.slot_id} is owned by pid {state.pid}")
    slot_path.unlink(missing_ok=True)


def _read_slot(path: Path, *, slot_id: int) -> VisualBackendSlotState:
    if not path.exists():
        return VisualBackendSlotState(slot_id=slot_id, path=path, held=False)
    try:
        payload = read_json_object(path, label="visual backend slot")
    except (OSError, ValueError):
        return VisualBackendSlotState(slot_id=slot_id, path=path, held=True, stale=False)
    pid = payload.get("pid")
    pid_value = pid if isinstance(pid, int) else None
    stale = bool(pid_value and not _pid_exists(pid_value))
    port = payload.get("port")
    return VisualBackendSlotState(
        slot_id=slot_id,
        path=path,
        held=True,
        stale=stale,
        run_id=str(payload.get("run_id") or ""),
        pid=pid_value,
        backend=str(payload.get("backend") or ""),
        port=port if isinstance(port, int) else None,
        output_dir=str(payload.get("output_dir") or ""),
        status_path=str(payload.get("status_path") or ""),
        owner=str(payload.get("owner") or ""),
        acquired_at=_float_or_none(payload.get("acquired_at")),
    )


def _slot_filename(slot_id: int) -> str:
    return f"slot-{slot_id}.json"


def _slot_id_from_path(path: Path) -> int:
    stem = path.stem
    if stem.startswith("slot-"):
        try:
            return int(stem.removeprefix("slot-"))
        except ValueError:
            pass
    return 0


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or manage MolmoSpaces visual slots.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--repo-root", type=Path, default=Path("."))
    status_parser.add_argument("--max-slots", type=int, default=None)

    acquire_parser = subparsers.add_parser("acquire")
    acquire_parser.add_argument("--repo-root", type=Path, default=Path("."))
    acquire_parser.add_argument("--run-id", required=True)
    acquire_parser.add_argument("--pid", type=int, required=True)
    acquire_parser.add_argument("--backend", required=True)
    acquire_parser.add_argument("--port", type=int, required=True)
    acquire_parser.add_argument("--output-dir", required=True)
    acquire_parser.add_argument("--status-path", required=True)
    acquire_parser.add_argument("--owner", required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--path", type=Path, required=True)
    release_parser.add_argument("--run-id", default="")
    release_parser.add_argument("--pid", type=int, default=None)
    release_parser.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "status":
        payload = [
            state.to_payload()
            for state in list_visual_backend_slots(
                repo_root=args.repo_root,
                max_slots=args.max_slots,
            )
        ]
        print(json.dumps(payload, sort_keys=True))
        return 0
    if args.command == "acquire":
        lease = acquire_visual_backend_slot(
            repo_root=args.repo_root,
            run_id=args.run_id,
            pid=args.pid,
            backend=args.backend,
            port=args.port,
            output_dir=args.output_dir,
            status_path=args.status_path,
            owner=args.owner,
        )
        print(json.dumps(lease.to_payload(), sort_keys=True))
        return 0
    if args.command == "release":
        release_visual_backend_slot(
            args.path,
            run_id=args.run_id,
            pid=args.pid,
            force=args.force,
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
