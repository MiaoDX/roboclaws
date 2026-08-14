from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

COMPLETION_SNAPSHOT_SCHEMA = "household_completion_snapshot_v1"


def completion_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in snapshot.items() if key != "digest"}
    encoded = json.dumps(
        unsigned,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
