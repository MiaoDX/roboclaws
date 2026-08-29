from __future__ import annotations

import pytest

from roboclaws.backends.molmospaces.scenario_state import target_start_receptacle_id
from roboclaws.household.generated_mess import (
    build_generated_mess_manifest,
    generated_mess_public_distractor_settlement_plan,
    targets_from_generated_mess_manifest,
)
from roboclaws.household.semantic_acceptability import public_source_requires_cleanup


def test_generated_mess_manifest_uses_public_cleanup_required_starts() -> None:
    receptacles = [
        {"receptacle_id": "fridge_01", "category": "Fridge"},
        {"receptacle_id": "tvstand_01", "category": "TVStand"},
        {"receptacle_id": "counter_01", "category": "CounterTop"},
        {"receptacle_id": "table_01", "category": "DiningTable"},
        {"receptacle_id": "desk_01", "category": "Desk"},
        {"receptacle_id": "sofa_01", "category": "Sofa"},
        {"receptacle_id": "coffee_01", "category": "CoffeeTable"},
        {"receptacle_id": "bed_01", "category": "Bed"},
        {"receptacle_id": "sink_01", "category": "Sink"},
    ]
    objects = [
        {"object_id": "apple_01", "category": "Apple"},
        {"object_id": "remote_01", "category": "RemoteControl"},
    ]

    manifest = build_generated_mess_manifest(objects, receptacles, target_count=2, seed=7)
    receptacle_by_id = {item["receptacle_id"]: item for item in receptacles}

    assert manifest["selection"]["start_semantics"] == "public_cleanup_required_v1"
    assert all(
        public_source_requires_cleanup(
            target["category"],
            receptacle_by_id[target["start_receptacle_id"]]["category"],
        )
        for target in manifest["targets"]
    )
    starts_by_category = {
        target["category"]: receptacle_by_id[target["start_receptacle_id"]]["category"]
        for target in manifest["targets"]
    }
    assert starts_by_category["Apple"] not in {"CounterTop", "DiningTable"}
    assert starts_by_category["RemoteControl"] not in {"Desk", "Sofa", "CoffeeTable"}


def test_generated_mess_accepts_every_public_semantic_destination() -> None:
    receptacles = [
        {"receptacle_id": "bed_01", "category": "Bed"},
        {"receptacle_id": "bed_02", "category": "Bed"},
        {"receptacle_id": "sofa_01", "category": "Sofa"},
        {"receptacle_id": "table_01", "category": "DiningTable"},
    ]

    manifest = build_generated_mess_manifest(
        [{"object_id": "pillow_01", "category": "Pillow"}],
        receptacles,
        target_count=1,
        seed=7,
    )

    assert manifest["targets"][0]["target_receptacle_id"] == "bed_01"
    assert manifest["targets"][0]["valid_receptacle_ids"] == [
        "bed_01",
        "bed_02",
        "sofa_01",
    ]


def test_generated_mess_manifest_rejects_missing_public_cleanup_start() -> None:
    with pytest.raises(ValueError, match="no public cleanup-required start receptacle"):
        build_generated_mess_manifest(
            [{"object_id": "plate_01", "category": "Plate"}],
            [{"receptacle_id": "sink_01", "category": "Sink"}],
            target_count=1,
            seed=7,
        )


def test_generated_mess_manifest_avoids_same_category_source_distractor() -> None:
    receptacles = [
        {"receptacle_id": "shelf_01", "category": "ShelvingUnit", "position": [0, 0]},
        {"receptacle_id": "bed_01", "category": "Bed", "position": [1, 0]},
        {"receptacle_id": "bed_02", "category": "Bed", "position": [2, 0]},
    ]
    objects = [
        {"object_id": "target_book", "category": "Book", "position": [0, 0]},
        {"object_id": "other_book", "category": "Newspaper", "position": [1, 0]},
    ]

    manifest = build_generated_mess_manifest(
        objects,
        receptacles,
        target_count=1,
        seed=7,
        object_ids=["target_book"],
    )

    assert manifest["targets"][0]["object_id"] == "target_book"
    assert manifest["targets"][0]["start_receptacle_id"] == "bed_02"


def test_generated_mess_manifest_rejects_when_all_starts_have_category_distractors() -> None:
    receptacles = [
        {"receptacle_id": "shelf_01", "category": "ShelvingUnit"},
        {"receptacle_id": "bed_01", "category": "Bed"},
        {"receptacle_id": "bed_02", "category": "Bed"},
    ]
    objects = [
        {"object_id": "target_book", "category": "Book"},
        {"object_id": "other_book", "category": "Book", "location_id": "bed_01"},
        {
            "object_id": "other_newspaper",
            "category": "Newspaper",
            "contained_in": "bed_02",
        },
    ]

    with pytest.raises(ValueError, match="no publicly identifiable cleanup start"):
        build_generated_mess_manifest(
            objects,
            receptacles,
            target_count=1,
            seed=7,
            object_ids=["target_book"],
        )


def test_generated_mess_manifest_prefers_explicit_distractor_location_over_nearest() -> None:
    receptacles = [
        {"receptacle_id": "shelf_01", "category": "ShelvingUnit", "position": [0, 0]},
        {"receptacle_id": "bed_01", "category": "Bed", "position": [1, 0]},
        {"receptacle_id": "bed_02", "category": "Bed", "position": [5, 0]},
    ]
    objects = [
        {"object_id": "target_book", "category": "Book", "position": [0, 0]},
        {
            "object_id": "other_book",
            "category": "Book",
            "location_id": "bed_02",
            "position": [1, 0],
        },
    ]

    manifest = build_generated_mess_manifest(
        objects,
        receptacles,
        target_count=1,
        seed=7,
        object_ids=["target_book"],
    )

    assert manifest["targets"][0]["start_receptacle_id"] == "bed_01"


def test_generated_mess_background_settlement_uses_public_semantics() -> None:
    receptacles = [
        {"receptacle_id": "sink_01", "category": "Sink"},
        {"receptacle_id": "shelf_01", "category": "ShelvingUnit"},
        {"receptacle_id": "tvstand_01", "category": "TVStand"},
        {"receptacle_id": "bed_01", "category": "Bed"},
        {"receptacle_id": "desk_01", "category": "Desk"},
    ]
    objects = [
        {"object_id": "target_plate", "category": "Plate", "location_id": "bed_01"},
        {"object_id": "wrong_book", "category": "Book", "location_id": "bed_01"},
        {"object_id": "settled_book", "category": "Book", "location_id": "desk_01"},
        {"object_id": "wrong_remote", "category": "RemoteControl", "location_id": "bed_01"},
        {"object_id": "unmanaged_vase", "category": "Vase", "location_id": "bed_01"},
    ]

    plan = generated_mess_public_distractor_settlement_plan(
        objects,
        receptacles,
        excluded_object_ids={"target_plate"},
    )

    assert plan == [
        {
            "object_id": "wrong_book",
            "category": "Book",
            "source_receptacle_id": "bed_01",
            "target_receptacle_id": "shelf_01",
        },
        {
            "object_id": "wrong_remote",
            "category": "RemoteControl",
            "source_receptacle_id": "bed_01",
            "target_receptacle_id": "tvstand_01",
        },
    ]


def test_explicit_generated_mess_manifest_can_keep_public_acceptable_start() -> None:
    receptacles = [
        {"receptacle_id": "fridge_01", "category": "Fridge"},
        {"receptacle_id": "counter_01", "category": "CounterTop"},
    ]
    objects = [{"object_id": "potato_01", "category": "Potato"}]
    manifest = {
        "schema": "roboclaws_generated_mess_manifest_v1",
        "targets": [
            {
                "object_id": "potato_01",
                "target_receptacle_id": "fridge_01",
                "valid_receptacle_ids": ["fridge_01"],
                "start_receptacle_id": "counter_01",
                "relation": "on",
                "placement_index": 0,
            }
        ],
    }

    selected = targets_from_generated_mess_manifest(
        objects,
        receptacles,
        manifest,
        target_count=1,
    )

    assert selected[0]["start_receptacle_id"] == "counter_01"


def test_runtime_uses_actual_seeded_start_receptacle() -> None:
    target = {
        "object_id": "plate_01",
        "target_receptacle_id": "sink_01",
    }
    state = {
        "objects": {
            "plate_01": {"seeded_start_receptacle_id": "bed_01"},
        },
        "receptacles": {
            "sink_01": {"receptacle_id": "sink_01"},
            "sofa_01": {"receptacle_id": "sofa_01"},
            "bed_01": {"receptacle_id": "bed_01"},
        },
    }

    assert target_start_receptacle_id(state, target) == "bed_01"
