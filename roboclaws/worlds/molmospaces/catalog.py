"""Source selection data for the MolmoSpaces scene sampler."""

from __future__ import annotations

import hashlib
from typing import Any

CURRENT_CURATED_INDICES: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 7, 9)
SCENE_SAMPLER_SELECTION_SEED = "2026-06-16.source-diverse-selection-v1"
SCENE_SAMPLER_SELECTION_STRATEGY = (
    "deterministic_seeded_random_order_with_room_count_diversity_first"
)

SOURCE_UI_CANDIDATE_INDICES: dict[str, tuple[int, ...]] = {
    "procthor-10k-val": (0, 10, 11, 12, 13, 15),
    "procthor-objaverse-val": (0, 1, 4, 10),
}

SOURCE_EVAL_CANDIDATE_INDICES: dict[str, tuple[int, ...]] = {
    "procthor-10k-val": (0, 2, 3, 5, 9, 10, 11, 12, 13, 15),
    "procthor-objaverse-val": (0, 1, 4, 5, 7, 10, 11, 12, 13, 14),
}

SOURCE_SELECTION_ROOM_COUNTS: dict[str, dict[int, int]] = {
    "procthor-10k-val": {
        0: 7,
        2: 10,
        3: 5,
        5: 4,
        9: 10,
        10: 4,
        11: 4,
        12: 10,
        13: 4,
        15: 10,
    },
}

SCANNER_READY_METADATA: dict[str, dict[int, dict[str, Any]]] = {
    "procthor-10k-val": {
        10: {
            "room_count": 4,
            "waypoint_count": 8,
            "quality_score": 1.0,
            "coverage_score": 0.4,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-10k-val-10/0615_2303/seed-7"
            ),
        },
        11: {
            "room_count": 4,
            "waypoint_count": 8,
            "quality_score": 1.0,
            "coverage_score": 0.4,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-10k-val-11/0615_2303/seed-7"
            ),
        },
        12: {
            "room_count": 10,
            "waypoint_count": 20,
            "quality_score": 1.0,
            "coverage_score": 1.0,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-10k-val-12/0615_2304/seed-7"
            ),
        },
        13: {
            "room_count": 4,
            "waypoint_count": 8,
            "quality_score": 1.0,
            "coverage_score": 0.4,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-10k-val-13/0615_2306/seed-7"
            ),
        },
        15: {
            "room_count": 10,
            "waypoint_count": 20,
            "quality_score": 1.0,
            "coverage_score": 1.0,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-10k-val-15/0615_2308/seed-7"
            ),
        },
    },
    "procthor-objaverse-val": {
        0: {
            "room_count": 4,
            "waypoint_count": 8,
            "quality_score": 1.0,
            "coverage_score": 0.4,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-0/0615_2348/seed-7"
            ),
        },
        1: {
            "room_count": 7,
            "waypoint_count": 14,
            "quality_score": 1.0,
            "coverage_score": 0.7,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-1/0615_2348/seed-7"
            ),
        },
        4: {
            "room_count": 4,
            "waypoint_count": 8,
            "quality_score": 1.0,
            "coverage_score": 0.4,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-4/0615_2350/seed-7"
            ),
        },
        5: {
            "room_count": 7,
            "waypoint_count": 14,
            "quality_score": 1.0,
            "coverage_score": 0.7,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-5/0615_2350/seed-7"
            ),
        },
        7: {
            "room_count": 6,
            "waypoint_count": 12,
            "quality_score": 1.0,
            "coverage_score": 0.6,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-7/0615_2351/seed-7"
            ),
        },
        10: {
            "room_count": 5,
            "waypoint_count": 10,
            "quality_score": 1.0,
            "coverage_score": 0.5,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-10/0616_0003/seed-7"
            ),
        },
        11: {
            "room_count": 8,
            "waypoint_count": 16,
            "quality_score": 1.0,
            "coverage_score": 0.8,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-11/0616_0004/seed-7"
            ),
        },
        12: {
            "room_count": 6,
            "waypoint_count": 12,
            "quality_score": 1.0,
            "coverage_score": 0.6,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-12/0616_0004/seed-7"
            ),
        },
        13: {
            "room_count": 6,
            "waypoint_count": 12,
            "quality_score": 1.0,
            "coverage_score": 0.6,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-13/0616_0005/seed-7"
            ),
        },
        14: {
            "room_count": 6,
            "waypoint_count": 12,
            "quality_score": 1.0,
            "coverage_score": 0.6,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                "molmospaces-procthor-objaverse-val-14/0616_0006/seed-7"
            ),
        },
    },
}

_ITHOR_FEWER_NAVIGATION_AREA_REJECTED_INDICES = (
    *range(1, 13),
    201,
    202,
    203,
    204,
    205,
    206,
    207,
    208,
    209,
    210,
    211,
    212,
    301,
    302,
    303,
    304,
    305,
    306,
    307,
    308,
    309,
    310,
    311,
    312,
)

_ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES = (
    401,
    402,
    403,
    404,
    405,
    406,
    407,
    408,
    409,
    410,
    411,
    412,
)

_ITHOR_REJECTED_METADATA: dict[int, dict[str, Any]] = {
    index: {
        "room_count": 1,
        "waypoint_count": 2,
        "quality_score": 1.0,
        "coverage_score": 0.1,
        "blocked_reason": "fewer_than_three_public_navigation_areas",
    }
    for index in _ITHOR_FEWER_NAVIGATION_AREA_REJECTED_INDICES
} | {
    index: {
        "room_count": 0,
        "waypoint_count": 0,
        "quality_score": 0.0,
        "coverage_score": 0.0,
        "blocked_reason": "missing_public_inspection_waypoints",
        "failure_class": "environment_blocked",
    }
    for index in _ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
}

_HOLODECK_FEWER_NAVIGATION_AREA_REJECTED_INDICES = (
    *range(20),
    22,
    25,
    26,
    27,
    29,
    30,
    33,
    36,
    38,
    39,
    44,
    47,
    48,
    52,
    53,
    62,
    63,
    67,
    71,
    76,
    77,
    81,
    87,
    94,
    95,
    99,
    101,
    106,
    108,
    110,
    111,
    113,
    114,
    115,
    116,
    124,
    127,
    132,
    138,
    139,
    143,
    145,
    146,
    148,
    150,
    151,
    157,
    162,
    167,
    170,
    173,
    175,
    176,
    179,
    180,
    181,
    182,
    183,
    186,
    188,
    191,
    195,
    197,
    198,
    199,
    201,
    207,
    209,
    212,
    215,
    216,
    221,
    225,
    228,
    230,
    237,
    238,
    243,
    246,
    247,
    248,
    253,
    256,
    258,
    263,
    266,
    272,
    273,
    274,
    275,
    279,
    280,
    285,
    290,
    291,
    292,
    296,
    299,
    300,
    301,
    302,
    305,
    307,
    313,
    314,
    317,
    318,
    322,
    323,
    325,
    330,
    333,
    335,
    337,
    338,
    340,
    345,
    349,
    350,
    354,
    356,
    358,
    360,
    362,
    363,
    365,
    367,
    371,
    374,
    377,
    385,
    386,
    387,
    390,
    391,
    395,
    396,
    397,
    398,
    399,
    400,
    401,
    406,
    418,
    421,
    422,
    424,
    425,
    428,
    431,
    436,
    438,
    440,
    442,
    443,
    444,
    447,
    449,
    450,
    451,
    452,
    456,
    459,
    460,
    464,
    466,
    468,
    474,
    476,
    477,
    483,
    486,
    489,
)

_HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES = (107, 171, 268)
_HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES = (261, 381, 403)
_HOLODECK_PREFILTER_GATE_MISMATCH_INDICES = (231, 344)

_HOLODECK_REJECTED_METADATA: dict[int, dict[str, Any]] = (
    {
        index: {
            "room_count": 1,
            "waypoint_count": 2,
            "quality_score": 1.0,
            "coverage_score": 0.1,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
        }
        for index in _HOLODECK_FEWER_NAVIGATION_AREA_REJECTED_INDICES
    }
    | {
        index: {
            "room_count": 1,
            "waypoint_count": 2,
            "quality_score": 0.75,
            "coverage_score": 0.1,
            "blocked_reason": "preview_not_reviewable",
        }
        for index in _HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES
    }
    | {
        index: {
            "room_count": 0,
            "waypoint_count": 0,
            "quality_score": 0.0,
            "coverage_score": 0.0,
            "blocked_reason": "missing_public_inspection_waypoints",
            "failure_class": "environment_blocked",
        }
        for index in _HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    }
    | {
        index: {
            "room_count": 1,
            "waypoint_count": 2,
            "quality_score": 1.0,
            "coverage_score": 0.1,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
            "selected_reason": "prefilter_high_confidence_but_public_map_gate_failed",
            "source_outcome": "gate_mismatch",
            "prefilter_status": "high_confidence",
            "prefilter_reason": "likely_multi_area",
            "cheap_room_count": 6,
            "product_smoke_run_dir": (
                "output/scene-sampler-scanner/product-smoke/"
                f"molmospaces-holodeck-objaverse-val-{index}/0616_1844/seed-7"
            ),
        }
        for index in _HOLODECK_PREFILTER_GATE_MISMATCH_INDICES
    }
)

SCANNER_REJECTED_METADATA: dict[str, dict[int, dict[str, Any]]] = {
    "ithor": _ITHOR_REJECTED_METADATA,
    "holodeck-objaverse-val": _HOLODECK_REJECTED_METADATA,
    "procthor-objaverse-val": {
        2: {
            "room_count": 1,
            "waypoint_count": 2,
            "quality_score": 1.0,
            "coverage_score": 0.1,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
        },
        3: {
            "room_count": 2,
            "waypoint_count": 4,
            "quality_score": 1.0,
            "coverage_score": 0.2,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
        },
        6: {
            "room_count": 1,
            "waypoint_count": 2,
            "quality_score": 1.0,
            "coverage_score": 0.1,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
        },
        8: {
            "room_count": 2,
            "waypoint_count": 4,
            "quality_score": 1.0,
            "coverage_score": 0.2,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
        },
        9: {
            "room_count": 2,
            "waypoint_count": 4,
            "quality_score": 1.0,
            "coverage_score": 0.2,
            "blocked_reason": "fewer_than_three_public_navigation_areas",
        },
    },
}


def admitted_sources(*, supported_sources: tuple[str, ...]) -> tuple[str, ...]:
    admitted = (
        set(SOURCE_UI_CANDIDATE_INDICES)
        | set(SOURCE_EVAL_CANDIDATE_INDICES)
        | set(SCANNER_REJECTED_METADATA)
    )
    return tuple(source for source in supported_sources if source in admitted)


def known_indices_for_source(source: str) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                *source_ui_indices(source),
                *source_eval_indices(source),
                *SOURCE_UI_CANDIDATE_INDICES.get(source, ()),
                *SOURCE_EVAL_CANDIDATE_INDICES.get(source, ()),
                *SCANNER_REJECTED_METADATA.get(source, ()),
                *(CURRENT_CURATED_INDICES if source == "procthor-10k-val" else ()),
            }
        )
    )


def scanner_metadata(*, source: str, scene_index: int) -> dict[str, Any]:
    return (
        SCANNER_READY_METADATA.get(source, {}).get(scene_index)
        or SCANNER_REJECTED_METADATA.get(source, {}).get(scene_index)
        or {}
    )


def source_ui_indices(source: str) -> tuple[int, ...]:
    return _select_diverse_indices(
        source=source,
        lane="ui",
        candidates=SOURCE_UI_CANDIDATE_INDICES.get(source, ()),
        target_count=3,
    )


def source_eval_indices(source: str) -> tuple[int, ...]:
    return _select_diverse_indices(
        source=source,
        lane="eval_stress",
        candidates=SOURCE_EVAL_CANDIDATE_INDICES.get(source, ()),
        target_count=10,
    )


def source_selection_metadata(
    *,
    source: str,
    lane: str,
    target_count: int,
    candidates: tuple[int, ...],
) -> dict[str, Any]:
    selected = _select_diverse_indices(
        source=source,
        lane=lane,
        candidates=candidates,
        target_count=target_count,
    )
    candidate_room_counts = {
        str(index): _selection_room_count(source=source, scene_index=index) for index in candidates
    }
    return {
        "selection_seed": SCENE_SAMPLER_SELECTION_SEED,
        "selection_strategy": SCENE_SAMPLER_SELECTION_STRATEGY,
        "lane": lane,
        "target_count": target_count,
        "candidate_indices": list(candidates),
        "selected_indices": list(selected),
        "candidate_room_counts": candidate_room_counts,
        "selected_room_counts": [
            candidate_room_counts[str(index)]
            for index in selected
            if str(index) in candidate_room_counts
        ],
        "unique_selected_room_count": len(
            {
                candidate_room_counts[str(index)]
                for index in selected
                if candidate_room_counts.get(str(index), 0) > 0
            }
        ),
    }


def sampler_world_id(*, source: str, scene_index: int) -> str:
    return f"molmospaces/{source}/{scene_index}"


def category_provenance(source: str) -> str:
    if source in {"ithor", "procthor-objaverse-val", "holodeck-objaverse-val"}:
        return "source_metadata"
    return "prepared_visual_label_manifest"


def category_manifest(source: str, *, default_manifest: str) -> str:
    if source in {"ithor", "procthor-objaverse-val", "holodeck-objaverse-val"}:
        return ""
    return default_manifest


def uses_legacy_preview_assets(*, source: str, scene_index: int) -> bool:
    return source == "procthor-10k-val" and scene_index not in SCANNER_READY_METADATA.get(
        source, {}
    )


def _select_diverse_indices(
    *,
    source: str,
    lane: str,
    candidates: tuple[int, ...],
    target_count: int,
) -> tuple[int, ...]:
    seeded = sorted(
        candidates,
        key=lambda index: _selection_sort_key(source=source, lane=lane, scene_index=index),
    )
    selected: list[int] = []
    seen_room_counts: set[int] = set()
    for index in seeded:
        room_count = _selection_room_count(source=source, scene_index=index)
        if room_count <= 0 or room_count in seen_room_counts:
            continue
        selected.append(index)
        seen_room_counts.add(room_count)
        if len(selected) == target_count:
            return tuple(selected)
    for index in seeded:
        if index in selected:
            continue
        selected.append(index)
        if len(selected) == target_count:
            break
    return tuple(selected)


def _selection_sort_key(*, source: str, lane: str, scene_index: int) -> tuple[int, int]:
    digest = hashlib.sha256(
        f"{SCENE_SAMPLER_SELECTION_SEED}:{source}:{lane}:{scene_index}".encode("utf-8")
    ).hexdigest()
    return int(digest[:16], 16), scene_index


def _selection_room_count(*, source: str, scene_index: int) -> int:
    metadata = scanner_metadata(source=source, scene_index=scene_index)
    if metadata.get("room_count"):
        return int(metadata["room_count"])
    return int(SOURCE_SELECTION_ROOM_COUNTS.get(source, {}).get(scene_index) or 0)
