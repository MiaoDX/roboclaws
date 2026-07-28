from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.drivers.household_live import (
    acquire_household_live_run_lease,
)
from roboclaws.household.visual_backend_slots import MOLMOSPACES_SUBPROCESS_BACKEND


def test_household_live_run_lease_writes_file_lock_payload(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_dir = tmp_path / "runs" / "seed-7"
    run_dir.mkdir(parents=True)
    lock_path = tmp_path / "live.lock"
    status_path = run_dir / "live_status.json"

    lease = acquire_household_live_run_lease(
        backend="isaaclab_subprocess",
        repo_root=repo_root,
        run_dir=run_dir,
        status_path=status_path,
        lock_path=lock_path,
        port=18788,
        owner="test-live",
        started_at_epoch=123.5,
        extra_lock_payload={"runtime": "test-runtime"},
    )
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["run_dir"] == str(run_dir)
        assert payload["status_path"] == str(status_path)
        assert payload["started_at_epoch"] == 123.5
        assert payload["runtime"] == "test-runtime"
        assert lease.status_fields() == {}
    finally:
        if lease.lock_file is not None:
            lease.lock_file.close()


def test_household_live_run_lease_exposes_visual_slot_status(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_dir = tmp_path / "runs" / "seed-7"
    run_dir.mkdir(parents=True)
    status_path = run_dir / "live_status.json"

    lease = acquire_household_live_run_lease(
        backend=MOLMOSPACES_SUBPROCESS_BACKEND,
        repo_root=repo_root,
        run_dir=run_dir,
        status_path=status_path,
        lock_path=tmp_path / "unused.lock",
        port=18788,
        owner="test-live",
        started_at_epoch=123.5,
    )
    try:
        payload = lease.status_fields()["visual_backend_slot"]
        assert payload["held"] is True
        assert payload["run_id"] == "runs/seed-7"
        assert payload["backend"] == MOLMOSPACES_SUBPROCESS_BACKEND
        assert payload["port"] == 18788
        assert payload["owner"] == "test-live"
    finally:
        lease.release_visual_slot()

    assert lease.status_fields() == {}


def test_household_live_run_lease_rejects_invalid_visual_slot_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_dir = tmp_path / "runs" / "seed-7"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS", "0")

    with pytest.raises(RuntimeError) as exc_info:
        acquire_household_live_run_lease(
            backend=MOLMOSPACES_SUBPROCESS_BACKEND,
            repo_root=repo_root,
            run_dir=run_dir,
            status_path=run_dir / "live_status.json",
            lock_path=tmp_path / "unused.lock",
            port=18788,
            owner="test-live",
            started_at_epoch=123.5,
        )

    assert "invalid MolmoSpaces visual backend slot config" in str(exc_info.value)
    assert "ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS must be a positive integer" in str(exc_info.value)
