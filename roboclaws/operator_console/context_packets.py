"""Public context-packet sanitizing for linked operator runs."""

from __future__ import annotations

import json
from typing import Any

PRIVATE_CONTEXT_TERMS = (
    "generated_mess_set",
    "generated_mess_truth",
    "acceptable_destination_sets",
    "acceptable_destination",
    "private_manifest",
    "target_receptacle_id",
    "private_target_truth",
    "global_movable_object_inventory",
    "private_scorer_truth",
    "scorer_truth",
)


def sanitize_operator_context_packet(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a public follow-up/resume context packet without private terms."""

    if not payload:
        return {}
    return strip_private_payload(dict(payload))


def context_packet_json(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def strip_private_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for term in PRIVATE_CONTEXT_TERMS:
        text = text.replace(term, "[redacted_private_field]")
    try:
        redacted = json.loads(text)
    except json.JSONDecodeError:
        return payload
    return redacted if isinstance(redacted, dict) else payload
