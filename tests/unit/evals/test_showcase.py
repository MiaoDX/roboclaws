import json
from pathlib import Path

import pytest

from roboclaws.evals.public_reports import _published_visual_report_href
from roboclaws.evals.showcase import (
    _load_execution_indexes,
    _published_report_href,
    _row_command,
    build_summary,
    derive_row,
    execute_manifest,
    manifest_digest,
    render_html,
    validate_manifest,
)


def test_published_report_href_matches_pages_allowlist() -> None:
    execution = Path("output/showcase/kimi/execution.json")
    result = "output/showcase/kimi/evals/household_world_cleanup/run-1/eval_results.json"

    assert _published_report_href(execution, result) == (
        "reports/kimi/evals/household_world_cleanup/run-1/eval_report.html"
    )
    assert _published_report_href(execution, "output/private/eval_results.json") is None


def test_published_visual_report_href_matches_nested_run_report() -> None:
    execution = Path("output/showcase/kimi/execution.json")
    result = (
        "output/showcase/kimi/evals/household_world_open_ended_goals/run-1/"
        "runs/sample/trial-0000/surface-run/seed-7/report.html"
    )

    assert _published_visual_report_href(execution, result) == (
        "reports/kimi/evals/household_world_open_ended_goals/run-1/"
        "runs/sample/trial-0000/surface-run/seed-7/report.html"
    )
    assert _published_visual_report_href(execution, "output/private/report.html") is None
    assert (
        _published_visual_report_href(execution, "output/showcase/kimi/evals/../report.html")
        is None
    )


@pytest.mark.parametrize("trial_count,report_exists", [(1, True), (1, False), (2, True)])
def test_showcase_links_existing_single_run_report(tmp_path, trial_count, report_exists):
    from roboclaws.evals.public_reports import publish_report_bundle

    shard = tmp_path / "kimi"
    result_path = shard / "evals" / "cleanup" / "run-1" / "eval_results.json"
    report_path = result_path.parent / "runs" / "trial-0000" / "report.html"
    report_path.parent.mkdir(parents=True)
    if report_exists:
        report_path.write_text('<html><body><img src="before.png"></body></html>')
    result_path.write_text(
        json.dumps({"results": [{"artifacts": {"report": str(report_path)}}] * trial_count})
    )
    execution = shard / "execution.json"
    execution.write_text(json.dumps({"results": {"cleanup": str(result_path)}}))

    _, _, summaries, visuals = _load_execution_indexes([execution])

    assert summaries["cleanup"] == "reports/kimi/evals/cleanup/run-1/eval_report.html"
    if trial_count == 1 and report_exists:
        assert visuals["cleanup"] == (
            "reports/kimi/evals/cleanup/run-1/runs/trial-0000/report.html"
        )
        site = tmp_path / "site"
        publish_report_bundle(shard / "evals", site / "reports" / "kimi" / "evals")
        assert (site / visuals["cleanup"]).is_file()
    else:
        assert visuals == {}


def manifest():
    source = json.loads(
        (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
    )
    return {**source, "rows": [source["rows"][0]]}


def test_summary_preserves_last_success_per_row_and_is_sanitized():
    m = manifest()
    passed = derive_row(m["rows"][0], {"aggregate": {"total": 1, "passed": 1, "pass_at_1": 1.0}})
    first = build_summary(
        m, [passed], commit="abc", run_url="run", attempted_at="2026-01-01T00:00:00Z"
    )
    blocked = derive_row(m["rows"][0], None)
    second = build_summary(
        m,
        [blocked],
        commit="def",
        run_url="run2",
        attempted_at="2026-01-02T00:00:00Z",
        previous=first,
    )
    assert second["rows"][0]["status"] == "blocked"
    assert second["last_success"]["household_world.smoke_regression"]["commit"] == "abc"
    assert second["manifest_digest"] == manifest_digest(m)
    assert passed["sample_ids"] == ["cleanup.smoke_seed7"]


def test_private_fields_are_rejected_recursively():
    m = manifest()
    with pytest.raises(ValueError, match="private field"):
        build_summary(
            m,
            [{"id": "household_world.smoke_regression", "prompt": "secret", "status": "passed"}],
            commit="a",
            run_url="r",
        )


def test_manifest_rejects_duplicate_ids():
    m = manifest()
    m["rows"].append(dict(m["rows"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(m)


@pytest.mark.parametrize(
    "key,value",
    [("timeout_s", 0), ("stall_timeout_s", -1), ("decision_call_budget", 0)],
)
def test_manifest_rejects_non_positive_budgets(key, value):
    m = manifest()
    if key == "decision_call_budget":
        m["rows"] = [
            row
            for row in json.loads(
                (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
            )["rows"]
            if row["execution_mode"] != "deterministic"
        ][:1]
    m["rows"][0][key] = value
    with pytest.raises(ValueError, match=f"invalid {key}"):
        validate_manifest(m)


def test_empty_attempt_is_blocked_not_passed():
    m = manifest()
    row = derive_row(m["rows"][0], {"aggregate": {}})
    assert row["status"] == "blocked"
    assert row["reason"] == "incomplete_attempt"


def test_unrequested_live_attempt_is_not_run():
    m = manifest()
    row = derive_row(m["rows"][0], None, missing_reason="live_execution_not_requested")
    assert row["status"] == "not_run"
    assert row["reason"] == "live_execution_not_requested"


def test_manifest_matches_canonical_suite_fixtures():
    root = Path(__file__).resolve().parents[3]
    validate_manifest(json.loads((root / "config/showcase-manifest.json").read_text()))


def test_public_map_build_showcase_uses_default_minimax_route():
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "config/showcase-manifest.json").read_text())
    row = next(row for row in manifest["rows"] if row["id"] == "household_world.map_build_quality")
    assert row["provider_profile"] == "minimax-responses"


def test_showcase_provider_lanes_follow_capacity_policy():
    from roboclaws.evals.showcase import showcase_lane

    assert showcase_lane("minimax-responses") == ("public-primary", 1)
    assert showcase_lane("mimo-tp-openai-chat") == ("public-primary", 2)
    assert showcase_lane("kimi-openai-chat") == ("unclassified", 99)
    assert showcase_lane("qwen-tp-responses") == ("unclassified", 99)


def test_manifest_rejects_evidence_identity_that_disagrees_with_selected_sample():
    root = Path(__file__).resolve().parents[3]
    m = json.loads((root / "config/showcase-manifest.json").read_text())
    row = next(row for row in m["rows"] if row["id"] == "household_world.map_build_quality")
    row["evidence_lane"] = "camera-grounded-labels"
    row["camera_labeler"] = "grounding-dino"

    with pytest.raises(ValueError, match="does not match selected sample"):
        validate_manifest(m)


def test_execute_manifest_does_not_run_model_lane_without_live_request(tmp_path):
    root = Path(__file__).resolve().parents[3]
    m = json.loads((root / "config/showcase-manifest.json").read_text())
    m["rows"] = [m["rows"][-1]]
    result = execute_manifest(m, output_dir=tmp_path, live_execution="blocked")
    assert result["results"] == {}
    assert result["attempts"] == [
        {
            "id": "household_world.open_ended_goals.minimax",
            "state": "blocked",
            "reason": "live_execution_not_requested",
            "agent_engine": "openai-agents-sdk",
            "provider_profile": "minimax-responses",
            "decision_call_budget": 16,
        }
    ]


def test_model_lane_live_command_uses_canonical_provider_identity(tmp_path):
    root = Path(__file__).resolve().parents[3]
    m = json.loads((root / "config/showcase-manifest.json").read_text())
    row = next(row for row in m["rows"] if row["id"] == "household_world.open_ended_goals.minimax")
    command = _row_command(row, live_execution="run", output_dir=tmp_path)
    assert command is not None
    assert "agent_engine=openai-agents-sdk" in command
    assert "provider_profile=minimax-responses" in command
    assert "live_execution=run" in command
    assert "live_timeout_s=1800" in command
    assert "live_stall_timeout_s=120" in command
    assert "decision_call_budget=16" in command
    assert "sample_id=open_ended.bread_seed7" in command
    assert "repetition_index=0" in command


def test_execute_manifest_keeps_contract_smoke_deterministic(tmp_path):
    root = Path(__file__).resolve().parents[3]
    m = json.loads((root / "config/showcase-manifest.json").read_text())
    m["rows"] = [m["rows"][0]]
    result = execute_manifest(m, output_dir=tmp_path, live_execution="blocked")
    assert "household_world.smoke_regression" in result["results"]
    assert result["attempts"][0]["agent_engine"] == "direct-runner"


def test_row_identity_comes_from_canonical_result_not_available_live_profile():
    row = json.loads(
        (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
    )["rows"][1]
    result = derive_row(
        row,
        {
            "aggregate": {"total": 1, "passed": 1},
            "results": [
                {
                    "identity": {
                        "agent_engine": "direct-runner",
                        "provider_profile": "not_applicable",
                        "evidence_lane": "world-public-labels",
                    }
                }
            ],
        },
    )
    assert result["agent_engine"] == "direct-runner"
    assert result["provider_profile"] == "not_applicable"
    assert result["evidence_lane"] == "world-public-labels"
    assert result["camera_labeler"] == "not_applicable"


def test_row_fails_when_runtime_identity_disagrees_with_manifest():
    row = manifest()["rows"][0]
    result = derive_row(
        row,
        {
            "aggregate": {"total": 1, "passed": 1},
            "results": [
                {
                    "identity": {
                        "evidence_lane": "camera-grounded-labels",
                        "camera_labeler": "grounding-dino",
                    }
                }
            ],
        },
    )

    assert result["status"] == "failed"
    assert result["reason"] == "showcase_identity_mismatch"


def test_showcase_html_renders_dashboard_instead_of_escaped_markdown():
    summary = {
        "attempted_at": "2026-08-27T09:51:43Z",
        "commit": "abc123",
        "run_url": "https://example.test/run",
        "artifact_url": "https://example.test/artifacts",
        "rows": [
            {
                "id": "household_world.cleanup_capability.kimi",
                "provider_profile": "kimi-openai-chat",
                "status": "blocked",
                "reason": "showcase_row_timeout",
                "report_artifact": None,
            },
            {
                "id": "household_world.cleanup_capability.mimo",
                "provider_profile": "mimo-tp-openai-chat",
                "status": "passed",
                "reason": None,
                "report_artifact": "eval_report.html",
                "report_href": "reports/mimo/evals/cleanup/run/eval_report.html",
                "visual_report_href": "reports/mimo/evals/cleanup/run/runs/sample/report.html",
            },
        ],
        "last_success": {
            "household_world.cleanup_capability.mimo": {"attempted_at": "2026-08-27T09:51:43Z"}
        },
    }

    rendered = render_html(summary)

    assert "<table>" in rendered
    assert "<pre>" not in rendered
    assert "showcase_row_timeout" in rendered
    assert "kimi-openai-chat" in rendered
    assert "public-compatibility" not in rendered
    assert 'href="reports/mimo/evals/cleanup/run/eval_report.html"' in rendered
    assert 'href="reports/mimo/evals/cleanup/run/runs/sample/report.html"' in rendered
    assert "Visual HTML report" in rendered
    assert rendered.count(">HTML report</a>") == 0
    assert rendered.count(">Eval summary</a>") == 1
    assert rendered.count('href="https://example.test/run"') == 3
    assert rendered.count(">Actions</a>") == 2
    assert rendered.count('href="https://example.test/artifacts"') == 1


@pytest.mark.parametrize(
    "counts,status",
    [
        ({"total": 3, "passed": 2, "blocked": 1}, "blocked"),
        ({"total": 3, "passed": 1, "blocked": 1, "failed": 1}, "failed"),
        ({"total": 3, "passed": 2}, "blocked"),
        ({"total": 3, "passed": 2, "not_run": 1}, "blocked"),
        ({"total": 3, "passed": 3}, "passed"),
    ],
)
def test_showcase_requires_every_case_to_pass(counts, status):
    row = derive_row(manifest()["rows"][0], {"aggregate": counts})
    assert row["status"] == status
    for key in ("total", "passed", "blocked", "failed"):
        if key in counts:
            assert row["metrics"][key] == counts[key]


def test_later_trial_identity_mismatch_cannot_pass_showcase():
    row = manifest()["rows"][0]
    results = {
        "aggregate": {"total": 2, "passed": 2},
        "results": [
            {
                "identity": {
                    "evidence_lane": "world-public-labels",
                    "camera_labeler": "not_applicable",
                }
            },
            {
                "identity": {
                    "evidence_lane": "camera-grounded-labels",
                    "camera_labeler": "grounding-dino",
                }
            },
        ],
    }
    derived = derive_row(row, results)
    assert derived["status"] == "failed"
    assert derived["reason"] == "showcase_identity_mismatch"
    assert derived["metrics"]["passed"] == 2


@pytest.mark.parametrize("actual", ["mimo-tp-openai-chat", "not_applicable", None])
def test_required_provider_row_cannot_use_another_provider(actual):
    row = next(
        row
        for row in json.loads(
            (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
        )["rows"]
        if row.get("provider_profile") == "minimax-responses"
    )
    derived = derive_row(
        row,
        {
            "aggregate": {"total": 1, "passed": 1},
            "results": [
                {
                    "identity": {
                        "agent_engine": row["agent_engine"],
                        "provider_profile": actual,
                        "evidence_lane": row["evidence_lane"],
                        "camera_labeler": row["camera_labeler"],
                    }
                }
            ],
        },
    )
    assert derived["status"] == "failed"
    assert derived["reason"] == "showcase_identity_mismatch"


@pytest.mark.parametrize("trials", [None, [], [{}], [{"identity": None}]])
def test_live_showcase_requires_trial_identity(trials):
    row = {**manifest()["rows"][0], "provider_profile": "minimax-responses"}
    result = derive_row(row, {"aggregate": {"total": 1, "passed": 1}, "results": trials})
    assert result["status"] == "blocked"
    assert result["reason"] == "incomplete_trial_identity"


@pytest.mark.parametrize("suite", ["cleanup_capability", "open_ended_goals"])
def test_compact_external_cases_are_paired_across_providers(suite):
    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
    )["rows"]
    paired = [row for row in rows if row["suite"] == suite]
    assert {row["provider_profile"] for row in paired} == {
        "minimax-responses",
        "mimo-tp-openai-chat",
    }
    fields = (
        "version",
        "sample_ids",
        "sample_id",
        "repetition_index",
        "seed",
        "evidence_lane",
        "camera_labeler",
        "budget",
        "decision_call_budget",
        "timeout_s",
        "stall_timeout_s",
    )
    assert {key: paired[0].get(key) for key in fields} == {
        key: paired[1].get(key) for key in fields
    }


def test_manifest_seed_must_match_executed_sample():
    m = manifest()
    m["rows"][0]["seed"] += 1
    with pytest.raises(ValueError, match="does not match selected sample"):
        validate_manifest(m)


def test_live_showcase_cases_allow_their_selected_provider():
    from roboclaws.evals.suite_loading import load_suite

    rows = json.loads(
        (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
    )["rows"]
    for row in rows:
        if not row.get("provider_profile"):
            continue
        _, samples = load_suite(row["suite"])
        selected = [sample for sample in samples if sample.sample_id in row["sample_ids"]]
        assert selected
        for sample in selected:
            assert row["provider_profile"] in sample.provider_profiles, row["id"]
