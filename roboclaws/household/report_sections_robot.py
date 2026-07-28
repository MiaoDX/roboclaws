from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.semantic_timeline import (
    CLOSE_RECEPTACLE_PHASE,
    PLACE_CLEANUP_PHASES,
    annotate_focus_visual_grounding,
    display_semantic_subphase,
)

EmptyStateRenderer = Callable[[str, str], str]
ViewFigureRenderer = Callable[[Any, str], str]
ReportAssetSrcResolver = Callable[[Any, Path | None], str]


def robot_timeline_section(
    run_dir: Path,
    steps: list[dict[str, Any]],
    *,
    empty_state_block: EmptyStateRenderer,
    view_figure: ViewFigureRenderer,
    report_asset_src: ReportAssetSrcResolver,
) -> str:
    if not steps:
        return (
            '<section class="panel robot-timeline robot-timeline-empty">'
            "<h2>Robot View Timeline</h2>"
            + empty_state_block(
                "No robot-view timeline captured",
                "This run did not record FPV/topdown/chase timeline frames. Review the "
                "Robot & Map tab for static map artifacts, SDK subphase reports, and "
                "navigation rehearsal evidence.",
            )
            + "</section>"
        )
    static_capture = _timeline_uses_static_isaac_captures(steps)
    cards = []
    previous_action = ""
    for index, step in enumerate(steps, start=1):
        cards.append(
            _robot_step_card(
                run_dir=run_dir,
                step=step,
                index=index,
                previous_action=previous_action,
                view_figure=view_figure,
                report_asset_src=report_asset_src,
            )
        )
        previous_action = str(step.get("action", step.get("label", "")))
    step_label = "step" if len(cards) == 1 else "steps"
    return (
        '<section class="panel robot-timeline"><h2>Robot View Timeline</h2>'
        f"{_isaac_static_robot_view_notice(static_capture)}"
        '<p class="note">FPV and top-down scene views are the default visual review '
        "surfaces. Base Metric Map preview and Runtime Metric Map evidence are "
        "rendered separately from scene imagery. "
        "FPV+bbox verification is generated from public visual-grounding boxes when present. "
        "Chase and top-view bbox verification are simulation/report-only evidence, "
        "not policy input and not private scoring truth. Observe role badges distinguish "
        "post-place verification from the next waypoint scan. Focus badges are "
        "public-state object/receptacle bindings; visibility badges say whether "
        "that bound object is actually visible in the current frame.</p>"
        f'<details class="robot-timeline-details" open><summary>Show {len(cards)} captured '
        f"robot-view {step_label}</summary>" + "".join(cards) + "</details></section>"
    )


def visual_core_robot_view_steps(
    run_result: dict[str, Any],
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _has_raw_fpv_observations(run_result):
        return steps
    return [step for step in steps if not _is_raw_fpv_observation_step(step)]


def _robot_step_card(
    *,
    run_dir: Path,
    step: dict[str, Any],
    index: int,
    previous_action: str,
    view_figure: ViewFigureRenderer,
    report_asset_src: ReportAssetSrcResolver,
) -> str:
    views = step.get("views", {})
    pose = step.get("robot_pose") or {}
    focus = annotate_focus_visual_grounding(step.get("focus") or {}) or {}
    semantic_phase = step.get("semantic_phase")
    fpv_bbox = _write_fpv_bbox_verification(run_dir, step, index, report_asset_src)
    pose_text = _robot_timeline_pose_text(pose)
    fpv_bbox_figure = view_figure(fpv_bbox, "FPV + bbox verification") if fpv_bbox else ""
    top_view_verify = (
        view_figure(views.get("verify"), "Top-view bbox verification sim-only")
        if focus.get("has_focus")
        else ""
    )
    sim_only_views = _sim_only_views(
        [
            figure
            for figure in (
                view_figure(views.get("chase"), "Chase sim-only"),
                top_view_verify,
            )
            if figure
        ]
    )
    return (
        '<article class="robot-step">'
        f"<h3>{index}. {html.escape(str(step.get('action', step.get('label', 'step'))))}</h3>"
        f'<p class="pose">{html.escape(pose_text)}</p>'
        f"{_semantic_phase_summary(semantic_phase)}"
        f"{_observation_role_summary(step, previous_action)}"
        f"{action_evidence_summary(step)}"
        f"{_focus_summary(step, focus)}"
        f"{_robot_evidence_summary(step)}"
        f"{_robot_view_provenance_summary(step)}"
        f"{robot_view_camera_contract_summary(step.get('camera_control_contract'))}"
        '<div class="views robot-primary-views">'
        f"{view_figure(views.get('fpv'), 'FPV')}"
        f"{view_figure(views.get('topdown'), 'Top-down Scene View')}"
        f"{fpv_bbox_figure}"
        "</div>"
        f"{sim_only_views}"
        "</article>"
    )


def _sim_only_views(figures: list[str]) -> str:
    if not figures:
        return ""
    grid_class = "views sim-only-grid"
    if len(figures) == 1:
        grid_class += " sim-only-grid-single"
    return (
        '<details class="sim-only-views"><summary>Simulation/report-only views</summary>'
        f'<div class="{grid_class}">'
        f"{''.join(figures)}"
        "</div></details>"
    )


def _timeline_uses_static_isaac_captures(steps: list[dict[str, Any]]) -> bool:
    return any(_step_uses_static_isaac_capture(step) for step in steps)


def _robot_timeline_pose_text(pose: dict[str, Any]) -> str:
    theta = pose.get("theta", pose.get("yaw_deg", "?"))
    theta_label = "theta" if "theta" in pose else "yaw_deg"
    return (
        f"x={pose.get('x', '?')} y={pose.get('y', '?')} "
        f"{theta_label}={theta} head_pitch={pose.get('head_pitch', '?')}"
    )


def _step_uses_static_isaac_capture(step: dict[str, Any]) -> bool:
    provenance = step.get("view_provenance")
    if not isinstance(provenance, dict):
        return False
    if provenance.get("semantic_pose_state_refreshed") is False:
        return True
    return "isaac_lab_camera_rgb_static_robot_views" in json.dumps(provenance, sort_keys=True)


def _isaac_static_robot_view_notice(enabled: bool) -> str:
    if not enabled:
        return ""
    return (
        '<p class="note robot-view-caveat"><strong>Isaac report-only view caveat:</strong> '
        "these FPV/topdown/chase/verify frames are static captures from the loaded USD "
        "scene, reused across semantic cleanup steps. The cleanup state changes are "
        "recorded in backend JSON as isaac_semantic_pose; they are not rendered back "
        "into the Isaac USD stage yet.</p>"
    )


def _robot_view_provenance_summary(step: dict[str, Any]) -> str:
    provenance = (
        step.get("view_provenance") if isinstance(step.get("view_provenance"), dict) else {}
    )
    if not provenance:
        return ""
    note = str(provenance.get("evidence_note") or "")
    if _step_uses_static_isaac_capture(step):
        badges = _badge("Isaac view", "static report-only")
        badges += _badge("Step render", "not refreshed")
    elif _step_uses_refreshed_isaac_semantic_pose_capture(step):
        badges = _badge("Isaac view", "semantic pose rerender")
        badges += _badge("Step render", "refreshed")
    else:
        return ""
    if note:
        badges += _badge("Evidence note", note)
    return '<div class="semantic-badges robot-view-provenance">' + badges + "</div>"


def _step_uses_refreshed_isaac_semantic_pose_capture(step: dict[str, Any]) -> bool:
    provenance = step.get("view_provenance")
    if not isinstance(provenance, dict):
        return False
    if provenance.get("semantic_pose_state_refreshed") is True:
        return True
    return "isaac_lab_camera_rgb_semantic_pose_robot_views" in json.dumps(
        provenance,
        sort_keys=True,
    )


def robot_view_camera_contract_summary(contract: Any) -> str:
    if not isinstance(contract, dict):
        return ""
    badges = "".join(
        [
            _badge("Camera contract", contract.get("status", "unknown")),
            _badge("Camera model", contract.get("camera_model", "unknown")),
            _badge(
                "Head-camera FPV",
                contract.get("camera_model", "")
                in {
                    "robot_mounted_head_camera_v1",
                    "robot_head_camera_equivalent_v1",
                },
            ),
        ]
    )
    fpv = (
        contract.get("agent_facing_fpv")
        if isinstance(contract.get("agent_facing_fpv"), dict)
        else {}
    )
    fpv_source = fpv.get("source")
    if fpv_source:
        badges += _badge("FPV source", fpv_source)
    lighting = (
        contract.get("lighting_profile")
        if isinstance(contract.get("lighting_profile"), dict)
        else {}
    )
    if lighting:
        badges += _badge("Lighting", lighting.get("profile_id", "unknown"))
    color = contract.get("color_profile") if isinstance(contract.get("color_profile"), dict) else {}
    if color:
        badges += _badge("Color", color.get("profile_id", "unknown"))
    note = str(contract.get("evidence_note") or "")
    note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""
    return f'<div class="semantic-badges robot-view-camera-contract">{badges}</div>{note_html}'


def _write_fpv_bbox_verification(
    run_dir: Path,
    step: dict[str, Any],
    index: int,
    report_asset_src: ReportAssetSrcResolver,
) -> str:
    focus = annotate_focus_visual_grounding(step.get("focus") or {}) or {}
    visibility = focus.get("fpv_visibility") or {}
    boxes = visibility.get("boxes") or []
    if not boxes:
        return ""
    views = step.get("views") or {}
    fpv_path = _resolve_report_asset_path(run_dir, views.get("fpv"))
    if fpv_path is None:
        return ""
    label = str(step.get("label") or f"{index:04d}_fpv")
    output_path = fpv_path.with_name(f"{fpv_path.stem}.bbox.png")
    try:
        with Image.open(fpv_path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        for box in boxes:
            _draw_bbox(draw, box)
        image.save(output_path, format="PNG")
    except OSError:
        return ""
    return report_asset_src(output_path, run_dir) or f"robot_views/{html.escape(label)}.bbox.png"


def _resolve_report_asset_path(run_dir: Path, path: Any) -> Path | None:
    if not path:
        return None
    candidate = Path(str(path))
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    rooted = run_dir / candidate
    if rooted.exists():
        return rooted
    if candidate.exists():
        return candidate.resolve()
    return None


def _draw_bbox(draw: ImageDraw.ImageDraw, box: dict[str, Any]) -> None:
    bbox = box.get("bbox") or []
    if len(bbox) != 4:
        return
    try:
        x0, y0, x1, y1 = [int(value) for value in bbox]
    except (TypeError, ValueError):
        return
    try:
        color = tuple(int(value) for value in (box.get("color") or [239, 68, 68])[:3])
    except (TypeError, ValueError):
        color = (239, 68, 68)
    label = str(box.get("label") or "")
    draw.rectangle((x0, y0, x1, y1), outline=color, width=3)
    if not label:
        return
    try:
        text_box = draw.textbbox((x0, y0), label)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
    except AttributeError:
        text_width = max(40, len(label) * 7)
        text_height = 12
    label_y = max(0, y0 - text_height - 6)
    draw.rectangle((x0, label_y, x0 + text_width + 6, label_y + text_height + 6), fill=color)
    draw.text((x0 + 3, label_y + 3), label, fill=(255, 255, 255))


def _has_raw_fpv_observations(run_result: dict[str, Any]) -> bool:
    observations = run_result.get("raw_fpv_observations")
    agent_view = run_result.get("agent_view") or {}
    if observations is None and _is_agent_view_v2(agent_view):
        observations = agent_view_module.raw_fpv_observations(agent_view)
    return bool(observations)


def _is_agent_view_v2(payload: Any) -> bool:
    return (
        isinstance(payload, dict) and payload.get("schema") == agent_view_module.AGENT_VIEW_SCHEMA
    )


def _is_raw_fpv_observation_step(step: dict[str, Any]) -> bool:
    if step.get("semantic_phase"):
        return False
    action = str(step.get("action") or "")
    label = str(step.get("label") or "")
    return action.startswith("observe raw_fpv_") or "_raw_fpv_" in f"_{label}"


def _semantic_phase_summary(semantic_phase: Any) -> str:
    if not semantic_phase:
        return ""
    raw = str(semantic_phase)
    displayed = display_semantic_subphase(semantic_phase)
    if displayed is None:
        badges = _badge("Subphase", raw)
    else:
        badges = _badge("Subphase", displayed["label"])
        badges += _badge("Role", displayed["detail"])
        badges += _badge("Raw phase", raw)
    return '<div class="semantic-badges">' + badges + "</div>"


def _observation_role_summary(step: dict[str, Any], previous_action: str) -> str:
    if _action_tool(str(step.get("action", ""))) != "observe":
        return ""
    previous_tool = _action_tool(previous_action)
    if previous_tool in {*PLACE_CLEANUP_PHASES, CLOSE_RECEPTACLE_PHASE}:
        role = "post-place verification"
        raw_role = "post_place_observe"
    else:
        role = "waypoint scan"
        raw_role = "coverage_scan_observe"
    badges = _badge("Observe role", role)
    badges += _badge("Raw role", raw_role)
    return '<div class="semantic-badges">' + badges + "</div>"


def _focus_summary(step: dict[str, Any], focus: dict[str, Any]) -> str:
    if not focus.get("has_focus"):
        return ""
    bits = []
    handle = _observed_handle_from_action(str(step.get("action", "")))
    if handle:
        bits.append(_badge("Handle", handle))
    if focus.get("object_label"):
        bits.append(_badge("Object", focus["object_label"]))
    if focus.get("receptacle_label"):
        bits.append(_badge("Target", focus["receptacle_label"]))
    if focus.get("provenance"):
        bits.append(_badge("Focus provenance", focus["provenance"]))
    return '<div class="focus-badges">' + "".join(bits) + "</div>"


def _robot_evidence_summary(step: dict[str, Any]) -> str:
    pose = step.get("robot_pose") or {}
    focus = annotate_focus_visual_grounding(step.get("focus") or {}) or {}
    bits = []
    if pose.get("theta_source"):
        bits.append(_badge("Theta", pose["theta_source"]))
    if pose.get("head_pitch_source"):
        bits.append(_badge("Head pitch", pose["head_pitch_source"]))
    if pose.get("target_room_id"):
        relation = "same room" if pose.get("same_room_as_target") else "room mismatch"
        room_text = f"{relation} ({pose.get('robot_room_id')} -> {pose.get('target_room_id')})"
        bits.append(_badge("Room", room_text))
    if focus.get("has_focus"):
        fpv_visibility = focus.get("fpv_visibility") or {}
        if fpv_visibility.get("status") in {
            "ok",
            "weak_object_visibility",
            "contained_inside",
        }:
            bits.append(_badge("FPV visibility", _visibility_text(fpv_visibility)))
        visibility = focus.get("visibility") or {}
        if visibility.get("status") in {"ok", "weak_object_visibility", "contained_inside"}:
            bits.append(_badge("Verify visibility", _visibility_text(visibility)))
    if not bits:
        return ""
    return '<div class="evidence-badges">' + "".join(bits) + "</div>"


def action_evidence_summary(step: dict[str, Any]) -> str:
    evidence = step.get("action_evidence")
    if not isinstance(evidence, dict) or not evidence:
        return ""
    badges = _action_evidence_badges(evidence)
    note = str(evidence.get("evidence_note") or evidence.get("grounding_basis") or "")
    note_html = f'<p class="note action-evidence-note">{html.escape(note)}</p>' if note else ""
    if not badges and not note_html:
        return ""
    return '<div class="action-evidence-badges">' + "".join(badges) + f"</div>{note_html}"


def _action_evidence_badges(evidence: dict[str, Any]) -> list[str]:
    badges = []
    for label, value in _simple_action_evidence_badges(evidence):
        if value:
            badges.append(_badge(label, value))
    grounding = _grounding_badge_value(evidence)
    if grounding:
        badges.append(_badge("Grounding", grounding))
    for label, value in _resolved_action_evidence_badges(evidence):
        if value:
            badges.append(_badge(label, value))
    return badges


def _simple_action_evidence_badges(evidence: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("Agent tool", evidence.get("agent_tool")),
        ("Source observe", evidence.get("source_observation_id")),
        ("Source FPV bbox", _format_bbox(evidence.get("source_image_bbox"))),
        ("BBox review", evidence.get("reviewability_status")),
        ("Locality", evidence.get("locality_status")),
        ("Candidate state", evidence.get("candidate_state")),
        ("Authorization", evidence.get("actionability_status")),
    ]


def _resolved_action_evidence_badges(evidence: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("Resolved handle", evidence.get("resolved_object_id")),
        ("Backend primitive", evidence.get("backend_primitive")),
        ("Declared category", evidence.get("declared_category")),
        ("Public target", evidence.get("target_fixture_id")),
    ]


def _grounding_badge_value(evidence: dict[str, Any]) -> str:
    if not evidence.get("grounding_status"):
        return ""
    grounding = str(evidence["grounding_status"])
    if evidence.get("grounding_confidence") is not None:
        grounding += f" ({evidence['grounding_confidence']})"
    return grounding


def _format_bbox(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return ""
    return "[" + ", ".join(_format_bbox_value(item) for item in value) + "]"


def _format_bbox_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _visibility_text(visibility: dict[str, Any]) -> str:
    object_pixels = _pixel_count(visibility.get("object_pixels"))
    target_pixels = _pixel_count(visibility.get("receptacle_pixels"))
    status = str(visibility.get("visual_grounding_status") or visibility.get("status") or "")
    if status == "contained_inside":
        object_text = "object contained inside"
    else:
        object_text = f"object {object_pixels} px" if object_pixels > 0 else "object not visible"
    target_text = f"target {target_pixels} px" if target_pixels > 0 else "target not visible"
    if status and status != "ok":
        return f"{status}: {object_text}, {target_text}"
    return f"{object_text}, {target_text}"


def _pixel_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _action_tool(action: str) -> str:
    return action.split(" ", 1)[0] if action else ""


def _observed_handle_from_action(action: str) -> str:
    parts = action.split()
    if len(parts) >= 2 and parts[1].startswith("observed_"):
        return parts[1]
    return ""


def _badge(label: str, value: Any) -> str:
    return (
        f'<span class="badge">{html.escape(str(label))}: '
        f"<strong>{html.escape(str(value))}</strong></span>"
    )
