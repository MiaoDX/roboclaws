"""Long-horizon household eval helpers."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboclaws.evals.models import MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE, EvalSample
from roboclaws.household.backend_contract import build_cleanup_backend_session
from roboclaws.household.realworld_contract import (
    DEFAULT_REALWORLD_TASK,
    VISIBLE_OBJECT_DETECTIONS_MODE,
    RealWorldCleanupContract,
)
from roboclaws.household.realworld_run_artifacts import (
    RealWorldRunArtifactInputs,
    finalize_realworld_cleanup_run,
)
from roboclaws.household.report import write_state_snapshot
from roboclaws.household.skill_scratchpad import empty_skill_scratchpad
from roboclaws.household.visual_grounding import SIM_VISUAL_GROUNDING_PIPELINE_ID
from roboclaws.launch.backends import BACKEND_SPECS, SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND
from roboclaws.launch.goals import goal_contract_from_json
from roboclaws.maps.runtime_prior_snapshot import read_runtime_map_prior_artifact

LONG_HORIZON_GRADER_NAME = "long_horizon"
SNACK_RESTOCK_SETUP = "long-horizon-snack-restock"
LONG_HORIZON_POLICY = "long_horizon_scripted_feasibility"


@dataclass(frozen=True)
class LongHorizonTaskSpec:
    """Private long-horizon task reference used only by eval harness/grader."""

    task_id: str
    target_object_ids: tuple[str, ...]
    accepted_destination_ids: tuple[str, ...]
    cold_object_ids: tuple[str, ...]
    source_room_ids: tuple[str, ...]
    source_receptacle_ids: tuple[str, ...]
    destination_room_ids: tuple[str, ...]
    required_tool_sequence: tuple[str, ...]


def is_long_horizon_sample(sample: EvalSample) -> bool:
    return LONG_HORIZON_GRADER_NAME in sample.required_graders or _task_ref(sample) is not None


def long_horizon_spec(sample: EvalSample) -> LongHorizonTaskSpec | None:
    reference = _task_ref(sample)
    if reference is None:
        return None
    return LongHorizonTaskSpec(
        task_id=str(reference.get("task_id") or sample.sample_id),
        target_object_ids=tuple(str(item) for item in reference.get("target_object_ids") or ()),
        accepted_destination_ids=tuple(
            str(item) for item in reference.get("accepted_destination_ids") or ()
        ),
        cold_object_ids=tuple(str(item) for item in reference.get("cold_object_ids") or ()),
        source_room_ids=tuple(str(item) for item in reference.get("source_room_ids") or ()),
        source_receptacle_ids=tuple(
            str(item) for item in reference.get("source_receptacle_ids") or ()
        ),
        destination_room_ids=tuple(
            str(item) for item in reference.get("destination_room_ids") or ()
        ),
        required_tool_sequence=tuple(
            str(item) for item in reference.get("required_tool_sequence") or ()
        ),
    )


def run_scripted_long_horizon_trial(
    sample: EvalSample,
    *,
    output_dir: Path,
    seed: int,
    task_prompt: str = DEFAULT_REALWORLD_TASK,
    backend: str,
    evidence_lane: str | None = None,
    generated_mess_count: int = 0,
    generated_mess_object_ids: tuple[str, ...] = (),
    scene_source: str = "procthor-10k-val",
    scene_index: int = 0,
    molmospaces_python: str | Path | None = None,
    map_bundle_dir: str | Path | None = None,
    runtime_map_prior_path: str | Path | None = None,
    visual_grounding: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
    visual_grounding_base_url: str | None = None,
    visual_grounding_timeout_s: float | None = None,
    goal_contract_json: str | None = None,
    run_metadata_overrides: dict[str, Any] | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Execute a deterministic feasibility proof for a long-horizon eval sample."""

    spec = long_horizon_spec(sample)
    if spec is None:
        raise ValueError(f"sample {sample.sample_id!r} does not define a long-horizon task")
    if not spec.target_object_ids:
        raise ValueError("long-horizon task requires target_object_ids")
    if not spec.accepted_destination_ids:
        raise ValueError("long-horizon task requires accepted_destination_ids")

    output_dir.mkdir(parents=True, exist_ok=True)
    selected_object_ids = generated_mess_object_ids or spec.target_object_ids
    selected_count = generated_mess_count or len(selected_object_ids)
    runtime_map_prior = read_runtime_map_prior_artifact(runtime_map_prior_path)
    base_contract = build_cleanup_backend_session(
        backend_name=backend,
        run_dir=output_dir,
        seed=seed,
        generated_mess_count=selected_count,
        generated_mess_object_ids=selected_object_ids,
        scene_source=scene_source,
        scene_index=scene_index,
        molmospaces_python=molmospaces_python,
        map_bundle_dir=map_bundle_dir,
    )
    goal_contract = goal_contract_from_json(goal_contract_json)
    contract = RealWorldCleanupContract(
        base_contract,
        task_prompt=task_prompt,
        static_fixture_projection_mode="room_only",
        perception_mode=VISIBLE_OBJECT_DETECTIONS_MODE,
        map_bundle_dir=map_bundle_dir,
        visual_grounding_client=None,
        visual_grounding_pipeline_id=visual_grounding,
        visual_grounding_artifact_base_dir=output_dir,
        visual_grounding_run_id=f"seed-{seed}",
        runtime_map_prior=runtime_map_prior,
        evidence_lane=evidence_lane,
        public_acceptance_config=(goal_contract and {"task_intent": goal_contract.intent}),
    )
    trace_events: list[dict[str, Any]] = []
    started_at = time.time()
    before_snapshot = _write_snapshot(
        contract=base_contract,
        output_path=output_dir / "before.png",
        title="Before long-horizon task",
    )
    metric_map = _call_tool(trace_events, started_at, "metric_map", {}, contract.metric_map)
    _call_tool(
        trace_events,
        started_at,
        "resolve_target_query",
        {"query": "snack restock shelf fridge kitchen"},
        lambda: contract.resolve_target_query("snack restock shelf fridge kitchen"),
    )
    _observe_all_waypoints(trace_events, started_at, contract, metric_map)
    destination_id = _selected_destination_id(spec, cold=False)
    cold_destination_id = _selected_destination_id(spec, cold=True) or destination_id
    for object_id in spec.target_object_ids:
        handle = contract._handle_for_object(object_id)  # noqa: SLF001
        private_destination = (
            cold_destination_id if object_id in spec.cold_object_ids else destination_id
        )
        destination = _public_destination_id(contract, private_destination)
        _move_one_target(
            trace_events=trace_events,
            started_at=started_at,
            contract=contract,
            object_handle=handle,
            destination_id=destination,
            use_inside=_destination_requires_inside(contract, private_destination),
            requires_open=object_id in spec.cold_object_ids,
        )
    done = _call_tool(
        trace_events,
        started_at,
        "done",
        {"reason": f"{LONG_HORIZON_POLICY} complete"},
        lambda: contract.done(f"{LONG_HORIZON_POLICY} complete"),
    )
    if "score" not in done:
        base_done = base_contract.done(reason=f"{LONG_HORIZON_POLICY} incomplete")
        done = {
            **done,
            "cleanup_status": "failed",
            "score": dict(base_done.get("score") or {}),
            "final_locations": base_contract.final_locations(base_done.get("final_locations")),
            "final_containment": base_done.get("final_containment", {}),
            "tool_event_counts": base_done.get("tool_event_counts", {}),
        }
    after_snapshot = _write_snapshot(
        contract=base_contract,
        output_path=output_dir / "after.png",
        title="After long-horizon task",
    )
    scratchpad = empty_skill_scratchpad(
        note="Deterministic eval-only proof for long-horizon household task feasibility."
    )
    scratchpad["policy"] = LONG_HORIZON_POLICY
    scratchpad["target_count"] = len(spec.target_object_ids)
    run_result = finalize_realworld_cleanup_run(
        RealWorldRunArtifactInputs(
            output_dir=output_dir,
            backend=backend,
            base_contract=base_contract,
            contract=contract,
            scenario=base_contract.scenario,
            seed=seed,
            task_prompt=task_prompt,
            policy_name=LONG_HORIZON_POLICY,
            done=done,
            trace_events=trace_events,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            robot_view_steps=[],
            generated_mess_count=selected_count,
            goal_contract=goal_contract,
            agent_scratchpad=scratchpad,
            map_build=False,
            runtime_map_prior=runtime_map_prior,
            runtime_map_prior_path=runtime_map_prior_path,
            evidence_lane=evidence_lane,
            perception_mode=VISIBLE_OBJECT_DETECTIONS_MODE,
            record_robot_views=False,
            selected_bundle_dir=Path(map_bundle_dir) if map_bundle_dir is not None else None,
            planner_proof_evidence=None,
            use_planner_proof_for_cleanup_primitives=False,
            map_build_scan_profile=_null_map_build_scan_profile(),
            run_metadata_overrides={
                **dict(run_metadata_overrides or {}),
                "long_horizon_policy": LONG_HORIZON_POLICY,
            },
        )
    )
    base_contract.close()
    return run_result


def grade_long_horizon_task(
    sample: EvalSample,
    *,
    run_dir: Path,
    run_result: dict[str, Any],
) -> dict[str, Any]:
    spec = long_horizon_spec(sample)
    if spec is None:
        return {
            "status": "not_applicable",
            "failure_class": MISSING_NOT_APPLICABLE,
            "subgoals": {},
        }
    trace_events, trace_errors = _read_trace_events(run_dir / "trace.jsonl")
    final_locations = (
        run_result.get("final_locations")
        if isinstance(run_result.get("final_locations"), dict)
        else {}
    )
    final_containment = (
        run_result.get("final_containment")
        if isinstance(run_result.get("final_containment"), dict)
        else {}
    )
    destinations = set(spec.accepted_destination_ids)
    object_results = {
        object_id: {
            "final_location": str(final_locations.get(object_id) or MISSING_UNAVAILABLE),
            "accepted": str(final_locations.get(object_id) or "") in destinations,
            "contained_in": str((final_containment.get(object_id) or {}).get("contained_in") or "")
            if isinstance(final_containment.get(object_id), dict)
            else "",
        }
        for object_id in spec.target_object_ids
    }
    sequence = _tool_sequence(trace_events)
    subgoals = {
        "map_acquired": "metric_map" in sequence,
        "source_visited": _visited_any_room(trace_events, spec.source_room_ids),
        "destination_reached": _destination_reached(trace_events, destinations)
        or all(item["accepted"] for item in object_results.values()),
        "target_observed": _target_observed(run_result, spec.target_object_ids),
        "picked": _tool_count(sequence, "pick") >= len(spec.target_object_ids),
        "placed": all(item["accepted"] for item in object_results.values()),
        "container_closed": _container_closed(trace_events, spec.cold_object_ids),
        "done_claim": _has_completion_claim(run_result),
        "hands_empty": _hands_empty(run_result, final_locations=final_locations),
    }
    failures = []
    if trace_errors:
        failures.append("trace_json_invalid")
    if not all(subgoals.values()):
        failures.extend(name for name, passed in subgoals.items() if not passed)
    if not _required_sequence_present(sequence, spec.required_tool_sequence):
        failures.append("required_tool_sequence_missing")
    if _private_truth_leaked(run_dir, run_result):
        failures.append("private_truth_leak")
    failure_class = _long_horizon_failure_class(failures)
    return {
        "status": "failed" if failures else "passed",
        "failure_class": failure_class if failures else MISSING_NOT_APPLICABLE,
        "task_id": spec.task_id,
        "failures": failures,
        "subgoals": subgoals,
        "object_results": object_results,
        "trace_parse_errors": trace_errors,
        "first_failure_step": _first_failure_step(trace_events, failures),
        "required_tool_sequence": list(spec.required_tool_sequence),
        "observed_tool_sequence": sequence,
    }


def generated_mess_object_ids(sample: EvalSample) -> tuple[str, ...]:
    launch_overrides = sample.launch_overrides or {}
    value = launch_overrides.get("generated_mess_object_ids")
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    spec = long_horizon_spec(sample)
    if spec is not None:
        return spec.target_object_ids
    return ()


def implementation_backend_for_direct_long_horizon(sample: EvalSample, requested: str) -> str:
    if not is_long_horizon_sample(sample):
        return requested
    if requested == SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND:
        backend = BACKEND_SPECS.get(sample.backend)
        return backend.implementation_backend if backend is not None else requested
    return requested


def metric_fields(grader_outputs: dict[str, Any]) -> dict[str, Any]:
    grader = grader_outputs[LONG_HORIZON_GRADER_NAME]
    return {
        "long_horizon_subgoals": grader.get("subgoals", MISSING_NOT_APPLICABLE),
        "long_horizon_first_failure_step": grader.get(
            "first_failure_step",
            MISSING_NOT_APPLICABLE,
        ),
    }


def run_trial(
    sample: EvalSample,
    product_runner: Any,
    default_product_runner: Any,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    if is_long_horizon_sample(sample) and product_runner is default_product_runner:
        return run_scripted_long_horizon_trial(sample, **kwargs)
    return product_runner(**kwargs)


def skill_name(sample: EvalSample, default: str) -> str:
    return "household-long-horizon" if is_long_horizon_sample(sample) else default


def manipulation_required(sample: EvalSample, default: bool) -> bool:
    return default or is_long_horizon_sample(sample)


def _task_ref(sample: EvalSample) -> dict[str, Any] | None:
    reference = sample.private_goal_reference.get("long_horizon_task")
    return dict(reference) if isinstance(reference, dict) else None


def _selected_destination_id(spec: LongHorizonTaskSpec, *, cold: bool) -> str:
    if cold:
        for destination_id in spec.accepted_destination_ids:
            if "fridge" in destination_id.lower() or "refrigerator" in destination_id.lower():
                return destination_id
    for destination_id in spec.accepted_destination_ids:
        if not ("fridge" in destination_id.lower() or "refrigerator" in destination_id.lower()):
            return destination_id
    return spec.accepted_destination_ids[0] if spec.accepted_destination_ids else ""


def _public_destination_id(contract: RealWorldCleanupContract, private_destination_id: str) -> str:
    return (
        contract._public_fixture_reference_id(private_destination_id)  # noqa: SLF001
        or private_destination_id
    )


def _destination_requires_inside(
    contract: RealWorldCleanupContract,
    private_destination_id: str,
) -> bool:
    fixture = contract._fixtures.get(private_destination_id) or {}  # noqa: SLF001
    text = " ".join(
        str(value)
        for value in (
            fixture.get("category"),
            fixture.get("name"),
            fixture.get("fixture_id"),
            private_destination_id,
        )
        if value is not None
    ).lower()
    affordances = {str(item).lower() for item in fixture.get("affordances") or []}
    return "place_inside" in affordances or any(
        term in text
        for term in (
            "fridge",
            "refrigerator",
            "shelvingunit",
            "bookshelf",
            "bookcase",
            "shelf",
        )
    )


def _observe_all_waypoints(
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    metric_map: dict[str, Any],
) -> None:
    for waypoint in metric_map.get("inspection_waypoints") or []:
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id:
            continue
        _call_tool(
            trace_events,
            started_at,
            "navigate_to_waypoint",
            {"waypoint_id": waypoint_id},
            lambda selected=waypoint_id: contract.navigate_to_waypoint(selected),
        )
        _call_tool(trace_events, started_at, "observe", {}, contract.observe)


def _move_one_target(
    *,
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    object_handle: str,
    destination_id: str,
    use_inside: bool,
    requires_open: bool,
) -> None:
    _navigate_to_object_source_waypoint(trace_events, started_at, contract, object_handle)
    navigate = _call_tool(
        trace_events,
        started_at,
        "navigate_to_object",
        {"object_id": object_handle},
        lambda: contract.navigate_to_object(object_handle),
    )
    if _needs_visual_recovery(navigate):
        _recover_visual_evidence(trace_events, started_at, contract, object_handle)
        _call_tool(
            trace_events,
            started_at,
            "navigate_to_object",
            {"object_id": object_handle},
            lambda: contract.navigate_to_object(object_handle),
        )
    pick = _call_tool(
        trace_events,
        started_at,
        "pick",
        {"object_id": object_handle},
        lambda: contract.pick(object_handle),
    )
    if _needs_visual_recovery(pick):
        _recover_visual_evidence(trace_events, started_at, contract, object_handle)
        _call_tool(
            trace_events,
            started_at,
            "pick",
            {"object_id": object_handle},
            lambda: contract.pick(object_handle),
        )
    _call_tool(
        trace_events,
        started_at,
        "navigate_to_receptacle",
        {"fixture_id": destination_id},
        lambda: contract.navigate_to_receptacle(destination_id),
    )
    if use_inside and requires_open:
        _call_tool(
            trace_events,
            started_at,
            "open_receptacle",
            {"fixture_id": destination_id},
            lambda: contract.open_receptacle(destination_id),
        )
    if use_inside:
        _call_tool(
            trace_events,
            started_at,
            "place_inside",
            {"fixture_id": destination_id},
            lambda: contract.place_inside(destination_id),
        )
        if not requires_open:
            return
        _call_tool(
            trace_events,
            started_at,
            "close_receptacle",
            {"fixture_id": destination_id},
            lambda: contract.close_receptacle(destination_id),
        )
        return
    _call_tool(
        trace_events,
        started_at,
        "place",
        {"fixture_id": destination_id},
        lambda: contract.place(destination_id),
    )


def _navigate_to_object_source_waypoint(
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    object_handle: str,
) -> None:
    waypoint_id = _object_source_waypoint_id(contract, object_handle)
    if not waypoint_id:
        return
    _call_tool(
        trace_events,
        started_at,
        "navigate_to_waypoint",
        {"waypoint_id": waypoint_id, "purpose": "object_source_revisit"},
        lambda: contract.navigate_to_waypoint(waypoint_id),
    )


def _object_source_waypoint_id(
    contract: RealWorldCleanupContract,
    object_handle: str,
) -> str:
    detection = contract._detections_by_handle.get(object_handle) or {}  # noqa: SLF001
    waypoint_id = str(detection.get("waypoint_id") or "")
    if waypoint_id:
        return waypoint_id
    generated = contract._generated_inspection_waypoint_for_object(object_handle)  # noqa: SLF001
    return str(generated.get("waypoint_id") or "")


def _recover_visual_evidence(
    trace_events: list[dict[str, Any]],
    started_at: float,
    contract: RealWorldCleanupContract,
    object_handle: str,
) -> None:
    _call_tool(
        trace_events,
        started_at,
        "adjust_camera",
        {"object_id": object_handle, "yaw_delta_deg": 15.0, "pitch_delta_deg": 0.0},
        lambda: contract.adjust_camera(yaw_delta_deg=15.0, pitch_delta_deg=0.0),
    )
    _call_tool(
        trace_events,
        started_at,
        "observe",
        {"object_id": object_handle, "purpose": "visual_evidence_recovery"},
        contract.observe,
    )


def _needs_visual_recovery(response: dict[str, Any]) -> bool:
    return response.get("ok") is False and response.get("error_reason") == (
        "visual_evidence_not_reviewable"
    )


def _call_tool(
    events: list[dict[str, Any]],
    started_at: float,
    tool: str,
    request: dict[str, Any],
    fn: Any,
) -> dict[str, Any]:
    events.append(_trace_event(started_at, tool=tool, event="request", request=request))
    response = fn()
    events.append(_trace_event(started_at, tool=tool, event="response", response=response))
    return response


def _trace_event(started_at: float, *, tool: str, event: str, **payload: Any) -> dict[str, Any]:
    return {
        "ts": round(time.time() - started_at, 6),
        "tool": tool,
        "event": event,
        **payload,
    }


def _write_snapshot(*, contract: Any, output_path: Path, title: str) -> Path:
    visual_snapshot = contract.write_visual_snapshot(output_path, title=title)
    if visual_snapshot is not None:
        return visual_snapshot
    return write_state_snapshot(
        contract.scenario,
        contract.object_locations(),
        output_path,
        title=title,
    )


def _null_map_build_scan_profile() -> Any:
    from roboclaws.household.map_build_scan_profile import map_build_scan_profile

    return map_build_scan_profile()


def _read_trace_events(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    events: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return [], [{"path": str(path), "error": "missing"}]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"path": str(path), "line": str(line_number), "error": exc.msg})
            continue
        if isinstance(item, dict):
            events.append(item)
        else:
            errors.append({"path": str(path), "line": str(line_number), "error": "not_object"})
    return events, errors


def _tool_sequence(trace_events: list[dict[str, Any]]) -> list[str]:
    return [
        str(event.get("tool") or "")
        for event in trace_events
        if event.get("event") == "response" and event.get("tool")
    ]


def _tool_count(sequence: list[str], tool: str) -> int:
    return sum(1 for item in sequence if item == tool)


def _visited_any_room(trace_events: list[dict[str, Any]], room_ids: tuple[str, ...]) -> bool:
    if not room_ids:
        return True
    expected = set(room_ids)
    for event in trace_events:
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if str(response.get("current_room_id") or response.get("room_id") or "") in expected:
            return True
    return False


def _destination_reached(trace_events: list[dict[str, Any]], destinations: set[str]) -> bool:
    for event in trace_events:
        if event.get("event") != "response":
            continue
        if event.get("tool") not in {
            "navigate_to_receptacle",
            "place",
            "place_inside",
            "close_receptacle",
        }:
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        for key in ("fixture_id", "receptacle_id", "location_id", "contained_in"):
            if str(response.get(key) or "") in destinations:
                return True
    return False


def _target_observed(run_result: dict[str, Any], object_ids: tuple[str, ...]) -> bool:
    runtime_map = (
        run_result.get("runtime_metric_map")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else {}
    )
    observed = runtime_map.get("observed_objects") if isinstance(runtime_map, dict) else []
    if not isinstance(observed, list):
        return False
    public_count = sum(1 for item in observed if isinstance(item, dict) and item.get("object_id"))
    return public_count >= len(object_ids)


def _container_closed(trace_events: list[dict[str, Any]], cold_object_ids: tuple[str, ...]) -> bool:
    if not cold_object_ids:
        return True
    sequence = _tool_sequence(trace_events)
    try:
        place_index = sequence.index("place_inside")
        close_index = sequence.index("close_receptacle")
    except ValueError:
        return False
    return close_index > place_index


def _has_completion_claim(run_result: dict[str, Any]) -> bool:
    claim = run_result.get("agent_completion_claim")
    return isinstance(claim, dict) and bool(claim.get("completion_summary"))


def _hands_empty(run_result: dict[str, Any], *, final_locations: dict[str, Any]) -> bool:
    if any(str(value) == "held_by_agent" for value in final_locations.values()):
        return False
    runtime_map = (
        run_result.get("runtime_metric_map")
        if isinstance(run_result.get("runtime_metric_map"), dict)
        else {}
    )
    summary = runtime_map.get("cleanup_worklist_summary") if isinstance(runtime_map, dict) else {}
    if isinstance(summary, dict) and summary.get("held_object_id"):
        return False
    return True


def _required_sequence_present(sequence: list[str], required: tuple[str, ...]) -> bool:
    if not required:
        return True
    start = 0
    for tool in required:
        try:
            index = sequence.index(tool, start)
        except ValueError:
            return False
        start = index + 1
    return True


def _private_truth_leaked(run_dir: Path, run_result: dict[str, Any]) -> bool:
    forbidden = {
        "private_manifest",
        "acceptable_destinations",
        "target_object_ids",
        "accepted_destination_ids",
        "long_horizon_task",
    }
    agent_view = run_result.get("agent_view")
    if _contains_forbidden_key(agent_view, forbidden):
        return True
    path = run_dir / "agent_view.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}
    if _contains_forbidden_key(payload, forbidden):
        return True
    trace_events, _errors = _read_trace_events(run_dir / "trace.jsonl")
    return any(_contains_forbidden_key(event, forbidden) for event in trace_events)


def _contains_forbidden_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return bool(forbidden.intersection(value)) or any(
            _contains_forbidden_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def _long_horizon_failure_class(failures: list[str]) -> str:
    if "private_truth_leak" in failures:
        return "private_truth_leak"
    if "trace_json_invalid" in failures:
        return "artifact_missing"
    if "required_tool_sequence_missing" in failures:
        return "trajectory_policy_violation"
    if any(item in failures for item in ("placed", "hands_empty", "container_closed")):
        return "private_goal_not_satisfied"
    if "target_observed" in failures:
        return "perception_miss"
    if any(item in failures for item in ("source_visited", "destination_reached")):
        return "trajectory_policy_violation"
    return "partial_progress_only"


def _first_failure_step(trace_events: list[dict[str, Any]], failures: list[str]) -> int | str:
    if not failures:
        return MISSING_NOT_APPLICABLE
    for index, event in enumerate(trace_events, start=1):
        if event.get("event") != "response":
            continue
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        if response.get("ok") is False:
            return index
    return MISSING_UNAVAILABLE
