#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from roboclaws.core.json_sources import read_json_object, read_jsonl_object_rows
from roboclaws.core.task_intents import HOUSEHOLD_INTENT_CLEANUP, household_task_identity

SCHEMA = "roboclaws_visual_showcase_v1"
DEFAULT_SIZE = (1280, 720)
DEFAULT_DURATION_MS = 900
DEFAULT_HOLD_MS = 1400
TOOLS = [
    ("observe", "Observe"),
    ("navigate_to_object", "Nav object"),
    ("pick", "Pick"),
    ("navigate_to_receptacle", "Nav receptacle"),
    ("open_receptacle", "Open"),
    ("place", "Place"),
    ("place_inside", "Place inside"),
    ("close_receptacle", "Close"),
    ("done", "Done"),
]
ACTION_ALIASES = {
    "navigate_object": "navigate_to_object",
    "navigate_receptacle": "navigate_to_receptacle",
}
BACKGROUND = "#f5f7fb"
INK = "#111827"
MUTED = "#5b6472"
BORDER = "#cfd7e3"
PANEL = "#ffffff"
ACCENT = "#2563eb"
GREEN = "#15803d"
ORANGE = "#f97316"
BLACK = "#0b1020"


@dataclass(frozen=True)
class FrameSpec:
    label: str
    chapter: str
    title: str
    subtitle: str
    active_tool: str
    duration_ms: int = DEFAULT_DURATION_MS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a chaptered household cleanup showcase GIF from a completed run.",
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--basename", default="showcase")
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    parser.add_argument("--duration-ms", type=int, default=DEFAULT_DURATION_MS)
    parser.add_argument("--hold-ms", type=int, default=DEFAULT_HOLD_MS)
    parser.add_argument("--no-bbox", action="store_true", help="Use raw FPV frames.")
    parser.add_argument("--skip-gif", action="store_true")
    parser.add_argument(
        "--max-chain-frames",
        type=int,
        default=0,
        help="Optional cap per object chain. Zero keeps every action frame.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir or args.run_dir / "showcase"
    try:
        manifest = render_showcase(
            run_dir=args.run_dir,
            out_dir=out_dir,
            basename=args.basename,
            size=(args.width, args.height),
            duration_ms=args.duration_ms,
            hold_ms=args.hold_ms,
            prefer_bbox=not args.no_bbox,
            write_gif=not args.skip_gif,
            max_chain_frames=args.max_chain_frames,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(manifest, indent=2))
    return 0


def render_showcase(
    *,
    run_dir: Path,
    out_dir: Path,
    basename: str = "showcase",
    size: tuple[int, int] = DEFAULT_SIZE,
    duration_ms: int = DEFAULT_DURATION_MS,
    hold_ms: int = DEFAULT_HOLD_MS,
    prefer_bbox: bool = True,
    write_gif: bool = True,
    max_chain_frames: int = 0,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    out_dir = out_dir.resolve()
    run_result = _load_json(run_dir / "run_result.json")
    steps = _load_steps(run_result)
    frame_specs = build_frame_plan(
        run_dir=run_dir,
        run_result=run_result,
        steps=steps,
        duration_ms=duration_ms,
        hold_ms=hold_ms,
        max_chain_frames=max_chain_frames,
    )

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    eval_summary = _evaluation_summary(run_result)
    context = _run_context(run_result)
    rendered: list[Image.Image] = []
    selected_frames: list[dict[str, Any]] = []
    for index, spec in enumerate(frame_specs, start=1):
        step = steps[spec.label]
        frame = render_frame(
            run_dir=run_dir,
            step=step,
            spec=spec,
            size=size,
            prefer_bbox=prefer_bbox,
            frame_index=index,
            frame_count=len(frame_specs),
            eval_summary=eval_summary,
            context=context,
        )
        frame_name = f"{index:03d}_{_slug(spec.chapter)}_{_slug(spec.active_tool)}.png"
        frame_path = frames_dir / frame_name
        frame.save(frame_path)
        rendered.append(frame)
        selected_frames.append(
            {
                "index": index,
                "label": spec.label,
                "chapter": spec.chapter,
                "title": spec.title,
                "active_tool": spec.active_tool,
                "duration_ms": spec.duration_ms,
                "frame": _relative_to(frame_path, out_dir),
                "source_views": step.get("views", {}),
            }
        )

    contact_sheet_path = out_dir / "contact_sheet.png"
    _write_contact_sheet(rendered, frame_specs, contact_sheet_path)

    gif_path = out_dir / f"{basename}.gif"
    if write_gif:
        _write_gif(rendered, [spec.duration_ms for spec in frame_specs], gif_path)

    manifest = {
        "schema": SCHEMA,
        "source_run_dir": str(run_dir),
        "frame_count": len(frame_specs),
        "size": {"width": size[0], "height": size[1]},
        "context": context,
        "eval_summary": eval_summary,
        "public_private_boundary": (
            "FPV is the agent-facing visual panel. RPV/chase/map panels are report-only "
            "evidence. Scores are post-run evaluation, not agent input."
        ),
        "outputs": {
            "gif": _relative_to(gif_path, out_dir) if write_gif else None,
            "contact_sheet": _relative_to(contact_sheet_path, out_dir),
            "frames_dir": _relative_to(frames_dir, out_dir),
        },
        "selected_frames": selected_frames,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def build_frame_plan(
    *,
    run_dir: Path,
    run_result: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    duration_ms: int = DEFAULT_DURATION_MS,
    hold_ms: int = DEFAULT_HOLD_MS,
    max_chain_frames: int = 0,
) -> list[FrameSpec]:
    ordered_steps = sorted(steps.values(), key=lambda step: _label_index(str(step["label"])))
    total_waypoints = _inspection_waypoint_count(run_result)
    observe_progress = _observe_progress_by_label(run_dir / "trace.jsonl", total_waypoints)

    specs: list[FrameSpec] = []
    before = _first_step_with_action(ordered_steps, "before")
    if before:
        specs.append(
            FrameSpec(
                label=before["label"],
                chapter="Task",
                title="Household cleanup starts",
                subtitle=_context_subtitle(run_result),
                active_tool="observe",
                duration_ms=hold_ms,
            )
        )

    specs.extend(
        _observe_sweep_specs(
            ordered_steps,
            observe_progress=observe_progress,
            total_waypoints=total_waypoints,
            duration_ms=duration_ms,
        )
    )

    for chain_index, chain in enumerate(_object_action_chains(ordered_steps), start=1):
        chain_steps = _trim_chain(chain, max_chain_frames)
        chain_total = len(chain_steps)
        for action_index, step in enumerate(chain_steps, start=1):
            specs.append(
                _action_frame_spec(
                    step=step,
                    chain_index=chain_index,
                    action_index=action_index,
                    chain_total=chain_total,
                    duration_ms=duration_ms,
                )
            )

    after = _first_step_with_action(ordered_steps, "after")
    if after:
        specs.append(
            FrameSpec(
                label=after["label"],
                chapter="Done",
                title="Cleanup complete",
                subtitle=_final_subtitle(run_result),
                active_tool="done",
                duration_ms=hold_ms,
            )
        )

    return _dedupe_specs(specs)


def render_frame(
    *,
    run_dir: Path,
    step: dict[str, Any],
    spec: FrameSpec,
    size: tuple[int, int],
    prefer_bbox: bool,
    frame_index: int,
    frame_count: int,
    eval_summary: dict[str, Any],
    context: dict[str, Any],
) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(image)
    fonts = _fonts(width)
    margin = 24
    header_h = 84
    footer_h = 112
    content_y = header_h + 12
    content_h = height - content_y - footer_h - margin
    gap = 20
    main_w = min(int(content_h * 1.5), int((width - margin * 2 - gap) * 0.64))
    side_w = width - margin * 2 - gap - main_w
    main_box = (margin, content_y, margin + main_w, content_y + content_h)
    side_x = main_box[2] + gap
    side_gap = 18
    inset_h = (content_h - side_gap) // 2
    rpv_box = (side_x, content_y, side_x + side_w, content_y + inset_h)
    map_box = (side_x, content_y + inset_h + side_gap, side_x + side_w, content_y + content_h)

    _draw_header(draw, spec, context, frame_index, frame_count, fonts, width)
    _draw_image_panel(
        image,
        draw,
        _open_view_image(run_dir, step, "fpv", prefer_bbox=prefer_bbox),
        main_box,
        "Agent FPV",
        "input view",
        fonts,
        fill="#0f172a",
    )
    _draw_image_panel(
        image,
        draw,
        _open_view_image(run_dir, step, "chase", prefer_bbox=False),
        rpv_box,
        "RPV",
        "report-only view",
        fonts,
        fill="#111827",
    )
    _draw_image_panel(
        image,
        draw,
        _open_view_image(run_dir, step, "map", prefer_bbox=False),
        map_box,
        "Map / labels",
        "report-only evidence",
        fonts,
        fill="#111827",
    )
    _draw_footer(draw, spec, eval_summary, fonts, width, height)
    return image


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing required artifact: {path}")
    return read_json_object(path, label=path.name)


def _load_steps(run_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_steps = run_result.get("robot_view_steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("run_result.json does not contain robot_view_steps")
    steps: dict[str, dict[str, Any]] = {}
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict) or not raw_step.get("label"):
            continue
        steps[str(raw_step["label"])] = raw_step
    if not steps:
        raise ValueError("robot_view_steps does not contain labeled frames")
    return steps


def _inspection_waypoint_count(run_result: dict[str, Any]) -> int:
    candidates = (
        run_result.get("agent_view", {})
        .get("metric_map", {})
        .get("generated_exploration_candidates", [])
    )
    if isinstance(candidates, list) and candidates:
        return len(candidates)
    candidates = run_result.get("runtime_metric_map", {}).get("inspection_waypoints", [])
    if isinstance(candidates, list) and candidates:
        return len(candidates)
    return 0


def _observe_progress_by_label(trace_path: Path, total_waypoints: int) -> dict[str, dict[str, Any]]:
    if not trace_path.exists():
        return {}

    progress: dict[str, dict[str, Any]] = {}
    seen_waypoints: set[str] = set()
    pending: dict[str, Any] | None = None
    for _, event in read_jsonl_object_rows(trace_path, label="showcase trace"):
        if event.get("event") == "response" and event.get("tool") == "observe":
            response = event.get("response", {})
            waypoint_id = response.get("waypoint_id") or response.get("inspection_waypoint_id")
            if waypoint_id:
                seen_waypoints.add(str(waypoint_id))
            pending = {
                "observed": len(seen_waypoints),
                "total": total_waypoints or None,
                "source_observation_id": response.get("source_observation_id"),
                "waypoint_id": waypoint_id,
            }
        elif event.get("event") == "robot_view_capture" and event.get("action") == "observe":
            label = str(event.get("label") or "")
            if pending and label:
                progress[label] = pending
                pending = None
    return progress


def _observe_sweep_specs(
    ordered_steps: list[dict[str, Any]],
    *,
    observe_progress: dict[str, dict[str, Any]],
    total_waypoints: int,
    duration_ms: int,
) -> list[FrameSpec]:
    observe_steps = [
        step
        for step in ordered_steps
        if _base_action(step) == "observe" and _is_before_cleanup_actions(step, ordered_steps)
    ]
    if not observe_steps:
        return []

    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if observe_progress and total_waypoints > 0:
        thresholds = [1, max(1, math.ceil(total_waypoints / 2)), total_waypoints]
        for threshold in thresholds:
            for step in observe_steps:
                progress = observe_progress.get(str(step["label"]))
                if progress and int(progress.get("observed") or 0) >= threshold:
                    selected.append((step, progress))
                    break
    if not selected:
        indexes = sorted({0, len(observe_steps) // 2, len(observe_steps) - 1})
        selected = [(observe_steps[index], {}) for index in indexes]

    specs: list[FrameSpec] = []
    seen: set[str] = set()
    for step, progress in selected:
        label = str(step["label"])
        if label in seen:
            continue
        seen.add(label)
        observed = progress.get("observed")
        total = progress.get("total") or total_waypoints
        if observed and total:
            subtitle = f"Observe sweep: {observed}/{total} public exploration waypoints"
        else:
            subtitle = "Observe sweep: building public runtime evidence"
        specs.append(
            FrameSpec(
                label=label,
                chapter="Observe",
                title="Agent observes the scene",
                subtitle=subtitle,
                active_tool="observe",
                duration_ms=duration_ms,
            )
        )
    return specs


def _is_before_cleanup_actions(step: dict[str, Any], ordered_steps: list[dict[str, Any]]) -> bool:
    step_index = _label_index(str(step["label"]))
    first_action_index = min(
        (
            _label_index(str(candidate["label"]))
            for candidate in ordered_steps
            if _base_action(candidate)
            not in {
                "before",
                "observe",
                "after",
            }
        ),
        default=10**9,
    )
    return step_index < first_action_index


def _object_action_chains(ordered_steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    chains: list[list[dict[str, Any]]] = []
    current_key = ""
    current: list[dict[str, Any]] = []
    for step in ordered_steps:
        action = _base_action(step)
        if action in {"before", "observe", "after"}:
            continue
        key = _object_key(step)
        if current and key and key != current_key:
            chains.append(current)
            current = []
        current.append(step)
        current_key = key or current_key
    if current:
        chains.append(current)
    return chains


def _trim_chain(chain: list[dict[str, Any]], max_chain_frames: int) -> list[dict[str, Any]]:
    if max_chain_frames <= 0 or len(chain) <= max_chain_frames:
        return chain
    required_actions = {
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
    selected = [step for step in chain if _base_action(step) in required_actions]
    if len(selected) > max_chain_frames:
        if max_chain_frames == 1:
            return [selected[-1]]
        indexes = sorted(
            {
                round(index * (len(selected) - 1) / (max_chain_frames - 1))
                for index in range(max_chain_frames)
            }
        )
        return [selected[index] for index in indexes]
    return selected


def _action_frame_spec(
    *,
    step: dict[str, Any],
    chain_index: int,
    action_index: int,
    chain_total: int,
    duration_ms: int,
) -> FrameSpec:
    action = _base_action(step)
    focus = step.get("focus", {})
    obj = _pretty_category(focus.get("object_category")) or _observed_token(str(step["label"]))
    receptacle = _pretty_category(focus.get("receptacle_category"))
    chapter = obj or f"Object {chain_index}"
    if action in {"navigate_to_object", "pick"}:
        title = f"{obj}: {TOOLS_BY_ID().get(action, action)}"
        source = receptacle or "source surface"
        subtitle = f"Cleanup chain {chain_index}, step {action_index}/{chain_total}: from {source}"
    elif action in {"navigate_to_receptacle", "open_receptacle", "close_receptacle"}:
        target = receptacle or "target receptacle"
        title = f"{obj}: {TOOLS_BY_ID().get(action, action)}"
        subtitle = (
            f"Cleanup chain {chain_index}, step {action_index}/{chain_total}: target {target}"
        )
    else:
        target = receptacle or "target receptacle"
        title = f"{obj}: place at {target}"
        subtitle = f"Cleanup chain {chain_index}, step {action_index}/{chain_total}: {action}"
    return FrameSpec(
        label=str(step["label"]),
        chapter=chapter,
        title=title,
        subtitle=subtitle,
        active_tool=action,
        duration_ms=duration_ms,
    )


def _dedupe_specs(specs: list[FrameSpec]) -> list[FrameSpec]:
    output: list[FrameSpec] = []
    seen: set[str] = set()
    for spec in specs:
        key = f"{spec.label}:{spec.active_tool}:{spec.chapter}"
        if key in seen:
            continue
        seen.add(key)
        output.append(spec)
    return output


def _first_step_with_action(
    ordered_steps: list[dict[str, Any]], action: str
) -> dict[str, Any] | None:
    for step in ordered_steps:
        if _base_action(step) == action:
            return step
    return None


def _base_action(step: dict[str, Any]) -> str:
    action = str(step.get("semantic_phase") or step.get("action") or "").split()[0]
    return ACTION_ALIASES.get(action, action)


def _object_key(step: dict[str, Any]) -> str:
    focus = step.get("focus", {})
    object_id = focus.get("object_id")
    if object_id:
        return str(object_id)
    token = _observed_token(str(step.get("label") or ""))
    return token or str(focus.get("object_category") or "")


def _observed_token(label: str) -> str:
    match = re.search(r"(observed_\d+)", label)
    return match.group(1) if match else ""


def _label_index(label: str) -> int:
    match = re.match(r"(\d+)", label)
    return int(match.group(1)) if match else 10**8


def _open_view_image(
    run_dir: Path,
    step: dict[str, Any],
    view: str,
    *,
    prefer_bbox: bool,
) -> Image.Image:
    views = step.get("views", {})
    rel = views.get(view)
    if not rel and view == "map":
        rel = views.get("verify")
    if not rel:
        return _placeholder(f"missing {view}")
    path = run_dir / str(rel)
    if view == "fpv" and prefer_bbox:
        bbox_path = path.with_name(path.name.replace(".fpv.png", ".fpv.bbox.png"))
        if bbox_path.exists():
            path = bbox_path
    if not path.exists():
        return _placeholder(f"missing {view}")
    return Image.open(path).convert("RGB")


def _placeholder(label: str) -> Image.Image:
    image = Image.new("RGB", (540, 360), "#e5e7eb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline="#9ca3af", width=2)
    draw.text((16, 16), label, fill=INK)
    return image


def _draw_header(
    draw: ImageDraw.ImageDraw,
    spec: FrameSpec,
    context: dict[str, Any],
    frame_index: int,
    frame_count: int,
    fonts: dict[str, ImageFont.ImageFont],
    width: int,
) -> None:
    draw.rectangle((0, 0, width, 84), fill=PANEL)
    draw.line((0, 83, width, 83), fill=BORDER, width=1)
    draw.text((24, 18), spec.title, fill=INK, font=fonts["title"])
    subtitle = _fit_text(spec.subtitle, fonts["body"], max_width=width - 260)
    draw.text((24, 54), subtitle, fill=MUTED, font=fonts["body"])

    badge = f"{context.get('driver', 'agent')} | {context.get('profile', 'run')}"
    badge_w = _text_width(draw, badge, fonts["small"]) + 24
    badge_box = (width - badge_w - 24, 16, width - 24, 44)
    draw.rounded_rectangle(badge_box, radius=8, fill="#e8f0ff", outline="#b8cdf8")
    draw.text((badge_box[0] + 12, badge_box[1] + 7), badge, fill=ACCENT, font=fonts["small"])
    progress = f"{frame_index}/{frame_count}"
    draw.text(
        (width - 24 - _text_width(draw, progress, fonts["small"]), 54),
        progress,
        fill=MUTED,
        font=fonts["small"],
    )


def _draw_image_panel(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    source: Image.Image,
    box: tuple[int, int, int, int],
    title: str,
    note: str,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    fill: str,
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=10, fill=PANEL, outline=BORDER, width=1)
    label_h = 32
    draw.rounded_rectangle((x0, y0, x1, y0 + label_h), radius=10, fill=fill)
    draw.rectangle((x0, y0 + label_h - 10, x1, y0 + label_h), fill=fill)
    draw.text((x0 + 12, y0 + 8), title, fill="#ffffff", font=fonts["small_bold"])
    note_w = _text_width(draw, note, fonts["small"])
    draw.text((x1 - note_w - 12, y0 + 8), note, fill="#dbeafe", font=fonts["small"])

    inner = (x0 + 10, y0 + label_h + 10, x1 - 10, y1 - 10)
    fitted = ImageOps.contain(source, (inner[2] - inner[0], inner[3] - inner[1]))
    px = inner[0] + ((inner[2] - inner[0]) - fitted.width) // 2
    py = inner[1] + ((inner[3] - inner[1]) - fitted.height) // 2
    draw.rectangle(inner, fill="#0b1020")
    canvas.paste(fitted, (px, py))


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    spec: FrameSpec,
    eval_summary: dict[str, Any],
    fonts: dict[str, ImageFont.ImageFont],
    width: int,
    height: int,
) -> None:
    footer_y = height - 112
    draw.rectangle((0, footer_y, width, height), fill=PANEL)
    draw.line((0, footer_y, width, footer_y), fill=BORDER, width=1)

    _draw_tool_bar(draw, spec.active_tool, fonts, x=24, y=footer_y + 18, width=width - 48)
    caption = _fit_text(spec.subtitle, fonts["body"], max_width=width - 48)
    draw.text((24, footer_y + 58), caption, fill=INK, font=fonts["body"])
    eval_text = _eval_text(eval_summary)
    draw.text((24, footer_y + 86), eval_text, fill=MUTED, font=fonts["small"])


def _draw_tool_bar(
    draw: ImageDraw.ImageDraw,
    active_tool: str,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    x: int,
    y: int,
    width: int,
) -> None:
    gap = 8
    pill_h = 28
    labels = TOOLS
    raw_widths = [_text_width(draw, label, fonts["small"]) + 24 for _, label in labels]
    total = sum(raw_widths) + gap * (len(labels) - 1)
    scale = min(1.0, width / max(total, 1))
    cursor = x
    for (tool, label), raw_w in zip(labels, raw_widths, strict=True):
        pill_w = max(54, int(raw_w * scale))
        active = tool == active_tool or (active_tool == "place_inside" and tool == "place")
        fill = ACCENT if active else "#eef2f7"
        outline = "#1d4ed8" if active else BORDER
        text_fill = "#ffffff" if active else INK
        draw.rounded_rectangle(
            (cursor, y, cursor + pill_w, y + pill_h),
            radius=14,
            fill=fill,
            outline=outline,
        )
        text = _fit_text(label, fonts["small"], max_width=pill_w - 16)
        text_w = _text_width(draw, text, fonts["small"])
        draw.text(
            (cursor + (pill_w - text_w) // 2, y + 7), text, fill=text_fill, font=fonts["small"]
        )
        cursor += pill_w + gap


def _evaluation_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    score = run_result.get("score") or {}
    semantic = score.get("semantic_acceptability") or {}
    total = semantic.get("total_targets") or score.get("total_targets")
    return {
        "cleanup_status": run_result.get("cleanup_status") or score.get("status"),
        "completion_status": run_result.get("completion_status") or score.get("completion_status"),
        "semantic_accepted": semantic.get("accepted_count"),
        "semantic_total": total,
        "exact_restored": score.get("restored_count"),
        "exact_total": score.get("total_targets") or total,
        "disturbance_count": score.get("disturbance_count", run_result.get("disturbance_count")),
        "sweep_coverage_rate": run_result.get("sweep_coverage_rate")
        or score.get("sweep_coverage_rate"),
    }


def _eval_text(eval_summary: dict[str, Any]) -> str:
    semantic = _ratio(eval_summary.get("semantic_accepted"), eval_summary.get("semantic_total"))
    exact = _ratio(eval_summary.get("exact_restored"), eval_summary.get("exact_total"))
    disturbance = eval_summary.get("disturbance_count")
    if disturbance is None:
        disturbance = "?"
    return (
        "Post-run eval: "
        f"{semantic} semantic accepted | {exact} exact hidden-target match | "
        f"{disturbance} disturbances"
    )


def _ratio(value: Any, total: Any) -> str:
    return "?/?" if value is None or total is None else f"{value}/{total}"


def _run_context(run_result: dict[str, Any]) -> dict[str, Any]:
    task_identity = household_task_identity(
        surface=run_result.get("task_surface"),
        intent=run_result.get("task_intent") or HOUSEHOLD_INTENT_CLEANUP,
    )
    return {
        **task_identity,
        "driver": _driver_name(run_result),
        "profile": (
            run_result.get("evidence_lane")
            or run_result.get("cleanup_profile")
            or run_result.get("perception_mode")
            or "run"
        ),
        "backend": run_result.get("backend") or run_result.get("robot", {}).get("backend"),
        "seed": run_result.get("seed"),
    }


def _driver_name(run_result: dict[str, Any]) -> str:
    policy = str(run_result.get("policy") or "")
    if "codex" in policy.lower() or run_result.get("agent_driven"):
        return "Codex agent"
    return policy or "agent"


def _context_subtitle(run_result: dict[str, Any]) -> str:
    context = _run_context(run_result)
    parts = ["bounded MCP tools", str(context.get("profile") or "cleanup")]
    if context.get("seed") is not None:
        parts.append(f"seed {context['seed']}")
    return " | ".join(parts)


def _final_subtitle(run_result: dict[str, Any]) -> str:
    reason = str(run_result.get("terminate_reason") or "").strip()
    if reason:
        return reason
    status = run_result.get("completion_status") or run_result.get("cleanup_status") or "complete"
    return f"Cleanup status: {status}"


def _pretty_category(value: Any) -> str:
    if not value:
        return ""
    text = str(value).replace("_", " ")
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return " ".join(part.capitalize() for part in text.split())


def _fonts(width: int) -> dict[str, ImageFont.ImageFont]:
    scale = 1.0 if width >= 1200 else 0.85
    return {
        "title": _font("DejaVuSans-Bold.ttf", int(26 * scale)),
        "body": _font("DejaVuSans.ttf", int(17 * scale)),
        "small": _font("DejaVuSans.ttf", int(13 * scale)),
        "small_bold": _font("DejaVuSans-Bold.ttf", int(13 * scale)),
    }


def _font(name: str, size: int) -> ImageFont.ImageFont:
    candidates = [
        name,
        f"/usr/share/fonts/truetype/dejavu/{name}",
        f"/usr/share/fonts/truetype/liberation2/{name}",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text(text: str, font: ImageFont.ImageFont, *, max_width: int) -> str:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    output = text
    while output and _text_width(draw, output + ellipsis, font) > max_width:
        output = output[:-1]
    return output.rstrip() + ellipsis


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _write_gif(frames: list[Image.Image], durations: list[int], gif_path: Path) -> None:
    gif_path.parent.mkdir(parents=True, exist_ok=True)
    if not frames:
        raise ValueError("cannot write GIF with no frames")
    paletted = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=160) for frame in frames]
    paletted[0].save(
        gif_path,
        format="GIF",
        save_all=True,
        append_images=paletted[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )


def _write_contact_sheet(
    frames: list[Image.Image], specs: list[FrameSpec], output_path: Path
) -> None:
    if not frames:
        return
    cols = 3
    thumb_w, thumb_h = 360, 203
    label_h = 34
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "#ffffff")
    draw = ImageDraw.Draw(sheet)
    font = _font("DejaVuSans.ttf", 13)
    for index, (frame, spec) in enumerate(zip(frames, specs, strict=True)):
        col = index % cols
        row = index // cols
        x = col * thumb_w
        y = row * (thumb_h + label_h)
        thumb = ImageOps.contain(frame, (thumb_w, thumb_h))
        sheet.paste(thumb, (x, y))
        label = _fit_text(
            f"{index + 1:02d}. {spec.chapter}: {spec.active_tool}", font, max_width=thumb_w - 12
        )
        draw.text((x + 6, y + thumb_h + 9), label, fill=INK, font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "frame"


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def TOOLS_BY_ID() -> dict[str, str]:
    return {tool: label for tool, label in TOOLS}


if __name__ == "__main__":
    sys.exit(main())
