from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_agent_sdk_perf_matrix.py"


def _load_matrix_module():
    spec = importlib.util.spec_from_file_location("run_agent_sdk_perf_matrix", MATRIX_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_agent_sdk_perf_matrix_dry_run_lists_rows_and_budgets(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70)
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    output = capsys.readouterr().out
    assert status == 0
    assert "Agent SDK speedup matrix dry-run" in output
    assert "provider_calls_planned: False" in output
    assert "gpt_world_public_group0" in output
    assert "unsupported_provider" in output
    assert '"max_live_runs": 0' in output


def test_agent_sdk_perf_matrix_rejects_missing_manifest(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    manifest = tmp_path / "missing-matrix.json"

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    assert status == 1
    err = capsys.readouterr().err
    assert "could not read matrix manifest" in err
    assert "matrix manifest source is missing" in err
    assert str(manifest) in err


def test_agent_sdk_perf_matrix_rejects_malformed_manifest(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    manifest = tmp_path / "matrix.json"
    manifest.write_text("{not-json\n", encoding="utf-8")

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    assert status == 1
    err = capsys.readouterr().err
    assert "could not read matrix manifest" in err
    assert "matrix manifest source must contain valid JSON object" in err
    assert str(manifest) in err


def test_agent_sdk_perf_matrix_rejects_non_object_manifest(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    manifest = tmp_path / "matrix.json"
    manifest.write_text("[]\n", encoding="utf-8")

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    assert status == 1
    assert "matrix manifest must be a JSON object" in capsys.readouterr().err


def test_agent_sdk_perf_matrix_rejects_manifest_without_rows(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    manifest = tmp_path / "matrix.json"
    manifest.write_text(
        json.dumps({"schema": "agent_sdk_speedup_matrix_v1"}),
        encoding="utf-8",
    )

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    assert status == 1
    err = capsys.readouterr().err
    assert "matrix manifest rows must be a non-empty JSON array" in err
    assert str(manifest) in err


def test_agent_sdk_perf_matrix_rejects_empty_manifest_rows(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    manifest = tmp_path / "matrix.json"
    manifest.write_text(
        json.dumps({"schema": "agent_sdk_speedup_matrix_v1", "rows": []}),
        encoding="utf-8",
    )

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    assert status == 1
    assert "matrix manifest rows must be a non-empty JSON array" in capsys.readouterr().err


def test_agent_sdk_perf_matrix_rejects_wrong_shaped_manifest_rows(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    manifest = tmp_path / "matrix.json"
    manifest.write_text(
        json.dumps({"schema": "agent_sdk_speedup_matrix_v1", "rows": ["not-a-row"]}),
        encoding="utf-8",
    )

    status = matrix.main(["--manifest", str(manifest), "--dry-run"])

    assert status == 1
    assert "matrix manifest row 1 must be a JSON object" in capsys.readouterr().err


def test_agent_sdk_perf_matrix_blocks_privacy_leak(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(
        tmp_path / "candidate",
        restored=5,
        elapsed_s=70,
        live_timing_extra={"raw_prompt": "do not persist me", "note": "Bearer top-secret"},
    )
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "privacy gate failed" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "blocked"
    assert row["privacy_gate"]["status"] == "failed"
    reasons = {finding["reason"] for finding in row["privacy_gate"]["findings"]}
    assert "forbidden key raw_prompt" in reasons
    assert "forbidden marker bearer " in reasons


def test_agent_sdk_perf_matrix_blocks_model_call_metric_privacy_leak(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70)
    (candidate / "model_call_metrics.jsonl").write_text(
        json.dumps(
            {
                "schema": "roboclaws_model_call_metric_v1",
                "agent_engine": "codex-cli",
                "raw_prompt": "do not persist me",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "privacy gate failed" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    reasons = {finding["reason"] for finding in row["privacy_gate"]["findings"]}
    assert "forbidden key raw_prompt" in reasons


def test_agent_sdk_perf_matrix_blocks_openai_agents_event_privacy_leak(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70)
    (candidate / "openai-agents-events.jsonl").write_text(
        json.dumps(
            {
                "schema": "openai_agents_model_input_filter_v1",
                "event": "model_input_filter",
                "metrics": {"input_bytes_reduced": 1200},
                "raw_prompt": "do not persist me",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "privacy gate failed" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    reasons = {finding["reason"] for finding in row["privacy_gate"]["findings"]}
    assert "forbidden key raw_prompt" in reasons


def test_agent_sdk_perf_matrix_rejects_faster_but_worse_quality(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=4, elapsed_s=50)
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "behavior quality regressed" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "rejected"
    assert row["quality_comparison"]["regressed"] is True
    assert row["speed_comparison"]["elapsed_delta_s"] == -50.0


def test_agent_sdk_perf_matrix_allows_expected_rejected_evidence_row(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=4, elapsed_s=50)
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        expected_decision_status="rejected",
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "rejected"
    assert row["expected_decision_status"] == "rejected"
    assert packet["summary"]["rejected"] == ["gpt_world_public_group0"]


def test_agent_sdk_perf_matrix_records_expected_blocked_evidence_row(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(
        tmp_path / "baseline",
        restored=0,
        elapsed_s=20,
        status={"phase": "failed", "reason": "agent_cli_failure", "exit_status": 1},
        run_result=False,
    )
    candidate = _write_run(
        tmp_path / "candidate",
        restored=0,
        elapsed_s=20,
        status={"phase": "failed", "reason": "agent_cli_failure", "exit_status": 1},
        run_result=False,
    )
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        expected_terminal="agent_cli_failure",
        expected_decision_status="blocked",
        feature_flags_extra={"expected_blocked_evidence": True},
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "blocked"
    assert row["expected_decision_status"] == "blocked"
    assert "expected blocked evidence" in row["reasons"]
    assert packet["summary"]["blocked"] == ["gpt_world_public_group0"]


def test_agent_sdk_perf_matrix_accepts_same_or_better_and_reports_buckets(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=80)
    candidate = _write_run(
        tmp_path / "candidate",
        restored=5,
        elapsed_s=70,
        gap_s=50,
        trace_events=[
            _trace_request("observe_camera_grounded_candidates", {}),
            _trace_response("observe_camera_grounded_candidates"),
            _trace_response("metric_map"),
            _trace_response("metric_map"),
            _trace_request(
                "declare_visual_candidates",
                {"observation_id": "raw_fpv_001"},
            ),
            _trace_response("declare_visual_candidates"),
        ],
    )
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        lane="camera-grounded-labels",
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "accepted"
    assert row["quality_comparison"]["regressed"] is False
    assert packet["rows"][1]["status"] == "unsupported"
    assert packet["summary"]["unsupported"] == ["unsupported_provider"]
    report = row["reducible_bucket_report"]
    assert report["available"] is True
    assert report["tool_handler_s"] == 5.0
    assert report["failed_or_noop_tool_count"] == 0
    assert report["dominant_bucket"] == "model_or_sdk_between_tool_gap"
    assert report["camera_grounded_tool_breakdown"] == {
        "observe_camera_grounded_candidates": 1,
        "declare_visual_candidates_requests": 1,
        "composite_internal_declare_visual_candidates": 0,
        "standalone_declare_visual_candidates": 1,
    }
    assert report["latency_buckets"] == {
        "model_or_sdk_between_tool_gap": {"seconds": 50.0, "share": 0.7143, "reducible": True},
        "visual_capture": {"seconds": 20.0, "share": 0.2857, "reducible": True},
        "mcp_backend_tool_handler": {"seconds": 5.0, "share": 0.0714, "reducible": False},
        "residual_or_unattributed": {"seconds": 0.0, "share": 0.0, "reducible": False},
    }
    candidate_ids = {
        candidate_id for item in report["recommendations"] for candidate_id in item["candidate_ids"]
    }
    assert {"O", "N"}.issubset(candidate_ids)
    recommendation_summary = packet["summary"]["recommendation_summary"]
    assert recommendation_summary["source"] == "reducible_bucket_report"
    assert recommendation_summary["claim_scope"] == "no-provider diagnostic recommendation evidence"
    assert recommendation_summary["candidate_counts"]["O"] == 1
    assert recommendation_summary["candidate_counts"]["N"] == 1
    assert recommendation_summary["candidate_group_counts"]["group2_lane_specific_reductions"] == 2
    assert recommendation_summary["dominant_bucket_counts"] == {"model_or_sdk_between_tool_gap": 1}
    assert {"O", "N"}.issubset(set(recommendation_summary["top_candidate_ids"]))
    assert recommendation_summary["top_candidate_groups"][0] == "group2_lane_specific_reductions"
    assert recommendation_summary["row_recommendations"] == [
        {
            "row_id": "gpt_world_public_group0",
            "evidence_lane": "camera-grounded-labels",
            "dominant_bucket": "model_or_sdk_between_tool_gap",
            "candidate_groups": [
                "group1_private_sdk_levers",
                "group2_lane_specific_reductions",
            ],
            "candidate_ids": ["A", "G", "H", "I", "J", "L", "N", "O"],
        }
    ]


def test_agent_sdk_perf_matrix_blocks_malformed_candidate_source(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70)
    (candidate / "trace.jsonl").write_text(
        json.dumps(_trace_response("observe")) + "\n{not-json}\n",
        encoding="utf-8",
    )
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "run source error" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "blocked"
    assert row["quality_comparison"] == {}
    assert row["speed_comparison"] == {}
    assert row["reducible_bucket_report"] == {"available": False, "recommendations": []}
    assert any("trace.jsonl:2" in reason for reason in row["reasons"])


def test_agent_sdk_perf_matrix_blocks_non_object_candidate_source(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70)
    (candidate / "trace.jsonl").write_text('["not", "an", "object"]\n', encoding="utf-8")
    manifest = _write_manifest(tmp_path, baseline=baseline, candidate=candidate)
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "run source error" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "blocked"
    assert any("trace.jsonl:1" in reason and "JSON object" in reason for reason in row["reasons"])


def test_agent_sdk_perf_matrix_uses_row_calibration_for_normalized_deltas(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=80)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70, gap_s=50)
    _write_model_call_metrics(
        baseline,
        input_tokens=120,
        cached_input_tokens=20,
        output_tokens=10,
        duration_s=30.0,
    )
    _write_model_call_metrics(
        candidate,
        input_tokens=80,
        cached_input_tokens=0,
        output_tokens=5,
        duration_s=12.0,
    )
    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "schema": "roboclaws_model_latency_calibration_v1",
                "available": True,
                "sample_count": 40,
                "total_row_count": 40,
                "limitations": ["not_repo_default_calibration"],
                "coefficients": {
                    "intercept_s": 1.0,
                    "uncached_input_s_per_token": 0.1,
                    "cached_input_s_per_token": 0.0,
                    "output_s_per_token": 0.2,
                    "reasoning_s_per_token": 0.0,
                    "image_s_per_unit": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        calibration_path=calibration,
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    speed = row["speed_comparison"]
    assert row["artifact_links"]["calibration"] == str(calibration)
    assert speed["observed_model_api_delta_s"] == -18.0
    assert speed["estimated_model_work_delta_s"] == -3.0
    assert speed["model_latency_residual_delta_s"] == -15.0
    assert speed["candidate_estimated_model_work_s"]["limitations"] == [
        "not_repo_default_calibration"
    ]
    assert "_calibration" not in row


def test_agent_sdk_perf_matrix_blocks_malformed_calibration_source(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=80)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70, gap_s=50)
    calibration = tmp_path / "calibration.json"
    calibration.write_text("{not-json\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        calibration_path=calibration,
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "calibration source error" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "blocked"
    assert row["quality_comparison"] == {}
    assert row["speed_comparison"] == {}
    assert row["reducible_bucket_report"] == {"available": False, "recommendations": []}
    assert any(
        "calibration source error" in reason and "calibration.json" in reason
        for reason in row["reasons"]
    )


def test_agent_sdk_perf_matrix_blocks_non_object_calibration_source(
    tmp_path: Path,
    capsys,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=80)
    candidate = _write_run(tmp_path / "candidate", restored=5, elapsed_s=70, gap_s=50)
    calibration = tmp_path / "calibration.json"
    calibration.write_text("[]\n", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        calibration_path=calibration,
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 1
    assert "calibration source error" in capsys.readouterr().err
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "blocked"
    assert any(
        "calibration source error" in reason and "expected object" in reason
        for reason in row["reasons"]
    )


def test_agent_sdk_perf_matrix_does_not_recommend_o_for_composite_internal_declare(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100, gap_s=80)
    candidate = _write_run(
        tmp_path / "candidate",
        restored=5,
        elapsed_s=70,
        gap_s=50,
        trace_events=[
            _trace_request("observe_camera_grounded_candidates", {}),
            _trace_response("observe"),
            _trace_request("declare_visual_candidates", {"observation_id": "raw_fpv_001"}),
            _trace_response("declare_visual_candidates"),
            _trace_response("observe_camera_grounded_candidates"),
        ],
    )
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        lane="camera-grounded-labels",
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    report = packet["rows"][0]["reducible_bucket_report"]
    assert report["camera_grounded_tool_breakdown"] == {
        "observe_camera_grounded_candidates": 1,
        "declare_visual_candidates_requests": 1,
        "composite_internal_declare_visual_candidates": 1,
        "standalone_declare_visual_candidates": 0,
    }
    candidate_ids = {
        candidate_id for item in report["recommendations"] for candidate_id in item["candidate_ids"]
    }
    assert "O" not in candidate_ids
    assert packet["summary"]["recommendation_summary"]["candidate_counts"].get("O") is None


def test_agent_sdk_perf_matrix_accepts_expected_raw_fpv_diagnostic_terminal(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(
        tmp_path / "baseline",
        restored=0,
        elapsed_s=300,
        status={"phase": "failed", "reason": "provider_transient_failure", "exit_status": 1},
        run_result=False,
        trace_tools=[
            "navigate_to_visual_candidate",
            "navigate_to_visual_candidate",
            "navigate_to_visual_candidate",
        ],
    )
    candidate = _write_run(
        tmp_path / "candidate",
        restored=0,
        elapsed_s=180,
        status={
            "phase": "failed",
            "reason": "raw_fpv_sdk_turn_budget_exhausted",
            "exit_status": 1,
        },
        run_result=False,
        trace_tools=["navigate_to_visual_candidate"],
    )
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=candidate,
        lane="camera-raw-fpv",
        expected_terminal="raw_fpv_sdk_turn_budget_exhausted",
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    row = packet["rows"][0]
    assert row["status"] == "accepted"
    assert "raw-FPV accepted as classified diagnostic evidence" in row["reasons"]
    assert row["quality_comparison"]["regressed"] is True


def test_agent_sdk_perf_matrix_summarizes_candidate_coverage(
    tmp_path: Path,
) -> None:
    matrix = _load_matrix_module()
    baseline = _write_run(tmp_path / "baseline", restored=5, elapsed_s=100)
    accepted = _write_run(tmp_path / "accepted", restored=5, elapsed_s=70)
    rejected = _write_run(tmp_path / "rejected", restored=4, elapsed_s=50)
    blocked = _write_run(
        tmp_path / "blocked",
        restored=0,
        elapsed_s=20,
        status={"phase": "failed", "reason": "agent_cli_failure", "exit_status": 1},
        run_result=False,
    )
    manifest = _write_manifest(
        tmp_path,
        baseline=baseline,
        candidate=accepted,
        candidate_groups=[
            {"group_id": "group1_private_sdk_levers", "candidate_ids": ["A", "I"]},
            {"group_id": "group2_lane_specific_reductions", "candidate_ids": ["F"]},
            {"group_id": "group3_raw_fpv_stabilization", "candidate_ids": ["P"]},
            {"group_id": "group4_expensive_orchestration", "candidate_ids": ["C", "K"]},
            {"group_id": "group5_promotion_and_compatibility", "candidate_ids": ["X"]},
        ],
        candidate_queue=[
            {
                "candidate_id": "A",
                "queue": "accepted",
                "row_policy": "deterministic_only",
                "coverage_state_when_no_row": "accepted_deterministic_no_live_refresh_row",
                "next_action": "keep deterministic proof",
            },
            {
                "candidate_id": "K",
                "queue": "bypass-for-now",
                "row_policy": "no_live_row_until_parallelism_hypothesis",
                "coverage_state_when_no_row": "bypassed_no_live_refresh_row",
                "next_action": "revisit only for read-only tools",
            },
            {
                "candidate_id": "X",
                "queue": "gate-conditional",
                "row_policy": "promotion_gate_only",
                "coverage_state_when_no_row": "conditional_gate_no_live_refresh_row",
                "next_action": "run before promotion",
            },
        ],
        extra_rows=[
            {
                "row_id": "rejected_f",
                "provider_profile": "kimi-openai-chat",
                "model": "gpt-5.5",
                "evidence_lane": "world-public-labels",
                "candidate_group": "group0_foundation",
                "candidate_ids": ["Q", "Y"],
                "dependency_candidate_ids": ["F"],
                "feature_flags": {
                    "expected_rejected_evidence": True,
                    "offline_preflight": True,
                    "provider_calls": False,
                    "quality_comparator": True,
                },
                "stop_conditions": ["privacy_gate_failed", "unexpected_decision_status"],
                "baseline_role": "completed_live_responses_baseline",
                "baseline_run_dir": str(baseline),
                "candidate_run_dir": str(rejected),
                "provider_calls": False,
                "expected_terminal": "finished",
                "expected_decision_status": "rejected",
            },
            {
                "row_id": "blocked_p",
                "provider_profile": "kimi-openai-chat",
                "model": "gpt-5.5",
                "evidence_lane": "camera-raw-fpv",
                "candidate_group": "group0_foundation",
                "candidate_ids": ["Q", "Y"],
                "dependency_candidate_ids": ["P"],
                "feature_flags": {
                    "expected_blocked_evidence": True,
                    "offline_preflight": True,
                    "provider_calls": False,
                    "quality_comparator": True,
                },
                "stop_conditions": ["privacy_gate_failed", "unexpected_decision_status"],
                "baseline_role": "blocked_live_baseline",
                "baseline_run_dir": str(blocked),
                "candidate_run_dir": str(blocked),
                "provider_calls": False,
                "expected_terminal": "agent_cli_failure",
                "expected_decision_status": "blocked",
            },
        ],
    )
    decision_packet = tmp_path / "decision.json"

    status = matrix.main(
        [
            "--manifest",
            str(manifest),
            "--offline-preflight",
            "--decision-packet",
            str(decision_packet),
        ]
    )

    assert status == 0
    packet = json.loads(decision_packet.read_text(encoding="utf-8"))
    coverage = packet["summary"]["candidate_coverage"]
    assert coverage["source"] == "candidate_groups_and_decision_rows"
    assert packet["candidate_queue"] == [
        {
            "candidate_id": "A",
            "queue": "accepted",
            "row_policy": "deterministic_only",
            "coverage_state_when_no_row": "accepted_deterministic_no_live_refresh_row",
            "next_action": "keep deterministic proof",
        },
        {
            "candidate_id": "K",
            "queue": "bypass-for-now",
            "row_policy": "no_live_row_until_parallelism_hypothesis",
            "coverage_state_when_no_row": "bypassed_no_live_refresh_row",
            "next_action": "revisit only for read-only tools",
        },
        {
            "candidate_id": "X",
            "queue": "gate-conditional",
            "row_policy": "promotion_gate_only",
            "coverage_state_when_no_row": "conditional_gate_no_live_refresh_row",
            "next_action": "run before promotion",
        },
    ]
    assert coverage["candidate_count"] == 17
    assert coverage["state_counts"]["accepted_only"] >= 1
    assert coverage["state_counts"]["rejected_only"] == 1
    assert coverage["state_counts"]["blocked_only"] == 1
    assert coverage["state_counts"]["no_decision_row"] == 5
    assert coverage["coverage_state_counts"]["accepted_deterministic_no_live_refresh_row"] == 1
    assert coverage["coverage_state_counts"]["bypassed_no_live_refresh_row"] == 1
    assert coverage["coverage_state_counts"]["conditional_gate_no_live_refresh_row"] == 1
    assert {"A", "C", "I", "K", "X"} == set(coverage["no_decision_row_candidate_ids"])
    assert {"C", "I"} == set(coverage["unresolved_no_row_candidate_ids"])
    items = {item["candidate_id"]: item for item in coverage["items"]}
    assert items["R"]["evidence_state"] == "accepted_only"
    assert items["F"]["evidence_state"] == "rejected_only"
    assert items["P"]["evidence_state"] == "blocked_only"
    assert items["C"]["evidence_state"] == "no_decision_row"
    assert items["A"]["coverage_state"] == "accepted_deterministic_no_live_refresh_row"
    assert items["A"]["queue"] == "accepted"
    assert items["A"]["row_policy"] == "deterministic_only"
    assert items["A"]["next_action"] == "keep deterministic proof"
    assert items["K"]["coverage_state"] == "bypassed_no_live_refresh_row"
    assert items["X"]["coverage_state"] == "conditional_gate_no_live_refresh_row"
    assert items["R"]["row_ids"] == ["gpt_world_public_group0"]
    assert items["F"]["row_ids"] == ["rejected_f"]
    assert items["P"]["row_ids"] == ["blocked_p"]
    assert items["C"]["row_ids"] == []
    assert "do not rerun unchanged" in items["F"]["next_action"]
    assert "recorded provider/backend/capability blocker changes" in items["P"]["next_action"]
    assert "no decision-row evidence yet" in items["C"]["next_action"]


def _write_manifest(
    tmp_path: Path,
    *,
    baseline: Path,
    candidate: Path,
    lane: str = "world-public-labels",
    expected_terminal: str = "finished",
    expected_decision_status: str = "",
    feature_flags_extra: dict[str, object] | None = None,
    calibration_path: Path | None = None,
    candidate_groups: list[dict[str, object]] | None = None,
    candidate_queue: list[dict[str, object]] | None = None,
    extra_rows: list[dict[str, object]] | None = None,
) -> Path:
    feature_flags = {
        "dry_run_matrix": True,
        "offline_preflight": True,
        "privacy_gate": True,
        "provider_calls": False,
        "quality_comparator": True,
        "reducible_bucket_report": True,
    }
    if feature_flags_extra:
        feature_flags.update(feature_flags_extra)
    rows: list[dict[str, object]] = [
        {
            "row_id": "gpt_world_public_group0",
            "provider_profile": "kimi-openai-chat",
            "model": "gpt-5.5",
            "evidence_lane": lane,
            "candidate_group": "group0_foundation",
            "candidate_ids": ["R", "S", "T", "U", "V", "W", "Y", "B", "Z", "Q"],
            "dependency_candidate_ids": [],
            "feature_flags": feature_flags,
            "stop_conditions": [
                "privacy_gate_failed",
                "quality_regression",
                "provider_calls_planned",
            ],
            "baseline_role": "full_lane_baseline",
            "baseline_run_dir": str(baseline),
            "candidate_run_dir": str(candidate),
            "calibration_path": str(calibration_path or ""),
            "provider_calls": False,
            "expected_terminal": expected_terminal,
            "expected_decision_status": expected_decision_status,
        },
        {
            "row_id": "unsupported_provider",
            "provider_profile": "unsupported-provider-route",
            "model": "kimi",
            "evidence_lane": lane,
            "candidate_group": "group0_foundation",
            "candidate_ids": ["B"],
            "dependency_candidate_ids": [],
            "feature_flags": {"unsupported_matrix_row": True, "provider_calls": False},
            "stop_conditions": ["unsupported_provider_route"],
            "provider_calls": False,
            "unsupported_reason": "unsupported provider route",
        },
    ]
    if extra_rows:
        rows.extend(extra_rows)
    manifest = tmp_path / "matrix.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "agent_sdk_speedup_matrix_v1",
                "budget_caps": {
                    "concurrency": 1,
                    "max_live_runs": 0,
                    "max_wall_clock_s": 0,
                    "racing_multiplier": 1.0,
                },
                "candidate_groups": candidate_groups
                or [
                    {
                        "group_id": "group0_foundation",
                        "candidate_ids": ["R", "S", "T", "U", "V", "W", "Y", "B", "Z", "Q"],
                    }
                ],
                "candidate_queue": candidate_queue or [],
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _write_run(
    run_dir: Path,
    *,
    restored: int,
    elapsed_s: float,
    gap_s: float = 40.0,
    trace_tools: list[str] | None = None,
    trace_events: list[dict[str, object]] | None = None,
    live_timing_extra: dict[str, object] | None = None,
    status: dict[str, object] | None = None,
    run_result: bool = True,
) -> Path:
    run_dir.mkdir()
    timing = {
        "runtime": "openai-agents-live",
        "provider_profile": "kimi-openai-chat",
        "wire_api": "responses",
        "model": "gpt-5.5",
        "evidence_lane": "world-public-labels",
        "runner_timing": {"total_elapsed_s": elapsed_s},
        "mcp_trace_timing": {
            "between_tool_gap_s": gap_s,
            "robot_view_capture_s": 20.0,
            "tool_handler_s": 5.0,
        },
    }
    if live_timing_extra:
        timing.update(live_timing_extra)
    (run_dir / "live_timing.json").write_text(json.dumps(timing), encoding="utf-8")
    (run_dir / "live_status.json").write_text(
        json.dumps(status or {"phase": "finished", "exit_status": 0}),
        encoding="utf-8",
    )
    if run_result:
        (run_dir / "run_result.json").write_text(
            json.dumps(
                {
                    "cleanup_status": "success",
                    "completion_status": "success",
                    "mess_restoration_rate": restored / 5,
                    "sweep_coverage_rate": 1.0,
                    "disturbance_count": 0,
                    "score": {
                        "restored_count": restored,
                        "total_targets": 5,
                        "mess_restoration_rate": restored / 5,
                        "disturbance_count": 0,
                        "object_results": [
                            {"restored": True, "semantic_acceptability": "preferred"}
                            for _ in range(restored)
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
    events = trace_events
    tools = trace_tools or ["observe", "navigate_to_object", "pick", "place", "done"]
    if events is None:
        events = [_trace_response(tool) for tool in tools]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    return run_dir


def _write_model_call_metrics(
    run_dir: Path,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    duration_s: float,
) -> None:
    row = {
        "event": "span_end",
        "span_type": "response",
        "duration_s": duration_s,
        "provider_profile": "kimi-openai-chat",
        "wire_api": "responses",
        "model": "gpt-5.5",
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": cached_input_tokens},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    (run_dir / "openai-agents-spans.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _trace_request(tool: str, request: dict[str, object]) -> dict[str, object]:
    return {"event": "request", "tool": tool, "request": request}


def _trace_response(tool: str) -> dict[str, object]:
    return {"event": "response", "tool": tool, "response": {"ok": True}}
