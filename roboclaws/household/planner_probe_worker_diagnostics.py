from __future__ import annotations

import argparse
import json
import time
from typing import Any

from roboclaws.household import planner_probe_runtime_diagnostics as probe_runtime
from roboclaws.household import planner_probe_sampler_contract as probe_sampler

_WORKER_EVENT_STARTED_AT = time.monotonic()
_CUDA_MEMORY_SNAPSHOTS: list[dict[str, Any]] = []
_WORKER_EXCEPTION_CONTEXT: dict[str, Any] = {}


def _emit_worker_event(event: str, **payload: Any) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "elapsed_s": round(time.monotonic() - _WORKER_EVENT_STARTED_AT, 6),
                **payload,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _record_worker_exception_context(**payload: Any) -> None:
    for key, value in payload.items():
        if value is not None:
            _WORKER_EXCEPTION_CONTEXT[key] = value


def _worker_exception_probe_context(args: argparse.Namespace) -> dict[str, Any]:
    context = {
        "cleanup_task_config": _WORKER_EXCEPTION_CONTEXT.get("cleanup_task_config")
        or probe_sampler.cleanup_task_config_request_from_args(args),
        "task_sampler_robot_placement_profile": _WORKER_EXCEPTION_CONTEXT.get(
            "task_sampler_robot_placement_profile"
        )
        or probe_sampler.task_sampler_robot_placement_profile_request_from_args(args),
        "cleanup_task_sampler_adapter": _WORKER_EXCEPTION_CONTEXT.get(
            "cleanup_task_sampler_adapter"
        )
        or {},
        "requested_cleanup_primitive_binding": _WORKER_EXCEPTION_CONTEXT.get(
            "requested_cleanup_primitive_binding"
        )
        or probe_sampler.requested_cleanup_primitive_binding(args),
        "task_sampler_failure_diagnostics": _WORKER_EXCEPTION_CONTEXT.get(
            "task_sampler_failure_diagnostics"
        )
        or {},
        "image_artifacts": _WORKER_EXCEPTION_CONTEXT.get("image_artifacts") or {},
    }
    for key in (
        "curobo_memory_profile",
        "sampled_task_binding",
        "cleanup_primitive_binding",
        "cleanup_primitive_binding_blockers",
        "policy_exception_context",
    ):
        if key in _WORKER_EXCEPTION_CONTEXT:
            context[key] = _WORKER_EXCEPTION_CONTEXT[key]
    return context


def _record_cuda_memory_snapshot(stage: str) -> dict[str, Any]:
    snapshot = probe_runtime.cuda_memory_snapshot(stage, started_at=_WORKER_EVENT_STARTED_AT)
    _CUDA_MEMORY_SNAPSHOTS.append(snapshot)
    _emit_worker_event("cuda_memory_snapshot", stage=stage, cuda_memory=snapshot)
    return snapshot
