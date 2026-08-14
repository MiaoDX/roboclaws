#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import parse_json_object_text  # noqa: E402
from roboclaws.household.visual_grounding import (  # noqa: E402
    validate_visual_grounding_request,
    visual_grounding_failure_response,
)
from roboclaws.household.visual_grounding_sidecar.adapter_contracts import (  # noqa: E402
    ADAPTER_MODE_AUTO,
    ADAPTER_MODE_REAL,
    ADAPTER_MODE_UNAVAILABLE,
    DEFAULT_PIPELINE_ID,
    REAL_ROUTER_PIPELINE_ID,
    visual_grounding_adapter_catalog,
)
from roboclaws.household.visual_grounding_sidecar.adapter_service import (  # noqa: E402
    visual_grounding_service_response,
)

ENDPOINT = "/v1/visual-grounding/candidates"
ADAPTER_MODES = (
    ADAPTER_MODE_AUTO,
    ADAPTER_MODE_REAL,
    ADAPTER_MODE_UNAVAILABLE,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Serve the configurable Roboclaws visual-grounding HTTP sidecar. "
            "Real model adapters are explicit sidecar work; by default named "
            "real pipelines return visible adapter_unavailable failures."
        )
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18880)
    parser.add_argument(
        "--pipeline",
        default=os.environ.get("VISUAL_GROUNDING_PIPELINE_ID", DEFAULT_PIPELINE_ID),
        help=(
            f"Configured detector pipeline id, or '{REAL_ROUTER_PIPELINE_ID}' "
            "to route requested detector pipelines through one local sidecar."
        ),
    )
    parser.add_argument(
        "--adapter-mode",
        choices=ADAPTER_MODES,
        default=_adapter_mode_default(),
        help=(
            "auto reports adapters according to local model readiness; "
            "real loads optional sidecar model adapters; unavailable forces "
            "explicit missing-sidecar responses."
        ),
    )
    parser.add_argument("--latency-ms", type=int, default=3)
    parser.add_argument(
        "--list-adapters",
        action="store_true",
        help="Print the lightweight sidecar adapter catalog as JSON and exit.",
    )
    return parser.parse_args(argv)


def _adapter_mode_default() -> str:
    value = os.environ.get("VISUAL_GROUNDING_ADAPTER_MODE", ADAPTER_MODE_AUTO)
    if value in ADAPTER_MODES:
        return value
    expected = ", ".join(ADAPTER_MODES)
    raise SystemExit(f"VISUAL_GROUNDING_ADAPTER_MODE must be one of {expected}, got {value!r}")


def make_handler(
    *,
    pipeline_id: str,
    adapter_mode: str,
    latency_ms: int,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "roboclaws-visual-grounding-service/1.0"

        def do_POST(self) -> None:  # noqa: N802
            if self.path != ENDPOINT:
                self.send_error(404, "not found")
                return

            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = _read_request_json_object(
                    self.rfile.read(length),
                    source=f"POST {self.path}",
                )
                validate_visual_grounding_request(payload)
            except Exception as exc:
                self._write_json(
                    400,
                    visual_grounding_failure_response(
                        pipeline_id=pipeline_id or DEFAULT_PIPELINE_ID,
                        reason="bad_request",
                        message=str(exc),
                        latency_ms=0,
                    ),
                )
                return

            if latency_ms > 0:
                time.sleep(latency_ms / 1000)

            self._write_json(
                200,
                visual_grounding_service_response(
                    payload=payload,
                    configured_pipeline_id=pipeline_id,
                    adapter_mode=adapter_mode,
                    latency_ms=latency_ms,
                ),
            )

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _read_request_json_object(body: bytes, *, source: str) -> dict[str, Any]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"visual grounding HTTP request source must contain UTF-8 JSON object: {source}"
        ) from exc
    return parse_json_object_text(text, label="visual grounding HTTP request", source=source)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_adapters:
        print(json.dumps(visual_grounding_adapter_catalog(), indent=2, sort_keys=True))
        return 0
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(
            pipeline_id=args.pipeline,
            adapter_mode=args.adapter_mode,
            latency_ms=args.latency_ms,
        ),
    )
    print(
        "visual grounding service: "
        f"http://{args.host}:{args.port}{ENDPOINT} "
        f"pipeline={args.pipeline} adapter_mode={args.adapter_mode}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
