#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.maps.b1_alignment import (  # noqa: E402
    build_alignment_residuals,
    validate_alignment_residual_artifact,
)
from roboclaws.maps.b1_semantic_review_promotion import (  # noqa: E402
    DEFAULT_PACKET,
    PromotionError,
    build_reviewed_correspondence_manifest,
    read_review_packet,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a human-edited B1/Map12 semantic review packet and run the "
            "alignment fitter on the promoted manifest without writing the committed asset."
        )
    )
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--map-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = build_reviewed_correspondence_manifest(
            read_review_packet(args.review_packet),
            source_packet=args.review_packet,
        )
    except PromotionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    promoted_path = args.output_dir / "promoted_correspondences.preview.json"
    promoted_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    residuals = build_alignment_residuals(
        manifest,
        map_bundle=args.map_bundle,
        output_dir=args.output_dir,
        correspondences_path=promoted_path,
    )
    errors = validate_alignment_residual_artifact(residuals)
    residuals["validation"] = {"status": "passed" if not errors else "failed", "errors": errors}
    residuals_path = args.output_dir / "alignment_residuals.json"
    residuals_path.write_text(
        json.dumps(residuals, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "schema": residuals["schema"],
                "status": residuals.get("status"),
                "global_alignment_status": residuals.get("global_alignment_status"),
                "accepted_anchor_count": residuals.get("accepted_anchor_count"),
                "promoted_correspondences": str(promoted_path),
                "alignment_residuals": str(residuals_path),
                "errors": errors,
                "committed_manifest_written": False,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
