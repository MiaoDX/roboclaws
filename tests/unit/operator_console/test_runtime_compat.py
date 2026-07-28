from __future__ import annotations

from unittest.mock import patch

import pytest

from roboclaws.operator_console.runtime_compat import pid_is_active


@pytest.mark.parametrize("state", ["Z", "X"])
def test_pid_is_active_rejects_dead_linux_process_states(state: str) -> None:
    with (
        patch("roboclaws.operator_console.runtime_compat.sys.platform", "linux"),
        patch(
            "roboclaws.operator_console.runtime_compat.Path.read_text",
            return_value=f"123 (worker) name) {state} 1 2 3",
        ),
        patch("roboclaws.operator_console.runtime_compat.os.kill") as kill,
    ):
        assert pid_is_active(123) is False

    kill.assert_not_called()


def test_pid_is_active_falls_back_when_proc_state_is_unavailable() -> None:
    with (
        patch("roboclaws.operator_console.runtime_compat.sys.platform", "darwin"),
        patch("roboclaws.operator_console.runtime_compat.os.kill") as kill,
    ):
        assert pid_is_active(123) is True

    kill.assert_called_once_with(123, 0)
