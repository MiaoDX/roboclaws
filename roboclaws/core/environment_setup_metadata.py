"""Private report metadata for public environment setup launch arguments."""

from __future__ import annotations

import json
import os
from typing import Any

from roboclaws.core.environment_setup import (
    ENVIRONMENT_SETUP_BASELINE,
    ENVIRONMENT_SETUP_OPTIONS,
    RELOCATION_SETUP_OPTIONS,
)
from roboclaws.core.json_sources import parse_json_object_text

ENVIRONMENT_SETUP_METADATA_ENV = "ROBOCLAWS_ENVIRONMENT_SETUP_JSON"


def environment_setup_metadata(
    *,
    setup: str,
    seed: str | int | None,
    relocation_count: str | int | None,
) -> dict[str, Any]:
    """Return private/report setup provenance from public launch arguments."""

    if setup not in ENVIRONMENT_SETUP_OPTIONS:
        raise ValueError(f"unsupported environment setup: {setup}")
    count = 0 if setup == ENVIRONMENT_SETUP_BASELINE else _nonnegative_int(relocation_count or 0)
    policy = setup.removeprefix("relocate-") if setup in RELOCATION_SETUP_OPTIONS else "none"
    return {
        "mode": setup,
        "seed": _optional_int(seed),
        "relocation_policy": policy,
        "relocation_count": count,
        "relocated_objects": [],
        "feeds_cleanup_scoring": setup in RELOCATION_SETUP_OPTIONS,
    }


def environment_setup_run_metadata(
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a run-result merge payload for private/report setup provenance."""

    if not metadata:
        return {}
    return {
        "environment_setup": dict(metadata),
        "private_evaluation": {
            "environment_setup": dict(metadata),
        },
    }


def environment_setup_metadata_json(
    *,
    setup: str,
    seed: str | int | None,
    relocation_count: str | int | None,
) -> str:
    """Serialize private setup provenance for child launch processes."""

    return json.dumps(
        environment_setup_metadata(
            setup=setup,
            seed=seed,
            relocation_count=relocation_count,
        ),
        sort_keys=True,
        separators=(",", ":"),
    )


def environment_setup_run_metadata_from_env(
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read setup provenance from the launch environment."""

    env_map = os.environ if env is None else env
    raw = str(env_map.get(ENVIRONMENT_SETUP_METADATA_ENV) or "").strip()
    if not raw:
        return {}
    payload = parse_json_object_text(raw, label=ENVIRONMENT_SETUP_METADATA_ENV)
    return environment_setup_run_metadata(payload)


def _optional_int(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value).strip())


def _nonnegative_int(value: str | int) -> int:
    parsed = int(str(value).strip())
    if parsed < 0:
        raise ValueError("relocation_count must be >= 0")
    return parsed
