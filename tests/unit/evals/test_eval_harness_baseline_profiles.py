from __future__ import annotations

from pathlib import Path

from roboclaws.evals.harness import runner, selector
from roboclaws.evals.harness.prior import resolve_baseline_prior

LIVE_AGENT_ROW_IDS = {
    "map-build-consumer-openai-agents-sdk-codex-responses",
    "map-build-consumer-openai-agents-sdk-mimo-responses",
    "map-build-consumer-openai-agents-sdk-mimo-tp-openai-chat",
    "map-build-consumer-openai-agents-sdk-kimi-openai-chat",
    "map-build-consumer-openai-agents-sdk-minimax-responses",
    "openai-agents-sdk-open-task-live-eval",
    "openai-agents-sdk-session-live-eval",
    "openai-agents-sdk-cleanup-live-eval",
    "openai-agents-sdk-cleanup-no-skill-eval",
    "openai-agents-sdk-cleanup-dynamic-full-eval",
    "openai-agents-sdk-cleanup-dynamic-routed-eval",
    "openai-agents-sdk-cleanup-sandbox-skills-eval",
}
ALTERNATE_PROVIDER_MATRIX_ROW_IDS = {
    "map-build-consumer-openai-agents-sdk-codex-responses",
    "map-build-consumer-openai-agents-sdk-mimo-responses",
    "map-build-consumer-openai-agents-sdk-minimax-responses",
}
FIXED_PRIOR_PROVIDER_ROW_IDS = ALTERNATE_PROVIDER_MATRIX_ROW_IDS | {
    "map-build-consumer-openai-agents-sdk-kimi-openai-chat"
}
EXPERIMENTAL_SKILL_DELIVERY_ROW_IDS = {
    "openai-agents-sdk-cleanup-no-skill-eval",
    "openai-agents-sdk-cleanup-dynamic-full-eval",
    "openai-agents-sdk-cleanup-dynamic-routed-eval",
    "openai-agents-sdk-cleanup-sandbox-skills-eval",
}


def test_baseline_prior_resolves_relative_catalog_entry(tmp_path: Path) -> None:
    prior = tmp_path / "by-sha256" / "digest" / "runtime_map_prior_snapshot.json"
    prior.parent.mkdir(parents=True)
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    catalog = tmp_path / "runtime_map_prior_catalog.json"
    catalog.write_text(
        "{\n"
        '  "schema": "runtime_map_prior_catalog_v1",\n'
        '  "entries": [{\n'
        '    "id": "world::mujoco",\n'
        '    "world_id": "molmospaces/procthor-10k-val/0",\n'
        '    "backend_id": "mujoco",\n'
        '    "path": "by-sha256/digest/runtime_map_prior_snapshot.json",\n'
        '    "status": "accepted",\n'
        '    "source": "runtime_prior_selector",\n'
        '    "staleness": "compatible"\n'
        "  }]\n"
        "}\n",
        encoding="utf-8",
    )

    assert resolve_baseline_prior(catalog_path=catalog) == str(prior.resolve())


def _selected_rows(manifest: dict) -> dict[str, dict]:
    return {row["row_id"]: row for row in manifest["rows"] if row["selected"]}


def test_baseline_core_profile_selects_non_live_baseline_rows(tmp_path: Path) -> None:
    prior = tmp_path / "canonical-prior.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    full = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
        output_dir=tmp_path / "full",
        runtime_map_prior=str(prior),
    )
    manifest = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-core",
        output_dir=tmp_path / "core",
    )

    rows = _selected_rows(manifest)
    assert set(rows) == set(_selected_rows(full)) - LIVE_AGENT_ROW_IDS
    assert manifest["summary"]["selected_row_count"] == 18
    assert manifest["summary"]["live_agent_eval_row_count"] == 0
    assert manifest["summary"]["budget_skipped_count"] == 0
    assert {signal["id"] for signal in manifest["signals"]} == {"baseline_core_profile"}
    assert (
        "tests/contract/molmo_cleanup/test_household_mcp_server_misc.py::"
        "test_agent_sdk_camera_grounded_composite_flag_cannot_expand_entitlement"
        in rows["agent-view-contract-tests"]["command"]
    )


def test_baseline_live_default_profile_excludes_fixed_prior_provider_sweep(
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-live-default",
        output_dir=tmp_path / "default",
    )

    rows = _selected_rows(manifest)
    assert not (set(rows) & FIXED_PRIOR_PROVIDER_ROW_IDS)
    assert manifest["summary"]["selected_row_count"] == 21
    assert manifest["summary"]["live_agent_eval_row_count"] == 3
    assert manifest["summary"]["budget_skipped_count"] == 0
    assert all(
        row["axes"].get("provider_profile") in {None, "minimax-responses"} for row in rows.values()
    )
    assert {signal["id"] for signal in manifest["signals"]} == {"baseline_live_default_profile"}


def test_baseline_ci_is_deterministic_subset_without_provider_rows(tmp_path: Path) -> None:
    core = selector.build_eval_harness(profile="baseline-core", output_dir=tmp_path / "core")
    ci = selector.build_eval_harness(profile="baseline-ci", output_dir=tmp_path / "ci")
    core_ids = set(_selected_rows(core))
    ci_rows = _selected_rows(ci)
    assert set(ci_rows) <= core_ids
    assert ci_rows
    assert all(row["expense"] == "deterministic" for row in ci_rows.values())
    assert all(not row["axes"].get("provider_profile") for row in ci_rows.values())


def test_baseline_refresh_keeps_fixed_prior_matrix_visible_without_prior(
    tmp_path: Path,
) -> None:
    without_prior = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
        runtime_map_prior="",
        output_dir=tmp_path / "without-prior",
    )
    prior = tmp_path / "canonical-prior.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    with_prior = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
        runtime_map_prior=str(prior),
        output_dir=tmp_path / "with-prior",
    )

    without_rows = _selected_rows(without_prior)
    assert set(without_rows) & FIXED_PRIOR_PROVIDER_ROW_IDS == FIXED_PRIOR_PROVIDER_ROW_IDS
    assert without_prior["runtime_map_prior"].endswith("runtime_map_prior_snapshot.json")
    assert all(
        without_rows[row_id]["prior_policy"] == "required"
        for row_id in FIXED_PRIOR_PROVIDER_ROW_IDS
    )
    assert set(_selected_rows(with_prior)) & FIXED_PRIOR_PROVIDER_ROW_IDS == (
        FIXED_PRIOR_PROVIDER_ROW_IDS
    )


def test_fixed_prior_substitution_is_limited_to_fixed_prior_profiles(tmp_path: Path) -> None:
    """Only fixed-prior profiles replace a row's own same-run prior reference.

    The other baseline profiles keep the same-run chain: their consumer resolves
    the artifact its own map-build row just produced, so a live-default gate
    cannot pass by consuming an unrelated catalog prior.
    """
    row_dir = tmp_path / "map-build"
    artifact = row_dir / "run" / "direct-map-build-world-public" / "runtime_metric_map.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    row_argument = "runtime_map_prior=${direct-map-build-world-public:runtime_metric_map.json}"
    catalog_prior = "assets/eval-priors/by-sha256/digest/runtime_map_prior_snapshot.json"

    def resolve(profile: str) -> str:
        manifest = {
            "profile": profile,
            "runtime_map_prior": catalog_prior,
            "rows": [{"row_id": "direct-map-build-world-public", "row_dir": str(row_dir)}],
        }
        return runner._resolve_row_argument(row_argument, manifest)

    assert resolve("baseline-refresh") == f"runtime_map_prior={catalog_prior}"
    assert resolve("baseline-live-default") == f"runtime_map_prior={artifact}"
