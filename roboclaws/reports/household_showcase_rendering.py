from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from roboclaws.reports.household_showcase_plan import TOOLS, FrameSpec

BACKGROUND = "#f5f7fb"
INK = "#111827"
MUTED = "#5b6472"
BORDER = "#cfd7e3"
PANEL = "#ffffff"
ACCENT = "#2563eb"


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
    margin, header_h, footer_h, gap = 24, 84, 112, 20
    content_y = header_h + 12
    content_h = height - content_y - footer_h - margin
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


def write_gif(frames: list[Image.Image], durations: list[int], gif_path: Path) -> None:
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


def write_contact_sheet(
    frames: list[Image.Image], specs: list[FrameSpec], output_path: Path
) -> None:
    if not frames:
        return
    cols, thumb_w, thumb_h, label_h = 3, 360, 203, 34
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "#ffffff")
    draw = ImageDraw.Draw(sheet)
    font = _font("DejaVuSans.ttf", 13)
    for index, (frame, spec) in enumerate(zip(frames, specs, strict=True)):
        x = (index % cols) * thumb_w
        y = (index // cols) * (thumb_h + label_h)
        sheet.paste(ImageOps.contain(frame, (thumb_w, thumb_h)), (x, y))
        label = _fit_text(
            f"{index + 1:02d}. {spec.chapter}: {spec.active_tool}", font, max_width=thumb_w - 12
        )
        draw.text((x + 6, y + thumb_h + 9), label, fill=INK, font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _open_view_image(
    run_dir: Path, step: dict[str, Any], view: str, *, prefer_bbox: bool
) -> Image.Image:
    views = step.get("views", {})
    rel = views.get(view) or (views.get("verify") if view == "map" else None)
    if not rel:
        return _placeholder(f"missing {view}")
    path = run_dir / str(rel)
    if view == "fpv" and prefer_bbox:
        bbox_path = path.with_name(path.name.replace(".fpv.png", ".fpv.bbox.png"))
        if bbox_path.exists():
            path = bbox_path
    return Image.open(path).convert("RGB") if path.exists() else _placeholder(f"missing {view}")


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
    draw.text(
        (24, 54),
        _fit_text(spec.subtitle, fonts["body"], max_width=width - 260),
        fill=MUTED,
        font=fonts["body"],
    )
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
    draw.text(
        (24, footer_y + 58),
        _fit_text(spec.subtitle, fonts["body"], max_width=width - 48),
        fill=INK,
        font=fonts["body"],
    )
    draw.text((24, footer_y + 86), _eval_text(eval_summary), fill=MUTED, font=fonts["small"])


def _draw_tool_bar(
    draw: ImageDraw.ImageDraw,
    active_tool: str,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    x: int,
    y: int,
    width: int,
) -> None:
    gap, pill_h = 8, 28
    raw_widths = [_text_width(draw, label, fonts["small"]) + 24 for _, label in TOOLS]
    scale = min(1.0, width / max(sum(raw_widths) + gap * (len(TOOLS) - 1), 1))
    cursor = x
    for (tool, label), raw_w in zip(TOOLS, raw_widths, strict=True):
        pill_w = max(54, int(raw_w * scale))
        active = tool == active_tool or (active_tool == "place_inside" and tool == "place")
        draw.rounded_rectangle(
            (cursor, y, cursor + pill_w, y + pill_h),
            radius=14,
            fill=ACCENT if active else "#eef2f7",
            outline="#1d4ed8" if active else BORDER,
        )
        text = _fit_text(label, fonts["small"], max_width=pill_w - 16)
        draw.text(
            (cursor + (pill_w - _text_width(draw, text, fonts["small"])) // 2, y + 7),
            text,
            fill="#ffffff" if active else INK,
            font=fonts["small"],
        )
        cursor += pill_w + gap


def _eval_text(summary: dict[str, Any]) -> str:
    semantic = _ratio(summary.get("semantic_accepted"), summary.get("semantic_total"))
    exact = _ratio(summary.get("exact_restored"), summary.get("exact_total"))
    disturbance = summary.get("disturbance_count")
    disturbance_text = disturbance if disturbance is not None else "?"
    return (
        f"Post-run eval: {semantic} semantic accepted | "
        f"{exact} exact hidden-target match | {disturbance_text} disturbances"
    )


def _ratio(value: Any, total: Any) -> str:
    return "?/?" if value is None or total is None else f"{value}/{total}"


def _fonts(width: int) -> dict[str, ImageFont.ImageFont]:
    scale = 1.0 if width >= 1200 else 0.85
    return {
        "title": _font("DejaVuSans-Bold.ttf", int(26 * scale)),
        "body": _font("DejaVuSans.ttf", int(17 * scale)),
        "small": _font("DejaVuSans.ttf", int(13 * scale)),
        "small_bold": _font("DejaVuSans-Bold.ttf", int(13 * scale)),
    }


def _font(name: str, size: int) -> ImageFont.ImageFont:
    for candidate in [
        name,
        f"/usr/share/fonts/truetype/dejavu/{name}",
        f"/usr/share/fonts/truetype/liberation2/{name}",
    ]:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text(text: str, font: ImageFont.ImageFont, *, max_width: int) -> str:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if _text_width(draw, text, font) <= max_width:
        return text
    output = text
    while output and _text_width(draw, output + "...", font) > max_width:
        output = output[:-1]
    return output.rstrip() + "..."


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left
