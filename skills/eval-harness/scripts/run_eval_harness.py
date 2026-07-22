#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from roboclaws.core.json_sources import read_json_object  # noqa: E402

SELECTOR_PATH = SCRIPT_DIR / "select_eval_harness.py"
LOCAL_EXECUTION_PATH = SCRIPT_DIR / "eval_harness_local_execution.py"
CLOUDML_EXECUTION_PATH = SCRIPT_DIR / "eval_harness_cloudml.py"
CLOUDML_LIFECYCLE_PATH = SCRIPT_DIR / "eval_harness_cloudml_lifecycle.py"
DEFAULT_VISUAL_GROUNDING_BASE_URL = "http://127.0.0.1:18880"
PROVIDER_TIMING_PROXY_ENV = "ROBOCLAWS_PROVIDER_TIMING_PROXY"
DINO_SIDECAR_AUTOSTART_ENV = "ROBOCLAWS_EVAL_HARNESS_AUTOSTART_DINO_SIDECAR"
EVAL_HARNESS_MCP_PORT_ENV = "ROBOCLAWS_EVAL_HARNESS_MCP_PORT"
SESSION_LIVE_MCP_PORT_ENV = "ROBOCLAWS_SESSION_LIVE_MCP_PORT"
DINO_SIDECAR_STARTUP_TIMEOUT_S = 15.0
ROW_BLOCKER_REQUIREMENT_PRIORITY = {
    "codex_provider": 0,
    "openai_agents_package": 1,
    "just": 2,
    "python_env": 3,
    "dino_sidecar": 4,
    "runtime_map_prior": 5,
    "docker": 6,
}
RUNTIME_MAP_PRIOR_SOURCE_ROW_ID = "direct-map-build-world-public"


def _load_script(name: str, path: Path) -> Any:
    script_spec = importlib.util.spec_from_file_location(name, path)
    if script_spec is None or script_spec.loader is None:
        raise RuntimeError(f"could not load {name} at {path}")
    module = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(module)
    return module


selector = _load_script("eval_harness_selector", SELECTOR_PATH)
local_execution = _load_script("eval_harness_local_execution", LOCAL_EXECUTION_PATH)
cloudml_execution = _load_script("eval_harness_cloudml", CLOUDML_EXECUTION_PATH)
cloudml_lifecycle = _load_script("eval_harness_cloudml_lifecycle", CLOUDML_LIFECYCLE_PATH)


_MANAGED_DINO_SIDECARS: list[dict[str, Any]] = []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recommend or execute adaptive Roboclaws eval-harness rows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("mode", choices=("recommend", "execute"))
    parser.add_argument("--budget", choices=("smoke", "focused", "full"), default="focused")
    parser.add_argument("--profile", choices=selector.HARNESS_PROFILES, default="adaptive")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--since")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--agent-engine", default="")
    parser.add_argument("--provider-profile", default="")
    parser.add_argument("--intent", default="")
    parser.add_argument("--preset", default="")
    parser.add_argument("--evidence-lane", default="")
    parser.add_argument("--camera-labeler", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--execution-target", choices=("local", "cloudml", "auto"), default="local")
    parser.add_argument("--max-parallel", type=local_execution.positive_int, default=1)
    parser.add_argument("--cloudml-dry-run", type=cloudml_execution.bool_value, default=False)
    parser.add_argument("--cloudml-preemptible", type=cloudml_execution.bool_value, default=False)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--row-id", action="append", default=[])
    parser.add_argument("--shard-id", default="local-main")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    row_ids = selector._split_csv_values(args.row_id)
    manifest = _manifest_from_args(args)
    output_dir = Path(manifest["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "execute":
        if args.execution_target == "local":
            _execute_harness(
                manifest,
                row_ids=row_ids,
                max_parallel=args.max_parallel,
                shard_id=args.shard_id,
            )
        else:
            _write_outputs(manifest, output_dir)
            cloudml_execution.prepare_cloudml_execution(
                manifest,
                execution_target=args.execution_target,
                row_ids=row_ids,
                run_id=args.shard_id if args.shard_id != "local-main" else "",
                dry_run=args.cloudml_dry_run,
                preemptible=args.cloudml_preemptible,
            )
    _write_outputs(manifest, output_dir)
    print(f"eval harness manifest: {output_dir / 'eval_harness.json'}")
    print(f"eval harness report: {output_dir / 'eval_harness.html'}")
    return _exit_status(manifest, row_ids=row_ids)


def _manifest_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.manifest is not None:
        if args.mode != "execute":
            raise ValueError("--manifest is only supported in execute mode")
        manifest = _load_frozen_manifest(args.manifest)
        manifest["mode"] = "execute"
        manifest["frozen_manifest_path"] = str(args.manifest)
        return manifest
    return selector.build_eval_harness(
        mode=args.mode,
        budget=args.budget,
        profile=args.profile,
        plan=args.plan,
        since=args.since,
        changed_files=selector._split_csv_values(args.changed_file),
        agent_engine=selector._split_csv(args.agent_engine),
        provider_profile=selector._split_csv(args.provider_profile),
        intent=selector._split_csv(args.intent),
        preset=selector._split_csv(args.preset),
        evidence_lane=selector._split_csv(args.evidence_lane),
        camera_labeler=selector._split_csv(args.camera_labeler),
        output_dir=args.output_dir,
    )


def _load_frozen_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_required_json_object(path, label="eval harness manifest")
    if manifest.get("schema") != "roboclaws_eval_harness_manifest_v1":
        raise ValueError(f"{path} is not an eval harness manifest")
    if not isinstance(manifest.get("rows"), list):
        raise ValueError(f"{path} eval harness manifest must contain a rows list")
    if not manifest.get("output_dir"):
        raise ValueError(f"{path} eval harness manifest must define output_dir")
    return manifest


def _execute_harness(
    manifest: dict[str, Any],
    *,
    row_ids: list[str] | tuple[str, ...] = (),
    max_parallel: int = 1,
    shard_id: str = "local-main",
) -> None:
    try:
        local_execution.execute_local_rows(
            manifest,
            run_row=_run_row,
            row_blockers=_row_blockers,
            write_row_result=_write_row_result,
            row_ids=row_ids,
            max_parallel=max_parallel,
            shard_id=shard_id,
        )
    finally:
        _stop_managed_dino_sidecars()


def _row_blockers(row: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    requirements = row.get("requires") or []
    for requirement in sorted(
        requirements,
        key=lambda item: ROW_BLOCKER_REQUIREMENT_PRIORITY.get(str(item), 100),
    ):
        blocker = _requirement_blocker(
            str(requirement),
            row=row,
            manifest=manifest,
            prior_blockers=blockers,
        )
        if blocker:
            blockers.append(blocker)
    return blockers


def _requirement_blocker(
    requirement: str,
    *,
    row: dict[str, Any],
    manifest: dict[str, Any],
    prior_blockers: list[dict[str, str]],
) -> dict[str, str] | None:
    axes = row.get("axes") or {}
    if requirement == "just" and shutil.which("just") is None:
        return _environment_blocker("just is not on PATH")
    if requirement == "python_env" and not (REPO_ROOT / ".venv" / "bin" / "python").exists():
        return _environment_blocker(".venv/bin/python is missing")
    if requirement == "docker" and shutil.which("docker") is None:
        return _environment_blocker("docker is not on PATH")
    if requirement == "codex_provider":
        return _provider_requirement_blocker(axes)
    if requirement == "openai_agents_package" and not _has_module("agents"):
        return _environment_blocker("openai-agents package is not installed")
    if requirement == "dino_sidecar" and not prior_blockers and not _ensure_dino_sidecar(manifest):
        return _environment_blocker("Grounding DINO visual-grounding sidecar is not reachable")
    if requirement == "runtime_map_prior" and not _runtime_prior_available(manifest):
        return _environment_blocker(
            "map-build prior artifact is required before cleanup consumer row"
        )
    return None


def _environment_blocker(detail: str) -> dict[str, str]:
    return {"category": "environment_blocked", "detail": detail}


def _run_row(row: dict[str, Any], manifest: dict[str, Any]) -> None:
    for key in ("blocker_category", "blockers", "failure_class", "failure_detail"):
        row.pop(key, None)
    row_dir = Path(row["row_dir"])
    row_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = row_dir / "stdout.log"
    stderr_path = row_dir / "stderr.log"
    command = _resolve_row_command(row, manifest)
    env = _row_environment(row)
    timeout_s = float(row.get("timeout_s") or 0) or None
    returncode, stdout, stderr, timed_out = local_execution.run_local_command(
        command,
        cwd=REPO_ROOT,
        env=env,
        timeout_s=timeout_s,
    )
    if timed_out:
        row["status"] = "ran"
        row["exit_code"] = 124
        row["outcome"] = "failed"
        row["failure_class"] = "harness_row_timeout"
        row["failure_detail"] = f"row exceeded timeout_s={timeout_s:g}"
    else:
        row["status"] = "ran"
        row["exit_code"] = returncode
        row["outcome"] = "passed" if returncode == 0 else "failed"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    row["output_artifacts"] = [
        _display_path(stdout_path),
        _display_path(stderr_path),
    ]
    _attach_eval_outputs(row)
    _classify_eval_result_row(row)
    _classify_failed_row(row, stderr=stderr, stdout=stdout)


def _row_environment(row: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    if _should_default_provider_timing_proxy(row) and PROVIDER_TIMING_PROXY_ENV not in env:
        env[PROVIDER_TIMING_PROXY_ENV] = "1"
        row["defaulted_provider_timing_proxy"] = True
    port = _live_row_mcp_port(row)
    if port:
        env[EVAL_HARNESS_MCP_PORT_ENV] = port
        if _command_uses_session_live(row):
            env[SESSION_LIVE_MCP_PORT_ENV] = port
        row["mcp_port"] = port
    return env


def _should_default_provider_timing_proxy(row: dict[str, Any]) -> bool:
    return False


def _live_row_mcp_port(row: dict[str, Any]) -> str:
    if str(row.get("row_kind") or "") != "live_agent_eval":
        return ""
    row_id = str(row.get("row_id") or "")
    if not row_id:
        return ""
    return str(19000 + (_stable_row_port_offset(row_id) % 1000))


def _stable_row_port_offset(row_id: str) -> int:
    total = 0
    for index, char in enumerate(row_id):
        total += (index + 1) * ord(char)
    return total


def _command_uses_session_live(row: dict[str, Any]) -> bool:
    return any(str(item) == "session-live" for item in row.get("command") or [])


def _resolve_row_command(row: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    command = [_resolve_row_argument(str(item), manifest) for item in row["command"]]
    if _command_uses_surface_run(row, command):
        command.append(f"port={_live_row_mcp_port(row)}")
    row["resolved_command"] = command
    row["resolved_command_display"] = " ".join(command)
    return command


def _command_uses_surface_run(row: dict[str, Any], command: list[str]) -> bool:
    return bool(_live_row_mcp_port(row)) and any(str(item) == "run::surface" for item in command)


def _resolve_row_argument(argument: str, manifest: dict[str, Any]) -> str:
    return re.sub(
        r"\$\{([^}:]+):([^}]+)\}",
        lambda match: str(_row_artifact_path(manifest, match.group(1), match.group(2))),
        argument,
    )


def _row_artifact_path(manifest: dict[str, Any], row_id: str, artifact_name: str) -> Path:
    run_dir = _row_run_dir(manifest, row_id)
    matches = sorted(run_dir.glob(f"**/{artifact_name}"))
    if not matches:
        raise FileNotFoundError(f"{row_id} did not produce {artifact_name} under {run_dir}")
    return matches[-1]


def _row_run_dir(manifest: dict[str, Any], row_id: str) -> Path:
    for row in manifest.get("rows") or []:
        if row.get("row_id") == row_id:
            return Path(row["row_dir"]) / "run"
    raise KeyError(f"unknown eval-harness row id: {row_id}")


def _classify_failed_row(row: dict[str, Any], *, stderr: str, stdout: str) -> None:
    if row.get("exit_code") == 0:
        return
    combined = f"{stderr}\n{stdout}".lower()
    if (
        "another interactive codex molmo cleanup session appears to be active" in combined
        or ("requested mcp port" in combined and "is already accepting connections" in combined)
        or "no molmospaces visual backend slot is available" in combined
        or "visual grounding sidecar is not ready for product runs" in combined
        or "visual grounding service timed out" in combined
        or "visual grounding connection error" in combined
        or "visual grounding adapter unavailable" in combined
    ):
        row["status"] = "blocked"
        row["outcome"] = "blocked"
        row["blocker_category"] = "environment_blocked"
        row["blockers"] = [
            _environment_blocker(
                "required local runtime, visual-grounding service, or visual slot is unavailable"
            )
        ]
    elif any(
        marker in combined
        for marker in (
            "model_or_provider_unavailable",
            "provider 502",
            "provider 429",
            "bad gateway",
            "rate limit",
            "model service",
            "missing provider env",
            "missing_provider_key",
        )
    ):
        row["status"] = "blocked"
        row["outcome"] = "blocked"
        row["blocker_category"] = "model_or_provider_unavailable"
        row["blockers"] = [
            {
                "category": "model_or_provider_unavailable",
                "detail": "provider, key, rate-limit, or model service failure",
            }
        ]


def _append_output_artifacts(row: dict[str, Any], *paths: Path) -> None:
    artifacts = list(row.get("output_artifacts") or [])
    for path in paths:
        if path.is_file():
            display = _display_path(path)
            if display not in artifacts:
                artifacts.append(display)
    row["output_artifacts"] = artifacts


def _attach_eval_outputs(row: dict[str, Any]) -> None:
    if row.get("row_kind") not in {"eval_suite", "live_agent_eval"}:
        return
    for item in row.get("command") or []:
        if not str(item).startswith("output_dir="):
            continue
        output_root = Path(str(item).split("=", 1)[1])
        stamp = _command_value(row, "stamp")
        if stamp:
            matches = sorted(output_root.glob(f"*/{stamp}"))
            if matches:
                artifacts = list(row.get("output_artifacts") or [])
                for path in (matches[-1] / "eval_results.json", matches[-1] / "eval_report.html"):
                    if path.exists():
                        artifacts.append(_display_path(path))
                row["output_artifacts"] = artifacts


def _classify_eval_result_row(row: dict[str, Any]) -> None:
    if row.get("row_kind") not in {"eval_suite", "live_agent_eval"}:
        return
    result_paths = [
        REPO_ROOT / str(path)
        for path in row.get("output_artifacts") or []
        if str(path).endswith("eval_results.json")
    ]
    if not result_paths:
        return
    try:
        payload = _load_required_json_object(result_paths[-1], label="eval_results.json")
    except ValueError as exc:
        row["outcome"] = "failed"
        row["failure_class"] = "harness_bug_unclassified"
        row["eval_results_error"] = str(exc)
        return
    aggregate = payload.get("aggregate") if isinstance(payload.get("aggregate"), dict) else {}
    failed = int(aggregate.get("failed") or 0)
    blocked = int(aggregate.get("blocked") or 0)
    total = int(aggregate.get("total") or 0)
    row["eval_aggregate"] = {
        "total": total,
        "passed": int(aggregate.get("passed") or 0),
        "failed": failed,
        "blocked": blocked,
        "failure_classes": aggregate.get("failure_classes") or {},
    }
    if failed:
        row["outcome"] = "failed"
        row["failure_class"] = _first_failure_class(aggregate)
    elif blocked:
        row["status"] = "blocked"
        row["outcome"] = "blocked"
        row["blocker_category"] = _first_failure_class(aggregate) or "environment_blocked"


def _load_required_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        return read_json_object(path, label=label)
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc


def _first_failure_class(aggregate: dict[str, Any]) -> str:
    failure_classes = aggregate.get("failure_classes")
    if isinstance(failure_classes, dict) and failure_classes:
        return str(next(iter(failure_classes)))
    return ""


def _command_value(row: dict[str, Any], key: str) -> str:
    prefix = f"{key}="
    for item in row.get("command") or []:
        text = str(item)
        if text.startswith(prefix):
            return text.split("=", 1)[1]
    return ""


def _provider_requirement_blocker(axes: dict[str, Any]) -> dict[str, str] | None:
    from roboclaws.agents.provider_registry import provider_readiness

    readiness = provider_readiness(
        agent_engine=str(axes.get("agent_engine") or ""),
        provider_profile=str(axes.get("provider_profile") or "") or None,
    )
    if readiness.get("ok"):
        return None
    return {
        "category": "model_or_provider_unavailable",
        "detail": _provider_readiness_message(readiness),
    }


def _provider_readiness_message(readiness: dict[str, Any]) -> str:
    message = str(readiness.get("message") or "").strip()
    if message:
        return message
    missing = [str(item) for item in readiness.get("missing_env") or []]
    if missing:
        return (
            f"{readiness.get('provider_profile') or readiness.get('provider')} "
            f"requires {', '.join(missing)}"
        )
    return (
        f"provider_profile {readiness.get('provider_profile') or readiness.get('provider')!r} "
        f"is not ready for agent_engine {readiness.get('agent_engine')!r}"
    )


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _dino_sidecar_available() -> bool:
    base_url = _visual_grounding_base_url()
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _ensure_dino_sidecar(manifest: dict[str, Any]) -> bool:
    if _dino_sidecar_available():
        return True
    if not _dino_sidecar_autostart_enabled():
        return False
    return _start_managed_dino_sidecar(manifest)


def _visual_grounding_base_url() -> str:
    return os.environ.get("VISUAL_GROUNDING_BASE_URL", DEFAULT_VISUAL_GROUNDING_BASE_URL)


def _dino_sidecar_autostart_enabled() -> bool:
    value = os.environ.get(DINO_SIDECAR_AUTOSTART_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _start_managed_dino_sidecar(manifest: dict[str, Any]) -> bool:
    base_url = _visual_grounding_base_url()
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme not in {"", "http"} or host not in {"127.0.0.1", "localhost", "::1"}:
        return False

    python_bin, sidecar_args = _dino_sidecar_start_command(host=host, port=port)
    if not python_bin.exists():
        return False

    sidecar_dir = Path(manifest["output_dir"]) / "sidecars" / "visual-grounding"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    stdout = (sidecar_dir / "stdout.log").open("a", encoding="utf-8")
    stderr = (sidecar_dir / "stderr.log").open("a", encoding="utf-8")
    command = [str(python_bin), *sidecar_args]
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=stdout,
        stderr=stderr,
        text=True,
        env=os.environ.copy(),
    )
    _MANAGED_DINO_SIDECARS.append(
        {"process": process, "stdout": stdout, "stderr": stderr, "base_url": base_url}
    )
    manifest["dino_sidecar_autostart"] = {
        "base_url": base_url,
        "command": command,
        "stdout": _display_path(sidecar_dir / "stdout.log"),
        "stderr": _display_path(sidecar_dir / "stderr.log"),
    }
    return _wait_for_dino_sidecar(process, timeout_s=DINO_SIDECAR_STARTUP_TIMEOUT_S)


def _dino_sidecar_start_command(*, host: str, port: int) -> tuple[Path, list[str]]:
    dedicated_python = REPO_ROOT / ".venv-visual-grounding" / "bin" / "python"
    script = "scripts/visual_grounding/serve_visual_grounding_service.py"
    if dedicated_python.exists():
        return dedicated_python, [
            script,
            "--host",
            host,
            "--port",
            str(port),
            "--pipeline",
            "real-router",
            "--adapter-mode",
            "real",
        ]
    return REPO_ROOT / ".venv" / "bin" / "python", [
        script,
        "--host",
        host,
        "--port",
        str(port),
        "--pipeline",
        "grounding-dino",
    ]


def _wait_for_dino_sidecar(process: subprocess.Popen[Any], *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() <= deadline:
        if _dino_sidecar_available():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def _stop_managed_dino_sidecars() -> None:
    while _MANAGED_DINO_SIDECARS:
        managed = _MANAGED_DINO_SIDECARS.pop()
        try:
            process = managed["process"]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)
        finally:
            managed["stdout"].close()
            managed["stderr"].close()


def _runtime_prior_available(manifest: dict[str, Any]) -> bool:
    for row in manifest.get("rows") or []:
        if row.get("row_id") != RUNTIME_MAP_PRIOR_SOURCE_ROW_ID:
            continue
        if row.get("status") != "ran" or row.get("outcome") != "passed":
            return False
        run_dir = Path(row["row_dir"]) / "run"
        return any(run_dir.glob("**/runtime_metric_map.json"))
    return False


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _write_outputs(manifest: dict[str, Any], output_dir: Path) -> None:
    json_path = output_dir / "eval_harness.json"
    md_path = output_dir / "eval_harness.md"
    html_path = output_dir / "eval_harness.html"
    json_path.write_text(
        json.dumps(_redacted_manifest(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(manifest), encoding="utf-8")
    html_path.write_text(_render_html(manifest), encoding="utf-8")


def _write_row_result(row: dict[str, Any]) -> None:
    row_dir = Path(row["row_dir"])
    row_dir.mkdir(parents=True, exist_ok=True)
    result_path = row_dir / "row_result.json"
    artifacts = list(row.get("output_artifacts") or [])
    result_display_path = _display_path(result_path)
    if result_display_path not in artifacts:
        artifacts.append(result_display_path)
    row["output_artifacts"] = artifacts
    result_path.write_text(
        json.dumps(_redacted_manifest(row), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _redacted_manifest(value: Any) -> Any:
    private_keys = {
        "private_goal_reference",
        "private_evaluation",
        "private_manifest",
        "generated_mess_set",
        "acceptable_destinations",
        "hidden_targets",
        "raw_provider_logs",
    }
    if isinstance(value, dict):
        return {
            key: _redacted_manifest(child)
            for key, child in value.items()
            if str(key) not in private_keys
        }
    if isinstance(value, list):
        return [_redacted_manifest(item) for item in value]
    return value


def _render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Eval Harness",
        "",
        f"- Mode: `{manifest['mode']}`",
        f"- Budget: `{manifest['budget']}`",
        f"- Profile: `{manifest.get('profile', 'adaptive')}`",
        f"- Selected rows: `{manifest['summary']['selected_row_count']}`",
        "",
        "## Signals",
        "",
    ]
    if manifest.get("signals"):
        for signal in manifest["signals"]:
            files = ", ".join(signal.get("matched_files") or [])
            patterns = ", ".join(signal.get("matched_patterns") or [])
            detail = files or patterns or signal.get("source", "")
            lines.append(f"- `{signal['id']}`: {detail}")
    else:
        lines.append("- none")
    lines.extend(["", "## Rows", ""])
    for row in manifest["rows"]:
        selected = "selected" if row.get("selected") else "skipped"
        lines.append(f"### {row['row_id']}")
        lines.append("")
        lines.append(f"- Kind: `{row['row_kind']}`")
        lines.append(f"- Status: `{row['status']}`")
        if row.get("outcome"):
            lines.append(f"- Outcome: `{row['outcome']}`")
        if row.get("failure_class"):
            lines.append(f"- Failure class: `{row['failure_class']}`")
        lines.append(f"- Selection: `{selected}`")
        if row.get("blocker_category"):
            lines.append(f"- Blocker: `{row['blocker_category']}`")
        if row.get("reason_selected"):
            lines.append(f"- Rationale: {row['reason_selected']}")
        if row.get("skip_reason"):
            lines.append(f"- Skip reason: {row['skip_reason']}")
        if row.get("output_artifacts"):
            artifacts = ", ".join(str(item) for item in row["output_artifacts"])
            lines.append(f"- Artifacts: {artifacts}")
        lines.append(f"- Command: `{row['command_display']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_html(manifest: dict[str, Any]) -> str:
    rows = []
    for row in manifest["rows"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(row['row_id'])}</td>"
            f"<td>{html.escape(row['row_kind'])}</td>"
            f"<td>{html.escape(str(row['status']))}</td>"
            f"<td>{html.escape(str(row.get('outcome') or ''))}</td>"
            f"<td>{html.escape(str(row.get('failure_class') or ''))}</td>"
            f"<td>{html.escape(str(row.get('blocker_category') or ''))}</td>"
            f"<td><code>{html.escape(row['command_display'])}</code></td>"
            "</tr>"
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Eval Harness</title>"
        "<style>body{font-family:sans-serif;margin:24px;}"
        "table{border-collapse:collapse;width:100%;}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top;}"
        "code{white-space:pre-wrap;}</style></head><body>"
        "<h1>Eval Harness</h1>"
        f"<p>Mode: <code>{html.escape(manifest['mode'])}</code> "
        f"Budget: <code>{html.escape(manifest['budget'])}</code> "
        f"Profile: <code>{html.escape(str(manifest.get('profile', 'adaptive')))}</code></p>"
        "<table><thead><tr><th>Row</th><th>Kind</th><th>Status</th>"
        "<th>Outcome</th><th>Failure class</th><th>Blocker</th>"
        "<th>Command</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></body></html>\n"
    )


def _exit_status(manifest: dict[str, Any], *, row_ids: list[str] | tuple[str, ...] = ()) -> int:
    requested = {str(row_id) for row_id in row_ids}

    def in_scope(row: dict[str, Any]) -> bool:
        return str(row.get("row_id")) in requested if requested else bool(row.get("selected"))

    blocked = [
        row
        for row in manifest["rows"]
        if in_scope(row)
        and row.get("status") == "blocked"
        and row.get("requirement", "required") == "required"
    ]
    failed = [
        row
        for row in manifest["rows"]
        if in_scope(row)
        and row.get("requirement", "required") == "required"
        and row.get("status") == "ran"
        and (row.get("exit_code") or row.get("outcome") == "failed")
    ]
    if failed:
        return 1
    if blocked:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
