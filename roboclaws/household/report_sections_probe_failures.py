from __future__ import annotations

import html
from typing import Any

from roboclaws.household.report_sections_probe import planner_probe_post_placement_rejection_views


def planner_probe_placement_scene_diagnostics_section(evidence: dict[str, Any]) -> str:
    diagnostics = evidence.get("task_sampler_failure_diagnostics") or {}
    scene_diagnostics = diagnostics.get("placement_scene_diagnostics") or []
    if not scene_diagnostics:
        return ""
    last = diagnostics.get("last_placement_scene_diagnostic") or scene_diagnostics[-1]
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('Scene diagnostics', _scene_diagnostic_count(diagnostics, scene_diagnostics))}"
        f"{_metric('Valid free points', last.get('valid_free_point_count', ''))}"
        f"{_metric('Free-space fraction', _scene_free_space_fraction(last))}"
        f"{_metric('Low free space', _yes_no(last.get('low_free_space')))}"
        f"{_metric('Nearest free distance', last.get('nearest_free_point_distance_m', ''))}"
        "</div>"
    )
    rows = [
        ("Target", last.get("target_name", "")),
        ("Target position", last.get("target_position", "")),
        ("Sampling radius range", last.get("sampling_radius_range", "")),
        ("Sampling area m2", last.get("sampling_area_m2", "")),
        ("Robot safety radius", last.get("robot_safety_radius", "")),
        ("px per meter", last.get("px_per_m", "")),
        ("Total free points", last.get("total_free_point_count", "")),
        ("Nearest free point", last.get("nearest_free_point", "")),
        ("Error", last.get("error", "")),
    ]
    scene_rows = "".join(
        _placement_scene_diagnostic_row(item)
        for item in scene_diagnostics
        if isinstance(item, dict)
    )
    scene_table = (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Target</th>'
        "<th>Valid free points</th><th>Free-space fraction</th>"
        "<th>Nearest free distance</th><th>Low free space</th></tr></thead>"
        f"<tbody>{scene_rows}</tbody></table></div>"
        if scene_rows
        else ""
    )
    band_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('radius_min_m', '')))}</td>"
        f"<td>{html.escape(str(item.get('radius_max_m', '')))}</td>"
        f"<td>{html.escape(str(item.get('free_point_count', '')))}</td>"
        "</tr>"
        for item in last.get("radius_band_counts") or []
        if isinstance(item, dict)
    )
    band_table = (
        '<div class="table-wrap"><table><thead><tr><th>Radius min m</th>'
        "<th>Radius max m</th><th>Free points</th></tr></thead>"
        f"<tbody>{band_rows}</tbody></table></div>"
        if band_rows
        else ""
    )
    note = (
        "Scene diagnostics summarize public map free-space around the actual "
        "upstream robot-placement target. They explain placement feasibility "
        "without changing cleanup semantics."
    )
    return (
        '<section class="panel planner-probe-placement-scene-diagnostics">'
        "<h2>Placement Scene Diagnostics</h2>"
        f'<p class="note">{html.escape(note)}</p>{metrics}{_field_table(rows)}'
        f"{scene_table}{band_table}</section>"
    )


def planner_probe_post_placement_rejection_section(evidence: dict[str, Any]) -> str:
    diagnostics = evidence.get("task_sampler_failure_diagnostics") or {}
    grasp_failures = diagnostics.get("grasp_failures") or []
    if not grasp_failures:
        return ""
    removed = [
        item for item in grasp_failures if isinstance(item, dict) and item.get("removed_candidate")
    ]
    effective_removals = (
        _safe_int(diagnostics.get("candidate_effective_removal_count"), 0)
        if "candidate_effective_removal_count" in diagnostics
        else len(removed)
    )
    candidate_name_misses = _safe_int(diagnostics.get("candidate_name_miss_count"), 0)
    threshold_exceeded = _safe_int(diagnostics.get("grasp_threshold_exceeded_count"), 0)
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('Grasp failures', diagnostics.get('grasp_failure_count', len(grasp_failures)))}"
        f"{_metric('Candidate removal calls', diagnostics.get('candidate_removal_count', 0))}"
        f"{_metric('Removed by grasp threshold', len(removed))}"
        f"{_metric('Effective removals', effective_removals)}"
        f"{_metric('Candidate name misses', candidate_name_misses)}"
        f"{_metric('Threshold exceeded rows', threshold_exceeded)}"
        "</div>"
    )
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('object_name', '')))}</td>"
        f"<td>{html.escape(str(item.get('count_before', '')))}</td>"
        f"<td>{html.escape(str(item.get('count_after', '')))}</td>"
        f"<td>{html.escape(str(item.get('max_failures', '')))}</td>"
        f"<td>{html.escape(str(item.get('threshold_exceeded', '')))}</td>"
        f"<td>{html.escape(str(item.get('threshold_crossed', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_count_before', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_count_after', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_name_present_before', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_name_present_after', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_removal_call_count_delta', '')))}</td>"
        f"<td>{html.escape(str(item.get('removed_candidate', '')))}</td>"
        "</tr>"
        for item in grasp_failures
        if isinstance(item, dict)
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Object</th>'
        "<th>Count before</th><th>Count after</th><th>Max failures</th>"
        "<th>Threshold exceeded</th><th>Threshold crossed</th>"
        "<th>Candidates before</th><th>Candidates after</th>"
        "<th>Name present before</th><th>Name present after</th>"
        "<th>Removal-call delta</th><th>Removed</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )
    removal_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('object_name', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_count_before', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_count_after', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_name_present_before', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_name_present_after', '')))}</td>"
        f"<td>{html.escape(str(item.get('effective_removal', '')))}</td>"
        "</tr>"
        for item in diagnostics.get("candidate_removals") or []
        if isinstance(item, dict)
    )
    removal_table = (
        "<h3>Candidate Removal Effectiveness</h3>"
        '<div class="table-wrap"><table><thead><tr><th>Object</th>'
        "<th>Candidates before</th><th>Candidates after</th>"
        "<th>Name present before</th><th>Name present after</th>"
        "<th>Effective removal</th></tr></thead>"
        f"<tbody>{removal_rows}</tbody></table></div>"
        if removal_rows
        else ""
    )
    note = (
        "Post-placement candidate rejection diagnostics explain failures after "
        "robot placement succeeds, such as grasp-feasibility thresholds removing "
        "the sampled object from the candidate pool."
    )
    return (
        '<section class="panel planner-probe-post-placement-rejections">'
        "<h2>Post-Placement Candidate Rejections</h2>"
        f'<p class="note">{html.escape(note)}</p>{metrics}'
        f"{planner_probe_post_placement_rejection_views(diagnostics)}{table}{removal_table}</section>"
    )


def _placement_scene_diagnostic_row(item: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(str(item.get('call_index', '')))}</td>"
        f"<td>{html.escape(str(item.get('target_name', '')))}</td>"
        f"<td>{html.escape(str(item.get('valid_free_point_count', '')))}</td>"
        f"<td>{html.escape(str(_scene_free_space_fraction(item)))}</td>"
        f"<td>{html.escape(str(item.get('nearest_free_point_distance_m', '')))}</td>"
        f"<td>{html.escape(str(item.get('low_free_space', '')))}</td>"
        "</tr>"
    )


def _scene_diagnostic_count(
    diagnostics: dict[str, Any],
    scene_diagnostics: list[dict[str, Any]],
) -> Any:
    return diagnostics.get("placement_scene_diagnostic_count", len(scene_diagnostics))


def _scene_free_space_fraction(item: dict[str, Any]) -> Any:
    return _format_fraction(item.get("valid_neighborhood_fraction", ""))


def planner_probe_policy_exception_section(evidence: dict[str, Any]) -> str:
    context = evidence.get("policy_exception_context") or {}
    if not context:
        return ""
    primitives = context.get("action_primitives") or []
    summary = (
        '<div class="metric-grid">'
        f"{_metric('Failure kind', context.get('failure_kind', 'unknown'))}"
        f"{_metric('Stage', context.get('stage', 'unknown'))}"
        f"{_metric('Exception', context.get('exception_type', 'unknown'))}"
        f"{_metric('No planned trajectory', _yes_no(context.get('no_planned_trajectory')))}"
        f"{_metric('Steps requested', context.get('steps_requested', 'unknown'))}"
        f"{_metric('Primitives', context.get('action_primitive_count', len(primitives)))}"
        "</div>"
    )
    message = str(context.get("message") or "")
    rows = []
    for primitive in primitives:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(primitive.get('index', '')))}</td>"
            f"<td>{html.escape(str(primitive.get('primitive_class', '')))}</td>"
            f"<td>{html.escape(str(primitive.get('current_phase', '')))}</td>"
            f"<td>{html.escape(_yes_no(primitive.get('planned_trajectory_present')))}</td>"
            f"<td>{html.escape(str(primitive.get('planned_trajectory_len', '')))}</td>"
            f"<td>{html.escape(str(primitive.get('trajectory_index', '')))}</td>"
            "</tr>"
        )
    table_rows = "".join(rows) or '<tr><td colspan="6">No action primitives recorded.</td></tr>'
    table = (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Primitive</th>'
        "<th>Current phase</th><th>Planned trajectory</th><th>Trajectory len</th>"
        f"<th>Trajectory index</th></tr></thead><tbody>{table_rows}</tbody></table></div>"
    )
    detail_rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in (
            ("Policy class", context.get("policy_class") or ""),
            ("Policy phase", context.get("policy_current_phase") or ""),
            ("Message", message),
        )
    )
    details = (
        '<div class="table-wrap"><table><thead><tr><th>Signal</th><th>Value</th>'
        f"</tr></thead><tbody>{detail_rows}</tbody></table></div>"
    )
    note = (
        "Policy exception diagnostics preserve the planner primitive state at the "
        "target-runtime failure point, before the artifact is collapsed into a "
        "blocked-capability result."
    )
    return (
        '<section class="panel"><h2>Policy Exception Diagnostics</h2>'
        f'<p class="note">{html.escape(note)}</p>{summary}{details}{table}</section>'
    )


def rby1m_curobo_gate_section(run_result: dict[str, Any]) -> str:
    gate = run_result.get("rby1m_curobo_gate") or {}
    if not gate:
        return ""
    blockers = gate.get("blockers") or []
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('code', '')))}</td>"
        f"<td>{html.escape(str(item.get('message', '')))}</td>"
        "</tr>"
        for item in blockers
    )
    if not rows:
        rows = '<tr><td colspan="2">None</td></tr>'
    metrics = (
        '<div class="metric-grid">'
        f"{_metric('Status', gate.get('status', 'unknown'))}"
        f"{_metric('Embodiment', gate.get('embodiment', 'unknown'))}"
        f"{_metric('CuRobo', 'available' if gate.get('curobo_available') else 'missing')}"
        f"{_metric('Execution', _execution_gate_label(gate))}"
        "</div>"
    )
    badges = "".join(
        (
            _badge("RBY1M CuRobo ready", gate.get("rby1m_curobo_ready", False)),
            _badge("Planner backed", gate.get("planner_backed", False)),
            _badge("Strict proof", gate.get("strict_proof_eligible", False)),
        )
    )
    note = gate.get("evidence_note") or (
        "RBY1M/CuRobo readiness requires target-robot planner execution."
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>Blocker</th>'
        f"<th>Message</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )
    return (
        '<section class="panel rby1m-curobo-gate">'
        "<h2>RBY1M CuRobo Gate</h2>"
        f'<p class="note">{html.escape(str(note))}</p>'
        f'{metrics}<div class="badges">{badges}</div>{table}</section>'
    )


def _execution_gate_label(gate: dict[str, Any]) -> str:
    return "attempted" if gate.get("execution_attempted") else "not attempted"


def planner_probe_blockers_section(evidence: dict[str, Any]) -> str:
    blockers = evidence.get("blockers") or []
    if not blockers:
        return ""
    rows = []
    for blocker in blockers:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(blocker.get('code', 'blocked')))}</td>"
            f"<td>{html.escape(str(blocker.get('message', '')))}</td>"
            "</tr>"
        )
    return (
        '<section class="panel"><h2>Capability Blockers</h2>'
        '<div class="table-wrap"><table><thead><tr><th>Code</th><th>Message</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></section>"
    )


def planner_probe_artifacts_section(run_result: dict[str, Any]) -> str:
    artifacts = run_result.get("artifacts") or {}
    rows = []
    for key in ("stdout", "stderr"):
        value = artifacts.get(key)
        if value:
            rows.append(f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>")
    if not rows:
        return ""
    return (
        '<section class="panel"><h2>Probe Artifacts</h2>'
        '<div class="table-wrap"><table><thead><tr><th>Artifact</th><th>Path</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></section>"
    )


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


def _field_table(rows: list[tuple[str, Any]]) -> str:
    table_rows = "".join(
        f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
        if value not in (None, "")
    )
    if not table_rows:
        table_rows = '<tr><td colspan="2">No values recorded.</td></tr>'
    return (
        '<div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th>'
        f"</tr></thead><tbody>{table_rows}</tbody></table></div>"
    )


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _format_fraction(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.6f}"
    return value


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
