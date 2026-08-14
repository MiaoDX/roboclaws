from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any

from roboclaws.household.manipulation_contract import (
    BLOCKED_CAPABILITY_PROVENANCE,
    MANIPULATION_PROBE_CONTRACT,
    PLANNER_BACKED_PROVENANCE,
)
from roboclaws.household.manipulation_provenance import (
    blocked_planner_probe_evidence,
    planner_backed_probe_evidence,
)
from roboclaws.household.rby1m_curobo_gate import rby1m_curobo_gate_from_planner_probe
from roboclaws.household.report import render_planner_manipulation_report
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND

PROBE_TASK = "pick_and_place"

_DIRECT_EVIDENCE_KEYS = (
    "runtime_diagnostics",
    "cuda_memory_snapshots",
    "curobo_memory_profile",
    "cleanup_task_config",
    "cleanup_task_sampler_adapter",
    "task_sampler_failure_diagnostics",
    "image_artifacts",
    "sampled_task_binding",
    "requested_cleanup_primitive_binding",
    "cleanup_primitive_binding",
    "policy_exception_context",
)


def write_probe_result(
    *,
    output_dir: Path,
    stdout_path: Path,
    stderr_path: Path,
    embodiment: str,
    probe_mode: str,
    steps: int,
    worker_payload: dict[str, Any] | None,
    returncode: int,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    worker_payload = worker_payload or {}
    evidence, status, primitive_provenance = _probe_evidence_and_status(
        embodiment=embodiment,
        probe_mode=probe_mode,
        steps=steps,
        worker_payload=worker_payload,
        returncode=returncode,
        blockers=blockers,
    )
    _attach_worker_payload_evidence(evidence, worker_payload, returncode)
    run_result = _run_result_payload(
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        status=status,
        primitive_provenance=primitive_provenance,
        evidence=evidence,
    )
    _write_report_and_result(output_dir, run_result)
    return run_result


def blockers_from_completed(
    returncode: int,
    worker_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if returncode == 0 and worker_payload and worker_payload.get("ok"):
        return []
    if returncode < 0:
        return [
            {
                "code": "process_signal",
                "message": f"worker terminated by {_signal_name(-returncode)}",
            }
        ]
    if worker_payload and not worker_payload.get("ok"):
        message = (
            worker_payload.get("message") or worker_payload.get("exception_type") or "worker failed"
        )
        return [
            {
                "code": str(worker_payload.get("exception_type", "worker_exception")),
                "message": str(message),
            }
        ]
    if returncode != 0:
        return [{"code": "worker_exit", "message": f"worker exited {returncode}"}]
    return []


def worker_payload_from_stdout(stdout: str) -> dict[str, Any] | None:
    json_objects = _parse_stdout_json_objects(stdout)
    if not json_objects:
        return None
    final_payload = next((item for item in reversed(json_objects) if "ok" in item), None)
    payload: dict[str, Any] = dict(final_payload or {})
    worker_events = [item for item in json_objects if item.get("event")]
    _attach_stdout_event_diagnostics(payload, worker_events)
    return payload or None


def process_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _probe_evidence_and_status(
    *,
    embodiment: str,
    probe_mode: str,
    steps: int,
    worker_payload: dict[str, Any],
    returncode: int,
    blockers: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, str]:
    if _planner_probe_succeeded(returncode, worker_payload, blockers):
        evidence = planner_backed_probe_evidence(
            backend=MOLMOSPACES_SUBPROCESS_BACKEND,
            embodiment=embodiment,
            task=PROBE_TASK,
            probe_mode=probe_mode,
            upstream_policy_class=str(worker_payload["upstream_policy_class"]),
            steps_requested=steps,
            steps_executed=int(worker_payload.get("steps_executed") or 0),
            max_abs_qpos_delta=float(worker_payload.get("max_abs_qpos_delta") or 0.0),
            image_artifacts=worker_payload.get("image_artifacts") or {},
        )
        return evidence, PLANNER_BACKED_PROVENANCE, PLANNER_BACKED_PROVENANCE
    evidence = blocked_planner_probe_evidence(
        backend=MOLMOSPACES_SUBPROCESS_BACKEND,
        embodiment=embodiment,
        task=PROBE_TASK,
        probe_mode=probe_mode,
        blockers=blockers or _default_blockers(worker_payload, probe_mode),
        upstream_policy_class=worker_payload.get("upstream_policy_class"),
        execution_attempted=bool(worker_payload.get("execution_attempted")),
    )
    return evidence, BLOCKED_CAPABILITY_PROVENANCE, BLOCKED_CAPABILITY_PROVENANCE


def _planner_probe_succeeded(
    returncode: int,
    worker_payload: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> bool:
    executed = bool(worker_payload.get("execution_attempted"))
    max_delta = float(worker_payload.get("max_abs_qpos_delta") or 0.0)
    return returncode == 0 and executed and max_delta > 0.0 and not blockers


def _attach_worker_payload_evidence(
    evidence: dict[str, Any],
    worker_payload: dict[str, Any],
    returncode: int,
) -> None:
    evidence["worker_returncode"] = returncode
    evidence["worker_payload"] = worker_payload
    for key in _DIRECT_EVIDENCE_KEYS:
        if worker_payload.get(key):
            evidence[key] = worker_payload[key]
    _attach_robot_placement_profile(evidence, worker_payload)
    if "cleanup_primitive_binding_blockers" in worker_payload:
        evidence["cleanup_primitive_binding_blockers"] = worker_payload[
            "cleanup_primitive_binding_blockers"
        ]
    _attach_worker_stage_events(evidence, worker_payload)


def _attach_robot_placement_profile(
    evidence: dict[str, Any],
    worker_payload: dict[str, Any],
) -> None:
    profile = worker_payload.get("task_sampler_robot_placement_profile")
    if profile and (profile.get("requested") or profile.get("applied")):
        evidence["task_sampler_robot_placement_profile"] = profile


def _attach_worker_stage_events(
    evidence: dict[str, Any],
    worker_payload: dict[str, Any],
) -> None:
    worker_stage_events = list(worker_payload.get("worker_stage_events") or [])
    if worker_stage_events:
        evidence["worker_stage_events"] = worker_stage_events
        evidence["last_worker_stage"] = worker_payload.get("last_worker_stage")


def _run_result_payload(
    *,
    stdout_path: Path,
    stderr_path: Path,
    status: str,
    primitive_provenance: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    run_result = {
        "artifact_kind": "molmo_planner_backed_manipulation_probe",
        "contract": MANIPULATION_PROBE_CONTRACT,
        "backend": MOLMOSPACES_SUBPROCESS_BACKEND,
        "status": status,
        "final_status": status,
        "primitive_provenance": primitive_provenance,
        "manipulation_evidence": evidence,
        "artifacts": {
            "stdout": stdout_path.name,
            "stderr": stderr_path.name,
        },
    }
    run_result["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(run_result)
    return run_result


def _write_report_and_result(output_dir: Path, run_result: dict[str, Any]) -> None:
    report_path = render_planner_manipulation_report(run_dir=output_dir, run_result=run_result)
    run_result["artifacts"]["report"] = report_path.name
    (output_dir / "run_result.json").write_text(
        json.dumps(run_result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _default_blockers(worker_payload: dict[str, Any], probe_mode: str) -> list[dict[str, Any]]:
    if probe_mode == "config_import":
        return [
            {
                "code": "execution_not_attempted",
                "message": (
                    "Planner config/class import succeeded, but execution proof was not attempted."
                ),
            }
        ]
    if not worker_payload.get("execution_attempted"):
        return [
            {
                "code": "execution_not_reached",
                "message": "Planner execution did not start.",
            }
        ]
    return [
        {"code": "no_robot_state_delta", "message": "Planner execution did not move robot state."}
    ]


def _signal_name(signum: int) -> str | int:
    if signum in {item.value for item in signal.Signals}:
        return signal.Signals(signum).name
    return signum


def _attach_stdout_event_diagnostics(
    payload: dict[str, Any],
    worker_events: list[dict[str, Any]],
) -> None:
    runtime_diagnostics = _last_runtime_diagnostics(worker_events)
    if runtime_diagnostics and "runtime_diagnostics" not in payload:
        payload["runtime_diagnostics"] = runtime_diagnostics
    if worker_events:
        payload["worker_stage_events"] = worker_events
        payload["last_worker_stage"] = str(
            worker_events[-1].get("stage") or worker_events[-1].get("event") or ""
        )
    memory_snapshots = _cuda_memory_snapshots(worker_events)
    if memory_snapshots and "cuda_memory_snapshots" not in payload:
        payload["cuda_memory_snapshots"] = memory_snapshots


def _last_runtime_diagnostics(worker_events: list[dict[str, Any]]) -> Any:
    return next(
        (
            item.get("runtime_diagnostics")
            for item in reversed(worker_events)
            if item.get("event") == "runtime_diagnostics"
        ),
        None,
    )


def _cuda_memory_snapshots(worker_events: list[dict[str, Any]]) -> list[Any]:
    return [
        item["cuda_memory"]
        for item in worker_events
        if item.get("event") == "cuda_memory_snapshot" and item.get("cuda_memory")
    ]


def _parse_stdout_json_objects(stdout: str) -> list[dict[str, Any]]:
    objects = []
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        line = line.strip()
        if not line.startswith(("{", "[")):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"planner manipulation probe stdout row must contain valid JSON object: "
                f"stdout:{line_number}: {exc.msg}"
            ) from exc
        if isinstance(payload, dict):
            objects.append(payload)
        else:
            raise ValueError(
                "planner manipulation probe stdout row must contain a JSON object: "
                f"stdout:{line_number}"
            )
    return objects
