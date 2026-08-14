from __future__ import annotations

from pathlib import Path

from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from roboclaws.household.planner_observed_binding import (
    OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
)
from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.planner_proof_requests import (
    build_probe_commands,
    write_planner_proof_requests,
)
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary
from tests.unit.molmo_cleanup.molmo_planner_proof_requests_support import (
    _BindingContract,
)


def test_planner_proof_requests_preserve_bound_probe_args(tmp_path: Path) -> None:
    contract = _BindingContract()
    substeps = [
        {
            "object_id": "observed_001",
            "source_receptacle_id": "counter_01",
            "target_receptacle_id": "sink_01",
            "steps": [
                {"phase": "navigate_to_object"},
                {"phase": "pick"},
                {"phase": "navigate_to_receptacle"},
                {"phase": "place"},
                {"phase": "object_done"},
            ],
        }
    ]

    manifest = write_planner_proof_requests(
        output_path=tmp_path / "planner_proof_requests.json",
        contract=contract,
        substeps=substeps,
    )

    assert manifest["schema"] == PLANNER_PROOF_REQUESTS_SCHEMA
    assert manifest["request_count"] == 1
    assert manifest["ready_count"] == 1
    assert manifest["agent_view_exposed"] is False
    request = manifest["requests"][0]
    assert request["request_id"] == "proof_001"
    assert request["object_id"] == "observed_001"
    assert request["source_receptacle_id"] == "counter_01"
    assert request["target_receptacle_id"] == "sink_01"
    assert request["tools"] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]
    assert request["binding"]["schema"] == OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA
    assert request["planner_probe_args"]["--cleanup-object-id"] == "observed_001"
    assert request["planner_probe_args"]["--cleanup-planner-object-id"] == "pickup/body"
    assert manifest["planner_scene"]["scene_xml"] == "/tmp/molmospaces-scene.xml"
    assert (tmp_path / "planner_proof_requests.json").is_file()


def test_proof_request_selection_matches_prior_result_by_cleanup_pair() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_regenerated",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "planner_probe_args": {"--cleanup-object-id": "observed_001"},
            }
        ],
    }
    prior_summary = {
        "results": [
            {
                "request_id": "proof_old",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "task_feasibility_blocker_kind": "grasp_feasibility",
                "task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "blockers": [{"code": "HouseInvalidForTask"}],
            }
        ]
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
    )

    excluded = selection["excluded_requests"][0]
    assert excluded["request_id"] == "proof_regenerated"
    assert excluded["prior_result_match_kind"] == "object_target"
    assert excluded["prior_task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert selection["selected_request_ids"] == []
    assert selection["grasp_feasibility_blocker_count"] == 1
    assert selection["grasp_feasibility_blockers"][0]["prior_result_match_kind"] == (
        "object_target"
    )


def test_proof_request_selection_ignores_colliding_request_id_for_different_pair() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "fridge_01",
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-planner-object-id": "apple_runtime_1_0_2",
                    "--cleanup-planner-target-receptacle-id": "fridge_runtime_1_0_2",
                },
            }
        ],
    }
    prior_summary = {
        "results": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "cleanup_task_config": {
                    "planner_object_id": "book_runtime_1_0_8",
                    "planner_target_receptacle_id": "shelf_runtime_1_0_2",
                },
                "blockers": [{"code": "HouseInvalidForTask"}],
            }
        ]
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
    )

    assert selection["selected_request_ids"] == ["proof_001"]
    assert selection["excluded_requests"] == []
    assert selection["target_feasibility_blocker_count"] == 0


def test_proof_request_selection_ignores_local_ids_when_planner_object_differs() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_003",
                "ready": True,
                "object_id": "observed_003",
                "target_receptacle_id": "fridge_01",
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_003",
                    "--cleanup-planner-object-id": "lettuce_runtime_1_0_2",
                    "--cleanup-planner-target-receptacle-id": "fridge_runtime_1_0_2",
                },
            }
        ],
    }
    prior_summary = {
        "results": [
            {
                "request_id": "proof_003",
                "object_id": "observed_003",
                "target_receptacle_id": "fridge_01",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "cleanup_task_config": {
                    "planner_object_id": "bread_runtime_1_0_2",
                    "planner_target_receptacle_id": "fridge_runtime_1_0_2",
                },
                "blockers": [{"code": "HouseInvalidForTask"}],
            }
        ]
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
    )

    assert selection["selected_request_ids"] == ["proof_003"]
    assert selection["excluded_requests"] == []
    assert selection["target_feasibility_blocker_count"] == 0


def test_proof_request_selection_matches_prior_result_by_planner_object_target() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_new",
                "ready": True,
                "object_id": "observed_009",
                "target_receptacle_id": "shelf_01",
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_009",
                    "--cleanup-planner-object-id": "book_runtime_1_0_8",
                    "--cleanup-planner-target-receptacle-id": "shelf_runtime_1_0_2",
                },
            }
        ],
    }
    prior_summary = {
        "results": [
            {
                "request_id": "standalone_observed_001_to_shelf_01",
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "task_feasibility_blocker_kind": "grasp_feasibility",
                "task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "cleanup_task_config": {
                    "planner_object_id": "book_runtime_1_0_8",
                    "planner_target_receptacle_id": "shelf_runtime_1_1_2",
                },
                "blockers": [{"code": "HouseInvalidForTask"}],
            }
        ]
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
    )

    excluded = selection["excluded_requests"][0]
    assert excluded["request_id"] == "proof_new"
    assert excluded["prior_result_match_kind"] == "planner_object_target"
    assert excluded["prior_task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert selection["selected_request_ids"] == []
    assert selection["grasp_feasibility_blocker_count"] == 1
    assert selection["grasp_feasibility_blockers"][0]["prior_result_match_kind"] == (
        "planner_object_target"
    )


def test_proof_request_selection_generates_fallback_alias_requests(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "source_receptacle_id": "counter_01",
                "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
                "binding": {
                    "candidate_pickup_names": [
                        "pickup/body",
                        "pickup/alt",
                        "Pickup|surface|1|1",
                    ],
                    "candidate_place_receptacle_names": [
                        "sink/body",
                        "sink/alt",
                        "Sink|1|2",
                    ],
                    "backend_planner_task_binding": {
                        "candidate_pickup_names": [
                            "pickup/body",
                            "pickup/alt",
                            "Pickup|surface|1|1",
                        ],
                        "candidate_place_receptacle_names": [
                            "sink/body",
                            "sink/alt",
                            "Sink|1|2",
                        ],
                    },
                    "requested_cleanup_primitive_binding": {
                        "object_id": "observed_001",
                        "target_receptacle_id": "sink_01",
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                },
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "sink_01",
                    "--cleanup-source-receptacle-id": "counter_01",
                    "--cleanup-tools": "navigate_to_object,pick,navigate_to_receptacle,place",
                    "--cleanup-planner-object-id": "pickup/body",
                    "--cleanup-planner-target-receptacle-id": "sink/body",
                },
            }
        ],
    }
    prior_summary = {
        "results": [
            {
                "request_id": "proof_001",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "task_feasibility_blocker_kind": "grasp_feasibility",
                "task_feasibility_blocker_summary": ("3 grasp failures; 1 candidate-removal calls"),
                "blockers": [{"code": "HouseInvalidForTask"}],
            }
        ]
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=2,
    )
    commands = build_probe_commands(
        manifest=manifest,
        output_dir=tmp_path,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        request_selection=selection,
    )

    assert selection["mode"] == "exclude_task_feasibility_blocked_with_fallbacks"
    assert selection["fallback_required"] is False
    assert selection["excluded_count"] == 1
    assert selection["generated_fallback_request_count"] == 2
    assert selection["selected_request_ids"] == [
        "proof_001_fallback_01",
        "proof_001_fallback_02",
    ]
    assert selection["fallback_generation"]["status"] == "generated"
    generated = selection["fallback_generation"]["generated_requests"]
    assert generated[0]["source_request_id"] == "proof_001"
    assert generated[0]["object_id"] == "observed_001"
    assert generated[0]["target_receptacle_id"] == "sink_01"
    assert generated[0]["fallback_request"]["prior_task_feasibility_blocker_kind"] == (
        "grasp_feasibility"
    )
    assert generated[0]["fallback_request"]["prior_task_feasibility_blocker_summary"] == (
        "3 grasp failures; 1 candidate-removal calls"
    )
    assert generated[0]["fallback_request"]["prior_result_match_kind"] == "request_id"
    assert generated[0]["fallback_request"]["prior_blockers"][0]["code"] == ("HouseInvalidForTask")
    assert generated[0]["planner_probe_args"]["--cleanup-planner-target-receptacle-id"] == (
        "sink/alt"
    )
    assert generated[1]["planner_probe_args"]["--cleanup-planner-object-id"] == ("pickup/alt")
    assert selection["selected_requests"][0]["prior_task_feasibility_blocker_kind"] == (
        "grasp_feasibility"
    )
    assert selection["selected_requests"][0]["prior_result_match_kind"] == "request_id"
    assert selection["fallback_generation"]["filtered_alias_count"] == 2
    assert {
        (item["axis"], item["alias"])
        for item in selection["fallback_generation"]["filtered_aliases"]
    } == {
        ("object", "Pickup|surface|1|1"),
        ("target", "Sink|1|2"),
    }
    assert [item["request_id"] for item in commands] == selection["selected_request_ids"]
    assert "sink/alt" in commands[0]["command"]
    assert "pickup/alt" in commands[1]["command"]


def test_proof_request_selection_filters_non_runtime_fallback_aliases() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "binding": {
                    "candidate_pickup_names": ["pickup/body", "Pickup|surface|1|1"],
                    "candidate_place_receptacle_names": ["sink/body", "Sink|1|2"],
                },
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "sink_01",
                    "--cleanup-planner-object-id": "pickup/body",
                    "--cleanup-planner-target-receptacle-id": "sink/body",
                },
            }
        ],
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary={
            "results": [
                {
                    "request_id": "proof_001",
                    "task_feasibility_status": "blocked",
                    "blockers": [{"code": "HouseInvalidForTask"}],
                }
            ]
        },
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
    )

    assert selection["selected_count"] == 0
    assert selection["generated_fallback_request_count"] == 0
    assert selection["fallback_required"] is True
    fallback_generation = selection["fallback_generation"]
    assert fallback_generation["status"] == "exhausted"
    assert fallback_generation["unavailable_source_request_count"] == 1
    assert fallback_generation["exhaustion_blocker_count"] == 1
    assert fallback_generation["exhaustion_blockers"][0]["code"] == (
        "no_fallback_candidate_available"
    )
    assert fallback_generation["filtered_alias_count"] == 2
    assert {
        (item["axis"], item["alias"], item["reason"])
        for item in fallback_generation["filtered_aliases"]
    } == {
        ("object", "Pickup|surface|1|1", "not_exact_scene_runtime_alias"),
        ("target", "Sink|1|2", "not_exact_scene_runtime_alias"),
    }


def test_proof_request_selection_normalizes_non_root_alias_into_generated_request() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "binding": {
                    "candidate_pickup_names": [
                        "book_beef_1_1_8",
                    ],
                    "candidate_place_receptacle_names": [
                        "shelf_cafe_1_0_2",
                    ],
                },
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "shelf_01",
                    "--cleanup-planner-object-id": "Book|surface|8|79",
                    "--cleanup-planner-target-receptacle-id": "shelf_cafe_1_0_2",
                },
            }
        ],
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary={
            "results": [
                {
                    "request_id": "proof_001",
                    "task_feasibility_status": "blocked",
                    "blockers": [{"code": "HouseInvalidForTask"}],
                }
            ]
        },
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=4,
    )

    fallback_generation = selection["fallback_generation"]
    assert selection["fallback_required"] is False
    assert fallback_generation["status"] == "generated"
    assert fallback_generation["generated_request_count"] == 1
    assert fallback_generation["normalized_aliases"] == [
        {
            "source_request_id": "proof_001",
            "axis": "object",
            "alias": "book_beef_1_1_8",
            "normalized_alias": "book_beef_1_0_8",
            "reason": "pickup_root_variant_normalized",
            "evidence_note": (
                "Normalized a non-root MolmoSpaces runtime pickup alias to "
                "the variant-0 root-body alias before command generation."
            ),
        }
    ]
    generated = fallback_generation["generated_requests"][0]
    assert generated["planner_probe_args"]["--cleanup-planner-object-id"] == "book_beef_1_0_8"
    assert generated["planner_probe_args"]["--cleanup-planner-target-receptacle-id"] == (
        "shelf_cafe_1_0_2"
    )
    assert {
        (item["axis"], item["alias"], item["reason"])
        for item in fallback_generation["filtered_aliases"]
    } == {
        ("object", "Book|surface|8|79", "not_exact_scene_runtime_alias"),
        ("object", "book_beef_1_1_8", "not_pickup_root_body_alias"),
    }


def test_proof_request_selection_reselects_prior_covered_below_quality_horizon() -> None:
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        steps_requested=1,
        steps_executed=1,
        max_abs_qpos_delta=0.01,
    )
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
            }
        ],
    }
    prior_summary = {
        "results": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "status": "planner_backed",
                "planner_backed": True,
                "cleanup_binding_promoted": True,
                "task_feasibility_status": "ready",
                "steps_executed": 1,
                "max_abs_qpos_delta": 0.01,
                "proof_quality": evidence["proof_quality"],
            }
        ]
    }

    one_step_selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_prior_covered=True,
        prior_covered_min_proof_steps=1,
    )
    two_step_selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_prior_covered=True,
        prior_covered_min_proof_steps=2,
    )

    assert one_step_selection["covered_request_count"] == 1
    assert one_step_selection["selected_count"] == 0
    assert two_step_selection["covered_request_count"] == 0
    assert two_step_selection["selected_request_ids"] == ["proof_001"]
    assert two_step_selection["selected_requests"][0]["prior_proof_quality"] == "one_step_motion"
    assert two_step_selection["selected_requests"][0]["prior_steps_executed"] == 1


def test_proof_request_selection_carries_prior_filtered_candidates() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "shelf_01",
                "binding": {
                    "candidate_pickup_names": [
                        "book_beef_1_0_8",
                        "Book|surface|8|79",
                    ],
                    "candidate_place_receptacle_names": [
                        "shelf_cafe_1_0_2",
                        "ShelvingUnit|2|3",
                    ],
                },
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "shelf_01",
                    "--cleanup-planner-object-id": "book_beef_1_0_8",
                    "--cleanup-planner-target-receptacle-id": "shelf_cafe_1_0_2",
                },
            }
        ],
    }
    prior_summary = {
        "fallback_generation": {
            "discovered_aliases": [
                {
                    "source_request_id": "proof_001",
                    "axis": "object",
                    "alias": "book_beef_1_1_8",
                    "derived_from": "proof_001_fallback_02",
                    "invalid_alias": "Book|surface|8|79",
                    "reason": "valid_name_sibling_from_prior_keyerror",
                },
                {
                    "source_request_id": "proof_001",
                    "axis": "object",
                    "alias": "book_beef_1_2_8",
                    "derived_from": "proof_001_fallback_02",
                    "invalid_alias": "Book|surface|8|79",
                    "reason": "valid_name_sibling_from_prior_keyerror",
                },
                {
                    "source_request_id": "proof_001",
                    "axis": "target",
                    "alias": "shelf_cafe_1_1_2",
                    "derived_from": "proof_001_fallback_01",
                    "invalid_alias": "ShelvingUnit|2|3",
                    "reason": "valid_name_sibling_from_prior_keyerror",
                },
            ],
            "filtered_aliases": [
                {
                    "source_request_id": "proof_001",
                    "axis": "object",
                    "alias": "book_beef_1_1_8",
                    "derived_from": "proof_001_fallback_02",
                    "reason": "prior_non_root_body_alias",
                    "prior_blockers": [
                        {
                            "code": "AssertionError",
                            "message": "Object is not a root body",
                        }
                    ],
                }
            ],
            "filtered_pairs": [
                {
                    "source_request_id": "proof_001",
                    "object_alias": "book_beef_1_0_8",
                    "target_alias": "shelf_cafe_1_1_2",
                    "derived_from": "proof_001_fallback_01",
                    "reason": "prior_task_feasibility_blocked_pair",
                    "prior_blockers": [{"code": "HouseInvalidForTask"}],
                }
            ],
        },
        "results": [
            {
                "request_id": "proof_001",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "blockers": [{"code": "HouseInvalidForTask"}],
            },
            {
                "request_id": "proof_001_fallback_01",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "cleanup_task_config": {
                    "planner_object_id": "book_beef_1_2_8",
                    "planner_target_receptacle_id": "shelf_cafe_1_0_2",
                },
                "blockers": [
                    {
                        "code": "AssertionError",
                        "message": "Object is not a root body",
                    }
                ],
            },
        ],
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=4,
    )

    fallback_generation = selection["fallback_generation"]
    assert selection["selected_request_ids"] == []
    assert selection["fallback_required"] is True
    assert fallback_generation["status"] == "exhausted"
    assert fallback_generation["generated_request_count"] == 0
    assert {item["code"] for item in fallback_generation["exhaustion_blockers"]} == {
        "target_task_feasibility_blocked_pairs",
        "no_fallback_candidate_available",
    }
    assert fallback_generation["normalized_alias_count"] == 2
    assert {
        (item["alias"], item["normalized_alias"])
        for item in fallback_generation["normalized_aliases"]
    } == {
        ("book_beef_1_1_8", "book_beef_1_0_8"),
        ("book_beef_1_2_8", "book_beef_1_0_8"),
    }
    assert {
        (item["axis"], item["alias"], item["reason"], item.get("derived_from", ""))
        for item in fallback_generation["filtered_aliases"]
    } == {
        ("object", "Book|surface|8|79", "not_exact_scene_runtime_alias", ""),
        ("target", "ShelvingUnit|2|3", "not_exact_scene_runtime_alias", ""),
        ("object", "book_beef_1_1_8", "prior_non_root_body_alias", "proof_001_fallback_02"),
        ("object", "book_beef_1_2_8", "prior_non_root_body_alias", "proof_001_fallback_01"),
    }
    assert fallback_generation["filtered_pairs"] == [
        {
            "source_request_id": "proof_001",
            "object_alias": "book_beef_1_0_8",
            "target_alias": "shelf_cafe_1_1_2",
            "derived_from": "proof_001_fallback_01",
            "reason": "prior_task_feasibility_blocked_pair",
            "prior_blockers": [{"code": "HouseInvalidForTask"}],
        }
    ]
