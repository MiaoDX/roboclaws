from __future__ import annotations

from unittest.mock import Mock

from roboclaws.evals import showcase_process


def test_timeout_cleanup_kills_process_group_after_wrapper_exit(monkeypatch) -> None:
    process = Mock(pid=4312)
    process.poll.return_value = 0
    killpg = Mock()
    monkeypatch.setattr(showcase_process.os, "killpg", killpg)

    showcase_process._terminate_process_group(process)

    assert killpg.call_args_list == [
        ((4312, showcase_process.signal.SIGTERM),),
        ((4312, showcase_process.signal.SIGKILL),),
    ]
    process.wait.assert_not_called()
