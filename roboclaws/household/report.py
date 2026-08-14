from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from roboclaws.core.rerun import (
    report_rerun_command_from_env,
)
from roboclaws.household.report_document import wrap_report_html
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
from roboclaws.household.report_sections_isaac import isaac_runtime_section
from roboclaws.household.report_sections_map import (
    map_evidence_refresh_summary_section,
    runtime_metric_map_preview_section,
)
from roboclaws.household.report_sections_nav2_map import nav2_map_bundle_section
from roboclaws.household.report_sections_proof import (
    attached_planner_proof_section,
    cleanup_primitive_gate_section,
    manipulation_provenance_section,
    planner_cleanup_bridge_section,
    planner_proof_requests_section,
)
from roboclaws.household.report_sections_robot import (
    robot_timeline_section,
    visual_core_robot_view_steps,
)
from roboclaws.household.report_sections_timing import runtime_timing_section
from roboclaws.household.report_tables import (
    _artifact_link,
    _report_asset_src,
    _score_table,
    _view_figure,
    _yes_no,
    badge,
    empty_state_block,
    extract_moves,
    metric,
    moves_table,
    present_sections,
    review_image,
    semantic_steps_table,
)
from roboclaws.household.semantic_timeline import (
    PLACE_CLEANUP_PHASES,
)
from roboclaws.household.types import CleanupScenario


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
        wrap_report_html(body, rerun_command=rerun_command, title=report_title),
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
    moves = extract_moves(trace_events)
    score = run_result["score"]
    return present_sections(
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
                        empty_state_block=empty_state_block,
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
                [semantic_steps_table(run_result.get("semantic_substeps") or [])],
            ),
            _report_tab_panel(
                "robot",
                [
                    agibot_sdk_runner_section(
                        run_dir,
                        run_result,
                        metric=metric,
                        artifact_link=_artifact_link,
                    ),
                    isaac_runtime_section(
                        run_dir,
                        run_result,
                        metric=metric,
                        artifact_link=_artifact_link,
                        yes_no=_yes_no,
                    ),
                    nav2_map_bundle_section(
                        run_dir,
                        run_result,
                        metric=metric,
                        review_image=review_image,
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
    body = "\n".join(present_sections(sections))
    if not body:
        body = empty_state_block(
            "No report data recorded",
            "This run did not produce artifacts for this report section.",
        )
    escaped_id = html.escape(tab_id)
    return (
        f'<div id="report-tab-{escaped_id}" class="report-tab-panel" '
        f'data-report-tab="{escaped_id}" role="tabpanel" '
        f'aria-labelledby="report-tab-button-{escaped_id}">{body}</div>'
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
          {badge("Scenario", scenario.scenario_id)}
          {badge("Backend", run_result.get("backend", "unknown"))}
          {badge("Contract", run_result.get("contract", "legacy"))}
          {badge("Status", _summary_status_label(_summary_status(run_result)))}
          {badge("Restored", restored_summary)}
          {badge("Generated mess", _generated_mess_summary(run_result))}
          {badge("Policy", run_result.get("policy", run_result.get("planner", "unknown")))}
          {evidence_lane_badges(run_result, badge)}
          {badge("Agent driven", run_result.get("agent_driven", False))}
          {badge("Provenance", run_result["primitive_provenance"])}
          {badge("MCP server", run_result.get("mcp_server", "none"))}
          {_confidence_layer_badges(run_result)}
          {_robotbadge(run_result)}
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
          {review_image(before_name, "Before cleanup")}
          <figcaption>
            <strong>Initial room state</strong>
            <span>Object locations before the cleanup loop.</span>
          </figcaption>
        </figure>
        <figure>
          {review_image(after_name, "After cleanup")}
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
        f"{review_image(path, label)}"
        f"<figcaption><strong>{escaped_label}</strong><span>{escaped_caption}</span></figcaption>"
        "</figure>"
    )


def _object_moves_section(moves: list[dict[str, Any]]) -> str:
    return f"""
    <section class="panel">
      <h2>Object Moves</h2>
      {moves_table(moves)}
    </section>
    """


def _score_section(score: dict[str, Any]) -> str:
    return f"""
    <section class="panel">
      <h2>Score</h2>
      {_score_table(score)}
    </section>
    """


def _summary_metrics(run_result: dict[str, Any], score: dict[str, Any]) -> str:
    semantic = score.get("semantic_acceptability")
    semantic_count = ""
    if isinstance(semantic, dict):
        semantic_count = f"{semantic.get('accepted_count', 0)}/{semantic.get('total_targets', 0)}"
    restored_count = f"{score.get('restored_count', 0)}/{score.get('total_targets', 0)}"
    return (
        '<div class="metric-grid">'
        f"{metric('Status', _summary_status_label(_summary_status(run_result)))}"
        f"{metric('Restored', restored_count)}"
        f"{metric('Generated', _generated_mess_summary(run_result))}"
        f"{metric('Sweep', _rate_text(run_result.get('sweep_coverage_rate')))}"
        f"{metric('Disturbance', run_result.get('disturbance_count', 0))}"
        f"{metric('Semantic', semantic_count or 'n/a')}"
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


def _robotbadge(run_result: dict[str, Any]) -> str:
    robot_name = run_result.get("robot_name")
    if not robot_name:
        return ""
    return badge("Robot", robot_name)


def _robot_view_camera_badges(run_result: dict[str, Any]) -> str:
    summary = run_result.get("robot_view_camera_control")
    if not isinstance(summary, dict):
        return ""
    return badge("Robot-view camera", summary.get("status", "unknown")) + badge(
        "Head-camera FPV", summary.get("head_camera_fpv", False)
    )


def _confidence_layer_badges(run_result: dict[str, Any]) -> str:
    layer = run_result.get("confidence_layer")
    if not layer:
        return ""
    return "".join(
        (
            badge("Confidence layer", layer),
            badge("Next layer", run_result.get("next_confidence_layer", "unknown")),
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
