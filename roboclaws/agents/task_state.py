"""Privacy-bounded task snapshots and atomic checkpoints."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class SnapshotError(ValueError):
    """Raised when a snapshot or checkpoint violates its contract."""


@dataclasses.dataclass(frozen=True)
class EvidenceRef:
    ref: str
    digest: str
    kind: str = "artifact"


@dataclasses.dataclass(frozen=True)
class Observation:
    value: Any
    observed_at: str
    provenance: str
    stale: bool = False

    def public(self) -> dict[str, Any]:
        value = self.value if isinstance(self.value, (str, int, float, bool, type(None))) else None
        return {
            "value": value,
            "observed_at": self.observed_at,
            "provenance": self.provenance,
            "stale": self.stale,
        }


@dataclasses.dataclass
class TaskSnapshot:
    task: str
    intent: str
    pose: dict[str, Any] | None = None
    waypoint: dict[str, Any] | None = None
    objects: dict[str, Observation] = dataclasses.field(default_factory=dict)
    action_outcomes: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    safety: dict[str, Any] = dataclasses.field(default_factory=dict)
    completion: dict[str, Any] = dataclasses.field(default_factory=dict)
    evidence: list[EvidenceRef] = dataclasses.field(default_factory=list)
    revision: int = 0

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise SnapshotError("revision must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "intent": self.intent,
            "pose": self.pose,
            "waypoint": self.waypoint,
            "objects": {k: v.public() for k, v in self.objects.items()},
            "action_outcomes": self.action_outcomes,
            "safety": self.safety,
            "completion": self.completion,
            "evidence": [dataclasses.asdict(e) for e in self.evidence],
            "revision": self.revision,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSnapshot":
        required = {"task", "intent", "revision"}
        if not required <= data.keys():
            raise SnapshotError(f"missing fields: {sorted(required - data.keys())}")
        objects = {k: Observation(**v) for k, v in data.get("objects", {}).items()}
        evidence = [EvidenceRef(**e) for e in data.get("evidence", [])]
        fields = (
            "task",
            "intent",
            "pose",
            "waypoint",
            "action_outcomes",
            "safety",
            "completion",
            "revision",
        )
        return cls(objects=objects, evidence=evidence, **{k: data.get(k) for k in fields})

    @classmethod
    def from_json(cls, text: str) -> "TaskSnapshot":
        try:
            return cls.from_dict(json.loads(text))
        except (json.JSONDecodeError, TypeError) as exc:
            raise SnapshotError("invalid snapshot JSON") from exc


@dataclasses.dataclass(frozen=True)
class Checkpoint:
    snapshot: TaskSnapshot
    schema_version: int = 1

    def to_json(self) -> str:
        return json.dumps(
            {"schema_version": self.schema_version, "snapshot": self.snapshot.to_dict()},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str, *, previous_revision: int | None = None) -> "Checkpoint":
        try:
            payload = json.loads(text)
            checkpoint = cls(TaskSnapshot.from_dict(payload["snapshot"]), payload["schema_version"])
        except (KeyError, TypeError, json.JSONDecodeError, SnapshotError) as exc:
            raise SnapshotError("invalid checkpoint") from exc
        if previous_revision is not None and checkpoint.snapshot.revision <= previous_revision:
            raise SnapshotError("checkpoint revision is not monotonic")
        return checkpoint


def atomic_write_checkpoint(path: str | Path, checkpoint: Checkpoint) -> None:
    """Write a checkpoint durably, replacing the destination only on success."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(checkpoint.to_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest_payload(value: Any) -> str:
    """Return a stable digest for evidence without retaining its payload."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
