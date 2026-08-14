"""Trusted stdio boundary for isolated candidate public projections."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

PROJECTION_REQUEST_SCHEMA = "candidate_projection_request_v1"
PROJECTION_RESULT_SCHEMA = "candidate_projection_result_v1"
PROJECTION_WORKER_COMMAND_ENV = "ROBOCLAWS_CANDIDATE_PROJECTION_WORKER_COMMAND"
_OPERATIONS = frozenset({"declare_visual_candidates", "raw_fpv_observe_state"})
_FORBIDDEN_KEY_PARTS = (
    "acceptable_destination",
    "api_key",
    "credential",
    "generated_mess",
    "grader",
    "holdout",
    "private_goal",
    "private_truth",
    "provider_key",
    "scenario_secret",
    "secret",
    "token_value",
)
_MAX_PAYLOAD_BYTES = 1_000_000


def project_candidate_public_response(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    command_raw = os.environ.get(PROJECTION_WORKER_COMMAND_ENV, "")
    if not command_raw:
        return payload
    if operation not in _OPERATIONS:
        raise ValueError(f"unsupported candidate projection operation: {operation}")
    validate_candidate_public_payload(payload)
    command = _load_worker_command(command_raw)
    request = {
        "schema": PROJECTION_REQUEST_SCHEMA,
        "operation": operation,
        "payload": payload,
    }
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n"
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("candidate projection request exceeds byte limit")
    completed = subprocess.run(
        command,
        input=encoded,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
        env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"candidate projection worker failed with exit code {completed.returncode}"
        )
    if len(completed.stdout.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("candidate projection result exceeds byte limit")
    return _load_projection_result(completed.stdout, operation=operation)


def _load_worker_command(raw: str) -> list[str]:
    command = json.loads(raw)
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(arg, str) for arg in command)
    ):
        raise ValueError("candidate projection worker command must be a JSON string list")
    if len(command) > 64:
        raise ValueError("candidate projection worker command exceeds argv limit")
    return command


def _load_projection_result(raw: str, *, operation: str) -> dict[str, Any]:
    result = json.loads(raw)
    if not isinstance(result, dict) or set(result) != {"schema", "operation", "payload"}:
        raise ValueError("candidate projection result fields must be exact")
    if result.get("schema") != PROJECTION_RESULT_SCHEMA or result.get("operation") != operation:
        raise ValueError("candidate projection result identity mismatch")
    projected = result.get("payload")
    if not isinstance(projected, dict):
        raise ValueError("candidate projection result payload must be an object")
    validate_candidate_public_payload(projected)
    return projected


def validate_candidate_public_payload(payload: Any, *, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if not isinstance(key, str):
                raise ValueError("candidate public projection keys must be strings")
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                raise ValueError(f"candidate projection contains forbidden key at {path}.{key}")
            validate_candidate_public_payload(value, path=f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            validate_candidate_public_payload(value, path=f"{path}[{index}]")
        return
    if payload is None or isinstance(payload, (bool, float, int, str)):
        return
    raise ValueError(f"candidate projection contains unsupported value at {path}")
