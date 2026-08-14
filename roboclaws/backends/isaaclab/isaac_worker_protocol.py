"""Isaac Lab backend runtime support."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.isaac_lab_backend import ISAACLAB_SUBPROCESS_BACKEND
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE


def safe_file_stem(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned or "view"


def write_placeholder_image(
    path: Path,
    *,
    title: str,
    subtitle: str,
    state: dict[str, Any],
    width: int,
    height: int,
    focus_object_id: str | None = None,
    focus_receptacle_id: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), (28, 32, 38))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 58), fill=(55, 68, 82))
    draw.text((16, 14), title[:80], fill=(245, 248, 250))
    draw.text((16, 36), subtitle[:80], fill=(178, 203, 219))
    receptacles = list((state.get("receptacle_index") or {}).keys())
    objects = state.get("scenario", {}).get("objects") or []
    _draw_receptacle_tiles(
        draw,
        receptacles=receptacles,
        width=width,
        focus_receptacle_id=focus_receptacle_id,
    )
    _draw_object_markers(
        draw,
        objects=objects,
        state=state,
        width=width,
        height=height,
        focus_object_id=focus_object_id,
    )
    image.save(path)


def _draw_receptacle_tiles(
    draw: ImageDraw.ImageDraw,
    *,
    receptacles: list[str],
    width: int,
    focus_receptacle_id: str | None,
) -> None:
    if not receptacles:
        return
    cell_w = max(48, (width - 32) // min(len(receptacles), 5))
    for index, receptacle_id in enumerate(receptacles[:10]):
        row = index // 5
        col = index % 5
        x0 = 16 + col * cell_w
        y0 = 82 + row * 88
        fill = (78, 116, 94) if receptacle_id == focus_receptacle_id else (70, 80, 92)
        draw.rectangle((x0, y0, x0 + cell_w - 8, y0 + 68), outline=(140, 159, 176), fill=fill)
        draw.text((x0 + 6, y0 + 6), receptacle_id[:18], fill=(240, 240, 240))


def _draw_object_markers(
    draw: ImageDraw.ImageDraw,
    *,
    objects: list[dict[str, Any]],
    state: dict[str, Any],
    width: int,
    height: int,
    focus_object_id: str | None,
) -> None:
    for index, obj in enumerate(objects[:12]):
        object_id = str(obj.get("object_id", ""))
        location = str(state.get("locations", {}).get(object_id, obj.get("location_id", "")))
        x = 24 + (index % 6) * max(56, (width - 48) // 6)
        y = height - 100 + (index // 6) * 34
        fill = (210, 155, 65) if object_id == focus_object_id else (169, 191, 112)
        draw.ellipse((x, y, x + 18, y + 18), fill=fill, outline=(245, 245, 245))
        draw.text((x + 24, y + 1), f"{object_id[:14]}->{location[:14]}", fill=(230, 230, 230))


def ok_response(tool: str, **payload: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "status": "ok",
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "physical_robot": False,
        "planner_backed": False,
        **payload,
    }


def error_response(tool: str, error: str, **payload: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool,
        "status": "error",
        "error": error,
        "backend": ISAACLAB_SUBPROCESS_BACKEND,
        "primitive_provenance": ISAAC_SEMANTIC_POSE_PROVENANCE,
        "physical_robot": False,
        "planner_backed": False,
        **payload,
    }


def read_state(path: Path) -> dict[str, Any]:
    state = read_json_object(path, label="Isaac worker state")
    state["_state_path"] = str(path)
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: value for key, value in state.items() if not key.startswith("_")}
    path.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_state_from_state_arg(state: dict[str, Any]) -> None:
    write_state(Path(state["_state_path"]), state)


def count_tool_request(state: dict[str, Any], tool: str) -> None:
    counts = Counter(state.get("tool_event_counts") or {})
    counts[f"{tool}:request"] += 1
    state["tool_event_counts"] = dict(counts)


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(state["scenario"]))
    by_id = {obj["object_id"]: obj for obj in payload["objects"]}
    for object_id, location_id in state["locations"].items():
        by_id[object_id]["location_id"] = location_id
        containment = (state.get("containment") or {}).get(object_id)
        if containment:
            by_id[object_id].update(containment)
    return payload
