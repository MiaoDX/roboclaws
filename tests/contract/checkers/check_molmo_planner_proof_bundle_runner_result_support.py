from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA
from roboclaws.household.planner_proof_requests import (
    proof_execution_horizon,
)
from roboclaws.household.planner_proof_results import proof_result_summary_from_commands
from roboclaws.household.planner_proof_selection import proof_request_selection_from_summary
from roboclaws.household.report_planner import render_planner_proof_bundle_runner_report

REPO_ROOT = Path(__file__).resolve().parents[3]

CHECKER_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_planner_proof_bundle_runner_result.py"
)


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_molmo_planner_proof_bundle_runner_result",
        CHECKER_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_runner_artifact(base: Path) -> dict[str, object]:
    manifest = _runner_manifest(base)
    _write_manifest_and_report(base, manifest)
    return manifest


def _write_manifest_and_report(base: Path, manifest: dict[str, object]) -> None:
    manifest["proof_request_selection"] = proof_request_selection_from_summary(
        {
            "schema": "planner_cleanup_proof_requests_v1",
            "requests": [
                {
                    "request_id": command["request_id"],
                    "object_id": command["object_id"],
                    "target_receptacle_id": command["target_receptacle_id"],
                    "ready": True,
                }
                for command in manifest["commands"]
            ],
        }
    )
    manifest["proof_result_summary"] = proof_result_summary_from_commands(manifest["commands"])
    (base / "proof_bundle_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    render_planner_proof_bundle_runner_report(output_dir=base, manifest=manifest)


def _runner_manifest(base: Path) -> dict[str, object]:
    proof_dir = base / "proofs" / "001_observed_001_to_sink_01"
    command = [
        "python",
        "probe.py",
        "--output-dir",
        str(proof_dir),
        "--cleanup-object-id",
        "observed_001",
        "--cleanup-target-receptacle-id",
        "sink_01",
    ]
    return {
        "schema": PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA,
        "status": "dry_run",
        "cleanup_run_result": str(base / "cleanup" / "run_result.json"),
        "output_dir": str(base),
        "proof_request_count": 1,
        "ready_request_count": 1,
        "proof_execution_horizon": proof_execution_horizon(
            command_steps=2,
            prior_covered_min_proof_steps=1,
        ),
        "command_count": 1,
        "commands": [
            {
                "request_id": "proof_001",
                "object_id": "observed_001",
                "target_receptacle_id": "sink_01",
                "tools": [
                    "navigate_to_object",
                    "pick",
                    "navigate_to_receptacle",
                    "place",
                ],
                "semantic_subphases": [
                    {"phase": "navigate_to_object", "label": "nav", "detail": "object"},
                    {"phase": "pick", "label": "pick", "detail": "object"},
                    {"phase": "navigate_to_receptacle", "label": "nav", "detail": "target"},
                    {"phase": "place", "label": "place", "detail": "surface"},
                ],
                "output_dir": str(proof_dir),
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
                "command": command,
            }
        ],
        "cleanup_command": [],
        "report": str(base / "report.html"),
    }
