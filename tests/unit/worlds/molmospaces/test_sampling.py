from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from roboclaws.launch.catalog import LaunchError, resolve_surface_launch
from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS, world_spec
from roboclaws.worlds.molmospaces import prefilter as scene_sampler_prefilter
from roboclaws.worlds.molmospaces.sampling import (
    EVAL_STRESS_LANE,
    READINESS_BLOCKED,
    READINESS_REJECTED,
    UI_LANE,
    MolmoSpacesSceneRef,
    candidate_profile_report,
    candidate_readiness_report,
    eval_projection_metadata,
    eval_sample_id,
    eval_sample_payload,
    eval_sample_ref,
    eval_sampler_rows,
    eval_suite_payload,
    load_room_label_manifest,
    parse_molmospaces_world_id,
    readiness_report,
    sampler_manifest,
    sampler_rows,
    scanner_admission_report,
    scanner_execution_plan,
    scene_only_prefilter_report,
    selection_gap_report,
    source_availability_report,
    source_prep_report,
    ui_molmospaces_world_ids,
    validate_sampler_manifest,
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


def test_scene_sampler_manifest_separates_ui_and_eval_worlds() -> None:
    validate_sampler_manifest()

    assert ui_molmospaces_world_ids() == UI_WORLD_IDS
    assert MOLMOSPACES_CONSOLE_WORLD_IDS == ui_molmospaces_world_ids()

    ui_rows = [row for row in sampler_rows() if row.ui_ready]
    eval_rows = eval_sampler_rows()
    assert [(row.scene_source, row.scene_index) for row in ui_rows] == [
        ("procthor-10k-val", 0),
        ("procthor-10k-val", 11),
        ("procthor-10k-val", 15),
        ("procthor-objaverse-val", 0),
        ("procthor-objaverse-val", 1),
        ("procthor-objaverse-val", 10),
    ]
    assert [(row.scene_source, row.scene_index) for row in eval_rows] == [
        ("procthor-10k-val", 0),
        ("procthor-10k-val", 10),
        ("procthor-10k-val", 11),
        ("procthor-10k-val", 12),
        ("procthor-10k-val", 13),
        ("procthor-10k-val", 15),
        ("procthor-objaverse-val", 0),
        ("procthor-objaverse-val", 1),
        ("procthor-objaverse-val", 4),
        ("procthor-objaverse-val", 5),
        ("procthor-objaverse-val", 7),
        ("procthor-objaverse-val", 10),
        ("procthor-objaverse-val", 11),
        ("procthor-objaverse-val", 12),
        ("procthor-objaverse-val", 13),
        ("procthor-objaverse-val", 14),
    ]
    assert all(UI_LANE in row.lanes for row in ui_rows)
    assert all(EVAL_STRESS_LANE in row.lanes for row in eval_rows)

    assert "molmospaces/procthor-10k-val/9" not in WORLD_SPECS
    assert world_spec("molmospaces/procthor-10k-val/9").availability == "hidden"


def test_scene_sampler_ui_selection_is_seeded_and_room_diverse() -> None:
    manifest = sampler_manifest()
    policy = manifest["selection_policy"]

    assert policy["schema"] == "molmospaces_scene_sampler_selection_policy_v1"
    assert policy["selection_seed"] == "2026-06-16.source-diverse-selection-v1"
    assert policy["selection_strategy"] == (
        "deterministic_seeded_random_order_with_room_count_diversity_first"
    )
    assert policy["sources"]["procthor-10k-val"]["ui"]["selected_indices"] == [11, 15, 0]
    assert policy["sources"]["procthor-10k-val"]["ui"]["selected_room_counts"] == [4, 10, 7]
    assert policy["sources"]["procthor-objaverse-val"]["ui"]["selected_indices"] == [10, 0, 1]
    assert policy["sources"]["procthor-objaverse-val"]["ui"]["selected_room_counts"] == [
        5,
        4,
        7,
    ]


def test_source_aware_molmospaces_sampler_worlds_are_launchable() -> None:
    for row in sampler_rows():
        if row.scene_index is None:
            continue
        world_id = row.world_id
        plan = resolve_surface_launch(
            [
                "surface=household-world",
                f"world={world_id}",
                "backend=mujoco",
                "preset=map-build",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
            ]
        )
        assert plan.world == world_id
        assert f"scene_source={row.scene_source}" in plan.overrides


def test_legacy_molmospaces_world_id_is_rejected_with_replacement() -> None:
    with pytest.raises(LaunchError, match="molmospaces/procthor-10k-val/0"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/val_0",
                "backend=mujoco",
                "preset=map-build",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
            ]
        )


def test_source_aware_candidate_worlds_are_launchable_but_not_default_visible() -> None:
    world_id = "molmospaces/ithor/1"

    spec = world_spec(world_id)
    plan = resolve_surface_launch(
        [
            "surface=household-world",
            f"world={world_id}",
            "backend=mujoco",
            "preset=map-build",
            "agent_engine=direct-runner",
            "evidence_lane=world-public-labels",
        ]
    )

    assert world_id not in WORLD_SPECS
    assert world_id not in MOLMOSPACES_CONSOLE_WORLD_IDS
    assert spec.availability == "hidden"
    assert spec.sampler_metadata["selected_reason"] == "dynamic_source_aware_scanner_candidate"
    assert plan.world == world_id
    assert "scene_source=ithor" in plan.overrides
    assert "scene_index=1" in plan.overrides
    assert "map_bundle=assets/maps/molmospaces/ithor/1" in plan.overrides


def test_world_spec_sampler_metadata_is_immutable() -> None:
    spec = world_spec("molmospaces/procthor-10k-val/0")

    with pytest.raises(TypeError):
        spec.sampler_metadata["selected_reason"] = "changed"  # type: ignore[index]


def test_household_molmospaces_launch_rejects_disabled_map_bundle() -> None:
    with pytest.raises(LaunchError, match="cannot use map_bundle"):
        resolve_surface_launch(
            [
                "surface=household-world",
                "world=molmospaces/ithor/1",
                "backend=mujoco",
                "preset=map-build",
                "agent_engine=direct-runner",
                "evidence_lane=world-public-labels",
                "map_bundle=none",
            ]
        )


def test_scene_sampler_parses_source_aware_world_ids() -> None:
    assert parse_molmospaces_world_id("molmospaces/procthor-10k-val/9") == MolmoSpacesSceneRef(
        scene_source="procthor-10k-val",
        scene_index=9,
    )
    assert parse_molmospaces_world_id("molmospaces/ithor/3") == MolmoSpacesSceneRef(
        scene_source="ithor",
        scene_index=3,
    )
    assert parse_molmospaces_world_id("molmospaces/holodeck-objaverse-val/12") == (
        MolmoSpacesSceneRef(scene_source="holodeck-objaverse-val", scene_index=12)
    )


def test_scene_sampler_rejects_unknown_source_aware_world_ids() -> None:
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene_source"):
        parse_molmospaces_world_id("molmospaces/unknown-source/1")
    with pytest.raises(ValueError, match="unsupported MolmoSpaces scene index"):
        parse_molmospaces_world_id("molmospaces/ithor/not-an-index")
    with pytest.raises(ValueError, match="negative MolmoSpaces scene index"):
        parse_molmospaces_world_id("molmospaces/ithor/-1")


def test_scene_sampler_records_partial_and_blocked_source_projection() -> None:
    projection = eval_projection_metadata()

    _assert_scene_sampler_projection_summary(projection)
    _assert_partial_projection_source(
        projection["scene_sources"]["procthor-10k-val"],
        scene_source="procthor-10k-val",
        expected_rejected_indices={1, 2, 3, 4, 5, 7, 9},
    )
    _assert_complete_projection_source(
        projection["scene_sources"]["procthor-objaverse-val"],
        scene_source="procthor-objaverse-val",
        expected_rejected_indices={2, 3, 6, 8, 9},
    )
    _assert_rejected_ithor_projection_source(projection["scene_sources"]["ithor"])
    _assert_rejected_holodeck_projection_source(
        projection["scene_sources"]["holodeck-objaverse-val"]
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


def test_scene_sampler_eval_suite_payload_matches_committed_fixture() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/household_world/suites/scene_sampler_stress.json").read_text(
            encoding="utf-8"
        )
    )

    assert eval_suite_payload() == fixture


def test_scene_sampler_eval_sample_payloads_match_committed_fixtures() -> None:
    for row in eval_sampler_rows():
        fixture_path = REPO_ROOT / eval_sample_ref(row)
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

        assert eval_sample_payload(row) == fixture


def test_scene_sampler_eval_sample_payload_rejects_non_eval_rows() -> None:
    rejected = next(row for row in sampler_rows() if row.scene_index == 1)

    with pytest.raises(ValueError, match="eval-ready sampler row"):
        eval_sample_payload(rejected)


def test_scene_sampler_rejects_heuristic_room_category_provenance() -> None:
    manifest = copy.deepcopy(sampler_manifest())
    ready_row = next(
        row
        for row in manifest["rows"]
        if row["readiness_status"] == "ready" and row["scene_index"] == 0
    )
    ready_row["category_provenance"] = "heuristic_room_count"

    with pytest.raises(ValueError, match="trusted room-category provenance"):
        validate_sampler_manifest(manifest)


@pytest.mark.parametrize(
    ("source_text", "expected_message"),
    [
        ("{", "room label manifest source must contain valid JSON object"),
        ("[]", "room label manifest source must contain a JSON object"),
    ],
)
def test_scene_sampler_room_label_manifest_reports_source_errors(
    tmp_path: Path,
    source_text: str,
    expected_message: str,
) -> None:
    manifest_path = tmp_path / "room-labels.json"
    manifest_path.write_text(source_text, encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_room_label_manifest(manifest_path)

    message = str(exc_info.value)
    assert expected_message in message
    assert str(manifest_path) in message


def test_scene_sampler_requires_exactly_three_ui_rows_per_visible_source() -> None:
    manifest = copy.deepcopy(sampler_manifest())
    row = next(
        row
        for row in manifest["rows"]
        if row["scene_source"] == "procthor-objaverse-val" and row["scene_index"] == 4
    )
    row["readiness_status"] = "ready"
    row["lanes"] = [UI_LANE, EVAL_STRESS_LANE]

    with pytest.raises(ValueError, match="more than 3 UI samples"):
        validate_sampler_manifest(manifest)


def test_scene_sampler_limits_eval_stress_rows_per_source() -> None:
    manifest = copy.deepcopy(sampler_manifest())
    template = next(
        row
        for row in manifest["rows"]
        if row["readiness_status"] == "ready" and row["scene_index"] == 0
    )
    manifest["rows"] = [
        {
            **template,
            "world_id": f"molmospaces/procthor-10k-val/0/eval-{index}",
            "lanes": [EVAL_STRESS_LANE],
        }
        for index in range(11)
    ]

    with pytest.raises(ValueError, match="more than 10 eval-stress samples"):
        validate_sampler_manifest(manifest)


def test_scene_sampler_readiness_report_is_per_source() -> None:
    report = readiness_report()

    assert report["schema"] == "molmospaces_scene_sampler_readiness_report_v1"
    assert report["summary"]["source_count"] == 4
    assert report["summary"]["ui_supported_source_count"] == 2
    assert report["summary"]["eval_complete_source_count"] == 1
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["ui_status"] == "ready"
    assert procthor["ui_ready_count"] == 3
    assert procthor["eval_status"] == "partial_or_blocked"
    assert procthor["eval_ready_count"] == 6

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["ui_status"] == "ready"
    assert objaverse["ui_ready_count"] == 3
    assert objaverse["eval_status"] == "complete"
    assert objaverse["eval_ready_count"] == 10
    assert {row["scene_index"] for row in objaverse["blocked_rows"]} == {2, 3, 6, 8, 9}

    ithor = report["sources"]["ithor"]
    assert ithor["ui_status"] == "not_visible"
    assert ithor["ui_ready_count"] == 0
    assert ithor["eval_status"] == "partial_or_blocked"
    assert ithor["eval_ready_count"] == 0
    assert {row["scene_index"] for row in ithor["blocked_rows"]} == ITHOR_REJECTED_INDICES
    assert {
        row["scene_index"]
        for row in ithor["blocked_rows"]
        if row["failure_class"] == "environment_blocked"
    } == ITHOR_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["ui_status"] == "not_visible"
    assert holodeck["ui_ready_count"] == 0
    assert holodeck["eval_status"] == "partial_or_blocked"
    assert holodeck["eval_ready_count"] == 0
    assert {row["scene_index"] for row in holodeck["blocked_rows"]} == (HOLODECK_REJECTED_INDICES)
    assert {
        row["scene_index"]
        for row in holodeck["blocked_rows"]
        if row["failure_class"] == "environment_blocked"
    } == HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    assert all(
        row["failure_class"] == "map_actionability_failure"
        for row in holodeck["blocked_rows"]
        if row["scene_index"] not in HOLODECK_MISSING_PUBLIC_WAYPOINT_REJECTED_INDICES
    )
    assert {
        row["scene_index"]
        for row in holodeck["blocked_rows"]
        if row["blocked_reason"] == "preview_not_reviewable"
    } == HOLODECK_PREVIEW_NOT_REVIEWABLE_REJECTED_INDICES
    assert {
        row["scene_index"]
        for row in holodeck["blocked_rows"]
        if row["scene_index"] in HOLODECK_PREFILTER_GATE_MISMATCH_INDICES
    } == HOLODECK_PREFILTER_GATE_MISMATCH_INDICES


def test_scene_sampler_source_availability_reports_missing_molmospaces_module(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = source_availability_report(candidate_indices=(0, 2))

    assert report["schema"] == "molmospaces_scene_source_availability_report_v1"
    assert report["probe_mode"] == "no_download_no_vlm"
    assert report["python_executable"]
    assert report["python_version"]
    assert report["molmospaces_module_available"] is False
    assert "molmospaces_module_stdout" in report
    assert "scene_root_stdout" in report
    assert report["summary"] == {
        "source_count": 4,
        "available_source_count": 0,
        "blocked_source_count": 4,
        "scene_root_available_source_count": 0,
        "source_dir_available_count": 0,
        "scene_index_map_available_count": 0,
        "missing_candidate_count": 8,
        "invalid_candidate_count": 0,
    }
    for source in ("ithor", "procthor-objaverse-val", "holodeck-objaverse-val"):
        source_report = report["sources"][source]
        assert source_report["status"] == "blocked"
        assert source_report["failure_class"] == "environment_blocked"
        assert "module is not importable" in source_report["blocked_reason"]
        assert source_report["candidate_indices"] == [0, 2]


def test_scene_sampler_candidate_readiness_keeps_ready_rejected_and_blocked_rows(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = candidate_readiness_report(candidate_indices=(0, 1, 2))

    assert report["schema"] == "molmospaces_scene_sampler_candidate_readiness_v1"
    assert report["summary"] == {
        "source_count": 4,
        "candidate_count": 16 + TOTAL_REJECTED_ROW_COUNT + 1,
        "ready_candidate_count": 16,
        "blocked_candidate_count": 1,
        "rejected_candidate_count": TOTAL_REJECTED_ROW_COUNT,
        "ui_ready_count": 6,
        "ui_needed_count": 6,
        "eval_ready_count": 16,
        "eval_needed_count": 24,
        "ui_supported_source_count": 2,
        "eval_complete_source_count": 1,
        "blocked_source_count": 1,
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["ui_ready_count"] == 3
    assert procthor["eval_ready_count"] == 6
    assert procthor["candidate_count"] == 13
    assert procthor["ready_candidate_count"] == 6
    assert procthor["rejected_candidate_count"] == 7
    val_1 = next(item for item in procthor["candidates"] if item["scene_index"] == 1)
    assert val_1["readiness_status"] == READINESS_REJECTED
    assert val_1["blocked_reason"] == "fewer_than_three_public_navigation_areas"

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["ui_ready_count"] == 3
    assert objaverse["eval_ready_count"] == 10
    assert objaverse["candidate_count"] == 15
    assert objaverse["ready_candidate_count"] == 10
    assert objaverse["rejected_candidate_count"] == 5
    assert {
        item["scene_index"]
        for item in objaverse["candidates"]
        if item["readiness_status"] == READINESS_REJECTED
    } == {2, 3, 6, 8, 9}

    ithor = report["sources"]["ithor"]
    assert ithor["blocked_candidate_count"] == 1
    assert ithor["rejected_candidate_count"] == len(ITHOR_REJECTED_INDICES)
    assert ithor["candidates"][0]["world_id"] == "molmospaces/ithor/0"
    assert ithor["candidates"][0]["failure_class"] == "environment_blocked"
    assert {
        item["scene_index"]
        for item in ithor["candidates"]
        if item["readiness_status"] == READINESS_REJECTED
    } == ITHOR_REJECTED_INDICES

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["blocked_candidate_count"] == 0
    assert holodeck["rejected_candidate_count"] == len(HOLODECK_REJECTED_INDICES)
    assert {
        item["scene_index"]
        for item in holodeck["candidates"]
        if item["readiness_status"] == READINESS_REJECTED
    } == HOLODECK_REJECTED_INDICES


def test_scene_sampler_selection_gap_report_prioritizes_missing_samples(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = selection_gap_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_selection_gaps_v1"
    assert report["summary"]["ui_needed_count"] == 6
    assert report["summary"]["eval_needed_count"] == 24
    assert report["summary"]["candidate_range_sufficient_source_count"] == 0
    assert report["summary"]["candidate_range_insufficient_source_count"] == 1
    assert report["summary"]["source_prep_required_count"] == 0
    assert report["summary"]["next_actions"] == {
        "expand_candidate_range": 1,
        "do_not_scan_without_new_human_curation": 2,
    }
    assert report["summary"]["worklist"][0] == {
        "scene_source": "procthor-10k-val",
        "next_action": "expand_candidate_range",
        "selection_capacity_status": "candidate_range_insufficient",
        "source_availability_status": "blocked",
        "ui_needed_count": 0,
        "ui_scan_candidate_count": 0,
        "eval_needed_count": 4,
        "eval_scan_candidate_count": 2,
        "next_scan_world_ids": [
            "molmospaces/procthor-10k-val/8",
            "molmospaces/procthor-10k-val/6",
        ],
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["ui_needed_count"] == 0
    assert procthor["eval_needed_count"] == 4
    assert procthor["selection_capacity_status"] == "candidate_range_insufficient"
    assert procthor["next_action"] == "expand_candidate_range"
    assert procthor["next_ui_scan_world_ids"] == []
    assert procthor["next_eval_scan_world_ids"] == [
        "molmospaces/procthor-10k-val/8",
        "molmospaces/procthor-10k-val/6",
    ]
    assert procthor["rejected_candidate_indices"] == [1, 2, 3, 4, 5, 7, 9]

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["ui_needed_count"] == 0
    assert objaverse["eval_needed_count"] == 0
    assert objaverse["selection_capacity_status"] == "complete"
    assert objaverse["next_action"] == "none"
    assert objaverse["next_ui_scan_world_ids"] == []
    assert objaverse["next_eval_scan_world_ids"] == []
    assert objaverse["rejected_candidate_indices"] == [2, 3, 6, 8, 9]

    ithor = report["sources"]["ithor"]
    assert ithor["ui_needed_count"] == 3
    assert ithor["eval_needed_count"] == 10
    assert ithor["selection_capacity_status"] == "rejected_exhausted"
    assert ithor["next_action"] == "do_not_scan_without_new_human_curation"
    assert ithor["next_ui_scan_world_ids"] == []
    assert ithor["next_eval_scan_world_ids"] == []

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["ui_needed_count"] == 3
    assert holodeck["eval_needed_count"] == 10
    assert holodeck["selection_capacity_status"] == "rejected_exhausted"
    assert holodeck["next_action"] == "do_not_scan_without_new_human_curation"
    assert holodeck["next_ui_scan_world_ids"] == []
    assert holodeck["next_eval_scan_world_ids"] == []
    assert holodeck["rejected_candidate_indices"] == sorted(HOLODECK_REJECTED_INDICES)


def test_scene_sampler_selection_gap_report_records_expanded_range_capacity(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = selection_gap_report(candidate_indices=tuple(range(20)))

    assert report["summary"]["candidate_range_insufficient_source_count"] == 0
    assert report["summary"]["candidate_range_sufficient_source_count"] == 1
    assert report["summary"]["source_prep_required_count"] == 1
    assert report["summary"]["next_actions"] == {
        "run_source_prep_before_scanner": 1,
        "do_not_scan_without_new_human_curation": 2,
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["selection_capacity_status"] == "candidate_range_sufficient"
    assert procthor["next_action"] == "run_source_prep_before_scanner"
    assert procthor["eval_scan_candidate_count"] == 4
    assert procthor["next_eval_scan_world_ids"] == [
        "molmospaces/procthor-10k-val/16",
        "molmospaces/procthor-10k-val/19",
        "molmospaces/procthor-10k-val/18",
        "molmospaces/procthor-10k-val/17",
    ]
    assert report["sources"]["procthor-objaverse-val"]["selection_capacity_status"] == "complete"
    assert (
        report["sources"]["holodeck-objaverse-val"]["selection_capacity_status"]
        == "rejected_exhausted"
    )


def test_scene_sampler_selection_gap_marks_ithor_rejected_when_assets_are_visible() -> None:
    report = selection_gap_report(candidate_indices=tuple(range(13)))

    ithor = report["sources"]["ithor"]
    assert ithor["selection_capacity_status"] == "rejected_exhausted"
    assert ithor["next_action"] == "do_not_scan_without_new_human_curation"
    assert ithor["next_ui_scan_world_ids"] == []
    assert ithor["next_eval_scan_world_ids"] == []
    rejected_ithor = set(ithor["rejected_candidate_indices"])
    assert set(range(1, 13)).issubset(rejected_ithor)
    assert {209, 210, 211, 303, 305}.issubset(rejected_ithor)
    assert {404, 406, 408, 411}.issubset(rejected_ithor)

    prep = source_prep_report(candidate_indices=tuple(range(13)))
    assert prep["sources"]["ithor"]["prep_status"] == "rejected_exhausted"
    assert prep["sources"]["ithor"]["install_candidates"] == []


def test_scene_sampler_candidate_profile_lists_metadata_first_worklists() -> None:
    report = candidate_profile_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_candidate_profile_v1"
    assert report["probe_mode"] == "no_download_no_backend_no_vlm"
    assert report["download_policy"] == "manual_operator_only"
    assert report["summary"]["source_count"] == 4
    assert report["summary"]["metadata_worklist_source_count"] == 2
    assert report["summary"]["metadata_worklist_candidate_count"] == 20
    assert report["summary"]["next_actions"] == {
        "choose_new_candidate_indices_or_gate_change": 1,
        "metadata_first_human_curation": 2,
    }
    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["profile_status"] == "metadata_worklist_ready"
    assert procthor["next_action"] == "metadata_first_human_curation"
    assert procthor["metadata_worklist_candidate_count"] == 10
    assert report["sources"]["procthor-objaverse-val"]["profile_status"] == "complete"

    ithor = report["sources"]["ithor"]
    assert ithor["profile_status"] == "known_rejected_exhausted"
    assert ithor["next_action"] == "choose_new_candidate_indices_or_gate_change"
    assert set(range(1, 13)).issubset(ithor["known_rejected_indices"])
    assert {201, 208, 209, 210, 211, 303, 304, 305, 307, 309}.issubset(
        ithor["known_rejected_indices"]
    )
    assert {404, 406, 408, 409, 411}.issubset(ithor["known_rejected_indices"])
    assert ithor["metadata_worklist_candidate_count"] == 0
    assert ithor["metadata_worklist_world_ids"] == []
    assert ithor["metadata_worklist_candidates"] == []

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["profile_status"] == "metadata_worklist_ready"
    assert holodeck["next_action"] == "metadata_first_human_curation"
    assert set(range(20)).issubset(holodeck["known_rejected_indices"])
    assert {71, 106, 157, 173, 280, 292, 323, 349, 360, 396}.issubset(
        holodeck["known_rejected_indices"]
    )
    assert holodeck["metadata_worklist_candidate_count"] == 10
    assert all(
        index not in holodeck["known_rejected_indices"]
        for index in holodeck["metadata_worklist_indices"]
    )
    assert holodeck["metadata_worklist_world_ids"][0].startswith(
        "molmospaces/holodeck-objaverse-val/"
    )


def test_scene_sampler_candidate_profile_does_not_reoffer_failed_preview_candidates() -> None:
    report = candidate_profile_report(candidate_indices=(404, 406, 408, 411))

    ithor = report["sources"]["ithor"]
    assert {404, 406, 408, 411}.issubset(ithor["known_rejected_indices"])
    assert {404, 406, 408, 411}.isdisjoint(ithor["metadata_worklist_indices"])

    failed = {
        candidate["scene_index"]: candidate
        for candidate in ithor["candidates"]
        if candidate["scene_index"] in {404, 406, 408, 411}
    }
    assert failed[404]["known_blocked_reason"] == "missing_public_inspection_waypoints"
    assert all(
        candidate["next_action"] == "do_not_scan_without_gate_change_or_new_curation"
        for candidate in failed.values()
    )


def test_scene_sampler_prefilter_optional_json_loads_object(tmp_path: Path) -> None:
    source = tmp_path / "prefilter.json"
    source.write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    assert scene_sampler_prefilter._read_json_if_exists(source) == {"status": "ready"}


@pytest.mark.parametrize("source_text", ["{bad json\n", "[]\n"])
def test_scene_sampler_prefilter_optional_json_ignores_bad_source(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "prefilter.json"
    source.write_text(source_text, encoding="utf-8")

    assert scene_sampler_prefilter._read_json_if_exists(source) == {}


def test_scene_sampler_prefilter_optional_json_ignores_missing_source(tmp_path: Path) -> None:
    assert scene_sampler_prefilter._read_json_if_exists(tmp_path / "missing.json") == {}


def test_scene_sampler_scene_only_prefilter_stops_when_descriptors_are_missing(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = scene_only_prefilter_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_scene_prefilter_v1"
    assert report["probe_mode"] == "no_download_no_backend_no_vlm"
    assert report["download_policy"] == "manual_operator_only"
    assert report["prefilter_policy"]["admission_effect"] == "none_prefilter_only"
    assert report["summary"]["metadata_worklist_source_count"] == 3
    assert report["summary"]["expensive_proof_candidate_count"] == 0
    assert report["summary"]["next_actions"] == {"stop_prefilter_inconclusive": 3}

    procthor = report["sources"]["procthor-10k-val"]
    assert procthor["prefilter_status"] == "prefilter_inconclusive"
    assert procthor["next_action"] == "stop_prefilter_inconclusive"
    assert procthor["candidate_count"] == 10
    assert procthor["expensive_proof_candidate_count"] == 0

    ithor = report["sources"]["ithor"]
    assert ithor["prefilter_status"] == "prefilter_inconclusive"
    assert ithor["next_action"] == "stop_prefilter_inconclusive"
    assert ithor["candidate_count"] == 10
    assert ithor["expensive_proof_candidate_count"] == 0
    assert {candidate["prefilter_reason"] for candidate in ithor["candidates"]}.issubset(
        {"descriptor_missing", "source_index_reference_missing"}
    )


def test_scene_sampler_scene_only_prefilter_selects_high_confidence_descriptor(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco><geom name='room_0'/></mujoco>", encoding="utf-8")
    candidate_path.with_suffix(".json").write_text(
        json.dumps({"rooms": [{"id": "kitchen"}, {"id": "living"}, {"id": "hall"}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        scene_sampler,
        "candidate_profile_report",
        lambda *, candidate_indices: {
            "selection_policy": {},
            "sources": {
                source: {
                    "scene_family": "holodeck-objaverse",
                    "scene_split": "val",
                    "profile_status": (
                        "metadata_worklist_ready"
                        if source == "holodeck-objaverse-val"
                        else "complete"
                    ),
                    "next_action": (
                        "metadata_first_human_curation"
                        if source == "holodeck-objaverse-val"
                        else "none"
                    ),
                    "metadata_worklist_candidate_count": 1
                    if source == "holodeck-objaverse-val"
                    else 0,
                    "metadata_worklist_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "metadata_worklist_rank": 0,
                            "known_failure_class": "environment_blocked",
                            "known_blocked_reason": "map build product smoke pending",
                            "candidate_file": {
                                "scene_source": "holodeck-objaverse-val",
                                "scene_index": 22,
                                "path": str(candidate_path),
                                "exists": True,
                                "status": "available",
                                "source": "molmospaces_get_scenes",
                                "paths": [
                                    {
                                        "role": "base",
                                        "path": str(candidate_path),
                                        "exists": True,
                                    }
                                ],
                                "missing_paths": [],
                            },
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            },
        },
    )

    report = scene_only_prefilter_report(candidate_indices=tuple(range(40)))
    holodeck = report["sources"]["holodeck-objaverse-val"]

    assert holodeck["prefilter_status"] == "high_confidence_ready"
    assert holodeck["next_action"] == "run_expensive_proof_for_prefiltered_candidates"
    assert holodeck["high_confidence_candidate_count"] == 1
    assert holodeck["expensive_proof_candidate_count"] == 1
    candidate = holodeck["candidates"][0]
    assert candidate["prefilter_status"] == "high_confidence"
    assert candidate["prefilter_reason"] == "likely_multi_area"
    assert candidate["cheap_room_count"] == 3
    assert candidate["scene_descriptor_path"] == str(candidate_path.with_suffix(".json"))
    assert candidate["expensive_proof_selected"] is True
    assert candidate["admission_effect"] == "none_prefilter_only"


def test_scene_sampler_scene_only_prefilter_marks_single_room_low_confidence(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_23.xml"
    candidate_path.write_text("<mujoco><geom name='room_0'/></mujoco>", encoding="utf-8")

    monkeypatch.setattr(
        scene_sampler,
        "candidate_profile_report",
        lambda *, candidate_indices: {
            "selection_policy": {},
            "sources": {
                source: {
                    "scene_family": "holodeck-objaverse",
                    "scene_split": "val",
                    "profile_status": (
                        "metadata_worklist_ready"
                        if source == "holodeck-objaverse-val"
                        else "complete"
                    ),
                    "next_action": (
                        "metadata_first_human_curation"
                        if source == "holodeck-objaverse-val"
                        else "none"
                    ),
                    "metadata_worklist_candidate_count": 1
                    if source == "holodeck-objaverse-val"
                    else 0,
                    "metadata_worklist_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 23,
                            "world_id": "molmospaces/holodeck-objaverse-val/23",
                            "candidate_file": {
                                "scene_source": "holodeck-objaverse-val",
                                "scene_index": 23,
                                "path": str(candidate_path),
                                "exists": True,
                                "status": "available",
                                "source": "molmospaces_get_scenes",
                                "paths": [
                                    {
                                        "role": "base",
                                        "path": str(candidate_path),
                                        "exists": True,
                                    }
                                ],
                                "missing_paths": [],
                            },
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            },
        },
    )

    report = scene_only_prefilter_report(candidate_indices=tuple(range(40)))
    holodeck = report["sources"]["holodeck-objaverse-val"]

    assert holodeck["prefilter_status"] == "low_confidence_only"
    assert holodeck["next_action"] == "stop_prefilter_inconclusive"
    assert holodeck["expensive_proof_candidate_count"] == 0
    candidate = holodeck["candidates"][0]
    assert candidate["prefilter_status"] == "low_confidence"
    assert candidate["prefilter_reason"] == "single_room_likely"
    assert candidate["cheap_room_count"] == 1
    assert candidate["next_action"] == "do_not_run_expensive_proof_without_gate_change"


def test_scene_sampler_source_prep_report_lists_manual_prep_steps(monkeypatch) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = source_prep_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_source_prep_v1"
    assert report["probe_mode"] == "no_download_no_vlm"
    assert report["download_policy"] == "manual_operator_only"
    assert report["summary"]["source_count"] == 4
    assert report["summary"]["missing_resource_summary"]["by_resource_type"] == {}
    assert report["summary"]["missing_resource_summary"]["by_reason"] == {}
    assert report["summary"]["prep_status_counts"] == {
        "blocked_prefilter_inconclusive": 2,
        "complete": 1,
        "gate_mismatch": 1,
    }
    assert report["summary"]["worklist"][0]["scene_source"] == "procthor-10k-val"
    assert report["summary"]["worklist"][0]["next_action"] == "run_scene_only_prefilter_or_stop"
    assert report["summary"]["worklist"][0]["metadata_worklist_candidate_count"] == 10
    assert report["summary"]["worklist"][0]["install_candidate_count"] == 2

    _assert_partial_procthor_source_prep(report["sources"]["procthor-10k-val"])

    objaverse = report["sources"]["procthor-objaverse-val"]
    assert objaverse["prep_status"] == "complete"
    assert objaverse["recommended_candidate_range"] == "0:9"
    assert objaverse["molmospaces_get_scenes_call"] == ('get_scenes("procthor-objaverse", "val")')
    assert objaverse["missing_resources"] == []

    ithor = report["sources"]["ithor"]
    assert ithor["molmospaces_get_scenes_call"] == 'get_scenes("ithor", "train")'
    assert ithor["prep_status"] == "blocked_prefilter_inconclusive"
    assert ithor["candidate_profile_status"] == "metadata_worklist_ready"
    assert ithor["candidate_profile_next_action"] == "metadata_first_human_curation"
    assert ithor["metadata_worklist_candidate_count"] == 10
    assert ithor["scene_prefilter_status"] == "prefilter_inconclusive"
    assert ithor["scene_prefilter_next_action"] == "stop_prefilter_inconclusive"
    assert ithor["scene_prefilter_expensive_proof_candidate_count"] == 0
    assert ithor["next_scan_world_ids"] == []
    assert ithor["install_candidates"] == []
    assert any(
        command["name"] == "rerun_readiness_after_prep" for command in ithor["operator_commands"]
    )

    holodeck = report["sources"]["holodeck-objaverse-val"]
    assert holodeck["prep_status"] == "gate_mismatch"
    assert holodeck["gate_mismatch_candidate_count"] == 2
    assert holodeck["gate_mismatch_world_ids"] == [
        "molmospaces/holodeck-objaverse-val/231",
        "molmospaces/holodeck-objaverse-val/344",
    ]
    assert holodeck["install_candidates"] == []
    assert holodeck["missing_resources"] == []


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


def test_scene_sampler_source_prep_promotes_metadata_worklist_when_assets_exist(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco />", encoding="utf-8")
    candidate_path.with_suffix(".json").write_text(
        json.dumps({"rooms": [{"id": "kitchen"}, {"id": "living"}, {"id": "hall"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scene_sampler,
        "source_availability_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "scene_source": source,
                    "status": "available",
                    "module_available": True,
                    "scene_root_available": True,
                    "scene_index_map_status": "available",
                    "molmospaces_scene_version": "test",
                    "scene_index_map_reason": "",
                    "scene_index_map_stdout": "",
                    "source_dir": str(tmp_path),
                    "source_dir_available": True,
                    "candidate_files": [
                        {
                            "scene_source": source,
                            "scene_index": 22,
                            "path": str(candidate_path),
                            "exists": True,
                            "status": "available",
                            "source": "molmospaces_get_scenes",
                            "raw_ref_type": "dict",
                            "paths": [
                                {
                                    "role": "base",
                                    "path": str(candidate_path),
                                    "exists": True,
                                }
                            ],
                            "missing_paths": [],
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler,
        "selection_gap_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "scene_source": source,
                    "status": "incomplete",
                    "selection_capacity_status": (
                        "rejected_exhausted" if source == "holodeck-objaverse-val" else "complete"
                    ),
                    "ui_needed_count": 3 if source == "holodeck-objaverse-val" else 0,
                    "eval_needed_count": 10 if source == "holodeck-objaverse-val" else 0,
                    "next_scan_candidates": [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler,
        "candidate_profile_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "profile_status": (
                        "metadata_worklist_ready"
                        if source == "holodeck-objaverse-val"
                        else "complete"
                    ),
                    "next_action": (
                        "metadata_first_human_curation"
                        if source == "holodeck-objaverse-val"
                        else "none"
                    ),
                    "metadata_worklist_indices": [22] if source == "holodeck-objaverse-val" else [],
                    "metadata_worklist_world_ids": ["molmospaces/holodeck-objaverse-val/22"]
                    if source == "holodeck-objaverse-val"
                    else [],
                    "metadata_worklist_candidate_count": 1
                    if source == "holodeck-objaverse-val"
                    else 0,
                    "metadata_worklist_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "known_failure_class": "environment_blocked",
                            "known_blocked_reason": "map build product smoke pending",
                            "candidate_file": {
                                "scene_source": "holodeck-objaverse-val",
                                "scene_index": 22,
                                "path": str(candidate_path),
                                "exists": True,
                                "status": "available",
                                "source": "molmospaces_get_scenes",
                                "paths": [
                                    {
                                        "role": "base",
                                        "path": str(candidate_path),
                                        "exists": True,
                                    }
                                ],
                                "missing_paths": [],
                            },
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    prep = source_prep_report(candidate_indices=tuple(range(40)))
    holodeck = prep["sources"]["holodeck-objaverse-val"]

    assert holodeck["prep_status"] == "ready_for_scanner"
    assert holodeck["scene_prefilter_status"] == "high_confidence_ready"
    assert holodeck["scene_prefilter_expensive_proof_candidate_count"] == 1
    assert holodeck["metadata_worklist_scan_world_ids"] == ["molmospaces/holodeck-objaverse-val/22"]
    assert holodeck["install_candidates"][0]["world_id"] == (
        "molmospaces/holodeck-objaverse-val/22"
    )
    assert holodeck["install_candidates"][0]["primary_path"] == str(candidate_path)
    assert holodeck["install_candidates"][0]["prefilter_status"] == "high_confidence"
    assert holodeck["install_candidates"][0]["prefilter_reason"] == "likely_multi_area"
    assert holodeck["install_candidates"][0]["prefilter_score"] == 3


def test_scene_sampler_scanner_execution_plan_runs_metadata_worklist_candidates(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco />", encoding="utf-8")
    monkeypatch.setattr(
        scene_sampler,
        "source_prep_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "prep_status": (
                        "ready_for_scanner" if source == "holodeck-objaverse-val" else "complete"
                    ),
                    "install_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "primary_path": str(candidate_path),
                            "path_status": "available",
                            "paths": [
                                {
                                    "role": "base",
                                    "path": str(candidate_path),
                                    "exists": True,
                                }
                            ],
                            "missing_paths": [],
                            "install_command": "",
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler,
        "scanner_admission_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "admission_rows": [
                        {
                            "scene_family": "holodeck-objaverse",
                            "scene_split": "val",
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "readiness_status": READINESS_BLOCKED,
                            "admission_status": "blocked",
                            "lanes": [],
                            "failure_class": "environment_blocked",
                            "blocked_reason": "map build product smoke pending",
                            "selected_reason": "scanner_evidence_incomplete_for_source_sampler",
                            "room_count": 1,
                            "waypoint_count": 2,
                            "category_provenance": "unavailable",
                            "preview_statuses": {
                                "fpv": "reviewable",
                                "map": "reviewable",
                                "chase": "reviewable",
                                "topdown": "reviewable",
                            },
                            "passed_gates": ["source_asset_available", "preview_metadata"],
                            "required_gates": [
                                "source_asset_available",
                                "preview_metadata",
                                "public_room_count",
                                "public_waypoints",
                                "trusted_category_provenance",
                                "map_build_artifacts",
                            ],
                            "missing_gates": [
                                "public_room_count",
                                "public_waypoints",
                                "trusted_category_provenance",
                                "map_build_artifacts",
                            ],
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    plan = scanner_execution_plan(candidate_indices=tuple(range(40)))
    holodeck = plan["sources"]["holodeck-objaverse-val"]

    assert 22 in plan["candidate_indices"]
    assert plan["summary"]["candidate_count"] == 1
    assert plan["summary"]["ready_for_product_smoke_count"] == 1
    assert holodeck["prep_status"] == "ready_for_scanner"
    assert holodeck["candidates"][0]["scanner_status"] == "ready_for_product_smoke"
    assert holodeck["candidates"][0]["world_id"] == "molmospaces/holodeck-objaverse-val/22"
    assert (
        "render_scene_previews.py --world molmospaces/holodeck-objaverse-val/22"
        in (holodeck["candidates"][0]["preview_command"])
    )
    assert (
        "world=molmospaces/holodeck-objaverse-val/22"
        in (holodeck["candidates"][0]["map_build_product_smoke_command"])
    )


def test_scene_sampler_scanner_execution_plan_does_not_rerun_rejected_metadata_candidates(
    monkeypatch,
    tmp_path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    candidate_path = tmp_path / "val_22.xml"
    candidate_path.write_text("<mujoco />", encoding="utf-8")
    monkeypatch.setattr(
        scene_sampler,
        "source_prep_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "prep_status": (
                        "ready_for_scanner" if source == "holodeck-objaverse-val" else "complete"
                    ),
                    "install_candidates": [
                        {
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "primary_path": str(candidate_path),
                            "path_status": "available",
                            "paths": [
                                {
                                    "role": "base",
                                    "path": str(candidate_path),
                                    "exists": True,
                                }
                            ],
                            "missing_paths": [],
                            "install_command": "",
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler,
        "scanner_admission_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "admission_rows": [
                        {
                            "scene_family": "holodeck-objaverse",
                            "scene_split": "val",
                            "scene_source": "holodeck-objaverse-val",
                            "scene_index": 22,
                            "world_id": "molmospaces/holodeck-objaverse-val/22",
                            "readiness_status": READINESS_REJECTED,
                            "admission_status": "rejected",
                            "lanes": [],
                            "failure_class": "map_actionability_failure",
                            "blocked_reason": "fewer_than_three_public_navigation_areas",
                            "selected_reason": "fewer_than_three_public_navigation_areas",
                            "room_count": 1,
                            "waypoint_count": 2,
                            "category_provenance": "source_metadata",
                            "preview_statuses": {
                                "fpv": "reviewable",
                                "map": "reviewable",
                                "chase": "reviewable",
                                "topdown": "reviewable",
                            },
                            "passed_gates": [],
                            "required_gates": [
                                "source_asset_available",
                                "preview_metadata",
                                "public_room_count",
                                "public_waypoints",
                                "trusted_category_provenance",
                                "map_build_artifacts",
                            ],
                            "missing_gates": [],
                        }
                    ]
                    if source == "holodeck-objaverse-val"
                    else [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    plan = scanner_execution_plan(candidate_indices=tuple(range(40)))
    holodeck = plan["sources"]["holodeck-objaverse-val"]

    assert plan["summary"]["candidate_count"] == 1
    assert plan["summary"]["ready_for_product_smoke_count"] == 0
    assert plan["summary"]["blocked_count"] == 1
    assert holodeck["candidates"][0]["scanner_status"] == "rejected_by_admission"
    assert holodeck["candidates"][0]["next_action"] == ("do_not_scan_without_new_human_curation")


def test_scene_sampler_source_prep_install_command_resolves_dict_scene_refs() -> None:
    from roboclaws.worlds.molmospaces.preparation import install_candidate_command

    command = install_candidate_command(
        dataset_name="procthor-10k",
        split="val",
        scene_index=4,
    )

    assert 'mapping = get_scenes("procthor-10k", "val")["val"]' in command
    assert "scene_ref = mapping[4]" in command
    assert "_scene_xml_path_from_ref(scene_ref, get_scenes_root())" in command
    assert "for role in ('base', 'physics', 'ceiling')" in command
    assert "install_scene_with_objects_and_grasps_from_path(scene_path)" in command


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"valid JSON object: .*preview\.json",
        ),
        (
            "[]\n",
            r"scene sampler preview metadata source must contain a JSON object: .*preview\.json",
        ),
    ],
)
def test_scene_sampler_preview_metadata_rejects_bad_sources(
    monkeypatch,
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(scene_sampler, "_PREVIEW_ROOT", tmp_path)
    (tmp_path / "molmospaces-val_4-preview.json").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        scene_sampler._preview_metadata(4)


def test_scene_sampler_preview_metadata_rejects_missing_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(scene_sampler, "_PREVIEW_ROOT", tmp_path)

    with pytest.raises(
        ValueError,
        match=r"missing preview metadata for scene 4: .*molmospaces-val_4-preview\.json",
    ):
        scene_sampler._preview_metadata(4)


def test_scene_sampler_preview_metadata_loads_valid_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(scene_sampler, "_PREVIEW_ROOT", tmp_path)
    payload = {
        "scene_source": "procthor-10k-val",
        "scene_index": 4,
        "backend": scene_sampler.PRIMARY_MOLMOSPACES_BACKEND,
    }
    (tmp_path / "molmospaces-val_4-preview.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    assert scene_sampler._preview_metadata(4) == payload


def test_scene_sampler_scanner_admission_report_records_missing_gates(monkeypatch) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    report = scanner_admission_report(candidate_indices=tuple(range(10)))

    assert report["schema"] == "molmospaces_scene_sampler_scanner_admission_v1"
    assert report["probe_mode"] == "no_download_no_backend_no_vlm"
    assert report["summary"]["admitted_count"] == 16
    assert report["summary"]["blocked_count"] == 3
    assert report["summary"]["rejected_count"] == TOTAL_REJECTED_ROW_COUNT
    assert report["summary"]["missing_gate_counts"] == {
        "source_asset_available": 3,
        "preview_metadata": 3,
        "public_room_count": 3,
        "public_waypoints": 3,
        "trusted_category_provenance": 3,
        "map_build_artifacts": 3,
    }
    procthor = report["sources"]["procthor-10k-val"]
    val_0 = next(item for item in procthor["admission_rows"] if item["scene_index"] == 0)
    assert val_0["admission_status"] == "admitted"
    assert val_0["lanes"] == [UI_LANE, EVAL_STRESS_LANE]
    assert val_0["failure_class"] == ""
    val_1 = next(item for item in procthor["admission_rows"] if item["scene_index"] == 1)
    assert val_1["admission_status"] == "rejected"
    assert val_1["failure_class"] == "map_actionability_failure"
    val_10 = next(item for item in procthor["admission_rows"] if item["scene_index"] == 10)
    assert val_10["admission_status"] == "admitted"
    assert val_10["lanes"] == [EVAL_STRESS_LANE]

    objaverse = report["sources"]["procthor-objaverse-val"]
    objaverse_0 = next(item for item in objaverse["admission_rows"] if item["scene_index"] == 0)
    assert objaverse_0["admission_status"] == "admitted"
    assert objaverse_0["category_provenance"] == "source_metadata"
    objaverse_2 = next(item for item in objaverse["admission_rows"] if item["scene_index"] == 2)
    assert objaverse_2["admission_status"] == "rejected"
    assert objaverse_2["failure_class"] == "map_actionability_failure"

    holodeck = report["sources"]["holodeck-objaverse-val"]
    holodeck_0 = next(item for item in holodeck["admission_rows"] if item["scene_index"] == 0)
    assert holodeck_0["admission_status"] == "rejected"
    assert holodeck_0["failure_class"] == "map_actionability_failure"
    assert holodeck_0["blocked_reason"] == "fewer_than_three_public_navigation_areas"
    assert holodeck_0["category_provenance"] == "source_metadata"
    assert holodeck_0["missing_gates"] == []
    assert holodeck_0["next_action"] == "do_not_scan_without_new_human_curation"

    ithor = report["sources"]["ithor"]
    assert ithor["needed_ui_count"] == 3
    assert ithor["needed_eval_count"] == 10
    assert ithor["admission_rows"][0]["world_id"] == "molmospaces/ithor/0"
    assert ithor["admission_rows"][0]["admission_status"] == "blocked"
    ithor_1 = next(item for item in ithor["admission_rows"] if item["scene_index"] == 1)
    assert ithor_1["admission_status"] == "rejected"
    assert ithor_1["blocked_reason"] == "fewer_than_three_public_navigation_areas"


def test_scene_sampler_scanner_admission_accepts_reviewable_prepared_label_packets(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "candidate_readiness_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "ui_ready_count": 0,
                    "eval_ready_count": 0,
                    "candidates": []
                    if source != "ithor"
                    else [
                        {
                            "scene_family": "ithor",
                            "scene_split": "not_applicable",
                            "scene_source": "ithor",
                            "scene_index": 1,
                            "world_id": "molmospaces/ithor/1",
                            "readiness_status": READINESS_BLOCKED,
                            "lanes": [],
                            "eval_ready": False,
                            "failure_class": "environment_blocked",
                            "blocked_reason": "map build product smoke pending",
                            "selected_reason": "scanner_candidate_ready_for_product_smoke",
                            "room_count": 4,
                            "waypoint_count": 4,
                            "category_provenance": "prepared_visual_label_manifest",
                            "preview_statuses": {
                                "fpv": "reviewable",
                                "map": "reviewable",
                                "chase": "reviewable",
                                "topdown": "reviewable",
                            },
                            "candidate_file": {
                                "exists": True,
                                "path": "/tmp/FloorPlan1_physics.xml",
                            },
                        }
                    ],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )
    monkeypatch.setattr(
        scene_sampler,
        "selection_gap_report",
        lambda *, candidate_indices: {
            "sources": {
                source: {
                    "ui_needed_count": 3 if source == "ithor" else 0,
                    "eval_needed_count": 10 if source == "ithor" else 0,
                    "next_scan_candidates": [],
                }
                for source in scene_sampler.SUPPORTED_SCENE_SOURCES
            }
        },
    )

    report = scanner_admission_report(candidate_indices=(1,))
    row = report["sources"]["ithor"]["admission_rows"][0]

    assert row["admission_status"] == "blocked"
    assert row["passed_gates"] == [
        "source_asset_available",
        "preview_metadata",
        "public_room_count",
        "public_waypoints",
        "trusted_category_provenance",
    ]
    assert row["missing_gates"] == ["map_build_artifacts"]
    assert row["next_action"] == "run_map_build_product_smoke_before_eval_admission"


def test_scene_sampler_scanner_execution_plan_skips_prefilter_inconclusive_sources(
    monkeypatch,
) -> None:
    import roboclaws.worlds.molmospaces.sampling as scene_sampler

    monkeypatch.setattr(
        scene_sampler,
        "_molmospaces_module_status",
        lambda: (False, "module_not_importable:molmo_spaces", ""),
    )

    plan = scanner_execution_plan(candidate_indices=tuple(range(11)))
    ithor = plan["sources"]["ithor"]

    assert plan["schema"] == "molmospaces_scene_sampler_scanner_execution_plan_v1"
    assert plan["download_policy"] == "manual_operator_only"
    assert plan["summary"]["candidate_count"] == 2
    assert plan["summary"]["ready_for_product_smoke_count"] == 0
    assert plan["summary"]["blocked_count"] == 2
    assert plan["summary"]["blocked_source_count"] == 1
    procthor = plan["sources"]["procthor-10k-val"]
    assert procthor["prep_status"] == "blocked_prefilter_inconclusive"
    assert procthor["candidate_count"] == 2
    assert procthor["blocked_count"] == 2
    assert ithor["prep_status"] == "blocked_prefilter_inconclusive"
    assert ithor["candidates"] == []
