from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import (
    _run_result,
    _write_product_artifacts,
)


@pytest.mark.parametrize(
    ("artifact_name", "file_name"),
    [
        ("run_result", "run_result.json"),
        ("agent_view", "agent_view.json"),
        ("runtime_metric_map", "runtime_metric_map.json"),
        ("private_evaluation", "private_evaluation.json"),
    ],
)
def test_eval_runner_fails_aloud_on_malformed_required_json_artifact(
    tmp_path: Path,
    artifact_name: str,
    file_name: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="success")
        result = _run_result(run_dir, completion_status="success")
        (run_dir / file_name).write_text('["not-an-object"]\n', encoding="utf-8")
        return result

    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp=f"malformed-{artifact_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    assert payload["aggregate"]["failed"] == 1
    assert payload["aggregate"]["failure_classes"] == {"artifact_missing": 1}
    result = payload["results"][0]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    artifacts = result["grader_outputs"]["artifacts"]
    assert artifacts["status"] == "failed"
    assert artifacts["failure_class"] == "artifact_missing"
    assert artifacts["source_errors"] == [
        {
            "artifact": artifact_name,
            "path": str(run.output_dir / "runs" / "cleanup_smoke_seed7" / "trial-0000" / file_name),
            "reason": "invalid_json_object",
        }
    ]


@pytest.mark.parametrize("sidecar_name", ["live_status.json", "live_timing.json"])
def test_eval_runner_fails_aloud_on_malformed_efficiency_sidecars(
    tmp_path: Path,
    sidecar_name: str,
) -> None:
    def product_runner(**kwargs: Any) -> dict[str, Any]:
        run_dir = Path(kwargs["output_dir"])
        _write_product_artifacts(run_dir, completion_status="success")
        (run_dir / sidecar_name).write_text("{", encoding="utf-8")
        return _run_result(run_dir, completion_status="success")

    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp=f"malformed-{sidecar_name}",
        product_runner=product_runner,
    )

    payload = json.loads(run.results_path.read_text())
    result = payload["results"][0]
    efficiency = result["grader_outputs"]["efficiency"]
    assert result["status"] == "failed"
    assert result["failure_class"] == "artifact_missing"
    assert efficiency["status"] == "failed"
    assert efficiency["failure_class"] == "artifact_missing"
    assert efficiency["source_errors"][0]["path"].endswith(sidecar_name)
    assert efficiency["source_errors"][0]["reason"].startswith(
        "invalid_json:Expecting property name enclosed in double quotes"
    )
