from __future__ import annotations

import sys
from pathlib import Path

import pytest

from roboclaws.launch import executor


def test_spawn_launch_plan_flushes_child_output_before_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    def fake_execute_launch_plan(_plan: object) -> int:
        print("child stdout without newline", end="")
        print("child stderr without newline", end="", file=sys.stderr)
        return 7

    monkeypatch.setattr(executor, "execute_launch_plan", fake_execute_launch_plan)
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"

    with (
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
        capfd.disabled(),
    ):
        process = executor.spawn_launch_plan(
            object(),  # type: ignore[arg-type]
            cwd=tmp_path,
            env={},
            stdout=stdout,
            stderr=stderr,
        )
        assert process.wait(timeout=5.0) == 7

    assert stdout_path.read_text(encoding="utf-8") == "child stdout without newline"
    assert stderr_path.read_text(encoding="utf-8") == "child stderr without newline"
