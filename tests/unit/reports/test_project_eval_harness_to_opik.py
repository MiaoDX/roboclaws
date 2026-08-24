from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts/reports/project_eval_harness_to_opik.py"
SPEC = importlib.util.spec_from_file_location("project_eval_harness_to_opik", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path, *, with_spans: bool = True) -> Path:
    run_dir = tmp_path / "runs/sample/trial-0000"
    run_dir.mkdir(parents=True)
    if with_spans:
        (run_dir / "openai-agents-spans.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "event": "span_start",
                            "schema": "openai_agents_sanitized_span_v1",
                            "span_id": "span_1",
                            "trace_id": "trace_1",
                            "span_type": "agent",
                            "span_name": "agent",
                            "started_at": "2026-08-17T00:00:00+00:00",
                            "ts_epoch": 1.0,
                        }
                    ),
                    json.dumps(
                        {
                            "event": "span_end",
                            "schema": "openai_agents_sanitized_span_v1",
                            "span_id": "span_1",
                            "trace_id": "trace_1",
                            "span_type": "agent",
                            "started_at": "2026-08-17T00:00:00+00:00",
                            "ended_at": "2026-08-17T00:00:01+00:00",
                            "status": "ok",
                        }
                    ),
                ]
            )
            + "\n"
        )
    manifest = {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "candidate_status": "terminal_with_failures",
        "publication_authorized": False,
        "rows": [
            {"row_id": "row-1", "axes": {"provider_profile": "provider-a", "intent": "cleanup"}}
        ],
        "observability_decision_report": {
            "schema": "roboclaws_observability_decision_report_v1",
            "state": "ready",
            "capability_health": {"passed": 1, "failed": 0, "blocked": 0},
            "harness_health": {"passed": 1, "failed": 0, "blocked": 0},
            "limitations": ["latency_incomparable"],
            "telemetry_coverage": {"token_usage": {"numerator": 1, "denominator": 1}},
            "provider_comparison": {
                "cohorts": [
                    {
                        "invariants": {"sample_id": "sample.1"},
                        "treatments": [["provider-a", "model-a", "responses"]],
                        "claims": {
                            "latency": {"state": "incomparable", "reason": "concurrent_execution"}
                        },
                        "metrics": {
                            "input_tokens": {
                                "availability": "available",
                                "claim_eligibility": "diagnostic_only",
                                "limitations": [],
                                "value": 12,
                            }
                        },
                    }
                ]
            },
            "triage": {
                "rows": [
                    {
                        "row_id": "row-1",
                        "suite_id": "suite.1",
                        "sample_id": "sample.1",
                        "trial_id": "sample_1-0000",
                        "execution_target": "local_cpu",
                        "outcome": "passed",
                        "failure_class": "not_applicable",
                        "terminal_reason": "",
                        "tool_call_count": 4,
                        "local_artifacts": {
                            "run_dir": "runs/sample/trial-0000",
                            "trace": "runs/sample/trial-0000/trace.jsonl",
                        },
                    }
                ]
            },
        },
    }
    path = tmp_path / "eval_harness.json"
    path.write_text(json.dumps(manifest))
    return path


def test_snapshot_copies_canonical_values_and_preserves_native_spans(tmp_path: Path) -> None:
    snapshot = MODULE.build_projection_snapshot(_manifest(tmp_path))
    assert snapshot["candidate_status"] == "unaccepted"
    assert snapshot["canonical_summary"]["capability_health"] == {
        "passed": 1,
        "failed": 0,
        "blocked": 0,
    }
    assert snapshot["provider_views"][0]["metrics"]["input_tokens"]["value"] == 12
    assert snapshot["items"][0]["scores"] == {"roboclaws.passed": 1, "roboclaws.tool_call_count": 4}
    assert snapshot["items"][0]["metadata"]["trace_fidelity"] == "native_span_trace"
    assert snapshot["traces"][0]["spans"][0]["status"] == "ok"
    assert snapshot["trace_coverage"] == {"native_span_trace": 1, "experiment_only": 0}


def test_snapshot_is_deterministic_and_missing_trace_stays_unavailable(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, with_spans=False)
    first = MODULE.build_projection_snapshot(manifest)
    second = MODULE.build_projection_snapshot(manifest)
    assert first == second
    assert first["traces"] == []
    assert first["items"][0]["metadata"]["trace_fidelity"] == "experiment_only"
    assert first["trace_coverage"] == {"native_span_trace": 0, "experiment_only": 1}


def test_snapshot_rejects_traversal_and_forbidden_payloads(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["observability_decision_report"]["triage"]["rows"][0]["local_artifacts"]["run_dir"] = (
        "../outside"
    )
    manifest.write_text(json.dumps(payload))
    with pytest.raises(MODULE.ProjectionError, match="traversal-free"):
        MODULE.build_projection_snapshot(manifest)

    findings = MODULE._privacy_scan(
        {"metadata": {"prompt": "do something", "safe": "/absolute/path"}}
    )
    assert "$.metadata.prompt:forbidden_key" in findings
    assert "$.metadata.safe:absolute_path" in findings


def test_real_historical_candidate_snapshot_contract() -> None:
    manifest = Path("output/eval-harness/20260817T072338Z/eval_harness.json")
    if not manifest.is_file():
        pytest.skip("historical candidate is not present")
    snapshot = MODULE.build_projection_snapshot(manifest)
    assert len(snapshot["items"]) == 65
    assert snapshot["trace_coverage"]["native_span_trace"] > 0
    assert snapshot["trace_coverage"]["experiment_only"] > 0
    assert snapshot["privacy_scan"] == {"state": "passed", "finding_count": 0}
