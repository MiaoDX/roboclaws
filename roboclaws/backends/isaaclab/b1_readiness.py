#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from roboclaws.backends.isaaclab.b1_readiness_artifacts import (
    build_readiness_artifact,
    readiness_artifact_with_alignment,
    readiness_artifact_with_navigation,
)
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    READINESS_SCHEMA,
    validate_navigation_smoke_artifact,
    validate_readiness_artifact,
)
from roboclaws.core.json_sources import read_json_object


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the static B1 / robot_map_12 Digital Twin readiness artifact. "
            "Run this with .venv-isaaclab/bin/python so pxr.Usd is available."
        )
    )
    parser.add_argument("--b1-root", type=Path, required=True)
    parser.add_argument("--map12-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--navigation-artifact",
        type=Path,
        help=(
            "Optional B1 navigation-smoke artifact. When it passes contract validation, "
            "the output readiness artifact may claim robot_navigation_supported=true."
        ),
    )
    parser.add_argument(
        "--alignment-artifact",
        type=Path,
        help=(
            "Optional B1 / Map 12 reviewed-correspondence residual artifact. "
            "Only passing residual evidence can promote map-scene alignment status."
        ),
    )
    parser.add_argument("--require-navigation-success", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = build_readiness_artifact(args.b1_root, args.map12_root)
        if args.alignment_artifact is not None:
            alignment_payload = read_json_object(
                args.alignment_artifact,
                label="alignment artifact",
            )
            payload = readiness_artifact_with_alignment(
                payload,
                alignment_payload,
                alignment_artifact_path=args.alignment_artifact,
            )
        navigation_payload: dict[str, Any] | None = None
        if args.navigation_artifact is not None:
            navigation_payload = read_json_object(
                args.navigation_artifact,
                label="navigation artifact",
            )
            payload = readiness_artifact_with_navigation(
                payload,
                navigation_payload,
                navigation_artifact_path=args.navigation_artifact,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = validate_readiness_artifact(
        payload,
        require_navigation_success=bool(args.require_navigation_success),
    )
    if args.require_navigation_success and navigation_payload is not None:
        errors.extend(
            f"navigation artifact: {error}"
            for error in validate_navigation_smoke_artifact(
                navigation_payload,
                require_files=True,
            )
        )
    payload["validation"] = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": READINESS_SCHEMA,
                "status": payload["validation"]["status"],
                "output": str(args.output),
                "robot_navigation_supported": payload.get("robot_navigation_supported"),
                "map12_overlay_status": payload.get("map12_overlay_status"),
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
