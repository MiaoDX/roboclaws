#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.b1_alignment_artifact import build_alignment_residuals
from roboclaws.maps.b1_alignment_contract import (
    B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
    validate_alignment_residual_artifact,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit B1 / Map 12 map-scene alignment from reviewed correspondences."
    )
    parser.add_argument("--correspondences", type=Path, required=True)
    parser.add_argument("--map-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = read_json_object(args.correspondences, label="correspondence manifest")
        payload = build_alignment_residuals(
            manifest,
            map_bundle=args.map_bundle,
            output_dir=args.output_dir,
            correspondences_path=args.correspondences,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = validate_alignment_residual_artifact(payload)
    payload["validation"] = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "alignment_residuals.json"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": B1_MAP12_ALIGNMENT_RESIDUALS_SCHEMA,
                "status": payload.get("status"),
                "global_alignment_status": payload.get("global_alignment_status"),
                "selected_transform_type": payload.get("selected_transform_type"),
                "accepted_anchor_count": payload.get("accepted_anchor_count"),
                "output": str(output_path),
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
