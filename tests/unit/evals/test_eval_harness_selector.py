from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTOR_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "select_eval_harness.py"
ROWS_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_rows.py"
RUNNER_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "run_eval_harness.py"

EXPECTED_ROW_IDS = {
    "route-trace-contract-tests",
    "eval-unit-tests",
    "cleanup-contract-tests",
    "agent-view-contract-tests",
    "household-direct-world-public-product",
    "open-ended-household-contract-tests",
    "smoke-regression-eval-suite",
    "map-build-consumer-eval-suite",
    "map-build-consumer-openai-agents-sdk-codex-router-responses",
    "map-build-consumer-openai-agents-sdk-mimo-mify-responses",
    "map-build-consumer-openai-agents-sdk-kimi-openai-chat",
    "map-build-consumer-openai-agents-sdk-minimax-responses",
    "open-ended-goals-eval-suite",
    "scene-sampler-stress-eval-suite",
    "cleanup-capability-eval-suite",
    "long-horizon-tasks-eval-suite",
    "openai-agents-sdk-open-task-live-eval",
    "openai-agents-sdk-session-live-eval",
    "openai-agents-sdk-cleanup-live-eval",
    "openai-agents-sdk-cleanup-camera-raw-fpv-live-product",
    "openai-agents-sdk-codex-router-responses-availability",
    "planner-proof-dry-run-product",
    "direct-camera-grounded-grounding-dino",
    "direct-map-build-grounding-dino",
    "direct-camera-raw-fpv",
    "direct-map-build-world-public",
    "direct-cleanup-runtime-prior-consumer",
}


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = _load_module("eval_harness_selector_test", SELECTOR_PATH)
rows_module = _load_module("eval_harness_rows_test", ROWS_PATH)
runner = _load_module("eval_harness_runner_test", RUNNER_PATH)


def _selected_rows(manifest: dict) -> dict[str, dict]:
    return {row["row_id"]: row for row in manifest["rows"] if row["selected"]}


def _assert_selected_rows_include(
    rows: dict[str, dict],
    *,
    case_name: str,
    present_rows: tuple[str, ...],
    absent_rows: tuple[str, ...] = (),
) -> None:
    for row_id in present_rows:
        assert row_id in rows, f"{case_name}: missing selected row {row_id}"
    for row_id in absent_rows:
        assert row_id not in rows, f"{case_name}: unexpectedly selected {row_id}"


def test_row_catalog_loads_current_eval_harness_rows(tmp_path: Path) -> None:
    rows = rows_module.candidate_rows(output_dir=tmp_path, explicit_axes={})

    assert {row["row_id"] for row in rows} == EXPECTED_ROW_IDS
    assert all(row["schema"] == "roboclaws_eval_harness_row_v1" for row in rows)
    assert rows_module.CATALOG_PATH.name == "rows.json"


def test_baseline_refresh_profile_selects_full_baseline_without_budget_skips(
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="smoke",
        profile="baseline-refresh",
        output_dir=tmp_path,
    )

    rows = _selected_rows(manifest)
    assert set(rows) == EXPECTED_ROW_IDS
    assert manifest["profile"] == "baseline-refresh"
    assert manifest["summary"]["selected_row_count"] == len(EXPECTED_ROW_IDS)
    assert manifest["summary"]["budget_skipped_count"] == 0
    assert manifest["summary"]["eval_suite_row_count"] == 6
    assert manifest["summary"]["live_agent_eval_row_count"] == 9
    assert rows["openai-agents-sdk-open-task-live-eval"]["status"] == "not_run"
    assert rows["openai-agents-sdk-cleanup-live-eval"]["status"] == "not_run"
    assert "live_stall_timeout_s=180" in rows["openai-agents-sdk-cleanup-live-eval"]["command"]
    provider_rows = [
        row
        for row_id, row in rows.items()
        if row_id.startswith("map-build-consumer-openai-agents-sdk-")
    ]
    assert len(provider_rows) == 4
    assert all("live_timeout_s=1500" in row["command"] for row in provider_rows)
    assert all("live_stall_timeout_s=180" in row["command"] for row in provider_rows)
    assert rows["direct-camera-grounded-grounding-dino"]["status"] == "not_run"
    assert rows["direct-map-build-grounding-dino"]["status"] == "not_run"
    assert rows["long-horizon-tasks-eval-suite"]["status"] == "not_run"
    assert rows["long-horizon-tasks-eval-suite"]["expense"] == "local-sim"
    assert "suite=long_horizon_tasks" in rows["long-horizon-tasks-eval-suite"]["command"]
    raw_fpv_row = rows["openai-agents-sdk-cleanup-camera-raw-fpv-live-product"]
    assert raw_fpv_row["axes"]["provider_profile"] == "codex-router-responses"
    assert "provider_profile=codex-router-responses" in raw_fpv_row["command"]
    assert rows["openai-agents-sdk-codex-router-responses-availability"]["requirement"] == (
        "optional"
    )
    assert {signal["id"] for signal in manifest["signals"]} == {"baseline_refresh_profile"}


def test_changed_file_signals_select_expected_eval_harness_rows(tmp_path: Path) -> None:
    cases = (
        {
            "name": "eval_harness",
            "changed_files": ["roboclaws/evals/runner.py"],
            "present_rows": ("eval-unit-tests", "smoke-regression-eval-suite"),
        },
        {
            "name": "cleanup_skill",
            "changed_files": ["skills/household-world/SKILL.md"],
            "present_rows": (
                "cleanup-capability-eval-suite",
                "openai-agents-sdk-cleanup-live-eval",
            ),
        },
        {
            "name": "agent_sdk",
            "changed_files": ["roboclaws/agents/drivers/openai_agents_live.py"],
            "present_rows": (
                "openai-agents-sdk-open-task-live-eval",
                "openai-agents-sdk-session-live-eval",
            ),
            "absent_rows": ("openai-agents-sdk-codex-router-responses-availability",),
        },
        {
            "name": "visual_grounding",
            "changed_files": ["roboclaws/household/visual_grounding.py"],
            "present_rows": ("direct-camera-grounded-grounding-dino",),
        },
        {
            "name": "raw_fpv",
            "changed_files": ["roboclaws/household/raw_fpv_guidance.py"],
            "present_rows": (
                "direct-camera-raw-fpv",
                "openai-agents-sdk-cleanup-camera-raw-fpv-live-product",
            ),
        },
        {
            "name": "agent_view_module",
            "changed_files": ["roboclaws/household/agent_view.py"],
            "present_rows": (
                "agent-view-contract-tests",
                "cleanup-contract-tests",
                "household-direct-world-public-product",
            ),
        },
        {
            "name": "agent_view_related_paths",
            "changed_files": [
                "roboclaws/household/realworld_agent_view_contract.py",
                "roboclaws/household/realworld_contract_payloads.py",
                "roboclaws/household/agibot_cleanup_contract.py",
            ],
            "present_rows": (
                "agent-view-contract-tests",
                "cleanup-contract-tests",
                "household-direct-world-public-product",
            ),
        },
        {
            "name": "map_build",
            "changed_files": ["roboclaws/maps/runtime_prior_snapshot.py"],
            "present_rows": (
                "direct-map-build-world-public",
                "direct-cleanup-runtime-prior-consumer",
                "map-build-consumer-eval-suite",
                "map-build-consumer-openai-agents-sdk-codex-router-responses",
                "map-build-consumer-openai-agents-sdk-mimo-mify-responses",
                "map-build-consumer-openai-agents-sdk-kimi-openai-chat",
                "map-build-consumer-openai-agents-sdk-minimax-responses",
            ),
        },
        {
            "name": "scene_sampler",
            "changed_files": ["roboclaws/launch/scene_sampler.py"],
            "present_rows": ("scene-sampler-stress-eval-suite",),
        },
        {
            "name": "long_horizon",
            "changed_files": ["roboclaws/evals/long_horizon.py"],
            "present_rows": ("long-horizon-tasks-eval-suite",),
        },
        {
            "name": "open_ended_file",
            "changed_files": ["docs/plans/2026-06-11-open-ended-proof-status.md"],
            "present_rows": (
                "open-ended-household-contract-tests",
                "open-ended-goals-eval-suite",
                "openai-agents-sdk-open-task-live-eval",
                "openai-agents-sdk-session-live-eval",
            ),
            "absent_rows": (
                "map-build-consumer-eval-suite",
                "cleanup-capability-eval-suite",
            ),
        },
    )

    for case in cases:
        manifest = selector.build_eval_harness(
            budget="focused",
            changed_files=case["changed_files"],
            output_dir=tmp_path / case["name"],
        )
        assert manifest["schema"] == "roboclaws_eval_harness_manifest_v1"
        _assert_selected_rows_include(
            _selected_rows(manifest),
            case_name=case["name"],
            present_rows=case["present_rows"],
            absent_rows=case.get("absent_rows", ()),
        )


def test_explicit_changed_file_does_not_pull_unrelated_worktree_diff(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(selector, "_changed_files_from_worktree", lambda: ["just/agent.just"])

    manifest = selector.build_eval_harness(
        budget="focused",
        changed_files=["roboclaws/household/visual_grounding.py"],
        output_dir=tmp_path,
    )

    rows = _selected_rows(manifest)
    assert "direct-camera-grounded-grounding-dino" in rows
    assert "route-trace-contract-tests" not in rows


def test_explicit_since_diff_failure_fails_aloud(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["git", "diff"],
            returncode=128,
            stdout="",
            stderr="fatal: bad revision 'missing-base'",
        )

    monkeypatch.setattr(selector.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="git diff --name-only 'missing-base' failed"):
        selector.build_eval_harness(
            budget="focused",
            since="missing-base",
            output_dir=tmp_path,
        )


def test_implicit_worktree_diff_failure_stays_best_effort(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["git", "diff"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

    monkeypatch.setattr(selector.subprocess, "run", fake_run)

    manifest = selector.build_eval_harness(budget="focused", output_dir=tmp_path)

    assert manifest["changed_files"] == []
    assert manifest["summary"]["selected_row_count"] == 0


def test_explicit_intent_axes_select_expected_eval_harness_rows(tmp_path: Path) -> None:
    cases = (
        {
            "name": "open_ended",
            "kwargs": {"intent": ["open-ended"]},
            "present_rows": (
                "open-ended-household-contract-tests",
                "open-ended-goals-eval-suite",
                "openai-agents-sdk-open-task-live-eval",
                "openai-agents-sdk-session-live-eval",
            ),
            "absent_rows": ("openai-agents-sdk-codex-router-responses-availability",),
        },
        {
            "name": "planner_proof",
            "kwargs": {"intent": ["planner-proof"]},
            "present_rows": ("planner-proof-dry-run-product",),
            "absent_rows": ("open-ended-goals-eval-suite",),
        },
    )

    for case in cases:
        manifest = selector.build_eval_harness(
            budget="focused",
            output_dir=tmp_path / case["name"],
            **case["kwargs"],
        )

        _assert_selected_rows_include(
            _selected_rows(manifest),
            case_name=case["name"],
            present_rows=case["present_rows"],
            absent_rows=case.get("absent_rows", ()),
        )


def test_runtime_prior_placeholder_resolves_to_map_build_artifact(tmp_path: Path) -> None:
    manifest = selector.build_eval_harness(
        budget="focused",
        changed_files=["roboclaws/maps/runtime_prior_snapshot.py"],
        output_dir=tmp_path,
    )
    rows = _selected_rows(manifest)
    map_row = rows["direct-map-build-world-public"]
    prior = Path(map_row["row_dir"]) / "run" / "seed-7" / "runtime_metric_map.json"
    prior.parent.mkdir(parents=True)
    prior.write_text('{"schema":"runtime_metric_map_v1"}\n', encoding="utf-8")

    command = runner._resolve_row_command(rows["direct-cleanup-runtime-prior-consumer"], manifest)

    assert f"runtime_map_prior={prior}" in command


def test_runtime_prior_blocker_uses_current_map_build_row(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}")
    repo_root = tmp_path / "repo"
    (repo_root / ".venv" / "bin").mkdir(parents=True)
    (repo_root / ".venv" / "bin" / "python").touch()
    monkeypatch.setattr(runner, "REPO_ROOT", repo_root)
    manifest = selector.build_eval_harness(
        budget="focused",
        changed_files=["roboclaws/maps/runtime_prior_snapshot.py"],
        output_dir=tmp_path,
    )
    rows = _selected_rows(manifest)
    map_row = rows["direct-map-build-world-public"]
    prior = Path(map_row["row_dir"]) / "run" / "seed-7" / "runtime_metric_map.json"
    prior.parent.mkdir(parents=True)
    prior.write_text('{"schema":"runtime_metric_map_v1"}\n', encoding="utf-8")
    map_row["status"] = "ran"
    map_row["outcome"] = "passed"

    blockers = runner._row_blockers(rows["direct-cleanup-runtime-prior-consumer"], manifest)

    assert blockers == []


def test_smoke_budget_records_relevant_expensive_rows_as_user_budget_skipped(
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="smoke",
        changed_files=["skills/household-world/SKILL.md"],
        output_dir=tmp_path,
    )

    rows = _selected_rows(manifest)
    assert rows["openai-agents-sdk-cleanup-live-eval"]["status"] == "skipped_by_budget"
    assert rows["cleanup-contract-tests"]["status"] == "not_run"


def test_explicit_axes_select_first_class_engine_and_provider_profile(
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="focused",
        agent_engine=["openai-agents-sdk"],
        provider_profile=["mimo-mify-responses"],
        evidence_lane=["camera-grounded-labels"],
        camera_labeler=["grounding-dino"],
        output_dir=tmp_path,
    )

    rows = _selected_rows(manifest)
    assert rows["openai-agents-sdk-open-task-live-eval"]["axes"]["provider_profile"] == (
        "mimo-mify-responses"
    )
    assert rows["openai-agents-sdk-session-live-eval"]["axes"]["provider_profile"] == (
        "mimo-mify-responses"
    )
    assert rows["direct-camera-grounded-grounding-dino"]["axes"]["camera_labeler"] == (
        "grounding-dino"
    )


def test_map_build_consumer_plan_selects_four_profile_model_matrix(
    tmp_path: Path,
) -> None:
    prior = tmp_path / "canonical-prior.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    manifest = selector.build_eval_harness(
        budget="focused",
        plan=REPO_ROOT / "docs/plans/2026-06-24-map-build-panorama-consumer-experiments.md",
        output_dir=tmp_path / "harness",
        runtime_map_prior=str(prior),
    )

    rows = _selected_rows(manifest)
    matrix_rows = {
        row_id: row
        for row_id, row in rows.items()
        if row_id.startswith("map-build-consumer-openai-agents-sdk-")
    }
    assert set(matrix_rows) == {
        "map-build-consumer-openai-agents-sdk-codex-router-responses",
        "map-build-consumer-openai-agents-sdk-mimo-mify-responses",
        "map-build-consumer-openai-agents-sdk-kimi-openai-chat",
        "map-build-consumer-openai-agents-sdk-minimax-responses",
    }
    assert {row["axes"]["provider_profile"] for row in matrix_rows.values()} == {
        "codex-router-responses",
        "mimo-mify-responses",
        "kimi-openai-chat",
        "minimax-responses",
    }
    for row in matrix_rows.values():
        assert "suite=map_consumer_fixed_prior" in row["command"]
        assert f"runtime_map_prior={prior}" in row["command"]
        assert row["axes"]["suite"] == "map_consumer_fixed_prior"
        assert "agent_engine=openai-agents-sdk" in row["command"]
        assert "live_timeout_s=1500" in row["command"]
        assert "live_execution=run" in row["command"]
        assert row["axes"]["provider_cell_count"] == "4"
        assert row["axes"]["default_local_concurrency_width"] == "1"
        assert row["axes"]["concurrency_policy"] == (
            "serial_by_default_for_single_molmospaces_visual_backend_slot"
        )


def test_explicit_provider_axis_selects_matching_map_build_consumer_matrix_rows(
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="focused",
        provider_profile=["kimi-openai-chat", "minimax-responses"],
        output_dir=tmp_path,
    )

    rows = _selected_rows(manifest)
    assert "map-build-consumer-openai-agents-sdk-kimi-openai-chat" in rows
    assert "map-build-consumer-openai-agents-sdk-minimax-responses" in rows
    assert "map-build-consumer-openai-agents-sdk-mimo-mify-responses" not in rows


def test_explicit_codex_env_selects_agent_sdk_availability_evidence(
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="focused",
        agent_engine=["openai-agents-sdk"],
        provider_profile=["codex-router-responses"],
        intent=["open-ended"],
        output_dir=tmp_path,
    )

    rows = _selected_rows(manifest)
    behavior_row = rows["openai-agents-sdk-open-task-live-eval"]
    session_row = rows["openai-agents-sdk-session-live-eval"]
    availability_row = rows["openai-agents-sdk-codex-router-responses-availability"]
    assert behavior_row["axes"]["provider_profile"] == "codex-router-responses"
    assert session_row["axes"]["provider_profile"] == "codex-router-responses"
    assert session_row["requirement"] == "required"
    assert behavior_row["requirement"] == "required"
    assert availability_row["axes"]["provider_profile"] == "codex-router-responses"
    assert availability_row["requirement"] == "optional"
    assert manifest["summary"]["optional_row_count"] == 1


def test_execute_marks_live_row_blocked_when_provider_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_BASE_URL", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("XM_LLM_API_KEY", raising=False)
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["skills/household-world/SKILL.md"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    rows = _selected_rows(manifest)
    assert rows["openai-agents-sdk-cleanup-live-eval"]["status"] == "blocked"
    assert (
        rows["openai-agents-sdk-cleanup-live-eval"]["blocker_category"]
        == "model_or_provider_unavailable"
    )


def test_provider_blocker_rejects_unknown_profile_even_when_codex_env_exists(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("CODEX_API_KEY", "key")

    blocker = runner._provider_requirement_blocker(
        {"agent_engine": "openai-agents-sdk", "provider_profile": "not-a-provider-route"}
    )

    assert blocker is not None
    assert blocker["category"] == "model_or_provider_unavailable"
    assert "provider_profile 'not-a-provider-route' is unknown" in blocker["detail"]
    assert "agent_engine 'openai-agents-sdk'" in blocker["detail"]


def test_execute_does_not_default_provider_timing_proxy_for_sdk_rows(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[dict[str, str]] = []
    monkeypatch.delenv("ROBOCLAWS_PROVIDER_TIMING_PROXY", raising=False)
    monkeypatch.setattr(runner, "_row_blockers", lambda row, manifest: [])

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **kwargs):
            if "agent_engine=openai-agents-sdk" in command:
                env = kwargs.get("env")
                assert isinstance(env, dict)
                captured.append(env)

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(runner.local_execution.subprocess, "Popen", FakeProcess)
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["skills/household-world/SKILL.md"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    assert captured
    assert "ROBOCLAWS_PROVIDER_TIMING_PROXY" not in captured[0]
    rows = _selected_rows(manifest)
    assert "defaulted_provider_timing_proxy" not in rows["openai-agents-sdk-cleanup-live-eval"]


def test_execute_preserves_provider_timing_proxy_escape_hatch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[dict[str, str]] = []
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_TIMING_PROXY", "0")
    monkeypatch.setattr(runner, "_row_blockers", lambda row, manifest: [])

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **kwargs):
            if "agent_engine=openai-agents-sdk" in command:
                env = kwargs.get("env")
                assert isinstance(env, dict)
                captured.append(env)

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(runner.local_execution.subprocess, "Popen", FakeProcess)
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["skills/household-world/SKILL.md"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    assert captured
    assert captured[0]["ROBOCLAWS_PROVIDER_TIMING_PROXY"] == "0"
    rows = _selected_rows(manifest)
    assert "defaulted_provider_timing_proxy" not in rows["openai-agents-sdk-cleanup-live-eval"]


def test_sdk_live_product_row_records_foreground_command_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="focused",
        changed_files=["roboclaws/household/raw_fpv_guidance.py"],
        output_dir=tmp_path,
    )
    row = _selected_rows(manifest)["openai-agents-sdk-cleanup-camera-raw-fpv-live-product"]

    class FakeProcess:
        returncode = 0

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "sdk foreground stdout", ""

    monkeypatch.setattr(runner.local_execution.subprocess, "Popen", FakeProcess)

    runner._run_row(row, manifest)

    assert row["status"] == "ran"
    assert row["outcome"] == "passed"
    assert "detached_live_run_dir" not in row
    assert any(path.endswith("stdout.log") for path in row["output_artifacts"])
    assert any(path.endswith("stderr.log") for path in row["output_artifacts"])


def test_successful_row_rerun_clears_previous_blocker_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = selector.build_eval_harness(
        budget="focused",
        changed_files=["roboclaws/household/raw_fpv_guidance.py"],
        output_dir=tmp_path,
    )
    row = _selected_rows(manifest)["openai-agents-sdk-cleanup-camera-raw-fpv-live-product"]
    row.update(
        {
            "status": "blocked",
            "outcome": "blocked",
            "blocker_category": "model_or_provider_unavailable",
            "blockers": [{"category": "model_or_provider_unavailable", "detail": "stale"}],
            "failure_class": "provider_transient_failure",
            "failure_detail": "stale",
        }
    )

    class FakeProcess:
        returncode = 0

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "sdk foreground stdout", ""

    monkeypatch.setattr(runner.local_execution.subprocess, "Popen", FakeProcess)

    runner._run_row(row, manifest)

    assert row["outcome"] == "passed"
    for key in ("blocker_category", "blockers", "failure_class", "failure_detail"):
        assert key not in row


def test_failed_live_row_with_busy_mcp_port_is_classified_as_blocked() -> None:
    for stderr in (
        (
            "error: requested MCP port 127.0.0.1:18788 is already accepting connections\n"
            "refusing to choose another port"
        ),
        "error: no MolmoSpaces visual backend slot is available under output/molmo/slots",
    ):
        row = {"exit_code": 1}

        runner._classify_failed_row(
            row,
            stderr=stderr,
            stdout="",
        )

        assert row["status"] == "blocked"
        assert row["outcome"] == "blocked"
        assert row["blocker_category"] == "environment_blocked"


def test_failed_dino_readiness_is_classified_as_environment_blocked() -> None:
    row = {"exit_code": 1}

    runner._classify_failed_row(
        row,
        stderr=(
            "visual grounding sidecar is not ready for product runs: timeout. "
            "visual grounding service timed out"
        ),
        stdout="",
    )

    assert row["status"] == "blocked"
    assert row["outcome"] == "blocked"
    assert row["blocker_category"] == "environment_blocked"


def test_optional_blocked_rows_do_not_fail_harness_exit_status() -> None:
    manifest = {
        "rows": [
            {
                "selected": True,
                "requirement": "optional",
                "status": "blocked",
                "outcome": "blocked",
            },
            {
                "selected": True,
                "requirement": "required",
                "status": "ran",
                "exit_code": 0,
                "outcome": "passed",
            },
        ]
    }

    assert runner._exit_status(manifest) == 0
    manifest["rows"][1]["status"] = "blocked"
    manifest["rows"][1]["outcome"] = "blocked"
    assert runner._exit_status(manifest) == 2


def test_dino_sidecar_default_matches_documented_service_port(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, int], float]] = []

    class _Socket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_create_connection(address: tuple[str, int], timeout: float):
        calls.append((address, timeout))
        return _Socket()

    monkeypatch.delenv("VISUAL_GROUNDING_BASE_URL", raising=False)
    monkeypatch.setattr(runner.socket, "create_connection", fake_create_connection)

    assert runner._dino_sidecar_available() is True
    assert calls == [(("127.0.0.1", 18880), 0.35)]


def test_dino_sidecar_requirement_autostarts_default_service(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls = {"available": 0, "started": 0, "stopped": 0}

    def fake_available() -> bool:
        calls["available"] += 1
        return calls["started"] > 0

    def fake_start(manifest: dict) -> bool:
        calls["started"] += 1
        manifest["dino_sidecar_autostart"] = {"base_url": runner.DEFAULT_VISUAL_GROUNDING_BASE_URL}
        return True

    def fake_stop() -> None:
        calls["stopped"] += 1

    monkeypatch.delenv("ROBOCLAWS_EVAL_HARNESS_AUTOSTART_DINO_SIDECAR", raising=False)
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner, "_dino_sidecar_available", fake_available)
    monkeypatch.setattr(runner, "_start_managed_dino_sidecar", fake_start)
    monkeypatch.setattr(runner, "_stop_managed_dino_sidecars", fake_stop)
    monkeypatch.setattr(
        runner,
        "_run_row",
        lambda row, manifest: row.update({"status": "ran", "outcome": "passed", "exit_code": 0}),
    )
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["roboclaws/household/visual_grounding.py"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    row = _selected_rows(manifest)["direct-camera-grounded-grounding-dino"]
    assert row["status"] == "ran"
    assert row["outcome"] == "passed"
    assert calls["available"] >= 1
    assert calls["started"] == 1
    assert calls["stopped"] == 1
    assert manifest["dino_sidecar_autostart"]["base_url"] == (
        runner.DEFAULT_VISUAL_GROUNDING_BASE_URL
    )


def test_dino_sidecar_autostart_can_be_disabled(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROBOCLAWS_EVAL_HARNESS_AUTOSTART_DINO_SIDECAR", "0")
    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner, "_dino_sidecar_available", lambda: False)
    monkeypatch.setattr(
        runner,
        "_start_managed_dino_sidecar",
        lambda manifest: (_ for _ in ()).throw(AssertionError("should not start")),
    )
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["roboclaws/household/visual_grounding.py"],
        output_dir=tmp_path,
    )

    blockers = runner._row_blockers(
        _selected_rows(manifest)["direct-camera-grounded-grounding-dino"],
        manifest,
    )

    assert blockers == [
        {
            "category": "environment_blocked",
            "detail": "Grounding DINO visual-grounding sidecar is not reachable",
        }
    ]


def test_recommendation_writes_json_markdown_and_html(tmp_path: Path) -> None:
    exit_code = runner.main(
        [
            "recommend",
            "--budget",
            "focused",
            "--changed-file",
            "roboclaws/agents/drivers/openai_agents_live.py",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    manifest = json.loads((tmp_path / "eval_harness.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "roboclaws_eval_harness_manifest_v1"
    assert manifest["profile"] == "adaptive"
    assert (tmp_path / "eval_harness.md").exists()
    assert (tmp_path / "eval_harness.html").exists()
    assert "openai-agents-sdk-open-task-live-eval" in (tmp_path / "eval_harness.md").read_text(
        encoding="utf-8"
    )
