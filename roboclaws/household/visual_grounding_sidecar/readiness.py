#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from roboclaws.household.visual_grounding import (
    DEFAULT_VISUAL_GROUNDING_BASE_URL,
    DEFAULT_VISUAL_GROUNDING_TIMEOUT_S,
    HttpVisualGroundingClient,
    VisualGroundingClientConfig,
    visual_grounding_request,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-fast readiness check for product visual-grounding sidecars."
    )
    parser.add_argument("--pipeline", required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VISUAL_GROUNDING_BASE_URL", DEFAULT_VISUAL_GROUNDING_BASE_URL),
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=float(
            os.environ.get("VISUAL_GROUNDING_TIMEOUT_S", DEFAULT_VISUAL_GROUNDING_TIMEOUT_S)
        ),
    )
    parser.add_argument(
        "--require-real-adapter",
        action="store_true",
        help="Reject contract stubs, unavailable adapters, and connection-only responses.",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = check_visual_grounding_readiness(
        pipeline_id=args.pipeline,
        base_url=args.base_url,
        timeout_s=args.timeout_s,
        require_real_adapter=args.require_real_adapter,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if result["ok"]:
        print(
            "visual grounding readiness ok: "
            f"pipeline={result['pipeline_id']} base_url={result['base_url']}"
        )
        return 0
    print(
        "error: visual grounding sidecar is not ready for product runs: "
        f"{result['reason']}. {result['message']}",
        file=sys.stderr,
    )
    if args.output:
        print(f"readiness artifact: {args.output}", file=sys.stderr)
    return 1


def check_visual_grounding_readiness(
    *,
    pipeline_id: str,
    base_url: str,
    timeout_s: float,
    require_real_adapter: bool,
) -> dict[str, Any]:
    client = HttpVisualGroundingClient(
        VisualGroundingClientConfig(
            pipeline_id=pipeline_id,
            base_url=base_url,
            timeout_s=timeout_s,
            api_key=os.environ.get("VISUAL_GROUNDING_API_KEY", ""),
            proposer_id=os.environ.get("VISUAL_GROUNDING_PROPOSER_ID", ""),
            proposer_model_id=os.environ.get("VISUAL_GROUNDING_PROPOSER_MODEL_ID", ""),
        )
    )
    response = client.request_candidates(_readiness_request(pipeline_id))
    pipeline = response.get("pipeline") or {}
    stages = list(pipeline.get("stages") or [])
    result = {
        "schema": "visual_grounding_readiness_v1",
        "ok": True,
        "pipeline_id": pipeline_id,
        "base_url": base_url,
        "require_real_adapter": require_real_adapter,
        "response_status": response.get("status"),
        "stage_statuses": [
            {
                "stage": str(stage.get("stage") or ""),
                "producer_id": str(stage.get("producer_id") or ""),
                "status": str(stage.get("status") or ""),
                "model_id": str(stage.get("model_id") or ""),
            }
            for stage in stages
            if isinstance(stage, dict)
        ],
        "candidate_count": len(response.get("candidates") or []),
        "reason": "",
        "message": "",
        "private_truth_included": False,
    }
    if response.get("status") != "ok":
        error = response.get("error") or {}
        return _blocked(
            result,
            reason=str(error.get("reason") or response.get("status") or "not_ok"),
            message=str(error.get("message") or "visual grounding sidecar did not return ok"),
        )
    if require_real_adapter:
        blocked = _real_adapter_blocker(stages)
        if blocked:
            return _blocked(result, reason=blocked[0], message=blocked[1])
    return result


def _real_adapter_blocker(stages: list[Any]) -> tuple[str, str] | None:
    if not stages:
        return "missing_stage_provenance", "real sidecar response did not include stage provenance"
    blocked_statuses = {
        "adapter_unavailable",
        "connection_error",
        "missing_dependency",
        "pipeline_mismatch",
        "timeout",
    }
    for stage in stages:
        if not isinstance(stage, dict):
            return "bad_stage_provenance", "real sidecar stage provenance must be objects"
        status = str(stage.get("status") or "")
        if status in blocked_statuses:
            return (
                status,
                "product-like camera-grounded-labels runs require a real visual-grounding "
                "adapter; start .venv-visual-grounding with --pipeline real-router "
                "--adapter-mode real",
            )
    return None


def _blocked(result: dict[str, Any], *, reason: str, message: str) -> dict[str, Any]:
    updated = dict(result)
    updated.update({"ok": False, "reason": reason, "message": message})
    return updated


def _readiness_request(pipeline_id: str) -> dict[str, Any]:
    width = 320
    height = 240
    image = Image.new("RGB", (width, height), color=(238, 238, 232))
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 70, 105, 170), fill=(70, 130, 180), outline=(30, 70, 110), width=3)
    draw.rectangle((130, 95, 205, 180), fill=(205, 90, 75), outline=(120, 45, 38), width=3)
    draw.ellipse((230, 70, 285, 130), fill=(245, 245, 245), outline=(80, 80, 80), width=3)
    draw.rectangle((20, 182, 300, 205), fill=(110, 85, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return visual_grounding_request(
        run_id="visual-grounding-readiness",
        raw_observation={
            "observation_id": "readiness_probe_001",
            "waypoint_id": "readiness_waypoint",
            "room_id": "readiness_room",
            "artifact_status": "readiness_probe",
        },
        category_hints=["dish", "cup", "book", "bottle"],
        public_map_hints={
            "schema": "visual_grounding_public_map_hints_v1",
            "fixture_hints": [],
            "private_truth_included": False,
        },
        pipeline_id=pipeline_id,
        image={
            "mime_type": "image/jpeg",
            "bytes_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "width": width,
            "height": height,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
