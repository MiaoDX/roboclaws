"""Agent View, runtime-map, and readiness report tables."""

from __future__ import annotations

import html
from typing import Any

from roboclaws.household import agent_view as agent_view_module


def runtime_metric_map_table(runtime_metric_map: dict[str, Any]) -> str:
    if not runtime_metric_map:
        return ""
    static_map = runtime_metric_map.get("static_map") or {}
    anchors = runtime_metric_map.get("public_semantic_anchors") or []
    observed = runtime_metric_map.get("observed_objects") or []
    target_candidates = runtime_metric_map.get("target_candidates") or []
    target_search = runtime_metric_map.get("target_search_summary") or {}
    candidates = runtime_metric_map.get("map_update_candidates") or []
    generated = runtime_metric_map.get("generated_exploration_candidates") or []
    producer_summary = runtime_metric_map.get("producer_summary") or {}
    producer_types = producer_summary.get("public_semantic_anchor_producer_types") or {}
    provenance = ", ".join(sorted(str(item) for item in producer_types)) or "unavailable"
    coverage = target_search.get("viewpoint_budget") or runtime_metric_map.get(
        "coverage_summary", {}
    )
    if isinstance(coverage, dict):
        visited = coverage.get("visited_waypoint_count", coverage.get("visited", "unavailable"))
        total = coverage.get(
            "total_public_waypoints",
            coverage.get("total_waypoint_count", coverage.get("total", "unavailable")),
        )
        coverage_text = f"{visited}/{total} public waypoints"
    else:
        coverage_text = str(coverage or "unavailable")
    summary = (
        f"schema={runtime_metric_map.get('schema', '')}, "
        f"static fixtures={len(static_map.get('fixtures') or [])}, "
        f"public semantic anchors={len(anchors)}, "
        f"observed objects={len(observed)}, target candidates={len(target_candidates)}, "
        f"update candidates={len(candidates)}, "
        f"generated exploration candidates={len(generated)}, "
        f"coverage={coverage_text}, public provenance={provenance}, "
        f"source map mutated={runtime_metric_map.get('source_map_mutated')}"
    )
    candidate_note = (
        "<p>No map update candidates proposed.</p>"
        if not candidates
        else f"<p>{len(candidates)} map update candidates proposed for review.</p>"
    )
    return (
        "<h3>Runtime Metric Map</h3>"
        f'<p class="note">{html.escape(summary)}. Static map, observed objects, '
        "public semantic anchors, and map update candidates remain separate.</p>"
        f"{_semantic_anchor_table(anchors)}{_runtime_observed_table(observed)}"
        f"{_target_candidates_section(target_candidates, target_search)}{candidate_note}"
    )


def worklist_summary_table(worklist: dict[str, Any]) -> str:
    objects = worklist.get("objects") or []
    if not objects:
        return ""
    rows = []
    for item in objects:
        evidence = item.get("visual_grounding_evidence") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('state', '')))}</td>"
            f"<td>{html.escape(str(item.get('category', '')))}</td>"
            f"<td>{html.escape(str(item.get('source_fixture_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('candidate_fixture_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('actionability_status', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('reviewability_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('last_waypoint_id', '')))}</td>"
            "</tr>"
        )
    return (
        "<h3>Observed Handle Lifecycle</h3>"
        '<div class="table-wrap"><table><thead><tr><th>Handle</th><th>State</th>'
        "<th>Category</th><th>Seen at fixture</th><th>Public candidate fixture</th>"
        "<th>Actionability</th><th>FPV reviewability</th><th>Last waypoint</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def skill_scratchpad_table(scratchpad: dict[str, Any]) -> str:
    if not scratchpad:
        return ""
    handles = scratchpad.get("observed_handles") or {}
    notes = scratchpad.get("notes") or []
    return (
        "<h3>Skill Scratchpad</h3>"
        '<p class="note">Non-authoritative agent notes. Cleanup Worklist facts '
        "remain authoritative for done gates, reports, and checkers.</p>"
        '<div class="metric-grid">'
        f"{_metric('Schema', scratchpad.get('schema', ''))}"
        f"{_metric('Authoritative', _yes_no(bool(scratchpad.get('authoritative'))))}"
        f"{_metric('Scratch handles', len(handles))}"
        f"{_metric('Notes', len(notes))}"
        "</div>"
    )


def _observed_objects_table(agent_view: dict[str, Any], observed: list[dict[str, Any]]) -> str:
    mode = _perception_mode(agent_view) or "visible_object_detections"
    if mode == "raw_fpv_only":
        return (
            '<p class="note">Raw FPV-only mode is active. Structured movable-object '
            "detections, categories, support estimates, target labels, and generated "
            "mess truth are not present in Agent View.</p>"
        )
    if mode == "camera_model_policy":
        return _camera_model_observed_table(observed)
    return _visible_object_observed_table(observed)


def _camera_model_observed_table(observed: list[dict[str, Any]]) -> str:
    rows = []
    for item in observed:
        support = item.get("support_estimate") or {}
        evidence = item.get("visual_grounding_evidence") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('category', '')))}</td>"
            f"<td>{html.escape(str(support.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('source_observation_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('model_provenance', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('reviewability_status', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('image_bbox', '')))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>No camera-model candidates registered.</p>"
    return (
        '<div class="table-wrap"><table><thead><tr><th>Observed handle</th>'
        "<th>Category</th><th>Support estimate</th><th>Raw observation</th>"
        "<th>Model provenance</th><th>FPV reviewability</th><th>FPV bbox</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _visible_object_observed_table(observed: list[dict[str, Any]]) -> str:
    rows = []
    for item in observed:
        support = item.get("support_estimate") or {}
        evidence = item.get("visual_grounding_evidence") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('category', '')))}</td>"
            f"<td>{html.escape(str(item.get('current_room_id', '')))}</td>"
            f"<td>{html.escape(str(support.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('reviewability_status', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('image_bbox', '')))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>No objects observed.</p>"
    return (
        '<div class="table-wrap"><table><thead><tr><th>Observed handle</th>'
        "<th>Category</th><th>Room</th><th>Support estimate</th>"
        "<th>FPV reviewability</th><th>FPV bbox</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _semantic_anchor_table(anchors: list[dict[str, Any]]) -> str:
    rows = []
    for item in anchors:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('anchor_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('anchor_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('category', '')))}</td>"
            f"<td>{html.escape(str(item.get('waypoint_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('producer_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('promotion_status', '')))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>No public semantic anchors yet.</p>"
    return (
        '<div class="table-wrap"><table><thead><tr><th>Anchor</th>'
        "<th>Type</th><th>Category</th><th>Waypoint</th>"
        "<th>Producer</th><th>Promotion</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _runtime_observed_table(observed: list[dict[str, Any]]) -> str:
    rows = []
    for item in observed:
        evidence = item.get("visual_grounding_evidence") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('category', '')))}</td>"
            f"<td>{html.escape(str(item.get('state', '')))}</td>"
            f"<td>{html.escape(str(item.get('actionability', '')))}</td>"
            f"<td>{html.escape(str(item.get('producer_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('source_observation_id', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('reviewability_status', '')))}</td>"
            f"<td>{html.escape(str(evidence.get('image_bbox', '')))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>No runtime observed objects yet.</p>"
    return (
        '<div class="table-wrap"><table><thead><tr><th>Handle</th>'
        "<th>Category</th><th>State</th><th>Actionability</th>"
        "<th>Producer</th><th>Observation</th><th>FPV reviewability</th>"
        "<th>FPV bbox</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _target_candidates_section(
    target_candidates: list[dict[str, Any]],
    target_search: dict[str, Any],
) -> str:
    target_rows = []
    for item in target_candidates:
        budget = item.get("inspection_budget") or {}
        target_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('candidate_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('candidate_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('label', '')))}</td>"
            f"<td>{html.escape(str(item.get('waypoint_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('target_actionability_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('evidence_lane', '')))}</td>"
            f"<td>{html.escape(str(budget.get('observation_count', '')))}</td>"
            f"<td>{html.escape(str(budget.get('camera_adjustment_attempt_count', '')))}</td>"
            f"<td>{html.escape(str(item.get('rejection_reason', '')))}</td>"
            "</tr>"
        )
    target_table = (
        "<p>No target candidates yet.</p>"
        if not target_rows
        else (
            '<div class="table-wrap"><table><thead><tr><th>Candidate</th>'
            "<th>Type</th><th>Label</th><th>Waypoint</th><th>Actionability</th>"
            "<th>Lane</th><th>Observes</th><th>Camera adjusts</th><th>Reason</th>"
            "</tr></thead><tbody>" + "".join(target_rows) + "</tbody></table></div>"
        )
    )
    budget = target_search.get("viewpoint_budget") or {}
    camera_budget = target_search.get("camera_adjustment_budget") or {}
    return (
        "<h3>Target Candidates</h3>"
        f'<p class="note">Public target search budget: '
        f"{html.escape(str(budget.get('visited_waypoint_count', 0)))} visited / "
        f"{html.escape(str(budget.get('total_public_waypoints', 0)))} waypoints, "
        f"{html.escape(str(camera_budget.get('attempt_count', 0)))} camera adjustments. "
        f"{html.escape(str(target_search.get('missing_target_policy', '')))}</p>"
        f"{target_table}"
    )


def _cleanup_policy_event_row(item: dict[str, Any], has_review_fields: bool) -> str:
    review_cells = ""
    if has_review_fields:
        review_cells = (
            f"<td>{html.escape(str(item.get('decision', '')))}</td>"
            f"<td>{html.escape(str(item.get('progress', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
        )
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('index', '')))}</td>"
        f"<td>{html.escape(str(item.get('tool', '')))}</td>"
        f"<td>{html.escape(str(item.get('role', '')))}</td>"
        f"<td>{html.escape(str(item.get('waypoint_id', '')))}</td>"
        f"<td>{html.escape(str(item.get('object_id', '')))}</td>"
        f"<td>{html.escape(str(item.get('fixture_id', '')))}</td>"
        f"{review_cells}"
        "</tr>"
    )


def _cleanup_policy_metrics(trace: dict[str, Any]) -> str:
    return (
        '<div class="metric-grid">'
        f"{_metric('Waypoint source', trace.get('waypoint_source', 'unknown'))}"
        f"{_metric('Loop style', trace.get('loop_style', 'unknown'))}"
        f"{_metric('Review kind', trace.get('agent_review_kind', 'n/a'))}"
        f"{_metric('Waypoint observes', trace.get('scan_observe_count', 0))}"
        f"{_metric('Cleanup actions', trace.get('cleanup_action_count', 0))}"
        f"{_metric('Post-place observes', trace.get('post_place_observe_count', 0))}"
        "</div>"
    )


def _cleanup_policy_badges(trace: dict[str, Any]) -> str:
    return "".join(
        (
            _badge(
                "First cleanup before full survey",
                trace.get("first_cleanup_before_full_survey", False),
            ),
            _badge("Agent reasoning visible", trace.get("agent_reasoning_visible", False)),
        )
    )


def _real_robot_readiness_metrics(readiness: dict[str, Any]) -> str:
    nav_summary = ", ".join(
        f"{key}={value}"
        for key, value in (readiness.get("navigation_backend_summary") or {}).items()
    )
    pose_summary = ", ".join(
        f"{key}={value}" for key, value in (readiness.get("pose_source_summary") or {}).items()
    )
    return (
        '<div class="metric-grid">'
        f"{_metric('Status', readiness.get('status', 'unknown'))}"
        f"{_metric('Map bundle', readiness.get('map_bundle_schema', 'unknown'))}"
        f"{_metric('Navigation backends', nav_summary or 'none')}"
        f"{_metric('Pose sources', pose_summary or 'none')}"
        f"{_metric('Backend variant', readiness.get('backend_variant', 'n/a'))}"
        f"{_metric('Movement enabled', readiness.get('movement_enabled', 'n/a'))}"
        f"{_metric('Report-only sim views', readiness.get('report_only_simulation_view_count', 0))}"
        f"{_metric('physical_navigation_pilot', readiness.get('physical_navigation_pilot', False))}"
        f"{_metric('physical_cleanup_ready', readiness.get('physical_cleanup_ready', False))}"
        "</div>"
    )


def _real_robot_readiness_badges(readiness: dict[str, Any]) -> str:
    return "".join(
        (
            _badge("Map shape", readiness.get("map_bundle_fields_present", False)),
            _badge("PoseStamped waypoints", readiness.get("pose_stamped_waypoints", False)),
            _badge("Public static map", readiness.get("public_static_map", False)),
            _badge(
                "Chase excluded from policy",
                readiness.get("policy_view_chase_excluded", False),
            ),
            _badge("Sim/static navigation only", readiness.get("semantic_navigation_only", False)),
            _badge(
                "Static costmap routes",
                readiness.get("sim_costmap_route_validation", False),
            ),
            _badge("Physical navigation pilot", readiness.get("physical_navigation_pilot", False)),
            _badge("Manipulation blocked", readiness.get("manipulation_blocked", False)),
        )
    )


def _real_robot_readiness_note(readiness: dict[str, Any]) -> str:
    if readiness.get("backend_variant") == "molmospaces_sim":
        return (
            "This section is a MolmoSpaces Agibot Contract Rehearsal. It validates "
            "household contract shape, Agibot-shaped stage sequencing, "
            "and simulated observe/navigation evidence. It is not physical Agibot "
            "GDK execution, not a real movement gate, and not manipulation proof."
        )
    if readiness.get("backend_variant") == "agibot_gdk":
        movement_flag = str(readiness.get("movement_enabled", False)).lower()
        return (
            "This section is an AgiBot Navigation + Perception Pilot. Roboclaws keeps "
            "the household public tool boundary while the AgiBot SDK runner "
            "owns GDK execution evidence and per-stage reports. Navigation is physical "
            "only when the session-level movement gate is enabled; "
            f"movement_enabled={movement_flag}, "
            "physical_cleanup_ready=false."
        )
    if readiness.get("physical_navigation_pilot"):
        physical_flags = (
            f"physical_navigation_pilot={str(readiness.get('physical_navigation_pilot')).lower()}, "
            f"physical_cleanup_ready={str(readiness.get('physical_cleanup_ready')).lower()}."
        )
        return (
            "This section is a physical Navigation + Perception Pilot. Backend waypoint "
            "navigation may execute, reached waypoints are observed, and physical "
            f"cleanup manipulation remains blocked_capability. {physical_flags}"
        )
    return (
        "This section checks contract shape, not live ROS/Nav2. Current simulator "
        "navigation is validated against a static Nav2-shaped costmap and still is "
        "not physical robot navigation; chase imagery is labelled "
        "report_only_simulation_view and is not a policy input."
    )


def _requested_generated_text(private: dict[str, Any]) -> str:
    requested = private.get("requested_generated_mess_count")
    if requested is None:
        return ""
    return f" (requested {requested})"


def _metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )


def _badge(label: str, value: Any) -> str:
    return (
        f'<span class="badge">{html.escape(str(label))}: '
        f"<strong>{html.escape(str(value))}</strong></span>"
    )


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _is_agent_view_v2(payload: Any) -> bool:
    return (
        isinstance(payload, dict) and payload.get("schema") == agent_view_module.AGENT_VIEW_SCHEMA
    )


def _base_metric_map(agent_view: Any) -> dict[str, Any]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.base_metric_map(agent_view)
    return dict(agent_view.get("metric_map") or {}) if isinstance(agent_view, dict) else {}


def _runtime_metric_map(agent_view: Any) -> dict[str, Any]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.runtime_metric_map(agent_view)
    if not isinstance(agent_view, dict):
        return {}
    runtime_map = agent_view.get("runtime_metric_map")
    if isinstance(runtime_map, dict):
        return dict(runtime_map)
    static_projection = agent_view.get("static_fixture_projection")
    if isinstance(static_projection, dict):
        return {"static_map": {"fixtures": list(static_projection.get("rooms") or [])}}
    return {}


def _observed_objects(agent_view: Any) -> list[dict[str, Any]]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.observed_objects(agent_view)
    return list(agent_view.get("observed_objects") or []) if isinstance(agent_view, dict) else []


def _raw_fpv_observations(agent_view: Any) -> list[dict[str, Any]]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.raw_fpv_observations(agent_view)
    if not isinstance(agent_view, dict):
        return []
    return list(agent_view.get("raw_fpv_observations") or [])


def _cleanup_worklist(agent_view: Any) -> dict[str, Any]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.cleanup_worklist(agent_view)
    return dict(agent_view.get("cleanup_worklist") or {}) if isinstance(agent_view, dict) else {}


def _model_declared_observation_evidence(agent_view: Any) -> dict[str, Any]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.model_declared_observation_evidence(agent_view)
    if not isinstance(agent_view, dict):
        return {}
    return dict(agent_view.get("model_declared_observation_evidence") or {})


def _camera_model_policy_evidence(agent_view: Any) -> dict[str, Any]:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.camera_model_policy_evidence(agent_view)
    if not isinstance(agent_view, dict):
        return {}
    return dict(agent_view.get("camera_model_policy_evidence") or {})


def _perception_mode(agent_view: Any) -> str:
    if _is_agent_view_v2(agent_view):
        return agent_view_module.perception_mode(agent_view)
    return str(agent_view.get("perception_mode") or "") if isinstance(agent_view, dict) else ""
