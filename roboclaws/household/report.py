from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.core.rerun import (
    render_rerun_panel,
    report_rerun_command_from_env,
    rerun_panel_css,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
)
from roboclaws.household.report_sections_agent import (
    advisory_review_section,
    agent_view_section,
    camera_model_policy_section,
    cleanup_policy_trace_section,
    evidence_lane_badges,
    model_declared_observations_section,
    private_evaluation_section,
    raw_fpv_observations_section,
    real_robot_readiness_section,
)
from roboclaws.household.report_sections_agibot import agibot_sdk_runner_section
from roboclaws.household.report_sections_grasp_cache import (
    grasp_cache_availability_preflight_section,
    grasp_cache_generation_preflight_section,
)
from roboclaws.household.report_sections_grasp_diagnostics import (
    grasp_cache_generation_report_sections,
    grasp_filter_diagnostics_report_sections,
    grasp_initial_contact_diagnostics_report_sections,
    grasp_pose_policy_cache_report_sections,
)
from roboclaws.household.report_sections_isaac import isaac_runtime_section
from roboclaws.household.report_sections_map import (
    map_evidence_refresh_summary_section,
    runtime_metric_map_preview_section,
)
from roboclaws.household.report_sections_nav2_map import nav2_map_bundle_section
from roboclaws.household.report_sections_probe import (
    planner_probe_cleanup_binding_section,
    planner_probe_quality_section,
    planner_probe_task_sampler_failure_section,
    planner_probe_task_sampler_robot_placement_profile_section,
    planner_probe_views_section,
)
from roboclaws.household.report_sections_probe_failures import (
    planner_probe_artifacts_section,
    planner_probe_blockers_section,
    planner_probe_grasp_collision_diagnostics_section,
    planner_probe_placement_scene_diagnostics_section,
    planner_probe_policy_exception_section,
    planner_probe_post_placement_rejection_section,
    rby1m_curobo_gate_section,
)
from roboclaws.household.report_sections_probe_runtime import (
    planner_probe_cuda_memory_section,
    planner_probe_curobo_extension_cache_section,
    planner_probe_curobo_memory_profile_section,
    planner_probe_diagnostics_section,
    planner_probe_warp_compatibility_section,
    planner_probe_worker_stages_section,
)
from roboclaws.household.report_sections_proof import (
    attached_planner_proof_section,
    cleanup_primitive_gate_section,
    manipulation_provenance_section,
    planner_cleanup_bridge_section,
    planner_proof_requests_section,
)
from roboclaws.household.report_sections_proof_bundle import (
    cleanup_rerun_artifact_section,
    cleanup_rerun_command_section,
    grasp_feasibility_mitigation_decision_section,
    proof_bundle_commands_section,
    proof_bundle_local_runtime_preflight_section,
    proof_bundle_results_section,
    proof_bundle_warmup_section,
    proof_execution_horizon_section,
)
from roboclaws.household.report_sections_proof_selection import proof_request_selection_section
from roboclaws.household.report_sections_robot import (
    robot_timeline_section,
    visual_core_robot_view_steps,
)
from roboclaws.household.report_sections_timing import runtime_timing_section
from roboclaws.household.semantic_timeline import (
    OBJECT_DONE_PHASE,
    PLACE_CLEANUP_PHASES,
    SEMANTIC_LOOP_DISPLAY_NOTE,
    display_semantic_subphases,
)
from roboclaws.household.types import CleanupScenario

_COLORS = {
    "dish": (65, 125, 193),
    "book": (117, 86, 160),
    "linen": (78, 154, 96),
    "food": (206, 108, 65),
    "toy": (196, 154, 56),
    "electronics": (80, 80, 80),
}


def write_state_snapshot(
    scenario: CleanupScenario,
    locations: dict[str, str],
    output_path: Path,
    *,
    title: str,
) -> Path:
    """Render a compact deterministic room-state PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (900, 580), (249, 250, 252))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 888, 568), outline=(190, 194, 202), width=2)
    draw.text((28, 26), title, fill=(30, 34, 42))

    positions = _receptacle_positions()
    receptacles = {item.receptacle_id: item for item in scenario.receptacles}
    for receptacle_id, (x, y) in positions.items():
        receptacle = receptacles[receptacle_id]
        draw.rounded_rectangle((x - 80, y - 32, x + 80, y + 32), radius=6, fill=(232, 235, 241))
        draw.rectangle((x - 80, y - 32, x + 80, y + 32), outline=(169, 176, 190), width=1)
        draw.text((x - 70, y - 8), receptacle.name[:22], fill=(45, 51, 64))

    offsets: dict[str, int] = {}
    for obj in sorted(scenario.objects, key=lambda item: item.object_id):
        location_id = locations.get(obj.object_id, obj.location_id)
        x, y = positions.get(location_id, (450, 470))
        offset = offsets.get(location_id, 0)
        offsets[location_id] = offset + 1
        color = _COLORS.get(obj.category, (70, 90, 120))
        marker_x = x - 58 + offset * 28
        marker_y = y + 44
        draw.ellipse((marker_x, marker_y, marker_x + 20, marker_y + 20), fill=color)
        draw.text(
            (marker_x - 8, marker_y + 24),
            obj.object_id.split("_", 1)[0][:8],
            fill=(30, 34, 42),
        )

    image.save(output_path, format="PNG")
    return output_path


def render_cleanup_report(
    *,
    run_dir: Path,
    scenario: CleanupScenario,
    run_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
    before_snapshot: Path,
    after_snapshot: Path,
    robot_view_steps: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a self-contained cleanup `report.html`."""
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.html"
    body = "\n".join(
        _cleanup_report_sections(
            run_dir=run_dir,
            scenario=scenario,
            run_result=run_result,
            trace_events=trace_events,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            robot_view_steps=robot_view_steps or [],
        )
    )
    rerun_command = (
        str(run_result.get("rerun_command") or "").strip() or report_rerun_command_from_env()
    )
    if rerun_command:
        run_result["rerun_command"] = rerun_command
    report_title = str(run_result.get("report_title") or "MolmoSpaces Cleanup Pilot")
    report_path.write_text(
        _wrap_html(body, rerun_command=rerun_command, title=report_title),
        encoding="utf-8",
    )
    return report_path


def _cleanup_report_sections(
    *,
    run_dir: Path,
    scenario: CleanupScenario,
    run_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
    before_snapshot: Path,
    after_snapshot: Path,
    robot_view_steps: list[dict[str, Any]],
) -> list[str]:
    """Return the canonical Cleanup Artifact Report section sequence."""
    moves = _extract_moves(trace_events)
    score = run_result["score"]
    return _present_sections(
        [
            _cleanup_report_tabs(),
            _cleanup_summary_section(scenario=scenario, run_result=run_result, score=score),
            _report_tab_panel(
                "overview",
                [
                    _confidence_layer_note(run_result),
                    map_evidence_refresh_summary_section(run_result),
                    runtime_metric_map_preview_section(run_dir, run_result),
                    _before_after_section(
                        before_snapshot=before_snapshot,
                        after_snapshot=after_snapshot,
                        run_result=run_result,
                        robot_view_steps=robot_view_steps,
                    ),
                    _object_moves_section(moves),
                ],
            ),
            _report_tab_panel(
                "timeline",
                [
                    robot_timeline_section(
                        run_dir,
                        visual_core_robot_view_steps(run_result, robot_view_steps),
                        empty_state_block=_empty_state_block,
                        view_figure=_view_figure,
                        report_asset_src=_report_asset_src,
                    )
                ],
            ),
            _report_tab_panel(
                "timing",
                [runtime_timing_section(run_dir, run_result, trace_events, robot_view_steps)],
            ),
            _report_tab_panel(
                "actions",
                [_semantic_steps_table(run_result.get("semantic_substeps") or [])],
            ),
            _report_tab_panel(
                "robot",
                [
                    agibot_sdk_runner_section(
                        run_dir,
                        run_result,
                        metric=_metric,
                        artifact_link=_artifact_link,
                    ),
                    isaac_runtime_section(
                        run_dir,
                        run_result,
                        metric=_metric,
                        artifact_link=_artifact_link,
                        yes_no=_yes_no,
                    ),
                    nav2_map_bundle_section(
                        run_dir,
                        run_result,
                        metric=_metric,
                        review_image=_review_image,
                        report_asset_src=_report_asset_src,
                    ),
                    real_robot_readiness_section(run_result),
                    cleanup_policy_trace_section(run_result),
                ],
            ),
            _report_tab_panel(
                "proof",
                [
                    _score_section(score),
                    manipulation_provenance_section(run_result),
                    attached_planner_proof_section(run_result, view_figure=_view_figure),
                    cleanup_primitive_gate_section(run_result),
                    planner_cleanup_bridge_section(run_result),
                    planner_proof_requests_section(run_result),
                ],
            ),
            _report_tab_panel(
                "agent",
                [
                    agent_view_section(run_result),
                    raw_fpv_observations_section(run_result, view_figure=_view_figure),
                    model_declared_observations_section(run_result),
                    camera_model_policy_section(run_result),
                    advisory_review_section(run_result),
                    private_evaluation_section(run_result),
                ],
            ),
        ]
    )


def render_planner_manipulation_report(
    *,
    run_dir: Path,
    run_result: dict[str, Any],
) -> Path:
    """Write a shared-underlay report for planner-backed manipulation probes."""
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.html"
    evidence = run_result.get("manipulation_evidence") or {}
    quality = planner_proof_quality_evidence(evidence)
    body = f"""
    <section class="summary">
      <div class="summary-head">
        <p class="eyebrow">Manipulation artifact</p>
        <h1>Planner-Backed Manipulation Probe</h1>
      </div>
      <div class="metric-grid">
        {_metric("Status", run_result.get("status", "unknown"))}
        {_metric("Embodiment", evidence.get("embodiment", "unknown"))}
        {_metric("Policy", evidence.get("upstream_policy_class", "unknown"))}
        {_metric("Proof Quality", quality.get("quality_tier", "unknown"))}
        {_metric("Steps", evidence.get("steps_executed", "n/a"))}
        {_metric("Qpos delta", evidence.get("max_abs_qpos_delta", "n/a"))}
        {_metric("Containment proven", "yes" if quality.get("containment_proven") else "no")}
      </div>
      <div class="badges">
        {_badge("Contract", run_result.get("contract", "unknown"))}
        {_badge("Backend", run_result.get("backend", "unknown"))}
        {_badge("Probe mode", evidence.get("probe_mode", "unknown"))}
        {_badge("Provenance", evidence.get("primitive_provenance", "unknown"))}
        {_badge("Planner backed", evidence.get("planner_backed", False))}
      </div>
    </section>
    {manipulation_provenance_section(run_result)}
    {planner_probe_quality_section(evidence)}
    {planner_probe_views_section(evidence)}
    {planner_probe_cleanup_binding_section(evidence)}
    {planner_probe_task_sampler_robot_placement_profile_section(evidence)}
    {planner_probe_task_sampler_failure_section(evidence)}
    {planner_probe_post_placement_rejection_section(evidence)}
    {planner_probe_grasp_collision_diagnostics_section(evidence)}
    {planner_probe_placement_scene_diagnostics_section(evidence)}
    {planner_probe_diagnostics_section(evidence)}
    {planner_probe_cuda_memory_section(evidence)}
    {planner_probe_curobo_memory_profile_section(evidence)}
    {planner_probe_policy_exception_section(evidence)}
    {planner_probe_curobo_extension_cache_section(evidence)}
    {planner_probe_warp_compatibility_section(evidence)}
    {planner_probe_worker_stages_section(evidence)}
    {rby1m_curobo_gate_section(run_result)}
    {planner_probe_blockers_section(evidence)}
    {planner_probe_artifacts_section(run_result)}
    """
    report_path.write_text(_wrap_html(body, extra_css=_planner_report_css()), encoding="utf-8")
    return report_path


def render_planner_proof_bundle_runner_report(
    *,
    output_dir: Path,
    manifest: dict[str, Any],
) -> Path:
    """Write a reviewable report for proof-bundle runner command manifests."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    commands = manifest.get("commands") or []
    cleanup_command = manifest.get("cleanup_command") or []
    cleanup_rerun = manifest.get("cleanup_rerun") or {}
    body = f"""
    <section class="summary">
      <div class="summary-head">
        <p class="eyebrow">Proof bundle runner artifact</p>
        <h1>Planner Proof Bundle Runner</h1>
      </div>
      <div class="metric-grid">
        {_metric("Status", manifest.get("status", "unknown"))}
        {_metric("Proof requests", manifest.get("proof_request_count", 0))}
        {_metric("Ready requests", manifest.get("ready_request_count", 0))}
        {_metric("Commands", manifest.get("command_count", len(commands)))}
      </div>
      <div class="badges">
        {_badge("Schema", manifest.get("schema", "unknown"))}
        {_badge("Output dir", manifest.get("output_dir", output_dir))}
      </div>
    </section>
    <section class="panel">
      <h2>Source Cleanup Artifact</h2>
      <p class="note">{html.escape(str(manifest.get("evidence_note", "")))}</p>
      {
        _path_table(
            [
                ("Cleanup run result", manifest.get("cleanup_run_result", "")),
                (
                    "Planner scene XML",
                    (manifest.get("planner_scene") or {}).get("scene_xml", ""),
                ),
            ]
        )
    }
    </section>
    {proof_execution_horizon_section(manifest.get("proof_execution_horizon") or {})}
    {proof_request_selection_section(manifest.get("proof_request_selection") or {})}
    {
        grasp_feasibility_mitigation_decision_section(
            manifest.get("grasp_feasibility_mitigation_decision") or {}
        )
    }
    {
        grasp_cache_availability_preflight_section(
            manifest.get("grasp_cache_availability_preflight") or {}
        )
    }
    {
        grasp_cache_generation_preflight_section(
            manifest.get("grasp_cache_generation_preflight") or {}
        )
    }
    {proof_bundle_local_runtime_preflight_section(manifest.get("local_runtime_preflight") or {})}
    {
        proof_bundle_results_section(
            manifest.get("prior_proof_result_summary") or {},
            output_dir=output_dir,
            title="Prior Proof Evidence",
            section_class="prior-proof-evidence",
            default_note=(
                "Prior proof evidence consumed by selection. This keeps standalone "
                "probe and prior bundle visuals reviewable in the runner report."
            ),
        )
    }
    {proof_bundle_warmup_section(manifest.get("warmup") or {})}
    {proof_bundle_commands_section(commands)}
    {
        proof_bundle_results_section(
            manifest.get("proof_result_summary") or {}, output_dir=output_dir
        )
    }
    {cleanup_rerun_command_section(cleanup_command)}
    {cleanup_rerun_artifact_section(cleanup_rerun)}
    """
    report_path.write_text(_wrap_html(body, extra_css=_planner_report_css()), encoding="utf-8")
    return report_path


def render_grasp_cache_generation_report(
    *,
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write a reviewable report for MolmoSpaces grasp cache generation attempts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    body = "\n".join(_present_sections(grasp_cache_generation_report_sections(result)))
    report_path.write_text(_wrap_html(body, extra_css=_planner_report_css()), encoding="utf-8")
    return report_path


def render_grasp_pose_policy_cache_report(
    *,
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write a reviewable report for validated pose-policy cache generation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    body = "\n".join(_present_sections(grasp_pose_policy_cache_report_sections(result)))
    report_path.write_text(_wrap_html(body, extra_css=_planner_report_css()), encoding="utf-8")
    return report_path


def render_grasp_filter_diagnostics_report(
    *,
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write a reviewable report for bounded grasp perturbation-filter diagnostics."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    body = "\n".join(_present_sections(grasp_filter_diagnostics_report_sections(result)))
    report_path.write_text(_wrap_html(body, extra_css=_planner_report_css()), encoding="utf-8")
    return report_path


def render_grasp_initial_contact_diagnostics_report(
    *,
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write a reviewable report for rigid-grasp initial-contact diagnostics."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    body = "\n".join(_present_sections(grasp_initial_contact_diagnostics_report_sections(result)))
    report_path.write_text(_wrap_html(body, extra_css=_planner_report_css()), encoding="utf-8")
    return report_path


def _present_sections(sections: list[str]) -> list[str]:
    return [section for section in sections if section]


def _cleanup_report_tabs() -> str:
    tabs = [
        ("overview", "Overview"),
        ("timeline", "Robot Timeline"),
        ("timing", "Timing"),
        ("actions", "Actions"),
        ("robot", "Robot & Map"),
        ("proof", "Score & Proof"),
        ("agent", "Agent & Eval"),
    ]
    buttons = "".join(
        '<button type="button" class="report-tab" '
        f'id="report-tab-button-{tab_id}" data-report-tab-button="{tab_id}" '
        f'aria-controls="report-tab-{tab_id}" aria-selected="{str(index == 0).lower()}">'
        f"{html.escape(label)}</button>"
        for index, (tab_id, label) in enumerate(tabs)
    )
    return f'<nav class="report-tabs" aria-label="Report sections">{buttons}</nav>'


def _report_tab_panel(tab_id: str, sections: list[str]) -> str:
    body = "\n".join(_present_sections(sections))
    if not body:
        body = _empty_state_block(
            "No report data recorded",
            "This run did not produce artifacts for this report section.",
        )
    escaped_id = html.escape(tab_id)
    return (
        f'<div id="report-tab-{escaped_id}" class="report-tab-panel" '
        f'data-report-tab="{escaped_id}" role="tabpanel" '
        f'aria-labelledby="report-tab-button-{escaped_id}">{body}</div>'
    )


def _empty_state_block(title: str, message: str) -> str:
    return (
        f'<div class="empty-state"><h3>{html.escape(title)}</h3><p>{html.escape(message)}</p></div>'
    )


def _cleanup_summary_section(
    *,
    scenario: CleanupScenario,
    run_result: dict[str, Any],
    score: dict[str, Any],
) -> str:
    restored_summary = f"{score['restored_count']}/{score['total_targets']}"
    if _is_open_ended_result(run_result):
        default_eyebrow = "Open-ended artifact"
        default_title = "MolmoSpaces Open-ended Pilot"
    else:
        default_eyebrow = "Cleanup artifact"
        default_title = "MolmoSpaces Cleanup Pilot"
    eyebrow = str(run_result.get("report_eyebrow") or default_eyebrow)
    title = str(run_result.get("report_title") or default_title)
    return f"""
    <section class="summary">
      <div class="summary-head">
        <p class="eyebrow">{html.escape(eyebrow)}</p>
        <h1>{html.escape(title)}</h1>
      </div>
      {_summary_metrics(run_result, score)}
      {_failure_reason_summary(run_result)}
      <details class="summary-metadata">
        <summary>Run metadata</summary>
        <div class="badges">
          {_badge("Scenario", scenario.scenario_id)}
          {_badge("Backend", run_result.get("backend", "unknown"))}
          {_badge("Contract", run_result.get("contract", "legacy"))}
          {_badge("Status", _summary_status_label(_summary_status(run_result)))}
          {_badge("Restored", restored_summary)}
          {_badge("Generated mess", _generated_mess_summary(run_result))}
          {_badge("Policy", run_result.get("policy", run_result.get("planner", "unknown")))}
          {evidence_lane_badges(run_result, _badge)}
          {_badge("Agent driven", run_result.get("agent_driven", False))}
          {_badge("Provenance", run_result["primitive_provenance"])}
          {_badge("MCP server", run_result.get("mcp_server", "none"))}
          {_confidence_layer_badges(run_result)}
          {_robot_badge(run_result)}
          {_robot_view_camera_badges(run_result)}
        </div>
      </details>
    </section>
    """


def _before_after_section(
    *,
    before_snapshot: Path,
    after_snapshot: Path,
    run_result: dict[str, Any],
    robot_view_steps: list[dict[str, Any]],
) -> str:
    before_name = before_snapshot.name
    after_name = after_snapshot.name
    pick_place = _pick_place_comparison_grid(
        run_result.get("semantic_substeps") or [],
        robot_view_steps,
    )
    return f"""
    <section class="panel before-after-section">
      <div class="section-heading">
        <h2>Before And After</h2>
      </div>
      <div class="snapshots">
        <figure>
          {_review_image(before_name, "Before cleanup")}
          <figcaption>
            <strong>Initial room state</strong>
            <span>Object locations before the cleanup loop.</span>
          </figcaption>
        </figure>
        <figure>
          {_review_image(after_name, "After cleanup")}
          <figcaption>
            <strong>Final room state</strong>
            <span>Object locations after all reported place actions.</span>
          </figcaption>
        </figure>
      </div>
      {pick_place}
    </section>
    """


def _pick_place_comparison_grid(
    semantic_substeps: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]],
) -> str:
    comparisons = _pick_place_comparisons(semantic_substeps, robot_view_steps)
    if not comparisons:
        return ""
    cards = []
    for item in comparisons:
        escaped_route = html.escape(item["route"])
        escaped_route_attr = html.escape(item["route"], quote=True)
        cards.append(
            '<details class="comparison-item" open>'
            "<summary>"
            '<span class="comparison-item-head">'
            f"<strong>{html.escape(item['object_id'])}</strong>"
            f'<span title="{escaped_route_attr}">{escaped_route}</span>'
            "</span>"
            "</summary>"
            '<div class="comparison-views">'
            f"{_comparison_figure(item.get('pick_view'), 'Pick view', item.get('pick_label'))}"
            f"{_comparison_figure(item.get('place_view'), 'Place view', item.get('place_label'))}"
            "</div>"
            "</details>"
        )
    return (
        '<details class="comparison-details" open>'
        "<summary>"
        f"Pick/place visual checks <span>{len(comparisons)} completed moves</span>"
        "</summary>"
        '<div class="comparison-grid">' + "".join(cards) + "</div></details>"
    )


def _pick_place_comparisons(
    semantic_substeps: list[dict[str, Any]],
    robot_view_steps: list[dict[str, Any]],
) -> list[dict[str, str]]:
    picks: dict[str, dict[str, Any]] = {}
    places: dict[str, dict[str, Any]] = {}
    for step in robot_view_steps:
        action = str(step.get("action") or "")
        handle = _action_object_id(action)
        if not handle:
            continue
        phase = str(step.get("semantic_phase") or "")
        if phase == "pick" and handle not in picks:
            picks[handle] = step
        elif phase in PLACE_CLEANUP_PHASES and handle not in places:
            places[handle] = step

    comparisons: list[dict[str, str]] = []
    for item in semantic_substeps:
        object_id = str(item.get("object_id") or "")
        if not object_id:
            continue
        pick = picks.get(object_id)
        place = places.get(object_id)
        if not pick and not place:
            continue
        route = (
            f"{item.get('source_receptacle_id') or 'unknown source'}"
            " -> "
            f"{item.get('target_receptacle_id') or 'unknown target'}"
        )
        comparisons.append(
            {
                "object_id": object_id,
                "route": route,
                "pick_view": _best_comparison_view(pick),
                "pick_label": str((pick or {}).get("action") or "pick"),
                "place_view": _best_comparison_view(place),
                "place_label": str((place or {}).get("action") or "place"),
            }
        )
    return comparisons


def _action_object_id(action: str) -> str:
    parts = action.split()
    if len(parts) >= 2:
        return parts[1]
    return ""


def _best_comparison_view(step: dict[str, Any] | None) -> str:
    if not step:
        return ""
    views = step.get("views") or {}
    return str(views.get("fpv") or views.get("verify") or views.get("chase") or "")


def _comparison_figure(path: Any, label: str, caption: Any) -> str:
    if not path:
        return '<figure class="comparison-missing"><figcaption>Missing view</figcaption></figure>'
    escaped_label = html.escape(label)
    escaped_caption = html.escape(str(caption or label))
    return (
        "<figure>"
        f"{_review_image(path, label)}"
        f"<figcaption><strong>{escaped_label}</strong><span>{escaped_caption}</span></figcaption>"
        "</figure>"
    )


def _review_image(path: Any, alt: str, *, caption: str | None = None) -> str:
    src = html.escape(str(path), quote=True)
    alt_text = html.escape(str(alt), quote=True)
    caption_text = str(caption or alt).strip() or "report image"
    escaped_caption = html.escape(caption_text, quote=True)
    aria_label = html.escape(f"Open {caption_text} image for review", quote=True)
    return (
        f'<a class="image-link" href="{src}" data-lightbox-image '
        f'data-lightbox-caption="{escaped_caption}" aria-label="{aria_label}">'
        f'<img src="{src}" alt="{alt_text}" loading="lazy" decoding="async">'
        "</a>"
    )


def _object_moves_section(moves: list[dict[str, Any]]) -> str:
    return f"""
    <section class="panel">
      <h2>Object Moves</h2>
      {_moves_table(moves)}
    </section>
    """


def _score_section(score: dict[str, Any]) -> str:
    return f"""
    <section class="panel">
      <h2>Score</h2>
      {_score_table(score)}
    </section>
    """


def _badge(label: str, value: Any) -> str:
    return (
        f'<span class="badge">{html.escape(str(label))}: '
        f"<strong>{html.escape(str(value))}</strong></span>"
    )


def _summary_metrics(run_result: dict[str, Any], score: dict[str, Any]) -> str:
    semantic = score.get("semantic_acceptability")
    semantic_count = ""
    if isinstance(semantic, dict):
        semantic_count = f"{semantic.get('accepted_count', 0)}/{semantic.get('total_targets', 0)}"
    restored_count = f"{score.get('restored_count', 0)}/{score.get('total_targets', 0)}"
    return (
        '<div class="metric-grid">'
        f"{_metric('Status', _summary_status_label(_summary_status(run_result)))}"
        f"{_metric('Restored', restored_count)}"
        f"{_metric('Generated', _generated_mess_summary(run_result))}"
        f"{_metric('Sweep', _rate_text(run_result.get('sweep_coverage_rate')))}"
        f"{_metric('Disturbance', run_result.get('disturbance_count', 0))}"
        f"{_metric('Semantic', semantic_count or 'n/a')}"
        "</div>"
    )


def _failure_reason_summary(run_result: dict[str, Any]) -> str:
    if not _is_failure_status(run_result):
        return ""
    reason = _failure_reason_text(run_result)
    if not reason:
        return ""
    return (
        '<div class="summary-alert summary-alert-failure">'
        "<strong>Failure Reason</strong>"
        f"<p>{html.escape(reason)}</p>"
        "</div>"
    )


def _is_failure_status(run_result: dict[str, Any]) -> bool:
    statuses = (
        [
            run_result.get("intent_status"),
            run_result.get("goal_status"),
            run_result.get("final_status"),
            run_result.get("status"),
        ]
        if _is_open_ended_result(run_result)
        else [
            run_result.get("cleanup_status"),
            run_result.get("completion_status"),
            run_result.get("status"),
        ]
    )
    live_status = run_result.get("live_status")
    if isinstance(live_status, dict):
        statuses.append(live_status.get("phase"))
    return any(
        str(status or "").strip().lower()
        in {"failed", "failure", "blocked", "error", "errored", "timeout", "timed_out"}
        for status in statuses
    )


def _summary_status(run_result: dict[str, Any]) -> Any:
    keys = (
        ("intent_status", "goal_status", "final_status", "status", "cleanup_status")
        if _is_open_ended_result(run_result)
        else ("cleanup_status", "status")
    )
    for key in keys:
        value = run_result.get(key)
        if value:
            return value
    return "unknown"


def _is_open_ended_result(run_result: dict[str, Any]) -> bool:
    goal_contract = run_result.get("goal_contract")
    goal_contract = goal_contract if isinstance(goal_contract, dict) else {}
    return (
        str(run_result.get("task_intent") or goal_contract.get("intent") or "").strip()
        == "open-ended"
    )


def _failure_reason_text(run_result: dict[str, Any]) -> str:
    score = run_result.get("score") if isinstance(run_result.get("score"), dict) else {}
    live_status = run_result.get("live_status")
    live_status = live_status if isinstance(live_status, dict) else {}
    candidates = [
        run_result.get("terminate_reason"),
        run_result.get("failure_reason"),
        run_result.get("error_reason"),
        score.get("completion_summary"),
        score.get("why_done"),
        live_status.get("reason"),
        live_status.get("detail"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )


def _summary_status_label(status: Any) -> str:
    value = str(status or "unknown")
    labels = {
        "physical_agibot_navigation_pilot_rehearsal": "Rehearsal",
        "physical_agibot_navigation_pilot_complete": "Pilot complete",
        "success": "Success",
        "partial_success": "Partial success",
        "failed": "Failed",
    }
    return labels.get(value, value.replace("_", " ").title())


def _rate_text(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.0%}"
    return "n/a" if value is None else str(value)


def _robot_badge(run_result: dict[str, Any]) -> str:
    robot_name = run_result.get("robot_name")
    if not robot_name:
        return ""
    return _badge("Robot", robot_name)


def _robot_view_camera_badges(run_result: dict[str, Any]) -> str:
    summary = run_result.get("robot_view_camera_control")
    if not isinstance(summary, dict):
        return ""
    return _badge("Robot-view camera", summary.get("status", "unknown")) + _badge(
        "Head-camera FPV", summary.get("head_camera_fpv", False)
    )


def _confidence_layer_badges(run_result: dict[str, Any]) -> str:
    layer = run_result.get("confidence_layer")
    if not layer:
        return ""
    return "".join(
        (
            _badge("Confidence layer", layer),
            _badge("Next layer", run_result.get("next_confidence_layer", "unknown")),
        )
    )


def _generated_mess_summary(run_result: dict[str, Any]) -> str:
    actual = run_result.get("generated_mess_count")
    requested = run_result.get("requested_generated_mess_count")
    if actual is None:
        return "n/a"
    if requested is None or requested == actual:
        return actual
    return f"{actual} actual / {requested} requested"


def _confidence_layer_note(run_result: dict[str, Any]) -> str:
    layer = str(run_result.get("confidence_layer") or "")
    if not layer:
        return ""
    summary = str(run_result.get("confidence_layer_summary") or "")
    next_layer = str(run_result.get("next_confidence_layer") or "")
    note = layer
    if summary:
        note = f"{note}: {summary}"
    if next_layer:
        note = f"{note} Next confidence layer: {next_layer}."
    return f'<section class="panel note-panel"><p class="note">{html.escape(note)}</p></section>'


def _path_table(rows: list[tuple[str, Any]]) -> str:
    table_rows = "".join(
        f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Artifact</th><th>Path</th>'
        "</tr></thead><tbody>" + table_rows + "</tbody></table></div>"
    )


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _artifact_link(path: str, run_dir: Path) -> str:
    if not path:
        return ""
    href = html.escape(path)
    label = html.escape(path)
    if (run_dir / path).exists():
        return f'<a href="{href}">{label}</a>'
    return label


def _view_figure(path: Any, label: str) -> str:
    if not path:
        return ""
    escaped_label = html.escape(label)
    return (
        "<figure>"
        f"{_review_image(path, f'{label} view')}"
        f"<figcaption>{escaped_label}</figcaption>"
        "</figure>"
    )


def _report_asset_src(path: Any, output_dir: Path | None) -> str:
    if not path:
        return ""
    path_text = str(path)
    if output_dir is None or path_text.startswith(("http://", "https://", "data:")):
        return path_text
    candidate = Path(path_text)
    try:
        if candidate.is_absolute():
            asset_path = candidate
        elif candidate.exists():
            asset_path = candidate.resolve()
        elif (output_dir / candidate).exists():
            asset_path = (output_dir / candidate).resolve()
        else:
            return path_text
        return Path(os.path.relpath(asset_path, output_dir.resolve())).as_posix()
    except OSError:
        return path_text


def _moves_table(moves: list[dict[str, Any]]) -> str:
    if not moves:
        return "<p>No place operations recorded.</p>"
    rows = []
    for index, move in enumerate(moves, start=1):
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(str(move.get('object_id', '')))}</td>"
            f"<td>{html.escape(str(move.get('receptacle_id', '')))}</td>"
            f"<td>{html.escape(str(move.get('primitive_provenance', '')))}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>#</th><th>Object</th><th>Placed at</th>'
        "<th>Primitive provenance</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _semantic_steps_table(semantic_substeps: list[dict[str, Any]]) -> str:
    if not semantic_substeps:
        return (
            '<section class="panel semantic-section semantic-section-empty">'
            "<h2>Semantic Substeps</h2>"
            + _empty_state_block(
                "No semantic cleanup actions recorded",
                "This AgiBot rehearsal exported map context, rehearsed the policy "
                "camera boundary, and rehearsed waypoint navigation. Physical "
                "manipulation and object cleanup were intentionally not executed.",
            )
            + "</section>"
        )
    cards = []
    for item in semantic_substeps:
        steps = item.get("steps", [])
        displayed = display_semantic_subphases(steps)
        status = _semantic_substep_status(steps)
        phase_rail = "".join(
            "<li>"
            f"<span>{html.escape(step['label'])}</span>"
            f"<small>{html.escape(step['detail'])}</small>"
            "</li>"
            for step in displayed
        )
        readback = _semantic_readback(steps)
        placement = _semantic_placement_readback(steps)
        cards.append(
            '<details class="semantic-card">'
            "<summary>"
            '<span class="semantic-card-head">'
            f"<strong>{html.escape(str(item.get('object_id', '')))}</strong>"
            f"<span>{html.escape(str(item.get('source_receptacle_id', '') or 'unknown source'))}"
            " -> "
            f"{html.escape(str(item.get('target_receptacle_id', '') or 'unknown target'))}</span>"
            "</span>"
            f'<span class="semantic-card-status">{html.escape(status)}'
            f" · {len(displayed)} phases</span>"
            "</summary>"
            f'<ol class="phase-rail">{phase_rail}</ol>'
            f'<p class="readback">Readback: {html.escape(readback or "pending")}</p>'
            f"{placement}"
            "</details>"
        )
    return (
        '<section class="panel semantic-section"><h2>Semantic Substeps</h2>'
        f'<p class="note">{html.escape(SEMANTIC_LOOP_DISPLAY_NOTE)}</p>'
        '<div class="semantic-cards">' + "".join(cards) + "</div></section>"
    )


def _semantic_substep_status(steps: list[dict[str, Any]]) -> str:
    if any(step.get("phase") in {OBJECT_DONE_PHASE, *PLACE_CLEANUP_PHASES} for step in steps):
        return "placed"
    if any(step.get("ok") is False for step in steps):
        return "blocked"
    return "pending"


def _semantic_readback(steps: list[dict[str, Any]]) -> str:
    candidates = [
        step for step in steps if step.get("phase") in {OBJECT_DONE_PHASE, *PLACE_CLEANUP_PHASES}
    ]
    if not candidates:
        return "pending"
    final_step = candidates[-1]
    readback = str(final_step.get("location_id") or "")
    relation = str(final_step.get("location_relation") or "")
    contained_in = final_step.get("contained_in")
    if contained_in:
        return f"{readback} ({relation}: {contained_in})"
    return readback or "pending"


def _semantic_placement_readback(steps: list[dict[str, Any]]) -> str:
    diagnostics = [
        step.get("placement_diagnostic")
        for step in steps
        if isinstance(step.get("placement_diagnostic"), dict)
    ]
    if not diagnostics:
        return ""
    diagnostic = diagnostics[-1]
    summary = (
        f"Placement: {diagnostic.get('support_status', diagnostic.get('status', 'unknown'))}; "
        f"relation={diagnostic.get('relation', '')}; "
        f"xy={diagnostic.get('xy_distance_m', '')}m; "
        f"z={diagnostic.get('z_delta_m', '')}m; "
        f"contact={diagnostic.get('contact_proof', '')}"
    )
    return f'<p class="readback">{html.escape(summary)}</p>'


def _score_table(score: dict[str, Any]) -> str:
    rows = []
    for row in score["object_results"]:
        exact_private_match = row.get("exact_private_match", row.get("restored", False))
        semantic_level = row.get("semantic_acceptability", "unknown")
        semantic_reason = row.get("semantic_reason", "")
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['object_id']))}</td>"
            f"<td>{html.escape(str(row['actual_location_id']))}</td>"
            f"<td>{'yes' if exact_private_match else 'no'}</td>"
            f"<td>{html.escape(str(semantic_level))}</td>"
            f"<td>{html.escape(str(semantic_reason))}</td>"
            "</tr>"
        )
    semantic_summary = _semantic_acceptability_summary(score)
    return (
        semantic_summary
        + '<div class="table-wrap"><table><thead><tr><th>Object</th><th>Final location</th>'
        "<th>Exact private match</th><th>Semantic acceptability</th><th>Reason</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _semantic_acceptability_summary(score: dict[str, Any]) -> str:
    semantic = score.get("semantic_acceptability")
    if not isinstance(semantic, dict):
        return ""
    counts = semantic.get("counts") or {}
    accepted = semantic.get("accepted_count", 0)
    total = semantic.get("total_targets", score.get("total_targets", 0))
    parts = [
        f"accepted {accepted}/{total}",
        f"preferred {counts.get('preferred', 0)}",
        f"acceptable {counts.get('acceptable', 0)}",
        f"questionable {counts.get('questionable', 0)}",
        f"wrong {counts.get('wrong', 0)}",
        f"unknown {counts.get('unknown', 0)}",
    ]
    return f'<p class="note">Semantic acceptability: {html.escape(", ".join(parts))}.</p>'


def _extract_moves(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    for event in trace_events:
        if event.get("tool") not in {"place", "place_inside"} or event.get("event") != "response":
            continue
        response = event.get("response")
        if isinstance(response, dict) and response.get("ok"):
            moves.append(response)
    return moves


def _image_lightbox_markup() -> str:
    return (
        '<div class="image-lightbox" data-image-lightbox hidden aria-hidden="true">'
        '<button type="button" class="lightbox-close" data-lightbox-close '
        'aria-label="Close image review">Close</button>'
        '<div class="lightbox-dialog" role="dialog" aria-modal="true" '
        'aria-label="Image review">'
        '<img alt="">'
        '<p class="lightbox-caption" data-lightbox-caption></p>'
        "</div></div>"
    )


def _wrap_html(
    body: str,
    *,
    extra_css: str = "",
    rerun_command: str | None = None,
    title: str = "MolmoSpaces Cleanup Pilot",
) -> str:
    extra_css_block = f"{extra_css.rstrip()}\n" if extra_css else ""
    rerun_panel = render_rerun_panel(rerun_command)
    image_lightbox = _image_lightbox_markup()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      color: #20242c;
      background: #eef2f6;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 48px; }}
    h1 {{ font-size: 30px; margin: 0; letter-spacing: 0; }}
    h2 {{ font-size: 19px; margin: 0 0 12px; letter-spacing: 0; }}
    h2 span {{ color: #647083; font-size: 13px; font-weight: 650; }}
    .summary {{
      background: #20242c;
      color: #f8fafc;
      border-radius: 8px;
      padding: 22px;
      box-shadow: 0 14px 34px rgba(25, 32, 44, 0.16);
    }}
    .summary-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; }}
    .summary-metadata {{
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 8px;
      margin-top: 12px;
      background: rgba(255, 255, 255, 0.05);
    }}
    .summary-metadata > summary {{
      min-height: 42px;
      padding: 10px 12px;
      cursor: pointer;
      color: #dbe5ef;
      font-weight: 750;
    }}
    .summary-metadata .badges {{ padding: 0 12px 12px; }}
    .summary-alert {{
      display: grid;
      gap: 6px;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 8px;
      margin: 0 0 12px;
      padding: 12px;
      background: rgba(255, 255, 255, 0.07);
    }}
    .summary-alert strong {{
      color: #ffffff;
      font-size: 14px;
    }}
    .summary-alert p {{
      margin: 0;
      color: #dbe5ef;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }}
    .summary-alert-failure {{
      border-color: rgba(248, 113, 113, 0.44);
      background: rgba(127, 29, 29, 0.28);
    }}
    .eyebrow {{
      margin: 0 0 6px;
      color: #a7d8cf;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      margin: 18px 0;
    }}
    .metric {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 8px;
      padding: 12px;
    }}
    .metric span {{ display: block; color: #b7c1ce; font-size: 12px; margin-bottom: 4px; }}
    .metric strong {{
      display: block;
      color: #ffffff;
      font-size: 19px;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }}
    .panel .metric {{
      background: #f8fafc;
      border-color: #d9dde6;
    }}
    .panel .metric span {{ color: #647083; }}
    .panel .metric strong {{ color: #20242c; }}
    .panel {{
      background: #ffffff;
      border: 1px solid #d8dee8;
      border-radius: 8px;
      padding: 18px;
      margin-top: 18px;
      box-shadow: 0 5px 16px rgba(25, 32, 44, 0.06);
    }}
    .report-tabs {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      margin-top: 18px;
      padding: 10px;
      background: rgba(238, 242, 246, 0.96);
      border: 1px solid #d8dee8;
      border-radius: 8px;
      backdrop-filter: blur(8px);
    }}
    .report-tab {{
      min-height: 40px;
      border: 1px solid #cfd6e2;
      border-radius: 6px;
      padding: 0 12px;
      background: #ffffff;
      color: #334155;
      font: inherit;
      font-size: 14px;
      font-weight: 700;
      white-space: nowrap;
      cursor: pointer;
    }}
    .report-tab[aria-selected="true"] {{
      background: #20242c;
      border-color: #20242c;
      color: #ffffff;
    }}
    .report-tab:focus-visible {{
      outline: 3px solid #7cc7bb;
      outline-offset: 2px;
    }}
    .report-tab-panel {{ scroll-margin-top: 80px; }}
    .note-panel {{ background: #fbfcfd; }}
    .empty-state {{
      border: 1px dashed #cbd5e1;
      border-radius: 8px;
      background: #f8fafc;
      padding: 18px;
    }}
    .empty-state h3 {{ margin: 0 0 6px; color: #20242c; }}
    .empty-state p {{ margin: 0; color: #647083; max-width: 720px; }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .badge {{
      background: #fff;
      border: 1px solid #d9dde6;
      border-radius: 6px;
      padding: 7px 10px;
    }}
    .summary .badge {{
      background: rgba(255, 255, 255, 0.09);
      border-color: rgba(255, 255, 255, 0.18);
      color: #e9edf4;
    }}
    .summary .badge strong {{ color: #ffffff; }}
    .snapshots {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .before-after-section .snapshots figcaption,
    .comparison-item figcaption,
    .nav2-preview figcaption {{
      display: grid;
      gap: 3px;
    }}
    figcaption strong {{ color: #20242c; }}
    figcaption span {{ color: #647083; font-size: 12px; }}
    .comparison-details,
    .timing-details,
    .artifact-details,
    .robot-timeline-details {{
      margin-top: 14px;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      background: #fbfcfd;
    }}
    .comparison-details > summary,
    .timing-details > summary,
    .artifact-details > summary,
    .robot-timeline-details > summary {{
      min-height: 44px;
      padding: 12px 14px;
      cursor: pointer;
      font-weight: 750;
    }}
    .comparison-details > summary span {{
      color: #647083;
      font-size: 13px;
      font-weight: 650;
      margin-left: 8px;
    }}
    .comparison-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 12px;
      padding: 0 12px 12px;
    }}
    .comparison-item {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
    }}
    .comparison-item summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 24px;
      gap: 10px;
      align-items: start;
      min-height: 58px;
      list-style: none;
      cursor: pointer;
    }}
    .comparison-item summary::-webkit-details-marker {{ display: none; }}
    .comparison-item summary::after {{
      content: "-";
      width: 24px;
      height: 24px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: #e6eef5;
      color: #334155;
      font-weight: 800;
    }}
    .comparison-item:not([open]) summary::after {{ content: "+"; }}
    .comparison-item[open] summary {{ margin-bottom: 10px; }}
    .comparison-item-head {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .comparison-item-head strong {{ font-size: 15px; overflow-wrap: anywhere; }}
    .comparison-item-head span {{
      color: #647083;
      font-size: 12px;
      overflow-wrap: anywhere;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      overflow: hidden;
    }}
    .comparison-views {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
    }}
    .comparison-missing {{
      display: grid;
      min-height: 120px;
      place-items: center;
      background: #f1f5f9;
    }}
    figure {{
      margin: 0;
      background: #fff;
      border: 1px solid #d9dde6;
      border-radius: 6px;
      padding: 10px;
    }}
    img {{ width: 100%; height: auto; display: block; }}
    .image-link {{
      position: relative;
      display: block;
      border-radius: 4px;
      overflow: hidden;
      cursor: zoom-in;
    }}
    .image-link::after {{
      content: "+";
      position: absolute;
      top: 8px;
      right: 8px;
      width: 26px;
      height: 26px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: rgba(32, 36, 44, 0.82);
      color: #ffffff;
      font-size: 18px;
      font-weight: 800;
      opacity: 0;
      transform: scale(0.94);
      transition: opacity 0.16s ease, transform 0.16s ease;
    }}
    .image-link:hover::after,
    .image-link:focus-visible::after {{
      opacity: 1;
      transform: scale(1);
    }}
    .image-link:focus-visible {{
      outline: 3px solid #7cc7bb;
      outline-offset: 3px;
    }}
    .image-lightbox[hidden] {{ display: none; }}
    .image-lightbox {{
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(12, 16, 24, 0.86);
    }}
    .lightbox-dialog {{
      display: grid;
      gap: 10px;
      max-width: min(96vw, 1440px);
      max-height: 92vh;
      color: #f8fafc;
    }}
    .lightbox-dialog img {{
      max-width: min(96vw, 1440px);
      max-height: 82vh;
      width: auto;
      height: auto;
      object-fit: contain;
      border-radius: 6px;
      background: #0f172a;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.42);
    }}
    .lightbox-caption {{
      margin: 0;
      color: #e2e8f0;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .lightbox-close {{
      position: fixed;
      top: 18px;
      right: 18px;
      min-height: 38px;
      border: 1px solid rgba(255, 255, 255, 0.22);
      border-radius: 6px;
      padding: 0 12px;
      background: rgba(15, 23, 42, 0.88);
      color: #ffffff;
      font: inherit;
      font-weight: 750;
      cursor: pointer;
    }}
    .lightbox-close:focus-visible {{
      outline: 3px solid #7cc7bb;
      outline-offset: 2px;
    }}
    figcaption {{ margin-top: 8px; color: #565f70; font-size: 14px; }}
    .note {{ color: #565f70; margin: 0 0 12px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #d9dde6; border-radius: 8px; }}
    .timing-lane-block {{
      margin: 14px 0;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .timing-lane-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }}
    .timing-lane-head h3 {{ margin: 0; font-size: 15px; }}
    .timing-lane-head span {{ color: #475569; font-weight: 750; }}
    .timing-lane {{
      display: flex;
      gap: 3px;
      overflow-x: auto;
      padding-bottom: 2px;
    }}
    .timing-segment {{
      flex: 0 0 max(var(--basis), 104px);
      min-height: 74px;
      display: grid;
      align-content: center;
      gap: 3px;
      padding: 10px;
      color: #ffffff;
      background: var(--segment-color);
      border-radius: 6px;
    }}
    .timing-segment strong,
    .timing-segment span,
    .timing-segment small {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .timing-segment span {{ font-size: 16px; font-weight: 800; }}
    .timing-segment small {{ color: rgba(255, 255, 255, 0.82); }}
    .timing-details .table-wrap,
    .artifact-details .table-wrap {{ margin: 0 12px 12px; }}
    .object-cycle-timing {{
      margin-top: 16px;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .object-cycle-timing > h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .object-cycle-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .object-cycle {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #ffffff;
    }}
    .object-cycle h3 {{ margin: 0 0 8px; font-size: 15px; overflow-wrap: anywhere; }}
    .object-cycle .timing-lane-block {{ margin: 0; padding: 10px; }}
    .object-cycle p {{ margin: 8px 0 0; color: #565f70; font-size: 12px; overflow-wrap: anywhere; }}
    .robot-timeline-details .robot-step {{
      margin: 0 12px 12px;
    }}
    .robot-step {{
      background: #fff;
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 14px;
    }}
    .robot-step h3 {{ font-size: 16px; margin: 0 0 4px; }}
    .pose {{ margin: 0 0 10px; color: #565f70; font-size: 13px; }}
    .semantic-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }}
    .semantic-badges .badge {{ font-size: 13px; padding: 5px 8px; background: #eef6ff; }}
    .focus-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 10px; }}
    .focus-badges .badge {{ font-size: 13px; padding: 5px 8px; }}
    .action-evidence-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: -2px 0 10px; }}
    .action-evidence-badges .badge {{
      font-size: 12px; padding: 4px 7px; background: #fff7ed; border-color: #fed7aa;
    }}
    .action-evidence-note {{ margin-top: -4px; }}
    .evidence-badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: -4px 0 10px; }}
    .evidence-badges .badge {{ font-size: 12px; padding: 4px 7px; background: #f8fafc; }}
    .views {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 10px;
    }}
    .robot-primary-views {{
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }}
    .sim-only-views {{
      margin-top: 10px;
      border: 1px dashed #cbd5e1;
      border-radius: 8px;
      background: #f8fafc;
    }}
    .sim-only-views > summary {{
      min-height: 40px;
      padding: 10px 12px;
      cursor: pointer;
      color: #475569;
      font-weight: 750;
    }}
    .sim-only-views .views {{ padding: 0 12px 12px; }}
    .sim-only-grid-single {{
      grid-template-columns: minmax(0, min(100%, 560px));
      justify-content: start;
    }}
{extra_css_block}    .raw-fpv-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }}
    .raw-fpv-card {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .raw-fpv-card h3 {{ margin: 0 0 4px; font-size: 15px; }}
    .raw-fpv-card figure {{ margin-top: 10px; }}
    .semantic-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .semantic-card {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .semantic-card summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto 24px;
      gap: 10px;
      align-items: center;
      list-style: none;
      cursor: pointer;
    }}
    .semantic-card summary::-webkit-details-marker {{ display: none; }}
    .semantic-card summary::after {{
      content: "+";
      width: 24px;
      height: 24px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      background: #e6eef5;
      color: #334155;
      font-weight: 800;
    }}
    .semantic-card[open] summary {{ margin-bottom: 10px; }}
    .semantic-card[open] summary::after {{ content: "-"; }}
    .semantic-card-head {{
      display: grid;
      gap: 4px;
      margin: 0;
      min-width: 0;
    }}
    .semantic-card-head strong {{
      overflow-wrap: anywhere;
      font-size: 14px;
    }}
    .semantic-card-head span {{
      color: #647083;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .semantic-card-status {{
      color: #475569;
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .phase-rail {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(58px, 1fr));
      gap: 8px;
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .phase-rail li {{
      border: 1px solid #bfdcd7;
      background: #eef8f6;
      border-radius: 7px;
      padding: 8px 6px;
      text-align: center;
    }}
    .phase-rail span {{ display: block; font-weight: 750; color: #1f5f58; }}
    .phase-rail small {{ display: block; margin-top: 2px; color: #687789; }}
    .command-phase-rail {{ min-width: 280px; }}
    .readback {{ margin: 10px 0 0; color: #565f70; font-size: 13px; overflow-wrap: anywhere; }}
    .nav2-explainer {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .nav2-explainer div {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .nav2-explainer strong {{ display: block; margin-bottom: 4px; }}
    .nav2-explainer span {{ color: #565f70; }}
    .nav2-preview-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 300px);
      gap: 12px;
      align-items: start;
    }}
    .nav2-legend {{
      border: 1px solid #d9dde6;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfd;
    }}
    .nav2-legend h3 {{ margin: 0 0 10px; font-size: 15px; }}
    .nav2-legend ul {{ display: grid; gap: 10px; list-style: none; padding: 0; margin: 0; }}
    .nav2-legend li {{
      display: grid;
      grid-template-columns: 18px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
    }}
    .nav2-legend small {{
      grid-column: 2;
      color: #647083;
    }}
    .legend-swatch {{
      width: 16px;
      height: 16px;
      border-radius: 4px;
      border: 1px solid #94a3b8;
      background: #e8eef6;
    }}
    .legend-swatch.fixture {{ background: #717c8d; border-color: #475569; }}
    .legend-swatch.waypoint {{ border-radius: 999px; background: #23865a; border-color: #23865a; }}
    .legend-swatch.robot {{ border-radius: 999px; background: #2e58b2; border-color: #1e4082; }}
    .nav2-legend p {{ margin: 12px 0 0; color: #565f70; }}
    .requirements {{ color: #565f70; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{
      padding: 9px 10px;
      text-align: left;
      border-bottom: 1px solid #e5e8ee;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    th {{ background: #eef1f5; font-weight: 650; }}
    @media (max-width: 640px) {{
      main {{ padding: 18px 12px 36px; }}
      .summary-head,
      .timing-lane-head {{
        display: grid;
        align-items: start;
      }}
      .semantic-card summary {{
        grid-template-columns: minmax(0, 1fr) 24px;
      }}
      .semantic-card-status {{
        grid-column: 1 / -1;
      }}
      .nav2-preview-layout {{
        grid-template-columns: 1fr;
      }}
    }}
{rerun_panel_css()}
  </style>
</head>
<body><main>{rerun_panel}{body}</main>{image_lightbox}<script>
(() => {{
  const buttons = Array.from(document.querySelectorAll("[data-report-tab-button]"));
  const panels = Array.from(document.querySelectorAll("[data-report-tab]"));
  if (!buttons.length || !panels.length) return;
  document.documentElement.classList.add("tabs-ready");
  const validTabs = new Set(panels.map((panel) => panel.dataset.reportTab));
  function activate(tab, options = {{}}) {{
    if (!validTabs.has(tab)) tab = panels[0].dataset.reportTab;
    for (const button of buttons) {{
      const selected = button.dataset.reportTabButton === tab;
      button.setAttribute("aria-selected", String(selected));
    }}
    let selectedPanel = panels[0];
    for (const panel of panels) {{
      const selected = panel.dataset.reportTab === tab;
      panel.hidden = !selected;
      if (selected) selectedPanel = panel;
    }}
    if (options.scroll === true && selectedPanel) {{
      requestAnimationFrame(() => {{
        selectedPanel.scrollIntoView({{ block: "start", inline: "nearest" }});
      }});
    }}
  }}
  for (const button of buttons) {{
    button.addEventListener("click", () => {{
      const tab = button.dataset.reportTabButton;
      activate(tab, {{ scroll: true }});
      history.replaceState(null, "", `#${{tab}}`);
    }});
  }}
  const hash = location.hash.replace("#", "");
  activate(validTabs.has(hash) ? hash : panels[0].dataset.reportTab);
}})();
(() => {{
  const lightbox = document.querySelector("[data-image-lightbox]");
  if (!lightbox) return;
  const lightboxImage = lightbox.querySelector("img");
  const caption = lightbox.querySelector("[data-lightbox-caption]");
  const closeButton = lightbox.querySelector("[data-lightbox-close]");
  let returnFocus = null;

  function openLightbox(link) {{
    returnFocus = link;
    lightboxImage.src = link.href;
    lightboxImage.alt = link.querySelector("img")?.alt || "";
    caption.textContent = link.dataset.lightboxCaption || lightboxImage.alt || "";
    lightbox.hidden = false;
    lightbox.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    closeButton?.focus();
  }}

  function closeLightbox() {{
    lightbox.hidden = true;
    lightbox.setAttribute("aria-hidden", "true");
    lightboxImage.removeAttribute("src");
    document.body.style.overflow = "";
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
    returnFocus = null;
  }}

  document.addEventListener("click", (event) => {{
    const link = event.target.closest?.("[data-lightbox-image]");
    if (link) {{
      event.preventDefault();
      openLightbox(link);
      return;
    }}
    if (!lightbox.hidden && event.target === lightbox) closeLightbox();
    if (!lightbox.hidden && event.target.closest?.("[data-lightbox-close]")) closeLightbox();
  }});

  document.addEventListener("keydown", (event) => {{
    if (event.key === "Escape" && !lightbox.hidden) closeLightbox();
  }});
}})();
</script></body>
</html>
"""


def _planner_report_css() -> str:
    return """    .diagnostic-view {
      background: #ffffff;
    }
    .diagnostic-visual {
      border-radius: 8px;
      overflow: hidden;
      background: #f8fafc;
    }
    .diagnostic-visual svg {
      width: 100%;
      height: auto;
      display: block;
    }
    .diagnostic-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .diagnostic-stat {
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 8px;
      background: #f8fafc;
    }
    .diagnostic-stat small {
      display: block;
      color: #64748b;
      margin-bottom: 3px;
    }
    .diagnostic-stat strong {
      color: #0f172a;
    }
    .post-placement-rejection-views h3 {
      margin: 14px 0 8px;
      font-size: 15px;
    }
    .rejection-view .diagnostic-visual {
      background: #fff7ed;
    }
    .grasp-blocker-matrix {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .grasp-blocker-card {
      border: 1px solid #fecaca;
      border-radius: 8px;
      padding: 12px;
      background: #fff7f7;
    }
    .grasp-blocker-route {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 8px;
      align-items: center;
      margin-bottom: 8px;
    }
    .grasp-blocker-route strong {
      overflow-wrap: anywhere;
    }
    .grasp-blocker-route span {
      color: #64748b;
      font-size: 12px;
    }
    .grasp-blocker-card p {
      margin: 8px 0 0;
      color: #475569;
    }
    .decision-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin: 0 0 12px;
    }
    .decision-card {
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      padding: 12px;
      background: #eff6ff;
    }
    .decision-card h3 { margin: 0 0 6px; font-size: 14px; color: #1e3a8a; }
    .decision-card strong {
      display: block;
      color: #0f172a;
      overflow-wrap: anywhere;
      margin-bottom: 8px;
    }
    .decision-card p { margin: 0; color: #475569; }
"""


def _receptacle_positions() -> dict[str, tuple[int, int]]:
    return {
        "sofa_01": (160, 130),
        "floor_01": (450, 250),
        "armchair_01": (725, 130),
        "desk_01": (160, 350),
        "coffee_table_01": (450, 130),
        "sink_01": (725, 350),
        "bookshelf_01": (160, 465),
        "laundry_hamper_01": (450, 465),
        "fridge_01": (725, 465),
        "toy_bin_01": (450, 350),
    }


def write_trace_jsonl(trace_path: Path, events: list[dict[str, Any]]) -> None:
    trace_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
