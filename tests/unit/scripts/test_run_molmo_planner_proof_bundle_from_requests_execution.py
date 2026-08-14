from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from tests.unit.scripts.run_molmo_planner_proof_bundle_from_requests_support import (
    _load_module,
    _proof_requests,
    _run_minimal_bundle,
)


def test_runner_reports_misaligned_proof_execution_horizon(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=1,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        exclude_prior_covered=True,
        prior_covered_min_proof_steps=2,
    )

    horizon = result["manifest"]["proof_execution_horizon"]
    assert horizon["status"] == "command_steps_below_coverage_horizon"
    assert horizon["command_quality_target"] == "one_step_motion"
    assert horizon["prior_covered_quality_floor"] == "multi_step_motion"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "command_steps_below_coverage_horizon" in report
    assert "Probe commands request 1 steps" in report


def test_runner_summarizes_grasp_feasibility_signatures(tmp_path: Path) -> None:
    proof_dir = tmp_path / "proofs" / "001"
    proof_dir.mkdir(parents=True)
    (proof_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")
    (proof_dir / "run_result.json").write_text(
        json.dumps(
            {
                "status": "blocked_capability",
                "artifacts": {},
                "manipulation_evidence": {
                    "execution_attempted": True,
                    "blockers": [{"code": "HouseInvalidForTask"}],
                    "task_sampler_failure_diagnostics": {
                        "robot_placement_attempt_count": 17,
                        "robot_placement_failure_count": 0,
                        "place_robot_near_call_count": 17,
                        "grasp_failure_count": 17,
                        "candidate_removal_count": 15,
                        "image_artifacts": {
                            "post_placement_attempt_001_head_camera": "planner_views/view.png"
                        },
                        "grasp_failures": [
                            {
                                "object_name": "bread_1",
                                "count_before": 0,
                                "count_after": 1,
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    summary = proof_result_summary_from_commands(
        [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "fridge_01",
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
            }
        ]
    )

    result = summary["results"][0]
    assert result["task_feasibility_blocker_kind"] == "grasp_feasibility"
    assert result["grasp_feasibility_signature"]["summary"] == (
        "17 grasp failures; 15 candidate-removal calls"
    )
    assert summary["grasp_feasibility_signature_count"] == 1
    assert summary["grasp_feasibility_signature_counts"][0]["request_ids"] == ["proof_001"]


def test_runner_can_add_visible_warmup_with_output_local_cache(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    output_dir = tmp_path / "bundle"

    result = runner.run_from_cleanup_result(
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
        warmup_rby1m_curobo=True,
    )

    manifest = result["manifest"]
    warmup = manifest["warmup"]
    shared_cache = str(output_dir / "torch_extensions")
    assert warmup["run_result"].endswith("rby1m_curobo_warmup/run_result.json")
    assert "--probe-mode" in warmup["command"]
    assert "config_import" in warmup["command"]
    assert "--torch-extensions-dir" in warmup["command"]
    assert shared_cache in warmup["command"]
    proof_command = manifest["commands"][0]["command"]
    assert "--torch-extensions-dir" in proof_command
    assert shared_cache in proof_command
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "RBY1M/CuRobo Warmup" in report
    assert "rby1m_curobo_warmup/run_result.json" in report
    assert "config_import" in report


def test_runner_records_local_runtime_preflight_blocker_before_execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    fake_python = tmp_path / "molmospaces-python"
    fake_python.write_text(
        "#!/bin/sh\necho \"ModuleNotFoundError: No module named 'molmo_spaces'\" >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    def fail_run_command(command: list[str]) -> None:
        raise AssertionError(f"proof command should not run after failed preflight: {command}")

    monkeypatch.setattr(runner, "_run_command", fail_run_command)

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=fake_python,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=2,
        timeout_s=600.0,
        renderer_device_id=0,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="low",
        execute_probes=True,
        warmup_rby1m_curobo=True,
    )

    manifest = result["manifest"]
    preflight = manifest["local_runtime_preflight"]
    assert result["status"] == "local_runtime_blocked"
    assert preflight["status"] == "blocked"
    assert preflight["blockers"][0]["code"] == "molmo_spaces_import_failed"
    assert manifest["proof_result_summary"]["result_count"] == 0
    assert manifest["proof_result_summary"]["results"][0]["status"] == "not_run"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Local Runtime Preflight" in report
    assert "molmo_spaces_import_failed" in report
    assert str(fake_python) in report


def test_runner_loads_request_artifact_from_run_result(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_dir = tmp_path / "cleanup"
    cleanup_dir.mkdir()
    (cleanup_dir / "planner_proof_requests.json").write_text(
        json.dumps(_proof_requests()),
        encoding="utf-8",
    )
    cleanup_run_result = cleanup_dir / "run_result.json"
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": "planner_proof_requests.json"}}),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
        runner_python=Path("python"),
        probe_script=Path("probe.py"),
        cleanup_script=Path("cleanup.py"),
        molmospaces_python=None,
        molmospaces_root=None,
        embodiment="franka",
        probe_mode="config_import",
        steps=1,
        timeout_s=30.0,
        renderer_device_id=-1,
        torch_extensions_dir=None,
        rby1m_curobo_memory_profile="none",
    )

    command = result["manifest"]["commands"][0]["command"]
    assert "--embodiment" in command
    assert "franka" in command
    assert "--probe-mode" in command
    assert "config_import" in command


def test_runner_enriches_legacy_requests_with_source_scene(tmp_path: Path) -> None:
    runner = _load_module()
    requests = dict(_proof_requests())
    requests.pop("planner_scene", None)
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps(
            {
                "backend": "molmospaces_subprocess",
                "molmospaces_runtime": {"scene_xml": "/tmp/source-scene.xml"},
                "planner_proof_requests": requests,
            }
        ),
        encoding="utf-8",
    )

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
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

    command = result["manifest"]["commands"][0]["command"]
    assert result["manifest"]["planner_scene"]["scene_xml"] == "/tmp/source-scene.xml"
    assert "--cleanup-scene-xml" in command
    assert "/tmp/source-scene.xml" in command


def test_runner_records_cleanup_rerun_artifacts_when_rerun_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps(
            {
                "seed": 7,
                "backend": "api_semantic_synthetic",
                "static_fixture_projection_mode": "room_only",
                "perception_mode": "visible_object_detections",
                "requested_generated_mess_count": 10,
                "planner_proof_requests": _proof_requests(),
            }
        ),
        encoding="utf-8",
    )
    commands_run: list[list[str]] = []

    def fake_run_command(command: list[str]) -> None:
        commands_run.append(list(command))
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        if "--cleanup-object-id" in command:
            (output_dir / "run_result.json").write_text(
                json.dumps(
                    {
                        "status": "blocked_capability",
                        "manipulation_evidence": {
                            "execution_attempted": True,
                            "blockers": [
                                {
                                    "code": "HouseInvalidForTask",
                                    "message": "robot placement failed",
                                }
                            ],
                            "requested_cleanup_primitive_binding": {
                                "planner_object_id": "pickup/body",
                                "planner_target_receptacle_id": "sink/body",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
        else:
            (output_dir / "run_result.json").write_text("{}", encoding="utf-8")
        (output_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")

    monkeypatch.setattr(runner, "_run_command", fake_run_command)

    result = runner.run_from_cleanup_result(
        cleanup_run_result=cleanup_run_result,
        output_dir=tmp_path / "bundle",
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
        torch_extensions_dir=Path("torch_ext"),
        rby1m_curobo_memory_profile="low",
        execute_probes=True,
        rerun_cleanup=True,
        cleanup_output_dir=tmp_path / "rerun",
    )

    manifest = result["manifest"]
    assert result["status"] == "cleanup_rerun"
    assert len(commands_run) == 2
    assert commands_run[-1][:2] == ["python", "cleanup.py"]
    assert "--planner-proof-run-result" in commands_run[-1]
    cleanup_rerun = manifest["cleanup_rerun"]
    assert cleanup_rerun["output_dir"] == str(tmp_path / "rerun")
    assert cleanup_rerun["run_result"] == str(tmp_path / "rerun" / "run_result.json")
    assert cleanup_rerun["report"] == str(tmp_path / "rerun" / "report.html")
    summary = manifest["proof_result_summary"]
    assert summary["result_count"] == 1
    assert summary["task_feasibility_blocked_count"] == 1
    assert summary["results"][0]["task_feasibility_status"] == "blocked"
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Proof Probe Results" in report
    assert "HouseInvalidForTask" in report
    assert "Cleanup Rerun Artifact" in report
    assert str(tmp_path / "rerun" / "run_result.json") in report


def test_runner_requires_planner_proof_requests(tmp_path: Path) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "run_result.json"
    cleanup_run_result.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="planner proof requests"):
        runner.run_from_cleanup_result(
            cleanup_run_result=cleanup_run_result,
            output_dir=tmp_path / "bundle",
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


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("{not-json\n", "valid JSON object"),
        ("[]\n", "a JSON object"),
    ],
)
def test_runner_rejects_malformed_cleanup_run_result_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(source, encoding="utf-8")

    message = rf"cleanup run result source must contain {message}: .*run_result\.json"
    with pytest.raises(ValueError, match=message):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_rejects_non_object_inline_planner_proof_requests(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": []}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"inline planner proof requests must contain a JSON object: .*run_result\.json",
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_rejects_non_object_artifact_envelope(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(json.dumps({"artifacts": []}), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"cleanup run result artifacts must contain a JSON object: .*run_result\.json",
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


def test_runner_rejects_missing_declared_request_artifact(
    tmp_path: Path,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": "missing_requests.json"}}),
        encoding="utf-8",
    )

    with pytest.raises(
        FileNotFoundError,
        match=r"planner proof requests artifact is missing: .*missing_requests\.json",
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


@pytest.mark.parametrize("declared_source", [None, [], ""])
def test_runner_rejects_wrong_shaped_declared_request_artifact_path(
    tmp_path: Path,
    declared_source: object,
) -> None:
    runner = _load_module()
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": declared_source}}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            r"planner proof requests artifact path must be a non-empty string: "
            r".*run_result\.json"
        ),
    ):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")


@pytest.mark.parametrize(
    ("source", "valid"),
    [
        ("{not-json\n", False),
        ("[]\n", True),
    ],
)
def test_runner_rejects_malformed_declared_request_artifact_source(
    tmp_path: Path,
    source: str,
    valid: bool,
) -> None:
    runner = _load_module()
    cleanup_dir = tmp_path / "cleanup"
    cleanup_dir.mkdir()
    (cleanup_dir / "planner_proof_requests.json").write_text(source, encoding="utf-8")
    cleanup_run_result = cleanup_dir / "run_result.json"
    cleanup_run_result.write_text(
        json.dumps({"artifacts": {"planner_proof_requests": "planner_proof_requests.json"}}),
        encoding="utf-8",
    )

    reason = "a JSON object" if valid else "valid JSON object"
    message = (
        rf"planner proof requests source must contain {reason}: .*planner_proof_requests\.json"
    )
    with pytest.raises(ValueError, match=message):
        _run_minimal_bundle(runner, cleanup_run_result, output_dir=tmp_path / "bundle")
