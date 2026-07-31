"""Operator-visible state source error contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from roboclaws.operator_console.state_presentation import _artifact_href


@dataclass(frozen=True)
class JsonSourceError:
    path: Path
    label: str
    reason: str

    def to_payload(self, root: Path) -> dict[str, str]:
        return {
            "label": self.label,
            "path": str(self.path),
            "href": _artifact_href(root, self.path) if self.path.exists() else "",
            "reason": self.reason,
        }
