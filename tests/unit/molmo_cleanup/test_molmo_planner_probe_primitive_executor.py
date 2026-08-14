from __future__ import annotations

from typing import Any

from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
    validate_cleanup_primitive_evidence,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.manipulation_contract import (
    PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
    CleanupPrimitiveRequest,
)
from roboclaws.household.planner_cleanup_bridge import (
    planner_cleanup_bridge_evidence,
    validate_planner_cleanup_bridge_evidence,
)
from roboclaws.household.planner_primitive_executor import (
    PlannerBackedCleanupContractAdapter,
)
from roboclaws.household.planner_probe_primitive_executor import (
    PLANNER_PROBE_PRIMITIVE_EXECUTOR_SCHEMA,
    ProbeBackedCleanupPrimitiveExecutor,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_cleanup_loop import run_semantic_cleanup_loop
from roboclaws.household.semantic_timeline import semantic_substeps


def test_probe_backed_executor_blocks_generic_standalone_proof() -> None:
    executor = ProbeBackedCleanupPrimitiveExecutor(_attachment())

    result = executor(_request("place"))

    assert result.ok is False
    assert result.primitive_provenance == "blocked_capability"
    assert result.blockers[0]["code"] == "planner_probe_missing_cleanup_binding"


def test_probe_backed_executor_accepts_matching_bound_proof() -> None:
    executor = ProbeBackedCleanupPrimitiveExecutor(
        _attachment(
            binding={
                "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "tools": ["navigate_to_receptacle", "place"],
            }
        )
    )

    result = executor(_request("place"))

    assert result.ok is True
    assert result.primitive_provenance == "planner_backed"
    evidence = result.evidence
    assert evidence["schema"] == PLANNER_PROBE_PRIMITIVE_EXECUTOR_SCHEMA
    assert evidence["cleanup_primitive_binding"]["object_id"] == "observed_001"
    assert evidence["cleanup_primitive_binding"]["target_receptacle_id"] == "sink_01"


def test_probe_backed_executor_accepts_observed_handle_with_planner_aliases() -> None:
    executor = ProbeBackedCleanupPrimitiveExecutor(
        _attachment(
            binding={
                "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "planner_object_id": "pickup/body",
                "planner_target_receptacle_id": "sink/body",
                "tools": ["place"],
            }
        )
    )

    result = executor(_request("place"))

    assert result.ok is True
    assert result.evidence["cleanup_primitive_binding"]["object_id"] == "observed_001"
    assert result.evidence["cleanup_primitive_binding"]["planner_object_id"] == "pickup/body"


def test_probe_backed_executor_rejects_target_mismatch() -> None:
    executor = ProbeBackedCleanupPrimitiveExecutor(
        _attachment(
            binding={
                "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
                "object_id": "observed_001",
                "target_receptacle_id": "bookshelf_01",
                "tools": ["place"],
            }
        )
    )

    result = executor(_request("place"))

    assert result.ok is False
    assert result.blockers[0]["code"] == "planner_probe_target_mismatch"


def test_probe_backed_executor_drives_shared_loop_when_bound_to_cleanup_target() -> None:
    scenario = build_cleanup_scenario(seed=7)
    receptacles = _receptacles_by_id(scenario)
    base_contract = HouseholdBackendSession(scenario)
    probe_executor = ProbeBackedCleanupPrimitiveExecutor(
        _attachment(
            binding={
                "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
                "object_id": "mug_01",
                "target_receptacle_id": "sink_01",
                "source_receptacle_id": "sofa_01",
                "tools": [
                    "navigate_to_object",
                    "pick",
                    "navigate_to_receptacle",
                    "place",
                ],
            }
        )
    )
    contract = PlannerBackedCleanupContractAdapter(
        base_contract,
        executor=probe_executor,
        executor_name="probe-backed-unit",
    )
    trace_events: list[dict[str, Any]] = []

    result = run_semantic_cleanup_loop(
        targets=[
            {
                "object_id": "mug_01",
                "target_receptacle_id": "sink_01",
                "source_receptacle_id": "sofa_01",
                "target_receptacle": dict(receptacles["sink_01"]),
            }
        ],
        contract=contract,
        receptacles_by_id=receptacles,
        call_tool=lambda tool, request, fn: _call_tool(trace_events, tool, request, fn),
    )

    assert result.completed_objects == 1
    evidence = cleanup_primitive_evidence_from_substeps(
        semantic_substeps(trace_events, receptacles)
    )
    validate_cleanup_primitive_evidence(evidence, require_planner_backed=True)
    assert evidence["primitive_provenance_summary"] == {"planner_backed": 4}

    bridge = planner_cleanup_bridge_evidence(
        planner_proof_attachment=_attachment(
            binding={
                "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
                "object_id": "mug_01",
                "target_receptacle_id": "sink_01",
                "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
            }
        ),
        cleanup_primitive_evidence=evidence,
    )
    validate_planner_cleanup_bridge_evidence(bridge, require_ready=True)


def _request(tool: str) -> CleanupPrimitiveRequest:
    return CleanupPrimitiveRequest(
        tool=tool,
        object_id="observed_001",
        target_receptacle_id="sink_01",
        source_receptacle_id="counter_01",
    )


def _attachment(*, binding: dict[str, object] | None = None) -> dict[str, object]:
    attachment: dict[str, object] = {
        "schema": "planner_backed_cleanup_attachment_v1",
        "source_run_result": "output/proof/run_result.json",
        "contract": "planner_backed_manipulation_probe_v1",
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "planner_backed": True,
        "strict_proof_eligible": True,
        "embodiment": "rby1m",
        "task": "pick_and_place",
        "probe_mode": "execute",
        "upstream_policy_class": "CuroboPickAndPlacePlannerPolicy",
        "steps_executed": 2,
        "max_abs_qpos_delta": 0.01,
        "image_artifacts": {
            "initial": "planner_proof/initial.png",
            "final": "planner_proof/final.png",
        },
        "runtime_diagnostics": {
            "modules": {"curobo": {"available": True}},
        },
    }
    if binding is not None:
        attachment["cleanup_primitive_binding"] = binding
    return attachment


def _receptacles_by_id(scenario: Any) -> dict[str, dict[str, Any]]:
    return {item.receptacle_id: item.to_public_dict() for item in scenario.receptacles}


def _call_tool(
    trace_events: list[dict[str, Any]],
    tool: str,
    request: dict[str, Any],
    fn: Any,
) -> dict[str, Any]:
    trace_events.append({"event": "request", "tool": tool, "request": dict(request)})
    response = fn()
    trace_events.append(
        {
            "event": "response",
            "tool": tool,
            "request": dict(request),
            "response": dict(response),
        }
    )
    return response
