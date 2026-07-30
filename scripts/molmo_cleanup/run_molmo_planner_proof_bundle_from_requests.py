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
from roboclaws.household import report_planner  # noqa: E402
from roboclaws.household.planner_proof_requests import (  # noqa: E402
    PLANNER_PROOF_REQUESTS_SCHEMA,
    build_cleanup_rerun_command,
    build_probe_commands,
    build_probe_warmup_command,
    proof_bundle_run_manifest,
    proof_execution_horizon,
    proof_request_selection_from_summary,
    proof_result_summary_from_commands,
)
from roboclaws.household.planner_task_feasibility import (  # noqa: E402
    grasp_feasibility_signature_counts,
)
from roboclaws.household.subprocess_backend import DEFAULT_MOLMOSPACES_PYTHON  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBE_SCRIPT = (
    REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_planner_manipulation_probe.py"
)
DEFAULT_CLEANUP_SCRIPT = (
    REPO_ROOT / "examples" / "molmo_cleanup" / "molmospaces_realworld_cleanup.py"
)


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
    proof_request_selection = proof_request_selection_from_summary(
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


def _load_prior_proof_result_summary(
    manifest_paths: Path | Sequence[Path] | None,
    standalone_probe_run_results: Path | Sequence[Path] | None = None,
) -> dict[str, Any]:
    prior_manifest_paths = _prior_paths(manifest_paths)
    prior_probe_paths = _prior_paths(standalone_probe_run_results)
    if not prior_manifest_paths and not prior_probe_paths:
        return {}
    summaries = [
        *(_load_one_prior_proof_result_summary(path) for path in prior_manifest_paths),
        _load_standalone_probe_result_summary(prior_probe_paths),
    ]
    summaries = [summary for summary in summaries if summary]
    return _merge_prior_proof_result_summaries(summaries)


def _prior_paths(paths: Path | Sequence[Path] | None) -> list[Path]:
    if paths is None:
        return []
    if isinstance(paths, (str, Path)):
        return [Path(paths)]
    return [Path(item) for item in paths]


def _load_one_prior_proof_result_summary(path: Path) -> dict[str, Any]:
    manifest_path = path / "proof_bundle_run_manifest.json" if path.is_dir() else path
    data = read_source_json_object(manifest_path, label="prior proof bundle manifest")
    selection = data.get("proof_request_selection") or {}
    summaries = []
    nested_prior = data.get("prior_proof_result_summary")
    if isinstance(nested_prior, dict):
        summaries.append(dict(nested_prior))
    current = _prior_manifest_current_result_summary(data, selection)
    if current:
        summaries.append(current)
    if not summaries:
        return {}
    return _merge_prior_proof_result_summaries(summaries)


def _prior_manifest_current_result_summary(
    data: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    summary = data.get("proof_result_summary")
    current = dict(summary) if isinstance(summary, dict) else {}
    fallback_generation = selection.get("fallback_generation")
    if isinstance(fallback_generation, dict):
        current["fallback_generation"] = dict(fallback_generation)
    current["results"] = _merged_prior_results(
        current.get("results") or [],
        selection.get("excluded_requests") or [],
    )
    return current


def _load_standalone_probe_result_summary(run_result_paths: list[Path]) -> dict[str, Any]:
    if not run_result_paths:
        return {}
    commands = [
        _standalone_probe_command(run_result_path, index)
        for index, run_result_path in enumerate(run_result_paths, start=1)
    ]
    summary = proof_result_summary_from_commands(commands)
    summary["source_kind"] = "standalone_planner_probe_run_result"
    summary["evidence_note"] = (
        "Prior proof-result summary loaded directly from standalone planner-probe "
        "run_result artifacts. Selection still consumes the shared proof-result "
        "summary interface."
    )
    return summary


def _standalone_probe_command(run_result_path: Path, index: int) -> dict[str, Any]:
    data = read_source_json_object(
        run_result_path,
        label="standalone planner probe run result",
    )
    evidence = data.get("manipulation_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    requested_binding = evidence.get("requested_cleanup_primitive_binding")
    requested_binding = requested_binding if isinstance(requested_binding, dict) else {}
    cleanup_binding = evidence.get("cleanup_primitive_binding")
    cleanup_binding = cleanup_binding if isinstance(cleanup_binding, dict) else {}
    object_id = _first_nonempty_str(
        requested_binding.get("object_id"),
        cleanup_binding.get("object_id"),
        data.get("object_id"),
    )
    target_receptacle_id = _first_nonempty_str(
        requested_binding.get("target_receptacle_id"),
        cleanup_binding.get("target_receptacle_id"),
        data.get("target_receptacle_id"),
    )
    return {
        "request_id": _standalone_probe_request_id(
            data=data,
            evidence=evidence,
            requested_binding=requested_binding,
            run_result_path=run_result_path,
            object_id=object_id,
            target_receptacle_id=target_receptacle_id,
            index=index,
        ),
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "run_result": str(run_result_path),
        "report": str(_standalone_probe_report_path(run_result_path, data)),
    }


def _standalone_probe_request_id(
    *,
    data: dict[str, Any],
    evidence: dict[str, Any],
    requested_binding: dict[str, Any],
    run_result_path: Path,
    object_id: str,
    target_receptacle_id: str,
    index: int,
) -> str:
    explicit = _first_nonempty_str(
        data.get("request_id"),
        evidence.get("request_id"),
        requested_binding.get("request_id"),
    )
    if explicit:
        return explicit
    if object_id or target_receptacle_id:
        return (
            "standalone_"
            f"{_safe_id_part(object_id or 'object')}_to_"
            f"{_safe_id_part(target_receptacle_id or 'target')}"
        )
    parent = run_result_path.parent.name or run_result_path.stem
    return f"standalone_{index:03d}_{_safe_id_part(parent)}"


def _standalone_probe_report_path(run_result_path: Path, data: Any) -> Path:
    artifacts = data.get("artifacts") if isinstance(data, dict) else {}
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    value = str(artifacts.get("report") or "report.html")
    path = Path(value)
    if path.is_absolute():
        return path
    return run_result_path.parent / path


def _first_nonempty_str(*values: Any) -> str:
    for value in values:
        text = str(value or "")
        if text:
            return text
    return ""


def _safe_id_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)[:96]


def _merge_prior_proof_result_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    results_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    discovered_aliases: list[dict[str, Any]] = []
    filtered_aliases: list[dict[str, Any]] = []
    filtered_pairs: list[dict[str, Any]] = []
    normalized_aliases: list[dict[str, Any]] = []
    generated_requests: list[dict[str, Any]] = []
    for summary in summaries:
        for item in summary.get("results") or []:
            if not isinstance(item, dict):
                continue
            request_id = str(item.get("request_id") or "")
            if not request_id:
                continue
            key = _prior_result_merge_key(item)
            existing = results_by_key.get(key)
            candidate = dict(item)
            if existing is None or _prior_result_rank(candidate) >= _prior_result_rank(existing):
                results_by_key[key] = candidate
        fallback_generation = summary.get("fallback_generation") or {}
        if not isinstance(fallback_generation, dict):
            continue
        discovered_aliases.extend(_dict_items(fallback_generation.get("discovered_aliases")))
        filtered_aliases.extend(_dict_items(fallback_generation.get("filtered_aliases")))
        filtered_pairs.extend(_dict_items(fallback_generation.get("filtered_pairs")))
        normalized_aliases.extend(_dict_items(fallback_generation.get("normalized_aliases")))
        generated_requests.extend(_dict_items(fallback_generation.get("generated_requests")))
    fallback_generation = _merged_fallback_generation(
        discovered_aliases=discovered_aliases,
        filtered_aliases=filtered_aliases,
        filtered_pairs=filtered_pairs,
        normalized_aliases=normalized_aliases,
        generated_requests=generated_requests,
    )
    results = list(results_by_key.values())
    grasp_signature_counts = grasp_feasibility_signature_counts(results)
    return {
        "schema": "merged_prior_planner_proof_result_summary_v1",
        "result_count": len(results),
        "planner_backed_count": sum(1 for item in results if item.get("planner_backed")),
        "cleanup_binding_promoted_count": sum(
            1 for item in results if item.get("cleanup_binding_promoted")
        ),
        "execution_attempted_count": sum(1 for item in results if item.get("execution_attempted")),
        "task_feasibility_blocked_count": sum(
            1 for item in results if item.get("task_feasibility_status") == "blocked"
        ),
        "grasp_feasibility_blocked_count": sum(
            1
            for item in results
            if item.get("task_feasibility_blocker_kind") == "grasp_feasibility"
        ),
        "worker_stage_event_count": sum(
            int(item.get("worker_stage_event_count") or 0) for item in results
        ),
        "view_artifact_count": sum(len(item.get("views") or []) for item in results),
        "grasp_feasibility_signature_count": len(grasp_signature_counts),
        "grasp_feasibility_signature_counts": grasp_signature_counts,
        "prior_manifest_count": len(summaries),
        "results": results,
        "fallback_generation": fallback_generation,
    }


def _prior_result_merge_key(item: dict[str, Any]) -> tuple[str, str, str]:
    request_id = str(item.get("request_id") or "")
    if "_fallback_" not in request_id:
        return (request_id, "", "")
    config = item.get("cleanup_task_config")
    if not isinstance(config, dict):
        config = item.get("requested_cleanup_primitive_binding")
    config = config if isinstance(config, dict) else {}
    object_alias = str(config.get("planner_object_id") or "")
    target_alias = str(config.get("planner_target_receptacle_id") or "")
    if object_alias or target_alias:
        return (request_id, object_alias, target_alias)
    return (request_id, "", "")


def _prior_result_rank(item: dict[str, Any]) -> tuple[int, int, int, int]:
    task_status = str(item.get("task_feasibility_status") or "")
    status = str(item.get("status") or "")
    blockers = item.get("blockers") or []
    return (
        1 if task_status == "blocked" else 0,
        1 if status not in {"", "not_run"} else 0,
        1 if item.get("run_result_exists") else 0,
        len(blockers) if isinstance(blockers, list) else 0,
    )


def _dict_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _merged_fallback_generation(
    *,
    discovered_aliases: list[dict[str, Any]],
    filtered_aliases: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
    normalized_aliases: list[dict[str, Any]],
    generated_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    discovered = _dedupe_by_keys(
        discovered_aliases,
        ("source_request_id", "axis", "alias"),
    )
    aliases = _dedupe_by_keys(
        filtered_aliases,
        ("source_request_id", "axis", "alias", "reason"),
    )
    pairs = _dedupe_by_keys(
        filtered_pairs,
        ("source_request_id", "object_alias", "target_alias", "reason"),
    )
    normalized = _dedupe_by_keys(
        normalized_aliases,
        ("source_request_id", "axis", "alias", "normalized_alias"),
    )
    generated = _dedupe_by_keys(generated_requests, ("request_id",))
    return {
        "schema": "merged_planner_cleanup_proof_request_fallback_generation_v1",
        "enabled": any([discovered, aliases, pairs, normalized, generated]),
        "generated_request_count": len(generated),
        "generated_requests": generated,
        "discovered_alias_count": len(discovered),
        "discovered_aliases": discovered,
        "filtered_alias_count": len(aliases),
        "filtered_aliases": aliases,
        "filtered_pair_count": len(pairs),
        "filtered_pairs": pairs,
        "normalized_alias_count": len(normalized),
        "normalized_aliases": normalized,
        "evidence_note": (
            "Merged fallback candidate memory from one or more prior proof-bundle "
            "manifests. This is private runner evidence and is not exposed to Agent View."
        ),
    }


def _dedupe_by_keys(
    items: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    deduped = []
    seen: set[tuple[str, ...]] = set()
    for item in items:
        key = tuple(str(item.get(name) or "") for name in keys)
        if not any(key) or key in seen:
            continue
        deduped.append(dict(item))
        seen.add(key)
    return deduped


def _merged_prior_results(
    results: list[dict[str, Any]],
    excluded_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = [dict(item) for item in results if isinstance(item, dict)]
    result_ids = {str(item.get("request_id") or "") for item in merged}
    for item in excluded_requests:
        if not isinstance(item, dict):
            continue
        request_id = str(item.get("request_id") or "")
        if not request_id or request_id in result_ids:
            continue
        merged.append(
            {
                "request_id": request_id,
                "object_id": str(item.get("object_id") or ""),
                "target_receptacle_id": str(item.get("target_receptacle_id") or ""),
                "status": str(item.get("prior_status") or "blocked_capability"),
                "task_feasibility_status": str(
                    item.get("prior_task_feasibility_status") or "blocked"
                ),
                "task_feasibility_blocker_kind": str(
                    item.get("prior_task_feasibility_blocker_kind") or ""
                ),
                "task_feasibility_blocker_summary": str(
                    item.get("prior_task_feasibility_blocker_summary") or ""
                ),
                "blockers": list(item.get("prior_blockers") or []),
                "run_result": str(item.get("prior_run_result") or ""),
                "report": str(item.get("prior_report") or ""),
                "stdout": str(item.get("prior_stdout") or ""),
                "stderr": str(item.get("prior_stderr") or ""),
                "last_worker_stage": str(item.get("last_worker_stage") or ""),
                "execution_attempted": bool(item.get("execution_attempted")),
            }
        )
        result_ids.add(request_id)
    return merged


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
