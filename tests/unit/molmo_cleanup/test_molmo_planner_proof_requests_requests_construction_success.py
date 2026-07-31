from __future__ import annotations

from pathlib import Path

from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA
from roboclaws.household.planner_proof_requests import (
    build_probe_commands,
    build_probe_warmup_command,
)
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary


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
        molmospaces_python=None,
        molmospaces_root=None,
        torch_extensions_dir=Path("torch_ext"),
        task_sampler_robot_placement_profile="relaxed",
    )

    assert len(commands) == 1
    command = commands[0]["command"]
    assert command[:3] == ["python", "-m", "roboclaws.household.planner_probe"]
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


def test_build_probe_warmup_command_uses_config_import_and_shared_cache(
    tmp_path: Path,
) -> None:
    warmup = build_probe_warmup_command(
        output_dir=tmp_path,
        runner_python=Path("python"),
        molmospaces_python=Path("molmo-python"),
        molmospaces_root=Path("molmospaces"),
        torch_extensions_dir=Path("torch_ext"),
        timeout_s=900.0,
    )

    command = warmup["command"]
    assert warmup["kind"] == "rby1m_curobo_config_import"
    assert warmup["run_result"].endswith("rby1m_curobo_warmup/run_result.json")
    assert command[:3] == ["python", "-m", "roboclaws.household.planner_probe"]
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
