from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household import profiles as evidence_profiles
from roboclaws.household.agibot_map_bundle import write_agibot_nav2_map_bundle
from roboclaws.household.agibot_operator_gates import (
    bounded_local_nudge_status,
    operator_localization_gate,
    operator_run_enablement_gate,
)
from roboclaws.household.agibot_sdk_contract import (
    BLOCKED_MANIPULATION_TOOLS,
    PHYSICAL_AGIBOT_PILOT_POLICY,
    PHYSICAL_AGIBOT_PILOT_SCHEMA,
)
from roboclaws.household.agibot_sdk_projection import (
    _agent_view_from_agibot_export,
    _dominant_primitive_provenance,
    _empty_score,
    _first_waypoint_id,
    _fixture_by_id,
    _initial_locations,
    _navigation_policy_progress,
    _observation_policy_progress,
    _policy_event,
    _preferred_verified_waypoint_id,
    _readiness_payload,
    _record,
    _relpath,
    _skipped_waypoint_policy_events,
    _subphase_reports,
)
from roboclaws.household.agibot_sdk_stage_execution import (
    AgibotSDKStageExecutionError,
    execute_agibot_sdk_stage,
)
from roboclaws.household.agibot_sdk_stage_execution import (
    load_json as _load_json,
)
from roboclaws.household.agibot_sdk_stage_execution import (
    redact_artifact_tree as _redact_artifact_tree,
)
from roboclaws.household.agibot_sdk_stage_execution import (
    redact_payload as _redact_payload,
)
from roboclaws.household.agibot_sdk_stage_execution import (
    resolve_executable as _resolve_executable,
)
from roboclaws.household.agibot_sdk_stage_execution import (
    write_json as _write_json,
)
from roboclaws.household.digital_twin_review_assets import attach_map12_review_assets
from roboclaws.household.household_runtime_contract import (
    REALWORLD_CONTRACT,
)
from roboclaws.household.manipulation_contract import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.report import render_cleanup_report
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import CleanupScenario


class AgibotSDKRunnerError(RuntimeError):
    """Raised when the SDK runner subprocess fails before writing artifacts."""


class AgibotSDKRunnerAdapter:
    """Subprocess boundary from Roboclaws semantic tools to the AgiBot SDK runner."""

    def __init__(
        self,
        *,
        context_json: Path,
        run_dir: Path,
        runner_script: Path,
        runner_python: str | Path,
        real_movement_enabled: bool = False,
        agibot_map_artifact_dir: Path,
    ) -> None:
        self.context_json = Path(context_json).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.runner_script = Path(runner_script).expanduser().resolve()
        try:
            self.runner_python = _resolve_executable(runner_python)
        except AgibotSDKStageExecutionError as exc:
            raise AgibotSDKRunnerError(str(exc)) from None
        self.real_movement_enabled = bool(real_movement_enabled)
        self.agibot_map_artifact_dir = Path(agibot_map_artifact_dir).expanduser().resolve()
        self._validate_dependencies()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.subphase_results: list[dict[str, Any]] = []
        self._agent_view_result: dict[str, Any] | None = None
        self._context_payload: dict[str, Any] | None = None

    def _validate_dependencies(self) -> None:
        invalid = []
        if not self.context_json.is_file():
            invalid.append("context_json")
        if not self.runner_script.is_file():
            invalid.append("runner_script")
        if not self.agibot_map_artifact_dir.is_dir():
            invalid.append("agibot_map_artifact_dir")
        if invalid:
            raise AgibotSDKRunnerError(
                "Agibot SDK runner dependency check failed: invalid " + ", ".join(invalid)
            )

    def _redactions(self) -> dict[str, str]:
        return {
            self.runner_python: "<runner-python>",
            str(self.runner_script): "<runner-script>",
            str(self.runner_script.parent.parent): "<runner-root>",
            str(self.context_json): "<context-json>",
            str(self.agibot_map_artifact_dir): "<agibot-map-artifact-dir>",
            str(self.run_dir): "<run-dir>",
        }

    @property
    def agent_view_path(self) -> Path:
        return self.run_dir / "subphases" / "01-agent-view" / "agent_view.json"

    @property
    def vendor_agent_view_path(self) -> Path:
        return self.run_dir / "subphases" / "01-agent-view" / "vendor_agent_view.json"

    @property
    def context_payload(self) -> dict[str, Any]:
        if self._context_payload is None:
            self._context_payload = _load_json(self.context_json)
        return self._context_payload

    def export_agent_view(self) -> dict[str, Any]:
        if self._agent_view_result is None:
            self._agent_view_result = self._run_stage(
                "01-agent-view",
                [
                    "agent-view",
                    "--context-json",
                    str(self.context_json),
                    "--output-dir",
                    str(self.run_dir / "subphases" / "01-agent-view"),
                ]
                + (
                    ["--agibot-map-artifact-dir", str(self.agibot_map_artifact_dir)]
                    if self.agibot_map_artifact_dir
                    else []
                ),
            )
            self._wrap_vendor_agent_view_export()
        return self._agent_view_result

    def _wrap_vendor_agent_view_export(self) -> None:
        stage_dir = self.agent_view_path.parent
        vendor_agent_view = _load_json(self.agent_view_path)
        metric_map = _load_json(stage_dir / "metric_map.json")
        static_fixture_projection = _load_json(stage_dir / "static_fixture_projection.json")
        shutil.copy2(self.agent_view_path, self.vendor_agent_view_path)
        public_agent_view = _agent_view_from_agibot_export(
            metric_map=metric_map,
            static_fixture_projection=static_fixture_projection,
            vendor_agent_view=vendor_agent_view,
        )
        agent_view_module.require_agent_view(public_agent_view)
        _write_json(self.agent_view_path, public_agent_view)

    def metric_map(self) -> dict[str, Any]:
        self.export_agent_view()
        return agent_view_module.base_metric_map(_load_json(self.agent_view_path))

    def static_fixture_projection(self) -> dict[str, Any]:
        self.export_agent_view()
        path = self.agent_view_path.parent / "static_fixture_projection.json"
        if path.is_file():
            return _load_json(path)
        return {
            "schema": "static_fixture_projection_v1",
            "rooms": [],
            "contains_runtime_observations": False,
        }

    def observe(self, *, label: str = "observe") -> dict[str, Any]:
        self.export_agent_view()
        gate_block = self._movement_gate_block(tool="observe")
        if gate_block is not None:
            gate_block.setdefault("observation_label", label)
            return gate_block
        args = [
            "observe",
            "--agent-view-json",
            str(self.vendor_agent_view_path),
            "--output-dir",
            str(self.run_dir / "subphases" / "02-observe"),
            "--camera",
            "head_color",
        ]
        if self.real_movement_enabled:
            args.append("--execute")
        result = self._run_stage("02-observe", args)
        response = dict(result.get("tool_response") or {})
        response.setdefault("observation_label", label)
        response.setdefault("agibot_sdk_report", _relpath(result["report_path"], self.run_dir))
        return response

    def navigate_to_waypoint(self, *, waypoint_id: str) -> dict[str, Any]:
        self.export_agent_view()
        gate_block = self._movement_gate_block(tool="navigate_to_waypoint")
        if gate_block is not None:
            gate_block.setdefault("waypoint_id", waypoint_id)
            return gate_block
        args = [
            "navigate-waypoint",
            "--agent-view-json",
            str(self.vendor_agent_view_path),
            "--output-dir",
            str(self.run_dir / "subphases" / "03-navigate-waypoint"),
            "--waypoint-id",
            waypoint_id,
        ]
        if self.real_movement_enabled:
            args.extend(
                ["--execute", "--arrival-observe", "--context-json", str(self.context_json)]
            )
        result = self._run_stage("03-navigate-waypoint", args)
        response = dict(result.get("tool_response") or {})
        response.setdefault("agibot_sdk_report", _relpath(result["report_path"], self.run_dir))
        return response

    def navigate_to_room(self, *, room_id: str) -> dict[str, Any]:
        metric_map = self.metric_map()
        waypoints = [
            item
            for item in metric_map.get("inspection_waypoints") or []
            if isinstance(item, dict) and str(item.get("room_id") or "") == room_id
        ]
        if not waypoints:
            return self._blocked_response(
                tool="navigate_to_room",
                failure_type="missing_room_waypoint",
                message=f"Room {room_id!r} does not resolve to a public inspection waypoint.",
                extra={"room_id": room_id},
            )
        waypoint_id = _preferred_verified_waypoint_id(waypoints) or str(
            waypoints[0].get("waypoint_id") or ""
        )
        response = dict(self.navigate_to_waypoint(waypoint_id=waypoint_id))
        response["tool"] = "navigate_to_room"
        response["room_id"] = room_id
        response["goal_source"] = "room_inspection_waypoint"
        return response

    def navigate_to_fixture_preferred_waypoint(self, *, fixture_id: str) -> dict[str, Any]:
        fixture = _fixture_by_id(self.static_fixture_projection(), fixture_id)
        waypoint_id = str(
            (fixture or {}).get("preferred_manipulation_waypoint_id")
            or (fixture or {}).get("preferred_inspection_waypoint_id")
            or ""
        )
        if not fixture or not waypoint_id:
            response = self._blocked_response(
                tool="navigate_to_receptacle",
                failure_type="missing_fixture_preferred_waypoint",
                message=f"Fixture {fixture_id!r} does not resolve to a public preferred waypoint.",
            )
        else:
            response = self.navigate_to_waypoint(waypoint_id=waypoint_id)
            response = dict(response)
            response["tool"] = "navigate_to_receptacle"
        response["fixture_id"] = fixture_id
        response["receptacle_id"] = fixture_id
        response["preferred_waypoint_id"] = waypoint_id
        response["manipulation_ready"] = False
        return response

    def navigate_to_object(
        self,
        *,
        object_id: str,
        waypoint_id: str = "",
        fixture_id: str = "",
    ) -> dict[str, Any]:
        if waypoint_id:
            response = dict(self.navigate_to_waypoint(waypoint_id=waypoint_id))
        elif fixture_id:
            response = dict(self.navigate_to_fixture_preferred_waypoint(fixture_id=fixture_id))
        else:
            response = self._blocked_response(
                tool="navigate_to_object",
                failure_type="object_not_mapped_to_public_waypoint",
                message=(
                    f"Object {object_id!r} does not resolve to a verified public waypoint "
                    "in the AgiBot pilot map context."
                ),
            )
        response["tool"] = "navigate_to_object"
        response["object_id"] = object_id
        response["fixture_id"] = fixture_id
        response["manipulation_ready"] = False
        return response

    def navigate_to_visual_candidate(
        self,
        *,
        source_observation_id: str,
        candidate_id: str = "",
        waypoint_id: str = "",
        fixture_id: str = "",
        target_fixture_id: str = "",
    ) -> dict[str, Any]:
        resolved_fixture_id = fixture_id or target_fixture_id
        if waypoint_id:
            response = dict(self.navigate_to_waypoint(waypoint_id=waypoint_id))
        elif resolved_fixture_id:
            response = dict(
                self.navigate_to_fixture_preferred_waypoint(fixture_id=resolved_fixture_id)
            )
        else:
            response = self._blocked_response(
                tool="navigate_to_visual_candidate",
                failure_type="visual_candidate_not_mapped_to_public_waypoint",
                message=(
                    "Visual candidate navigation requires a verified waypoint or "
                    "fixture-preferred waypoint in the AgiBot pilot map context."
                ),
            )
        response["tool"] = "navigate_to_visual_candidate"
        response["source_observation_id"] = source_observation_id
        response["candidate_id"] = candidate_id
        response["fixture_id"] = resolved_fixture_id
        response["target_fixture_id"] = target_fixture_id
        response["bounded_local_nudge"] = bounded_local_nudge_status(
            enabled=False,
            context=self.context_payload,
        )
        response["manipulation_ready"] = False
        return response

    def blocked_manipulation(
        self,
        *,
        tool: str,
        reason: str = "physical_manipulation_unproven",
    ) -> dict[str, Any]:
        return self._blocked_response(tool=tool, failure_type=reason, message=reason)

    def _blocked_response(
        self,
        *,
        tool: str,
        failure_type: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = {
            "ok": False,
            "tool": tool,
            "status": "blocked_capability",
            "contract": REALWORLD_CONTRACT,
            "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
            "error_reason": "blocked_capability",
            "failure_type": failure_type,
            "backend_error_summary": message,
            "physical_navigation_pilot": True,
            "physical_cleanup_ready": False,
            "manipulation_ready": False,
        }
        if extra:
            response.update(extra)
        return response

    def _movement_gate_block(self, *, tool: str) -> dict[str, Any] | None:
        if not self.real_movement_enabled:
            return None
        context = self.context_payload
        localization_gate = operator_localization_gate(context)
        run_gate = operator_run_enablement_gate(context, movement_enabled=True)
        if not localization_gate["ok"]:
            return self._blocked_response(
                tool=tool,
                failure_type="operator_localization_gate_not_confirmed",
                message="Operator localization gate is required before AgiBot real movement.",
                extra={
                    "operator_localization_gate": localization_gate,
                    "operator_run_enablement_gate": run_gate,
                    "human_takeover_stop": True,
                },
            )
        if not run_gate["ok"]:
            return self._blocked_response(
                tool=tool,
                failure_type="operator_run_enablement_gate_not_confirmed",
                message="Operator run enablement gate is required before AgiBot real movement.",
                extra={
                    "operator_localization_gate": localization_gate,
                    "operator_run_enablement_gate": run_gate,
                    "human_takeover_stop": True,
                },
            )
        return None

    def _run_stage(self, stage_name: str, args: list[str]) -> dict[str, Any]:
        try:
            result = execute_agibot_sdk_stage(
                stage_name=stage_name,
                args=args,
                run_dir=self.run_dir,
                runner_python=self.runner_python,
                runner_script=self.runner_script,
                redactions=self._redactions(),
            )
        except AgibotSDKStageExecutionError as exc:
            raise AgibotSDKRunnerError(str(exc)) from None
        self.subphase_results.append(result)
        if result["returncode"] and stage_name == "01-agent-view":
            raise AgibotSDKRunnerError(
                f"SDK runner agent-view export failed: exit={result['returncode']}"
            )
        return result


def run_physical_agibot_cleanup_pilot(
    *,
    run_dir: Path,
    context_json: Path,
    runner_script: Path,
    runner_python: str | Path,
    real_movement_enabled: bool = False,
    agibot_map_artifact_dir: Path,
    waypoint_id: str | None = None,
    scenario: CleanupScenario | None = None,
) -> dict[str, Any]:
    """Run the AgiBot real-robot cleanup backend pilot through the SDK CLI boundary."""
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    scenario = scenario or build_cleanup_scenario(seed=7)
    adapter = AgibotSDKRunnerAdapter(
        context_json=context_json,
        run_dir=run_dir,
        runner_script=runner_script,
        runner_python=runner_python,
        real_movement_enabled=real_movement_enabled,
        agibot_map_artifact_dir=agibot_map_artifact_dir,
    )
    started_at = time.time()
    trace_events: list[dict[str, Any]] = []
    policy_events: list[dict[str, Any]] = []
    before_snapshot = write_state_snapshot(
        scenario,
        _initial_locations(scenario),
        run_dir / "before.png",
        title="Before physical AgiBot pilot",
    )
    after_snapshot = write_state_snapshot(
        scenario,
        _initial_locations(scenario),
        run_dir / "after.png",
        title="After physical AgiBot pilot",
    )

    metric_map = adapter.metric_map()
    static_fixture_projection = adapter.static_fixture_projection()
    _record(trace_events, started_at, "metric_map", {}, metric_map)
    _record(trace_events, started_at, "static_fixture_projection", {}, static_fixture_projection)

    observation = adapter.observe(label="pre_navigation")
    policy_events.append(
        _policy_event(
            len(policy_events),
            observation,
            "pre_navigation_observe",
            decision="observe_head_color",
            progress=_observation_policy_progress(observation),
            reason=(
                "The pilot observes the robot-local head_color policy camera before "
                "navigation so the operator can review perception evidence separately "
                "from movement."
            ),
        )
    )
    _record(trace_events, started_at, "observe", {"label": "pre_navigation"}, observation)

    waypoint_id = waypoint_id or _first_waypoint_id(metric_map)
    navigation = adapter.navigate_to_waypoint(waypoint_id=waypoint_id)
    policy_events.append(
        _policy_event(
            len(policy_events),
            navigation,
            "inspection_waypoint",
            decision="visit_public_waypoint",
            progress=_navigation_policy_progress(
                navigation,
                waypoint_id=waypoint_id,
                real_movement_enabled=real_movement_enabled,
            ),
            reason=(
                "The pilot selected one verified generated/public waypoint from the "
                "agent-facing metric map and routed it through navigate_to_waypoint."
            ),
        )
    )
    policy_events.extend(
        _skipped_waypoint_policy_events(
            policy_events=policy_events,
            metric_map=metric_map,
            selected_waypoint_id=waypoint_id,
        )
    )
    _record(
        trace_events,
        started_at,
        "navigate_to_waypoint",
        {"waypoint_id": waypoint_id},
        navigation,
    )

    manipulation_results = []
    for tool in BLOCKED_MANIPULATION_TOOLS:
        result = adapter.blocked_manipulation(tool=tool)
        manipulation_results.append(result)
        policy_events.append(
            _policy_event(
                len(policy_events),
                result,
                "blocked_manipulation",
                decision="block_manipulation",
                progress=(
                    "Physical manipulation is intentionally blocked: "
                    f"{tool} returned blocked_capability."
                ),
                reason=(
                    "Navigation + perception pilot evidence is allowed, but physical "
                    "cleanup is not ready until hardware pick/place proof and operator "
                    "safety approval exist."
                ),
            )
        )
        _record(trace_events, started_at, tool, {}, result)

    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in trace_events),
        encoding="utf-8",
    )

    readiness = _readiness_payload(
        context=adapter.context_payload,
        metric_map=metric_map,
        static_fixture_projection=static_fixture_projection,
        observation=observation,
        navigation=navigation,
        manipulation_results=manipulation_results,
        real_movement_enabled=real_movement_enabled,
    )
    subphase_reports = _subphase_reports(adapter.subphase_results, run_dir)
    nav2_map_bundle = (
        write_agibot_nav2_map_bundle(
            source_map_dir=Path(agibot_map_artifact_dir),
            context_json=context_json,
            bundle_dir=run_dir / "map_bundle",
        )
        if agibot_map_artifact_dir is not None
        else {}
    )
    if nav2_map_bundle:
        readiness["map_bundle_snapshot_present"] = bool(nav2_map_bundle.get("snapshot_complete"))
        readiness["map_bundle_artifact_count"] = len(nav2_map_bundle.get("artifact_hashes") or {})
        readiness["map_bundle_parameter_hash"] = nav2_map_bundle.get("parameter_hash", "")
        readiness["map_bundle_snapshot_root"] = nav2_map_bundle.get("snapshot_root", "")
    agent_view = _load_json(adapter.agent_view_path)
    agent_view_module.require_agent_view(agent_view)
    run_result = {
        "schema": PHYSICAL_AGIBOT_PILOT_SCHEMA,
        "contract": REALWORLD_CONTRACT,
        "evidence_lane": evidence_profiles.PHYSICAL_ROBOT_EVIDENCE_LANE,
        "evidence_lane_metadata": evidence_profiles.agibot_gdk_evidence_metadata(),
        "backend": evidence_profiles.AGIBOT_SDK_RUNNER_BACKEND,
        "backend_variant": evidence_profiles.AGIBOT_GDK_BACKEND_VARIANT,
        "policy": PHYSICAL_AGIBOT_PILOT_POLICY,
        "agent_driven": False,
        "mcp_server": "roboclaws_physical_robot_evidence_cli_boundary",
        "scenario_id": scenario.scenario_id,
        "task_prompt": scenario.task,
        "seed": scenario.seed,
        "cleanup_status": readiness["status"],
        "primitive_provenance": _dominant_primitive_provenance([navigation, observation]),
        "generated_mess_count": 0,
        "requested_generated_mess_count": 0,
        "sweep_coverage_rate": 1.0 if observation.get("ok") else 0.0,
        "disturbance_count": 0,
        "score": _empty_score(),
        "private_evaluation": {
            "generated_mess_count": 0,
            "generated_mess_set": [],
            "acceptable_destination_sets": {},
            "mess_restoration_rate": 0.0,
            "sweep_coverage_rate": 1.0 if observation.get("ok") else 0.0,
            "disturbance_count": 0,
            "public_contract_note": "AgiBot physical pilot does not run private cleanup scoring.",
        },
        "agent_view": agent_view,
        "cleanup_policy_trace": {
            "schema": "cleanup_policy_trace_v1",
            "agent_review_kind": "agibot_navigation_perception_pilot_review",
            "agent_reasoning_visible": True,
            "waypoint_source": "agibot_sdk_agent_view_export",
            "loop_style": "physical_agibot_navigation_perception_pilot",
            "total_waypoints": len(metric_map.get("inspection_waypoints") or []),
            "selected_waypoint_id": waypoint_id,
            "skipped_waypoint_count": sum(
                1 for item in policy_events if item.get("decision") == "skip_public_waypoint"
            ),
            "observed_waypoint_count": 1 if observation.get("ok") else 0,
            "scan_observe_count": 1,
            "cleanup_action_count": 0,
            "placed_object_count": 0,
            "post_place_observe_count": 0,
            "first_cleanup_before_full_survey": False,
            "events": policy_events,
            "public_contract_note": (
                "Roboclaws owns the cleanup-shaped session and calls the AgiBot SDK "
                "runner at semantic tool granularity."
            ),
            "operator_review_note": (
                "Agibot pilot progress records the visible tool choice, decision, "
                "progress, and reason for each visited or skipped public waypoint."
            ),
        },
        "semantic_substeps": [],
        "real_robot_readiness": readiness,
        "nav2_map_bundle": nav2_map_bundle,
        "agibot_sdk_runner": {
            "schema": "agibot_sdk_runner_boundary_v1",
            "backend_variant": evidence_profiles.AGIBOT_GDK_BACKEND_VARIANT,
            "runner_script_configured": True,
            "agibot_map_artifact_dir_configured": True,
            "real_movement_enabled": real_movement_enabled,
            "subphase_reports": subphase_reports,
            "gdk_imported_by_roboclaws": False,
            "public_tool_boundary": [
                "metric_map",
                "static_fixture_projection",
                "observe",
                "navigate_to_waypoint",
                "navigate_to_room",
                "navigate_to_receptacle",
                "navigate_to_object",
                "navigate_to_visual_candidate",
                "done",
            ],
        },
        "physical_agibot_pilot": {
            "schema": PHYSICAL_AGIBOT_PILOT_SCHEMA,
            "observation": observation,
            "navigation_attempt": navigation,
            "blocked_manipulation_results": manipulation_results,
        },
        "manipulation_evidence": {
            "schema": "physical_manipulation_block_v1",
            "status": "blocked_capability",
            "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
            "planner_backed": False,
            "strict_proof_eligible": False,
            "api_semantic_state_edits": 0,
            "evidence_note": "First physical AgiBot pilot intentionally blocks manipulation.",
            "blockers": [str(item["tool"]) for item in manipulation_results],
            "strict_proof_requirements": [
                "planner-backed manipulation binding",
                "operator safety approval",
                "hardware pick/place validation",
            ],
        },
        "artifacts": {
            "run_result": "run_result.json",
            "trace": "trace.jsonl",
            "before_snapshot": "before.png",
            "after_snapshot": "after.png",
            "report": "report.html",
            "agibot_subphases": "subphases",
        },
        "runtime_timing": {
            "total_elapsed_s": time.time() - started_at,
            "tool_handler_s": 0.0,
            "robot_view_capture_s": 0.0,
            "between_tool_gap_s": 0.0,
            "tool_call_count": len(trace_events) // 2,
        },
    }
    if nav2_map_bundle:
        run_result["artifacts"]["map_bundle"] = "map_bundle"
        run_result["artifacts"]["nav2_map_yaml"] = "map_bundle/map.yaml"
        run_result["artifacts"]["nav2_occupancy_image"] = "map_bundle/map.pgm"
        run_result["artifacts"]["nav2_map_preview"] = "map_bundle/preview.png"
    attach_map12_review_assets(run_dir, adapter.context_payload, run_result)
    run_result = _redact_payload(run_result, adapter._redactions())
    (run_dir / "run_result.json").write_text(
        json.dumps(run_result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_cleanup_report(
        run_dir=run_dir,
        scenario=scenario,
        run_result=run_result,
        trace_events=trace_events,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        robot_view_steps=[],
    )
    _redact_artifact_tree(run_dir, adapter._redactions())
    return run_result
