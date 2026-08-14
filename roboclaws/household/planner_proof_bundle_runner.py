#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object as read_source_json_object  # noqa: E402
from roboclaws.household import planner_proof_selection, report_planner  # noqa: E402
from roboclaws.household.planner_proof_contracts import PLANNER_PROOF_REQUESTS_SCHEMA  # noqa: E402
from roboclaws.household.planner_proof_prior_sources import (  # noqa: E402
    _load_prior_proof_result_summary,
)
from roboclaws.household.planner_proof_requests import (  # noqa: E402
    build_cleanup_rerun_command,
    build_probe_commands,
    build_probe_warmup_command,
    proof_bundle_run_manifest,
    proof_execution_horizon,
)
from roboclaws.household.subprocess_backend import DEFAULT_MOLMOSPACES_PYTHON  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBE_SCRIPT = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_planner_manipulation_probe.py"
)
DEFAULT_CLEANUP_SCRIPT = REPO_ROOT / "examples/molmo_cleanup/molmospaces_realworld_cleanup.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or run bound planner proof bundle commands from a cleanup artifact."
    )
    parser.add_argument("cleanup_run_result", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runner-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--probe-script", type=Path, default=DEFAULT_PROBE_SCRIPT)
    parser.add_argument("--cleanup-script", type=Path, default=DEFAULT_CLEANUP_SCRIPT)
    parser.add_argument("--molmospaces-python", type=Path, default=DEFAULT_MOLMOSPACES_PYTHON)
    parser.add_argument("--molmospaces-root", type=Path)
    parser.add_argument("--embodiment", choices=("franka", "rby1m"), default="rby1m")
    parser.add_argument("--probe-mode", choices=("config_import", "execute"), default="execute")
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--renderer-device-id", type=int, default=0)
    parser.add_argument("--torch-extensions-dir", type=Path)
    parser.add_argument(
        "--rby1m-curobo-memory-profile",
        choices=("none", "low"),
        default="low",
    )
    parser.add_argument(
        "--task-sampler-robot-placement-profile",
        choices=("none", "relaxed", "wide"),
        default="none",
    )
    parser.add_argument("--execute-probes", action="store_true")
    parser.add_argument(
        "--warmup-rby1m-curobo",
        action="store_true",
        help="Run a visible config-import warmup before proof commands.",
    )
    parser.add_argument("--rerun-cleanup", action="store_true")
    parser.add_argument("--cleanup-output-dir", type=Path)
    parser.add_argument("--prior-proof-bundle-manifest", type=Path, action="append")
    parser.add_argument("--prior-planner-probe-run-result", type=Path, action="append")
    parser.add_argument("--exclude-task-feasibility-blocked", action="store_true")
    parser.add_argument(
        "--request-id",
        dest="request_ids",
        action="append",
        help="Limit proof-bundle command generation to the named request id. Repeatable.",
    )
    parser.add_argument(
        "--exclude-prior-covered",
        action="store_true",
        help=(
            "Exclude requests that already have prior planner-backed proof with "
            "cleanup binding promoted."
        ),
    )
    parser.add_argument(
        "--prior-covered-min-proof-steps",
        type=int,
        default=1,
        help=(
            "Minimum executed proof steps required before a prior planner-backed "
            "cleanup binding counts as covered."
        ),
    )
    parser.add_argument("--generate-fallback-requests", action="store_true")
    parser.add_argument("--fallback-alias-limit", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_from_cleanup_result(
        cleanup_run_result=args.cleanup_run_result,
        output_dir=args.output_dir,
        runner_python=args.runner_python,
        probe_script=args.probe_script,
        cleanup_script=args.cleanup_script,
        molmospaces_python=args.molmospaces_python,
        molmospaces_root=args.molmospaces_root,
        embodiment=args.embodiment,
        probe_mode=args.probe_mode,
        steps=args.steps,
        timeout_s=args.timeout_s,
        renderer_device_id=args.renderer_device_id,
        torch_extensions_dir=args.torch_extensions_dir,
        rby1m_curobo_memory_profile=args.rby1m_curobo_memory_profile,
        task_sampler_robot_placement_profile=args.task_sampler_robot_placement_profile,
        execute_probes=args.execute_probes,
        warmup_rby1m_curobo=args.warmup_rby1m_curobo,
        rerun_cleanup=args.rerun_cleanup,
        cleanup_output_dir=args.cleanup_output_dir,
        prior_proof_bundle_manifest=args.prior_proof_bundle_manifest,
        prior_planner_probe_run_result=args.prior_planner_probe_run_result,
        request_ids=args.request_ids,
        exclude_task_feasibility_blocked=args.exclude_task_feasibility_blocked,
        exclude_prior_covered=args.exclude_prior_covered,
        prior_covered_min_proof_steps=args.prior_covered_min_proof_steps,
        generate_fallback_requests=args.generate_fallback_requests,
        fallback_alias_limit=args.fallback_alias_limit,
    )
    print(
        json.dumps(
            {
                "manifest": str(result["manifest_path"]),
                "report": str(result["report_path"]),
                "status": result["status"],
            }
        )
    )


def run_from_cleanup_result(
    *,
    cleanup_run_result: Path,
    output_dir: Path,
    runner_python: Path,
    probe_script: Path,
    cleanup_script: Path,
    molmospaces_python: Path | None,
    molmospaces_root: Path | None,
    embodiment: str,
    probe_mode: str,
    steps: int,
    timeout_s: float,
    renderer_device_id: int,
    torch_extensions_dir: Path | None,
    rby1m_curobo_memory_profile: str,
    task_sampler_robot_placement_profile: str = "none",
    execute_probes: bool = False,
    warmup_rby1m_curobo: bool = False,
    rerun_cleanup: bool = False,
    cleanup_output_dir: Path | None = None,
    prior_proof_bundle_manifest: Path | Sequence[Path] | None = None,
    prior_planner_probe_run_result: Path | Sequence[Path] | None = None,
    request_ids: Sequence[str] | None = None,
    exclude_task_feasibility_blocked: bool = False,
    exclude_prior_covered: bool = False,
    prior_covered_min_proof_steps: int = 1,
    generate_fallback_requests: bool = False,
    fallback_alias_limit: int = 4,
) -> dict[str, Any]:
    cleanup_run_result = cleanup_run_result.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_run = read_source_json_object(cleanup_run_result, label="cleanup run result")
    requests = _load_proof_requests(source_run, cleanup_run_result.parent)
    prior_summary = _load_prior_proof_result_summary(
        prior_proof_bundle_manifest,
        prior_planner_probe_run_result,
    )
    proof_request_selection = planner_proof_selection.proof_request_selection_from_summary(
        requests,
        prior_proof_result_summary=prior_summary,
        include_request_ids=request_ids,
        exclude_task_feasibility_blocked=exclude_task_feasibility_blocked,
        exclude_prior_covered=exclude_prior_covered,
        prior_covered_min_proof_steps=prior_covered_min_proof_steps,
        generate_fallback_requests=generate_fallback_requests,
        fallback_alias_limit=fallback_alias_limit,
    )
    effective_torch_extensions_dir = _effective_torch_extensions_dir(
        output_dir=output_dir,
        torch_extensions_dir=torch_extensions_dir,
        warmup_rby1m_curobo=warmup_rby1m_curobo,
    )
    warmup = (
        build_probe_warmup_command(
            output_dir=output_dir,
            runner_python=runner_python,
            probe_script=probe_script,
            molmospaces_python=molmospaces_python,
            molmospaces_root=molmospaces_root,
            embodiment=embodiment,
            timeout_s=timeout_s,
            renderer_device_id=renderer_device_id,
            torch_extensions_dir=effective_torch_extensions_dir,
            rby1m_curobo_memory_profile=rby1m_curobo_memory_profile,
        )
        if warmup_rby1m_curobo
        else {}
    )
    commands = build_probe_commands(
        manifest=requests,
        output_dir=output_dir,
        runner_python=runner_python,
        probe_script=probe_script,
        molmospaces_python=molmospaces_python,
        molmospaces_root=molmospaces_root,
        embodiment=embodiment,
        probe_mode=probe_mode,
        steps=steps,
        timeout_s=timeout_s,
        renderer_device_id=renderer_device_id,
        torch_extensions_dir=effective_torch_extensions_dir,
        rby1m_curobo_memory_profile=rby1m_curobo_memory_profile,
        task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
        request_selection=proof_request_selection,
    )
    requested_horizon = proof_execution_horizon(
        command_steps=steps,
        prior_covered_min_proof_steps=prior_covered_min_proof_steps,
    )
    local_runtime_preflight = _local_runtime_preflight(
        molmospaces_python=molmospaces_python,
        execute_requested=execute_probes,
    )
    proof_results: list[Path] = []
    status = "dry_run"
    if execute_probes:
        if _local_runtime_preflight_blocked(local_runtime_preflight):
            status = "local_runtime_blocked"
        else:
            status = "probes_executed"
            if warmup:
                _run_command(warmup["command"])
            for item in commands:
                _run_command(item["command"])
                proof_results.append(Path(item["run_result"]))
    cleanup_command: list[str] = []
    cleanup_rerun: dict[str, Any] = {}
    if rerun_cleanup:
        if not execute_probes:
            raise ValueError("--rerun-cleanup requires --execute-probes")
        if status == "local_runtime_blocked":
            cleanup_rerun = {}
        else:
            cleanup_output = cleanup_output_dir or output_dir / "cleanup_with_planner_proof_bundle"
            cleanup_command = build_cleanup_rerun_command(
                runner_python=runner_python,
                cleanup_script=cleanup_script,
                cleanup_output_dir=cleanup_output,
                source_run_result=source_run,
                proof_run_results=proof_results,
            )
            _run_command(cleanup_command)
            status = "cleanup_rerun"
            cleanup_rerun = {
                "output_dir": str(cleanup_output),
                "run_result": str(cleanup_output / "run_result.json"),
                "report": str(cleanup_output / "report.html"),
            }
    manifest = proof_bundle_run_manifest(
        cleanup_run_result=cleanup_run_result,
        output_dir=output_dir,
        proof_requests=requests,
        commands=commands,
        warmup=warmup,
        local_runtime_preflight=local_runtime_preflight,
        proof_execution_horizon=requested_horizon,
        proof_request_selection=proof_request_selection,
        prior_proof_result_summary=prior_summary,
        cleanup_command=cleanup_command,
        cleanup_rerun=cleanup_rerun,
        molmospaces_python=molmospaces_python,
        molmospaces_root=molmospaces_root,
    )
    manifest["status"] = status
    report_path = output_dir / "report.html"
    manifest["report"] = str(report_path)
    manifest_path = output_dir / "proof_bundle_run_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = report_planner.render_planner_proof_bundle_runner_report(
        output_dir=output_dir,
        manifest=manifest,
    )
    return {
        "status": status,
        "manifest_path": manifest_path,
        "report_path": report_path,
        "manifest": manifest,
    }


def _local_runtime_preflight(
    *,
    molmospaces_python: Path | None,
    execute_requested: bool,
) -> dict[str, Any]:
    if not execute_requested:
        return {}
    preflight: dict[str, Any] = {
        "schema": "planner_proof_bundle_local_runtime_preflight_v1",
        "requested": True,
        "status": "not_checked",
        "python_executable": str(molmospaces_python or ""),
        "checks": [],
        "blockers": [],
        "evidence_note": (
            "Local-dev runtime preflight for real proof execution. A blocked "
            "preflight prevents proof commands from running and keeps the report "
            "reviewable."
        ),
    }
    if molmospaces_python is None:
        preflight["checks"].append(
            {
                "name": "molmospaces_python",
                "status": "not_checked",
                "message": "No separate MolmoSpaces Python runtime configured.",
            }
        )
        return preflight
    if not molmospaces_python.is_file():
        blocker = {
            "code": "molmospaces_python_missing",
            "message": f"MolmoSpaces Python executable is missing: {molmospaces_python}",
        }
        preflight["status"] = "blocked"
        preflight["blockers"].append(blocker)
        preflight["checks"].append({"name": "python_executable", "status": "blocked", **blocker})
        return preflight
    command = [
        str(molmospaces_python),
        "-c",
        "import molmo_spaces; print('molmo_spaces import ok')",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except subprocess.TimeoutExpired as exc:
        preflight["status"] = "blocked"
        blocker = {
            "code": "molmo_spaces_import_timeout",
            "message": "MolmoSpaces package import preflight exceeded 30 seconds.",
        }
        preflight["blockers"].append(blocker)
        preflight["checks"].append(
            {
                "name": "molmo_spaces_import",
                "command": command,
                "status": "blocked",
                "returncode": "",
                "stdout": str(exc.stdout or "").strip(),
                "stderr": str(exc.stderr or "").strip(),
                **blocker,
            }
        )
        return preflight
    check = {
        "name": "molmo_spaces_import",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    if completed.returncode == 0:
        preflight["status"] = "ready"
        check["status"] = "ready"
    else:
        preflight["status"] = "blocked"
        blocker = {
            "code": "molmo_spaces_import_failed",
            "message": completed.stderr.strip() or completed.stdout.strip() or "import failed",
        }
        preflight["blockers"].append(blocker)
        check.update({"status": "blocked", **blocker})
    preflight["checks"].append(check)
    return preflight


def _local_runtime_preflight_blocked(preflight: dict[str, Any]) -> bool:
    return str(preflight.get("status") or "") == "blocked"


def _load_proof_requests(source_run: dict[str, Any], base: Path) -> dict[str, Any]:
    if "planner_proof_requests" in source_run:
        inline = source_run.get("planner_proof_requests")
        if not isinstance(inline, dict):
            source_path = base / "run_result.json"
            raise ValueError(
                f"inline planner proof requests must contain a JSON object: {source_path}"
            )
        if inline.get("schema") != PLANNER_PROOF_REQUESTS_SCHEMA:
            raise ValueError(
                f"inline planner proof requests use unsupported schema: {base / 'run_result.json'}"
            )
        return _with_source_planner_scene(inline, source_run)
    if "artifacts" not in source_run:
        artifacts: dict[str, Any] = {}
    elif not isinstance(source_run["artifacts"], dict):
        raise ValueError(
            f"cleanup run result artifacts must contain a JSON object: {base / 'run_result.json'}"
        )
    else:
        artifacts = source_run["artifacts"]
    declared_request_path = _declared_planner_proof_request_path(artifacts, base)
    request_path = _resolve_path(base, declared_request_path)
    if request_path.is_file():
        data = read_source_json_object(request_path, label="planner proof requests")
        if data.get("schema") != PLANNER_PROOF_REQUESTS_SCHEMA:
            raise ValueError(f"planner proof requests use unsupported schema: {request_path}")
        return _with_source_planner_scene(data, source_run)
    if declared_request_path:
        raise FileNotFoundError(f"planner proof requests artifact is missing: {request_path}")
    raise ValueError("cleanup run_result does not include planner proof requests")


def _declared_planner_proof_request_path(artifacts: dict[str, Any], base: Path) -> str:
    if "planner_proof_requests" not in artifacts:
        return ""
    declared_request_source = artifacts["planner_proof_requests"]
    if not isinstance(declared_request_source, str) or not declared_request_source.strip():
        raise ValueError(
            "planner proof requests artifact path must be a non-empty string: "
            f"{base / 'run_result.json'}"
        )
    return declared_request_source.strip()


def _with_source_planner_scene(
    requests: dict[str, Any],
    source_run: dict[str, Any],
) -> dict[str, Any]:
    planner_scene = requests.get("planner_scene") or {}
    if planner_scene.get("scene_xml"):
        return requests
    runtime = source_run.get("molmospaces_runtime") or {}
    scene_xml = str(runtime.get("scene_xml") or "")
    if not scene_xml:
        return requests
    enriched = dict(requests)
    enriched["planner_scene"] = {
        "schema": "planner_cleanup_proof_scene_v1",
        "available": True,
        "scene_xml": scene_xml,
        "backend": str(source_run.get("backend") or ""),
        "evidence_note": (
            "Real MolmoSpaces cleanup scene inferred from source run_result for "
            "backward-compatible proof-bundle command generation."
        ),
    }
    return enriched


def _effective_torch_extensions_dir(
    *,
    output_dir: Path,
    torch_extensions_dir: Path | None,
    warmup_rby1m_curobo: bool,
) -> Path | None:
    if torch_extensions_dir is not None:
        return torch_extensions_dir
    if warmup_rby1m_curobo:
        return output_dir / "torch_extensions"
    return None


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True, cwd=REPO_ROOT)


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    repo_path = REPO_ROOT / path
    if repo_path.exists():
        return repo_path
    return base / path


if __name__ == "__main__":
    main()
