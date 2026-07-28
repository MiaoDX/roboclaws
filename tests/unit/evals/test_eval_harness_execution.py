from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytest import MonkeyPatch

from roboclaws.evals import cli

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "run_eval_harness.py"
ROWS_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_rows.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_module("eval_harness_execution_runner_test", RUNNER_PATH)
rows_module = _load_module("eval_harness_execution_rows_test", ROWS_PATH)
local_execution = runner.local_execution


def _row(
    tmp_path: Path,
    row_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    concurrency_group: str = "",
) -> dict[str, Any]:
    return {
        "schema": "roboclaws_eval_harness_row_v1",
        "row_id": row_id,
        "row_kind": "contract_test",
        "selected": True,
        "status": "not_run",
        "outcome": "",
        "requirement": "required",
        "depends_on": list(depends_on),
        "concurrency_group": concurrency_group,
        "timeout_s": 10,
        "row_dir": str(tmp_path / "rows" / row_id),
        "command": [sys.executable, "-c", "pass"],
        "command_display": f"run {row_id}",
    }


def _manifest(tmp_path: Path, *rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "budget": "focused",
        "profile": "adaptive",
        "signals": [],
        "summary": {"selected_row_count": len(rows)},
        "output_dir": str(tmp_path),
        "rows": list(rows),
    }


def _pass_row(row: dict[str, Any], _manifest: dict[str, Any]) -> None:
    row.update(status="ran", outcome="passed", exit_code=0)


def _no_blockers(_row: dict[str, Any], _manifest: dict[str, Any]) -> list[dict[str, str]]:
    return []


def test_local_execution_defaults_to_one_serial_worker(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _row(tmp_path, "a"), _row(tmp_path, "b"))
    active = 0
    max_active = 0
    lock = threading.Lock()

    def run_row(row: dict[str, Any], manifest: dict[str, Any]) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        _pass_row(row, manifest)

    local_execution.execute_local_rows(
        manifest,
        run_row=run_row,
        row_blockers=_no_blockers,
        write_row_result=lambda row: None,
    )

    assert max_active == 1
    assert manifest["execution"] == {
        "execution_target": "local",
        "worker_pool": "local",
        "shard_id": "local-main",
        "max_parallel": 1,
        "row_ids": ["a", "b"],
    }


def test_independent_rows_overlap_with_parallel_workers(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, _row(tmp_path, "a"), _row(tmp_path, "b"))
    active = 0
    max_active = 0
    lock = threading.Lock()

    def run_row(row: dict[str, Any], manifest: dict[str, Any]) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        _pass_row(row, manifest)

    local_execution.execute_local_rows(
        manifest,
        run_row=run_row,
        row_blockers=_no_blockers,
        write_row_result=lambda row: None,
        max_parallel=2,
    )

    assert max_active == 2


def test_concurrency_group_stays_serial(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        _row(tmp_path, "a", concurrency_group="visual"),
        _row(tmp_path, "b", concurrency_group="visual"),
    )
    active = 0
    max_active = 0
    lock = threading.Lock()

    def run_row(row: dict[str, Any], manifest: dict[str, Any]) -> None:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        _pass_row(row, manifest)

    local_execution.execute_local_rows(
        manifest,
        run_row=run_row,
        row_blockers=_no_blockers,
        write_row_result=lambda row: None,
        max_parallel=2,
    )

    assert max_active == 1


def test_dependency_runs_before_consumer(tmp_path: Path) -> None:
    producer = _row(tmp_path, "producer")
    consumer = _row(tmp_path, "consumer", depends_on=("producer",))
    manifest = _manifest(tmp_path, consumer, producer)
    order: list[str] = []

    def run_row(row: dict[str, Any], manifest: dict[str, Any]) -> None:
        order.append(row["row_id"])
        _pass_row(row, manifest)

    local_execution.execute_local_rows(
        manifest,
        run_row=run_row,
        row_blockers=_no_blockers,
        write_row_result=lambda row: None,
        max_parallel=2,
    )

    assert order == ["producer", "consumer"]


def test_failed_dependency_blocks_consumer(tmp_path: Path) -> None:
    producer = _row(tmp_path, "producer")
    consumer = _row(tmp_path, "consumer", depends_on=("producer",))
    manifest = _manifest(tmp_path, producer, consumer)
    executed: list[str] = []

    def run_row(row: dict[str, Any], _manifest: dict[str, Any]) -> None:
        executed.append(row["row_id"])
        row.update(status="ran", outcome="failed", exit_code=1)

    local_execution.execute_local_rows(
        manifest,
        run_row=run_row,
        row_blockers=_no_blockers,
        write_row_result=lambda row: None,
        max_parallel=2,
    )

    assert executed == ["producer"]
    assert consumer["status"] == "blocked"
    assert consumer["blocker_category"] == "dependency_blocked"


@pytest.mark.parametrize("dependency", ["missing", "self"])
def test_unresolvable_dependency_blocks_loudly(tmp_path: Path, dependency: str) -> None:
    row_id = "self" if dependency == "self" else "consumer"
    row = _row(tmp_path, row_id, depends_on=(dependency,))
    manifest = _manifest(tmp_path, row)

    local_execution.execute_local_rows(
        manifest,
        run_row=_pass_row,
        row_blockers=_no_blockers,
        write_row_result=lambda row: None,
    )

    assert row["status"] == "blocked"
    assert row["outcome"] == "blocked"
    assert row["blocker_category"] == "dependency_blocked"
    assert row["blockers"][0]["detail"]


def test_runner_records_provenance_timing_and_redacted_row_result(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    row = _row(tmp_path, "a")
    row["private_evaluation"] = {"hidden_targets": ["secret"]}
    manifest = _manifest(tmp_path, row)
    monkeypatch.setattr(runner, "_run_row", _pass_row)
    monkeypatch.setattr(runner, "_row_blockers", _no_blockers)

    runner._execute_harness(manifest, shard_id="shard-7")

    payload = json.loads((Path(row["row_dir"]) / "row_result.json").read_text(encoding="utf-8"))
    assert payload["attempt"] == 1
    assert payload["execution_target"] == "local"
    assert payload["worker_pool"] == "local"
    assert payload["shard_id"] == "shard-7"
    assert payload["worker_id"]
    assert payload["started_at"].endswith("Z")
    assert payload["finished_at"].endswith("Z")
    assert payload["duration_s"] >= 0
    assert payload["output_artifacts"][-1].endswith("row_result.json")
    assert "private_evaluation" not in payload
    assert "hidden_targets" not in json.dumps(payload)


def test_cloudml_worker_environment_records_remote_provenance(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    row = _row(tmp_path, "a")
    manifest = _manifest(tmp_path, row)
    monkeypatch.setenv("ROBOCLAWS_EVAL_EXECUTION_TARGET", "cloudml")
    monkeypatch.setenv("ROBOCLAWS_EVAL_WORKER_POOL", "cloudml-r49")
    monkeypatch.setenv("ROBOCLAWS_EVAL_CLOUDML_JOB_ID", "t-demo")
    monkeypatch.setenv("ROBOCLAWS_EVAL_CLOUDML_POD_NAME", "pod-demo")
    monkeypatch.setattr(runner, "_run_row", _pass_row)
    monkeypatch.setattr(runner, "_row_blockers", _no_blockers)

    runner._execute_harness(manifest, shard_id="shard-7")

    assert row["execution_target"] == "cloudml"
    assert row["worker_pool"] == "cloudml-r49"
    assert row["cloudml_job_id"] == "t-demo"
    assert row["cloudml_pod_name"] == "pod-demo"


def test_frozen_manifest_executes_exact_rows_without_selection(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    first = _row(output_dir, "first")
    second = _row(output_dir, "second")
    manifest = _manifest(output_dir, first, second)
    manifest_path = tmp_path / "frozen.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        runner.selector,
        "build_eval_harness",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("selector must not run")),
    )
    monkeypatch.setattr(runner, "_run_row", _pass_row)
    monkeypatch.setattr(runner, "_row_blockers", _no_blockers)

    exit_code = runner.main(["execute", "--manifest", str(manifest_path), "--row-id", "first"])

    payload = json.loads((output_dir / "eval_harness.json").read_text(encoding="utf-8"))
    by_id = {row["row_id"]: row for row in payload["rows"]}
    assert exit_code == 0
    assert by_id["first"]["outcome"] == "passed"
    assert by_id["second"]["status"] == "not_run"
    assert payload["execution"]["row_ids"] == ["first"]


def test_row_timeout_is_recorded_and_process_is_stopped(tmp_path: Path) -> None:
    row = _row(tmp_path, "timeout")
    row["command"] = [sys.executable, "-c", "import time; time.sleep(5)"]
    row["timeout_s"] = 0.05

    runner._run_row(row, _manifest(tmp_path, row))

    assert row["status"] == "ran"
    assert row["outcome"] == "failed"
    assert row["exit_code"] == 124
    assert row["failure_class"] == "harness_row_timeout"


def test_eval_cli_forwards_execution_overrides(monkeypatch: MonkeyPatch) -> None:
    captured: list[str] = []
    fake_runner = SimpleNamespace(main=lambda argv: captured.extend(argv) or 0)
    monkeypatch.setattr(cli, "_load_eval_harness_runner", lambda: fake_runner)

    exit_code = cli._run_eval_harness(
        "execute",
        {
            "execution_target": "local",
            "max_parallel": "4",
            "cloudml_dry_run": "true",
            "manifest": "output/eval-harness/frozen.json",
            "row_id": "a,b",
            "shard_id": "worker-2",
        },
    )

    assert exit_code == 0
    assert captured == [
        "execute",
        "--execution-target",
        "local",
        "--max-parallel",
        "4",
        "--cloudml-dry-run",
        "true",
        "--manifest",
        "output/eval-harness/frozen.json",
        "--row-id",
        "a,b",
        "--shard-id",
        "worker-2",
    ]


def test_catalog_resolves_execution_and_provider_requirements(tmp_path: Path) -> None:
    rows = {
        row["row_id"]: row
        for row in rows_module.candidate_rows(output_dir=tmp_path, explicit_axes={})
    }

    codex = rows["map-build-consumer-openai-agents-sdk-codex-router-responses"]
    kimi = rows["map-build-consumer-openai-agents-sdk-kimi-openai-chat"]
    consumer = rows["direct-cleanup-runtime-prior-consumer"]
    assert "network:internal-api-router" in codex["execution_requirements"]
    assert "network:external-egress" in kimi["execution_requirements"]
    assert "provider:kimi-openai-chat" in kimi["execution_requirements"]
    assert codex["timeout_s"] == 3600
    assert consumer["depends_on"] == ["direct-map-build-world-public"]
