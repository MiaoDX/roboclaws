from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTOR_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "select_eval_harness.py"

LIVE_AGENT_ROW_IDS = {
    "map-build-consumer-openai-agents-sdk-codex-router-responses",
    "map-build-consumer-openai-agents-sdk-mimo-mify-responses",
    "map-build-consumer-openai-agents-sdk-kimi-openai-chat",
    "map-build-consumer-openai-agents-sdk-minimax-responses",
    "openai-agents-sdk-open-task-live-eval",
    "openai-agents-sdk-session-live-eval",
    "openai-agents-sdk-cleanup-live-eval",
    "openai-agents-sdk-cleanup-camera-raw-fpv-live-product",
    "openai-agents-sdk-codex-router-responses-availability",
}
ALTERNATE_PROVIDER_MATRIX_ROW_IDS = {
    "map-build-consumer-openai-agents-sdk-mimo-mify-responses",
    "map-build-consumer-openai-agents-sdk-kimi-openai-chat",
    "map-build-consumer-openai-agents-sdk-minimax-responses",
}


def _load_selector():
    spec = importlib.util.spec_from_file_location("eval_harness_baseline_profiles", SELECTOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = _load_selector()


def _selected_rows(manifest: dict) -> dict[str, dict]:
    return {row["row_id"]: row for row in manifest["rows"] if row["selected"]}


def test_baseline_core_profile_selects_non_live_baseline_rows(tmp_path: Path) -> None:
    full = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
        output_dir=tmp_path / "full",
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


def test_baseline_live_default_profile_excludes_alternate_provider_sweep(
    tmp_path: Path,
) -> None:
    full = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
        output_dir=tmp_path / "full",
    )
    manifest = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-live-default",
        output_dir=tmp_path / "default",
    )

    rows = _selected_rows(manifest)
    assert set(rows) == set(_selected_rows(full)) - ALTERNATE_PROVIDER_MATRIX_ROW_IDS
    assert manifest["summary"]["selected_row_count"] == 24
    assert manifest["summary"]["live_agent_eval_row_count"] == 6
    assert manifest["summary"]["budget_skipped_count"] == 0
    assert all(
        row["axes"].get("provider_profile") in {None, "codex-router-responses"}
        for row in rows.values()
    )
    assert {signal["id"] for signal in manifest["signals"]} == {"baseline_live_default_profile"}
