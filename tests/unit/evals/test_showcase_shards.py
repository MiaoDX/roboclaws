import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from roboclaws.evals import showcase_shards as shards
from roboclaws.evals.models import EvalResult, EvalTrial
from roboclaws.evals.result_persistence import persist_results
from roboclaws.evals.showcase import derive_row, manifest_digest, write_atomic
from roboclaws.evals.suite_loading import load_suite


@pytest.fixture
def manifest(monkeypatch):
    monkeypatch.setattr(shards, "repository_revision", lambda: "frozen-code")
    source = json.loads(Path("config/showcase-manifest.json").read_text())
    row = next(row for row in source["rows"] if row["id"].endswith("cleanup_capability.minimax"))
    row.update(model="MiniMax-M3", total_token_budget=16_000_000, execution_timeout_s=10830)
    row.pop("repetition_index")
    return {**source, "rows": [row]}


def evidence(manifest, plan, shard, directory, *, status="passed", mutate=None):
    row = manifest["rows"][0]
    suite, samples = shards.load_suite(row["suite"])
    sample = next(s for s in samples if s.sample_id == shard["sample_id"])
    trial = EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id=shard["id"],
        repetition_index=shard["repetition_index"],
        agent_engine=row["agent_engine"],
        runner_class="live-agent",
        provider_profile=row["provider_profile"],
        model=row["model"],
        budgets={
            "time_s": row["timeout_s"],
            "stall_timeout_s": row["timeout_s"],
            "decision_calls": row["decision_call_budget"],
            "total_tokens": row["total_token_budget"],
            "retry": 0,
        },
        runtime={"skill_delivery_cell": "static-full"},
    )
    result = EvalResult.from_trial(
        trial,
        status=status,
        grader_outputs={},
        failure_class={
            "passed": "not_applicable",
            "failed": "partial_progress_only",
            "blocked": "model_or_provider_unavailable",
        }[status],
    )
    if mutate:
        mutate(result.identity)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.html").write_text("<html>Public run evidence</html>")
    result.artifacts["report"] = str(directory / "report.html")
    _, path, _ = persist_results(
        suite=suite, results=[result], output_dir=directory / "evals", budget=row["budget"]
    )
    write_atomic(directory / "shard.json", {"plan_sha256": manifest_digest(plan), "shard": shard})
    write_atomic(
        directory / "execution.json",
        {
            "results": {row["id"]: str(path)},
            "attempts": [{"id": row["id"], "state": "completed"}],
        },
    )
    return directory


def test_every_repetition_has_budgeted_independent_shard(manifest):
    plan = shards.build_shard_plan(manifest)
    assert [s["repetition_index"] for s in plan["shards"]] == [0, 1, 2]
    assert plan["envelope"]["provider_tokens"] == 48_000_000
    assert plan["envelope"]["decision_calls"] == 300
    assert plan["max_parallel"] == 2
    assert plan["trial_retries"] == 0
    for shard in plan["shards"]:
        assert shard["timeout_minutes"] == 86
        assert shard["execution_timeout_s"] == 3630


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_token_budget", 8_000_000),
        ("model", "MiniMax-M2.7"),
        ("timeout_s", 3500),
    ],
)
def test_changed_bounds_or_model_cannot_reuse_plan(manifest, field, value):
    plan = shards.build_shard_plan(manifest)
    manifest["rows"][0][field] = value
    with pytest.raises(ValueError):
        shards.validate_plan(manifest, plan)


def test_code_and_case_content_are_part_of_frozen_identity(manifest, monkeypatch):
    plan = shards.build_shard_plan(manifest)
    monkeypatch.setattr(shards, "repository_revision", lambda: "different-code")
    with pytest.raises(ValueError, match="differs"):
        shards.validate_plan(manifest, plan)
    monkeypatch.setattr(shards, "repository_revision", lambda: "frozen-code")
    suite, samples = load_suite("cleanup_capability")
    changed = [replace(samples[0], grader_config={"min_restoration_rate": 0.1})]
    monkeypatch.setattr(shards, "load_suite", lambda _: (suite, changed))
    with pytest.raises(ValueError, match="differs"):
        shards.validate_plan(manifest, plan)


def test_live_execution_uses_existing_cli_once_and_cannot_overwrite(
    manifest, monkeypatch, tmp_path
):
    plan = shards.build_shard_plan(manifest)
    calls = []
    monkeypatch.setattr(shards, "execute_manifest", lambda m, **kw: calls.append((m, kw)))
    directory = tmp_path / "case"
    shards.execute_shard(
        manifest, plan, shard_id=plan["shards"][1]["id"], output_dir=directory, live_execution="run"
    )
    assert len(calls) == 1
    assert calls[0][0]["rows"][0]["repetition_index"] == 1
    assert calls[0][0]["rows"][0]["total_token_budget"] == 16_000_000
    with pytest.raises(FileExistsError):
        shards.execute_shard(
            manifest,
            plan,
            shard_id=plan["shards"][1]["id"],
            output_dir=directory,
            live_execution="run",
        )
    assert len(calls) == 1


def test_merge_preserves_failed_and_blocked_denominators(manifest, tmp_path):
    plan = shards.build_shard_plan(manifest)
    directories = [
        evidence(manifest, plan, s, tmp_path / s["id"], status=status)
        for s, status in zip(plan["shards"], ("passed", "failed", "blocked"), strict=True)
    ]
    index = shards.merge_shards(
        manifest, plan, shard_dirs=directories, output_dir=tmp_path / "merged"
    )
    row = manifest["rows"][0]
    packet = json.loads(Path(index["results"][row["id"]]).read_text())
    assert [r["status"] for r in packet["results"]] == ["passed", "failed", "blocked"]
    assert {k: packet["aggregate"][k] for k in ("passed", "failed", "blocked", "total")} == {
        "passed": 1,
        "failed": 1,
        "blocked": 1,
        "total": 3,
    }
    assert derive_row(row, packet)["status"] != "passed"


def test_missing_shard_cannot_be_hidden_by_passing_available_cases(manifest, tmp_path):
    plan = shards.build_shard_plan(manifest)
    directories = [evidence(manifest, plan, s, tmp_path / s["id"]) for s in plan["shards"][:-1]]
    index = shards.merge_shards(
        manifest, plan, shard_dirs=directories, output_dir=tmp_path / "merged"
    )
    assert index["results"] == {}
    assert index["attempts"][0]["reason"] == "incomplete_shard_set"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda i: i.update(model="MiniMax-M2.7"),
        lambda i: i.update(repetition_index=2),
        lambda i: i["budgets"].update(total_tokens=32_000_000),
        lambda i: i["runtime"].update(skill_delivery_cell="no-skill"),
    ],
)
def test_wrong_trial_identity_or_treatment_cannot_be_merged(manifest, tmp_path, mutation):
    plan = shards.build_shard_plan(manifest)
    directory = evidence(manifest, plan, plan["shards"][0], tmp_path / "case", mutate=mutation)
    with pytest.raises(ValueError, match="identity|budgets|Skill"):
        shards.merge_shards(manifest, plan, shard_dirs=[directory], output_dir=tmp_path / "merged")


def test_duplicate_and_mixed_epoch_shards_are_rejected(manifest, tmp_path):
    plan = shards.build_shard_plan(manifest)
    directory = evidence(manifest, plan, plan["shards"][0], tmp_path / "case")
    with pytest.raises(ValueError, match="duplicate"):
        shards.merge_shards(
            manifest, plan, shard_dirs=[directory, directory], output_dir=tmp_path / "merged"
        )
    other = copy.deepcopy(plan)
    other["commit"] = "old-code"
    write_atomic(
        directory / "shard.json",
        {"plan_sha256": manifest_digest(other), "shard": plan["shards"][0]},
    )
    with pytest.raises(ValueError, match="incompatible"):
        shards.merge_shards(manifest, plan, shard_dirs=[directory], output_dir=tmp_path / "merged")


def test_dependency_cases_cannot_be_silently_split(manifest, monkeypatch):
    suite, samples = load_suite("cleanup_capability")
    samples = [replace(samples[0], artifact_dependencies={"runtime_map_prior": "map-build"})]
    monkeypatch.setattr(shards, "load_suite", lambda _: (suite, samples))
    with pytest.raises(ValueError, match="dependencies"):
        shards.build_shard_plan(manifest)


def test_full_fifteen_case_threshold_and_report_links_survive_merge(
    manifest, monkeypatch, tmp_path
):
    suite, original = load_suite("cleanup_capability")
    samples = [
        replace(original[0], sample_id=f"cleanup.scene{i}", world=f"molmospaces/test/{i}")
        for i in range(5)
    ]
    suite = replace(suite, sample_ids=tuple(s.sample_id for s in samples))
    for target in (
        "roboclaws.evals.showcase_shards.load_suite",
        "roboclaws.evals.suite_loading.load_suite",
        "roboclaws.evals.showcase_acceptance.load_suite",
    ):
        monkeypatch.setattr(target, lambda _: (suite, samples))
    row = manifest["rows"][0]
    row.pop("sample_id")
    row.update(
        sample_ids=list(suite.sample_ids),
        execution_timeout_s=54030,
        cohort_acceptance={
            "min_passed": 12,
            "min_per_world": 1,
            "reserved_worlds": [s.world for s in samples[-2:]],
            "min_reserved_passed": 5,
        },
    )
    plan = shards.build_shard_plan(manifest)
    assert len(plan["shards"]) == 15
    directories = [
        evidence(
            manifest, plan, s, tmp_path / s["id"], status="failed" if i in (0, 3, 6) else "passed"
        )
        for i, s in enumerate(plan["shards"])
    ]
    index = shards.merge_shards(
        manifest, plan, shard_dirs=directories, output_dir=tmp_path / "merged"
    )
    packet = json.loads(Path(index["results"][row["id"]]).read_text())
    verdict = derive_row(row, packet)
    assert verdict["status"] == "passed"
    assert verdict["metrics"]["failed"] == 3
    html = Path(packet["artifacts"]["eval_report"]).read_text()
    assert "outside eval output" not in html
    assert html.count("/report.html") == 15
