from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from roboclaws.household import planner_proof_execution as execution
from roboclaws.household.household_backend_contract import SYNTHETIC_BACKEND
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND


def test_dry_run_composes_cleanup_bundle_and_product_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_execution_fakes(monkeypatch)
    request = execution.PlannerProofRequest(
        output_dir=tmp_path,
        mode="dry-run",
        stamp="contract",
    )

    result = execution.execute_planner_proof(request)

    run_root = tmp_path / "contract"
    cleanup_call = calls["cleanup"][0]
    assert cleanup_call["output_dir"] == run_root / "cleanup"
    assert cleanup_call["backend"] == SYNTHETIC_BACKEND
    assert cleanup_call["include_robot"] is False
    bundle_call = calls["bundle"][0]
    assert bundle_call["cleanup_run_result"] == run_root / "cleanup" / "run_result.json"
    assert bundle_call["execute_probes"] is False
    assert bundle_call["rerun_cleanup"] is False
    assert calls["bundle_validation"] == [
        {
            "path": run_root / "proof_bundle" / "proof_bundle_run_manifest.json",
            "require_proof_outputs": False,
            "require_cleanup_rerun_output": False,
            "require_proof_execution_horizon": True,
        }
    ]
    product_validation = calls["cleanup_validation"][0]
    assert product_validation["expect_backend"] == SYNTHETIC_BACKEND
    assert product_validation["require_planner_proof_attachment"] is False
    assert result["status"] == "dry_run"
    assert result["cleanup_rerun_result"] is None


def test_execute_rerun_requires_proofs_and_validates_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_execution_fakes(monkeypatch, bundle_status="cleanup_rerun")
    request = execution.PlannerProofRequest(
        output_dir=tmp_path,
        mode="execute-rerun",
        stamp="contract",
    )

    result = execution.execute_planner_proof(request)

    run_root = tmp_path / "contract"
    cleanup_call = calls["cleanup"][0]
    assert cleanup_call["backend"] == MOLMOSPACES_SUBPROCESS_BACKEND
    assert cleanup_call["include_robot"] is True
    assert cleanup_call["record_robot_views"] is True
    bundle_call = calls["bundle"][0]
    assert bundle_call["execute_probes"] is True
    assert bundle_call["rerun_cleanup"] is True
    assert bundle_call["cleanup_output_dir"] == run_root / "cleanup_rerun"
    assert bundle_call["torch_extensions_dir"] == run_root / "torch_extensions"
    assert calls["bundle_validation"][0]["require_proof_outputs"] is True
    assert calls["bundle_validation"][0]["require_cleanup_rerun_output"] is True
    assert len(calls["cleanup_validation"]) == 2
    rerun_validation = calls["cleanup_validation"][1]
    assert rerun_validation["expect_backend"] == MOLMOSPACES_SUBPROCESS_BACKEND
    assert rerun_validation["require_planner_proof_attachment"] is True
    assert rerun_validation["require_planner_backed_cleanup_primitives"] is True
    assert rerun_validation["require_planner_cleanup_bridge_ready"] is True
    assert result["cleanup_rerun_result"] == str(run_root / "cleanup_rerun" / "run_result.json")


@pytest.mark.parametrize(
    "candidate",
    [
        execution.PlannerProofRequest(output_dir=Path("output"), generated_mess_count=4),
        execution.PlannerProofRequest(output_dir=Path("output"), steps=0),
        execution.PlannerProofRequest(output_dir=Path("output"), timeout_s=0),
    ],
)
def test_request_validation_fails_before_execution(
    candidate: execution.PlannerProofRequest,
) -> None:
    with pytest.raises(ValueError):
        execution.execute_planner_proof(candidate)


def _install_execution_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bundle_status: str = "dry_run",
) -> dict[str, list[dict[str, Any]]]:
    calls: dict[str, list[dict[str, Any]]] = {
        "cleanup": [],
        "cleanup_validation": [],
        "bundle": [],
        "bundle_validation": [],
    }

    def fake_cleanup(**kwargs: Any) -> dict[str, Any]:
        calls["cleanup"].append(kwargs)
        return {"contract": "realworld_cleanup_v1"}

    def fake_cleanup_validation(_result: dict[str, Any], _base: Path, **kwargs: Any) -> None:
        calls["cleanup_validation"].append(kwargs)

    def fake_bundle(**kwargs: Any) -> dict[str, Any]:
        calls["bundle"].append(kwargs)
        manifest = kwargs["output_dir"] / "proof_bundle_run_manifest.json"
        return {"status": bundle_status, "manifest_path": manifest}

    def fake_bundle_validation(path: Path, **kwargs: Any) -> Path:
        calls["bundle_validation"].append({"path": path, **kwargs})
        return path

    monkeypatch.setattr(execution, "run_household_world_episode", fake_cleanup)
    monkeypatch.setattr(execution, "validate_run_result", fake_cleanup_validation)
    monkeypatch.setattr(execution, "run_from_cleanup_result", fake_bundle)
    monkeypatch.setattr(execution, "validate_bundle_path", fake_bundle_validation)
    monkeypatch.setattr(
        execution,
        "read_json_object",
        lambda _path, *, label: {"contract": "realworld_cleanup_v1", "label": label},
    )
    return calls
