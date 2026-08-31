from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.household.visual_grounding import (
    HttpVisualGroundingClient,
    VisualGroundingClientConfig,
    visual_grounding_request,
)
from roboclaws.household.visual_grounding_sidecar import (
    adapter_candidates,
    adapter_omdet,
    adapter_service,
    adapter_yolo,
)
from roboclaws.household.visual_grounding_sidecar.adapter_contracts import (
    visual_grounding_adapter_catalog,
)
from roboclaws.household.visual_grounding_sidecar.service import make_handler

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_COMMAND = [
    sys.executable,
    "-m",
    "roboclaws.household.visual_grounding_sidecar.service",
]


def test_real_mode_dispatches_yolo_world_through_standard_yolo_loader(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class FakeBoxes:
        xyxy = [[1, 2, 7, 6]]
        conf = [0.72]
        cls = [0]

    class FakeResult:
        boxes = FakeBoxes()
        names = {0: "dish"}

    class FakeModel:
        def predict(self, *, source: str, conf: float, verbose: bool) -> list[FakeResult]:
            assert source.endswith(".jpg")
            assert conf > 0
            assert verbose is False
            return [FakeResult()]

    def fake_yolo_loader(model_id: str, *, producer_id: str) -> FakeModel:
        seen["model_id"] = model_id
        seen["producer_id"] = producer_id
        return FakeModel()

    monkeypatch.setattr(adapter_yolo, "_load_yolo_model", fake_yolo_loader)

    response = adapter_service.visual_grounding_service_response(
        payload=_request("yolo-world", image=_jpeg_image_payload()),
        configured_pipeline_id="yolo-world",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "ok"
    assert seen["producer_id"] == "yolo-world"
    assert response["pipeline"]["stages"][0]["producer_id"] == "yolo-world"
    assert response["candidates"][0]["category"] == "dish"
    assert response["diagnostics"]["diagnostic_mode"] == "real_yolo-world"


def test_real_mode_dispatches_omdet_turbo_adapter(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    class FakeInputs(dict):
        input_ids = [[1]]

        def to(self, device: str) -> "FakeInputs":
            seen["device"] = device
            return self

    class FakeProcessor:
        def __call__(
            self,
            *,
            images: Image.Image,
            text: list[str],
            task: str,
            return_tensors: str,
        ) -> FakeInputs:
            assert images.size == (10, 10)
            assert text == ["a dish", "a book", "a toy"]
            assert task.startswith("Detect")
            assert return_tensors == "pt"
            seen["text"] = text
            return FakeInputs(pixel_values="fake")

        def post_process_grounded_object_detection(
            self,
            outputs: Any,
            *,
            text_labels: list[str],
            threshold: float,
            nms_threshold: float,
            target_sizes: list[tuple[int, int]],
            max_num_det: int | None,
        ) -> list[dict[str, Any]]:
            assert outputs == {"fake": "outputs"}
            assert text_labels == ["a dish", "a book", "a toy"]
            assert threshold == 0.2
            assert nms_threshold == 0.4
            assert target_sizes == [(10, 10)]
            assert max_num_det == 6
            return [
                {
                    "boxes": [[1, 2, 7, 6]],
                    "scores": [0.73],
                    "text_labels": ["a dish"],
                }
            ]

    class FakeModel:
        def __call__(self, **inputs: Any) -> dict[str, str]:
            assert inputs == {"pixel_values": "fake"}
            return {"fake": "outputs"}

    class FakeTorch:
        class _NoGrad:
            def __enter__(self) -> None:
                return None

            def __exit__(self, *_args: Any) -> None:
                return None

        def no_grad(self) -> "FakeTorch._NoGrad":
            return self._NoGrad()

    def fake_load_omdet(
        model_id: str,
        requested_device: str,
        requested_dtype: str,
    ) -> tuple[FakeProcessor, FakeModel, FakeTorch, dict[str, Any]]:
        seen["model_id"] = model_id
        seen["requested_device"] = requested_device
        seen["requested_dtype"] = requested_dtype
        return (
            FakeProcessor(),
            FakeModel(),
            FakeTorch(),
            {"device": "cpu", "dtype": "auto", "model_id": model_id},
        )

    monkeypatch.setattr(adapter_omdet, "_load_omdet_turbo", fake_load_omdet)
    request = _request("omdet-turbo", image=_jpeg_image_payload())
    request["pipeline_request"]["proposer"]["runtime_parameters"] = {
        "confidence_threshold": 0.2,
        "nms_threshold": 0.4,
        "max_detections": 6,
        "device": "cpu",
        "torch_dtype": "auto",
    }

    response = adapter_service.visual_grounding_service_response(
        payload=request,
        configured_pipeline_id="omdet-turbo",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "ok"
    assert seen["model_id"] == "omlab/omdet-turbo-swin-tiny-hf"
    assert seen["requested_device"] == "cpu"
    assert response["pipeline"]["stages"][0]["producer_id"] == "omdet-turbo"
    assert response["pipeline"]["stages"][0]["runtime_parameters"]["confidence_threshold"] == 0.2
    assert response["candidates"][0]["category"] == "dish"
    assert response["diagnostics"]["diagnostic_mode"] == "real_omdet-turbo"


def test_real_mode_qwen_direct_is_retired_without_fake_success() -> None:
    response = adapter_service.visual_grounding_service_response(
        payload=_request("qwen3-vl-direct", image=_jpeg_image_payload()),
        configured_pipeline_id="qwen3-vl-direct",
        adapter_mode="real",
        latency_ms=1,
    )

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "adapter_unavailable"
    assert response["candidates"] == []
    assert response["pipeline"]["stages"][0]["stage"] == "proposer"
    assert response["pipeline"]["stages"][0]["producer_id"] == "qwen3-vl-direct"
    assert response["diagnostics"]["required_adapters"][0]["producer_id"] == "qwen3-vl-direct"


def test_real_adapter_bbox_normalization_and_destination_hint() -> None:
    request = _request("grounding-dino")
    candidate = adapter_candidates._candidate_from_xyxy(  # noqa: SLF001
        payload=request,
        image=_tiny_image(),
        category="dish",
        xyxy=[1, 2, 7, 6],
        confidence=1.2,
        evidence_note="unit probe",
    )

    assert candidate is not None
    assert candidate["image_region"] == {"type": "bbox", "value": [0.1, 0.2, 0.6, 0.4]}
    assert candidate["confidence"] == 1.0
    assert candidate["destination_hint"]["candidate_fixture_id"] == "sink_01"


def test_adapter_candidate_limit_removes_overlapping_duplicate_boxes(monkeypatch) -> None:
    monkeypatch.setenv("VISUAL_GROUNDING_MAX_CANDIDATES", "8")
    candidates = [
        {
            "category": "food",
            "confidence": 0.7,
            "image_region": {"type": "bbox", "value": [0.1, 0.1, 0.2, 0.2]},
        },
        {
            "category": "potato",
            "confidence": 0.9,
            "image_region": {"type": "bbox", "value": [0.11, 0.11, 0.18, 0.18]},
        },
        {
            "category": "book",
            "confidence": 0.8,
            "image_region": {"type": "bbox", "value": [0.6, 0.6, 0.2, 0.2]},
        },
    ]

    selected = adapter_candidates._top_candidates(candidates)  # noqa: SLF001

    assert [candidate["category"] for candidate in selected] == ["potato", "book"]


def test_configurable_service_rejects_pipeline_mismatch() -> None:
    server = _start_service(pipeline_id="grounding-dino", adapter_mode="auto")
    try:
        response = _client("yoloe", server).request_candidates(_request("yoloe"))
    finally:
        server.shutdown()
        server.server_close()

    assert response["status"] == "failed"
    assert response["error"]["reason"] == "pipeline_mismatch"
    assert response["candidates"] == []


def test_configurable_service_rejects_non_object_request_before_dispatch() -> None:
    server = _start_service(pipeline_id="grounding-dino", adapter_mode="auto")
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/v1/visual-grounding/candidates",
            data=b"[]",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
        payload = exc.read()
    finally:
        server.shutdown()
        server.server_close()

    response = json.loads(payload.decode("utf-8"))
    assert response["status"] == "failed"
    assert response["error"]["reason"] == "bad_request"
    assert response["candidates"] == []
    assert (
        response["error"]["message"]
        == "visual grounding HTTP request source must contain a JSON object: "
        "POST /v1/visual-grounding/candidates"
    )


def test_adapter_catalog_lists_real_adapter_slots_without_private_truth() -> None:
    catalog = visual_grounding_adapter_catalog()

    assert catalog["schema"] == "visual_grounding_adapter_catalog_v1"
    assert "real" in catalog["adapter_modes"]
    assert catalog["private_truth_included"] is False
    by_id = {item["producer_id"]: item for item in catalog["adapters"]}
    assert "yolo-custom" not in by_id
    assert "fake-http" not in by_id
    assert "contract-fake" not in by_id
    assert by_id["grounding-dino"]["optional_extra"] == "visual-grounding-dino"
    assert by_id["grounding-dino"]["runtime"]["status"] in {
        "missing_dependency",
        "dependency_ready_model_unverified",
    }
    assert {item["name"] for item in by_id["grounding-dino"]["runtime"]["checks"]} == {
        "torch",
        "transformers",
    }
    assert by_id["yoloe"]["optional_extra"] == "visual-grounding-yoloe"
    assert {item["name"] for item in by_id["yoloe"]["runtime"]["checks"]} == {"ultralytics"}
    assert by_id["yolo-world"]["optional_extra"] == "visual-grounding-yolo-world"
    assert {item["name"] for item in by_id["yolo-world"]["runtime"]["checks"]} == {"ultralytics"}
    assert by_id["omdet-turbo"]["optional_extra"] == "visual-grounding-omdet"
    assert {item["name"] for item in by_id["omdet-turbo"]["runtime"]["checks"]} == {
        "torch",
        "transformers",
    }
    for retired in {
        "retired-vlm",
        "qwen3-vl",
        "retired-vlm-qualified",
        "vertex_ai/gemini-3.1-flash-lite-preview",
        "vertex_ai/gemini-3-flash-preview",
        "tongyi/qwen3-vl-flash",
        "tongyi/qwen3-vl-plus",
        "siliconflow/Qwen/Qwen3-VL-8B-Instruct",
    }:
        assert retired not in by_id
    assert "authorization" not in json.dumps(catalog).lower()
    assert "secret-provider-key" not in json.dumps(catalog)


def test_dependency_metadata_does_not_expose_retired_qwen_vlm_extra() -> None:
    root_pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    sidecar_pyproject = (REPO_ROOT / "sidecars" / "visual-grounding" / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    for text in (root_pyproject, sidecar_pyproject):
        assert "qwen3vl" not in text.lower()
        assert "qwen-vl-utils" not in text


def test_configurable_service_lists_adapter_catalog_cli() -> None:
    result = subprocess.run(
        [*SERVICE_COMMAND, "--list-adapters"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    catalog = json.loads(result.stdout)
    assert catalog["schema"] == "visual_grounding_adapter_catalog_v1"
    assert {item["producer_id"] for item in catalog["adapters"]} == {
        "grounding-dino",
        "yoloe",
        "yolo-world",
        "omdet-turbo",
    }
    assert "yolo-custom" not in {item["producer_id"] for item in catalog["adapters"]}
    by_id = {item["producer_id"]: item for item in catalog["adapters"]}
    assert "runtime" in by_id["grounding-dino"]
    assert "retired-vlm" not in by_id
    assert "qwen3-vl" not in by_id
    assert "authorization" not in result.stdout.lower()
    assert "secret-provider-key" not in result.stdout


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
