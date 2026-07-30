#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object

DEFAULT_DRAFT = Path("docs/status/active/b1-map12-scene-correspondences-draft.json")
DEFAULT_OUTPUT = Path(
    "output/b1-map12/manual-draft-alignment/b1-map12-scene-correspondences.verification-only.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an explicit verification-only accepted manifest from the manual B1/Map12 "
            "draft anchors. This is not the final accepted correspondence asset."
        )
    )
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_verification_manifest(
            read_draft_packet(args.draft),
            source_draft=args.draft,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": payload.get("schema"),
                "verification_only": payload["verification_only"],
                "accepted_anchor_count": len(payload["anchors"]),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def build_verification_manifest(
    draft: dict[str, Any], *, source_draft: Path = DEFAULT_DRAFT
) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise ValueError("manual draft must contain a JSON object")
    anchors = [
        dict(anchor)
        for anchor in draft.get("anchors") or []
        if isinstance(anchor, dict) and has_explicit_picks(anchor)
    ]
    if not anchors:
        raise ValueError("manual draft has no anchors with explicit map_xy and scene_xyz picks")
    promoted = []
    for index, anchor in enumerate(anchors, start=1):
        item = dict(anchor)
        item["review_status"] = "accepted"
        item["anchor_role"] = "alignment"
        item["confidence"] = item.get("confidence") or 0.8
        evidence = dict(item.get("evidence") or {})
        evidence["verification_note"] = (
            "Verification-only promotion from proposed manual draft anchors. "
            "These anchors verify map-scene geometry only, not room semantics."
        )
        item["evidence"] = evidence
        promoted.append(item)
    return {
        "schema": draft.get("schema"),
        "source_map_frame": draft.get("source_map_frame"),
        "target_scene_frame": draft.get("target_scene_frame"),
        "bbox_seed_policy": draft.get("bbox_seed_policy"),
        "scene_projection_policy": draft.get("scene_projection_policy"),
        "verification_only": True,
        "source_draft": source_draft.as_posix(),
        "notes": [
            "Generated for local residual verification from proposed manual draft anchors.",
            "Do not commit this as assets/maps/b1-map12-scene-correspondences.json.",
            "Do not use alignment anchors as room semantic evidence.",
        ],
        "anchors": promoted,
    }


def has_explicit_picks(anchor: dict[str, Any]) -> bool:
    return (
        isinstance(anchor.get("map_xy"), list)
        and len(anchor["map_xy"]) == 2
        and isinstance(anchor.get("scene_xyz"), list)
        and len(anchor["scene_xyz"]) == 3
    )


def read_draft_packet(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label="manual draft")
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
