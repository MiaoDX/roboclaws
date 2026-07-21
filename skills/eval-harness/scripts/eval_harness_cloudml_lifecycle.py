from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "roboclaws_eval_harness_cloudml_plan_v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "eval-harness"
TERMINAL_SUCCESS_STATES = {"completed", "succeed", "succeeded", "success"}
TERMINAL_FAILURE_STATES = {
    "cancelled",
    "canceled",
    "error",
    "failed",
    "killed",
    "stopped",
    "terminated",
}


def status_cloudml_run(
    run_ref: str,
    *,
    wait: bool = False,
    poll_interval_s: float = 15.0,
    timeout_s: float = 3600.0,
    executor_path: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    if poll_interval_s <= 0:
        raise ValueError("poll_interval_s must be greater than zero")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be greater than zero")
    plan_path, plan, _ = load_cloudml_run(run_ref)
    resolved_executor = executor_path or _executor_path()
    deadline = time.monotonic() + timeout_s
    while True:
        summary = _refresh_cloudml_status(plan, executor_path=resolved_executor)
        _write_json(plan_path, plan)
        if not wait or summary["all_terminal"]:
            return summary, plan_path
        if time.monotonic() >= deadline:
            raise TimeoutError(f"CloudML run {plan['run_id']} did not finish within {timeout_s:g}s")
        time.sleep(min(poll_interval_s, max(0.0, deadline - time.monotonic())))


def collect_cloudml_run(
    adapter: Any,
    run_ref: str,
    *,
    executor_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    plan_path, plan, manifest = load_cloudml_run(run_ref)
    resolved_executor = executor_path or _executor_path()
    status = _refresh_cloudml_status(plan, executor_path=resolved_executor)
    _write_json(plan_path, plan)
    if not status["all_terminal"]:
        raise ValueError(f"CloudML run {plan['run_id']} is not terminal")
    output_dir = Path(manifest["output_dir"])
    collected_root = output_dir / "cloudml" / "collected"
    result = subprocess.run(
        [
            str(resolved_executor),
            "storage",
            "juicefs",
            "download",
            "--url",
            str(plan["staging"]["output_url"]),
            "--output_dir",
            str(collected_root),
            "--refresh_list",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "CloudML result download failed: " + (result.stderr or result.stdout).strip()
        )
    download = _parse_json_object(result.stdout, label="JuiceFS download")
    if download.get("status") != "ok" or int(download.get("exit_code") or 0) != 0:
        raise RuntimeError(f"CloudML result download was not successful: {download}")
    plan["download"] = {
        "completed_at": _utc_now(),
        "output_dir": str(collected_root),
        "files": int(download.get("files") or 0),
    }
    collection = adapter.collect_cloudml_results(plan, manifest, collected_root=collected_root)
    if collection["missing_result_count"]:
        raise ValueError(
            f"CloudML collection is missing {collection['missing_result_count']} row result(s)"
        )
    _write_json(plan_path, plan)
    return plan, manifest, plan_path


def resume_cloudml_run(
    adapter: Any,
    run_ref: str,
    *,
    retry_shard_ids: tuple[str, ...] = (),
) -> tuple[dict[str, Any], Path]:
    plan_path, plan, _ = load_cloudml_run(run_ref)
    adapter.executor_from_environment(
        plan,
        dry_run=False,
        plan_path=plan_path,
        retry_shard_ids=retry_shard_ids,
    )
    _write_json(plan_path, plan)
    return plan, plan_path


def load_cloudml_run(run_ref: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    plan_path = _resolve_plan_path(run_ref)
    plan = _read_json_object(plan_path, label="CloudML plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"unsupported CloudML plan schema in {plan_path}")
    manifest_path = Path(str(plan.get("source_manifest") or ""))
    if not manifest_path.is_file():
        manifest_path = plan_path.parents[1] / "eval_harness.json"
    manifest = _read_json_object(manifest_path, label="eval harness manifest")
    return plan_path, plan, manifest


def _refresh_cloudml_status(plan: dict[str, Any], *, executor_path: Path) -> dict[str, Any]:
    shards = list(plan.get("shards") or [])
    submitted = [shard for shard in shards if shard.get("task_id")]
    for shard in submitted:
        task_id = str(shard["task_id"])
        result = subprocess.run(
            [
                str(executor_path),
                "compute",
                "cloudml",
                "custom_train",
                "describe",
                "--job_id",
                task_id,
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"CloudML status query failed for {task_id}: "
                + (result.stderr or result.stdout).strip()
            )
        job = _parse_json_object(result.stdout, label=f"CloudML status describe for {task_id}")
        resolved_id = str(
            job.get("jobId") or job.get("job_id") or job.get("task_id") or job.get("id") or ""
        )
        if resolved_id != task_id:
            raise RuntimeError(
                f"CloudML status describe returned job {resolved_id or '<missing>'} for {task_id}"
            )
        state = _normalize_cloudml_state(str(job.get("state") or job.get("status") or ""))
        shard["remote_status"] = state
        shard["status_checked_at"] = _utc_now()
        shard["console_url"] = str(job.get("console_url") or shard.get("console_url") or "")
    terminal_states = TERMINAL_SUCCESS_STATES | TERMINAL_FAILURE_STATES
    terminal_count = sum(1 for shard in submitted if shard.get("remote_status") in terminal_states)
    succeeded_count = sum(
        1 for shard in submitted if shard.get("remote_status") in TERMINAL_SUCCESS_STATES
    )
    failed_count = sum(
        1 for shard in submitted if shard.get("remote_status") in TERMINAL_FAILURE_STATES
    )
    summary = {
        "run_id": str(plan.get("run_id") or ""),
        "submitted_shard_count": len(submitted),
        "terminal_shard_count": terminal_count,
        "succeeded_shard_count": succeeded_count,
        "failed_shard_count": failed_count,
        "all_terminal": bool(shards)
        and len(submitted) == len(shards)
        and terminal_count == len(shards),
        "all_succeeded": bool(shards)
        and len(submitted) == len(shards)
        and succeeded_count == len(shards),
        "shards": [
            {
                "shard_id": str(shard["shard_id"]),
                "task_id": str(shard.get("task_id") or ""),
                "status": str(shard.get("remote_status") or "not_submitted"),
                "console_url": str(shard.get("console_url") or ""),
            }
            for shard in shards
        ],
    }
    plan["status"] = summary
    return summary


def _normalize_cloudml_state(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "queued": "enqueued",
        "queueing": "enqueued",
        "successful": "succeeded",
        "done": "completed",
        "cancel": "cancelled",
    }
    return aliases.get(normalized, normalized or "unknown")


def _resolve_plan_path(run_ref: str) -> Path:
    candidate = Path(run_ref)
    direct_candidates = [
        candidate,
        candidate / "cloudml_plan.json",
        candidate / "cloudml" / "cloudml_plan.json",
        DEFAULT_OUTPUT_ROOT / run_ref / "cloudml" / "cloudml_plan.json",
    ]
    for path in direct_candidates:
        if path.is_file():
            return path.resolve()
    matches = []
    for path in DEFAULT_OUTPUT_ROOT.glob("*/cloudml/cloudml_plan.json"):
        try:
            payload = _read_json_object(path, label="CloudML plan")
        except ValueError:
            continue
        if str(payload.get("run_id") or "") == run_ref:
            matches.append(path)
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        raise ValueError(f"multiple CloudML runs match {run_ref!r}; pass the output directory")
    raise ValueError(f"CloudML run not found: {run_ref}")


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    return _parse_json_object(path.read_text(encoding="utf-8"), label=label)


def _parse_json_object(value: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _executor_path() -> Path:
    return Path(os.environ.get("ROBOCLAWS_EXECUTOR_PATH", "/home/mi/executor/exe"))


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
