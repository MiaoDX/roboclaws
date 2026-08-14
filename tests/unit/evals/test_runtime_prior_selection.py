from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.evals.map_build_reports import map_build_matrix_summary_from_bundles
from roboclaws.evals.runtime_prior_selection import (
    RUNTIME_PRIOR_SELECTION_MANIFEST_SCHEMA,
    load_runtime_prior_selection_manifest,
    runtime_prior_catalog_from_reports,
    select_recommended_runtime_prior,
    write_runtime_prior_selection,
)
from roboclaws.maps.runtime_prior_catalog import (
    ADVISORY_REGRADE,
    BLOCKING_STALE,
    COMPATIBLE,
    RUNTIME_PRIOR_CATALOG_SCHEMA,
    STALE,
    classify_runtime_prior_compatibility,
)


def test_runtime_prior_selector_emits_catalog_entry_for_accepted_candidate(
    tmp_path: Path,
) -> None:
    prior = _runtime_prior(tmp_path, "accepted-prior")
    manifest = _manifest(prior)
    summary = map_build_matrix_summary_from_bundles([_map_build_bundle(tmp_path, prior)])

    report = select_recommended_runtime_prior(manifest=manifest, matrix_summary=summary)
    catalog = runtime_prior_catalog_from_reports([report])

    assert report["schema"] == "runtime_map_prior_selection_report_v1"
    assert report["status"] == "accepted"
    assert report["selected_prior_path"] == str(prior)
    assert report["catalog_key"] == {
        "world": "molmospaces/procthor-objaverse-val/0",
        "backend": "mujoco",
        "source_map_identity": "map-bundle-sha256:abc",
        "scene_identity": "procthor-objaverse-val/0",
    }
    candidate = report["candidates"][0]
    assert candidate["status"] == "accepted"
    gates = {gate["id"]: gate["status"] for gate in candidate["hard_gates"]}
    assert gates["runtime_map_prior_schema_valid"] == "passed"
    assert gates["private_boundary_safe"] == "passed"
    assert gates["downstream_open-ended_no_regression"] == "passed"
    assert gates["downstream_cleanup_no_regression"] == "passed"
    assert catalog["schema"] == RUNTIME_PRIOR_CATALOG_SCHEMA
    assert catalog["entries"][0]["status"] == "accepted"
    assert catalog["entries"][0]["staleness"] == COMPATIBLE
    assert catalog["entries"][0]["path"] == str(prior)


def test_runtime_prior_selector_rejects_private_truth_prior(tmp_path: Path) -> None:
    prior = _runtime_prior(tmp_path, "private-prior", extra={"generated_mess_set": []})
    manifest = _manifest(prior)
    summary = map_build_matrix_summary_from_bundles([_map_build_bundle(tmp_path, prior)])

    report = select_recommended_runtime_prior(manifest=manifest, matrix_summary=summary)

    assert report["status"] == "no_accepted_candidate"
    gates = {gate["id"]: gate["status"] for gate in report["candidates"][0]["hard_gates"]}
    assert gates["private_boundary_safe"] == "failed"
    assert report["catalog_entry"] is None


def test_runtime_prior_selection_writer_emits_report_and_catalog(tmp_path: Path) -> None:
    prior = _runtime_prior(tmp_path, "writer-prior")
    manifest_path = tmp_path / "manifest.json"
    eval_results_path = tmp_path / "eval_results.json"
    output_dir = tmp_path / "selection"
    manifest_path.write_text(json.dumps(_manifest(prior)), encoding="utf-8")
    eval_results_path.write_text(
        json.dumps(_map_build_bundle(tmp_path, prior)),
        encoding="utf-8",
    )

    artifacts = write_runtime_prior_selection(
        manifest_path=manifest_path,
        eval_results_paths=[eval_results_path],
        output_dir=output_dir,
    )

    report = json.loads(Path(artifacts["report"]).read_text(encoding="utf-8"))
    catalog = json.loads(Path(artifacts["catalog"]).read_text(encoding="utf-8"))
    assert report["status"] == "accepted"
    assert report["selected_prior_path"] == str(prior)
    assert catalog["schema"] == RUNTIME_PRIOR_CATALOG_SCHEMA
    assert catalog["entries"][0]["path"] == str(prior)


def test_runtime_prior_selection_manifest_rejects_cleanup_private_catalog_key(
    tmp_path: Path,
) -> None:
    manifest = _manifest(_runtime_prior(tmp_path, "prior"))
    manifest["catalog_key"]["scenario_setup"] = "relocate-cleanup-related-objects"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="private cleanup fields"):
        load_runtime_prior_selection_manifest(manifest_path)


def test_runtime_prior_compatibility_classification(tmp_path: Path) -> None:
    prior = _runtime_prior(tmp_path, "prior")
    base = {
        "world": "world-a",
        "backend": "mujoco",
        "source_map_identity": "map-a",
        "runtime_map_prior_schema": "runtime_map_prior_snapshot_v1",
        "public_map_contract_version": "2026-07-01",
        "grader_version": "grader-a",
    }

    assert (
        classify_runtime_prior_compatibility(
            entry_contract=base,
            current_contract=dict(base),
            prior_path=str(prior),
        )
        == COMPATIBLE
    )
    assert (
        classify_runtime_prior_compatibility(
            entry_contract=base,
            current_contract={**base, "grader_version": "grader-b"},
            prior_path=str(prior),
        )
        == ADVISORY_REGRADE
    )
    assert (
        classify_runtime_prior_compatibility(
            entry_contract=base,
            current_contract={**base, "public_map_contract_version": "2026-08-01"},
            prior_path=str(prior),
        )
        == STALE
    )
    assert (
        classify_runtime_prior_compatibility(
            entry_contract=base,
            current_contract={**base, "source_map_identity": "map-b"},
            prior_path=str(prior),
        )
        == BLOCKING_STALE
    )
    assert (
        classify_runtime_prior_compatibility(
            entry_contract=base,
            current_contract=dict(base),
            prior_path=str(tmp_path / "missing.json"),
        )
        == BLOCKING_STALE
    )


def _runtime_prior(tmp_path: Path, name: str, *, extra: dict[str, object] | None = None) -> Path:
    path = tmp_path / f"{name}.json"
    payload = {
        "schema": "runtime_map_prior_snapshot_v1",
        "runtime_metric_map": {"schema": "runtime_metric_map_v1"},
        "contract": {"private_truth_included": False},
    }
    payload.update(extra or {})
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _manifest(prior: Path) -> dict[str, object]:
    contract = {
        "world": "molmospaces/procthor-objaverse-val/0",
        "backend": "mujoco",
        "source_map_identity": "map-bundle-sha256:abc",
        "runtime_map_prior_schema": "runtime_map_prior_snapshot_v1",
        "public_map_contract_version": "2026-07-01",
        "grader_version": "map-build-grader-v1",
    }
    return {
        "schema": RUNTIME_PRIOR_SELECTION_MANIFEST_SCHEMA,
        "catalog_key": {
            "world": "molmospaces/procthor-objaverse-val/0",
            "backend": "mujoco",
            "source_map_identity": "map-bundle-sha256:abc",
            "scene_identity": "procthor-objaverse-val/0",
        },
        "source_map_contract": contract,
        "current_contract": dict(contract),
        "hard_gate_thresholds": {
            "min_public_semantic_anchors": 10,
            "min_stable_semantic_anchor_categories": 2,
            "min_sim_truth_fixture_category_recall": 1.0,
            "min_sim_truth_fixture_category_precision": 1.0,
            "min_sim_truth_best_view_waypoint_accuracy": 1.0,
        },
        "candidates": [
            {
                "candidate_id": "codex-responses-map-build",
                "profile_key": [
                    "openai-agents-sdk",
                    "codex-responses",
                    "not_applicable",
                    "camera-grounded-labels",
                    "grounding-dino",
                    "mujoco",
                    "7",
                ],
                "runtime_map_prior": str(prior),
                "source_map_identity": "map-bundle-sha256:abc",
                "run_id": "run-map-build-1",
                "producer": {"provider_profile": "codex-responses"},
                "usage": {"total_cost_usd": 0.12},
                "artifact_schema_versions": {
                    "runtime_map_prior_snapshot": "runtime_map_prior_snapshot_v1"
                },
            }
        ],
    }


def _map_build_bundle(output_dir: Path, prior: Path) -> dict[str, object]:
    return {
        "schema": "roboclaws_eval_results_bundle_v1",
        "suite": {"suite_id": "household_world.map_build_consumer"},
        "aggregate": {"pass_at_1": 1.0, "passed": 5, "total": 5},
        "artifacts": {"output_dir": str(output_dir)},
        "results": [
            {
                "identity": _identity("map_build.fixture_focused_seed7"),
                "status": "passed",
                "failure_class": "not_applicable",
                "metrics": {
                    "tool_call_count": 60,
                    "tool_event_counts": {"observe:request": 30},
                    "wall_time_s": 100.0,
                    "model_attempt_summary": {"attempt_count": 61},
                },
                "grader_outputs": {
                    "outcome": {
                        "base_map_anchor_like_count": 14,
                        "public_semantic_anchor_count": 30,
                        "runtime_enrichment_anchor_count": 16,
                        "semantic_enrichment_over_base": True,
                        "generated_exploration_candidate_count": 7,
                        "observed_object_count": 0,
                        "target_candidate_count": 37,
                        "stable_semantic_anchor_category_count": 2,
                        "stable_semantic_anchor_categories": ["bed", "fridge"],
                        "duplicate_fixture_viewpoint_group_count": 0,
                        "rgb_only_object_pose_claim_count": 0,
                        "sim_truth_fixture_category_recall": 1.0,
                        "sim_truth_fixture_category_precision": 1.0,
                        "sim_truth_best_view_waypoint_accuracy": 1.0,
                        "private_truth_absent": True,
                        "source_map_not_mutated": True,
                    }
                },
                "artifacts": {"runtime_map_prior_snapshot": str(prior)},
            },
            _consumer_result("open_ended.stable_anchor_no_prior_seed7", "no_prior", 7, 18),
            _consumer_result(
                "open_ended.stable_anchor_fixture_focused_prior_seed7",
                "fixture_focused_prior",
                5,
                13,
            ),
            _consumer_result("cleanup.consumer_no_prior_seed7", "no_prior", 9, 30),
            _consumer_result(
                "cleanup.consumer_fixture_focused_prior_seed7", "fixture_focused_prior", 6, 26
            ),
        ],
    }


def _identity(sample_id: str) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "trial_id": f"{sample_id}-0000",
        "agent_engine": "openai-agents-sdk",
        "provider_profile": "codex-responses",
        "model": "not_applicable",
        "evidence_lane": "camera-grounded-labels",
        "camera_labeler": "grounding-dino",
        "backend": "mujoco",
        "seed": 7,
    }


def _consumer_result(
    sample_id: str,
    variant: str,
    observe: int,
    tool_call_count: int,
) -> dict[str, object]:
    return {
        "identity": {
            **_identity(sample_id),
            "sample_metadata": {"variant_id": variant},
        },
        "status": "passed",
        "failure_class": "not_applicable",
        "metrics": {
            "comparison_tool_counts": {
                "observe": observe,
                "navigate_to_waypoint": 2,
                "navigate_to_relative_pose": 0,
                "adjust_camera": 1,
            },
            "tool_call_count": tool_call_count,
            "tool_event_counts": {"observe:request": observe},
            "wall_time_s": tool_call_count + 0.5,
            "prior_use_verdict": (
                "stable_anchor_used" if variant == "fixture_focused_prior" else "prior_ignored"
            ),
        },
        "grader_outputs": {},
        "artifacts": {},
    }
