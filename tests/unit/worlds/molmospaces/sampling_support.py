from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.worlds.molmospaces.sampling import (
    READINESS_REJECTED,
    eval_sample_id,
    eval_sampler_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES = {
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
}

ITHOR_REJECTED_INDICES = {
    *range(1, 13),
    *range(201, 213),
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
    *ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES,
}

HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES = {107, 171, 268}

HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES = {261, 381, 403}

HOLODECK_PREFILTER_GATE_MISMATCH_INDICES = {231, 344}

HOLODECK_REJECTED_INDICES = {
    *range(20),
    *HOLODECK_PREFILTER_GATE_MISMATCH_INDICES,
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
    *HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES,
    *HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES,
}

PROCTHOR_10K_REJECTED_COUNT = 7

PROCTHOR_OBJAVERSE_REJECTED_COUNT = 5

TOTAL_REJECTED_ROW_COUNT = (
    PROCTHOR_10K_REJECTED_COUNT
    + PROCTHOR_OBJAVERSE_REJECTED_COUNT
    + len(ITHOR_REJECTED_INDICES)
    + len(HOLODECK_REJECTED_INDICES)
)

UI_WORLD_IDS = (
    "molmospaces/procthor-10k-val/0",
    "molmospaces/procthor-10k-val/11",
    "molmospaces/procthor-10k-val/15",
    "molmospaces/procthor-objaverse-val/0",
    "molmospaces/procthor-objaverse-val/1",
    "molmospaces/procthor-objaverse-val/10",
)


@pytest.fixture(autouse=True)
def _isolate_scene_sampler_scanner_artifacts(monkeypatch, tmp_path) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    scanner_root = tmp_path / "scene-sampler-scanner"
    monkeypatch.setattr(scene_sampler, "_SCANNER_OUTPUT_ROOT", scanner_root)
    monkeypatch.setattr(scene_sampler, "_SCANNER_PREVIEW_ROOT", scanner_root / "previews")
    monkeypatch.setattr(
        scene_sampler,
        "_SCANNER_PRODUCT_SMOKE_ROOT",
        scanner_root / "product-smoke",
    )


def _assert_scene_sampler_projection_summary(projection: dict[str, object]) -> None:
    assert projection["summary"] == {
        "source_count": 4,
        "target_sample_count": 40,
        "ready_sample_count": 16,
        "partial_source_count": 1,
        "rejected_source_count": 2,
        "blocked_source_count": 0,
        "complete_source_count": 1,
        "blocked_row_count": 0,
        "rejected_row_count": TOTAL_REJECTED_ROW_COUNT,
        "blocked_or_rejected_row_count": TOTAL_REJECTED_ROW_COUNT,
        "remaining_sample_count": 24,
    }


def _assert_partial_projection_source(
    source_projection: dict[str, object],
    *,
    scene_source: str,
    expected_rejected_indices: set[int],
) -> None:
    assert source_projection["target_count"] == 10
    assert source_projection["ready_count"] == 6
    assert source_projection["partial_gap_count"] == 4
    assert source_projection["needed_count"] == 4
    assert source_projection["blocked_count"] == 0
    assert source_projection["rejected_count"] == len(expected_rejected_indices)
    assert source_projection["blocked_or_rejected_row_count"] == len(expected_rejected_indices)
    assert source_projection["support_status"] == "partial"
    assert source_projection["status"] == "partial_or_blocked"
    assert source_projection["sample_ids"] == [
        eval_sample_id(row) for row in eval_sampler_rows() if row.scene_source == scene_source
    ]
    rejected_indices = {
        row["scene_index"]
        for row in source_projection["blocked_rows"]
        if row["readiness_status"] == READINESS_REJECTED
    }
    assert rejected_indices == expected_rejected_indices
    assert any(
        row["scene_index"] == 4
        and row["blocked_reason"] == "fewer_than_three_public_navigation_areas"
        for row in source_projection["blocked_rows"]
    )


def _assert_complete_projection_source(
    source_projection: dict[str, object],
    *,
    scene_source: str,
    expected_rejected_indices: set[int],
) -> None:
    assert source_projection["target_count"] == 10
    assert source_projection["ready_count"] == 10
    assert source_projection["partial_gap_count"] == 0
    assert source_projection["needed_count"] == 0
    assert source_projection["blocked_count"] == 0
    assert source_projection["rejected_count"] == len(expected_rejected_indices)
    assert source_projection["blocked_or_rejected_row_count"] == len(expected_rejected_indices)
    assert source_projection["support_status"] == "complete"
    assert source_projection["status"] == "complete"
    assert source_projection["sample_ids"] == [
        eval_sample_id(row) for row in eval_sampler_rows() if row.scene_source == scene_source
    ]
    blocked_indices = {
        row["scene_index"]
        for row in source_projection["blocked_rows"]
        if row["readiness_status"] == READINESS_REJECTED
    }
    assert blocked_indices == expected_rejected_indices
    if scene_source == "procthor-10k-val":
        assert any(
            row["scene_index"] == 4 and row["blocked_reason"] == "preview_not_reviewable"
            for row in source_projection["blocked_rows"]
        )


def _assert_rejected_ithor_projection_source(source_projection: dict[str, object]) -> None:
    assert source_projection["ready_count"] == 0
    assert source_projection["partial_gap_count"] == 10
    assert source_projection["needed_count"] == 10
    assert source_projection["blocked_count"] == 0
    assert source_projection["rejected_count"] == len(ITHOR_REJECTED_INDICES)
    assert source_projection["blocked_or_rejected_row_count"] == len(ITHOR_REJECTED_INDICES)
    assert source_projection["support_status"] == "rejected"
    assert source_projection["status"] == "rejected"
    assert {row["scene_index"] for row in source_projection["blocked_rows"]} == (
        ITHOR_REJECTED_INDICES
    )
    assert all(
        row["readiness_status"] == READINESS_REJECTED for row in source_projection["blocked_rows"]
    )
    assert {
        row["scene_index"]
        for row in source_projection["blocked_rows"]
        if row["failure_class"] == "environment_blocked"
    } == ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    assert all(
        row["failure_class"] == "map_actionability_failure"
        for row in source_projection["blocked_rows"]
        if row["scene_index"] not in ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    )


def _assert_rejected_holodeck_projection_source(source_projection: dict[str, object]) -> None:
    assert source_projection["ready_count"] == 0
    assert source_projection["partial_gap_count"] == 10
    assert source_projection["needed_count"] == 10
    assert source_projection["blocked_count"] == 0
    assert source_projection["rejected_count"] == len(HOLODECK_REJECTED_INDICES)
    assert source_projection["blocked_or_rejected_row_count"] == len(HOLODECK_REJECTED_INDICES)
    assert source_projection["support_status"] == "rejected"
    assert source_projection["status"] == "rejected"
    assert {row["scene_index"] for row in source_projection["blocked_rows"]} == (
        HOLODECK_REJECTED_INDICES
    )
    assert all(
        row["readiness_status"] == READINESS_REJECTED for row in source_projection["blocked_rows"]
    )
    assert {
        row["scene_index"]
        for row in source_projection["blocked_rows"]
        if row["failure_class"] == "environment_blocked"
    } == HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    assert all(
        row["failure_class"] == "map_actionability_failure"
        for row in source_projection["blocked_rows"]
        if row["scene_index"] not in HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    )
    assert {
        row["scene_index"]
        for row in source_projection["blocked_rows"]
        if row["blocked_reason"] == "preview_not_reviewable"
    } == HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES
    gate_mismatch_rows = [
        row
        for row in source_projection["blocked_rows"]
        if row["scene_index"] in HOLODECK_PREFILTER_GATE_MISMATCH_INDICES
    ]
    assert {row["scene_index"] for row in gate_mismatch_rows} == (
        HOLODECK_PREFILTER_GATE_MISMATCH_INDICES
    )
    assert all(row["room_count"] == 1 and row["waypoint_count"] == 2 for row in gate_mismatch_rows)


def _assert_partial_procthor_source_prep(procthor: dict[str, object]) -> None:
    assert procthor["prep_status"] == "blocked_prefilter_inconclusive"
    assert procthor["recommended_candidate_range"] == "0:39"
    assert procthor["molmospaces_get_scenes_call"] == 'get_scenes("procthor-10k", "val")'
    assert procthor["scene_index_map_status"] == "blocked"
    assert procthor["scene_index_map_reason"] == "molmo_spaces_module_unavailable"
    assert procthor["candidate_profile_status"] == "metadata_worklist_ready"
    assert procthor["candidate_profile_next_action"] == "metadata_first_human_curation"
    assert procthor["metadata_worklist_candidate_count"] == 10
    assert procthor["scene_prefilter_status"] == "prefilter_inconclusive"
    assert procthor["scene_prefilter_next_action"] == "stop_prefilter_inconclusive"
    assert procthor["scene_prefilter_expensive_proof_candidate_count"] == 0
    assert procthor["missing_resources"] == []
    assert procthor["missing_resource_summary"]["by_resource_type"] == {}
