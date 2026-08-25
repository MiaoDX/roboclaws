from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.harness import runner
from roboclaws.evals.observability_decision_report import (
    build_observability_decision_report,
)


def test_non_authoritative_manifests_are_not_applicable(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, mode="recommend", rows=[])
    report = build_observability_decision_report(manifest)
    assert report == {
        "schema": "roboclaws_observability_decision_report_v1",
        "state": "not_applicable",
        "reason": "recommend_manifest",
    }

    manifest["mode"] = "execute"
    manifest["rows"] = [_row("pending", outcome="")]
    assert build_observability_decision_report(manifest)["reason"] == "nonterminal_manifest"

    manifest["execution"] = {"shard_id": "worker-1"}
    assert build_observability_decision_report(manifest)["reason"] == "worker_shard_manifest"


def test_serial_provider_claims_are_independent(tmp_path: Path) -> None:
    rows = []
    for provider, duration in (("alpha", 1.2), ("beta", None)):
        bundle = tmp_path / provider / "eval_results.json"
        run_dir = bundle.parent / "runs" / "sample" / "trial-0000"
        run_dir.mkdir(parents=True)
        bundle.write_text(json.dumps(_bundle(provider, run_dir)), encoding="utf-8")
        (run_dir / "model_call_metrics.jsonl").write_text(
            json.dumps(_call(provider, duration)) + "\n", encoding="utf-8"
        )
        rows.append(_row(provider, artifacts=[str(bundle)]))
    report = build_observability_decision_report(_manifest(tmp_path, rows=rows))
    cohort = report["provider_comparison"]["cohorts"][0]
    assert cohort["claims"]["quality"]["state"] == "eligible"
    assert cohort["claims"]["model_work"]["state"] == "eligible"
    assert cohort["claims"]["latency"]["state"] == "eligible"
    assert cohort["claims"]["latency"]["reason"] == "comparable_serial_execution"
    assert report["telemetry_coverage"]["model_duration"] == {
        "numerator": 1,
        "denominator": 2,
    }
    assert cohort["metrics"]["input_tokens"]["value"] == 10
    assert report["capability_health"]["slices"]["provider_route"]["alpha/alpha"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "blocked": 0,
    }


def test_concurrency_suppresses_latency_ranking(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, rows=[_row("passed")])
    manifest["execution"] = {"authorized_max_active_tasks": 8}
    report = build_observability_decision_report(manifest)
    assert report["provider_comparison"]["cohorts"] == []
    assert report["harness_health"]["passed"] == 1


def test_explicit_execution_scope_ignores_unexecuted_selected_rows(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, rows=[_row("executed"), _row("pending", outcome="")])
    manifest["execution"] = {"shard_id": "local-main", "row_ids": ["executed"]}
    report = build_observability_decision_report(manifest)
    assert report["state"] == "ready_with_limitations"
    assert report["harness_health"]["total"] == 1
    assert report["harness_health"]["passed"] == 1


def test_malformed_declared_bundle_fails_finalization(tmp_path: Path) -> None:
    bundle = tmp_path / "eval_results.json"
    bundle.write_text("{broken", encoding="utf-8")
    manifest = _manifest(tmp_path, rows=[_row("broken", artifacts=[str(bundle)])])
    with pytest.raises(ValueError, match="must contain valid JSON"):
        build_observability_decision_report(manifest)
    assert manifest["rows"][0]["outcome"] == "passed"


def test_contradictory_model_call_identity_fails_finalization(tmp_path: Path) -> None:
    bundle = tmp_path / "provider" / "eval_results.json"
    run_dir = bundle.parent / "runs" / "sample" / "trial-0000"
    run_dir.mkdir(parents=True)
    bundle.write_text(json.dumps(_bundle("alpha", run_dir)), encoding="utf-8")
    call = _call("different-provider", 1.0) | {"model": "alpha"}
    (run_dir / "model_call_metrics.jsonl").write_text(json.dumps(call) + "\n")
    manifest = _manifest(tmp_path, rows=[_row("alpha", artifacts=[str(bundle)])])
    with pytest.raises(ValueError, match="contradicts EvalTrial identity"):
        build_observability_decision_report(manifest)


def test_explicit_regeneration_is_byte_stable(tmp_path: Path) -> None:
    manifest_path = tmp_path / "eval_harness.json"
    manifest = _manifest(tmp_path, rows=[_row("terminal")])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    runner.regenerate_observability_report(manifest_path)
    first = {
        suffix: (tmp_path / f"eval_harness.{suffix}").read_bytes() for suffix in ("json", "md")
    }
    runner.regenerate_observability_report(manifest_path)
    second = {
        suffix: (tmp_path / f"eval_harness.{suffix}").read_bytes() for suffix in ("json", "md")
    }
    assert second == first


def test_report_outputs_deny_stale_worker_paths(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        rows=[
            _row(
                "collected",
                artifacts=[
                    "/tmp/roboclaws-cloudml/output/row_result.json",
                    "output/eval-harness/accepted/row_result.json",
                ],
            )
        ],
    )
    runner._write_outputs(manifest, tmp_path)
    for suffix in ("json", "md"):
        rendered = (tmp_path / f"eval_harness.{suffix}").read_text()
        assert "/tmp/roboclaws-cloudml" not in rendered


def test_attached_baseline_regressions_are_projected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, rows=[_row("current")])
    manifest["comparisons"] = [
        {
            "label": "accepted-baseline",
            "manifest_sha256": "a" * 64,
            "common_row_count": 3,
            "common_passed_row_count": 2,
            "behavior_regression_row_ids": ["current"],
            "outcome_regression_row_ids": ["current"],
        }
    ]
    report = build_observability_decision_report(manifest)
    assert report["capability_health"]["baseline_regressions"] == [
        {
            "label": "accepted-baseline",
            "manifest_sha256": "a" * 64,
            "common_row_count": 3,
            "common_passed_row_count": 2,
            "regressed_row_ids": ["current"],
        }
    ]


def test_opik_disabled_retains_local_drilldown(tmp_path: Path) -> None:
    bundle = tmp_path / "provider" / "eval_results.json"
    run_dir = bundle.parent / "runs" / "sample" / "trial-0000"
    run_dir.mkdir(parents=True)
    bundle.write_text(json.dumps(_bundle("alpha", run_dir)), encoding="utf-8")
    (run_dir / "model_call_metrics.jsonl").write_text(json.dumps(_call("alpha", 1.0)) + "\n")
    receipt = bundle.with_name("opik_projection.json")
    receipt.write_text(json.dumps({"state": "disabled", "reason": "endpoint_not_configured"}))
    manifest = _manifest(
        tmp_path,
        rows=[_row("alpha", artifacts=[str(bundle), str(receipt)])],
    )
    report = build_observability_decision_report(manifest)
    triage = report["triage"]["rows"][0]
    assert report["state"] == "ready_with_limitations"
    assert triage["local_artifacts"]["run_dir"] == "provider/runs/sample/trial-0000"
    assert triage["opik_run"] is None


def test_acceptance_candidate_projection() -> None:
    path = Path("output/eval-harness/20260817T072338Z/eval_harness.json")
    if not path.is_file():
        pytest.skip("persisted acceptance candidate is unavailable")
    report = build_observability_decision_report(json.loads(path.read_text()), manifest_path=path)
    assert {
        key: report["harness_health"][key] for key in ("total", "passed", "failed", "blocked")
    } == {
        "total": 29,
        "passed": 27,
        "failed": 1,
        "blocked": 1,
    }
    providers = report["telemetry_coverage"]["by_provider"]
    assert providers["codex-responses"]["model_duration"] == {
        "numerator": 77,
        "denominator": 77,
    }
    assert providers["mimo-responses"]["model_duration"] == {
        "numerator": 74,
        "denominator": 74,
    }
    assert providers["minimax-responses"]["model_duration"] == {
        "numerator": 62,
        "denominator": 62,
    }
    assert providers["kimi-openai-chat"]["model_duration"] == {
        "numerator": 0,
        "denominator": 19,
    }
    serialized = json.dumps(report, sort_keys=True)
    assert "/tmp/roboclaws-cloudml" not in serialized
    assert "acceptable_destinations" not in serialized
    stalled = [row for row in report["triage"]["rows"] if row.get("timeout_budget_s") == 180]
    assert stalled and stalled[0]["failure_class"] == "environment_blocked"
    assert all(
        cohort["claims"]["latency"]["state"] == "incomparable"
        for cohort in report["provider_comparison"]["cohorts"]
    )


def _manifest(tmp_path: Path, *, mode: str = "execute", rows: list[dict] | None = None) -> dict:
    return {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": mode,
        "budget": "focused",
        "profile": "adaptive",
        "output_dir": str(tmp_path),
        "summary": {"selected_row_count": len(rows or [])},
        "rows": rows or [],
    }


def _row(row_id: str, *, outcome: str = "passed", artifacts: list[str] | None = None) -> dict:
    return {
        "row_id": row_id,
        "row_kind": "live_agent_eval",
        "selected": True,
        "status": "ran" if outcome else "running",
        "outcome": outcome,
        "axes": {},
        "output_artifacts": artifacts or [],
        "command_display": "eval fixture",
        "reason_selected": "fixture",
        "skip_reason": "",
    }


def _bundle(provider: str, run_dir: Path) -> dict:
    return {
        "schema": "roboclaws_eval_results_bundle_v1",
        "results": [
            {
                "status": "passed",
                "failure_class": "not_applicable",
                "identity": {
                    "suite_id": "suite",
                    "suite_version": "1",
                    "sample_id": "sample",
                    "sample_version": "1",
                    "trial_id": f"{provider}-0000",
                    "seed": 7,
                    "agent_engine": "openai-agents-sdk",
                    "provider_profile": provider,
                    "model": provider,
                    "surface": "household-world",
                    "runtime": {"hardware": "local"},
                },
                "metrics": {"wall_time_s": 2.0, "tool_call_count": 1},
                "artifacts": {"run_dir": str(run_dir)},
            }
        ],
    }


def _call(provider: str, duration: float | None) -> dict:
    return {
        "schema": "roboclaws_model_call_metric_v1",
        "agent_engine": "openai-agents-sdk",
        "provider_profile": provider,
        "model": provider,
        "wire_api": "responses",
        "duration_s": duration,
        "input_tokens": 10 if duration is not None else None,
        "uncached_input_tokens": 10 if duration is not None else None,
        "cached_input_tokens": 0 if duration is not None else None,
        "output_tokens": 1 if duration is not None else None,
        "reasoning_tokens": 0 if duration is not None else None,
    }
