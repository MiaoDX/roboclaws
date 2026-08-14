from __future__ import annotations

import tempfile
from typing import Any

from PIL import Image

from roboclaws.household.visual_grounding_sidecar.adapter_runtime import (
    _clamp_float,
    _float_at,
    _float_env_optional,
    _float_or_none,
    _float_setting,
    _int_env,
    _norm,
    _runtime_bool_param,
    _runtime_float_param,
    _runtime_int_param,
)


def _grounding_dino_candidates_from_result(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    result: dict[str, Any],
    category_hints: list[str],
) -> list[dict[str, Any]]:
    boxes = _rows(result.get("boxes"))
    scores = _vector(result.get("scores"))
    labels = _vector(result.get("text_labels") or result.get("labels"))
    candidates: list[dict[str, Any]] = []
    for index, box in enumerate(boxes):
        confidence = _float_at(scores, index, default=0.0)
        category = _category_from_model_label(
            _value_at(labels, index, default=""),
            category_hints,
        )
        candidate = _candidate_from_xyxy(
            payload=payload,
            image=image,
            category=category,
            xyxy=box,
            confidence=confidence,
            evidence_note=f"Grounding DINO detected {category} from RAW_FPV pixels",
        )
        if candidate is not None:
            candidates.append(candidate)
    return _top_candidates(candidates)


def _omdet_candidates_from_result(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    result: dict[str, Any],
    category_hints: list[str],
) -> list[dict[str, Any]]:
    boxes = _rows(result.get("boxes"))
    scores = _vector(result.get("scores"))
    labels = _vector(result.get("text_labels") or result.get("labels"))
    candidates: list[dict[str, Any]] = []
    for index, box in enumerate(boxes):
        category = _category_from_model_label(
            _value_at(labels, index, default=""),
            category_hints,
        )
        candidate = _candidate_from_xyxy(
            payload=payload,
            image=image,
            category=category,
            xyxy=box,
            confidence=_float_at(scores, index, default=0.0),
            evidence_note=f"OmDet-Turbo detected {category} from RAW_FPV pixels",
        )
        if candidate is not None:
            candidates.append(candidate)
    return _top_candidates(candidates)


def _yolo_candidates_from_model(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    model: Any,
    category_hints: list[str],
    predict_kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    results = _run_yolo_prediction(
        image=image,
        model=model,
        predict_kwargs=predict_kwargs,
    )
    candidates: list[dict[str, Any]] = []
    for result in results or []:
        candidates.extend(
            _yolo_candidates_from_result(
                payload=payload,
                image=image,
                result=result,
                category_hints=category_hints,
            )
        )
    return _top_candidates(candidates)


def _yolo_predict_kwargs(runtime_parameters: dict[str, Any]) -> dict[str, Any]:
    threshold = _runtime_float_param(
        runtime_parameters,
        "confidence_threshold",
        env_name="VISUAL_GROUNDING_YOLO_CONFIDENCE_THRESHOLD",
        default=0.25,
        minimum=0.0,
        maximum=1.0,
    )
    predict_kwargs: dict[str, Any] = {
        "conf": threshold,
        "verbose": False,
    }
    imgsz = _runtime_int_param(
        runtime_parameters,
        "image_size",
        env_name="VISUAL_GROUNDING_YOLO_IMAGE_SIZE",
        minimum=1,
    )
    if imgsz is not None:
        predict_kwargs["imgsz"] = imgsz
    iou_value = runtime_parameters.get("iou_threshold")
    iou = _float_env_optional(
        "VISUAL_GROUNDING_YOLO_IOU_THRESHOLD",
        minimum=0.0,
        maximum=1.0,
    )
    if iou_value is not None:
        iou = _float_setting(
            iou_value,
            "runtime_parameters.iou_threshold",
            minimum=0.0,
            maximum=1.0,
        )
    if iou is not None:
        predict_kwargs["iou"] = iou
    max_det = _runtime_int_param(
        runtime_parameters,
        "max_detections",
        env_name="VISUAL_GROUNDING_YOLO_MAX_DET",
        minimum=1,
    )
    if max_det is not None:
        predict_kwargs["max_det"] = max_det
    agnostic_nms = _runtime_bool_param(
        runtime_parameters,
        "agnostic_nms",
        env_name="VISUAL_GROUNDING_YOLO_AGNOSTIC_NMS",
    )
    if agnostic_nms is not None:
        predict_kwargs["agnostic_nms"] = agnostic_nms
    augment = _runtime_bool_param(
        runtime_parameters,
        "augment",
        env_name="VISUAL_GROUNDING_YOLO_AUGMENT",
    )
    if augment is not None:
        predict_kwargs["augment"] = augment
    retina_masks = _runtime_bool_param(
        runtime_parameters,
        "retina_masks",
        env_name="VISUAL_GROUNDING_YOLO_RETINA_MASKS",
    )
    if retina_masks is not None:
        predict_kwargs["retina_masks"] = retina_masks
    return predict_kwargs


def _run_yolo_prediction(
    *,
    image: Image.Image,
    model: Any,
    predict_kwargs: dict[str, Any],
) -> Any:
    with tempfile.NamedTemporaryFile(suffix=".jpg") as temp_image:
        image.save(temp_image.name, format="JPEG", quality=90)
        if hasattr(model, "predict"):
            return model.predict(source=temp_image.name, **predict_kwargs)
        return model(temp_image.name)


def _yolo_candidates_from_result(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    result: Any,
    category_hints: list[str],
) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    rows = _rows(getattr(boxes, "xyxy", []))
    confidences = _vector(getattr(boxes, "conf", []))
    classes = _vector(getattr(boxes, "cls", []))
    names = getattr(result, "names", {}) or {}
    candidates: list[dict[str, Any]] = []
    for index, box in enumerate(rows):
        class_id = int(_float_at(classes, index, default=index))
        category = _category_from_yolo_class(
            class_id=class_id,
            names=names,
            category_hints=category_hints,
        )
        candidate = _candidate_from_xyxy(
            payload=payload,
            image=image,
            category=category,
            xyxy=box,
            confidence=_float_at(confidences, index, default=0.0),
            evidence_note=f"YOLOE detected {category} from RAW_FPV pixels",
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _yolo_prompt_labels(
    category_hints: list[str],
    *,
    runtime_parameters: dict[str, Any] | None = None,
) -> list[str]:
    runtime_parameters = runtime_parameters or {}
    expand = _runtime_bool_param(
        runtime_parameters,
        "prompt_expansion",
        env_name="VISUAL_GROUNDING_YOLO_EXPAND_CLEANUP_HINTS",
        default=True,
    )
    if not expand:
        return category_hints
    expansions = {
        "dish": ("dish", "plate", "bowl", "cup", "mug", "utensil"),
        "food": ("food", "apple", "potato", "bread", "fruit", "vegetable"),
        "book": ("book", "paper", "magazine", "newspaper"),
        "linen": ("linen", "towel", "cloth", "blanket"),
        "toy": ("toy", "ball", "plush toy", "teddy bear"),
        "electronics": ("electronics", "remote control", "remote", "phone"),
        "pillow": ("pillow", "cushion"),
    }
    labels: list[str] = []
    seen: set[str] = set()
    for hint in category_hints:
        for label in expansions.get(_norm(hint), (hint,)):
            key = _norm(label)
            if not key or key in seen:
                continue
            seen.add(key)
            labels.append(label)
    return labels


def _candidate_from_xyxy(
    *,
    payload: dict[str, Any],
    image: Image.Image,
    category: str,
    xyxy: Any,
    confidence: float,
    evidence_note: str,
) -> dict[str, Any] | None:
    bbox = _normalized_xyxy_to_xywh(xyxy, width=image.width, height=image.height)
    if bbox is None:
        return None
    return {
        "category": category or "object",
        "image_region": {"type": "bbox", "value": bbox},
        "confidence": _clamp_float(confidence, 0.0, 1.0),
        "evidence_note": evidence_note,
        "source_fixture_id": "",
        "destination_hint": _destination_hint(payload, category),
    }


def _normalized_xyxy_to_xywh(
    value: Any,
    *,
    width: int,
    height: int,
) -> list[float] | None:
    numbers = [_float_or_none(item) for item in _vector(value)[:4]]
    if len(numbers) != 4 or any(item is None for item in numbers):
        return None
    x1, y1, x2, y2 = [float(item) for item in numbers]
    x1, x2 = sorted((_clamp_float(x1, 0.0, float(width)), _clamp_float(x2, 0.0, float(width))))
    y1, y2 = sorted(
        (
            _clamp_float(y1, 0.0, float(height)),
            _clamp_float(y2, 0.0, float(height)),
        )
    )
    box_width = max(0.0, x2 - x1)
    box_height = max(0.0, y2 - y1)
    if box_width <= 0.0 or box_height <= 0.0 or width <= 0 or height <= 0:
        return None
    return [
        round(x1 / width, 6),
        round(y1 / height, 6),
        round(box_width / width, 6),
        round(box_height / height, 6),
    ]


def _destination_hint(payload: dict[str, Any], category: str) -> dict[str, Any]:
    preferences = _destination_preferences(category)
    if not preferences:
        return {}
    public_map_hints = payload.get("public_map_hints") or {}
    for fixture in public_map_hints.get("fixture_hints") or []:
        searchable = " ".join(
            [
                str(fixture.get("fixture_id") or ""),
                str(fixture.get("category") or ""),
                str(fixture.get("name") or ""),
                " ".join(str(item) for item in fixture.get("affordances") or []),
            ]
        ).lower()
        if any(preference in searchable for preference in preferences):
            return {
                "candidate_fixture_id": str(fixture.get("fixture_id") or ""),
                "confidence": 0.45,
                "basis": "sidecar_public_fixture_affordance_hint",
            }
    return {}


def _destination_preferences(category: str) -> tuple[str, ...]:
    category_norm = _norm(category)
    if category_norm in {"dish", "cup", "mug", "plate", "bowl", "utensil"}:
        return ("sink", "countertop")
    if category_norm in {"food", "apple", "bread", "potato", "fruit", "vegetable"}:
        return ("fridge", "refrigerator")
    if category_norm in {"book", "paper", "magazine", "newspaper"}:
        return ("shelf", "bookshelf", "desk")
    if category_norm in {"linen", "towel", "cloth", "blanket", "clothing"}:
        return ("hamper", "laundry")
    if category_norm in {"toy", "ball", "plush", "teddy"}:
        return ("toy", "bin", "shelf")
    if category_norm in {"remotecontrol", "remote", "electronics", "phone"}:
        return ("tv", "stand", "desk")
    if category_norm in {"pillow", "cushion"}:
        return ("bed", "sofa")
    return ()


def _category_from_model_label(raw_label: Any, category_hints: list[str]) -> str:
    if isinstance(raw_label, (int, float)):
        index = int(raw_label)
        if 0 <= index < len(category_hints):
            return category_hints[index]
    label = str(raw_label or "").strip()
    if not label:
        return category_hints[0] if category_hints else "object"
    label_norm = _norm(label.removeprefix("a ").removeprefix("an "))
    for hint in category_hints:
        hint_norm = _norm(hint)
        if hint_norm and (hint_norm == label_norm or hint_norm in label_norm):
            return hint
    return label.replace("a ", "", 1).replace("an ", "", 1) or "object"


def _category_from_yolo_class(
    *,
    class_id: int,
    names: Any,
    category_hints: list[str],
) -> str:
    if isinstance(names, dict) and class_id in names:
        return str(names[class_id])
    if isinstance(names, list) and 0 <= class_id < len(names):
        return str(names[class_id])
    if 0 <= class_id < len(category_hints):
        return category_hints[class_id]
    return category_hints[0] if category_hints else "object"


def _top_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_candidates = _int_env(
        "VISUAL_GROUNDING_MAX_CANDIDATES",
        8,
        minimum=1,
    )
    return sorted(
        candidates,
        key=lambda item: -float(item.get("confidence") or 0.0),
    )[:max_candidates]


def _rows(value: Any) -> list[list[Any]]:
    raw = _as_list(value)
    if not raw:
        return []
    if isinstance(raw[0], (list, tuple)):
        return [list(item) for item in raw]
    return [raw]


def _vector(value: Any) -> list[Any]:
    raw = _as_list(value)
    if raw and isinstance(raw[0], (list, tuple)):
        return [item[0] if item else None for item in raw]
    return raw


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return value
    return [value]


def _value_at(values: list[Any], index: int, *, default: Any) -> Any:
    return values[index] if index < len(values) else default
