from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.reports.household_showcase_plan import (
    DEFAULT_DURATION_MS,
    DEFAULT_HOLD_MS,
    build_frame_plan,
    evaluation_summary,
    load_steps,
    run_context,
)
from roboclaws.reports.household_showcase_rendering import (
    render_frame,
    write_contact_sheet,
)
from roboclaws.reports.household_showcase_rendering import (
    write_gif as write_gif_file,
)

SCHEMA = "roboclaws_visual_showcase_v1"
DEFAULT_SIZE = (1280, 720)


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
    run_result_path = run_dir / "run_result.json"
    if not run_result_path.exists():
        raise FileNotFoundError(f"missing required artifact: {run_result_path}")
    try:
        run_result = json.loads(run_result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{run_result_path.name} source must contain valid JSON object: {run_result_path}"
        ) from exc
    if not isinstance(run_result, dict):
        raise ValueError(
            f"{run_result_path.name} source must contain a JSON object: {run_result_path}"
        )
    steps = load_steps(run_result)
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
    eval_summary = evaluation_summary(run_result)
    context = run_context(run_result)
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
        frame_path = frames_dir / f"{index:03d}_{_slug(spec.chapter)}_{_slug(spec.active_tool)}.png"
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
    write_contact_sheet(rendered, frame_specs, contact_sheet_path)
    gif_path = out_dir / f"{basename}.gif"
    if write_gif:
        write_gif_file(rendered, [spec.duration_ms for spec in frame_specs], gif_path)
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


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-") or "frame"


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
