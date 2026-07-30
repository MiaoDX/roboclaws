#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from html import escape
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object

SUGGESTION_SCHEMA = "b1_map12_manual_anchor_semantic_suggestions_v1"
REVIEW_PACKET_SCHEMA = "b1_map12_manual_anchor_semantic_review_packet_v1"
DEFAULT_DRAFT = Path("docs/status/active/b1-map12-scene-correspondences-draft.json")
DEFAULT_SCENE_DIAGNOSTIC = Path(
    "output/b1-map12/scene-topdown-label-overlay/scene_topdown_diagnostic.json"
)
DEFAULT_OUTPUT = Path("output/b1-map12/manual-draft-anchor-semantic-suggestions.json")
DEFAULT_REVIEW_PACKET_OUTPUT = Path(
    "output/b1-map12/manual-draft-anchor-semantic-review-packet.json"
)
DEFAULT_REVIEW_REPORT_OUTPUT = Path("output/b1-map12/manual-draft-anchor-semantic-review.html")
STRONG_DISTANCE_M = 0.5
SEMANTIC_PROJECTION_SCHEMA = "b1_map12_semantic_projection_v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Suggest Map12 navigation area and B1 scene partition candidates for manual "
            "draft anchors. Writes review suggestions only; never accepts anchors."
        )
    )
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--room-projection", type=Path, required=True)
    parser.add_argument("--scene-diagnostic", type=Path, default=DEFAULT_SCENE_DIAGNOSTIC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--review-packet-output",
        type=Path,
        default=DEFAULT_REVIEW_PACKET_OUTPUT,
        help=(
            "Optional review aid that combines manual picks with semantic suggestions. "
            "Anchors remain proposed and require human acceptance."
        ),
    )
    parser.add_argument(
        "--review-report-output",
        type=Path,
        default=DEFAULT_REVIEW_REPORT_OUTPUT,
        help="Static HTML table for human review of the semantic review packet.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        draft = read_json_object(args.draft, label="manual draft")
        payload = build_semantic_suggestions(
            draft=draft,
            room_projection=read_json_object(args.room_projection, label="room projection"),
            scene_diagnostic=read_json_object(args.scene_diagnostic, label="scene diagnostic"),
            draft_path=args.draft,
            room_projection_path=args.room_projection,
            scene_diagnostic_path=args.scene_diagnostic,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    review_packet_output = args.review_packet_output
    review_report_output = args.review_report_output
    if review_packet_output is not None:
        review_packet = build_semantic_review_packet(
            draft=draft,
            suggestions=payload,
            draft_path=args.draft,
            suggestions_path=args.output,
        )
        review_packet_output.parent.mkdir(parents=True, exist_ok=True)
        review_packet_output.write_text(
            json.dumps(review_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if review_report_output is not None:
            review_report_output.parent.mkdir(parents=True, exist_ok=True)
            review_report_output.write_text(
                render_semantic_review_report(review_packet, packet_path=review_packet_output),
                encoding="utf-8",
            )
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "anchor_count": payload["anchor_count"],
                "strong_candidate_count": payload["strong_candidate_count"],
                "output": str(args.output),
                "review_packet_output": str(review_packet_output or ""),
                "review_report_output": str(review_report_output or ""),
            },
            sort_keys=True,
        )
    )
    return 0


def build_semantic_suggestions(
    *,
    draft: dict[str, Any],
    room_projection: dict[str, Any],
    scene_diagnostic: dict[str, Any],
    draft_path: Path | None = None,
    room_projection_path: Path | None = None,
    scene_diagnostic_path: Path | None = None,
) -> dict[str, Any]:
    labels = map_labels(room_projection)
    partitions = scene_partitions(scene_diagnostic)
    suggestions = []
    for anchor in explicit_anchor_picks(draft):
        map_xy = anchor["map_xy"]
        scene_xyz = anchor["scene_xyz"]
        map_candidates = nearest_map_candidates(float(map_xy[0]), float(map_xy[1]), labels)
        scene_candidates = nearest_scene_candidates(
            float(scene_xyz[0]),
            float(scene_xyz[1]),
            partitions,
        )
        strong = bool(
            map_candidates
            and scene_candidates
            and map_candidates[0]["distance_m"] <= STRONG_DISTANCE_M
            and scene_candidates[0]["distance_m"] <= STRONG_DISTANCE_M
        )
        suggestions.append(
            {
                "anchor_id": str(anchor.get("anchor_id") or ""),
                "review_status": "proposed_suggestion",
                "suggestion_status": "strong_candidate_needs_review"
                if strong
                else "nearest_only_needs_review",
                "map_xy": map_xy,
                "scene_xyz": scene_xyz,
                "recommended_navigation_area_id": map_candidates[0]["map_area_id"]
                if strong
                else "",
                "recommended_asset_partition_id": scene_candidates[0]["partition_id"]
                if strong
                else "",
                "map_candidates": map_candidates[:3],
                "scene_candidates": scene_candidates[:3],
            }
        )
    return {
        "schema": SUGGESTION_SCHEMA,
        "draft": str(draft_path or ""),
        "room_projection": str(room_projection_path or ""),
        "scene_diagnostic": str(scene_diagnostic_path or ""),
        "policy": {
            "status": "review_suggestions_only",
            "strong_distance_m": STRONG_DISTANCE_M,
            "accepted_manifest_mutated": False,
            "note": (
                "Nearest candidates are hints. They must be reviewed before accepted anchors "
                "use them."
            ),
        },
        "anchor_count": len(suggestions),
        "strong_candidate_count": sum(
            item["suggestion_status"] == "strong_candidate_needs_review" for item in suggestions
        ),
        "suggestions": suggestions,
    }


def build_semantic_review_packet(
    *,
    draft: dict[str, Any],
    suggestions: dict[str, Any],
    draft_path: Path | None = None,
    suggestions_path: Path | None = None,
) -> dict[str, Any]:
    suggestion_by_anchor = {
        str(item.get("anchor_id") or ""): item
        for item in suggestions.get("suggestions") or []
        if isinstance(item, dict)
    }
    anchors = []
    for anchor in explicit_anchor_picks(draft):
        anchor_id = str(anchor.get("anchor_id") or "")
        suggestion = suggestion_by_anchor.get(anchor_id, {})
        map_candidates = [
            item for item in suggestion.get("map_candidates") or [] if isinstance(item, dict)
        ]
        scene_candidates = [
            item for item in suggestion.get("scene_candidates") or [] if isinstance(item, dict)
        ]
        recommended_area = str(suggestion.get("recommended_navigation_area_id") or "")
        recommended_partition = str(suggestion.get("recommended_asset_partition_id") or "")
        candidate = dict(anchor)
        candidate["anchor_role"] = str(anchor.get("anchor_role") or "alignment")
        candidate["review_status"] = "proposed"
        candidate["navigation_area_id"] = recommended_area
        candidate["asset_partition_id"] = recommended_partition
        candidate["semantic_review"] = {
            "status": "needs_human_review",
            "suggestion_status": str(suggestion.get("suggestion_status") or "missing_suggestion"),
            "recommended_navigation_area_id": recommended_area,
            "recommended_asset_partition_id": recommended_partition,
            "map_candidates": map_candidates,
            "scene_candidates": scene_candidates,
            "acceptance_instructions": (
                "Use anchor_role=alignment for geometry-only picks. Use anchor_role=semantic "
                "only for room-interior label points with final navigation_area_id and "
                "asset_partition_id, then change review_status to accepted."
            ),
        }
        anchors.append(candidate)
    return {
        "schema": REVIEW_PACKET_SCHEMA,
        "source_map_frame": draft.get("source_map_frame"),
        "target_scene_frame": draft.get("target_scene_frame"),
        "bbox_seed_policy": draft.get("bbox_seed_policy"),
        "scene_projection_policy": draft.get("scene_projection_policy"),
        "source_draft": str(draft_path or suggestions.get("draft") or ""),
        "source_suggestions": str(suggestions_path or ""),
        "status": "needs_human_review",
        "accepted_manifest_mutated": False,
        "accepted_anchor_count": 0,
        "proposed_anchor_count": len(anchors),
        "strong_candidate_count": int(suggestions.get("strong_candidate_count") or 0),
        "policy": {
            "auto_accept": False,
            "review_required": True,
            "note": (
                "This packet is a review aid only. It must not be used as a verified "
                "correspondence manifest until anchors are explicitly accepted."
            ),
        },
        "anchors": anchors,
    }


def render_semantic_review_report(
    packet: dict[str, Any], *, packet_path: Path | None = None
) -> str:
    rows = "\n".join(render_anchor_row(anchor) for anchor in packet.get("anchors") or [])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>B1 Map12 Manual Anchor Semantic Review</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d7dde5; padding: 6px; vertical-align: top; }}
    th {{ background: #eef2f6; text-align: left; }}
    code {{ background: #f6f8fa; padding: 1px 3px; }}
    .notice {{ border-left: 4px solid #b36b00; background: #fff8e8; padding: 10px; }}
  </style>
</head>
<body>
  <h1>B1 Map12 Manual Anchor Semantic Review</h1>
  <p class="notice">Review aid only. It does not accept anchors or mutate the committed manifest.
  Final ids must be human reviewed before running the strict promoter.</p>
  <p>Packet: <code>{escape(str(packet_path or ""))}</code></p>
  <p>Status: <strong>{escape(str(packet.get("status") or ""))}</strong>.
  Proposed: <strong>{escape(str(packet.get("proposed_anchor_count") or 0))}</strong>.
  Accepted: <strong>{escape(str(packet.get("accepted_anchor_count") or 0))}</strong>.
  Strong candidates: <strong>{escape(str(packet.get("strong_candidate_count") or 0))}</strong>.</p>
  <table id="semantic-review-report">
    <thead>
      <tr>
        <th>Anchor</th>
        <th>Status</th>
        <th>Map XY</th>
        <th>Scene XYZ</th>
        <th>Recommended IDs</th>
        <th>Map Candidates</th>
        <th>Scene Candidates</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""


def render_anchor_row(anchor: dict[str, Any]) -> str:
    review = (
        anchor.get("semantic_review") if isinstance(anchor.get("semantic_review"), dict) else {}
    )
    review_status = escape(str(anchor.get("review_status") or ""))
    suggestion_status = escape(str(review.get("suggestion_status") or ""))
    return f"""<tr>
  <td><code>{escape(str(anchor.get("anchor_id") or ""))}</code></td>
  <td>{review_status}<br />{suggestion_status}</td>
  <td><code>{escape(json.dumps(anchor.get("map_xy") or []))}</code></td>
  <td><code>{escape(json.dumps(anchor.get("scene_xyz") or []))}</code></td>
  <td>navigation: <code>{escape(str(anchor.get("navigation_area_id") or ""))}</code><br />
      asset: <code>{escape(str(anchor.get("asset_partition_id") or ""))}</code></td>
  <td>{render_candidate_list(review.get("map_candidates") or [], "map_area_id")}</td>
  <td>{render_candidate_list(review.get("scene_candidates") or [], "partition_id")}</td>
</tr>"""


def render_candidate_list(candidates: list[Any], id_field: str) -> str:
    items = []
    for candidate in candidates[:3]:
        if not isinstance(candidate, dict):
            continue
        label = str(candidate.get(id_field) or candidate.get("label_id") or "")
        distance = candidate.get("distance_m")
        items.append(f"<li><code>{escape(label)}</code> {escape(str(distance))} m</li>")
    return "<ul>" + "".join(items) + "</ul>" if items else ""


def explicit_anchor_picks(draft: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = [
        anchor
        for anchor in draft.get("anchors") or []
        if isinstance(anchor, dict)
        and isinstance(anchor.get("map_xy"), list)
        and len(anchor["map_xy"]) == 2
        and isinstance(anchor.get("scene_xyz"), list)
        and len(anchor["scene_xyz"]) == 3
    ]
    if not anchors:
        raise ValueError("draft has no anchors with explicit map_xy and scene_xyz")
    return anchors


def map_labels(room_projection: dict[str, Any]) -> list[dict[str, Any]]:
    if room_projection.get("schema") != SEMANTIC_PROJECTION_SCHEMA:
        raise ValueError(f"unexpected room projection schema: {room_projection.get('schema')!r}")
    labels = []
    for room in room_projection.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        points = room.get("map_polygon")
        if not isinstance(points, list) or len(points) < 3:
            continue
        labels.append(
            {
                "label_id": str(room.get("room_id") or ""),
                "map_area_id": str(room.get("navigation_area_id") or ""),
                "scene_partition_id": str(room.get("asset_partition_id") or ""),
                "room_label": str(room.get("room_label") or room.get("room_id") or ""),
                "review_status": str(room.get("review_status") or ""),
                "geometry": {"points": points},
            }
        )
    if not labels:
        raise ValueError("room projection has no map_polygon labels")
    return labels


def scene_partitions(scene_diagnostic: dict[str, Any]) -> list[dict[str, Any]]:
    partitions = []
    for partition in scene_diagnostic.get("partitions") or []:
        if not isinstance(partition, dict):
            continue
        bounds = partition.get("scene_frame_bounds")
        if not isinstance(bounds, dict):
            continue
        partitions.append(
            {
                "partition_id": str(partition.get("partition_id") or ""),
                "bounds": bounds,
            }
        )
    if not partitions:
        raise ValueError("scene diagnostic has no partition bounds")
    return partitions


def nearest_map_candidates(
    x: float, y: float, labels: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for label in labels:
        points = label["geometry"]["points"]
        distance = polygon_distance(x, y, points)
        rows.append(
            {
                "label_id": str(label.get("label_id") or ""),
                "map_area_id": str(label.get("map_area_id") or ""),
                "scene_partition_id": str(label.get("scene_partition_id") or ""),
                "room_label": str(label.get("room_label") or ""),
                "review_status": str(label.get("review_status") or ""),
                "inside": distance == 0.0,
                "distance_m": round(distance, 6),
            }
        )
    return sorted(rows, key=lambda item: (item["distance_m"], item["label_id"]))


def nearest_scene_candidates(
    x: float, y: float, partitions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for partition in partitions:
        distance = bounds_distance(x, y, partition["bounds"])
        rows.append(
            {
                "partition_id": partition["partition_id"],
                "inside": distance == 0.0,
                "distance_m": round(distance, 6),
            }
        )
    return sorted(rows, key=lambda item: (item["distance_m"], item["partition_id"]))


def polygon_distance(x: float, y: float, points: list[dict[str, Any]]) -> float:
    if point_in_polygon(x, y, points):
        return 0.0
    distances = []
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        distances.append(
            segment_distance(
                x,
                y,
                float(point["x"]),
                float(point["y"]),
                float(next_point["x"]),
                float(next_point["y"]),
            )
        )
    return min(distances)


def point_in_polygon(x: float, y: float, points: list[dict[str, Any]]) -> bool:
    inside = False
    previous = points[-1]
    for point in points:
        xi = float(point["x"])
        yi = float(point["y"])
        xj = float(previous["x"])
        yj = float(previous["y"])
        crosses_y = (yi > y) != (yj > y)
        if crosses_y and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        previous = point
    return inside


def segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    segment_len_sq = vx * vx + vy * vy
    if segment_len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / segment_len_sq))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def bounds_distance(x: float, y: float, bounds: dict[str, Any]) -> float:
    dx = max(float(bounds["min_x"]) - x, 0.0, x - float(bounds["max_x"]))
    dy = max(float(bounds["min_y"]) - y, 0.0, y - float(bounds["max_y"]))
    return math.hypot(dx, dy)


if __name__ == "__main__":
    raise SystemExit(main())
