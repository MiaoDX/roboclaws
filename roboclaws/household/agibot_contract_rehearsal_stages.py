from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.agibot_contract_rehearsal import (
    BLOCKED_MANIPULATION_TOOLS,
    REHEARSAL_MODE_CLEANUP_ACTIONS,
    REHEARSAL_MODE_CONTRACT,
    RUNTIME_FIXTURE,
    RUNTIME_MOLMOSPACES_SUBPROCESS,
    _agent_view_with_cleanup_actions,
    _agent_view_with_runtime_observation,
    _agibot_shaped_metric_map,
    _agibot_shaped_static_fixture_projection,
    _empty_cleanup_actions_result,
    _first_waypoint_id_from_sequence,
    _load_json,
    _policy_event,
    _record,
    _record_action_done,
    _record_robot_view,
    _relpath,
    _run_cleanup_action_rehearsal,
    _run_result,
    _runtime_export,
    _write_preflight_artifacts,
    _write_snapshot,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    blocked_manipulation as _blocked_manipulation,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    simulated_navigation as _simulated_navigation,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    simulated_observation as _simulated_observation,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    write_json as _write_json,
)
from roboclaws.household.agibot_contract_rehearsal_runtime import (
    write_stage_artifact as _write_stage_artifact,
)
from roboclaws.household.cleanup_primitive_evidence import (
    cleanup_primitive_evidence_from_substeps,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    VISIBLE_OBJECT_DETECTIONS_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.report import (
    render_cleanup_report,
    write_trace_jsonl,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_timeline import semantic_substeps
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend
from roboclaws.household.types import CleanupScenario
from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_path


@dataclass(frozen=True)
class _ContractRehearsalOptions:
    seed: int
    generated_mess_count: int
    runtime: str
    waypoint_id: str | None
    molmospaces_python: Path | None
    include_robot: bool
    robot_name: str
    rehearsal_mode: str
    cleanup_object_count: int
    record_robot_views: bool
    context_json: Path | None
    agibot_map_artifact_dir: Path | None


@dataclass
class _RehearsalTraceState:
    started_at: float
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    policy_events: list[dict[str, Any]] = field(default_factory=list)
    robot_view_steps: list[dict[str, Any]] = field(default_factory=list)
    robot_view_index: int = 0


@dataclass(frozen=True)
class _ContractRehearsalSession:
    scenario: CleanupScenario
    base_contract: HouseholdBackendSession
    contract: HouseholdRuntimeContract
    backend_instance: MolmoSpacesSubprocessBackend | None


@dataclass(frozen=True)
class _RehearsalPreflightState:
    metric_map: dict[str, Any]
    static_fixture_projection: dict[str, Any]
    preflight: dict[str, Path]
    waypoint_sequence: dict[str, Any]
    subphase_reports: list[dict[str, Any]]


@dataclass(frozen=True)
class _ObserveNavigateResult:
    observation: dict[str, Any]
    navigation: dict[str, Any]


@dataclass(frozen=True)
class _RehearsalActionResult:
    manipulation_results: list[dict[str, Any]]
    cleanup_actions: dict[str, Any]
    final_locations: dict[str, Any]
    done_response: dict[str, Any] | None


def run_contract_rehearsal(
    *,
    run_dir: Path,
    options: _ContractRehearsalOptions,
) -> dict[str, Any]:
    _validate_contract_rehearsal_options(options)
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    state = _RehearsalTraceState(started_at=time.time())
    session: _ContractRehearsalSession | None = None

    try:
        session = _build_contract_rehearsal_session(run_dir=run_dir, options=options)
        before_snapshot = _write_rehearsal_boundary_snapshot(
            run_dir=run_dir,
            session=session,
            state=state,
            options=options,
            filename="before.png",
            action="before",
            label_suffix="before",
            title="Before MolmoSpaces Agibot contract rehearsal",
        )
        preflight = _prepare_rehearsal_preflight(
            run_dir=run_dir,
            session=session,
            state=state,
            options=options,
        )
        observe_navigation = _run_rehearsal_observe_navigation(
            run_dir=run_dir,
            session=session,
            state=state,
            options=options,
            preflight=preflight,
        )
        action_result = _run_rehearsal_action_stage(
            run_dir=run_dir,
            session=session,
            state=state,
            options=options,
            preflight=preflight,
        )
        return _finalize_rehearsal_run(
            run_dir=run_dir,
            session=session,
            state=state,
            options=options,
            preflight=preflight,
            observe_navigation=observe_navigation,
            action_result=action_result,
            before_snapshot=before_snapshot,
        )
    finally:
        if session is not None and session.backend_instance is not None:
            session.backend_instance.close()


def _validate_contract_rehearsal_options(options: _ContractRehearsalOptions) -> None:
    if options.runtime not in {RUNTIME_FIXTURE, RUNTIME_MOLMOSPACES_SUBPROCESS}:
        expected = f"{RUNTIME_FIXTURE}|{RUNTIME_MOLMOSPACES_SUBPROCESS}"
        raise ValueError(f"unsupported rehearsal runtime {options.runtime!r} (expected {expected})")
    if options.rehearsal_mode not in {REHEARSAL_MODE_CONTRACT, REHEARSAL_MODE_CLEANUP_ACTIONS}:
        expected = f"{REHEARSAL_MODE_CONTRACT}|{REHEARSAL_MODE_CLEANUP_ACTIONS}"
        raise ValueError(
            f"unsupported rehearsal mode {options.rehearsal_mode!r} (expected {expected})"
        )
    if options.cleanup_object_count < 1:
        raise ValueError("cleanup_object_count must be >= 1")
    if options.record_robot_views and (
        options.runtime != RUNTIME_MOLMOSPACES_SUBPROCESS or not options.include_robot
    ):
        raise ValueError(
            "record_robot_views requires runtime=molmospaces-subprocess and include_robot=true"
        )


def _build_contract_rehearsal_session(
    *,
    run_dir: Path,
    options: _ContractRehearsalOptions,
) -> _ContractRehearsalSession:
    backend_instance: MolmoSpacesSubprocessBackend | None = None
    if options.runtime == RUNTIME_MOLMOSPACES_SUBPROCESS:
        backend_instance = MolmoSpacesSubprocessBackend(
            run_dir=run_dir,
            seed=options.seed,
            python_executable=options.molmospaces_python,
            include_robot=options.include_robot,
            robot_name=options.robot_name,
            generated_mess_count=options.generated_mess_count,
        )
        scenario = backend_instance.scenario
        base_contract = HouseholdBackendSession(scenario, backend=backend_instance)
    else:
        scenario = build_cleanup_scenario(seed=options.seed)
        base_contract = HouseholdBackendSession(scenario)
    contract = HouseholdRuntimeContract(
        base_contract,
        task_prompt=scenario.task,
        static_fixture_projection_mode="exact_fixtures",
        perception_mode=VISIBLE_OBJECT_DETECTIONS_MODE,
        map_bundle_dir=molmospaces_nav2_map_bundle_path(
            scene_source="procthor-10k-val",
            scene_index=0,
        ),
    )
    return _ContractRehearsalSession(
        scenario=scenario,
        base_contract=base_contract,
        contract=contract,
        backend_instance=backend_instance,
    )


def _write_rehearsal_boundary_snapshot(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    filename: str,
    action: str,
    label_suffix: str,
    title: str,
) -> Path:
    snapshot = _write_snapshot(
        runtime=options.runtime,
        contract=session.base_contract,
        scenario=session.scenario,
        output_path=run_dir / filename,
        title=title,
    )
    if options.record_robot_views:
        state.robot_view_index = _record_robot_view(
            robot_view_steps=state.robot_view_steps,
            trace_events=state.trace_events,
            started_at=state.started_at,
            backend=session.base_contract.backend,
            run_dir=run_dir,
            index=state.robot_view_index,
            action=action,
            label_suffix=label_suffix,
        )
    return snapshot


def _prepare_rehearsal_preflight(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
) -> _RehearsalPreflightState:
    metric_map = _agibot_shaped_metric_map(session.contract.metric_map(), seed=options.seed)
    static_fixture_projection = _agibot_shaped_static_fixture_projection(
        session.contract.static_fixture_projection()
    )
    preflight = _write_preflight_artifacts(
        run_dir=run_dir,
        scenario=session.scenario,
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        runtime=options.runtime,
        seed=options.seed,
        generated_mess_count=options.generated_mess_count,
        backend_instance=session.backend_instance,
        context_json=options.context_json,
        agibot_map_artifact_dir=options.agibot_map_artifact_dir,
    )
    preflight_agent_view = _load_json(preflight["agent_view"])
    waypoint_sequence = _load_json(preflight["waypoint_sequence"])
    metric_map = agent_view_module.base_metric_map(preflight_agent_view)
    static_fixture_projection = _load_json(preflight["static_fixture_projection"])
    subphase_reports = [
        _agent_view_stage_report(
            run_dir=run_dir,
            preflight=preflight,
            metric_map=metric_map,
        )
    ]
    _record(state.trace_events, state.started_at, "metric_map", {}, metric_map)
    return _RehearsalPreflightState(
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        preflight=preflight,
        waypoint_sequence=waypoint_sequence,
        subphase_reports=subphase_reports,
    )


def _agent_view_stage_report(
    *,
    run_dir: Path,
    preflight: dict[str, Path],
    metric_map: dict[str, Any],
) -> dict[str, Any]:
    return _write_stage_artifact(
        run_dir=run_dir,
        stage_dir=run_dir / "subphases" / "01-agent-view",
        stage="agent_view_export",
        status="ok",
        ok=True,
        tool_response=metric_map,
        artifacts={
            "metric_map": _relpath(preflight["metric_map"], run_dir),
            "static_fixture_projection": _relpath(preflight["static_fixture_projection"], run_dir),
            "agent_view": _relpath(preflight["agent_view"], run_dir),
            "scene_identity": _relpath(preflight["scene_identity"], run_dir),
            "map_preview": _relpath(preflight["map_preview"], run_dir),
            "waypoint_sequence": _relpath(preflight["waypoint_sequence"], run_dir),
            "runner_task_input": _relpath(preflight["runner_task_input"], run_dir),
        },
        note=(
            "Generated Agibot-shaped preflight artifacts from the simulated MolmoSpaces "
            "cleanup scene. No real Agibot map or GDK artifact was consumed."
        ),
    )


def _run_rehearsal_observe_navigation(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
) -> _ObserveNavigateResult:
    runtime_dir = run_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    selected_waypoint_id = options.waypoint_id or _first_waypoint_id_from_sequence(
        preflight.waypoint_sequence
    )
    observation = _run_rehearsal_observe_stage(
        run_dir=run_dir,
        runtime_dir=runtime_dir,
        session=session,
        state=state,
        options=options,
        preflight=preflight,
        waypoint_id=selected_waypoint_id,
    )
    navigation = _run_rehearsal_navigation_stage(
        run_dir=run_dir,
        runtime_dir=runtime_dir,
        session=session,
        state=state,
        options=options,
        preflight=preflight,
        waypoint_id=selected_waypoint_id,
    )
    return _ObserveNavigateResult(observation=observation, navigation=navigation)


def _run_rehearsal_observe_stage(
    *,
    run_dir: Path,
    runtime_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
    waypoint_id: str,
) -> dict[str, Any]:
    observation_image = _write_snapshot(
        runtime=options.runtime,
        contract=session.base_contract,
        scenario=session.scenario,
        output_path=runtime_dir / "policy_observation.png",
        title="Simulated policy observation",
    )
    observation = _simulated_observation(
        session.contract.observe(),
        observation_image=observation_image,
        run_dir=run_dir,
        runtime=options.runtime,
        metric_map=preflight.metric_map,
        waypoint_id=waypoint_id,
    )
    _write_json(runtime_dir / "observation.json", observation)
    preflight.subphase_reports.append(
        _observe_stage_report(run_dir=run_dir, observation=observation)
    )
    state.policy_events.append(_policy_event(len(state.policy_events), observation, "observe"))
    _record(
        state.trace_events,
        state.started_at,
        "observe",
        {"label": "pre_navigation"},
        observation,
    )
    return observation


def _observe_stage_report(*, run_dir: Path, observation: dict[str, Any]) -> dict[str, Any]:
    return _write_stage_artifact(
        run_dir=run_dir,
        stage_dir=run_dir / "subphases" / "02-observe",
        stage="observe",
        status="ok",
        ok=True,
        tool_response=observation,
        artifacts={"observation": "runtime/observation.json"},
        note=(
            "Simulated policy-camera observe evidence. This validates the public observe "
            "result shape, not a head_color GDK camera capture."
        ),
    )


def _run_rehearsal_navigation_stage(
    *,
    run_dir: Path,
    runtime_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
    waypoint_id: str,
) -> dict[str, Any]:
    navigation = _simulated_navigation(
        session.contract.navigate_to_waypoint(waypoint_id),
        metric_map=preflight.metric_map,
        waypoint_id=waypoint_id,
        runtime=options.runtime,
    )
    _write_json(runtime_dir / "navigation.json", navigation)
    preflight.subphase_reports.append(
        _navigation_stage_report(run_dir=run_dir, navigation=navigation)
    )
    state.policy_events.append(
        _policy_event(len(state.policy_events), navigation, "navigate_waypoint")
    )
    _record(
        state.trace_events,
        state.started_at,
        "navigate_to_waypoint",
        {"waypoint_id": waypoint_id},
        navigation,
    )
    if options.record_robot_views and navigation.get("ok"):
        state.robot_view_index = _record_robot_view(
            robot_view_steps=state.robot_view_steps,
            trace_events=state.trace_events,
            started_at=state.started_at,
            backend=session.base_contract.backend,
            run_dir=run_dir,
            index=state.robot_view_index,
            action=f"navigate_to_waypoint {waypoint_id}",
            label_suffix=f"navigate_waypoint_{waypoint_id}",
        )
    return navigation


def _navigation_stage_report(*, run_dir: Path, navigation: dict[str, Any]) -> dict[str, Any]:
    return _write_stage_artifact(
        run_dir=run_dir,
        stage_dir=run_dir / "subphases" / "03-navigate-waypoint",
        stage="navigate_waypoint",
        status="ok",
        ok=True,
        tool_response=navigation,
        artifacts={"navigation": "runtime/navigation.json"},
        note=(
            "Simulated waypoint navigation evidence with Agibot-shaped runner fields "
            "and MolmoSpaces simulation provenance."
        ),
    )


def _run_rehearsal_action_stage(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
) -> _RehearsalActionResult:
    if options.rehearsal_mode == REHEARSAL_MODE_CONTRACT:
        return _run_blocked_manipulation_stage(
            run_dir=run_dir,
            session=session,
            state=state,
            preflight=preflight,
        )
    return _run_cleanup_actions_stage(
        run_dir=run_dir,
        session=session,
        state=state,
        options=options,
        preflight=preflight,
    )


def _run_blocked_manipulation_stage(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    preflight: _RehearsalPreflightState,
) -> _RehearsalActionResult:
    manipulation_results = []
    for tool in BLOCKED_MANIPULATION_TOOLS:
        result = _blocked_manipulation(tool)
        manipulation_results.append(result)
        state.policy_events.append(
            _policy_event(len(state.policy_events), result, "blocked_manipulation")
        )
        _record(state.trace_events, state.started_at, tool, {}, result)
    _write_json(run_dir / "runtime" / "blocked_manipulation.json", manipulation_results)
    preflight.subphase_reports.append(
        _blocked_manipulation_stage_report(
            run_dir=run_dir,
            manipulation_results=manipulation_results,
        )
    )
    return _RehearsalActionResult(
        manipulation_results=manipulation_results,
        cleanup_actions=_empty_cleanup_actions_result(),
        final_locations=session.base_contract.backend.object_locations(),
        done_response=None,
    )


def _blocked_manipulation_stage_report(
    *,
    run_dir: Path,
    manipulation_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return _write_stage_artifact(
        run_dir=run_dir,
        stage_dir=run_dir / "subphases" / "04-blocked-manipulation",
        stage="blocked_manipulation",
        status="blocked_capability",
        ok=False,
        tool_response={"blocked_tools": manipulation_results},
        artifacts={"blocked_manipulation": "runtime/blocked_manipulation.json"},
        note="Manipulation tools are intentionally visible but blocked in this contract rehearsal.",
    )


def _run_cleanup_actions_stage(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
) -> _RehearsalActionResult:
    cleanup_actions = _run_cleanup_action_rehearsal(
        contract=session.contract,
        base_contract=session.base_contract,
        metric_map=preflight.metric_map,
        static_fixture_projection=preflight.static_fixture_projection,
        trace_events=state.trace_events,
        policy_events=state.policy_events,
        started_at=state.started_at,
        runtime=options.runtime,
        run_dir=run_dir,
        robot_view_steps=state.robot_view_steps,
        robot_view_index_ref=[state.robot_view_index],
        record_robot_views=options.record_robot_views,
        cleanup_object_count=options.cleanup_object_count,
    )
    state.robot_view_index = int(cleanup_actions.get("robot_view_index", state.robot_view_index))
    done_response = _record_action_done(
        contract=session.base_contract,
        trace_events=state.trace_events,
        started_at=state.started_at,
        runtime=options.runtime,
    )
    final_locations = dict(
        done_response.get("final_locations") or session.base_contract.backend.object_locations()
    )
    cleanup_actions["final_object_locations"] = final_locations
    _write_json(run_dir / "runtime" / "cleanup_actions.json", cleanup_actions)
    preflight.subphase_reports.append(
        _cleanup_actions_stage_report(run_dir=run_dir, cleanup_actions=cleanup_actions)
    )
    return _RehearsalActionResult(
        manipulation_results=[],
        cleanup_actions=cleanup_actions,
        final_locations=final_locations,
        done_response=done_response,
    )


def _cleanup_actions_stage_report(
    *,
    run_dir: Path,
    cleanup_actions: dict[str, Any],
) -> dict[str, Any]:
    completed_object_count = int(cleanup_actions.get("completed_object_count") or 0)
    return _write_stage_artifact(
        run_dir=run_dir,
        stage_dir=run_dir / "subphases" / "04-cleanup-actions",
        stage="cleanup_actions",
        status="ok" if completed_object_count else "partial",
        ok=bool(completed_object_count),
        tool_response=cleanup_actions,
        artifacts={"cleanup_actions": "runtime/cleanup_actions.json"},
        note=(
            "Opt-in simulated cleanup-action rehearsal. Pick/place effects are "
            "api_semantic MolmoSpaces state updates, not Agibot GDK manipulation or "
            "planner-backed proof."
        ),
    )


def _finalize_rehearsal_run(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
    observe_navigation: _ObserveNavigateResult,
    action_result: _RehearsalActionResult,
    before_snapshot: Path,
) -> dict[str, Any]:
    after_snapshot = _write_rehearsal_boundary_snapshot(
        run_dir=run_dir,
        session=session,
        state=state,
        options=options,
        filename="after.png",
        action="after",
        label_suffix="after",
        title="After MolmoSpaces Agibot contract rehearsal",
    )
    top_level_agent_view = _top_level_agent_view(
        session=session,
        options=options,
        preflight=preflight,
        observation=observe_navigation.observation,
    )
    substeps = semantic_substeps(state.trace_events, session.contract.public_receptacles_by_id())
    cleanup_primitive_evidence = cleanup_primitive_evidence_from_substeps(substeps)
    runtime_export = _write_rehearsal_runtime_export(
        run_dir=run_dir,
        options=options,
        preflight=preflight,
        observe_navigation=observe_navigation,
        action_result=action_result,
        substeps=substeps,
        robot_view_steps=state.robot_view_steps,
    )
    _write_json(run_dir / "agent_view.json", top_level_agent_view)
    trace_path = run_dir / "trace.jsonl"
    write_trace_jsonl(trace_path, state.trace_events)
    run_result = _build_and_write_rehearsal_result(
        run_dir=run_dir,
        session=session,
        state=state,
        options=options,
        preflight=preflight,
        observe_navigation=observe_navigation,
        action_result=action_result,
        top_level_agent_view=top_level_agent_view,
        runtime_export=runtime_export,
        trace_path=trace_path,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        substeps=substeps,
        cleanup_primitive_evidence=cleanup_primitive_evidence,
    )
    render_cleanup_report(
        run_dir=run_dir,
        scenario=session.scenario,
        run_result=run_result,
        trace_events=state.trace_events,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        robot_view_steps=state.robot_view_steps,
    )
    return run_result


def _top_level_agent_view(
    *,
    session: _ContractRehearsalSession,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
    observation: dict[str, Any],
) -> dict[str, Any]:
    if options.rehearsal_mode == REHEARSAL_MODE_CLEANUP_ACTIONS:
        return _agent_view_with_cleanup_actions(
            session.contract.agent_view_payload(),
            metric_map=preflight.metric_map,
            static_fixture_projection=preflight.static_fixture_projection,
            fallback_observation=observation,
        )
    return _agent_view_with_runtime_observation(
        metric_map=preflight.metric_map,
        static_fixture_projection=preflight.static_fixture_projection,
        observation=observation,
    )


def _write_rehearsal_runtime_export(
    *,
    run_dir: Path,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
    observe_navigation: _ObserveNavigateResult,
    action_result: _RehearsalActionResult,
    substeps: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime_export = _runtime_export(
        observation=observe_navigation.observation,
        navigation=observe_navigation.navigation,
        manipulation_results=action_result.manipulation_results,
        subphase_reports=preflight.subphase_reports,
        runtime=options.runtime,
        rehearsal_mode=options.rehearsal_mode,
        cleanup_actions=action_result.cleanup_actions,
        semantic_substeps=substeps,
        final_locations=action_result.final_locations,
        robot_view_steps=robot_view_steps,
    )
    _write_json(run_dir / "runtime" / "runtime_export.json", runtime_export)
    return runtime_export


def _build_and_write_rehearsal_result(
    *,
    run_dir: Path,
    session: _ContractRehearsalSession,
    state: _RehearsalTraceState,
    options: _ContractRehearsalOptions,
    preflight: _RehearsalPreflightState,
    observe_navigation: _ObserveNavigateResult,
    action_result: _RehearsalActionResult,
    top_level_agent_view: dict[str, Any],
    runtime_export: dict[str, Any],
    trace_path: Path,
    before_snapshot: Path,
    after_snapshot: Path,
    substeps: list[dict[str, Any]],
    cleanup_primitive_evidence: dict[str, Any],
) -> dict[str, Any]:
    run_result = _run_result(
        run_dir=run_dir,
        scenario=session.scenario,
        runtime=options.runtime,
        seed=options.seed,
        generated_mess_count=options.generated_mess_count,
        started_at=state.started_at,
        metric_map=preflight.metric_map,
        static_fixture_projection=preflight.static_fixture_projection,
        observation=observe_navigation.observation,
        navigation=observe_navigation.navigation,
        manipulation_results=action_result.manipulation_results,
        cleanup_actions=action_result.cleanup_actions,
        agent_view=top_level_agent_view,
        runtime_export=runtime_export,
        subphase_reports=preflight.subphase_reports,
        trace_path=trace_path,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        policy_events=state.policy_events,
        semantic_substeps=substeps,
        cleanup_primitive_evidence=cleanup_primitive_evidence,
        final_locations=action_result.final_locations,
        done_response=action_result.done_response,
        robot_view_steps=state.robot_view_steps,
        backend_instance=session.backend_instance,
        scene_identity_path=preflight.preflight["scene_identity"],
        map_preview_path=preflight.preflight["map_preview"],
        agibot_map_reference_path=preflight.preflight["agibot_map_reference"],
        rehearsal_mode=options.rehearsal_mode,
        record_robot_views=options.record_robot_views,
    )
    _write_json(run_dir / "run_result.json", run_result)
    return run_result
