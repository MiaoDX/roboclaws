"""Heartbeat-backed live_status.json writer for Molmo live runs."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.agents.live_timeout_debug import timeout_debug_snapshot
from roboclaws.agents.live_timing import round_duration


class LiveRunStatusWriter:
    def __init__(
        self,
        *,
        run_dir: Path,
        status_path: Path,
        started_at_epoch: float,
        lease_status_fields: Callable[[], dict[str, Any]],
    ) -> None:
        self.run_dir = run_dir
        self.status_path = status_path
        self.started_at_epoch = started_at_epoch
        self.lease_status_fields = lease_status_fields
        self.lock = threading.Lock()
        self.phase = "initializing"
        self.terminal = False
        self.heartbeat_stop = threading.Event()
        self.heartbeat_thread: threading.Thread | None = None

    def start_heartbeat(self) -> None:
        if self.heartbeat_thread is not None:
            return
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="roboclaws-live-status-heartbeat",
        )
        self.heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self.heartbeat_stop.set()
        thread = self.heartbeat_thread
        if thread is not None:
            thread.join(timeout=2)
            self.heartbeat_thread = None

    def write(
        self,
        phase: str,
        exit_status: int | None = None,
        reason: str = "",
        provider_reason: str = "",
        retryable: bool | None = None,
        resume_available: bool | None = None,
        detail: str = "",
    ) -> None:
        with self.lock:
            if self.terminal and exit_status is None:
                return
            self.phase = phase
            if exit_status is not None:
                self.terminal = True
            now = time.time()
            payload: dict[str, object] = {
                "phase": phase,
                "started_at_epoch": self.started_at_epoch,
                "updated_at_epoch": now,
                "elapsed_s": round_duration(now - self.started_at_epoch),
                "debug_snapshot": timeout_debug_snapshot(
                    self.run_dir,
                    started_at_epoch=self.started_at_epoch,
                    captured_at_epoch=now,
                ),
            }
            if reason:
                payload["reason"] = reason
            if provider_reason:
                payload["provider_reason"] = provider_reason
            if retryable is not None:
                payload["retryable"] = retryable
            if resume_available is not None:
                payload["resume_available"] = resume_available
            if detail:
                payload["detail"] = detail
            payload.update(self.lease_status_fields())
            if exit_status is not None:
                payload["finished_at_epoch"] = now
                payload["exit_status"] = exit_status
            tmp_path = self.status_path.with_suffix(f"{self.status_path.suffix}.tmp")
            tmp_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            tmp_path.replace(self.status_path)

    def _heartbeat_loop(self) -> None:
        while not self.heartbeat_stop.wait(15.0):
            with self.lock:
                if self.terminal:
                    return
                phase = self.phase
            self.write(phase)
