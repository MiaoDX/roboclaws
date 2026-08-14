from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.household import worker_runner


def test_worker_command_args_include_module_state_and_command(tmp_path: Path) -> None:
    command = worker_runner.worker_command_args(
        python_executable=Path("/runtime/python"),
        worker_module="roboclaws.backends.isaaclab.worker",
        state_path=tmp_path / "state.json",
        command="init",
        args=("--seed", "7"),
    )

    assert command == [
        "/runtime/python",
        "-m",
        "roboclaws.backends.isaaclab.worker",
        "--state-path",
        str(tmp_path / "state.json"),
        "init",
        "--seed",
        "7",
    ]


def test_parse_last_json_object_tolerates_worker_stdout_noise() -> None:
    payload = worker_runner.parse_last_json_object(
        'loading assets...\n{"ok": true, "tool": "init"}\n',
        worker_name="Test",
    )

    assert payload == {"ok": True, "tool": "init"}


def test_parse_last_json_object_tolerates_bracketed_worker_logs() -> None:
    payload = worker_runner.parse_last_json_object(
        'loading assets...\n{"ok": true, "tool": "init"}\n[2026-06-21 10:00:00] finished\n',
        worker_name="Test",
    )

    assert payload == {"ok": True, "tool": "init"}


def test_parse_last_json_object_rejects_malformed_structured_stdout_row() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"Test worker stdout row source must contain valid JSON object: stdout:3",
    ):
        worker_runner.parse_last_json_object(
            'loading assets...\n{"ok": true}\n{bad json\n',
            worker_name="Test",
        )


def test_parse_last_json_object_rejects_non_object_structured_stdout_row() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"Test worker stdout row source must contain a JSON object: stdout:2",
    ):
        worker_runner.parse_last_json_object(
            'loading assets...\n["not", "a", "worker", "packet"]\n',
            worker_name="Test",
        )


def test_run_json_worker_once_reports_missing_runtime(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Test Python runtime is missing"):
        worker_runner.run_json_worker_once(
            worker_name="Test",
            python_executable=tmp_path / "missing-python",
            missing_runtime_hint="Set TEST_PYTHON.",
            worker_module="test.worker",
            state_path=tmp_path / "state.json",
            command="init",
            args=(),
            env={},
            timeout_s=1.0,
        )


def test_run_json_worker_once_uses_env_timeout_and_parses_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(returncode=0, stdout='noise\n{"ok": true}\n', stderr="")

    monkeypatch.setattr(worker_runner.subprocess, "run", fake_run)

    payload = worker_runner.run_json_worker_once(
        worker_name="Test",
        python_executable=python,
        missing_runtime_hint="Set TEST_PYTHON.",
        worker_module="test.worker",
        state_path=tmp_path / "state.json",
        command="observe",
        args=("--x", "1"),
        env={"A": "B"},
        timeout_s=2.5,
    )

    assert payload == {"ok": True}
    assert captured["command"] == [
        str(python),
        "-m",
        "test.worker",
        "--state-path",
        str(tmp_path / "state.json"),
        "observe",
        "--x",
        "1",
    ]
    assert captured["env"] == {"A": "B"}
    assert captured["timeout"] == 2.5


def test_run_json_worker_once_reports_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(worker_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Test subprocess worker timed out"):
        worker_runner.run_json_worker_once(
            worker_name="Test",
            python_executable=python,
            missing_runtime_hint="Set TEST_PYTHON.",
            worker_module="test.worker",
            state_path=tmp_path / "state.json",
            command="snapshot",
            args=(),
            env={},
            timeout_s=3.0,
        )


def test_run_json_worker_once_reports_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=12, stdout="", stderr="boom")

    monkeypatch.setattr(worker_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Test subprocess worker failed"):
        worker_runner.run_json_worker_once(
            worker_name="Test",
            python_executable=python,
            missing_runtime_hint="Set TEST_PYTHON.",
            worker_module="test.worker",
            state_path=tmp_path / "state.json",
            command="init",
            args=(),
            env={},
            timeout_s=3.0,
        )


def test_worker_timeout_uses_override_or_command_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_WORKER_TIMEOUT_S", "9.5")

    assert (
        worker_runner.worker_timeout_s(
            command="snapshot",
            override_env_var="TEST_WORKER_TIMEOUT_S",
            command_timeouts={"snapshot": 4.0},
            default_timeout_s=1.0,
        )
        == 9.5
    )

    monkeypatch.delenv("TEST_WORKER_TIMEOUT_S")
    assert (
        worker_runner.worker_timeout_s(
            command="snapshot",
            override_env_var="TEST_WORKER_TIMEOUT_S",
            command_timeouts={"snapshot": 4.0},
            default_timeout_s=1.0,
        )
        == 4.0
    )
    assert (
        worker_runner.worker_timeout_s(
            command="observe",
            override_env_var="TEST_WORKER_TIMEOUT_S",
            command_timeouts={"snapshot": 4.0},
            default_timeout_s=1.0,
        )
        == 1.0
    )


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_worker_timeout_rejects_invalid_env_override(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("TEST_WORKER_TIMEOUT_S", value)

    with pytest.raises(
        ValueError,
        match=r"TEST_WORKER_TIMEOUT_S must be a positive finite number of seconds",
    ):
        worker_runner.worker_timeout_s(
            command="snapshot",
            override_env_var="TEST_WORKER_TIMEOUT_S",
            command_timeouts={"snapshot": 4.0},
            default_timeout_s=1.0,
        )


def test_worker_env_applies_defaults_and_removes_host_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DROP_ME", "host")
    monkeypatch.setenv("KEEP_ME", "host")
    monkeypatch.delenv("DEFAULT_ME", raising=False)

    env = worker_runner.worker_env(
        defaults={"KEEP_ME": "default", "DEFAULT_ME": "value"},
        remove=("DROP_ME",),
    )

    assert "DROP_ME" not in env
    assert env["KEEP_ME"] == "host"
    assert env["DEFAULT_ME"] == "value"
