from __future__ import annotations

import re
from pathlib import Path
from typing import Any

COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG = 25.0


def _rendering_parity_preset(name: str) -> dict[str, str | float | None]:
    if name == "combined-material-light":
        return {
            "material_texture_scale_mode": "none",
            "distant_light_rotate_x": COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG,
        }
    if name == "source-preserving":
        return {
            "material_texture_scale_mode": "none",
            "distant_light_rotate_x": None,
        }
    raise ValueError(f"unsupported rendering parity preset: {name}")


def _apply_material_texture_scale_candidate(
    *,
    output_usd_path: Path,
    mode: str,
) -> dict[str, Any]:
    if mode == "none":
        return {
            "mode": mode,
            "texture_scale_rewrite_count": 0,
            "default_candidate": False,
        }
    text = output_usd_path.read_text(encoding="utf-8", errors="ignore")
    updated, rewrite_count = _rewrite_texture_scale_inputs(text, mode=mode)
    if rewrite_count:
        output_usd_path.write_text(updated, encoding="utf-8")
    return {
        "mode": mode,
        "texture_scale_rewrite_count": rewrite_count,
        "default_candidate": True,
    }


def _apply_distant_light_orientation_candidate(
    *,
    output_usd_path: Path,
    rotate_x: float | None,
) -> dict[str, Any]:
    if rotate_x is None:
        return {
            "rotate_x": None,
            "rewrite_count": 0,
            "insert_count": 0,
            "default_candidate": False,
        }
    text = output_usd_path.read_text(encoding="utf-8", errors="ignore")
    updated, rewrite_count, insert_count = _rewrite_distant_light_rotate_x(
        text,
        rotate_x=rotate_x,
    )
    if rewrite_count or insert_count:
        output_usd_path.write_text(updated, encoding="utf-8")
    return {
        "rotate_x": rotate_x,
        "rewrite_count": rewrite_count,
        "insert_count": insert_count,
        "default_candidate": True,
    }


def _default_rendering_path_status(
    *,
    rendering_parity_preset: str,
    material_conversion_summary: dict[str, Any],
    light_conversion_summary: dict[str, Any],
) -> str:
    if rendering_parity_preset == "source-preserving":
        return "source_preserving_rendering_path"
    material_ready = (
        material_conversion_summary.get("mode") == "none"
        and int(material_conversion_summary.get("texture_scale_rewrite_count") or 0) == 0
    )
    light_ready = light_conversion_summary.get("rotate_x") == COMBINED_MATERIAL_LIGHT_ROTATE_X_DEG
    if material_ready and light_ready:
        return "default_rendering_path_uses_combined_material_light"
    return "default_rendering_path_candidate_incomplete"


def _rewrite_texture_scale_inputs(text: str, *, mode: str) -> tuple[str, int]:
    def replacement(match: re.Match[str]) -> str:
        values = _parse_float_values(match.group(2))
        if not values:
            return match.group(0)
        if mode == "identity":
            rewritten = [1.0 for _ in values]
        elif mode == "square":
            rewritten = [value * value for value in values]
            if len(rewritten) >= 4:
                rewritten[3] = values[3]
        else:
            raise ValueError(f"unsupported material texture scale mode: {mode}")
        return f"{match.group(1)}({_format_float_list(rewritten)})"

    return re.subn(
        r"(float[234]? inputs:(?:scale|fallback) = )\(([^)]+)\)",
        replacement,
        text,
    )


def _rewrite_distant_light_rotate_x(text: str, *, rotate_x: float) -> tuple[str, int, int]:
    parts: list[str] = []
    cursor = 0
    rewrites = 0
    inserts = 0
    for match in re.finditer(r'(?m)^(\s*)def DistantLight "[^"]+"\s*\{\s*$', text):
        block_start = match.start()
        block_end = _balanced_block_end(text, match.end() - 1)
        if block_end is None:
            continue
        block = text[block_start:block_end]
        rewritten, count = re.subn(
            r"float xformOp:rotateX = [^\s]+",
            f"float xformOp:rotateX = {_format_float(rotate_x)}",
            block,
        )
        rewrites += count
        if count == 0:
            rewritten = _insert_distant_light_rotate_x(rewritten, rotate_x=rotate_x)
            inserts += int(rewritten != block)
        parts.append(text[cursor:block_start])
        parts.append(rewritten)
        cursor = block_end
    if not parts:
        return text, 0, 0
    parts.append(text[cursor:])
    return "".join(parts), rewrites, inserts


def _insert_distant_light_rotate_x(block: str, *, rotate_x: float) -> str:
    close_index = block.rfind("}")
    if close_index < 0:
        return block
    match = re.search(r'(?m)^(\s*)def DistantLight "', block)
    indent = match.group(1) + "    " if match else "    "
    insertion = (
        f"{indent}float xformOp:rotateX = {_format_float(rotate_x)}\n"
        f'{indent}uniform token[] xformOpOrder = ["xformOp:rotateX"]\n'
    )
    return block[:close_index] + insertion + block[close_index:]


def _balanced_block_end(text: str, open_brace_index: int) -> int | None:
    depth = 0
    for index in range(open_brace_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                if index + 1 < len(text) and text[index + 1] == "\n":
                    return index + 2
                return index + 1
    return None


def _parse_float_values(raw: str) -> list[float]:
    values: list[float] = []
    for part in raw.split(","):
        try:
            values.append(float(part.strip()))
        except ValueError:
            return []
    return values


def _format_float_list(values: list[float]) -> str:
    return ", ".join(_format_float(value) for value in values)


def _format_float(value: float) -> str:
    formatted = f"{value:.6g}"
    return "0" if formatted == "-0" else formatted
