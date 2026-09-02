from pathlib import Path

import pytest

from roboclaws.agents.task_state import (
    Checkpoint,
    EvidenceRef,
    Observation,
    SnapshotError,
    TaskSnapshot,
    atomic_write_checkpoint,
)


def test_snapshot_round_trip_and_privacy() -> None:
    snapshot = TaskSnapshot(
        task="tid",
        intent="clean",
        pose={"x": 1},
        waypoint={"name": "sink"},
        objects={"cup": Observation("red", "now", "camera", stale=True)},
        action_outcomes=[{"action": "grasp", "ok": True}],
        safety={"estop": True},
        completion={"done": False},
        evidence=[EvidenceRef("run/a", "abc")],
        revision=2,
    )
    restored = TaskSnapshot.from_json(snapshot.to_json())
    assert restored == snapshot
    assert "prompt" not in snapshot.to_json() and "credential" not in snapshot.to_json()


def test_non_monotonic_rejected_and_atomic_write_preserves_previous(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    first = Checkpoint(TaskSnapshot("t", "i", revision=1))
    atomic_write_checkpoint(path, first)
    with pytest.raises(SnapshotError):
        Checkpoint.from_json(first.to_json(), previous_revision=1)
    assert Checkpoint.from_json(path.read_text()).snapshot.revision == 1
