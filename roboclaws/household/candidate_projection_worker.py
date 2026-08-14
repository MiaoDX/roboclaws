"""One-request worker for an isolated MCP behavior candidate image."""

from __future__ import annotations

import json
import sys
from typing import Any

from roboclaws.household.candidate_projection_protocol import (
    PROJECTION_REQUEST_SCHEMA,
    PROJECTION_RESULT_SCHEMA,
    validate_candidate_public_payload,
)
from roboclaws.household.household_mcp_projection import (
    _compact_declare_visual_candidates_response,
    _compact_raw_fpv_mcp_observe_state,
)


def dispatch_candidate_projection(request: dict[str, Any]) -> dict[str, Any]:
    if set(request) != {"schema", "operation", "payload"}:
        raise ValueError("candidate projection request fields must be exact")
    if request.get("schema") != PROJECTION_REQUEST_SCHEMA:
        raise ValueError("candidate projection request schema mismatch")
    operation = request.get("operation")
    payload = request.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("candidate projection request payload must be an object")
    validate_candidate_public_payload(payload)
    if operation == "declare_visual_candidates":
        projected = _compact_declare_visual_candidates_response(payload)
    elif operation == "raw_fpv_observe_state":
        projected = _compact_raw_fpv_mcp_observe_state(payload)
    else:
        raise ValueError(f"unsupported candidate projection operation: {operation}")
    validate_candidate_public_payload(projected)
    return {
        "schema": PROJECTION_RESULT_SCHEMA,
        "operation": operation,
        "payload": projected,
    }


def main() -> int:
    raw = sys.stdin.buffer.readline(1_000_001)
    if not raw or len(raw) > 1_000_000:
        raise ValueError("candidate projection request must be one bounded JSON line")
    request = json.loads(raw)
    result = dispatch_candidate_projection(request)
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
