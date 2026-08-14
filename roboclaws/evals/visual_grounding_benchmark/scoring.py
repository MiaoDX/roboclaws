from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

BBOX_MATCH_IOU_THRESHOLD = 0.3


@dataclass
class _CategoryMatch:
    matched_categories: list[str]
    matched_bbox_ious: list[float]

    @property
    def matched_count(self) -> int:
        return len(self.matched_categories)


@dataclass
class _DestinationSummary:
    hint_count: int = 0
    known_fixture_count: int = 0
    plausible_count: int = 0
    actionability_proxy_count: int = 0


@dataclass
class _PredictionScore:
    label_count: int
    candidate_count: int
    matched_label_count: int
    matched_candidate_count: int
    bbox_label_count: int
    bbox_candidate_count: int
    bbox_matched_label_count: int
    bbox_matched_candidate_count: int
    bbox_category_correct_count: int
    bbox_ious: list[float]
    duplicate_count: int
    rejected_proposal_count: int
    destination: _DestinationSummary
    private_label_detail: dict[str, Any]


@dataclass
class _ScoreTotals:
    label_count: int = 0
    candidate_count: int = 0
    matched_label_count: int = 0
    matched_candidate_count: int = 0
    bbox_label_count: int = 0
    bbox_candidate_count: int = 0
    bbox_matched_label_count: int = 0
    bbox_matched_candidate_count: int = 0
    bbox_category_correct_count: int = 0
    bbox_ious: list[float] = field(default_factory=list)
    duplicate_count: int = 0
    rejected_proposal_count: int = 0
    destination_hint_count: int = 0
    destination_hint_known_fixture_count: int = 0
    destination_hint_plausible_count: int = 0
    actionability_proxy_count: int = 0
    private_label_details: list[dict[str, Any]] = field(default_factory=list)

    def add(self, score: _PredictionScore) -> None:
        self.label_count += score.label_count
        self.candidate_count += score.candidate_count
        self.matched_label_count += score.matched_label_count
        self.matched_candidate_count += score.matched_candidate_count
        self.bbox_label_count += score.bbox_label_count
        self.bbox_candidate_count += score.bbox_candidate_count
        self.bbox_matched_label_count += score.bbox_matched_label_count
        self.bbox_matched_candidate_count += score.bbox_matched_candidate_count
        self.bbox_category_correct_count += score.bbox_category_correct_count
        self.bbox_ious.extend(score.bbox_ious)
        self.duplicate_count += score.duplicate_count
        self.rejected_proposal_count += score.rejected_proposal_count
        self.destination_hint_count += score.destination.hint_count
        self.destination_hint_known_fixture_count += score.destination.known_fixture_count
        self.destination_hint_plausible_count += score.destination.plausible_count
        self.actionability_proxy_count += score.destination.actionability_proxy_count
        self.private_label_details.append(score.private_label_detail)


def score_predictions(
    predictions: list[dict[str, Any]],
    observation_by_id: dict[str, dict[str, Any]],
    category_family_map: dict[str, str],
) -> dict[str, Any]:
    totals = _ScoreTotals()
    parse_failure_count = 0
    for prediction in predictions:
        if (prediction.get("pipeline") or {}).get("parse_failed"):
            parse_failure_count += 1
        observation = observation_by_id.get(str(prediction.get("observation_id") or ""), {})
        totals.add(
            _score_prediction(
                prediction=prediction,
                observation=observation,
                category_family_map=category_family_map,
            )
        )
    return {
        "metrics": _metrics_from_totals(totals, parse_failure_count, len(predictions)),
        "private_label_details": totals.private_label_details,
    }


def _score_prediction(
    *,
    prediction: dict[str, Any],
    observation: dict[str, Any],
    category_family_map: dict[str, str],
) -> _PredictionScore:
    static_fixture_projection = list(observation.get("static_fixture_projection") or [])
    labels = [
        _private_label(label, category_family_map)
        for label in observation.get("private_labels") or []
    ]
    candidates = list(prediction.get("candidates") or [])
    bbox_labels = [label for label in labels if label.get("bbox") is not None]
    category_match = _match_candidate_categories(
        labels=labels,
        candidates=candidates,
        category_family_map=category_family_map,
        collect_bbox_iou=not bbox_labels,
    )
    bbox_match = _match_bbox_labels(
        labels=bbox_labels,
        candidates=candidates,
        category_family_map=category_family_map,
        iou_threshold=BBOX_MATCH_IOU_THRESHOLD,
    )
    return _PredictionScore(
        label_count=len(labels),
        candidate_count=len(candidates),
        matched_label_count=category_match.matched_count,
        matched_candidate_count=category_match.matched_count,
        bbox_label_count=len(bbox_labels),
        bbox_candidate_count=sum(1 for candidate in candidates if candidate.get("bbox")),
        bbox_matched_label_count=int(bbox_match["matched_label_count"]),
        bbox_matched_candidate_count=int(bbox_match["matched_candidate_count"]),
        bbox_category_correct_count=int(bbox_match["category_correct_count"]),
        bbox_ious=[
            *category_match.matched_bbox_ious,
            *(float(value) for value in bbox_match["matched_ious"]),
        ],
        duplicate_count=_duplicate_count(candidates),
        rejected_proposal_count=int(
            ((prediction.get("diagnostic_evidence") or {}).get("rejected_proposal_count")) or 0
        ),
        destination=_destination_summary(candidates, static_fixture_projection),
        private_label_detail=_private_label_detail(
            prediction=prediction,
            labels=labels,
            matched_categories=category_match.matched_categories,
            bbox_labels=bbox_labels,
            bbox_matched_label_count=int(bbox_match["matched_label_count"]),
        ),
    )


def _match_candidate_categories(
    *,
    labels: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    category_family_map: dict[str, str],
    collect_bbox_iou: bool,
) -> _CategoryMatch:
    remaining = list(labels)
    matched_categories: list[str] = []
    matched_bbox_ious: list[float] = []
    for candidate in candidates:
        candidate_family = category_family(
            str(candidate.get("category") or ""),
            category_family_map,
        )
        match_index = next(
            (index for index, label in enumerate(remaining) if label["family"] == candidate_family),
            None,
        )
        if match_index is None:
            continue
        label = remaining.pop(match_index)
        matched_categories.append(candidate_family)
        iou = _bbox_iou(candidate.get("bbox"), label.get("bbox"))
        if collect_bbox_iou and iou is not None:
            matched_bbox_ious.append(iou)
    return _CategoryMatch(
        matched_categories=matched_categories,
        matched_bbox_ious=matched_bbox_ious,
    )


def _metrics_from_totals(
    totals: _ScoreTotals,
    parse_failure_count: int,
    prediction_count: int,
) -> dict[str, Any]:
    false_positive_count = max(0, totals.candidate_count - totals.matched_candidate_count)
    bbox_false_positive_count = max(
        0,
        totals.bbox_candidate_count - totals.bbox_matched_candidate_count,
    )
    return {
        "label_count": totals.label_count,
        "matched_label_count": totals.matched_label_count,
        "candidate_count": totals.candidate_count,
        "matched_candidate_count": totals.matched_candidate_count,
        "false_positive_count": false_positive_count,
        "recall": ratio(totals.matched_label_count, totals.label_count),
        "precision": ratio(totals.matched_candidate_count, totals.candidate_count),
        "category_family_accuracy": ratio(
            totals.matched_candidate_count,
            totals.candidate_count,
        ),
        "duplicate_count": totals.duplicate_count,
        "duplicate_rate": ratio(totals.duplicate_count, totals.candidate_count),
        "bbox_metrics_available": totals.bbox_label_count > 0,
        "bbox_iou_threshold": BBOX_MATCH_IOU_THRESHOLD,
        "bbox_label_count": totals.bbox_label_count,
        "bbox_candidate_count": totals.bbox_candidate_count,
        "bbox_matched_label_count": totals.bbox_matched_label_count,
        "bbox_matched_candidate_count": totals.bbox_matched_candidate_count,
        "bbox_false_positive_count": bbox_false_positive_count,
        "bbox_recall_at_iou": ratio(totals.bbox_matched_label_count, totals.bbox_label_count),
        "bbox_precision_at_iou": ratio(
            totals.bbox_matched_candidate_count,
            totals.bbox_candidate_count,
        ),
        "bbox_category_family_accuracy_at_iou": ratio(
            totals.bbox_category_correct_count,
            totals.bbox_matched_label_count,
        ),
        "bbox_false_positive_rate": ratio(
            bbox_false_positive_count,
            totals.bbox_candidate_count,
        ),
        "bbox_quality_available_count": len(totals.bbox_ious),
        "mean_bbox_iou": (
            round(sum(totals.bbox_ious) / len(totals.bbox_ious), 6) if totals.bbox_ious else None
        ),
        "bbox_quality_note": "overlay_review_required" if not totals.bbox_ious else "iou_available",
        "identity_stability_available": False,
        "identity_collision_rate": None,
        "rejected_proposal_count": totals.rejected_proposal_count,
        "cleanup_relevance_quality_available": totals.rejected_proposal_count > 0,
        "cleanup_relevance_reject_rate": ratio(
            totals.rejected_proposal_count,
            totals.rejected_proposal_count + totals.candidate_count,
        ),
        "destination_hint_count": totals.destination_hint_count,
        "destination_hint_rate": ratio(totals.destination_hint_count, totals.candidate_count),
        "destination_hint_known_fixture_count": totals.destination_hint_known_fixture_count,
        "destination_hint_known_fixture_rate": ratio(
            totals.destination_hint_known_fixture_count,
            totals.destination_hint_count,
        ),
        "destination_hint_plausible_count": totals.destination_hint_plausible_count,
        "destination_hint_plausible_rate": ratio(
            totals.destination_hint_plausible_count,
            totals.destination_hint_count,
        ),
        "actionability_proxy_count": totals.actionability_proxy_count,
        "actionability_proxy_rate": ratio(
            totals.actionability_proxy_count,
            totals.candidate_count,
        ),
        "structured_output_parse_failure_rate": ratio(parse_failure_count, prediction_count),
    }


def _private_label(label: dict[str, Any], category_family_map: dict[str, str]) -> dict[str, Any]:
    category = str(label.get("category") or "")
    family = str(label.get("category_family") or category_family(category, category_family_map))
    return {
        "category": category,
        "family": family,
        "bbox": label.get("bbox"),
        "visible": bool(label.get("visible", True)),
    }


def _private_label_detail(
    *,
    prediction: dict[str, Any],
    labels: list[dict[str, Any]],
    matched_categories: list[str],
    bbox_labels: list[dict[str, Any]],
    bbox_matched_label_count: int,
) -> dict[str, Any]:
    return {
        "observation_id": prediction.get("observation_id", ""),
        "private_category_families": [label["family"] for label in labels],
        "matched_category_families": matched_categories,
        "bbox_private_category_families": [label["family"] for label in bbox_labels],
        "bbox_matched_label_count": bbox_matched_label_count,
    }


def _match_bbox_labels(
    *,
    labels: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    category_family_map: dict[str, str],
    iou_threshold: float,
) -> dict[str, Any]:
    candidate_rows = _candidate_bbox_rows(candidates, category_family_map)
    possible_matches = _possible_bbox_matches(labels, candidate_rows, iou_threshold)

    matched_labels: set[int] = set()
    matched_candidates: set[int] = set()
    matched_ious: list[float] = []
    category_correct_count = 0
    for iou, label_index, candidate_index, category_correct in sorted(
        possible_matches,
        key=lambda item: (item[0], item[3]),
        reverse=True,
    ):
        if label_index in matched_labels or candidate_index in matched_candidates:
            continue
        matched_labels.add(label_index)
        matched_candidates.add(candidate_index)
        matched_ious.append(iou)
        if category_correct:
            category_correct_count += 1

    return {
        "matched_label_count": len(matched_labels),
        "matched_candidate_count": len(matched_candidates),
        "category_correct_count": category_correct_count,
        "matched_ious": matched_ious,
    }


def _candidate_bbox_rows(
    candidates: list[dict[str, Any]],
    category_family_map: dict[str, str],
) -> list[dict[str, Any]]:
    rows = []
    for index, candidate in enumerate(candidates):
        bbox = candidate.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        rows.append(
            {
                "index": index,
                "family": category_family(
                    str(candidate.get("category") or ""),
                    category_family_map,
                ),
                "bbox": bbox,
            }
        )
    return rows


def _possible_bbox_matches(
    labels: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    iou_threshold: float,
) -> list[tuple[float, int, int, bool]]:
    possible_matches: list[tuple[float, int, int, bool]] = []
    for label_index, label in enumerate(labels):
        if not label.get("visible", True):
            continue
        for candidate in candidate_rows:
            iou = _bbox_iou(candidate["bbox"], label.get("bbox"))
            if iou is None or iou < iou_threshold:
                continue
            category_correct = candidate["family"] == label["family"]
            possible_matches.append((iou, label_index, int(candidate["index"]), category_correct))
    return possible_matches


def category_family(category: str, category_family_map: dict[str, str]) -> str:
    return category_family_map.get(category, category)


def _bbox_iou(candidate_bbox: Any, label_bbox: Any) -> float | None:
    if not isinstance(candidate_bbox, list) or not isinstance(label_bbox, list):
        return None
    if len(candidate_bbox) != 4 or len(label_bbox) != 4:
        return None
    cx, cy, cw, ch = [float(item) for item in candidate_bbox]
    lx, ly, lw, lh = [float(item) for item in label_bbox]
    c2x, c2y = cx + cw, cy + ch
    l2x, l2y = lx + lw, ly + lh
    ix = max(0.0, min(c2x, l2x) - max(cx, lx))
    iy = max(0.0, min(c2y, l2y) - max(cy, ly))
    intersection = ix * iy
    union = (cw * ch) + (lw * lh) - intersection
    if union <= 0:
        return None
    return round(intersection / union, 6)


def _duplicate_count(candidates: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for candidate in candidates:
        key = (
            str(candidate.get("category") or ""),
            json.dumps(candidate.get("image_region") or {}, sort_keys=True),
        )
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _destination_summary(
    candidates: list[dict[str, Any]],
    static_fixture_projection: list[dict[str, Any]],
) -> _DestinationSummary:
    summary = _DestinationSummary()
    for candidate in candidates:
        hint_quality = _destination_hint_quality(candidate, static_fixture_projection)
        summary.hint_count += int(hint_quality["has_hint"])
        summary.known_fixture_count += int(hint_quality["known_fixture"])
        summary.plausible_count += int(hint_quality["plausible"])
        summary.actionability_proxy_count += int(hint_quality["actionable_proxy"])
    return summary


def _destination_hint_quality(
    candidate: dict[str, Any],
    static_fixture_projection: list[dict[str, Any]],
) -> dict[str, bool]:
    hint = candidate.get("destination_hint") or {}
    fixture_id = str(hint.get("candidate_fixture_id") or "")
    known_fixture = next(
        (
            fixture
            for fixture in static_fixture_projection
            if str(fixture.get("fixture_id") or "") == fixture_id
        ),
        None,
    )
    plausible = False
    if known_fixture is not None:
        fixture_text = _fixture_preference_text(known_fixture)
        preferences = _destination_preferences(str(candidate.get("category") or ""))
        plausible = not preferences or any(preference in fixture_text for preference in preferences)
    region = candidate.get("image_region") or {}
    return {
        "has_hint": bool(fixture_id),
        "known_fixture": known_fixture is not None,
        "plausible": plausible,
        "actionable_proxy": known_fixture is not None
        and plausible
        and region.get("type") in {"bbox", "point", "verbal_region"},
    }


def _fixture_preference_text(fixture: dict[str, Any]) -> str:
    return " ".join(
        [
            str(fixture.get("fixture_id") or ""),
            str(fixture.get("category") or ""),
            str(fixture.get("name") or ""),
            " ".join(str(item) for item in fixture.get("affordances") or []),
        ]
    ).lower()


def _destination_preferences(category: str) -> tuple[str, ...]:
    category_norm = "".join(ch for ch in str(category).lower() if ch.isalnum())
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


def ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)
