from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from roboclaws.household.semantic_timeline import (
    OBJECT_DONE_PHASE,
    PLACE_CLEANUP_PHASES,
    SEMANTIC_LOOP_DISPLAY_NOTE,
    display_semantic_subphases,
)


def empty_state_block(title: str, message: str) -> str:
    return (
        f'<div class="empty-state"><h3>{html.escape(title)}</h3><p>{html.escape(message)}</p></div>'
    )


def review_image(path: Any, alt: str, *, caption: str | None = None) -> str:
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


def badge(label: str, value: Any) -> str:
    return (
        f'<span class="badge">{html.escape(str(label))}: '
        f"<strong>{html.escape(str(value))}</strong></span>"
    )


def metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )


def present_sections(sections: list[str]) -> list[str]:
    return [section for section in sections if section]


def path_table(rows: list[tuple[str, Any]]) -> str:
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
        f"{review_image(path, f'{label} view')}"
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


def moves_table(moves: list[dict[str, Any]]) -> str:
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


def semantic_steps_table(semantic_substeps: list[dict[str, Any]]) -> str:
    if not semantic_substeps:
        return (
            '<section class="panel semantic-section semantic-section-empty">'
            "<h2>Semantic Substeps</h2>"
            + empty_state_block(
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


def extract_moves(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    for event in trace_events:
        if event.get("tool") not in {"place", "place_inside"} or event.get("event") != "response":
            continue
        response = event.get("response")
        if isinstance(response, dict) and response.get("ok"):
            moves.append(response)
    return moves
