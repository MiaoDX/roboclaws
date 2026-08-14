from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object as read_source_json_object
from roboclaws.household import planner_proof_results
from roboclaws.household.planner_task_feasibility import (
    grasp_feasibility_signature_counts,
)


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
    summary = planner_proof_results.proof_result_summary_from_commands(commands)
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
