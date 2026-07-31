from __future__ import annotations

import base64
import io
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.household.visual_grounding import (
    VISUAL_GROUNDING_RESPONSE_SCHEMA,
    HttpVisualGroundingClient,
    VisualGroundingClientConfig,
    visual_grounding_request,
)
from scripts.visual_grounding import adapters
from scripts.visual_grounding.check_visual_grounding_readiness import (
    _readiness_request,
    check_visual_grounding_readiness,
)
from scripts.visual_grounding.serve_visual_grounding_service import make_handler

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_SCRIPT = REPO_ROOT / "scripts" / "visual_grounding" / "serve_visual_grounding_service.py"


def test_model_loader_prefers_complete_local_cache() -> None:
    class _Factory:
        calls: list[dict[str, bool]] = []

        @classmethod
        def from_pretrained(cls, _model_id: str, **kwargs: bool) -> object:
            cls.calls.append(kwargs)
            return object()

    adapters._from_pretrained_local_first(_Factory, "cached-model")

    assert _Factory.calls == [{"local_files_only": True}]


def test_model_loader_uses_network_only_when_local_cache_is_missing() -> None:
    class _Factory:
        calls: list[dict[str, bool]] = []

        @classmethod
        def from_pretrained(cls, _model_id: str, **kwargs: bool) -> object:
            cls.calls.append(kwargs)
            if kwargs.get("local_files_only"):
                raise OSError("not cached")
            return object()

    adapters._from_pretrained_local_first(_Factory, "uncached-model")

    assert _Factory.calls == [{"local_files_only": True}, {}]


def test_configurable_service_reports_real_adapter_unavailable_by_default() -> None:
    server = _start_service(pipeline_id="grounding-dino", adapter_mode="auto")
    try:
        response = _client("grounding-dino", server).request_candidates(_request("grounding-dino"))
    finally:
        server.shutdown()
        server.server_close()

    assert response["status"] == "failed"
    assert response["candidates"] == []
    assert response["error"]["reason"] == "adapter_unavailable"
    assert response["pipeline"]["pipeline_id"] == "grounding-dino"
    assert response["pipeline"]["stages"][0]["stage"] == "proposer"
    assert response["pipeline"]["stages"][0]["producer_id"] == "grounding-dino"
    assert response["pipeline"]["stages"][0]["status"] == "adapter_unavailable"
    assert response["diagnostics"]["diagnostic_mode"] == "adapter_registry_stub"
    assert response["diagnostics"]["private_truth_included"] is False
    required = response["diagnostics"]["required_adapters"][0]
    assert required["producer_id"] == "grounding-dino"
    assert required["optional_extra"] == "visual-grounding-dino"
    assert "sidecar adapter" in required["setup_hint"]


def test_product_readiness_rejects_unavailable_grounding_dino_sidecar() -> None:
    server = _start_service(pipeline_id="grounding-dino", adapter_mode="auto")
    try:
        result = check_visual_grounding_readiness(
            pipeline_id="grounding-dino",
            base_url=f"http://127.0.0.1:{server.server_port}",
            timeout_s=2,
            require_real_adapter=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["ok"] is False
    assert result["reason"] == "adapter_unavailable"
    assert result["response_status"] == "failed"
    assert result["stage_statuses"][0]["status"] == "adapter_unavailable"


def test_product_readiness_probe_uses_camera_sized_jpeg_frame() -> None:
    request = _readiness_request("grounding-dino")
    image_packet = request["image"]
    image = Image.open(io.BytesIO(base64.b64decode(image_packet["bytes_base64"])))

    assert image_packet["mime_type"] == "image/jpeg"
    assert image_packet["width"] == 320
    assert image_packet["height"] == 240
    assert image.size == (320, 240)
    assert image.mode == "RGB"


def test_configurable_service_rejects_contract_fake_adapter_mode_from_cli() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SERVICE_SCRIPT),
            "--adapter-mode",
            "contract-fake",
            "--list-adapters",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_configurable_service_rejects_invalid_adapter_mode_from_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VISUAL_GROUNDING_ADAPTER_MODE", "contract-fake")

    result = subprocess.run(
        [
            sys.executable,
            str(SERVICE_SCRIPT),
            "--list-adapters",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "VISUAL_GROUNDING_ADAPTER_MODE must be one of auto, real, unavailable" in result.stderr


def test_configurable_service_contract_fake_pipeline_does_not_dispatch_fake_success() -> None:
    server = _start_service(pipeline_id="contract-fake", adapter_mode="auto")
    try:
        response = _client("yoloe", server).request_candidates(_request("yoloe"))
    finally:
        server.shutdown()
        server.server_close()

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "pipeline_mismatch"
    assert response["candidates"] == []


def test_real_mode_dispatches_grounding_dino_adapter(monkeypatch) -> None:
    def fake_grounding_dino_response(
        *,
        payload: dict[str, Any],
        pipeline_id: str,
        latency_ms: int,
    ) -> dict[str, Any]:
        assert payload["pipeline_request"]["pipeline_id"] == "grounding-dino"
        assert latency_ms == 1
        return {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": pipeline_id,
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake-real-model",
                        "status": "ok",
                        "latency_ms": 1,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "dish",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.9,
                    "evidence_note": "fake real adapter candidate",
                    "destination_hint": {"candidate_fixture_id": "sink_01"},
                }
            ],
            "diagnostics": {
                "schema": "visual_grounding_diagnostics_v1",
                "diagnostic_mode": "real_grounding_dino",
                "raw_proposals": [],
                "rejected_proposals": [],
                "private_truth_included": False,
            },
        }

    monkeypatch.setattr(
        adapters,
        "_grounding_dino_real_response",
        fake_grounding_dino_response,
    )

    response = adapters.visual_grounding_service_response(
        payload=_request("grounding-dino"),
        configured_pipeline_id="grounding-dino",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "ok"
    assert response["pipeline"]["stages"][0]["model_id"] == "fake-real-model"
    assert response["candidates"][0]["category"] == "dish"
    assert response["diagnostics"]["private_truth_included"] is False


def test_product_readiness_accepts_real_grounding_dino_sidecar(monkeypatch) -> None:
    def fake_grounding_dino_response(
        *,
        payload: dict[str, Any],
        pipeline_id: str,
        latency_ms: int,
    ) -> dict[str, Any]:
        assert payload["pipeline_request"]["pipeline_id"] == "grounding-dino"
        return {
            "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
            "status": "ok",
            "pipeline": {
                "pipeline_id": pipeline_id,
                "stages": [
                    {
                        "stage": "proposer",
                        "producer_id": "grounding-dino",
                        "model_id": "fake-real-model",
                        "status": "ok",
                        "latency_ms": latency_ms,
                    }
                ],
            },
            "candidates": [
                {
                    "category": "dish",
                    "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
                    "confidence": 0.9,
                }
            ],
            "diagnostics": {
                "schema": "visual_grounding_diagnostics_v1",
                "diagnostic_mode": "real_grounding_dino",
                "raw_proposals": [],
                "rejected_proposals": [],
                "private_truth_included": False,
            },
        }

    monkeypatch.setattr(
        adapters,
        "_grounding_dino_real_response",
        fake_grounding_dino_response,
    )
    server = _start_service(pipeline_id="grounding-dino", adapter_mode="real")
    try:
        result = check_visual_grounding_readiness(
            pipeline_id="grounding-dino",
            base_url=f"http://127.0.0.1:{server.server_port}",
            timeout_s=2,
            require_real_adapter=True,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["ok"] is True
    assert result["response_status"] == "ok"
    assert result["stage_statuses"][0]["model_id"] == "fake-real-model"


def test_grounding_dino_real_mode_defaults_to_base_recall(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_load_grounding_dino(
        model_id: str,
        requested_device: str,
        requested_dtype: str,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        seen["model_id"] = model_id
        seen["requested_device"] = requested_device
        seen["requested_dtype"] = requested_dtype
        raise adapters.VisualGroundingDeviceError("stop before model inference")

    monkeypatch.delenv("VISUAL_GROUNDING_DINO_MODEL_ID", raising=False)
    monkeypatch.delenv("VISUAL_GROUNDING_DINO_BOX_THRESHOLD", raising=False)
    monkeypatch.delenv("VISUAL_GROUNDING_DINO_TEXT_THRESHOLD", raising=False)
    monkeypatch.delenv("VISUAL_GROUNDING_DEVICE", raising=False)
    monkeypatch.delenv("VISUAL_GROUNDING_TORCH_DTYPE", raising=False)
    monkeypatch.setattr(adapters, "_load_grounding_dino", fake_load_grounding_dino)

    response = adapters.visual_grounding_service_response(
        payload=_request("grounding-dino", image=_jpeg_image_payload()),
        configured_pipeline_id="grounding-dino",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert seen == {
        "model_id": "IDEA-Research/grounding-dino-base",
        "requested_device": "auto",
        "requested_dtype": "auto",
    }
    stage = response["pipeline"]["stages"][0]
    assert stage["model_id"] == "IDEA-Research/grounding-dino-base"
    assert stage["runtime_parameters"]["box_threshold"] == 0.25
    assert stage["runtime_parameters"]["text_threshold"] == 0.2


def test_real_mode_reports_grounding_dino_missing_dependency(monkeypatch) -> None:
    def missing_grounding_dino(
        _model_id: str,
        _requested_device: str,
        _requested_dtype: str,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        raise ImportError("missing sidecar deps")

    monkeypatch.setattr(adapters, "_load_grounding_dino", missing_grounding_dino)

    response = adapters.visual_grounding_service_response(
        payload=_request("grounding-dino", image=_jpeg_image_payload()),
        configured_pipeline_id="grounding-dino",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "missing_dependency"
    assert response["candidates"] == []
    assert response["pipeline"]["stages"][0]["status"] == "missing_dependency"
    assert response["diagnostics"]["required_adapters"][0]["producer_id"] == "grounding-dino"
    assert response["diagnostics"]["private_truth_included"] is False


def test_real_mode_reports_grounding_dino_device_unavailable(monkeypatch) -> None:
    def cuda_unavailable(
        model_id: str,
        requested_device: str,
        requested_dtype: str,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        assert model_id == "IDEA-Research/grounding-dino-base"
        assert requested_device == "cuda"
        assert requested_dtype == "float16"
        raise adapters.VisualGroundingDeviceError("cuda unavailable")

    monkeypatch.setattr(adapters, "_load_grounding_dino", cuda_unavailable)
    request = _request("grounding-dino", image=_jpeg_image_payload())
    request["pipeline_request"]["proposer"]["runtime_parameters"] = {
        "device": "cuda",
        "torch_dtype": "float16",
        "box_threshold": 0.25,
        "text_threshold": 0.2,
    }

    response = adapters.visual_grounding_service_response(
        payload=request,
        configured_pipeline_id="grounding-dino",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "device_unavailable"
    stage = response["pipeline"]["stages"][0]
    assert stage["runtime"]["requested_device"] == "cuda"
    assert stage["runtime"]["requested_dtype"] == "float16"
    assert stage["runtime_parameters"]["box_threshold"] == 0.25
    assert response["diagnostics"]["runtime"]["requested_device"] == "cuda"


def test_real_mode_rejects_malformed_request_runtime_parameter(monkeypatch) -> None:
    def should_not_load_model(
        _model_id: str,
        _requested_device: str,
        _requested_dtype: str,
    ) -> tuple[Any, Any, Any, dict[str, Any]]:
        raise AssertionError("invalid runtime parameters should fail before model loading")

    monkeypatch.setattr(adapters, "_load_grounding_dino", should_not_load_model)
    request = _request("grounding-dino", image=_jpeg_image_payload())
    request["pipeline_request"]["proposer"]["runtime_parameters"] = {
        "box_threshold": "not-a-number",
    }

    response = adapters.visual_grounding_service_response(
        payload=request,
        configured_pipeline_id="grounding-dino",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "invalid_runtime_parameter"
    assert "runtime_parameters.box_threshold" in response["error"]["message"]
    assert response["pipeline"]["stages"][0]["status"] == "invalid_runtime_parameter"
    assert response["pipeline"]["stages"][0]["runtime_parameters"]["box_threshold"] == (
        "not-a-number"
    )

    request["pipeline_request"]["proposer"]["runtime_parameters"] = {"box_threshold": True}
    response = adapters.visual_grounding_service_response(
        payload=request,
        configured_pipeline_id="grounding-dino",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "invalid_runtime_parameter"


def test_real_mode_rejects_malformed_env_runtime_parameter(monkeypatch) -> None:
    def should_not_load_model(
        _model_id: str,
        *,
        producer_id: str,
    ) -> Any:
        raise AssertionError(f"invalid runtime env should fail before loading {producer_id} model")

    monkeypatch.setenv("VISUAL_GROUNDING_YOLO_IMAGE_SIZE", "wide")
    monkeypatch.setattr(adapters, "_load_yolo_model", should_not_load_model)

    response = adapters.visual_grounding_service_response(
        payload=_request("yolo-world", image=_jpeg_image_payload()),
        configured_pipeline_id="yolo-world",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "invalid_runtime_parameter"
    assert "VISUAL_GROUNDING_YOLO_IMAGE_SIZE" in response["error"]["message"]
    assert response["pipeline"]["stages"][0]["status"] == "invalid_runtime_parameter"


def _start_service(*, pipeline_id: str, adapter_mode: str) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(pipeline_id=pipeline_id, adapter_mode=adapter_mode, latency_ms=1),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _client(pipeline_id: str, server: ThreadingHTTPServer) -> HttpVisualGroundingClient:
    return HttpVisualGroundingClient(
        VisualGroundingClientConfig(
            pipeline_id=pipeline_id,
            base_url=f"http://127.0.0.1:{server.server_port}",
            timeout_s=2,
        )
    )


def _tiny_image() -> Image.Image:
    return Image.new("RGB", (10, 10), (240, 240, 240))


def _request(pipeline_id: str, *, image: dict[str, Any] | None = None) -> dict[str, Any]:
    return visual_grounding_request(
        run_id="seed-7",
        raw_observation={
            "observation_id": "raw_fpv_kitchen_dish_001",
            "waypoint_id": "wp_kitchen_01",
            "room_id": "kitchen",
            "artifact_status": "recorded",
        },
        category_hints=["dish", "book", "toy"],
        public_map_hints=_public_map_hints(),
        pipeline_id=pipeline_id,
        image=image
        or {
            "mime_type": "image/jpeg",
            "bytes_base64": "ZmFrZQ==",
            "width": 2,
            "height": 2,
        },
        proposer={"producer_id": pipeline_id.split("+", maxsplit=1)[0]},
    )


def _public_map_hints() -> dict[str, Any]:
    return {
        "schema": "visual_grounding_public_map_hints_v1",
        "source": "test_public_map_hints",
        "fixture_hints": [
            {
                "fixture_id": "sink_01",
                "room_id": "kitchen",
                "category": "sink",
                "affordances": ["inside"],
            }
        ],
        "private_truth_included": False,
    }


def _jpeg_image_payload() -> dict[str, Any]:
    buffer = io.BytesIO()
    _tiny_image().save(buffer, format="JPEG", quality=90)
    return {
        "mime_type": "image/jpeg",
        "bytes_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "width": 10,
        "height": 10,
    }
