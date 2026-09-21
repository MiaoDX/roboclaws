#!/usr/bin/env python3
"""Repair cache manifest entries left behind by interrupted MolmoSpaces setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from molmo_spaces.molmo_spaces_constants import DATA_TYPE_TO_SOURCE_TO_VERSION
from molmospaces_resources.manager import LOCAL_MANIFEST_NAME


def repair_cache(cache_root: Path) -> dict[str, Any]:
    """Remove unrecorded version paths so the manager can download them cleanly."""
    manifest_path = cache_root / LOCAL_MANIFEST_NAME
    manifest = _read_manifest(manifest_path)
    removed: list[str] = []
    for data_type, sources in DATA_TYPE_TO_SOURCE_TO_VERSION.items():
        for source, version in sources.items():
            target = cache_root / data_type / source / version
            if not target.exists():
                continue
            recorded = version in manifest.get(data_type, {}).get(source, [])
            if recorded:
                continue
            shutil.rmtree(target)
            removed.append(str(target))
    return {"cache_root": str(cache_root), "removed": removed}


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict) or any(
        not isinstance(sources, dict)
        or any(not isinstance(versions, list) for versions in sources.values())
        for sources in payload.values()
    ):
        raise ValueError(f"Invalid MolmoSpaces cache manifest: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(
            os.environ.get("MLSPACES_CACHE_DIR", "~/.cache/molmo-spaces-resources")
        ).expanduser(),
    )
    args = parser.parse_args()
    print(json.dumps(repair_cache(args.cache_root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
