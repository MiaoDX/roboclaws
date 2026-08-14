#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.evals.visual_grounding_benchmark.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
