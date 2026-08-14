from __future__ import annotations

import os

import pytest

from roboclaws.agents.visual_backend_slots import (
    VisualBackendSlotError,
    acquire_visual_backend_slot,
    list_visual_backend_slots,
    molmo_visual_slot_limit,
)


def test_default_visual_backend_slot_limit_is_one(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", raising=False)

    first = acquire_visual_backend_slot(
        repo_root=tmp_path,
        run_id="run-a",
        pid=os.getpid(),
        backend="molmospaces_subprocess",
        port=18788,
        output_dir=tmp_path / "run-a",
        status_path=tmp_path / "run-a" / "live_status.json",
        owner="test",
    )
    with pytest.raises(VisualBackendSlotError) as exc_info:
        acquire_visual_backend_slot(
            repo_root=tmp_path,
            run_id="run-b",
            pid=os.getpid(),
            backend="molmospaces_subprocess",
            port=18790,
            output_dir=tmp_path / "run-b",
            status_path=tmp_path / "run-b" / "live_status.json",
            owner="test",
        )

    assert "all 1 MolmoSpaces visual backend slot(s) are held" in str(exc_info.value)
    assert exc_info.value.active_slots[0]["run_id"] == "run-a"
    first.release()


def test_explicit_two_slot_limit_allows_two_and_blocks_third(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", "2")

    first = acquire_visual_backend_slot(
        repo_root=tmp_path,
        run_id="run-a",
        pid=os.getpid(),
        backend="molmospaces_subprocess",
        port=18788,
        output_dir=tmp_path / "run-a",
        status_path=tmp_path / "run-a" / "live_status.json",
        owner="test",
    )
    second = acquire_visual_backend_slot(
        repo_root=tmp_path,
        run_id="run-b",
        pid=os.getpid(),
        backend="molmospaces_subprocess",
        port=18790,
        output_dir=tmp_path / "run-b",
        status_path=tmp_path / "run-b" / "live_status.json",
        owner="test",
    )

    with pytest.raises(VisualBackendSlotError) as exc_info:
        acquire_visual_backend_slot(
            repo_root=tmp_path,
            run_id="run-c",
            pid=os.getpid(),
            backend="molmospaces_subprocess",
            port=18792,
            output_dir=tmp_path / "run-c",
            status_path=tmp_path / "run-c" / "live_status.json",
            owner="test",
        )

    assert {slot["run_id"] for slot in exc_info.value.active_slots} == {"run-a", "run-b"}
    assert first.state.slot_id == 1
    assert second.state.slot_id == 2
    first.release()
    second.release()


@pytest.mark.parametrize("raw", ["0", "-1", "abc"])
def test_invalid_visual_backend_slot_limit_env_fails_aloud(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", raw)

    with pytest.raises(VisualBackendSlotError) as exc_info:
        molmo_visual_slot_limit()

    assert "ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS must be a positive integer" in str(exc_info.value)
    assert repr(raw) in str(exc_info.value)


@pytest.mark.parametrize("max_slots", [0, -1, False])
def test_invalid_explicit_visual_backend_slot_limit_fails_aloud(tmp_path, max_slots: int) -> None:
    with pytest.raises(VisualBackendSlotError) as exc_info:
        list_visual_backend_slots(repo_root=tmp_path, max_slots=max_slots)

    assert f"max_slots must be a positive integer, got {max_slots!r}" in str(exc_info.value)


def test_stale_visual_backend_slot_is_released_only_when_pid_is_gone(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", "1")
    stale_pid = 999_999_999
    stale = acquire_visual_backend_slot(
        repo_root=tmp_path,
        run_id="stale-run",
        pid=stale_pid,
        backend="molmospaces_subprocess",
        port=18788,
        output_dir=tmp_path / "stale-run",
        status_path=tmp_path / "stale-run" / "live_status.json",
        owner="test",
    )
    assert stale.state.path.exists()

    replacement = acquire_visual_backend_slot(
        repo_root=tmp_path,
        run_id="fresh-run",
        pid=os.getpid(),
        backend="molmospaces_subprocess",
        port=18790,
        output_dir=tmp_path / "fresh-run",
        status_path=tmp_path / "fresh-run" / "live_status.json",
        owner="test",
    )

    states = list_visual_backend_slots(repo_root=tmp_path)
    assert states[0].run_id == "fresh-run"
    assert replacement.state.slot_id == stale.state.slot_id
    replacement.release()


@pytest.mark.parametrize("source", ["{", "[]"])
def test_corrupt_visual_backend_slot_source_is_held(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", "1")
    slot_path = tmp_path / "output" / "molmo" / "visual-backend-slots" / "slot-1.json"
    slot_path.parent.mkdir(parents=True)
    slot_path.write_text(source, encoding="utf-8")

    states = list_visual_backend_slots(repo_root=tmp_path)
    assert states[0].held is True
    assert states[0].stale is False
    assert states[0].run_id == ""

    with pytest.raises(VisualBackendSlotError) as exc_info:
        acquire_visual_backend_slot(
            repo_root=tmp_path,
            run_id="fresh-run",
            pid=os.getpid(),
            backend="molmospaces_subprocess",
            port=18790,
            output_dir=tmp_path / "fresh-run",
            status_path=tmp_path / "fresh-run" / "live_status.json",
            owner="test",
        )

    assert "all 1 MolmoSpaces visual backend slot(s) are held" in str(exc_info.value)
