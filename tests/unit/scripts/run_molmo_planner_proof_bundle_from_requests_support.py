from __future__ import annotations

import importlib.util
from pathlib import Path

from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA

REPO_ROOT = Path(__file__).resolve().parents[3]

SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_planner_proof_bundle_from_requests.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_molmo_planner_proof_bundle_from_requests",
        SCRIPT_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _assert_inline_dry_run_manifest(manifest: dict[str, object]) -> None:
    assert manifest["schema"] == "planner_cleanup_proof_bundle_run_manifest_v1"
    assert manifest["report"].endswith("report.html")
    assert manifest["proof_request_count"] == 1
    assert manifest["ready_request_count"] == 1
    assert manifest["command_count"] == 1
    assert manifest["proof_execution_horizon"]["schema"] == (
        "planner_cleanup_proof_execution_horizon_v1"
    )
    assert manifest["proof_execution_horizon"]["status"] == "aligned"
    assert manifest["proof_execution_horizon"]["command_steps"] == 2
    assert manifest["proof_execution_horizon"]["command_quality_target"] == "multi_step_motion"
    assert manifest["proof_execution_horizon"]["prior_covered_min_proof_steps"] == 1
    assert manifest["proof_request_selection"]["mode"] == "all_ready"
    assert manifest["proof_request_selection"]["selected_request_ids"] == ["proof_001"]
    assert manifest["commands"][0]["report"].endswith("report.html")
    assert manifest["planner_scene"]["scene_xml"] == "/tmp/molmospaces-scene.xml"
    assert manifest["proof_result_summary"]["expected_count"] == 1
    assert manifest["proof_result_summary"]["results"][0]["task_feasibility_status"] == "not_run"


def _assert_inline_dry_run_command(command_item: dict[str, object]) -> None:
    command = command_item["command"]
    assert command_item["tools"] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]
    assert command_item["semantic_subphases"] == [
        {"phase": "navigate_to_object", "label": "nav", "detail": "object"},
        {"phase": "pick", "label": "pick", "detail": "object"},
        {"phase": "navigate_to_receptacle", "label": "nav", "detail": "target"},
        {"phase": "place", "label": "place", "detail": "surface"},
    ]
    assert command[command.index("--cleanup-tools") + 1] == (
        "navigate_to_object,pick,navigate_to_receptacle,place"
    )
    assert command[:2] == ["python", "probe.py"]
    assert "--cleanup-object-id" in command
    assert "observed_001" in command
    assert "--cleanup-planner-target-receptacle-id" in command
    assert "sink/body" in command
    assert "--cleanup-scene-xml" in command
    assert "/tmp/molmospaces-scene.xml" in command
    assert "--task-sampler-robot-placement-profile" in command
    assert "relaxed" in command


def _assert_inline_dry_run_artifacts(result: dict[str, object]) -> None:
    assert Path(result["manifest_path"]).is_file()
    assert Path(result["report_path"]).is_file()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Planner Proof Bundle Runner" in report
    assert "Proof Execution Horizon" in report
    assert "multi_step_motion" in report
    assert "Semantic subphases" in report
    assert "navigate_to_object" in report
    assert "surface / place" in report
    assert "Proof Request Selection" in report
    assert "Proof Probe Commands" in report
    assert "Proof Probe Results" in report
    assert "not_run" in report
    assert "Cleanup Rerun Command" in report
    assert "observed_001" in report
    assert "--cleanup-object-id" in report
    assert "sink/body" in report
    assert "/tmp/molmospaces-scene.xml" in report


def _run_minimal_bundle(runner, cleanup_run_result: Path, *, output_dir: Path) -> dict[str, object]:
    return runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=output_dir,
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
    )


def _proof_requests() -> dict[str, object]:
    return {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "request_count": 1,
        "ready_count": 1,
        "planner_scene": {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": True,
            "scene_xml": "/tmp/molmospaces-scene.xml",
            "backend": "molmospaces_subprocess",
        },
        "agent_view_exposed": False,
        "blockers": [],
        "requests": [
            {
                "request_id": "proof_001",
                "ready": True,
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "source_receptacle_id": "counter_01",
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
