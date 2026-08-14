from __future__ import annotations

from pathlib import Path

from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.planner_proof_requests import (
    build_probe_commands,
    planner_proof_requests_from_substeps,
)
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary


def test_planner_proof_requests_record_blocked_binding() -> None:
    manifest = planner_proof_requests_from_substeps(
        contract=object(),
        substeps=[
            {
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "steps": [{"phase": "place"}],
            }
        ],
    )

    assert manifest["ready_count"] == 0
    assert manifest["blockers"][0]["code"] == "planner_binding_unavailable"
    assert manifest["requests"][0]["ready"] is False


def test_proof_request_selection_excludes_prior_task_feasibility_blocked(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "request_count": 2,
        "ready_count": 2,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "planner_probe_args": {"--cleanup-object-id": "observed_001"},
            },
            {
                "request_id": "proof_002",
                "ready": True,
                "object_id": "observed_002",
                "target_receptacle_id": "shelf_01",
                "planner_probe_args": {"--cleanup-object-id": "observed_002"},
            },
        ],
    }
    prior_summary = {
        "schema": "planner_cleanup_proof_result_summary_v1",
        "results": [
            {
                "request_id": "proof_001",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "run_result": str(tmp_path / "prior" / "run_result.json"),
                "report": str(tmp_path / "prior" / "report.html"),
                "stdout": str(tmp_path / "prior" / "stdout.txt"),
                "stderr": str(tmp_path / "prior" / "stderr.txt"),
                "last_worker_stage": "worker_exception",
                "execution_attempted": True,
                "blockers": [{"code": "HouseInvalidForTask"}],
            }
        ],
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
    )
    commands = build_probe_commands(
        manifest=manifest,
        output_dir=tmp_path,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        request_selection=selection,
    )

    assert selection["schema"] == "planner_cleanup_proof_request_selection_v1"
    assert selection["selected_request_ids"] == ["proof_002"]
    assert selection["excluded_requests"][0]["request_id"] == "proof_001"
    assert selection["excluded_requests"][0]["reason"] == "prior_task_feasibility_blocked"
    assert selection["excluded_requests"][0]["prior_result_match_kind"] == "request_id"
    assert selection["excluded_requests"][0]["prior_report"] == str(
        tmp_path / "prior" / "report.html"
    )
    assert selection["target_feasibility_blocker_count"] == 1
    assert selection["target_feasibility_blockers"] == [
        {
            "kind": "source_request",
            "source_request_id": "proof_001",
            "object_id": "observed_001",
            "target_receptacle_id": "sink_01",
            "object_alias": "",
            "target_alias": "",
            "derived_from": "",
            "reason": "prior_task_feasibility_blocked",
            "prior_status": "blocked_capability",
            "prior_task_feasibility_status": "blocked",
            "prior_blockers": [{"code": "HouseInvalidForTask"}],
            "prior_run_result": str(tmp_path / "prior" / "run_result.json"),
            "prior_report": str(tmp_path / "prior" / "report.html"),
            "prior_stdout": str(tmp_path / "prior" / "stdout.txt"),
            "prior_stderr": str(tmp_path / "prior" / "stderr.txt"),
            "last_worker_stage": "worker_exception",
            "execution_attempted": True,
            "prior_result_match_kind": "request_id",
        }
    ]
    assert selection["fallback_required"] is False
    assert len(commands) == 1
    assert commands[0]["request_id"] == "proof_002"


def test_proof_request_selection_marks_fallback_required_when_all_ready_blocked() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "planner_probe_args": {"--cleanup-object-id": "observed_001"},
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
    )

    assert selection["selected_count"] == 0
    assert selection["excluded_count"] == 1
    assert selection["target_feasibility_blocker_count"] == 1
    assert selection["fallback_required"] is True


def test_proof_request_selection_surfaces_grasp_feasibility_blockers() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
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
                "request_id": "proof_001",
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
    assert excluded["prior_result_match_kind"] == "request_id"
    assert excluded["prior_task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert excluded["prior_task_feasibility_blocker_summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )
    assert selection["target_feasibility_blocker_count"] == 1
    assert selection["grasp_feasibility_blocker_count"] == 1
    grasp_blocker = selection["grasp_feasibility_blockers"][0]
    assert grasp_blocker["source_request_id"] == "proof_001"
    assert grasp_blocker["kind"] == "source_request"
    assert grasp_blocker["prior_result_match_kind"] == "request_id"
    assert grasp_blocker["prior_task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert grasp_blocker["prior_task_feasibility_blocker_summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )


def test_proof_request_selection_discovers_runtime_alias_siblings_from_keyerror() -> None:
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
    valid_names = [
        "book_beef_1_0_8",
        "book_beef_1_1_8",
        "book_beef_1_2_8",
        "shelf_cafe_1_0_2",
        "shelf_cafe_1_1_2",
        "sink_other_1_1_5",
    ]
    prior_summary = {
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
                    "planner_object_id": "book_beef_1_0_8",
                    "planner_target_receptacle_id": "ShelvingUnit|2|3",
                },
                "blockers": [
                    {
                        "code": "KeyError",
                        "message": (
                            f"\"Invalid name 'ShelvingUnit|2|3'. Valid names: {valid_names}\""
                        ),
                    }
                ],
            },
            {
                "request_id": "proof_001_fallback_02",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "cleanup_task_config": {
                    "planner_object_id": "Book|surface|8|79",
                    "planner_target_receptacle_id": "shelf_cafe_1_0_2",
                },
                "blockers": [
                    {
                        "code": "KeyError",
                        "message": (
                            f"\"Invalid name 'Book|surface|8|79'. Valid names: {valid_names}\""
                        ),
                    }
                ],
            },
        ]
    }

    selection = proof_request_selection_from_summary(
        manifest,
        prior_proof_result_summary=prior_summary,
        exclude_task_feasibility_blocked=True,
        generate_fallback_requests=True,
        fallback_alias_limit=2,
    )

    assert selection["fallback_required"] is False
    assert selection["generated_fallback_request_count"] == 1
    fallback_generation = selection["fallback_generation"]
    assert fallback_generation["discovered_alias_count"] == 3
    assert fallback_generation["normalized_alias_count"] == 2
    assert {
        (item["alias"], item["normalized_alias"], item["reason"])
        for item in fallback_generation["normalized_aliases"]
    } == {
        ("book_beef_1_1_8", "book_beef_1_0_8", "pickup_root_variant_normalized"),
        ("book_beef_1_2_8", "book_beef_1_0_8", "pickup_root_variant_normalized"),
    }
    assert {
        (item["axis"], item["alias"], item["derived_from"])
        for item in fallback_generation["discovered_aliases"]
    } == {
        ("target", "shelf_cafe_1_1_2", "proof_001_fallback_01"),
        ("object", "book_beef_1_1_8", "proof_001_fallback_02"),
        ("object", "book_beef_1_2_8", "proof_001_fallback_02"),
    }
    generated = fallback_generation["generated_requests"]
    assert generated[0]["planner_probe_args"]["--cleanup-planner-target-receptacle-id"] == (
        "shelf_cafe_1_1_2"
    )
    assert generated[0]["planner_probe_args"]["--cleanup-planner-object-id"] == ("book_beef_1_0_8")
    assert {
        (item["axis"], item["alias"], item["reason"])
        for item in fallback_generation["filtered_aliases"]
    } == {
        ("object", "Book|surface|8|79", "not_exact_scene_runtime_alias"),
        ("target", "ShelvingUnit|2|3", "not_exact_scene_runtime_alias"),
        ("object", "book_beef_1_1_8", "not_pickup_root_body_alias"),
        ("object", "book_beef_1_2_8", "not_pickup_root_body_alias"),
    }


def test_proof_request_selection_filters_prior_failed_runtime_candidates() -> None:
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
            ]
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
                "task_feasibility_blocker_kind": "grasp_feasibility",
                "task_feasibility_blocker_summary": (
                    "17 grasp failures; 15 candidate-removal calls"
                ),
                "cleanup_task_config": {
                    "planner_object_id": "book_beef_1_0_8",
                    "planner_target_receptacle_id": "shelf_cafe_1_1_2",
                },
                "blockers": [{"code": "HouseInvalidForTask"}],
            },
            {
                "request_id": "proof_001_fallback_02",
                "status": "blocked_capability",
                "task_feasibility_status": "blocked",
                "cleanup_task_config": {
                    "planner_object_id": "book_beef_1_1_8",
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
        "grasp_feasibility_blocked_pairs",
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
        ("object", "book_beef_1_2_8", "not_pickup_root_body_alias", ""),
    }
    assert fallback_generation["filtered_pair_count"] == 1
    filtered_pair = fallback_generation["filtered_pairs"][0]
    assert {
        key: filtered_pair[key]
        for key in (
            "source_request_id",
            "object_alias",
            "target_alias",
            "derived_from",
            "reason",
            "prior_status",
            "prior_task_feasibility_status",
            "prior_task_feasibility_blocker_kind",
            "prior_task_feasibility_blocker_summary",
            "last_worker_stage",
            "execution_attempted",
        )
    } == {
        "source_request_id": "proof_001",
        "object_alias": "book_beef_1_0_8",
        "target_alias": "shelf_cafe_1_1_2",
        "derived_from": "proof_001_fallback_01",
        "reason": "prior_task_feasibility_blocked_pair",
        "prior_status": "blocked_capability",
        "prior_task_feasibility_status": "blocked",
        "prior_task_feasibility_blocker_kind": "grasp_feasibility",
        "prior_task_feasibility_blocker_summary": ("17 grasp failures; 15 candidate-removal calls"),
        "last_worker_stage": "",
        "execution_attempted": False,
    }
    assert filtered_pair["prior_blockers"] == [{"code": "HouseInvalidForTask"}]
