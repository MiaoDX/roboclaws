"""Managed lifecycle for the optional local visual-grounding process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from roboclaws.household.visual_grounding import (
    DEFAULT_VISUAL_GROUNDING_BASE_URL,
    DEFAULT_VISUAL_GROUNDING_TIMEOUT_S,
)
from roboclaws.household.visual_grounding_sidecar.readiness import (
    check_visual_grounding_readiness,
)


class ManagedVisualGroundingProcess:
    """Ensure a real local sidecar is ready and stop only a process we started."""

    def __init__(
        self,
        *,
        pipeline_id: str,
        timeout_s: float | None = None,
        autostart: bool | None = None,
        startup_timeout_s: float = 15.0,
        base_url: str | None = None,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.timeout_s = (
            timeout_s
            if timeout_s is not None
            else float(
                os.environ.get("VISUAL_GROUNDING_TIMEOUT_S", DEFAULT_VISUAL_GROUNDING_TIMEOUT_S)
            )
        )
        self.autostart = _autostart_enabled() if autostart is None else autostart
        self.startup_timeout_s = startup_timeout_s
        self.base_url = base_url or os.environ.get(
            "VISUAL_GROUNDING_BASE_URL",
            DEFAULT_VISUAL_GROUNDING_BASE_URL,
        )
        self.process: subprocess.Popen[bytes] | None = None
        self.log_metadata: dict[str, object] | None = None
        self.last_readiness: dict[str, object] | None = None

    def ensure_ready(self, run_dir: Path) -> dict[str, object]:
        run_dir.mkdir(parents=True, exist_ok=True)
        result = self._probe()
        self._record_readiness(run_dir, result)
        if result["ok"]:
            return result
        if result.get("reason") != "connection_error" or not self.autostart:
            raise RuntimeError(_readiness_error(result))
        result = self._start(run_dir)
        self._record_readiness(run_dir, result)
        if not result["ok"]:
            self.close()
            raise RuntimeError(_readiness_error(result))
        return result

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def __enter__(self) -> ManagedVisualGroundingProcess:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _probe(self) -> dict[str, object]:
        return check_visual_grounding_readiness(
            pipeline_id=self.pipeline_id,
            base_url=self.base_url,
            timeout_s=self.timeout_s,
            require_real_adapter=True,
        )

    def _record_readiness(self, run_dir: Path, result: dict[str, object]) -> None:
        self.last_readiness = result
        (run_dir / "visual_grounding_readiness.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _start(self, run_dir: Path) -> dict[str, object]:
        host, port = _local_endpoint(self.base_url)
        python = _sidecar_python()
        log_dir = run_dir / "visual_grounding_sidecar"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "stdout.log"
        stderr_path = log_dir / "stderr.log"
        command = [
            str(python),
            "-m",
            "roboclaws.household.visual_grounding_sidecar.service",
            "--host",
            host,
            "--port",
            str(port),
            "--pipeline",
            "real-router",
            "--adapter-mode",
            "real",
        ]
        self.log_metadata = {
            "base_url": self.base_url,
            "command": command,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }
        stdout = stdout_path.open("ab")
        stderr = stderr_path.open("ab")
        try:
            self.process = subprocess.Popen(
                command,
                cwd=_repo_root(),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        finally:
            stdout.close()
            stderr.close()
        deadline = time.monotonic() + self.startup_timeout_s
        while True:
            assert self.process is not None
            result = self._probe()
            self.last_readiness = result
            if result["ok"] or result.get("reason") != "connection_error":
                return result
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"failed to auto-start visual grounding sidecar; see {stderr_path}"
                )
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                return result
            time.sleep(min(0.2, remaining_s))


def _autostart_enabled() -> bool:
    return os.environ.get("ROBOCLAWS_AUTOSTART_VISUAL_GROUNDING_SIDECAR", "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _local_endpoint(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.scheme not in {"", "http"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "visual grounding sidecar auto-start requires a local HTTP VISUAL_GROUNDING_BASE_URL"
        )
    return host, parsed.port or 80


def _sidecar_python() -> Path:
    repo_root = _repo_root()
    for candidate in (
        repo_root / ".venv-visual-grounding/bin/python",
        repo_root / ".venv/bin/python",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return Path(sys.executable)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _readiness_error(result: dict[str, object]) -> str:
    return (
        "visual grounding sidecar is not ready for product runs: "
        f"{result.get('reason')}. {result.get('message')}"
    )
