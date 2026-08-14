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

from roboclaws.core.json_sources import read_json_object  # noqa: E402
from roboclaws.maps.b1_alignment import (  # noqa: E402
    ALIGNMENT_ANCHOR_ROLE,
    B1_MAP12_CORRESPONDENCES_SCHEMA,
    MIN_GLOBAL_ACCEPTED_ANCHORS,
    SEMANTIC_ANCHOR_ROLE,
    anchor_role,
    anchor_uses_known_poor_seed,
    valid_xy,
    valid_xyz,
    validate_correspondence_manifest,
)
from roboclaws.maps.b1_semantic_anchor_suggestions import (  # noqa: E402
    REVIEW_PACKET_SCHEMA,
)

DEFAULT_PACKET = Path("output/b1-map12/manual-draft-anchor-semantic-review-packet.json")
DEFAULT_OUTPUT = Path("assets/maps/b1-map12-scene-correspondences.json")
PROMOTED_ANCHOR_FIELDS = (
    "anchor_id",
    "anchor_type",
    "anchor_role",
    "navigation_area_id",
    "asset_partition_id",
    "map_xy",
    "scene_xyz",
    "evidence",
    "confidence",
    "review_status",
    "map_coordinate_source",
    "scene_coordinate_source",
    "coordinate_source",
    "map_polygon",
)


class PromotionError(ValueError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Promote a human-edited B1/Map12 semantic review packet into the "
            "correspondence manifest. Proposed rows, synthetic ids, and bbox seed "
            "coordinates are rejected."
        )
    )
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the human-edited packet without writing the committed manifest.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_reviewed_correspondence_manifest(
            read_review_packet(args.review_packet),
            source_packet=args.review_packet,
        )
    except PromotionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.check:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "accepted_anchor_count": len(payload["anchors"]),
                "source_review_packet": payload["source_review_packet"],
                "output": "" if args.check else str(args.output),
                "output_written": not args.check,
            },
            sort_keys=True,
        )
    )
    return 0


def build_reviewed_correspondence_manifest(
    packet: dict[str, Any],
    *,
    source_packet: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise PromotionError("review packet must contain a JSON object")
    if packet.get("schema") != REVIEW_PACKET_SCHEMA:
        raise PromotionError(
            "review packet schema must be b1_map12_manual_anchor_semantic_review_packet_v1"
        )
    validate_review_packet_metadata(packet)
    accepted = []
    for index, raw_anchor in enumerate(packet.get("anchors") or [], start=1):
        if not isinstance(raw_anchor, dict) or raw_anchor.get("review_status") != "accepted":
            continue
        anchor = dict(raw_anchor)
        anchor_id = str(anchor.get("anchor_id") or f"anchor {index}")
        validate_accepted_anchor(anchor_id, anchor)
        accepted.append(promoted_anchor(anchor))
    if not accepted:
        raise PromotionError("review packet has no human-accepted anchors")
    if len(accepted) < MIN_GLOBAL_ACCEPTED_ANCHORS:
        raise PromotionError(
            f"review packet needs at least {MIN_GLOBAL_ACCEPTED_ANCHORS} human-accepted anchors"
        )
    manifest = {
        "schema": B1_MAP12_CORRESPONDENCES_SCHEMA,
        "source_map_frame": packet.get("source_map_frame"),
        "target_scene_frame": packet.get("target_scene_frame"),
        "bbox_seed_policy": packet.get("bbox_seed_policy"),
        "scene_projection_policy": packet.get("scene_projection_policy"),
        "source_review_packet": str(source_packet or packet.get("source_draft") or ""),
        "promotion_policy": {
            "source_schema": REVIEW_PACKET_SCHEMA,
            "requires_review_status": "accepted",
            "rejects_synthetic_manual_draft_ids": True,
            "rejects_known_poor_bbox_seed": True,
            "auto_accept": False,
        },
        "anchors": accepted,
    }
    errors = validate_correspondence_manifest(manifest)
    if errors:
        raise PromotionError("; ".join(errors))
    return manifest


def validate_review_packet_metadata(packet: dict[str, Any]) -> None:
    anchors = [item for item in packet.get("anchors") or [] if isinstance(item, dict)]
    actual_accepted = sum(item.get("review_status") == "accepted" for item in anchors)
    actual_proposed = sum(item.get("review_status") == "proposed" for item in anchors)
    if (
        "accepted_anchor_count" in packet
        and int(packet.get("accepted_anchor_count") or 0) != actual_accepted
    ):
        raise PromotionError("review packet accepted_anchor_count does not match accepted anchors")
    if (
        "proposed_anchor_count" in packet
        and int(packet.get("proposed_anchor_count") or 0) != actual_proposed
    ):
        raise PromotionError("review packet proposed_anchor_count does not match proposed anchors")
    if packet.get("accepted_manifest_mutated") is not False:
        raise PromotionError(
            "review packet must declare accepted_manifest_mutated=false before promotion"
        )
    policy = packet.get("policy") if isinstance(packet.get("policy"), dict) else {}
    if policy.get("auto_accept") is not False:
        raise PromotionError("review packet policy must declare auto_accept=false")
    if policy.get("review_required") is not True:
        raise PromotionError("review packet policy must declare review_required=true")


def validate_accepted_anchor(anchor_id: str, anchor: dict[str, Any]) -> None:
    if not valid_xy(anchor.get("map_xy")):
        raise PromotionError(f"accepted anchor {anchor_id} needs explicit map_xy")
    if not valid_xyz(anchor.get("scene_xyz")):
        raise PromotionError(f"accepted anchor {anchor_id} needs explicit scene_xyz")
    role = anchor_role(anchor)
    if not anchor.get("anchor_role"):
        raise PromotionError(f"accepted anchor {anchor_id} needs anchor_role")
    if role not in {ALIGNMENT_ANCHOR_ROLE, SEMANTIC_ANCHOR_ROLE}:
        raise PromotionError(f"accepted anchor {anchor_id} has invalid anchor_role: {role}")
    if role == SEMANTIC_ANCHOR_ROLE:
        for field in ("navigation_area_id", "asset_partition_id"):
            value = str(anchor.get(field) or "")
            if not value:
                raise PromotionError(f"accepted semantic anchor {anchor_id} needs {field}")
            if value.startswith("manual_draft_"):
                raise PromotionError(
                    f"accepted semantic anchor {anchor_id} uses synthetic {field}: {value}"
                )
    if anchor_uses_known_poor_seed(anchor):
        raise PromotionError(f"accepted anchor {anchor_id} must not use bbox seed coordinates")


def promoted_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    promoted = {field: anchor[field] for field in PROMOTED_ANCHOR_FIELDS if field in anchor}
    promoted["anchor_role"] = anchor_role(anchor)
    return promoted


def read_review_packet(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label="review packet")
    except (FileNotFoundError, ValueError) as exc:
        raise PromotionError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
