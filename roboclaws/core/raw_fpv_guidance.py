"""Canonical RAW_FPV visual-candidate guidance policy."""

from __future__ import annotations

from typing import Any

RAW_FPV_DECLARATION_STRATEGY = "inline_on_navigate"
RAW_FPV_CATEGORY_HINT = "food, dish, book, linen, toy, electronics, or pillow"
RAW_FPV_PUBLIC_CLEANUP_PRIORITY_EXAMPLES = (
    ("dish", "bed"),
    ("dish", "desk"),
    ("food", "bed"),
    ("food", "desk"),
    ("book", "bed"),
    ("book", "sofa"),
    ("electronics", "bed"),
    ("electronics", "dining table"),
    ("pillow", "dining table"),
    ("linen", "desk"),
    ("toy", "bed"),
)
RAW_FPV_PUBLIC_SETTLED_EXAMPLES = (
    ("dish", "sink"),
    ("dish", "countertop"),
    ("dish", "dining table"),
    ("food", "fridge"),
    ("food", "countertop"),
    ("food", "dining table"),
    ("electronics", "TV stand"),
    ("electronics", "desk"),
    ("electronics", "sofa"),
    ("book", "shelf"),
    ("book", "desk"),
    ("pillow", "bed"),
)
RAW_FPV_HIGH_CONFIDENCE_TARGETS = (
    "objects whose visible current support is semantically questionable or wrong for that class",
    "obvious cases such as "
    + ", ".join(
        f"{category} on {support}" for category, support in RAW_FPV_PUBLIC_CLEANUP_PRIORITY_EXAMPLES
    ),
    "skip already settled distractors such as "
    + ", ".join(
        f"{category} on {support}" for category, support in RAW_FPV_PUBLIC_SETTLED_EXAMPLES
    ),
    "objects with most of the item inside the current FPV frame",
)
RAW_FPV_ACCEPTED_IMAGE_REGION_FORMS: tuple[dict[str, Any], ...] = (
    {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
    {"type": "point", "value": [390, 230]},
    {"type": "verbal_region", "value": "front of desk"},
)
RAW_FPV_INVALID_FIELDS_TO_AVOID: tuple[str, ...] = (
    "bbox_normalized",
    "bare x/y/width/height fields",
    'target_fixture_id=""',
    'target_fixture_id="None"',
    "target_fixture_id=null",
)


def raw_fpv_edge_reframe_instruction() -> str:
    return (
        "Do not declare or act from a tiny sliver. When a likely movable cleanup "
        "object is clipped at the left, right, bottom, or top FPV edge, or is partly "
        "occluded or overlapping so its bbox is not reviewable, reframe it at most "
        "once before continuing the sweep. Call adjust_camera then observe: for a "
        "left-edge candidate use yaw_delta_deg=45, for a right-edge candidate use "
        "yaw_delta_deg=-45, for a bottom-edge candidate use pitch_delta_deg=20, and "
        "for a top-edge candidate use pitch_delta_deg=-20. For overlap without a clear "
        "edge direction, make one bounded pitch probe with pitch_delta_deg=20; use "
        "-20 instead only when the candidate is above the frame center. Act only "
        "from the fresh observation and its new reviewable bbox. If the candidate "
        "becomes less visible or remains unreviewable, abandon it and continue the "
        "public waypoint sweep; never reuse the original sliver bbox."
    )


def raw_fpv_inline_candidate_instruction(observation_id: str | None = None) -> str:
    subject = (
        f"observation_id={observation_id}" if observation_id else "the current raw FPV observation"
    )
    return (
        f"Raw FPV-only mode uses {RAW_FPV_DECLARATION_STRATEGY}: inspect the FPV "
        f"image block for {subject}, do not batch-register candidates first, "
        "and call navigate_to_visual_candidate only when acting on one fresh, "
        "high-confidence cleanup object from that same source observation. "
        "Prioritize "
        + "; ".join(RAW_FPV_HIGH_CONFIDENCE_TARGETS)
        + ". Avoid permanent fixtures, built-in appliances, wall decor, tiny "
        "slivers, reflections, and regions already cleaned or already tried from "
        "the same source observation. Use the exact visual class when the image "
        "makes it clear (for example plate, cup, potato, remotecontrol, book, or "
        "pillow). Use broader cleanup categories such as "
        f"{RAW_FPV_CATEGORY_HINT} only when the exact object class is uncertain. "
        + raw_fpv_edge_reframe_instruction()
        + " "
        "Call navigate_to_visual_candidate with source_observation_id, category, "
        "evidence_note, and image_region before pick. With Base Metric Map "
        "context, omit target_fixture_id and normally omit source_fixture_id; "
        "do not invent fixture ids from stale map labels or guesses about the room. "
        "Use the candidate_fixture_id/recommended_tool returned by "
        "navigate_to_visual_candidate plus runtime_metric_map.public_semantic_anchors. "
        "When a destination is named or stale, resolve it through resolve_target_query "
        "or public runtime_metric_map target candidates. For any candidate you want to "
        "navigate to or pick, "
        "use image_region={type:bbox,value:[x,y,width,height]} from the same visible "
        "agent-facing FPV object. Verbal regions may clarify a bbox, but they do "
        "not count as an actionable cleanup chain without a reviewable bbox. If "
        "navigate_to_visual_candidate returns visual_candidate_not_resolved, do not "
        "keep retrying the same source_observation_id/category/region and do not call "
        "observe again at an unchanged pose. First move to a new waypoint, rotate the "
        "robot body, or adjust_camera once; then observe and retry only from the materially "
        "changed view with a fresh source_observation_id and tighter bbox. Never send "
        "bbox_normalized, "
        "bare x/y/width/height fields, "
        'target_fixture_id="", target_fixture_id="None", or target_fixture_id=null. '
        "After a successful pick/place for an observed handle, do not act on "
        "that same handle again; if grounding resolves to an already-handled "
        "object, continue the waypoint sweep."
    )


def raw_fpv_visual_candidate_recovery(
    *,
    source_observation_id: str | None = None,
) -> dict[str, Any]:
    example: dict[str, Any] = {
        "source_observation_id": source_observation_id or "<raw_fpv_observation_id>",
        "category": "toy",
        "evidence_note": "small object visible on the bed",
        "image_region": {"type": "bbox", "value": [0.1, 0.2, 0.3, 0.4]},
    }
    return {
        "schema": "raw_fpv_visual_candidate_recovery_v1",
        "required_tool": "navigate_to_visual_candidate",
        "required_next_action": "retry_navigate_to_visual_candidate",
        "declaration_strategy": RAW_FPV_DECLARATION_STRATEGY,
        "base_metric_map_target_fixture_rule": "omit_target_fixture_id",
        "accepted_image_region_forms": [dict(item) for item in RAW_FPV_ACCEPTED_IMAGE_REGION_FORMS],
        "invalid_fields_to_avoid": list(RAW_FPV_INVALID_FIELDS_TO_AVOID),
        "valid_example": example,
        "instruction": raw_fpv_inline_candidate_instruction(source_observation_id),
    }


def raw_fpv_visual_candidate_recovery_hint(
    *,
    source_observation_id: str | None = None,
) -> str:
    observation = source_observation_id or "<raw_fpv_observation_id>"
    return (
        "Retry with a valid navigate_to_visual_candidate example: "
        f"source_observation_id={observation}, category=toy, evidence_note='small object "
        "visible on the bed', image_region={type:bbox,value:[0.1,0.2,0.3,0.4]}; "
        "omit target_fixture_id with Base Metric Map context. Avoid bbox_normalized, "
        "bare x/y/width/height fields, "
        'target_fixture_id="", target_fixture_id="None", and target_fixture_id=null.'
    )
