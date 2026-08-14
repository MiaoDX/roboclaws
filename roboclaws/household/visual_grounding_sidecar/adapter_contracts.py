from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from roboclaws.household.visual_grounding import (
    VISUAL_GROUNDING_RESPONSE_SCHEMA,
    validate_visual_grounding_response,
)

ADAPTER_MODE_AUTO = "auto"
ADAPTER_MODE_REAL = "real"
ADAPTER_MODE_UNAVAILABLE = "unavailable"
REAL_ROUTER_PIPELINE_ID = "real-router"
DEFAULT_PIPELINE_ID = "grounding-dino"
DEFAULT_GROUNDING_DINO_MODEL_ID = "IDEA-Research/grounding-dino-base"
DEFAULT_GROUNDING_DINO_BOX_THRESHOLD = 0.25
DEFAULT_GROUNDING_DINO_TEXT_THRESHOLD = 0.20
ADAPTER_CATALOG_SCHEMA = "visual_grounding_adapter_catalog_v1"


@dataclass(frozen=True)
class AdapterSpec:
    producer_id: str
    role: str
    status: str
    model_id: str
    optional_extra: str
    setup_hint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "producer_id": self.producer_id,
            "role": self.role,
            "status": self.status,
            "model_id": self.model_id,
            "optional_extra": self.optional_extra,
            "runtime": adapter_runtime_status(self.producer_id),
            "setup_hint": self.setup_hint,
        }


ADAPTER_SPECS: dict[str, AdapterSpec] = {
    "grounding-dino": AdapterSpec(
        producer_id="grounding-dino",
        role="proposer",
        status="adapter_unavailable",
        model_id=DEFAULT_GROUNDING_DINO_MODEL_ID,
        optional_extra="visual-grounding-dino",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Transformers, Torch, and the selected Grounding DINO model weights."
        ),
    ),
    "yoloe": AdapterSpec(
        producer_id="yoloe",
        role="proposer",
        status="adapter_unavailable",
        model_id="yoloe-11s-seg.pt",
        optional_extra="visual-grounding-yoloe",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Ultralytics, the CLIP tokenizer package, and approved YOLOE weights."
        ),
    ),
    "yolo-world": AdapterSpec(
        producer_id="yolo-world",
        role="proposer",
        status="adapter_unavailable",
        model_id="yolov8s-world.pt",
        optional_extra="visual-grounding-yolo-world",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Ultralytics and approved YOLO-World weights."
        ),
    ),
    "omdet-turbo": AdapterSpec(
        producer_id="omdet-turbo",
        role="proposer",
        status="adapter_unavailable",
        model_id="omlab/omdet-turbo-swin-tiny-hf",
        optional_extra="visual-grounding-omdet",
        setup_hint=(
            "Run the sidecar adapter with --adapter-mode real after explicitly installing "
            "Torch, Transformers, and approved OmDet-Turbo weights."
        ),
    ),
}


def visual_grounding_adapter_catalog() -> dict[str, Any]:
    return {
        "schema": ADAPTER_CATALOG_SCHEMA,
        "real_router_pipeline_id": REAL_ROUTER_PIPELINE_ID,
        "default_pipeline_id": DEFAULT_PIPELINE_ID,
        "adapter_modes": [
            ADAPTER_MODE_AUTO,
            ADAPTER_MODE_REAL,
            ADAPTER_MODE_UNAVAILABLE,
        ],
        "adapters": [spec.as_dict() for spec in ADAPTER_SPECS.values()],
        "private_truth_included": False,
    }


def adapter_runtime_status(producer_id: str) -> dict[str, Any]:
    if producer_id == "grounding-dino":
        checks = _module_checks("torch", "transformers")
        return _dependency_runtime_status(
            checks=checks,
            ready_message=(
                "Grounding DINO Python dependencies are importable; model weights "
                "are verified only by a real adapter run."
            ),
            missing_message=(
                "Grounding DINO real mode requires importable torch and transformers "
                "in the sidecar environment."
            ),
        )
    if producer_id in {"yoloe", "yolo-world"}:
        checks = _module_checks("ultralytics")
        return _dependency_runtime_status(
            checks=checks,
            ready_message=(
                "Ultralytics is importable; YOLO-family weights are verified only "
                "by a real adapter run."
            ),
            missing_message=(
                f"{producer_id} real mode requires importable ultralytics in the "
                "sidecar environment."
            ),
        )
    if producer_id == "omdet-turbo":
        checks = _module_checks("torch", "transformers")
        return _dependency_runtime_status(
            checks=checks,
            ready_message=(
                "Torch and Transformers are importable; OmDet-Turbo weights are "
                "verified only by a real adapter run."
            ),
            missing_message=(
                "omdet-turbo real mode requires importable torch and transformers "
                "in the sidecar environment."
            ),
        )
    return {
        "status": "unknown_adapter",
        "checks": [],
        "auth_mode": "none",
        "model_weights_verified": False,
        "message": "No runtime readiness probe is registered for this adapter.",
    }


def _dependency_runtime_status(
    *,
    checks: list[dict[str, Any]],
    ready_message: str,
    missing_message: str,
) -> dict[str, Any]:
    missing = [str(item["name"]) for item in checks if not item["available"]]
    if missing:
        return {
            "status": "missing_dependency",
            "checks": checks,
            "missing_dependencies": missing,
            "auth_mode": "none",
            "model_weights_verified": False,
            "message": missing_message,
        }
    return {
        "status": "dependency_ready_model_unverified",
        "checks": checks,
        "missing_dependencies": [],
        "auth_mode": "none",
        "model_weights_verified": False,
        "message": ready_message,
    }


def _module_checks(*module_names: str) -> list[dict[str, Any]]:
    return [
        {
            "name": module_name,
            "available": importlib.util.find_spec(module_name) is not None,
        }
        for module_name in module_names
    ]


def request_pipeline_id(payload: dict[str, Any]) -> str:
    pipeline_request = payload.get("pipeline_request") or {}
    return str(pipeline_request.get("pipeline_id") or "").strip()


def effective_pipeline_id(
    *,
    configured_pipeline_id: str,
    requested_pipeline_id: str,
) -> str:
    configured = str(configured_pipeline_id or "").strip()
    requested = str(requested_pipeline_id or "").strip()
    if configured == REAL_ROUTER_PIPELINE_ID:
        return requested or DEFAULT_PIPELINE_ID
    return configured or requested or DEFAULT_PIPELINE_ID


def pipeline_request_is_allowed(
    *,
    configured_pipeline_id: str,
    requested_pipeline_id: str,
    effective_pipeline_id: str,
) -> bool:
    if configured_pipeline_id == REAL_ROUTER_PIPELINE_ID:
        return True
    if not requested_pipeline_id:
        return True
    return requested_pipeline_id == effective_pipeline_id


def adapter_unavailable_response(
    *,
    pipeline_id: str,
    adapter_mode: str,
    latency_ms: int,
) -> dict[str, Any]:
    producer_id = str(pipeline_id or DEFAULT_PIPELINE_ID)
    spec = ADAPTER_SPECS.get(producer_id)
    stage = {
        "stage": "proposer",
        "producer_id": producer_id,
        "model_id": spec.model_id if spec is not None else "",
        "status": "adapter_unavailable",
        "version": "adapter-unavailable-v1",
        "latency_ms": latency_ms,
    }
    if spec is not None:
        stage["optional_extra"] = spec.optional_extra
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "failed",
        "pipeline": {
            "pipeline_id": pipeline_id,
            "stages": [stage],
        },
        "candidates": [],
        "error": {
            "reason": "adapter_unavailable",
            "message": (
                f"visual grounding adapter for '{pipeline_id}' is not installed; "
                "install the optional sidecar adapter or run with --adapter-mode real "
                "in an environment with the selected model dependencies and weights."
            ),
        },
        "diagnostics": {
            "schema": "visual_grounding_diagnostics_v1",
            "diagnostic_mode": "adapter_registry_stub",
            "adapter_mode": adapter_mode,
            "required_adapters": [_required_adapter_record(stage, spec)],
            "raw_proposals": [],
            "rejected_proposals": [],
            "private_truth_included": False,
        },
    }
    return validate_visual_grounding_response(response)


def pipeline_mismatch_response(
    *,
    configured_pipeline_id: str,
    requested_pipeline_id: str,
) -> dict[str, Any]:
    response = {
        "schema": VISUAL_GROUNDING_RESPONSE_SCHEMA,
        "status": "failed",
        "pipeline": {
            "pipeline_id": requested_pipeline_id or configured_pipeline_id,
            "stages": [
                {
                    "stage": "router",
                    "producer_id": configured_pipeline_id,
                    "model_id": "",
                    "status": "pipeline_mismatch",
                    "latency_ms": 0,
                }
            ],
        },
        "candidates": [],
        "error": {
            "reason": "pipeline_mismatch",
            "message": (
                f"service pipeline '{configured_pipeline_id}' cannot satisfy "
                f"request pipeline '{requested_pipeline_id}'"
            ),
        },
    }
    return validate_visual_grounding_response(response)


def _required_adapter_record(
    stage: dict[str, Any],
    spec: AdapterSpec | None,
) -> dict[str, Any]:
    producer_id = str(stage.get("producer_id") or "")
    if spec is None:
        return {
            "stage": str(stage.get("stage") or ""),
            "producer_id": producer_id,
            "status": "adapter_unavailable",
            "model_id": str(stage.get("model_id") or ""),
            "optional_extra": "",
            "setup_hint": "No adapter spec is registered for this producer id.",
        }
    return {
        "stage": str(stage.get("stage") or ""),
        "producer_id": producer_id,
        "status": spec.status,
        "model_id": spec.model_id,
        "optional_extra": spec.optional_extra,
        "setup_hint": spec.setup_hint,
    }
