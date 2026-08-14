from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.contract.agibot.agibot_map_context_scripts_support import (
    RAW_FPV_CHECK_PATH,
    _FakeAgibotGDK,
    _FakeCameraFactory,
    _load_module,
    _require_raw_fpv_checker,
)


def test_raw_fpv_checker_records_head_color_status_and_no_motion(
    monkeypatch, tmp_path: Path
) -> None:
    _require_raw_fpv_checker()
    checker = _load_module(RAW_FPV_CHECK_PATH, "check_raw_fpv_status_mocked_success")
    fake_gdk = _FakeAgibotGDK(camera_factory=_FakeCameraFactory())

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(checker, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(checker, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(checker.time, "sleep", lambda seconds: None)

    rc = checker.main_from_args(
        [
            "--robot-host",
            "127.0.0.1",
            "--output-dir",
            str(tmp_path),
            "--cameras",
            "head_color",
        ]
    )

    status = json.loads((tmp_path / "raw_fpv_status.json").read_text(encoding="utf-8"))
    head = status["checks"][0]
    assert rc == 0
    assert status["raw_fpv_status"] == "head_color_available"
    assert status["read_only"] is True
    assert status["navigation_submission"] is False
    assert status["motion_or_write_calls_used"] == []
    assert head["ok"] is True
    assert head["camera"] == "head_color"
    assert head["shape"] == [640, 400]
    assert head["fps"] == 30.0
    assert (tmp_path / "head_color_latest.jpg").read_bytes().startswith(b"\xff\xd8")
    assert fake_gdk.gdk_release_calls == 1


def test_raw_fpv_checker_fails_loudly_on_missing_numpy(monkeypatch, tmp_path: Path) -> None:
    _require_raw_fpv_checker()
    checker = _load_module(RAW_FPV_CHECK_PATH, "check_raw_fpv_status_mocked_numpy")
    fake_gdk = _FakeAgibotGDK(camera_factory=_FakeCameraFactory(missing_numpy=True))

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(checker, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(checker, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(checker.time, "sleep", lambda seconds: None)

    with pytest.raises(ModuleNotFoundError, match="numpy"):
        checker.main_from_args(
            [
                "--robot-host",
                "127.0.0.1",
                "--output-dir",
                str(tmp_path),
                "--cameras",
                "head_color",
            ]
        )

    assert fake_gdk.gdk_release_calls == 1
