from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household.visual_grounding_sidecar import process as process_module
from roboclaws.household.visual_grounding_sidecar.process import ManagedVisualGroundingProcess


def _readiness(*, ok: bool, reason: str = "") -> dict[str, object]:
    return {
        "schema": "visual_grounding_readiness_v1",
        "ok": ok,
        "pipeline_id": "grounding-dino",
        "base_url": "http://127.0.0.1:18880",
        "require_real_adapter": True,
        "reason": reason,
        "message": "" if ok else reason,
    }


def test_managed_sidecar_returns_and_records_strict_http_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_readiness(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return _readiness(ok=True)

    monkeypatch.setattr(process_module, "check_visual_grounding_readiness", fake_readiness)
    sidecar = ManagedVisualGroundingProcess(
        pipeline_id="grounding-dino",
        timeout_s=3.5,
        autostart=False,
        base_url="http://127.0.0.1:18880",
    )

    result = sidecar.ensure_ready(tmp_path)

    assert result["ok"] is True
    assert sidecar.last_readiness == result
    assert sidecar.log_metadata is None
    assert calls == [
        {
            "pipeline_id": "grounding-dino",
            "base_url": "http://127.0.0.1:18880",
            "timeout_s": 3.5,
            "require_real_adapter": True,
        }
    ]
    assert (
        json.loads((tmp_path / "visual_grounding_readiness.json").read_text(encoding="utf-8"))
        == result
    )


def test_managed_sidecar_autostart_exposes_logs_and_final_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(
        [
            _readiness(ok=False, reason="connection_error"),
            _readiness(ok=False, reason="connection_error"),
            _readiness(ok=True),
        ]
    )
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: float) -> int:
            return 0

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        popen_calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(
        process_module, "check_visual_grounding_readiness", lambda **_kw: next(results)
    )
    monkeypatch.setattr(process_module, "_sidecar_python", lambda: Path("/sidecar/python"))
    monkeypatch.setattr(process_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(process_module.time, "sleep", lambda _seconds: None)
    sidecar = ManagedVisualGroundingProcess(
        pipeline_id="grounding-dino",
        autostart=True,
        startup_timeout_s=2.0,
        base_url="http://127.0.0.1:18880",
    )

    result = sidecar.ensure_ready(tmp_path)

    assert result["ok"] is True
    assert sidecar.last_readiness == result
    assert sidecar.log_metadata is not None
    assert sidecar.log_metadata["base_url"] == "http://127.0.0.1:18880"
    assert sidecar.log_metadata["command"] == popen_calls[0][0]
    assert sidecar.log_metadata["stdout"] == str(
        tmp_path / "visual_grounding_sidecar" / "stdout.log"
    )
    assert sidecar.log_metadata["stderr"] == str(
        tmp_path / "visual_grounding_sidecar" / "stderr.log"
    )
    assert popen_calls[0][0][-4:] == [
        "--pipeline",
        "real-router",
        "--adapter-mode",
        "real",
    ]
    assert popen_calls[0][1]["cwd"] == process_module._repo_root()


def test_managed_sidecar_respects_explicit_zero_startup_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes = 0

    def fake_readiness(**_kwargs: object) -> dict[str, object]:
        nonlocal probes
        probes += 1
        return _readiness(ok=False, reason="connection_error")

    class FakeProcess:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            return 0

    process = FakeProcess()
    monkeypatch.setattr(process_module, "check_visual_grounding_readiness", fake_readiness)
    monkeypatch.setattr(process_module, "_sidecar_python", lambda: Path("/sidecar/python"))
    monkeypatch.setattr(process_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    sidecar = ManagedVisualGroundingProcess(
        pipeline_id="grounding-dino",
        autostart=True,
        startup_timeout_s=0.0,
        base_url="http://127.0.0.1:18880",
    )

    with pytest.raises(RuntimeError, match="connection_error"):
        sidecar.ensure_ready(tmp_path)

    assert probes == 2
    assert process.terminated is True
    assert sidecar.last_readiness == _readiness(ok=False, reason="connection_error")
