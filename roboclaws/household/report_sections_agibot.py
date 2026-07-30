from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Callable


def agibot_sdk_runner_section(
    run_dir: Path,
    run_result: dict[str, Any],
    *,
    metric: Callable[[str, Any], str],
    artifact_link: Callable[[str, Path], str],
) -> str:
    runner = run_result.get("agibot_sdk_runner") or {}
    if not runner:
        return ""
    rows = []
    for item in runner.get("subphase_reports") or []:
        stage = str(item.get("stage", ""))
        report = str(item.get("report") or "")
        run_result_path = str(item.get("run_result") or "")
        rows.append(
            "<tr>"
            f"<td>{html.escape(stage)}</td>"
            f"<td>{html.escape(_agibot_public_tool_mapping(stage))}</td>"
            f"<td>{html.escape(_agibot_subphase_status_label(item))}</td>"
            f"<td>{artifact_link(report, run_dir)}</td>"
            f"<td>{artifact_link(run_result_path, run_dir)}</td>"
            "</tr>"
        )
    table = (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Backend stage</th><th>Maps to public tool</th><th>Evidence status</th>"
        "<th>Report</th><th>Run result</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )
    tools = ", ".join(str(item) for item in runner.get("public_tool_boundary") or [])
    gdk_imported = runner.get("gdk_imported_by_roboclaws", "unknown")
    next_layer = str(runner.get("next_confidence_layer") or "")
    metrics = (
        '<div class="metric-grid">'
        f"{metric('Backend variant', runner.get('backend_variant', 'unknown'))}"
        f"{metric('Runtime', runner.get('runtime', 'n/a'))}"
        f"{metric('Simulated', runner.get('simulated', 'n/a'))}"
        f"{metric('Physical robot', runner.get('physical_robot', 'n/a'))}"
        f"{metric('Movement enabled', runner.get('real_movement_enabled', False))}"
        f"{metric('GDK imported by Roboclaws', gdk_imported)}"
        f"{metric('Sub-phase reports', len(runner.get('subphase_reports') or []))}"
        "</div>"
    )
    heading = "AgiBot Backend Evidence <span>CLI boundary</span>"
    intro = (
        "One Roboclaws pilot run is replayed through three SDK-owned backend "
        "stages. The table maps each backend artifact back to the public "
        "household tool it supports, so these rows read as "
        "evidence for the same cleanup-shaped run rather than separate tasks. "
        "Dry-run rows are reviewable rehearsal evidence, not physical PNC "
        "execution proof."
    )
    next_layer_note = (
        '<p class="note">Next confidence layer: '
        f"{html.escape(next_layer)}. This report is the map/SDK dry-run layer; "
        "semantic cleanup actions and real GDK execution remain separate layers.</p>"
        if next_layer
        else ""
    )
    return (
        '<section class="panel agibot-sdk-runner">'
        f"<h2>{heading}</h2>"
        f'<p class="note">{html.escape(intro)}</p>'
        f"{metrics}"
        f'<p class="note">Public Roboclaws tools preserved: {html.escape(tools)}</p>'
        f"{next_layer_note}"
        f"{table}</section>"
    )


def _agibot_public_tool_mapping(stage: str) -> str:
    mappings = {
        "agent_view_export": "metric_map",
        "observe": "observe",
        "navigate_waypoint": "navigate_to_waypoint",
        "blocked_manipulation": "pick, place, place_inside, open_receptacle, close_receptacle",
    }
    return mappings.get(stage, "backend evidence")


def _agibot_subphase_status_label(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "")
    if status == "ok":
        return "OK"
    if status == "dry_run_blocked_capability":
        return "Dry-run blocked"
    if item.get("ok") is True:
        return "OK"
    return status.replace("_", " ").title() if status else "Unknown"
