from __future__ import annotations

from collections import Counter
from typing import Any

from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
    validate_cleanup_primitive_evidence,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.manipulation_contract import CleanupPrimitiveRequest
from roboclaws.household.planner_cleanup_bridge import (
    planner_cleanup_bridge_evidence,
    validate_planner_cleanup_bridge_evidence,
)
from roboclaws.household.planner_primitive_executor import (
    PlannerBackedCleanupContractAdapter,
    blocked_cleanup_primitive_result,
    planner_backed_cleanup_primitive_result,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_cleanup_loop import run_semantic_cleanup_loop
from roboclaws.household.semantic_timeline import semantic_substeps


def test_planner_primitive_adapter_makes_shared_loop_strict_ready() -> None:
    scenario = build_cleanup_scenario(seed=7)
    base_contract = HouseholdBackendSession(scenario)
    executor_calls: list[CleanupPrimitiveRequest] = []
    contract = PlannerBackedCleanupContractAdapter(
        base_contract,
        executor=_planner_executor(executor_calls),
        executor_name="unit-planner",
    )
    trace_events: list[dict[str, Any]] = []
    receptacles = _receptacles_by_id(scenario)

    result = run_semantic_cleanup_loop(
        targets=[
            _target("mug_01", "sink_01", receptacles, source_receptacle_id="sofa_01"),
            _target("apple_01", "fridge_01", receptacles, source_receptacle_id="desk_01"),
        ],
        contract=contract,
        receptacles_by_id=receptacles,
        call_tool=lambda tool, request, fn: _call_tool(trace_events, tool, request, fn),
    )

    assert result.completed_objects == 2
    assert result.failed_objects == ()
    assert [item.tool for item in executor_calls] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place_inside",
    ]

    substeps = semantic_substeps(trace_events, receptacles)
    evidence = cleanup_primitive_evidence_from_substeps(substeps)
    validate_cleanup_primitive_evidence(evidence, require_planner_backed=True)
    assert evidence["primitive_provenance_summary"] == {"planner_backed": 9}

    for item in evidence["objects"]:
        for step in item["subphases"]:
            primitive_evidence = step["planner_primitive_evidence"]
            assert primitive_evidence["schema"] == "planner_cleanup_primitive_executor_v1"
            assert primitive_evidence["tool"] == step["phase"]
            assert primitive_evidence["request"]["tool"] == step["phase"]
            assert primitive_evidence["state_sync_provenance"] == "api_semantic"

    bridge = planner_cleanup_bridge_evidence(
        planner_proof_attachment=_rby1m_curobo_attachment(),
        cleanup_primitive_evidence=evidence,
    )
    validate_planner_cleanup_bridge_evidence(bridge, require_ready=True)
    assert bridge["target_runtime_ready"] is True
    assert bridge["cleanup_primitives_ready"] is True


def test_planner_primitive_adapter_fails_closed_when_executor_blocks() -> None:
    scenario = build_cleanup_scenario(seed=7)
    base_contract = HouseholdBackendSession(scenario)
    executor_calls: list[CleanupPrimitiveRequest] = []
    contract = PlannerBackedCleanupContractAdapter(
        base_contract,
        executor=_blocking_executor(executor_calls),
        executor_name="unit-planner",
    )
    trace_events: list[dict[str, Any]] = []
    receptacles = _receptacles_by_id(scenario)

    result = run_semantic_cleanup_loop(
        targets=[_target("mug_01", "sink_01", receptacles, source_receptacle_id="sofa_01")],
        contract=contract,
        receptacles_by_id=receptacles,
        call_tool=lambda tool, request, fn: _call_tool(trace_events, tool, request, fn),
    )

    assert result.completed_objects == 0
    assert result.failed_objects[0]["failed_tool"] == "navigate_to_object"
    assert [item.tool for item in executor_calls] == ["navigate_to_object"]
    assert base_contract.backend.tool_event_counts == Counter()

    substeps = semantic_substeps(trace_events, receptacles)
    evidence = cleanup_primitive_evidence_from_substeps(substeps)
    validate_cleanup_primitive_evidence(evidence, accept_blocked_capability=True)
    assert evidence["status"] == "blocked_capability"
    assert evidence["primitive_provenance_summary"] == {"blocked_capability": 1}
    assert evidence["objects"][0]["subphases"][0]["planner_backed"] is False


def test_planner_primitive_adapter_requires_object_context_before_target_steps() -> None:
    scenario = build_cleanup_scenario(seed=7)
    base_contract = HouseholdBackendSession(scenario)
    executor_calls: list[CleanupPrimitiveRequest] = []
    contract = PlannerBackedCleanupContractAdapter(
        base_contract,
        executor=_planner_executor(executor_calls),
        executor_name="unit-planner",
    )

    response = contract.navigate_to_receptacle("sink_01")

    assert response["ok"] is False
    assert response["error_reason"] == "planner_primitive_missing_object_context"
    assert executor_calls == []
    assert base_contract.backend.tool_event_counts == Counter()


def test_default_cleanup_contract_remains_api_semantic_without_executor() -> None:
    scenario = build_cleanup_scenario(seed=7)
    contract = HouseholdBackendSession(scenario)
    trace_events: list[dict[str, Any]] = []
    receptacles = _receptacles_by_id(scenario)

    result = run_semantic_cleanup_loop(
        targets=[_target("mug_01", "sink_01", receptacles, source_receptacle_id="sofa_01")],
        contract=contract,
        receptacles_by_id=receptacles,
        call_tool=lambda tool, request, fn: _call_tool(trace_events, tool, request, fn),
    )

    assert result.completed_objects == 1
    evidence = cleanup_primitive_evidence_from_substeps(
        semantic_substeps(trace_events, receptacles)
    )
    validate_cleanup_primitive_evidence(evidence, accept_blocked_capability=True)
    assert evidence["status"] == "blocked_capability"
    assert evidence["primitive_provenance_summary"] == {"api_semantic": 4}
    assert all(
        step["planner_primitive_evidence"] == {}
        for item in evidence["objects"]
        for step in item["subphases"]
    )


def _planner_executor(
    calls: list[CleanupPrimitiveRequest],
) -> Any:
    def executor(request: CleanupPrimitiveRequest) -> dict[str, Any]:
        calls.append(request)
        return planner_backed_cleanup_primitive_result(
            executor="unit-planner",
            tool=request.tool,
            evidence={
                "planner_run_id": f"{request.tool}-{len(calls)}",
                "object_id": request.object_id,
                "target_receptacle_id": request.target_receptacle_id,
                "sim_steps_executed": 2,
                "max_abs_qpos_delta": 0.01,
            },
        ).to_dict()

    return executor


def _blocking_executor(
    calls: list[CleanupPrimitiveRequest],
) -> Any:
    def executor(request: CleanupPrimitiveRequest) -> dict[str, Any]:
        calls.append(request)
        return blocked_cleanup_primitive_result(
            executor="unit-planner",
            tool=request.tool,
            code="planner_primitive_fixture_missing",
            message="Unit test blocked primitive execution.",
        ).to_dict()

    return executor


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


def _target(
    object_id: str,
    receptacle_id: str,
    receptacles: dict[str, dict[str, Any]],
    *,
    source_receptacle_id: str,
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "target_receptacle_id": receptacle_id,
        "source_receptacle_id": source_receptacle_id,
        "target_receptacle": dict(receptacles[receptacle_id]),
    }


def _receptacles_by_id(scenario: Any) -> dict[str, dict[str, Any]]:
    return {item.receptacle_id: item.to_public_dict() for item in scenario.receptacles}


def _rby1m_curobo_attachment() -> dict[str, object]:
    return {
        "schema": "planner_backed_cleanup_attachment_v1",
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
        "runtime_diagnostics": {
            "modules": {"curobo": {"available": True}},
        },
    }
