from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.opik_projection import suite as opik_suite
from roboclaws.evals.runner import run_eval_suite
from tests.unit.evals.eval_runner_support import _passing_product_runner


def _persisted_suite(tmp_path: Path) -> Path:
    run = run_eval_suite(
        "smoke_regression",
        output_root=tmp_path,
        stamp="opik-contract",
        product_runner=_passing_product_runner,
    )
    return run.results_path


def test_suite_snapshot_exports_closed_identity_without_prompt_or_artifact_bodies(
    tmp_path: Path,
) -> None:
    results_path = _persisted_suite(tmp_path)

    snapshot = opik_suite.build_suite_projection_snapshot("smoke_regression", results_path)

    assert snapshot["project"]["name"] == "roboclaws-eval"
    assert len(snapshot["items"]) == 1
    assert snapshot["trace_coverage"] == {"native_span_trace": 0, "experiment_only": 1}
    assert snapshot["privacy_scan"] == {"state": "passed", "finding_count": 0}
    encoded = json.dumps(snapshot, sort_keys=True)
    assert '"prompt"' not in encoded
    assert "private_evaluation" not in encoded
    assert "run_result.json" not in encoded


def test_changed_result_content_creates_new_item_and_experiment_identity(tmp_path: Path) -> None:
    results_path = _persisted_suite(tmp_path)
    first = opik_suite.build_suite_projection_snapshot("smoke_regression", results_path)
    payload = json.loads(results_path.read_text())
    payload["results"][0]["status"] = "failed"
    payload["results"][0]["failure_class"] = "agent_no_completion_claim"
    results_path.write_text(json.dumps(payload), encoding="utf-8")

    changed = opik_suite.build_suite_projection_snapshot("smoke_regression", results_path)

    assert changed["dataset"] == first["dataset"]
    assert changed["items"][0]["projection_key"] != first["items"][0]["projection_key"]
    assert changed["experiment"]["projection_key"] != first["experiment"]["projection_key"]


def test_automatic_projection_failure_is_atomic_and_does_not_change_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results_path = _persisted_suite(tmp_path)
    source_before = results_path.read_bytes()

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise OSError("service unavailable")

    monkeypatch.setattr(opik_suite, "OpikHttp", unavailable)
    summary = opik_suite.project_completed_eval_to_opik(
        suite_ref="smoke_regression",
        eval_results_path=results_path,
        environ={"ROBOCLAWS_OPIK_ENDPOINT": "http://127.0.0.1:5174"},
    )

    assert summary["state"] == "unavailable"
    assert summary["reason"] == "opik_unavailable"
    assert results_path.read_bytes() == source_before
    receipt = json.loads(results_path.with_name("opik_projection.json").read_text())
    assert receipt["state"] == "unavailable"
    assert receipt["source_manifest_sha256"] != "unavailable"
