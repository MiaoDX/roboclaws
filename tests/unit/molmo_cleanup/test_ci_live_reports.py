from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roboclaws.household.ci_live_reports import (
    MODEL_ENTRIES,
    base_status,
    diagnostic_path_for_entry,
    entry_by_name,
    latest_seed_artifact_dir,
    publish_diagnostic_seed_run,
    publish_seed_run,
    read_status,
    report_path_for_entry,
    status_path_for_entry,
    write_live_index,
    write_manifest,
    write_status,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_MATRIX_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_ci_live_cleanup_matrix.py"
RUN_OPENAI_AGENTS_PATH = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "run_live_openai_agents_household.py"
)
ASSEMBLE_LIVE_PAGES_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "assemble_ci_live_pages.py"
PAGES_INDEX_PATH = REPO_ROOT / "scripts" / "reports" / "write_pages_index.py"


class _FakeHandoffServer:
    def __init__(self, run_result_path: Path) -> None:
        self.run_result_path = run_result_path
        self.wait_calls = 0

    def poll(self) -> int | None:
        return 0 if self.run_result_path.is_file() else None

    def wait(self) -> int:
        self.wait_calls += 1
        return 0


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ci_live_dry_run_args(tmp_path: Path, entry: str, *extra: str) -> list[str]:
    return [
        "--entry",
        entry,
        *extra,
        "--dry-run",
        "--skip-uv-sync",
        "--skip-prewarm",
        "--output-dir",
        str(tmp_path / "runs"),
        "--published-dir",
        str(tmp_path / "site" / "molmo" / "live"),
    ]


def test_ci_live_model_entries_match_provider_profiles() -> None:
    assert [entry.name for entry in MODEL_ENTRIES] == [
        "agents-sdk-kimi-k2.7-code",
    ]
    assert {
        entry.name: (
            entry.agent_engine,
            entry.provider_profile,
            entry.model,
            entry.secret_env,
            entry.profile,
        )
        for entry in MODEL_ENTRIES
    } == {
        "agents-sdk-kimi-k2.7-code": (
            "openai-agents-sdk",
            "kimi-openai-chat",
            "kimi-k2.7-code",
            "KIMI_API_KEY",
            "world-public-labels",
        ),
    }


def test_ci_live_status_reader_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(
        FileNotFoundError,
        match=r"Molmo live CI status source is missing: .*status\.json",
    ):
        read_status(tmp_path / "status.json")


def test_ci_live_status_reader_rejects_malformed_source(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    status_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Molmo live CI status source must contain valid JSON object: .*status\.json",
    ):
        read_status(status_path)


def test_ci_live_status_reader_rejects_non_object_source(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    status_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Molmo live CI status source must contain a JSON object: .*status\.json",
    ):
        read_status(status_path)


def test_dry_run_matrix_writes_status_and_manifest(tmp_path: Path) -> None:
    run_matrix = _load_module(RUN_MATRIX_PATH, "run_ci_live_cleanup_matrix")

    status = run_matrix.main(_ci_live_dry_run_args(tmp_path, "agents-sdk-kimi-k2.7-code"))

    assert status == 0
    status_path = tmp_path / "site" / "molmo" / "live" / "agents-sdk-kimi-k2.7-code" / "status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["status"] == "dry_run"
    assert payload["agent_engine"] == "openai-agents-sdk"
    assert payload["env"] == {
        "ROBOCLAWS_OPENAI_AGENTS_MODEL": "kimi-k2.7-code",
        "ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat",
        "ROBOCLAWS_PROVIDER_TIMING_PROXY": "1",
    }
    assert payload["profile"] == "world-public-labels"
    assert payload["generated_mess_count"] == 5
    assert payload["command"][:9] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=cleanup",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "evidence_lane=world-public-labels",
    ]
    assert payload["rerun_command"].startswith(
        "ROBOCLAWS_PROVIDER_PROFILE=kimi-openai-chat "
        "ROBOCLAWS_OPENAI_AGENTS_MODEL=kimi-k2.7-code "
        "ROBOCLAWS_PROVIDER_TIMING_PROXY=1 "
        "just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 "
        "backend=mujoco intent=cleanup agent_engine=openai-agents-sdk "
        "provider_profile=kimi-openai-chat evidence_lane=world-public-labels"
    )
    manifest = json.loads(
        (tmp_path / "site" / "molmo" / "live" / "live-report-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["schema"] == "molmo_live_ci_report_manifest_v1"
    assert manifest["entries"][0]["entry"] == "agents-sdk-kimi-k2.7-code"


def test_dry_run_agents_sdk_entry_uses_entry_engine_and_model_env(tmp_path: Path) -> None:
    run_matrix = _load_module(RUN_MATRIX_PATH, "run_ci_live_cleanup_matrix")

    status = run_matrix.main(_ci_live_dry_run_args(tmp_path, "agents-sdk-kimi-k2.7-code"))

    assert status == 0
    status_path = tmp_path / "site" / "molmo" / "live" / "agents-sdk-kimi-k2.7-code" / "status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["entry"] == "agents-sdk-kimi-k2.7-code"
    assert payload["label"] == "OpenAI Agents SDK + Kimi K2.7 Code"
    assert payload["agent_engine"] == "openai-agents-sdk"
    assert payload["model"] == "kimi-k2.7-code"
    assert payload["profile"] == "world-public-labels"
    assert payload["generated_mess_count"] == 5
    assert payload["env"] == {
        "ROBOCLAWS_OPENAI_AGENTS_MODEL": "kimi-k2.7-code",
        "ROBOCLAWS_PROVIDER_PROFILE": "kimi-openai-chat",
        "ROBOCLAWS_PROVIDER_TIMING_PROXY": "1",
    }
    assert payload["command"][:9] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=cleanup",
        "agent_engine=openai-agents-sdk",
        "provider_profile=kimi-openai-chat",
        "evidence_lane=world-public-labels",
    ]
    assert "relocation_count=5" in payload["command"]
    assert "ROBOCLAWS_OPENAI_AGENTS_MODEL=kimi-k2.7-code" in payload["rerun_command"]
    assert "agent_engine=openai-agents-sdk" in payload["rerun_command"]


def test_dry_run_generated_mess_count_override(tmp_path: Path) -> None:
    run_matrix = _load_module(RUN_MATRIX_PATH, "run_ci_live_cleanup_matrix")

    status = run_matrix.main(
        _ci_live_dry_run_args(
            tmp_path,
            "agents-sdk-kimi-k2.7-code",
            "--generated-mess-count",
            "12",
        )
    )

    assert status == 0
    status_path = tmp_path / "site" / "molmo" / "live" / "agents-sdk-kimi-k2.7-code" / "status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["generated_mess_count"] == 12
    assert "relocation_count=12" in payload["command"]


def test_ci_live_matrix_preserves_provider_timing_proxy_escape_hatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_matrix = _load_module(RUN_MATRIX_PATH, "run_ci_live_cleanup_matrix")
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_TIMING_PROXY", "0")

    status = run_matrix.main(_ci_live_dry_run_args(tmp_path, "agents-sdk-kimi-k2.7-code"))

    assert status == 0
    payload = json.loads(
        (
            tmp_path / "site" / "molmo" / "live" / "agents-sdk-kimi-k2.7-code" / "status.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["env"]["ROBOCLAWS_PROVIDER_TIMING_PROXY"] == "0"
    assert payload["rerun_command"].startswith(
        "ROBOCLAWS_PROVIDER_PROFILE=kimi-openai-chat "
        "ROBOCLAWS_OPENAI_AGENTS_MODEL=kimi-k2.7-code "
        "ROBOCLAWS_PROVIDER_TIMING_PROXY=0 "
    )


def test_failed_live_entry_publishes_partial_seed_diagnostics(tmp_path: Path, monkeypatch) -> None:
    run_matrix = _load_module(RUN_MATRIX_PATH, "run_ci_live_cleanup_matrix")
    entry = entry_by_name("agents-sdk-kimi-k2.7-code")
    output_dir = tmp_path / "runs"
    publish_root = tmp_path / "site" / "molmo" / "live"
    args = SimpleNamespace(
        output_dir=output_dir,
        seed=7,
        generated_mess_count=5,
        profile="world-public-labels",
        task="帮我收拾这个房间",
        host="127.0.0.1",
        port=18788,
        just_bin="just",
        dry_run=False,
        continue_on_error=False,
    )

    monkeypatch.setenv("KIMI_API_KEY", "test-key")

    def fake_run_checked(_command, **_kwargs):
        empty_latest_seed = output_dir / entry.name / "0513_2300" / "seed-7"
        empty_latest_seed.mkdir(parents=True)
        seed_dir = output_dir / entry.name / "0513_2217" / "seed-7"
        seed_dir.mkdir(parents=True)
        (seed_dir / "live_status.json").write_text('{"phase":"failed"}\n', encoding="utf-8")
        (seed_dir / "claude-events.jsonl").write_text(
            '{"type":"result","is_error":true}\n',
            encoding="utf-8",
        )
        (seed_dir / "claude.stderr.log").write_text("provider failed\n", encoding="utf-8")
        raise RuntimeError("provider failed")

    monkeypatch.setattr(run_matrix, "_run_checked", fake_run_checked)

    status = run_matrix._run_entry(entry, args, publish_root=publish_root)

    assert status["status"] == "failed"
    assert status["diagnostic_path"] == diagnostic_path_for_entry(entry.name, seed=7)
    assert status["run_dir"].endswith("0513_2217/seed-7")
    diagnostic_root = publish_root / entry.name / "diagnostics" / "seed-7"
    assert (diagnostic_root / "diagnostics.html").is_file()
    assert (diagnostic_root / "claude-events.jsonl").read_text(encoding="utf-8")
    assert not (diagnostic_root / "0513_2300").exists()
    payload = json.loads((publish_root / entry.name / "status.json").read_text(encoding="utf-8"))
    assert payload["diagnostic_path"] == status["diagnostic_path"]


def test_latest_seed_artifact_dir_ignores_seed_dirs_without_diagnostic_evidence(
    tmp_path: Path,
) -> None:
    entry_output_dir = tmp_path / "runs" / "agents-sdk-kimi-k2.7-code"
    (entry_output_dir / "0513_2217" / "seed-7").mkdir(parents=True)
    (entry_output_dir / "0513_2300" / "seed-7").mkdir(parents=True)

    assert latest_seed_artifact_dir(entry_output_dir, seed=7) is None


def test_live_openai_agents_explicit_operator_handoff_pauses_without_continuation(
    tmp_path: Path, monkeypatch
) -> None:
    run_sdk = _load_module(RUN_OPENAI_AGENTS_PATH, "run_live_openai_agents_household")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    args = SimpleNamespace(
        run_dir=run_dir,
        status_path=tmp_path / "live_status.json",
        repo_root=REPO_ROOT,
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        server_startup_timeout_s=3.0,
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        max_turns=None,
        incomplete_turn_continuation_attempts=None,
        cache_tools_list=True,
        mcp_client_session_timeout_s=None,
        agent_sdk_perf_profile="",
        continuation_mode="",
        model_thinking_mode="default",
        model_input_compaction=None,
        model_input_compaction_min_chars=None,
        model_racing=None,
        model_racing_arm_count=None,
        raw_fpv_image_memory=None,
        raw_fpv_image_memory_retain=None,
        camera_grounded_history_compaction=None,
        camera_grounded_history_retain=None,
        raw_fpv_candidate_budget=None,
        raw_fpv_repeated_failure_limit=None,
        done_retry_budget=None,
        max_observe_per_waypoint=None,
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        kickoff_prompt="到达第一个 waypoint 点，等待，不要调用 done，我计划手动调整下位置",
        backend="molmospaces_subprocess",
        task_surface="household-world",
        intent="open-ended",
        skill_name="household-world",
        policy="openai_agents_agent",
        task="到达第一个 waypoint 点，等待，不要调用 done，我计划手动调整下位置",
        min_generated_mess_count="0",
        profile="world-public-labels",
        checker_profile="",
        server_arg=[],
        checker_visual_arg=[],
        operator_resume_requests_path=None,
    )
    runner = run_sdk.LiveOpenAIAgentsHouseholdRunner(args)
    runner.server_proc = SimpleNamespace(poll=lambda: None)
    calls = []

    class FakeRuntime:
        def run(self, request):
            calls.append(request.kickoff_prompt)
            return SimpleNamespace(
                phase="agent-turn-complete",
                exit_status=0,
                reason="",
                provider_reason="",
                retryable=False,
                resume_available=False,
                usage={},
                trace_id="trace-1",
                provider_session_id="session-1",
                run_result_present=False,
                started_at_epoch=1.0,
                finished_at_epoch=2.0,
            )

    monkeypatch.setattr(run_sdk, "OpenAIAgentsLiveRuntime", FakeRuntime)

    runner._run_sdk_agent()

    assert runner.operator_handoff_active is True
    assert len(calls) == 1
    payload = json.loads(args.status_path.read_text(encoding="utf-8"))
    assert payload["phase"] == "paused"
    assert payload["reason"] == "operator_handoff_requested"
    assert payload["resume_available"] is True
    assert "MCP server remains alive" in payload["detail"]
    assert runner.live_timing["openai_agents_attempts"][0]["recovery_action"] == (
        "operator_handoff"
    )


def test_live_openai_agents_paused_handoff_consumes_resume_request_and_runs_second_turn(
    tmp_path: Path, monkeypatch
) -> None:
    run_sdk = _load_module(RUN_OPENAI_AGENTS_PATH, "run_live_openai_agents_household")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    resume_path = run_dir / "operator_resume_requests.jsonl"
    resume_path.write_text(
        json.dumps(
            {
                "schema": "operator_console_message_v1",
                "message_id": "resume-1",
                "command_type": "resume_with_prompt",
                "status": "queued",
                "body": "Continue from the adjusted pose.",
                "resume_request_packet": {
                    "schema": "operator_console_resume_request_packet_v1",
                    "operator_prompt": "Continue from the adjusted pose.",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        run_dir=run_dir,
        status_path=tmp_path / "live_status.json",
        repo_root=REPO_ROOT,
        client_url="http://127.0.0.1:18788/mcp",
        host="127.0.0.1",
        port=18788,
        lock_path=tmp_path / "live.lock",
        server_startup_timeout_s=3.0,
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        max_turns=None,
        incomplete_turn_continuation_attempts=None,
        cache_tools_list=True,
        mcp_client_session_timeout_s=None,
        agent_sdk_perf_profile="",
        continuation_mode="",
        model_thinking_mode="default",
        model_input_compaction=None,
        model_input_compaction_min_chars=None,
        model_racing=None,
        model_racing_arm_count=None,
        raw_fpv_image_memory=None,
        raw_fpv_image_memory_retain=None,
        camera_grounded_history_compaction=None,
        camera_grounded_history_retain=None,
        raw_fpv_candidate_budget=None,
        raw_fpv_repeated_failure_limit=None,
        done_retry_budget=None,
        max_observe_per_waypoint=None,
        context_soft_limit_tokens=None,
        context_hard_limit_tokens=None,
        model_service_retry_attempts=None,
        model_service_retry_sleep_s=None,
        kickoff_prompt="handoff",
        backend="molmospaces_subprocess",
        task_surface="household-world",
        intent="open-ended",
        skill_name="household-world",
        policy="openai_agents_agent",
        task="handoff",
        min_generated_mess_count="0",
        profile="world-public-labels",
        checker_profile="",
        server_arg=[],
        checker_visual_arg=[],
        operator_resume_requests_path=resume_path,
    )
    runner = run_sdk.LiveOpenAIAgentsHouseholdRunner(args)
    runner.server_proc = _FakeHandoffServer(run_dir / "run_result.json")
    calls = []

    class FakeRuntime:
        def run(self, request):
            calls.append(request)
            (run_dir / "run_result.json").write_text(
                json.dumps({"cleanup_status": "success"}),
                encoding="utf-8",
            )
            return SimpleNamespace(
                phase="agent-turn-complete",
                exit_status=0,
                reason="",
                provider_reason="",
                retryable=False,
                resume_available=False,
                usage={},
                trace_id="trace-resume",
                provider_session_id="session-resume",
                run_result_present=True,
                started_at_epoch=1.0,
                finished_at_epoch=2.0,
            )

    monkeypatch.setattr(run_sdk, "OpenAIAgentsLiveRuntime", FakeRuntime)
    monkeypatch.setattr(runner, "_check_result", lambda: None)

    status = runner._finish_operator_handoff()

    assert status == 0
    assert len(calls) == 1
    assert "resume_request_packet" in calls[0].kickoff_prompt
    request_rows = [
        json.loads(line) for line in resume_path.read_text(encoding="utf-8").splitlines()
    ]
    assert request_rows[0]["status"] == "claimed"
    attempts = json.loads(
        (run_dir / "operator_handoff_resume_attempts.json").read_text(encoding="utf-8")
    )
    assert attempts["attempts"][-1]["agent_engine"] == "openai-agents-sdk"
    payload = json.loads(args.status_path.read_text(encoding="utf-8"))
    assert payload["phase"] == "finished"


def test_publish_seed_run_and_pages_index_render_molmo_live_tiles(tmp_path: Path) -> None:
    write_pages_index = _load_module(PAGES_INDEX_PATH, "write_pages_index")

    source_seed = tmp_path / "source" / "0513_1447" / "seed-7"
    source_seed.mkdir(parents=True)
    (source_seed / "run_result.json").write_text("{}", encoding="utf-8")
    (source_seed / "report.html").write_text("<!doctype html>", encoding="utf-8")

    live_root = tmp_path / "site" / "molmo" / "live"
    published = publish_seed_run(
        source_seed_dir=source_seed,
        publish_root=live_root,
        entry_name="agents-sdk-kimi-k2.7-code",
        seed=7,
    )
    assert (published / "report.html").is_file()
    agents_published = publish_seed_run(
        source_seed_dir=source_seed,
        publish_root=live_root,
        entry_name="agents-sdk-kimi-k2.7-code",
        seed=7,
    )
    assert (agents_published / "report.html").is_file()

    success = base_status(
        entry_by_name("agents-sdk-kimi-k2.7-code"),
        seed=7,
        generated_mess_count=5,
        profile="world-public-labels",
        task="帮我收拾这个房间",
    )
    success.update(
        {
            "status": "success",
            "report_path": report_path_for_entry("agents-sdk-kimi-k2.7-code", seed=7),
        }
    )
    agents_success = base_status(
        entry_by_name("agents-sdk-kimi-k2.7-code"),
        seed=7,
        generated_mess_count=5,
        profile="world-public-labels",
        task="帮我收拾这个房间",
    )
    agents_success.update(
        {
            "status": "success",
            "report_path": report_path_for_entry("agents-sdk-kimi-k2.7-code", seed=7),
        }
    )
    write_status(status_path_for_entry(live_root, "agents-sdk-kimi-k2.7-code"), success)
    write_status(status_path_for_entry(live_root, "agents-sdk-kimi-k2.7-code"), agents_success)
    write_manifest(live_root)
    live_index = write_live_index(live_root)
    live_html = live_index.read_text(encoding="utf-8")
    assert "MolmoSpaces Live Cleanup Reports" in live_html
    assert "agents-sdk-kimi-k2.7-code/seed-7/report.html" in live_html
    assert "agents-sdk-kimi-k2.7-code/seed-7/report.html" in live_html
    assert "OpenAI Agents SDK + Kimi K2.7 Code" in live_html
    assert "openai-agents-sdk" in live_html
    assert "Rerun locally" in live_html

    out = write_pages_index.write_index(tmp_path / "site", include_molmo_live=True)
    html = out.read_text(encoding="utf-8")
    assert "MolmoSpaces Live Cleanup (main-only / opt-in CI)" in html
    assert "molmo/live/" in html
    assert "molmo/live/agents-sdk-kimi-k2.7-code/seed-7/report.html" in html
    assert "molmo/live/agents-sdk-kimi-k2.7-code/seed-7/report.html" in html
    assert "OpenAI Agents SDK + Kimi K2.7 Code" in html
    assert "openai-agents-sdk" in html
    assert "Kimi K2.7 Code" in html


def test_publish_diagnostic_seed_run_and_pages_index_link_failed_tile(tmp_path: Path) -> None:
    write_pages_index = _load_module(PAGES_INDEX_PATH, "write_pages_index")

    source_seed = tmp_path / "source" / "0513_2217" / "seed-7"
    source_seed.mkdir(parents=True)
    (source_seed / "live_status.json").write_text('{"phase":"failed"}\n', encoding="utf-8")
    (source_seed / "claude.stderr.log").write_text("provider failed\n", encoding="utf-8")

    live_root = tmp_path / "site" / "molmo" / "live"
    published = publish_diagnostic_seed_run(
        source_seed_dir=source_seed,
        publish_root=live_root,
        entry_name="agents-sdk-kimi-k2.7-code",
        seed=7,
    )
    assert (published / "diagnostics.html").is_file()

    failed = base_status(
        entry_by_name("agents-sdk-kimi-k2.7-code"),
        seed=7,
        generated_mess_count=5,
        profile="world-public-labels",
        task="帮我收拾这个房间",
    )
    failed.update(
        {
            "status": "failed",
            "reason": "provider failed",
            "diagnostic_path": diagnostic_path_for_entry(
                "agents-sdk-kimi-k2.7-code",
                seed=7,
            ),
        }
    )
    write_status(status_path_for_entry(live_root, "agents-sdk-kimi-k2.7-code"), failed)
    write_manifest(live_root)
    live_index = write_live_index(live_root)
    live_html = live_index.read_text(encoding="utf-8")
    assert "agents-sdk-kimi-k2.7-code/diagnostics/seed-7/diagnostics.html" in live_html

    out = write_pages_index.write_index(tmp_path / "site", include_molmo_live=True)
    html = out.read_text(encoding="utf-8")
    assert "molmo/live/agents-sdk-kimi-k2.7-code/diagnostics/seed-7/diagnostics.html" in html
    assert "OpenAI Agents SDK + Kimi K2.7 Code diagnostics" in html


def test_pages_index_without_live_manifest_renders_household_placeholder(tmp_path: Path) -> None:
    write_pages_index = _load_module(PAGES_INDEX_PATH, "write_pages_index")

    out = write_pages_index.write_index(tmp_path / "site", include_molmo_live=True)
    html = out.read_text(encoding="utf-8")

    assert "Household Reports" in html
    assert "No published household cleanup reports are available yet." in html
    assert "openclaw/demo/report.html" not in html
    assert "territory/report.html" not in html


def test_assemble_ci_live_pages_runs_without_site_packages(tmp_path: Path) -> None:
    source_root = tmp_path / "molmo-live-src"
    live_root = tmp_path / "site" / "molmo" / "live"
    status = base_status(
        entry_by_name("agents-sdk-kimi-k2.7-code"),
        seed=7,
        generated_mess_count=5,
        profile="world-public-labels",
        task="帮我收拾这个房间",
    )
    status.update({"status": "skipped", "reason": "fixture"})
    write_status(status_path_for_entry(source_root, "agents-sdk-kimi-k2.7-code"), status)

    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ASSEMBLE_LIVE_PAGES_PATH),
            str(source_root),
            str(live_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (live_root / "live-report-manifest.json").is_file()
    assert (live_root / "index.html").is_file()
