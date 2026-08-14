from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from roboclaws.household.manipulation_provenance import planner_backed_probe_evidence
from roboclaws.household.planner_observed_binding import (
    OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
)
from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.planner_proof_requests import (
    build_probe_commands,
    build_probe_warmup_command,
    planner_proof_requests_from_substeps,
    proof_bundle_run_manifest,
    write_planner_proof_requests,
)
from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary
from roboclaws.household.semantic_timeline import canonical_cleanup_tool_sequence


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


def test_build_probe_commands_uses_only_ready_requests(tmp_path: Path) -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "sink_01",
                    "--cleanup-planner-object-id": "pickup/body",
                },
            },
            {
                "request_id": "proof_002",
                "ready": False,
                "object_id": "observed_002",
                "target_receptacle_id": "desk_01",
                "planner_probe_args": {},
            },
        ],
        "planner_scene": {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": True,
            "scene_xml": "~/.cache/molmospaces/scene.xml",
            "backend": "molmospaces_subprocess",
        },
    }

    commands = build_probe_commands(
        manifest=manifest,
        output_dir=tmp_path,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        torch_extensions_dir=Path("torch_ext"),
        task_sampler_robot_placement_profile="relaxed",
    )

    assert len(commands) == 1
    command = commands[0]["command"]
    assert command[:2] == ["python", "probe.py"]
    assert "--cleanup-object-id" in command
    assert "observed_001" in command
    assert "--cleanup-planner-object-id" in command
    assert "pickup/body" in command
    assert "--cleanup-scene-xml" in command
    assert str(Path.home() / ".cache" / "molmospaces" / "scene.xml") in command
    assert "--task-sampler-robot-placement-profile" in command
    assert "relaxed" in command
    assert commands[0]["run_result"].endswith("run_result.json")


def test_build_probe_commands_rewrites_cleanup_tools_in_semantic_order(
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
                "tools": [
                    "navigate_to_object",
                    "pick",
                    "navigate_to_receptacle",
                    "open_receptacle",
                    "place_inside",
                ],
                "planner_probe_args": {
                    "--cleanup-object-id": "observed_001",
                    "--cleanup-target-receptacle-id": "sink_01",
                    "--cleanup-tools": (
                        "navigate_to_object,navigate_to_receptacle,"
                        "open_receptacle,pick,place_inside"
                    ),
                    "--cleanup-planner-object-id": "pickup/body",
                    "--cleanup-planner-target-receptacle-id": "sink/body",
                },
            }
        ],
        "planner_scene": {},
    }

    commands = build_probe_commands(
        manifest=manifest,
        output_dir=tmp_path,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
    )

    command = commands[0]["command"]
    cleanup_tools_arg = command[command.index("--cleanup-tools") + 1]
    assert cleanup_tools_arg == (
        "navigate_to_object,pick,navigate_to_receptacle,open_receptacle,place_inside"
    )
    assert commands[0]["tools"] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place_inside",
    ]


def test_canonical_cleanup_tool_sequence_uses_semantic_order() -> None:
    assert canonical_cleanup_tool_sequence(
        "navigate_to_object,navigate_to_receptacle,open_receptacle,pick,place_inside"
    ) == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place_inside",
    ]


def test_build_probe_warmup_command_uses_config_import_and_shared_cache(
    tmp_path: Path,
) -> None:
    warmup = build_probe_warmup_command(
        output_dir=tmp_path,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        molmospaces_python=Path("molmo-python"),
        molmospaces_root=Path("molmospaces"),
        torch_extensions_dir=Path("torch_ext"),
        timeout_s=900.0,
    )

    command = warmup["command"]
    assert warmup["kind"] == "rby1m_curobo_config_import"
    assert warmup["run_result"].endswith("rby1m_curobo_warmup/run_result.json")
    assert command[:2] == ["python", "probe.py"]
    assert "--probe-mode" in command
    assert "config_import" in command
    assert "--python-executable" in command
    assert "molmo-python" in command
    assert "--molmospaces-root" in command
    assert "molmospaces" in command
    assert "--torch-extensions-dir" in command
    assert "torch_ext" in command
    assert "--timeout-s" in command
    assert "900.0" in command


def test_proof_bundle_manifest_includes_grasp_cache_preflight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    object_dir = tmp_path / "assets" / "objects" / "thor" / "Kitchen Objects" / "Bread"
    object_dir.mkdir(parents=True)
    (object_dir / "Bread_1.xml").write_text("<mujoco />", encoding="utf-8")
    monkeypatch.setenv("MLSPACES_ASSETS_DIR", str(tmp_path / "wrong-assets"))

    manifest = proof_bundle_run_manifest(
        cleanup_run_result=tmp_path / "cleanup" / "run_result.json",
        output_dir=tmp_path / "bundle",
        proof_requests={
            "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
            "request_count": 1,
            "ready_count": 1,
            "requests": [
                {
                    "request_id": "proof_001",
                    "ready": True,
                    "object_id": "observed_001",
                    "target_receptacle_id": "fridge_01",
                    "planner_probe_args": {"--cleanup-object-id": "observed_001"},
                }
            ],
            "planner_scene": {
                "schema": "planner_cleanup_proof_scene_v1",
                "available": True,
                "scene_xml": str(tmp_path / "assets" / "scenes" / "procthor-val" / "val_0.xml"),
            },
        },
        commands=[],
        prior_proof_result_summary={
            "schema": "planner_cleanup_proof_result_summary_v1",
            "results": [
                {
                    "request_id": "proof_001",
                    "object_id": "observed_001",
                    "target_receptacle_id": "fridge_01",
                    "grasp_feasibility_signature": {
                        "schema": "planner_grasp_feasibility_signature_v1",
                        "kind": "grasp_feasibility",
                        "subkind": "grasp_cache_missing",
                        "pattern_key": "missing-cache",
                        "summary": "3 grasp-load failures; missing grasp cache: Bread_1",
                        "grasp_failure_count": 3,
                        "candidate_removal_count": 1,
                        "grasp_load_exception_asset_uids": ["Bread_1"],
                        "grasp_load_exception_types": ["ValueError"],
                    },
                }
            ],
        },
        proof_request_selection={
            "schema": "planner_cleanup_proof_request_selection_v1",
            "selected_count": 0,
            "excluded_count": 1,
            "selected_request_ids": [],
        },
    )

    decision = manifest["grasp_feasibility_mitigation_decision"]
    preflight = manifest["grasp_cache_availability_preflight"]
    assert decision["primary_route"] == "grasp_cache_mitigation"
    assert preflight["status"] == "missing_cache"
    assert preflight["assets_dir"] == str(tmp_path / "assets")
    assert preflight["assets_dir_source"] == "planner_scene"
    assert preflight["cache_missing_asset_uids"] == ["Bread_1"]
    assert preflight["assets"][0]["object_asset_status"] == "present"
    assert preflight["assets"][0]["candidate_grasp_files"][0]["relative_path"] == (
        "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz"
    )


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


def test_proof_request_selection_keeps_fallback_required_when_no_alias_available() -> None:
    manifest = {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "binding": {
                    "candidate_pickup_names": ["pickup/body"],
                    "candidate_place_receptacle_names": ["sink/body"],
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
    assert selection["fallback_generation"]["status"] == "exhausted"
    assert selection["fallback_generation"]["unavailable_source_request_count"] == 1
    assert selection["fallback_generation"]["exhaustion_blocker_count"] == 1
    assert selection["fallback_generation"]["exhaustion_blockers"][0]["code"] == (
        "no_fallback_candidate_available"
    )


def test_proof_result_summary_classifies_task_feasibility_and_views(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    views_dir = proof_dir / "planner_views"
    views_dir.mkdir(parents=True)
    (views_dir / "initial.png").write_bytes(b"initial")
    (views_dir / "final.png").write_bytes(b"final")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "blockers": [
                        {
                            "code": "HouseInvalidForTask",
                            "message": "robot placement failed near object",
                        }
                    ],
                    "cleanup_task_config": {
                        "scene_xml": "/tmp/scene.xml",
                        "planner_object_id": "pickup/body",
                    },
                    "task_sampler_robot_placement_profile": {
                        "profile": "relaxed",
                        "requested": True,
                        "applied": True,
                        "place_robot_near_overrides": {"max_tries": 50},
                    },
                    "cleanup_task_sampler_adapter": {
                        "applied": True,
                        "task_sampler_class": "PickAndPlaceTaskSampler",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "task_sampler_failure_diagnostics": {
                        "applied": True,
                        "task_sampler_class": "PickAndPlaceTaskSampler",
                        "robot_placement_attempt_count": 1,
                        "robot_placement_failure_count": 1,
                        "asset_failure_count": 1,
                        "grasp_failure_count": 3,
                        "grasp_failures": [
                            {
                                "object_name": "pickup/body",
                                "count_after": 3,
                                "removed_candidate": True,
                            }
                        ],
                        "last_placement_scene_diagnostic": {
                            "target_name": "pickup/body",
                            "valid_free_point_count": 3,
                            "valid_neighborhood_fraction": 0.000017,
                        },
                        "last_robot_placement_failure": {
                            "pickup_obj_name": "pickup/body",
                            "message": "Failed to place robot near object: pickup/body",
                        },
                    },
                    "requested_cleanup_primitive_binding": {
                        "scene_xml": "/tmp/scene.xml",
                        "planner_object_id": "pickup/body",
                        "planner_target_receptacle_id": "sink/body",
                    },
                    "image_artifacts": {
                        "initial": "planner_views/initial.png",
                        "final": "planner_views/final.png",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    commands = [
        {
            "request_id": "proof_001",
            "object_id": "observed_001",
            "target_receptacle_id": "sink_01",
            "run_result": str(proof_dir / "run_result.json"),
            "report": str(proof_dir / "report.html"),
        },
        {
            "request_id": "proof_002",
            "object_id": "observed_002",
            "target_receptacle_id": "shelf_01",
            "run_result": str(tmp_path / "missing" / "run_result.json"),
            "report": str(tmp_path / "missing" / "report.html"),
        },
    ]

    summary = proof_result_summary_from_commands(commands)

    assert summary["schema"] == "planner_cleanup_proof_result_summary_v1"
    assert summary["expected_count"] == 2
    assert summary["result_count"] == 1
    assert summary["missing_result_count"] == 1
    assert summary["task_feasibility_blocked_count"] == 1
    assert summary["view_artifact_count"] == 2
    assert summary["proof_quality_summary"]["quality_tier_counts"] == {"unknown": 1}
    result = summary["results"][0]
    assert result["proof_quality"]["quality_tier"] == "unknown"
    assert result["task_feasibility_status"] == "blocked"
    assert result["task_feasibility_blocker_kind"] == "robot_placement"
    assert result["task_feasibility_blocker_summary"] == "1 robot-placement failures"
    assert result["visual_status"] == "views_recorded"
    assert result["blockers"][0]["code"] == "HouseInvalidForTask"
    assert result["cleanup_task_sampler_adapter"]["applied"] is True
    assert result["cleanup_task_sampler_adapter"]["planner_target_receptacle_id"] == "sink/body"
    assert result["task_sampler_robot_placement_profile"]["profile"] == "relaxed"
    assert (
        result["task_sampler_robot_placement_profile"]["place_robot_near_overrides"]["max_tries"]
        == 50
    )
    assert result["task_sampler_failure_diagnostics"]["robot_placement_failure_count"] == 1
    assert result["task_sampler_failure_diagnostics"]["grasp_failure_count"] == 3
    assert (
        result["task_sampler_failure_diagnostics"]["last_placement_scene_diagnostic"][
            "valid_free_point_count"
        ]
        == 3
    )
    assert (
        result["task_sampler_failure_diagnostics"]["last_robot_placement_failure"][
            "pickup_obj_name"
        ]
        == "pickup/body"
    )
    assert result["views"][0]["path"].endswith("planner_views/final.png")
    assert summary["results"][1]["task_feasibility_status"] == "not_run"


def test_proof_result_summary_surfaces_non_object_run_result_source_error(
    tmp_path: Path,
) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "run_result.json").write_text('["not", "a", "packet"]', encoding="utf-8")

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    assert summary["result_count"] == 1
    assert summary["missing_result_count"] == 0
    result = summary["results"][0]
    assert result["run_result_exists"] is True
    assert result["status"] == "unreadable"
    assert result["task_feasibility_status"] == "unknown"
    assert result["visual_status"] == "unknown"
    assert result["blockers"][0]["code"] == "proof_run_result_unreadable"
    assert "non-object JSON: list" in result["blockers"][0]["message"]


def test_proof_result_summary_surfaces_malformed_run_result_source_error(
    tmp_path: Path,
) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "run_result.json").write_text("{bad json\n", encoding="utf-8")

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    result = summary["results"][0]
    assert result["run_result_exists"] is True
    assert result["status"] == "unreadable"
    assert result["blockers"][0]["code"] == "proof_run_result_unreadable"
    assert "JSONDecodeError:" in result["blockers"][0]["message"]


def test_proof_result_summary_carries_planner_proof_quality(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    views_dir = proof_dir / "planner_views"
    views_dir.mkdir(parents=True)
    (views_dir / "initial.png").write_bytes(b"initial")
    (views_dir / "final.png").write_bytes(b"final")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "planner_backed",
                "manipulation_evidence": planner_backed_probe_evidence(
                    backend="molmospaces_subprocess",
                    embodiment="rby1m",
                    task="pick_and_place",
                    probe_mode="execute",
                    upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
                    steps_requested=2,
                    steps_executed=2,
                    max_abs_qpos_delta=0.01,
                    image_artifacts={
                        "initial": "planner_views/initial.png",
                        "final": "planner_views/final.png",
                    },
                ),
            }
        ),
        encoding="utf-8",
    )

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    result = summary["results"][0]
    assert result["proof_quality"]["quality_tier"] == "multi_step_motion"
    assert result["steps_executed"] == 2
    assert summary["proof_quality_summary"]["quality_tier_counts"] == {"multi_step_motion": 1}


def test_proof_result_summary_classifies_grasp_feasibility_blocker(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_shelf_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "blockers": [
                        {
                            "code": "HouseInvalidForTask",
                            "message": "House invalid for tasks due to physics constraints",
                        }
                    ],
                    "task_sampler_failure_diagnostics": {
                        "applied": True,
                        "robot_placement_attempt_count": 17,
                        "robot_placement_failure_count": 0,
                        "grasp_failure_count": 17,
                        "candidate_removal_count": 15,
                        "grasp_failures": [
                            {
                                "object_name": "book/body",
                                "count_after": 17,
                                "removed_candidate": False,
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    commands = [
        {
            "request_id": "proof_001",
            "object_id": "observed_001",
            "target_receptacle_id": "shelf_01",
            "run_result": str(proof_dir / "run_result.json"),
            "report": str(proof_dir / "report.html"),
        }
    ]

    summary = proof_result_summary_from_commands(commands)

    assert summary["grasp_feasibility_blocked_count"] == 1
    result = summary["results"][0]
    assert result["task_feasibility_status"] == "blocked"
    assert result["task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert result["task_feasibility_blocker_summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )


def test_proof_result_summary_surfaces_timeout_worker_stage_evidence(
    tmp_path: Path,
) -> None:
    proof_dir = tmp_path / "proofs" / "001_observed_001_to_sink_01"
    proof_dir.mkdir(parents=True)
    (proof_dir / "planner_probe_stdout.txt").write_text("stdout", encoding="utf-8")
    (proof_dir / "planner_probe_stderr.txt").write_text("stderr", encoding="utf-8")
    (proof_dir / "report.html").write_text("<h1>proof</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "artifacts": {
                    "stdout": "planner_probe_stdout.txt",
                    "stderr": "planner_probe_stderr.txt",
                },
                "manipulation_evidence": {
                    "execution_attempted": False,
                    "blockers": [{"code": "timeout", "message": "Probe exceeded 1.0s"}],
                    "last_worker_stage": "rby1m_config_import",
                    "worker_stage_events": [
                        {
                            "event": "worker_start",
                            "stage": "worker_start",
                            "elapsed_s": 0.1,
                            "runtime_diagnostics": {"large": "omitted from bundle"},
                        },
                        {
                            "event": "rby1m_config_import_start",
                            "stage": "rby1m_config_import",
                            "elapsed_s": 3.2,
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    commands = [
        {
            "request_id": "proof_001_fallback_01",
            "object_id": "observed_001",
            "target_receptacle_id": "sink_01",
            "run_result": str(proof_dir / "run_result.json"),
            "report": str(proof_dir / "report.html"),
        }
    ]

    summary = proof_result_summary_from_commands(commands)

    assert summary["timeout_count"] == 1
    assert summary["rby1m_config_import_timeout_count"] == 1
    assert summary["execution_attempted_count"] == 0
    assert summary["worker_stage_event_count"] == 2
    assert summary["last_worker_stage_counts"] == {"rby1m_config_import": 1}
    result = summary["results"][0]
    assert result["task_feasibility_status"] == "not_reached"
    assert result["last_worker_stage"] == "rby1m_config_import"
    assert result["worker_stage_event_count"] == 2
    assert result["worker_stage_events"][0] == {
        "elapsed_s": 0.1,
        "event": "worker_start",
        "stage": "worker_start",
    }
    assert "runtime_diagnostics" not in result["worker_stage_events"][0]
    assert result["stdout"].endswith("planner_probe_stdout.txt")
    assert result["stderr"].endswith("planner_probe_stderr.txt")


class _BindingContract:
    backend = SimpleNamespace(
        backend="molmospaces_subprocess",
        scene_xml="/tmp/molmospaces-scene.xml",
    )

    def planner_observed_handle_binding(
        self,
        object_id: str,
        target_receptacle_id: str,
        *,
        source_receptacle_id: str = "",
        tools: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "schema": OBSERVED_HANDLE_PLANNER_BINDING_SCHEMA,
            "ok": True,
            "status": "ok",
            "object_id": object_id,
            "target_receptacle_id": target_receptacle_id,
            "source_receptacle_id": source_receptacle_id,
            "planner_object_id": "pickup/body",
            "planner_target_receptacle_id": "sink/body",
            "tools": list(tools or []),
            "planner_probe_args": {
                "--cleanup-object-id": object_id,
                "--cleanup-target-receptacle-id": target_receptacle_id,
                "--cleanup-source-receptacle-id": source_receptacle_id,
                "--cleanup-tools": ",".join(tools or []),
                "--cleanup-planner-object-id": "pickup/body",
                "--cleanup-planner-target-receptacle-id": "sink/body",
            },
            "blockers": [],
        }
