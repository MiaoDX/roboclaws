"""Prepared cohorts preserve pairing, reserved coverage, treatment and bounds."""

import json
from pathlib import Path

import pytest

from roboclaws.evals import showcase_shards
from roboclaws.evals.showcase import validate_manifest
from roboclaws.evals.suite_loading import load_suite, validate_suite_runtime_map_prior


@pytest.mark.parametrize("kind,cleanup_cases", [("full", 15), ("development", 9)])
def test_external_cohorts_are_paired_and_fully_budgeted(monkeypatch, kind, cleanup_cases):
    manifest = json.loads(Path(f"config/showcase-{kind}-manifest.json").read_text())
    validate_manifest(manifest)
    paired = {}
    for row in manifest["rows"]:
        key = (row["suite"], tuple(row["sample_ids"]))
        paired.setdefault(key, []).append(row)
        assert row["comparison_scope"] == "common"
        assert row["evidence_lane"] == "world-public-labels"
    for rows in paired.values():
        assert {r["provider_profile"] for r in rows} == {"minimax-responses", "mimo-tp-openai-chat"}
        treatments = [
            {k: v for k, v in r.items() if k not in {"id", "model", "provider_profile"}}
            for r in rows
        ]
        assert treatments[0] == treatments[1]
    monkeypatch.setattr(showcase_shards, "repository_revision", lambda: "test-code")
    plan = showcase_shards.build_shard_plan(manifest)
    assert plan["envelope"]["cases"] == 2 * (cleanup_cases + 4)
    assert plan["envelope"]["provider_tokens"] == 2 * cleanup_cases * 16_000_000 + 104_000_000
    assert plan["envelope"]["decision_calls"] == 2 * cleanup_cases * 100 + 632
    assert plan["max_parallel"] == 2 and plan["trial_retries"] == 0
    workflow = Path(".github/workflows/showcase.yml").read_text()
    assert f"showcase-{kind}-manifest.json" not in workflow
    cleanup_rows = [r for r in manifest["rows"] if "cleanup_convergence" in r["suite"]]
    for row in cleanup_rows:
        if kind == "full":
            assert row["cohort_acceptance"] == {
                "min_passed": 12,
                "min_per_world": 1,
                "min_reserved_passed": 5,
                "reserved_worlds": [
                    "molmospaces/procthor-10k-val/14",
                    "molmospaces/procthor-10k-val/15",
                ],
            }
        else:
            assert "cohort_acceptance" not in row
            assert not any(f"scene{s}." in sid for sid in row["sample_ids"] for s in [14, 15])


def test_visual_and_world_cohorts_keep_identical_fixtures_and_no_prior(tmp_path):
    world_suite, world = load_suite("cleanup_convergence_world_v2")
    visual_suite, visual = load_suite("cleanup_convergence_dino_v2")
    for suite in [world_suite, visual_suite]:
        with pytest.raises(ValueError, match="forbids runtime_map_prior"):
            validate_suite_runtime_map_prior(suite, tmp_path / "prior.json")
    for public, camera in zip(world, visual, strict=True):
        assert public.world == camera.world
        assert public.seed == camera.seed == 7
        assert public.trial_count == camera.trial_count == 3
        assert public.private_goal_reference == camera.private_goal_reference
        assert public.grader_config == camera.grader_config
        assert public.grader_config["min_complete_cleanup_chains"] == 4
        assert camera.evidence_lane == "camera-grounded-labels"
        assert camera.camera_labeler == "grounding-dino"
    assert {s.world.rsplit("/", 1)[-1] for s in visual} == {"0", "10", "12", "14", "15"}
    ledger = json.loads(
        Path("evals/household_world/manifests/simulation_convergence_visual_v2.json").read_text()
    )
    assert {(c["sample_id"], c["trial_index"]) for c in ledger["cases"]} == {
        (s.sample_id, i) for s in visual for i in range(s.trial_count)
    }
