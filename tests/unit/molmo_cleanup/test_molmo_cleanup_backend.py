from __future__ import annotations

from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.scenario import build_cleanup_scenario


def test_backend_pick_and_place_mutate_semantic_location_with_provenance() -> None:
    backend = ApiSemanticCleanupBackend(build_cleanup_scenario(seed=7))

    pick = backend.pick("mug_01")
    place = backend.place("sink_01")

    assert pick["ok"] is True
    assert pick["primitive_provenance"] == API_SEMANTIC_PROVENANCE
    assert pick["previous_location_id"] == "sofa_01"
    assert place["ok"] is True
    assert place["primitive_provenance"] == API_SEMANTIC_PROVENANCE
    assert backend.object_locations()["mug_01"] == "sink_01"
    assert backend.held_object_id is None


def test_backend_reports_stale_reference_errors_without_crashing() -> None:
    backend = ApiSemanticCleanupBackend(build_cleanup_scenario(seed=7))

    missing_object = backend.pick("missing_object")
    missing_receptacle = backend.navigate_to_receptacle("missing_receptacle")

    assert missing_object["ok"] is False
    assert missing_object["error_reason"] == "stale_reference"
    assert missing_receptacle["ok"] is False
    assert missing_receptacle["error_reason"] == "stale_reference"


def test_backend_rejects_invalid_hold_state_transitions() -> None:
    backend = ApiSemanticCleanupBackend(build_cleanup_scenario(seed=7))

    no_object = backend.place("sink_01")
    first_pick = backend.pick("mug_01")
    second_pick = backend.pick("book_01")

    assert no_object["error_reason"] == "not_holding"
    assert first_pick["ok"] is True
    assert second_pick["ok"] is False
    assert second_pick["error_reason"] == "already_holding"


def test_backend_done_scores_private_manifest_after_cleanup() -> None:
    backend = ApiSemanticCleanupBackend(build_cleanup_scenario(seed=7))

    for object_id, receptacle_id in (
        ("mug_01", "sink_01"),
        ("book_01", "bookshelf_01"),
        ("towel_01", "laundry_hamper_01"),
    ):
        assert backend.pick(object_id)["ok"] is True
        assert backend.place(receptacle_id)["ok"] is True

    done = backend.done(reason="cleaned enough")

    assert done["cleanup_status"] == "success"
    assert done["score"]["restored_count"] == 3
    assert done["tool_event_counts"]["pick:request"] == 3
    assert done["tool_event_counts"]["place:request"] == 3
