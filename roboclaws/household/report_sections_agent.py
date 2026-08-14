from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any

from roboclaws.household.report_sections_agent_tables import (
    _base_metric_map,
    _camera_model_policy_evidence,
    _cleanup_policy_badges,
    _cleanup_policy_event_row,
    _cleanup_policy_metrics,
    _cleanup_worklist,
    _metric,
    _model_declared_observation_evidence,
    _observed_objects,
    _observed_objects_table,
    _raw_fpv_observations,
    _real_robot_readiness_badges,
    _real_robot_readiness_metrics,
    _real_robot_readiness_note,
    _requested_generated_text,
    _runtime_metric_map,
    runtime_metric_map_table,
    skill_scratchpad_table,
    worklist_summary_table,
)
from roboclaws.household.report_sections_robot import robot_view_camera_contract_summary

ViewFigureRenderer = Callable[[Any, str], str]


def agent_view_section(run_result: dict[str, Any]) -> str:
    if run_result.get("contract") != "realworld_cleanup_v1":
        return ""
    agent_view = run_result.get("agent_view") or {}
    if not isinstance(agent_view, dict) or not agent_view:
        return ""
    metric_map = _base_metric_map(agent_view)
    runtime_metric_map = run_result.get("runtime_metric_map") or _runtime_metric_map(agent_view)
    observed = _observed_objects(agent_view)
    raw_observations = _raw_fpv_observations(agent_view)
    worklist = _cleanup_worklist(agent_view)
    scratchpad = run_result.get("agent_scratchpad") or {}
    waypoints = metric_map.get("inspection_waypoints") or []
    rooms = (runtime_metric_map.get("static_map") or {}).get("fixtures") or []
    summary = (
        f"{len(metric_map.get('rooms') or [])} public rooms, "
        f"{len(rooms)} static fixture projection room rows, {len(waypoints)} inspection waypoints, "
        f"{len(observed)} observed object handles, "
        f"{len(raw_observations)} raw FPV observations."
    )
    sweep_note = (
        '<p class="note">Map Build Mode: cleanup actions were disabled. '
        "This report shows runtime-map evidence from public observations, not "
        "private cleanup target truth.</p>"
        if run_result.get("map_build_mode") is True
        else ""
    )
    return (
        '<section class="panel agent-view"><h2>Agent View</h2>'
        f'<p class="note">{html.escape(summary)} No Generated Mess Set, target count, '
        "acceptable destination sets, is_misplaced labels, or global movable-object "
        "inventory are present here.</p>"
        f"{sweep_note}"
        f"{runtime_metric_map_table(runtime_metric_map)}"
        f"{worklist_summary_table(worklist)}"
        f"{skill_scratchpad_table(scratchpad)}"
        f"{_observed_objects_table(agent_view, observed)}</section>"
    )


def cleanup_policy_trace_section(run_result: dict[str, Any]) -> str:
    trace = run_result.get("cleanup_policy_trace") or {}
    if not trace:
        return ""
    events = [item for item in trace.get("events") or [] if isinstance(item, dict)]
    has_review_fields = any(
        item.get("decision") or item.get("progress") or item.get("reason") for item in events
    )
    rows = [_cleanup_policy_event_row(item, has_review_fields) for item in events]
    review_headers = (
        "<th>Decision</th><th>Progress</th><th>Reason</th>" if has_review_fields else ""
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Tool</th>'
        "<th>Role</th><th>Waypoint</th><th>Object</th><th>Fixture</th>"
        f"{review_headers}</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    notes = [
        "inspection_waypoints are static_map_fixture_coverage inputs. Coverage scans, "
        "cleanup actions, and post-place observes are labelled so reviewers can tell "
        "whether the run was interleaved or survey-first. The current public MCP surface "
        "models open_receptacle and close_receptacle as semantic access state around "
        "place_inside."
    ]
    operator_review_note = str(trace.get("operator_review_note") or "").strip()
    if operator_review_note:
        notes.append(operator_review_note)
    note_html = "".join(f'<p class="note">{html.escape(note)}</p>' for note in notes)
    return (
        '<section class="panel cleanup-policy-trace">'
        "<h2>Waypoint Honesty & Cleanup Loop</h2>"
        f"{note_html}"
        f'{_cleanup_policy_metrics(trace)}<div class="badges">{_cleanup_policy_badges(trace)}</div>'
        f"{table}</section>"
    )


def evidence_lane_badges(run_result: dict[str, Any], badge_html) -> str:  # noqa: ANN001
    metadata = _evidence_lane_metadata(run_result)
    if not metadata:
        return ""
    camera_labeler = metadata.get("camera_labeler", run_result.get("camera_labeler", ""))
    return "".join(
        (
            badge_html(
                "Evidence lane",
                metadata.get("evidence_lane", run_result.get("evidence_lane", "")),
            ),
            badge_html("Camera labeler", camera_labeler) if camera_labeler else "",
            badge_html("Agent input", metadata.get("agent_input", "")),
            badge_html("Input provenance", metadata.get("input_provenance", "")),
            badge_html("Report", metadata.get("report", "")),
        )
    )


def raw_fpv_observations_section(
    run_result: dict[str, Any],
    *,
    view_figure: ViewFigureRenderer,
) -> str:
    if run_result.get("contract") != "realworld_cleanup_v1":
        return ""
    observations = run_result.get("raw_fpv_observations")
    if observations is None:
        observations = _raw_fpv_observations(run_result.get("agent_view") or {})
    if not observations:
        return ""
    cards = []
    for item in observations:
        artifacts = item.get("image_artifacts") or {}
        fpv_path = artifacts.get("fpv") or item.get("fpv_image")
        offset = item.get("camera_offset") or {}
        camera_contract = robot_view_camera_contract_summary(item.get("camera_control_contract"))
        cards.append(
            '<article class="raw-fpv-card">'
            "<div>"
            f"<h3>{html.escape(str(item.get('observation_id', 'observation')))}</h3>"
            f'<p class="pose">room={html.escape(str(item.get("room_id", "")))} '
            f"waypoint={html.escape(str(item.get('waypoint_id', '')))}</p>"
            f'<p class="pose">camera yaw={html.escape(str(offset.get("yaw_delta_deg", 0)))} '
            f"pitch={html.escape(str(offset.get('pitch_delta_deg', 0)))}</p>"
            f'<p class="note">{html.escape(str(item.get("artifact_status", "")))}</p>'
            f"{camera_contract}"
            "</div>"
            f"{view_figure(fpv_path, 'FPV')}"
            "</article>"
        )
    return (
        '<section class="panel raw-fpv-section"><h2>Raw FPV Observations</h2>'
        '<p class="note">Camera-only perception evidence: these rows provide FPV image '
        "artifacts without structured movable-object detections, categories, support "
        "estimates, target labels, or generated mess truth.</p>"
        '<div class="raw-fpv-grid">' + "".join(cards) + "</div></section>"
    )


def model_declared_observations_section(run_result: dict[str, Any]) -> str:
    evidence = run_result.get("model_declared_observation_evidence")
    if evidence is None:
        evidence = _model_declared_observation_evidence(run_result.get("agent_view") or {})
    observations = run_result.get("model_declared_observations") or evidence.get(
        "observations",
        [],
    )
    if not observations:
        return ""
    rows = []
    for item in observations:
        region = item.get("image_region") or {}
        evidence = item.get("visual_grounding_evidence") or {}
        pipeline = item.get("visual_grounding_pipeline") or {}
        overlay = str(item.get("visual_grounding_overlay") or "")
        overlay_cell = f'<a href="{html.escape(overlay)}">overlay</a>' if overlay else ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('source_observation_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('producer_type', '')))}</td>"
            f"<td>{html.escape(str(pipeline.get('pipeline_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('category', '')))}</td>"
            f"<td>{html.escape(str(item.get('target_fixture_id', '')))}</td>"
            f"<td>{html.escape(str(region.get('type', '')))}: "
            f"{html.escape(str(region.get('value', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('reviewability_status', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('image_bbox', '')))}</td>"
            f"<td>{html.escape(str(item.get('grounding_status', '')))} "
            f"({html.escape(str(item.get('grounding_confidence', '')))})</td>"
            f"<td>{html.escape(str(item.get('actionability_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('target_plausibility', {}).get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('acted_on', False)))}</td>"
            f"<td>{overlay_cell}</td>"
            f"<td>{html.escape(str(item.get('evidence_note', '')))}</td>"
            f"<td>{html.escape(str(item.get('recovery_hint', '')))}</td>"
            "</tr>"
        )
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('Declared', evidence.get('observation_count', len(observations)))}"
        f"{_metric('Resolved', evidence.get('resolved_count', 0))}"
        f"{_metric('Acted on', evidence.get('acted_count', 0))}"
        f"{_metric('Private truth', evidence.get('private_truth_included', False))}"
        "</div>"
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Source observation</th>'
        "<th>Producer</th><th>Pipeline</th><th>Handle</th><th>Category</th><th>Target fixture</th>"
        "<th>Image region</th><th>FPV reviewability</th><th>FPV bbox</th>"
        "<th>Grounding</th><th>Actionability</th><th>Target plausibility</th>"
        "<th>Acted on</th><th>Overlay</th><th>Evidence note</th><th>Recovery hint</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    return (
        '<section class="panel model-declared-observations">'
        "<h2>Model-Declared Observations</h2>"
        '<p class="note">Public camera evidence converted into observed handles. '
        "Grounding status shows whether the hidden resolver found an executable "
        "object without exposing private scoring truth.</p>"
        f"{metrics}{table}</section>"
    )


def camera_model_policy_section(run_result: dict[str, Any]) -> str:
    evidence = run_result.get("camera_model_policy_evidence")
    if evidence is None:
        evidence = _camera_model_policy_evidence(run_result.get("agent_view") or {})
    if not evidence or not evidence.get("enabled"):
        return ""
    rows = []
    for event in evidence.get("events") or []:
        handles = ", ".join(str(item) for item in event.get("registered_observed_handles") or [])
        pipeline = event.get("visual_grounding_pipeline") or {}
        stages = pipeline.get("stages") or []
        stage_text = ", ".join(
            str(stage.get("stage") or stage.get("producer_id") or "") for stage in stages
        )
        labeler = (
            evidence.get("camera_labeler")
            or run_result.get("camera_labeler")
            or pipeline.get(
                "pipeline_id",
                "",
            )
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(event.get('observation_id', '')))}</td>"
            f"<td>{html.escape(str(event.get('room_id', '')))}</td>"
            f"<td>{html.escape(str(labeler))}</td>"
            f"<td>{html.escape(str(pipeline.get('pipeline_id', '')))}</td>"
            f"<td>{html.escape(str(pipeline.get('status', '')))}</td>"
            f"<td>{html.escape(stage_text)}</td>"
            f"<td>{html.escape(str(pipeline.get('failure_reason', '')))}</td>"
            f"<td>{html.escape(str(event.get('candidate_count', 0)))}</td>"
            f"<td>{html.escape(handles)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="9">No camera-labeler candidate events recorded.</td></tr>')
    camera_labeler = evidence.get("camera_labeler", run_result.get("camera_labeler", ""))
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('Events', evidence.get('event_count', 0))}"
        f"{_metric('Candidates', evidence.get('candidate_count', 0))}"
        f"{_metric('Camera labeler', camera_labeler)}"
        f"{_metric('Service pipeline', evidence.get('visual_grounding_pipeline_id', 'sim'))}"
        f"{_metric('Failures', evidence.get('visual_grounding_failure_count', 0))}"
        f"{_metric('Duplicate rate', evidence.get('duplicate_rate', 0))}"
        f"{_metric('Model', evidence.get('model_provenance', 'unknown'))}"
        f"{_metric('Private truth', evidence.get('private_truth_included', 'unknown'))}"
        "</div>"
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Observation</th>'
        "<th>Room</th><th>Camera labeler</th><th>Service pipeline</th>"
        "<th>Status</th><th>Stages</th>"
        "<th>Failure reason</th><th>Candidates</th><th>Handles</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    note = evidence.get("policy_note") or (
        "Camera labeler candidates are model-labelled public observations, "
        "not private scoring truth."
    )
    return (
        '<section class="panel camera-model-policy"><h2>Camera Labeler Evidence</h2>'
        f'<p class="note">{html.escape(str(note))}</p>{metrics}{table}</section>'
    )


def advisory_review_section(run_result: dict[str, Any]) -> str:
    advisory = run_result.get("advisory_evaluation") or {}
    if not advisory:
        return ""
    rows = []
    for item in advisory.get("object_reviews") or []:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('actual_location_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('advisory_verdict', '')))}</td>"
            f"<td>{html.escape(str(item.get('rationale', '')))}</td>"
            "</tr>"
        )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Object</th>'
        "<th>Final location</th><th>Advisory verdict</th><th>Rationale</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    counts = advisory.get("counts") or {}
    summary = (
        f"{advisory.get('overall_verdict', 'unknown')} from "
        f"{advisory.get('evaluator', 'unknown')}; "
        f"authoritative={str(advisory.get('authoritative')).lower()}; "
        f"reviewed {counts.get('total_reviewed', 0)} objects."
    )
    note = advisory.get("non_authoritative_note") or advisory.get("summary") or ""
    return (
        '<section class="panel advisory-review"><h2>Advisory Review</h2>'
        f'<p class="note">{html.escape(summary)}</p>'
        f'<p class="note">{html.escape(str(note))}</p>{table}</section>'
    )


def private_evaluation_section(run_result: dict[str, Any]) -> str:
    if run_result.get("contract") != "realworld_cleanup_v1":
        return ""
    private = run_result.get("private_evaluation") or {}
    targets = private.get("generated_mess_set") or []
    destinations = private.get("acceptable_destination_sets") or {}
    rows = []
    for object_id in targets:
        destination_text = ", ".join(str(item) for item in destinations.get(object_id, []))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(object_id))}</td>"
            f"<td>{html.escape(destination_text)}</td>"
            "</tr>"
        )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Generated mess object</th>'
        "<th>Acceptable destination set</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )
    summary = (
        f"Generated mess count {private.get('generated_mess_count', 0)}"
        f"{_requested_generated_text(private)}; "
        f"mess restoration rate {private.get('mess_restoration_rate', 0)}; "
        f"sweep coverage rate {private.get('sweep_coverage_rate', 0)}; "
        f"disturbance count {private.get('disturbance_count', 0)}."
    )
    return (
        '<section class="panel private-evaluation"><h2>Private Evaluation</h2>'
        f'<p class="note">{html.escape(summary)}</p>{table}</section>'
    )


def _evidence_lane_metadata(run_result: dict[str, Any]) -> dict[str, Any]:
    metadata = run_result.get("evidence_lane_metadata")
    return metadata or run_result.get("cleanup_profile_metadata", {})


def real_robot_readiness_section(run_result: dict[str, Any]) -> str:
    readiness = run_result.get("real_robot_readiness") or {}
    if not readiness:
        return ""
    blockers = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in readiness.get("blocked_capabilities") or []
    )
    return (
        '<section class="panel real-robot-readiness">'
        "<h2>Real-Robot Readiness</h2>"
        f'<p class="note">{html.escape(_real_robot_readiness_note(readiness))}</p>'
        f"{_real_robot_readiness_metrics(readiness)}"
        f'<div class="badges">{_real_robot_readiness_badges(readiness)}</div>'
        f'<ul class="requirements">{blockers}</ul></section>'
    )
