#!/usr/bin/env python3
"""CLI adapter for package-owned operator-console preview production."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

from roboclaws.operator_console.scene_preview_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
