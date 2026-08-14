from __future__ import annotations

from pathlib import Path

from roboclaws.evals.harness import selector

LIVE_AGENT_ROW_IDS = {
    "map-build-consumer-openai-agents-sdk-codex-responses",
    "map-build-consumer-openai-agents-sdk-mimo-responses",
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
        row["axes"].get("provider_profile") in {None, "kimi-openai-chat"} for row in rows.values()
    )
    assert {signal["id"] for signal in manifest["signals"]} == {"baseline_live_default_profile"}


def test_baseline_refresh_selects_fixed_prior_matrix_only_with_explicit_prior(
    tmp_path: Path,
) -> None:
    without_prior = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
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

    assert not (set(_selected_rows(without_prior)) & FIXED_PRIOR_PROVIDER_ROW_IDS)
    assert set(_selected_rows(with_prior)) & FIXED_PRIOR_PROVIDER_ROW_IDS == (
        FIXED_PRIOR_PROVIDER_ROW_IDS
    )
