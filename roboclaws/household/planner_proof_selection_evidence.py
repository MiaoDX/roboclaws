from __future__ import annotations

from typing import Any


def prior_result_blocker_fields(result: dict[str, Any]) -> dict[str, str]:
    fields = {}
    kind = str(result.get("task_feasibility_blocker_kind") or "")
    summary = str(result.get("task_feasibility_blocker_summary") or "")
    if kind:
        fields["prior_task_feasibility_blocker_kind"] = kind
    if summary:
        fields["prior_task_feasibility_blocker_summary"] = summary
    return fields
