"""Launch constants for household live-agent drivers."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from roboclaws.household.visual_backend_slots import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
    VisualBackendSlotError,
    VisualBackendSlotLease,
    acquire_visual_backend_slot,
)

HOUSEHOLD_SERVER_MODULE = "roboclaws.cli.agent_server"
HOUSEHOLD_SERVER_TASK = "household-world"


@dataclass
class HouseholdLiveRunLease:
    """Held backend-resource lease for one household live runner."""

    visual_slot: VisualBackendSlotLease | None = None
    lock_file: TextIO | None = None

    def status_fields(self) -> dict[str, Any]:
        if self.visual_slot is None:
            return {}
        return {"visual_backend_slot": self.visual_slot.to_payload()}

    def release_visual_slot(self) -> None:
        if self.visual_slot is None:
            return
        try:
            self.visual_slot.release()
        except VisualBackendSlotError as exc:
            print(f"warning: could not release visual backend slot: {exc}", file=sys.stderr)
        finally:
            self.visual_slot = None


def acquire_household_live_run_lease(
    *,
    backend: str,
    repo_root: Path,
    run_dir: Path,
    status_path: Path,
    lock_path: Path,
    port: int,
    owner: str,
    started_at_epoch: float,
    extra_lock_payload: dict[str, Any] | None = None,
) -> HouseholdLiveRunLease:
    """Acquire the backend-specific live-run lease used by cleanup runners."""

    if backend == MOLMOSPACES_SUBPROCESS_BACKEND:
        try:
            visual_slot = acquire_visual_backend_slot(
                repo_root=repo_root,
                run_id=_run_id_from_run_dir(run_dir),
                pid=os.getpid(),
                backend=backend,
                port=port,
                output_dir=run_dir,
                status_path=status_path,
                owner=owner,
            )
        except VisualBackendSlotError as exc:
            if not str(exc).startswith("all "):
                raise RuntimeError(
                    f"invalid MolmoSpaces visual backend slot config: {exc}"
                ) from exc
            detail = f": {json.dumps(exc.active_slots, sort_keys=True)}" if exc.active_slots else ""
            raise RuntimeError(
                "no MolmoSpaces visual backend slot is available"
                f" under {repo_root / 'output/molmo/visual-backend-slots'}{detail}"
            ) from exc
        return HouseholdLiveRunLease(visual_slot=visual_slot)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_file.seek(0)
        active = lock_file.read().strip()
        lock_file.close()
        detail = f": {active}" if active else ""
        raise RuntimeError(f"another live Molmo cleanup run holds {lock_path}{detail}") from exc

    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "run_dir": str(run_dir),
        "status_path": str(status_path),
        "started_at_epoch": started_at_epoch,
    }
    if extra_lock_payload:
        payload.update(extra_lock_payload)
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(json.dumps(payload, sort_keys=True) + "\n")
    lock_file.flush()
    return HouseholdLiveRunLease(lock_file=lock_file)


def household_server_argv(python_bin: str) -> list[str]:
    """Return the package entrypoint for the household MCP server."""

    return [
        python_bin,
        "-m",
        HOUSEHOLD_SERVER_MODULE,
        HOUSEHOLD_SERVER_TASK,
    ]


def _run_id_from_run_dir(run_dir: Path) -> str:
    name = run_dir.name
    parent = run_dir.parent.name
    if parent:
        return f"{parent}/{name}"
    return name


def add_household_cleanup_live_runner_args(
    parser: argparse.ArgumentParser,
    *,
    policy_default: str | None = None,
) -> None:
    """Add shared CLI args for household cleanup live-agent runners."""

    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--status-path", type=Path, required=True)
    parser.add_argument("--client-url", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--lock-path", type=Path, required=True)
    parser.add_argument("--server-startup-timeout-s", type=float, default=600.0)
    parser.add_argument("--kickoff-prompt", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--task-surface", default="household-world")
    parser.add_argument("--intent", default="cleanup")
    parser.add_argument("--skill-name", default="household-world")
    if policy_default is None:
        parser.add_argument("--policy", required=True)
    else:
        parser.add_argument("--policy", default=policy_default)
    parser.add_argument("--task", required=True)
    parser.add_argument("--min-generated-mess-count", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--checker-profile", default="")
    parser.add_argument("--operator-resume-requests-path", type=Path, default=None)
    parser.add_argument("--server-arg", action="append", default=[])
    parser.add_argument("--checker-visual-arg", action="append", default=[])
