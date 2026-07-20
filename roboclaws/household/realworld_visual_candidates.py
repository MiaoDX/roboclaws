from __future__ import annotations

import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.household import realworld_contract_projection
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    image_payload_for_raw_observation,
    sim_visual_grounding_pipeline,
)

MODEL_DECLARED_OBSERVATIONS_SCHEMA = "model_declared_observations_v1"
VISUAL_GROUNDING_EVIDENCE_SCHEMA = "visual_grounding_evidence_v1"
MAIN_CLEANUP_AGENT_PRODUCER = "main_cleanup_agent"
TEST_AGENT_PRODUCER = "test_agent"
SIMULATED_CAMERA_MODEL_PROVENANCE = "simulated_camera_model"
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = "visual_candidate_already_handled"
VISUAL_EVIDENCE_REVIEWABLE_STATUS = "reviewable"
VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS = "not_reviewable"
VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY = "needs_visual_evidence"
CANDIDATE_STATE_SEMANTIC = "semantic_candidate"
CANDIDATE_STATE_VISUAL_SCAN_REQUIRED = "visual_scan_required"
CANDIDATE_STATE_VISUALLY_CONFIRMED = "visually_confirmed"
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = "navigation_authorized"
VISUAL_GROUNDING_CATEGORY_HINTS = [
    "food",
    "dish",
    "book",
    "linen",
    "toy",
    "electronics",
    "pillow",
]

_EXACT_VISUAL_CATEGORY_ALIASES = frozenset(
    {"cup", "mug", "plate", "bowl", "utensil", "fork", "knife", "spoon", "ladle"}
)
_EXACT_VISUAL_SYNONYM_GROUPS = (frozenset({"spoon", "ladle"}),)
_OBJECT_CATEGORY_TARGETS = realworld_contract_projection._OBJECT_CATEGORY_TARGETS


def _visual_grounding_evidence_for_candidate(
    candidate: dict[str, Any],
    *,
    fallback_image_bbox: Any = None,
    grounding_status: str = "",
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    image_region = candidate.get("image_region")
    if not image_region and candidate.get("image_bbox"):
        image_region = {"type": "bbox", "value": candidate.get("image_bbox")}
    image_region = _normalize_image_region(image_region)
    bbox = image_region.get("value") if image_region.get("type") == "bbox" else fallback_image_bbox
    if bbox is None:
        bbox = candidate.get("image_bbox")
    image_dimensions = candidate.get("image_dimensions") or {}
    review = _bbox_reviewability(bbox, image_dimensions=image_dimensions)
    if (
        review["reviewability_status"] != VISUAL_EVIDENCE_REVIEWABLE_STATUS
        and image_region.get("type") == "verbal_region"
        and str(candidate.get("producer_type") or "") == TEST_AGENT_PRODUCER
    ):
        review = {
            "reviewability_status": VISUAL_EVIDENCE_REVIEWABLE_STATUS,
            "reviewability_reason": "test_agent_verbal_region",
            "bbox_coordinate_space": "",
            "image_bbox": [],
        }
    pipeline = candidate.get("visual_grounding_pipeline") or {}
    evidence = {
        "schema": VISUAL_GROUNDING_EVIDENCE_SCHEMA,
        "camera_frame": "agent_facing_fpv",
        "source_observation_id": str(candidate.get("source_observation_id") or ""),
        "producer_type": str(candidate.get("producer_type") or ""),
        "producer_id": str(candidate.get("producer_id") or ""),
        "image_region": image_region,
        "image_bbox": review["image_bbox"],
        "bbox_coordinate_space": review["bbox_coordinate_space"],
        "reviewability_status": review["reviewability_status"],
        "reviewability_reason": review["reviewability_reason"],
        "grounding_status": str(grounding_status or candidate.get("grounding_status") or ""),
        "locality_status": str(candidate.get("locality_status") or ""),
        "actionability_status": "actionable"
        if review["reviewability_status"] == VISUAL_EVIDENCE_REVIEWABLE_STATUS
        else VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY,
        "candidate_state": _candidate_state(
            {
                **candidate,
                "grounding_status": str(
                    grounding_status or candidate.get("grounding_status") or ""
                ),
                "reviewability_status": review["reviewability_status"],
            }
        ),
        "private_truth_included": False,
    }
    if candidate.get("visual_grounding_overlay"):
        evidence["visual_grounding_overlay"] = str(candidate["visual_grounding_overlay"])
    if pipeline:
        evidence["visual_grounding_pipeline_id"] = str(pipeline.get("pipeline_id") or "")
        evidence["visual_grounding_pipeline_status"] = str(pipeline.get("status") or "")
    if assert_no_forbidden_agent_view_keys is not None:
        assert_no_forbidden_agent_view_keys(evidence)
    return evidence


def _candidate_inputs_from_visual_grounding_response(
    response: dict[str, Any],
    *,
    raw_observation: dict[str, Any],
    visual_grounding_pipeline: dict[str, Any],
    artifact_base_dir: Path | None,
    resolve_destination_fixture_id: Callable[..., str],
) -> list[dict[str, Any]]:
    image = image_payload_for_raw_observation(
        raw_observation,
        base_dir=artifact_base_dir,
    )
    candidates = []
    for index, candidate in enumerate(response.get("candidates") or [], start=1):
        category = str(candidate.get("category") or "object")
        source_fixture_id = str(candidate.get("source_fixture_id") or "")
        target_fixture_id = resolve_destination_fixture_id(
            category=category,
            source_fixture_id=source_fixture_id,
        )
        overlay_path = _visual_grounding_overlay_for_candidate(
            raw_observation=raw_observation,
            candidate=candidate,
            index=index,
            artifact_base_dir=artifact_base_dir,
        )
        evidence_note = str(candidate.get("evidence_note") or "").strip()
        if not evidence_note:
            evidence_note = (
                "external visual grounding service proposed a public "
                f"{category} candidate from the agent-facing FPV frame"
            )
        candidates.append(
            {
                "category": category,
                "source_fixture_id": source_fixture_id,
                "target_fixture_id": target_fixture_id,
                "evidence_note": evidence_note,
                "image_region": candidate.get("image_region"),
                "confidence": candidate.get("confidence"),
                "producer_type": EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
                "producer_id": visual_grounding_pipeline.get("pipeline_id", ""),
                "visual_grounding_pipeline": visual_grounding_pipeline,
                "visual_grounding_stage_provenance": list(
                    visual_grounding_pipeline.get("stages") or []
                ),
                "visual_grounding_destination_hint": candidate.get("destination_hint") or {},
                "tracking": candidate.get("tracking") or {},
                "image_dimensions": {
                    "width": image.get("width", 0),
                    "height": image.get("height", 0),
                },
                "visual_grounding_overlay": overlay_path,
            }
        )
    return candidates


def _visual_grounding_overlay_for_candidate(
    *,
    raw_observation: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
    artifact_base_dir: Path | None,
) -> str:
    if artifact_base_dir is None:
        return ""
    region = candidate.get("image_region") or {}
    if region.get("type") != "bbox":
        return ""
    source_path = _raw_fpv_artifact_path(raw_observation, base_dir=artifact_base_dir)
    if source_path is None or not source_path.is_file():
        return ""
    observation_id = _safe_artifact_id(str(raw_observation.get("observation_id") or "raw_fpv"))
    rel_path = Path("visual_grounding") / "overlays" / observation_id / f"candidate_{index:03d}.jpg"
    output_path = artifact_base_dir / rel_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw

        with Image.open(source_path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        x, y, width, height = _normalized_bbox_pixels(
            region.get("value") or [0, 0, 0, 0],
            width=int(image.width),
            height=int(image.height),
        )
        draw.rectangle((x, y, x + width, y + height), outline=(26, 115, 232), width=3)
        label = str(candidate.get("category") or "candidate")
        draw.text((x + 4, max(0, y - 14)), label, fill=(26, 77, 160))
        image.save(output_path, format="JPEG", quality=80)
    except Exception:
        return ""
    return str(rel_path)


def _public_map_hints_for_visual_grounding_request(
    static_fixture_projection: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    for room in static_fixture_projection.get("rooms") or []:
        room_id = str(room.get("room_id") or "")
        for fixture in room.get("fixtures") or []:
            rows.append(
                {
                    "fixture_id": str(fixture.get("fixture_id") or ""),
                    "room_id": str(fixture.get("room_id") or room_id),
                    "category": str(fixture.get("category") or ""),
                    "name": str(fixture.get("name") or ""),
                    "affordances": list(fixture.get("affordances") or []),
                }
            )
    return {
        "schema": "visual_grounding_public_map_hints_v1",
        "source": "public_agent_view_map_evidence",
        "fixture_hints": rows,
        "private_truth_included": False,
    }


def _model_declared_observation_event(
    *,
    raw_observation: dict[str, Any],
    perception_mode: str,
    producer_type: str,
    producer_id: str,
    declared: list[dict[str, Any]],
    visual_grounding_pipeline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": MODEL_DECLARED_OBSERVATIONS_SCHEMA,
        "perception_mode": perception_mode,
        "observation_id": str(raw_observation["observation_id"]),
        "waypoint_id": str(raw_observation["waypoint_id"]),
        "room_id": str(raw_observation["room_id"]),
        "producer_type": producer_type,
        "producer_id": producer_id,
        "candidate_count": len(declared),
        "registered_observed_handles": [str(item["object_id"]) for item in declared],
        "visual_grounding_pipeline": visual_grounding_pipeline,
        "private_truth_included": False,
        "policy_note": (
            "Model-declared observations are derived from public camera evidence "
            "and public fixture metadata; private scoring truth is not exposed."
        ),
    }


def _bbox_reviewability(
    value: Any,
    *,
    image_dimensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    numbers = _numeric_bbox(value)
    if numbers is None:
        return {
            "reviewability_status": VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS,
            "reviewability_reason": "missing_bbox",
            "bbox_coordinate_space": "",
            "image_bbox": [],
        }
    x, y, width, height = numbers
    if width <= 0 or height <= 0:
        return {
            "reviewability_status": VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS,
            "reviewability_reason": "non_positive_bbox_extent",
            "bbox_coordinate_space": "",
            "image_bbox": numbers,
        }
    if x < 0 or y < 0:
        return {
            "reviewability_status": VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS,
            "reviewability_reason": "bbox_origin_outside_frame",
            "bbox_coordinate_space": "",
            "image_bbox": numbers,
        }
    if all(0.0 <= item <= 1.0 for item in numbers):
        if x + width <= 1.0 and y + height <= 1.0:
            return {
                "reviewability_status": VISUAL_EVIDENCE_REVIEWABLE_STATUS,
                "reviewability_reason": "normalized_bbox_inside_agent_fpv",
                "bbox_coordinate_space": "normalized_xywh",
                "image_bbox": numbers,
            }
        return {
            "reviewability_status": VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS,
            "reviewability_reason": "normalized_bbox_outside_frame",
            "bbox_coordinate_space": "normalized_xywh",
            "image_bbox": numbers,
        }
    dimensions = image_dimensions or {}
    frame_width = _positive_int(dimensions.get("width"))
    frame_height = _positive_int(dimensions.get("height"))
    if frame_width is not None and frame_height is not None:
        if x >= frame_width or y >= frame_height:
            return {
                "reviewability_status": VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS,
                "reviewability_reason": "pixel_bbox_outside_frame",
                "bbox_coordinate_space": "pixel_xywh",
                "image_bbox": numbers,
            }
    return {
        "reviewability_status": VISUAL_EVIDENCE_REVIEWABLE_STATUS,
        "reviewability_reason": "pixel_bbox_present_on_agent_fpv",
        "bbox_coordinate_space": "pixel_xywh",
        "image_bbox": numbers,
    }


def _numeric_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    numbers = [_float_or_none(item) for item in value]
    if any(number is None or not math.isfinite(number) for number in numbers):
        return None
    return [round(float(number), 6) for number in numbers if number is not None]


def _candidate_actionability_status(
    candidate: dict[str, Any],
    *,
    visual_grounding_evidence_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> str:
    declaration = candidate.get("model_declared_observation") or {}
    existing = str(
        candidate.get("actionability_status") or declaration.get("actionability_status") or ""
    )
    if existing == "already_handled":
        return existing
    grounding_status = str(
        candidate.get("grounding_status") or declaration.get("grounding_status") or "resolved"
    )
    if grounding_status in {"ambiguous", "unresolved"}:
        return "needs_clarification"
    evidence = candidate.get("visual_grounding_evidence")
    if not isinstance(evidence, dict) or not evidence:
        if visual_grounding_evidence_builder is not None:
            evidence = visual_grounding_evidence_builder(candidate)
        else:
            evidence = _visual_grounding_evidence_for_candidate(candidate)
    if evidence.get("reviewability_status") != VISUAL_EVIDENCE_REVIEWABLE_STATUS:
        return VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY
    if existing and existing != VISUAL_EVIDENCE_REQUIRED_ACTIONABILITY:
        return existing
    return "actionable"


def _candidate_state(candidate: dict[str, Any]) -> str:
    declaration = candidate.get("model_declared_observation") or {}
    existing = str(candidate.get("candidate_state") or declaration.get("candidate_state") or "")
    if existing == "already_handled":
        return existing
    actionability_status = str(
        candidate.get("actionability_status") or declaration.get("actionability_status") or ""
    )
    if actionability_status == "already_handled":
        return "already_handled"
    if existing == CANDIDATE_STATE_VISUAL_SCAN_REQUIRED:
        return existing
    grounding_status = str(
        candidate.get("grounding_status") or declaration.get("grounding_status") or "resolved"
    )
    if grounding_status in {"ambiguous", "unresolved"}:
        return CANDIDATE_STATE_SEMANTIC
    evidence = candidate.get("visual_grounding_evidence")
    reviewability_status = (
        str(evidence.get("reviewability_status") or "")
        if isinstance(evidence, dict)
        else str(candidate.get("reviewability_status") or "")
    )
    if reviewability_status != VISUAL_EVIDENCE_REVIEWABLE_STATUS:
        return CANDIDATE_STATE_VISUAL_SCAN_REQUIRED
    if candidate.get("cleanup_recommended") is False:
        return CANDIDATE_STATE_VISUALLY_CONFIRMED
    if existing == CANDIDATE_STATE_NAVIGATION_AUTHORIZED:
        return existing
    cleanup_recommended = bool(candidate.get("cleanup_recommended"))
    if cleanup_recommended:
        return CANDIDATE_STATE_NAVIGATION_AUTHORIZED
    return CANDIDATE_STATE_VISUALLY_CONFIRMED


def _candidate_state_history(candidate_state: str) -> list[str]:
    state = str(candidate_state or "")
    ordered = [
        CANDIDATE_STATE_SEMANTIC,
        CANDIDATE_STATE_VISUAL_SCAN_REQUIRED,
        CANDIDATE_STATE_VISUALLY_CONFIRMED,
        CANDIDATE_STATE_NAVIGATION_AUTHORIZED,
    ]
    if state in ordered:
        return ordered[: ordered.index(state) + 1]
    if state == "already_handled":
        return ordered + ["already_handled"]
    return [CANDIDATE_STATE_SEMANTIC]


def _required_tool_for_candidate_state(candidate_state: str) -> str:
    if candidate_state == CANDIDATE_STATE_NAVIGATION_AUTHORIZED:
        return "navigate_to_object"
    if candidate_state == CANDIDATE_STATE_VISUALLY_CONFIRMED:
        return "navigate_to_object"
    if candidate_state == CANDIDATE_STATE_VISUAL_SCAN_REQUIRED:
        return "adjust_camera"
    return "observe"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    number = _float_or_none(value)
    return number if number is not None else 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_image_region(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        region_type = str(value.get("type") or "verbal_region")
        raw_region_value = value.get("value")
    else:
        region_type = "verbal_region"
        raw_region_value = str(value or "unspecified")
    if region_type == "bbox" and isinstance(raw_region_value, (list, tuple)):
        numbers = [_float_or_none(item) for item in raw_region_value[:4]]
        if len(numbers) == 4 and all(number is not None for number in numbers):
            return {"type": "bbox", "value": numbers}
    if region_type == "point" and isinstance(raw_region_value, (list, tuple)):
        numbers = [_float_or_none(item) for item in raw_region_value[:2]]
        if len(numbers) == 2 and all(number is not None for number in numbers):
            return {"type": "point", "value": numbers}
    return {"type": "verbal_region", "value": str(raw_region_value or "unspecified")}


def _manual_visual_grounding_pipeline(
    *,
    candidate_count: int,
    producer_type: str,
    producer_id: str,
) -> dict[str, Any]:
    if producer_type == SIMULATED_CAMERA_MODEL_PROVENANCE:
        return sim_visual_grounding_pipeline(candidate_count=candidate_count)
    return {
        "schema": "visual_grounding_pipeline_v1",
        "pipeline_id": "manual",
        "status": "ok",
        "stages": [
            {
                "stage": "manual_declaration",
                "producer_id": producer_id,
                "model_id": producer_type,
                "status": "ok",
                "latency_ms": 0,
            }
        ],
        "candidate_count": candidate_count,
        "unresolved_count": 0,
        "duplicate_rate": 0.0,
    }


def _average_duplicate_rate(events: list[dict[str, Any]]) -> float:
    rates = []
    for item in events:
        pipeline = item.get("visual_grounding_pipeline") or {}
        rate = _float_or_none(pipeline.get("duplicate_rate"))
        if rate is not None:
            rates.append(rate)
    if not rates:
        return 0.0
    return round(sum(rates) / len(rates), 6)


def _visual_candidate_validation_error(
    candidate: Any,
    *,
    require_target_fixture_id: bool = True,
    perception_mode: str = "visible_object_detections",
    producer_type: str = "",
) -> dict[str, str] | None:
    if not isinstance(candidate, dict):
        return {"field": "candidate", "reason": "candidate must be an object"}
    for field in ("category", "evidence_note"):
        if not str(candidate.get(field) or "").strip():
            return {"field": field, "reason": f"{field} is required"}
    target_fixture_id = str(candidate.get("target_fixture_id") or "").strip()
    if (
        require_target_fixture_id
        and str(candidate.get("producer_type") or "") != EXTERNAL_VISUAL_GROUNDING_PROVENANCE
        and not target_fixture_id
    ):
        return {"field": "target_fixture_id", "reason": "target_fixture_id is required"}
    region_error = _image_region_validation_error(candidate.get("image_region"))
    if region_error is not None:
        return region_error
    if (
        perception_mode == "raw_fpv_only"
        and str(producer_type or "") == MAIN_CLEANUP_AGENT_PRODUCER
        and target_fixture_id
    ):
        return {
            "field": "target_fixture_id",
            "reason": (
                "target_fixture_id must be omitted in Base Metric Map RAW_FPV; use the "
                "candidate_fixture_id returned by navigate_to_visual_candidate"
            ),
        }
    return None


def _image_region_validation_error(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        if str(value or "").strip():
            return None
        return {"field": "image_region", "reason": "image_region is required"}
    region_type = str(value.get("type") or "")
    raw_region_value = value.get("value")
    if region_type not in {"bbox", "point", "verbal_region"}:
        return {
            "field": "image_region.type",
            "reason": "image_region.type must be bbox, point, or verbal_region",
        }
    if region_type == "verbal_region":
        if str(raw_region_value or "").strip():
            return None
        return {"field": "image_region.value", "reason": "verbal_region value is required"}
    if not isinstance(raw_region_value, (list, tuple)):
        return {"field": "image_region.value", "reason": f"{region_type} value must be a list"}
    expected = 4 if region_type == "bbox" else 2
    if len(raw_region_value) != expected:
        return {
            "field": "image_region.value",
            "reason": f"{region_type} value must contain {expected} numbers",
        }
    if any(_float_or_none(item) is None for item in raw_region_value):
        return {"field": "image_region.value", "reason": f"{region_type} values must be numbers"}
    return None


def _grounding_confidence(candidate: dict[str, Any], status: str) -> float:
    base = candidate.get("confidence")
    try:
        score = float(base) if base is not None else 0.72
    except (TypeError, ValueError):
        score = 0.72
    region = candidate.get("image_region") or {}
    if region.get("type") == "verbal_region":
        score -= 0.12
    if status == "ambiguous":
        score -= 0.24
    elif status == "unresolved":
        score -= 0.38
    return round(_clamp(score, 0.05, 0.99), 3)


def _declared_category_matches_object(category_norm: str, obj: Any) -> bool:
    return _declared_category_match_rank(category_norm, obj) > 0


def _declared_category_match_rank(category_norm: str, obj: Any) -> int:
    object_norm = _norm(f"{getattr(obj, 'category', '')} {getattr(obj, 'name', '')}")
    if not category_norm or category_norm in object_norm or object_norm in category_norm:
        return 2
    if any(
        category_norm in group and any(alias in object_norm for alias in group)
        for group in _EXACT_VISUAL_SYNONYM_GROUPS
    ):
        return 2
    if category_norm in _EXACT_VISUAL_CATEGORY_ALIASES:
        return 0
    declared_families = _category_alias_families(category_norm)
    object_families = _category_alias_families(object_norm)
    return 1 if declared_families.intersection(object_families) else 0


def _category_alias_family(text_norm: str) -> str:
    families = _category_alias_families(text_norm)
    return next(iter(families), "")


def _category_alias_families(text_norm: str) -> set[str]:
    families = set()
    for aliases, _targets in _OBJECT_CATEGORY_TARGETS:
        for alias in aliases:
            alias_norm = _norm(alias)
            if alias_norm and (alias_norm in text_norm or text_norm in alias_norm):
                families.add(aliases[0])
    return families


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _raw_fpv_artifact_path(
    raw_observation: dict[str, Any],
    *,
    base_dir: Path,
) -> Path | None:
    image_artifacts = raw_observation.get("image_artifacts") or {}
    value = image_artifacts.get("fpv") or raw_observation.get("fpv_image")
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else base_dir / path


def _normalized_bbox_pixels(value: Any, *, width: int, height: int) -> tuple[int, int, int, int]:
    numbers = [float(item) for item in value]
    return (
        round(numbers[0] * width),
        round(numbers[1] * height),
        round(numbers[2] * width),
        round(numbers[3] * height),
    )


def _safe_artifact_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return cleaned or "artifact"
