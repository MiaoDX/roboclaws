from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from roboclaws.household.manipulation_contract import (
    PLANNER_BACKED_PROVENANCE,
    PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
    PLANNER_PROOF_ATTACHMENT_SCHEMA,
    CleanupPrimitiveRequest,
    CleanupPrimitiveResult,
)
from roboclaws.household.planner_primitive_executor import (
    blocked_cleanup_primitive_result,
    planner_backed_cleanup_primitive_result,
)
from roboclaws.household.semantic_timeline import canonical_cleanup_tool_sequence

PLANNER_PROBE_PRIMITIVE_EXECUTOR_SCHEMA = "planner_probe_cleanup_primitive_executor_v1"
TARGET_SIDE_TOOLS = frozenset(
    {
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
)


class ProbeBackedCleanupPrimitiveExecutor:
    """Turn a bound planner proof attachment into cleanup primitive evidence."""

    def __init__(
        self,
        planner_proof_attachment: Mapping[str, Any],
        *,
        executor_name: str = "probe_backed_cleanup_primitive_executor",
    ) -> None:
        self.planner_proof_attachment = dict(planner_proof_attachment)
        self.executor_name = executor_name

    def __call__(self, request: CleanupPrimitiveRequest) -> CleanupPrimitiveResult:
        proof_blockers = _target_proof_blockers(self.planner_proof_attachment)
        if proof_blockers:
            return _blocked_result(
                self.executor_name,
                request,
                proof_blockers[0],
                proof_blockers,
            )
        binding = cleanup_primitive_binding_from_attachment(self.planner_proof_attachment)
        binding_blockers = _binding_blockers(binding, request)
        if binding_blockers:
            return _blocked_result(
                self.executor_name,
                request,
                binding_blockers[0],
                binding_blockers,
            )
        return planner_backed_cleanup_primitive_result(
            executor=self.executor_name,
            tool=request.tool,
            evidence={
                "schema": PLANNER_PROBE_PRIMITIVE_EXECUTOR_SCHEMA,
                "source_run_result": self.planner_proof_attachment.get("source_run_result", ""),
                "proof_schema": self.planner_proof_attachment.get("schema"),
                "proof_embodiment": self.planner_proof_attachment.get("embodiment"),
                "proof_probe_mode": self.planner_proof_attachment.get("probe_mode"),
                "upstream_policy_class": self.planner_proof_attachment.get("upstream_policy_class"),
                "steps_executed": int(self.planner_proof_attachment.get("steps_executed") or 0),
                "max_abs_qpos_delta": float(
                    self.planner_proof_attachment.get("max_abs_qpos_delta") or 0.0
                ),
                "image_artifacts": dict(self.planner_proof_attachment.get("image_artifacts") or {}),
                "cleanup_primitive_binding": binding,
                "request": request.to_dict(),
            },
        )


def cleanup_primitive_binding_from_attachment(
    attachment: Mapping[str, Any],
) -> dict[str, Any]:
    raw = (
        attachment.get("cleanup_primitive_binding")
        or attachment.get("planner_primitive_binding")
        or {}
    )
    return dict(raw) if isinstance(raw, Mapping) else {}


def normalize_cleanup_primitive_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    tools = _binding_tools(binding)
    return {
        "schema": str(binding.get("schema") or PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA),
        "object_id": str(binding.get("object_id") or ""),
        "target_receptacle_id": str(binding.get("target_receptacle_id") or ""),
        "source_receptacle_id": str(binding.get("source_receptacle_id") or ""),
        "planner_object_id": str(binding.get("planner_object_id") or ""),
        "planner_target_receptacle_id": str(binding.get("planner_target_receptacle_id") or ""),
        "tools": tools,
        "evidence_note": str(
            binding.get("evidence_note")
            or "Planner proof is bound to this cleanup primitive request."
        ),
    }


def _target_proof_blockers(attachment: Mapping[str, Any]) -> list[dict[str, str]]:
    blockers = []
    if attachment.get("schema") != PLANNER_PROOF_ATTACHMENT_SCHEMA:
        blockers.append(
            {
                "code": "planner_probe_invalid_attachment_schema",
                "message": "Probe-backed executor requires a planner proof attachment.",
            }
        )
    if attachment.get("primitive_provenance") != PLANNER_BACKED_PROVENANCE:
        blockers.append(
            {
                "code": "planner_probe_not_planner_backed",
                "message": "Planner proof attachment is not planner_backed.",
            }
        )
    if attachment.get("embodiment") != "rby1m":
        blockers.append(
            {
                "code": "planner_probe_not_rby1m",
                "message": "Cleanup primitive executor requires target RBY1M proof.",
            }
        )
    if attachment.get("probe_mode") != "execute":
        blockers.append(
            {
                "code": "planner_probe_not_execute_mode",
                "message": "Cleanup primitive executor requires execute-mode proof.",
            }
        )
    if "Curobo" not in str(attachment.get("upstream_policy_class") or ""):
        blockers.append(
            {
                "code": "planner_probe_not_curobo_policy",
                "message": "Cleanup primitive executor requires a CuRobo planner policy.",
            }
        )
    runtime = attachment.get("runtime_diagnostics") or {}
    modules = runtime.get("modules") if isinstance(runtime, Mapping) else {}
    curobo = modules.get("curobo") if isinstance(modules, Mapping) else {}
    if not isinstance(curobo, Mapping) or curobo.get("available") is not True:
        blockers.append(
            {
                "code": "planner_probe_curobo_unavailable",
                "message": "Cleanup primitive executor requires CuRobo runtime availability.",
            }
        )
    if int(attachment.get("steps_executed") or 0) < 1:
        blockers.append(
            {
                "code": "planner_probe_no_steps",
                "message": "Cleanup primitive executor requires at least one executed step.",
            }
        )
    if float(attachment.get("max_abs_qpos_delta") or 0.0) <= 0.0:
        blockers.append(
            {
                "code": "planner_probe_no_robot_state_delta",
                "message": "Cleanup primitive executor requires nonzero robot-state movement.",
            }
        )
    return blockers


def _binding_blockers(
    binding: Mapping[str, Any],
    request: CleanupPrimitiveRequest,
) -> list[dict[str, str]]:
    if not binding:
        return [
            {
                "code": "planner_probe_missing_cleanup_binding",
                "message": (
                    "Planner proof is strict target-runtime evidence but lacks cleanup "
                    "primitive binding for this object/tool/target."
                ),
            }
        ]
    normalized = normalize_cleanup_primitive_binding(binding)
    blockers = []
    if normalized["schema"] != PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA:
        blockers.append(
            {
                "code": "planner_probe_invalid_binding_schema",
                "message": (
                    f"Planner proof binding schema={normalized['schema']} does not match "
                    f"{PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA}."
                ),
            }
        )
    if request.tool not in normalized["tools"]:
        blockers.append(
            {
                "code": "planner_probe_tool_mismatch",
                "message": (
                    f"Planner proof binding tools={normalized['tools']} does not include "
                    f"requested tool={request.tool}."
                ),
            }
        )
    if normalized["object_id"] != request.object_id:
        blockers.append(
            {
                "code": "planner_probe_object_mismatch",
                "message": (
                    f"Planner proof binding object_id={normalized['object_id']} does not "
                    f"match requested object_id={request.object_id}."
                ),
            }
        )
    if request.tool in TARGET_SIDE_TOOLS:
        if normalized["target_receptacle_id"] != request.target_receptacle_id:
            blockers.append(
                {
                    "code": "planner_probe_target_mismatch",
                    "message": (
                        f"Planner proof binding target_receptacle_id="
                        f"{normalized['target_receptacle_id']} does not match requested "
                        f"target_receptacle_id={request.target_receptacle_id}."
                    ),
                }
            )
    return blockers


def _blocked_result(
    executor_name: str,
    request: CleanupPrimitiveRequest,
    blocker: Mapping[str, str],
    blockers: list[dict[str, str]],
) -> CleanupPrimitiveResult:
    result = blocked_cleanup_primitive_result(
        executor=executor_name,
        tool=request.tool,
        code=str(blocker.get("code") or "planner_probe_blocked"),
        message=str(blocker.get("message") or "Planner probe cannot satisfy request."),
    )
    return CleanupPrimitiveResult(
        ok=result.ok,
        primitive_provenance=result.primitive_provenance,
        planner_backed=result.planner_backed,
        strict_proof_eligible=result.strict_proof_eligible,
        executor=result.executor,
        status=result.status,
        blockers=tuple(blockers),
        tool=result.tool,
    )


def _binding_tools(binding: Mapping[str, Any]) -> list[str]:
    raw = binding.get("tools")
    if isinstance(raw, (list, tuple)):
        tools = [str(item) for item in raw if item]
    else:
        tool = binding.get("tool")
        tools = [str(tool)] if tool else []
    return canonical_cleanup_tool_sequence(tools)
