from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            (
                r"prior proof bundle manifest source must contain valid JSON object: "
                r".*proof_bundle_run_manifest\.json"
            ),
        ),
        (
            "[]\n",
            (
                r"prior proof bundle manifest source must contain a JSON object: "
                r".*proof_bundle_run_manifest\.json"
            ),
        ),
    ],
)
def test_runner_rejects_malformed_prior_proof_manifest_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    runner = _load_module()
    cleanup_run_result = _cleanup_run_result(tmp_path)
    prior_manifest = tmp_path / "prior" / "proof_bundle_run_manifest.json"
    prior_manifest.parent.mkdir()
    prior_manifest.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _run_minimal_bundle(
            runner,
            cleanup_run_result,
            output_dir=tmp_path / "bundle",
            prior_proof_bundle_manifest=prior_manifest,
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            (
                r"standalone planner probe run result source must contain valid JSON object: "
                r".*prior-probe/run_result\.json"
            ),
        ),
        (
            "[]\n",
            (
                r"standalone planner probe run result source must contain a JSON object: "
                r".*prior-probe/run_result\.json"
            ),
        ),
    ],
)
def test_runner_rejects_malformed_prior_probe_run_result_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    runner = _load_module()
    cleanup_run_result = _cleanup_run_result(tmp_path)
    prior_probe = tmp_path / "prior-probe" / "run_result.json"
    prior_probe.parent.mkdir()
    prior_probe.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _run_minimal_bundle(
            runner,
            cleanup_run_result,
            output_dir=tmp_path / "bundle",
            prior_planner_probe_run_result=prior_probe,
        )


def _cleanup_run_result(tmp_path: Path) -> Path:
    cleanup_run_result = tmp_path / "cleanup" / "run_result.json"
    cleanup_run_result.parent.mkdir()
    cleanup_run_result.write_text(
        json.dumps({"planner_proof_requests": _proof_requests()}),
        encoding="utf-8",
    )
    return cleanup_run_result


def _run_minimal_bundle(
    runner,
    cleanup_run_result: Path,
    *,
    output_dir: Path,
    prior_proof_bundle_manifest: Path | None = None,
    prior_planner_probe_run_result: Path | None = None,
) -> dict[str, object]:
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
        prior_proof_bundle_manifest=prior_proof_bundle_manifest,
        prior_planner_probe_run_result=prior_planner_probe_run_result,
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
