from __future__ import annotations

import json
import re
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_value
from roboclaws.household.planner_proof_fallbacks import (
    discovered_alias_values as _discovered_alias_values,
)
from roboclaws.household.planner_proof_fallbacks import (
    discovered_runtime_aliases_by_source_request as _discovered_runtime_aliases_by_source_request,
)
from roboclaws.household.planner_proof_fallbacks import (
    planner_arg as _planner_arg,
)
from roboclaws.household.planner_proof_fallbacks import (
    prior_fallback_candidate_filters_by_source_request,
)
from roboclaws.household.planner_proof_fallbacks import (
    prior_pair_filter_lookup as _prior_pair_filter_lookup,
)
from roboclaws.household.planner_proof_fallbacks import (
    proof_cleanup_task_config as _proof_cleanup_task_config,
)
from roboclaws.household.planner_proof_fallbacks import (
    unique_nonempty_values as _unique_nonempty_values,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    planner_proof_quality_summary,
)
from roboclaws.household.planner_task_feasibility import (
    grasp_cache_availability_preflight,
    grasp_cache_generation_preflight,
    grasp_feasibility_mitigation_decision,
    grasp_feasibility_signature,
    grasp_feasibility_signature_counts,
    task_feasibility_blocker_kind,
    task_feasibility_blocker_summary,
)
from roboclaws.household.semantic_timeline import (
    SEMANTIC_SUBPHASE_LABELS,
    canonical_cleanup_tool_sequence,
)

PLANNER_PROOF_REQUESTS_SCHEMA = "planner_cleanup_proof_requests_v1"
PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA = "planner_cleanup_proof_bundle_run_manifest_v1"
PLANNER_PROOF_RESULT_SUMMARY_SCHEMA = "planner_cleanup_proof_result_summary_v1"
PLANNER_PROOF_REQUEST_SELECTION_SCHEMA = "planner_cleanup_proof_request_selection_v1"
PLANNER_PROOF_EXECUTION_HORIZON_SCHEMA = "planner_cleanup_proof_execution_horizon_v1"
PLANNER_PROOF_REQUEST_FALLBACK_GENERATION_SCHEMA = (
    "planner_cleanup_proof_request_fallback_generation_v1"
)
_prior_fallback_candidate_filters_by_source_request = (
    prior_fallback_candidate_filters_by_source_request
)
_FALLBACK_REQUEST_ID_MARKER = "_fallback_"
_RUNTIME_ALIAS_RE = re.compile(r"^(?P<prefix>.+)_(?P<group>\d+)_(?P<variant>\d+)_(?P<room>\d+)$")


def planner_proof_requests_from_substeps(
    *,
    contract: Any,
    substeps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build private bound planner-proof requests from semantic cleanup substeps."""
    requests = []
    blockers = []
    for item in substeps:
        object_id = str(item.get("object_id") or "")
        target_receptacle_id = str(item.get("target_receptacle_id") or "")
        source_receptacle_id = str(item.get("source_receptacle_id") or "")
        tools = _cleanup_tools(item.get("steps") or [])
        binding = _planner_binding(
            contract=contract,
            object_id=object_id,
            target_receptacle_id=target_receptacle_id,
            source_receptacle_id=source_receptacle_id,
            tools=tools,
        )
        request = {
            "request_id": f"proof_{len(requests) + 1:03d}",
            "object_id": object_id,
            "target_receptacle_id": target_receptacle_id,
            "source_receptacle_id": source_receptacle_id,
            "tools": tools,
            "ready": bool(binding.get("ok")),
            "binding": binding,
            "planner_probe_args": dict(binding.get("planner_probe_args") or {}),
            "blockers": list(binding.get("blockers") or []),
        }
        if not request["ready"]:
            blockers.extend(_request_blockers(request))
        requests.append(request)
    ready_count = sum(1 for request in requests if request["ready"])
    return {
        "schema": PLANNER_PROOF_REQUESTS_SCHEMA,
        "request_count": len(requests),
        "ready_count": ready_count,
        "planner_scene": _planner_scene(contract),
        "requests": requests,
        "agent_view_exposed": False,
        "blockers": blockers,
        "evidence_note": (
            "Private planner proof requests derived from completed semantic cleanup "
            "substeps. Planner aliases are not part of Agent View."
        ),
    }


def write_planner_proof_requests(
    *,
    output_path: Path,
    contract: Any,
    substeps: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest = planner_proof_requests_from_substeps(contract=contract, substeps=substeps)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def ready_planner_proof_requests(
    manifest: dict[str, Any],
    *,
    request_selection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    assert manifest.get("schema") == PLANNER_PROOF_REQUESTS_SCHEMA, manifest
    selected_ids = _selected_request_ids(request_selection)
    requests = [
        *(manifest.get("requests") or []),
        *_generated_ready_proof_requests(request_selection),
    ]
    return [
        request
        for request in requests
        if request.get("ready")
        and (selected_ids is None or str(request.get("request_id") or "") in selected_ids)
    ]


def build_probe_commands(
    *,
    manifest: dict[str, Any],
    output_dir: Path,
    runner_python: Path,
    probe_script: Path,
    molmospaces_python: Path | None = None,
    molmospaces_root: Path | None = None,
    embodiment: str = "rby1m",
    probe_mode: str = "execute",
    steps: int = 2,
    timeout_s: float = 600.0,
    renderer_device_id: int = 0,
    torch_extensions_dir: Path | None = None,
    rby1m_curobo_memory_profile: str = "low",
    task_sampler_robot_placement_profile: str = "none",
    request_selection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    commands = []
    ready_requests = ready_planner_proof_requests(
        manifest,
        request_selection=request_selection,
    )
    for index, request in enumerate(ready_requests, start=1):
        proof_dir = output_dir / "proofs" / _proof_dir_name(index, request)
        command = [
            str(runner_python),
            str(probe_script),
            "--output-dir",
            str(proof_dir),
            "--embodiment",
            embodiment,
            "--probe-mode",
            probe_mode,
            "--renderer-device-id",
            str(renderer_device_id),
            "--rby1m-curobo-memory-profile",
            rby1m_curobo_memory_profile,
            "--steps",
            str(steps),
            "--timeout-s",
            str(timeout_s),
        ]
        if task_sampler_robot_placement_profile != "none":
            command.extend(
                [
                    "--task-sampler-robot-placement-profile",
                    task_sampler_robot_placement_profile,
                ]
            )
        if molmospaces_python is not None:
            command.extend(["--python-executable", str(molmospaces_python)])
        if molmospaces_root is not None:
            command.extend(["--molmospaces-root", str(molmospaces_root)])
        if torch_extensions_dir is not None:
            command.extend(["--torch-extensions-dir", str(torch_extensions_dir)])
        scene_xml = str((manifest.get("planner_scene") or {}).get("scene_xml") or "")
        if scene_xml:
            command.extend(["--cleanup-scene-xml", str(Path(scene_xml).expanduser())])
        tools = _request_tools(request)
        planner_probe_args = dict(request.get("planner_probe_args") or {})
        if tools:
            planner_probe_args["--cleanup-tools"] = ",".join(tools)
        for flag, value in sorted(planner_probe_args.items()):
            command.extend([str(flag), str(value)])
        commands.append(
            {
                "request_id": request.get("request_id"),
                "object_id": request.get("object_id"),
                "target_receptacle_id": request.get("target_receptacle_id"),
                "tools": tools,
                "semantic_subphases": _semantic_subphase_entries(tools),
                "output_dir": str(proof_dir),
                "run_result": str(proof_dir / "run_result.json"),
                "report": str(proof_dir / "report.html"),
                "command": command,
            }
        )
    return commands


def build_probe_warmup_command(
    *,
    output_dir: Path,
    runner_python: Path,
    probe_script: Path,
    molmospaces_python: Path | None = None,
    molmospaces_root: Path | None = None,
    embodiment: str = "rby1m",
    timeout_s: float = 600.0,
    renderer_device_id: int = 0,
    torch_extensions_dir: Path | None = None,
    rby1m_curobo_memory_profile: str = "low",
) -> dict[str, Any]:
    """Build a visible config-import warmup command for local proof-bundle runs."""
    warmup_dir = output_dir / "rby1m_curobo_warmup"
    command = [
        str(runner_python),
        str(probe_script),
        "--output-dir",
        str(warmup_dir),
        "--embodiment",
        embodiment,
        "--probe-mode",
        "config_import",
        "--renderer-device-id",
        str(renderer_device_id),
        "--rby1m-curobo-memory-profile",
        rby1m_curobo_memory_profile,
        "--steps",
        "1",
        "--timeout-s",
        str(timeout_s),
    ]
    if molmospaces_python is not None:
        command.extend(["--python-executable", str(molmospaces_python)])
    if molmospaces_root is not None:
        command.extend(["--molmospaces-root", str(molmospaces_root)])
    if torch_extensions_dir is not None:
        command.extend(["--torch-extensions-dir", str(torch_extensions_dir)])
    return {
        "kind": "rby1m_curobo_config_import",
        "output_dir": str(warmup_dir),
        "run_result": str(warmup_dir / "run_result.json"),
        "report": str(warmup_dir / "report.html"),
        "command": command,
        "evidence_note": (
            "Optional local-dev warmup before proof commands. This is runtime "
            "readiness evidence only; strict per-proof validation remains authoritative."
        ),
    }


def proof_execution_horizon(
    *,
    command_steps: int,
    prior_covered_min_proof_steps: int,
) -> dict[str, Any]:
    """Describe the proof-strength target requested by a proof-bundle run."""
    command_steps = max(0, int(command_steps))
    coverage_min_steps = max(1, int(prior_covered_min_proof_steps))
    blockers: list[dict[str, Any]] = []
    status = "aligned"
    if command_steps < coverage_min_steps:
        status = "command_steps_below_coverage_horizon"
        blockers.append(
            {
                "code": "command_steps_below_coverage_horizon",
                "message": (
                    f"Probe commands request {command_steps} steps, below the "
                    f"prior-covered minimum of {coverage_min_steps} steps."
                ),
            }
        )
    return {
        "schema": PLANNER_PROOF_EXECUTION_HORIZON_SCHEMA,
        "status": status,
        "command_steps": command_steps,
        "command_quality_target": _quality_target_for_steps(command_steps),
        "prior_covered_min_proof_steps": coverage_min_steps,
        "prior_covered_quality_floor": _quality_target_for_steps(coverage_min_steps),
        "blockers": blockers,
        "evidence_note": (
            "Requested proof-strength horizon for generated proof commands. "
            "This records the intended proof tier before local execution; strict "
            "proof results remain authoritative after execution."
        ),
    }


def _quality_target_for_steps(steps: int) -> str:
    if steps >= 2:
        return "multi_step_motion"
    if steps >= 1:
        return "one_step_motion"
    return "unknown"


def proof_bundle_run_manifest(
    *,
    cleanup_run_result: Path,
    output_dir: Path,
    proof_requests: dict[str, Any],
    commands: list[dict[str, Any]],
    warmup: dict[str, Any] | None = None,
    local_runtime_preflight: dict[str, Any] | None = None,
    proof_execution_horizon: dict[str, Any] | None = None,
    proof_request_selection: dict[str, Any] | None = None,
    prior_proof_result_summary: dict[str, Any] | None = None,
    proof_result_summary: dict[str, Any] | None = None,
    cleanup_command: list[str] | None = None,
    cleanup_rerun: dict[str, Any] | None = None,
    molmospaces_python: Path | None = None,
    molmospaces_root: Path | None = None,
) -> dict[str, Any]:
    selection = proof_request_selection or proof_request_selection_from_summary(proof_requests)
    summary = proof_result_summary or proof_result_summary_from_commands(commands)
    prior_summary = prior_proof_result_summary or {}
    grasp_mitigation_decision = grasp_feasibility_mitigation_decision(
        prior_proof_result_summary=prior_summary,
        proof_result_summary=summary,
        proof_request_selection=selection,
    )
    planner_scene = proof_requests.get("planner_scene") or {}
    planner_assets_dir = _assets_dir_from_planner_scene(planner_scene)
    grasp_cache_preflight = grasp_cache_availability_preflight(
        grasp_mitigation_decision,
        assets_dir=planner_assets_dir,
        assets_dir_source="planner_scene" if planner_assets_dir is not None else None,
    )
    return {
        "schema": PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA,
        "cleanup_run_result": str(cleanup_run_result),
        "output_dir": str(output_dir),
        "proof_request_count": int(proof_requests.get("request_count") or 0),
        "ready_request_count": int(proof_requests.get("ready_count") or 0),
        "planner_scene": planner_scene,
        "proof_request_selection": selection,
        "prior_proof_result_summary": prior_summary,
        "local_runtime_preflight": local_runtime_preflight or {},
        "proof_execution_horizon": proof_execution_horizon or {},
        "warmup": warmup or {},
        "command_count": len(commands),
        "commands": commands,
        "proof_result_summary": summary,
        "grasp_feasibility_mitigation_decision": grasp_mitigation_decision,
        "grasp_cache_availability_preflight": grasp_cache_preflight,
        "grasp_cache_generation_preflight": grasp_cache_generation_preflight(
            grasp_cache_preflight,
            output_dir=output_dir,
            molmospaces_python=molmospaces_python,
            molmospaces_root=molmospaces_root,
        ),
        "cleanup_command": cleanup_command or [],
        "cleanup_rerun": cleanup_rerun or {},
        "evidence_note": (
            "Dry-run manifest for generating bound planner proofs from an ADR-0003 "
            "cleanup artifact. Use --execute-probes in a local RBY1M/CuRobo session."
        ),
    }


def _assets_dir_from_planner_scene(planner_scene: dict[str, Any]) -> Path | None:
    scene_xml = str(planner_scene.get("scene_xml") or "")
    if not scene_xml:
        return None
    scene_path = Path(scene_xml)
    for parent in scene_path.parents:
        if parent.name == "scenes":
            return parent.parent
    return None


def proof_request_selection_from_summary(
    proof_requests: dict[str, Any],
    *,
    prior_proof_result_summary: dict[str, Any] | None = None,
    include_request_ids: Sequence[str] | None = None,
    exclude_task_feasibility_blocked: bool = False,
    exclude_prior_covered: bool = False,
    prior_covered_min_proof_steps: int = 1,
    generate_fallback_requests: bool = False,
    fallback_alias_limit: int = 4,
) -> dict[str, Any]:
    """Select ready proof requests, optionally excluding known infeasible requests."""
    prior_covered_min_proof_steps = max(1, int(prior_covered_min_proof_steps))
    requested_ids = _normalized_request_ids(include_request_ids)
    all_requests = [request for request in proof_requests.get("requests") or []]
    all_ready_requests = [
        request for request in proof_requests.get("requests") or [] if request.get("ready")
    ]
    request_filter = _request_id_filter(
        requested_ids=requested_ids,
        requests=all_requests,
        ready_requests=all_ready_requests,
    )
    ready_requests = [
        request
        for request in all_ready_requests
        if not requested_ids or str(request.get("request_id") or "") in set(requested_ids)
    ]
    prior_summary = prior_proof_result_summary or {}
    prior_results = _prior_results_by_request_id(prior_summary)
    prior_results_by_cleanup_pair = _prior_results_by_cleanup_pair(prior_summary)
    prior_results_by_planner_object_target = _prior_results_by_planner_object_target(prior_summary)
    discovered_aliases_by_request = _discovered_runtime_aliases_by_source_request(
        ready_requests,
        prior_summary,
    )
    prior_candidate_filters_by_request = _prior_fallback_candidate_filters_by_source_request(
        prior_summary
    )
    selected = []
    excluded = []
    generated = []
    filtered_aliases = []
    discovered_aliases = []
    filtered_pairs = []
    normalized_aliases = []
    for request in ready_requests:
        request_id = str(request.get("request_id") or "")
        prior_result, prior_result_match_kind = _prior_result_for_request(
            request,
            prior_results_by_request_id=prior_results,
            prior_results_by_cleanup_pair=prior_results_by_cleanup_pair,
            prior_results_by_planner_object_target=prior_results_by_planner_object_target,
        )
        if exclude_prior_covered and _prior_result_has_cleanup_binding_coverage(
            prior_result,
            min_proof_steps=prior_covered_min_proof_steps,
        ):
            excluded.append(
                _excluded_request(
                    request,
                    prior_result,
                    reason="prior_planner_proof_covered",
                    prior_result_match_kind=prior_result_match_kind,
                )
            )
            continue
        if (
            exclude_task_feasibility_blocked
            and prior_result.get("task_feasibility_status") == "blocked"
        ):
            excluded.append(
                _excluded_request(
                    request,
                    prior_result,
                    reason="prior_task_feasibility_blocked",
                    prior_result_match_kind=prior_result_match_kind,
                )
            )
            if generate_fallback_requests:
                fallback = _fallback_requests_for_blocked_request(
                    request,
                    prior_result,
                    limit=fallback_alias_limit,
                    discovered_aliases=discovered_aliases_by_request.get(request_id, {}),
                    prior_candidate_filters=prior_candidate_filters_by_request.get(request_id, {}),
                    prior_result_match_kind=prior_result_match_kind,
                )
                generated.extend(fallback["generated_requests"])
                filtered_aliases.extend(fallback["filtered_aliases"])
                discovered_aliases.extend(fallback["discovered_aliases"])
                filtered_pairs.extend(fallback["filtered_pairs"])
                normalized_aliases.extend(fallback["normalized_aliases"])
            continue
        selected.append(
            _selected_request(
                request,
                prior_result,
                prior_result_match_kind=prior_result_match_kind,
            )
        )
    selected.extend(
        _selected_request(request, {}, prior_result_match_kind="") for request in generated
    )
    fallback_required = bool(ready_requests) and not selected
    fallback_generation = _fallback_generation(
        enabled=generate_fallback_requests,
        ready_request_count=len(ready_requests),
        excluded_requests=excluded,
        generated_requests=generated,
        filtered_aliases=filtered_aliases,
        discovered_aliases=discovered_aliases,
        filtered_pairs=filtered_pairs,
        normalized_aliases=normalized_aliases,
        fallback_alias_limit=fallback_alias_limit,
    )
    target_feasibility_blockers = _target_feasibility_blockers(
        excluded_requests=excluded,
        filtered_pairs=fallback_generation.get("filtered_pairs") or [],
    )
    grasp_feasibility_blockers = _grasp_feasibility_blockers(target_feasibility_blockers)
    return {
        "schema": PLANNER_PROOF_REQUEST_SELECTION_SCHEMA,
        "mode": _proof_request_selection_mode(
            include_request_ids=bool(requested_ids),
            exclude_task_feasibility_blocked=exclude_task_feasibility_blocked,
            exclude_prior_covered=exclude_prior_covered,
            generate_fallback_requests=generate_fallback_requests,
        ),
        "ready_request_count": len(all_ready_requests),
        "candidate_request_count": len(ready_requests),
        "request_filter": request_filter,
        "selected_count": len(selected),
        "excluded_count": len(excluded),
        "covered_request_count": sum(
            1 for item in excluded if item.get("reason") == "prior_planner_proof_covered"
        ),
        "prior_covered_min_proof_steps": prior_covered_min_proof_steps,
        "generated_fallback_request_count": len(generated),
        "fallback_required": fallback_required,
        "selected_request_ids": [item["request_id"] for item in selected],
        "selected_requests": selected,
        "excluded_requests": excluded,
        "target_feasibility_blocker_count": len(target_feasibility_blockers),
        "target_feasibility_blockers": target_feasibility_blockers,
        "grasp_feasibility_blocker_count": len(grasp_feasibility_blockers),
        "grasp_feasibility_blockers": grasp_feasibility_blockers,
        "fallback_generation": fallback_generation,
        "prior_summary_available": bool(prior_proof_result_summary),
        "prior_result_count": len(prior_results),
        "evidence_note": (
            "Private proof request selection for local proof-bundle execution. "
            "Excluded requests require fallback generation before another exact proof run."
        ),
    }


def _proof_request_selection_mode(
    *,
    include_request_ids: bool,
    exclude_task_feasibility_blocked: bool,
    exclude_prior_covered: bool,
    generate_fallback_requests: bool,
) -> str:
    if exclude_task_feasibility_blocked and exclude_prior_covered and generate_fallback_requests:
        mode = "exclude_task_feasibility_blocked_and_prior_covered_with_fallbacks"
    elif exclude_task_feasibility_blocked and exclude_prior_covered:
        mode = "exclude_task_feasibility_blocked_and_prior_covered"
    elif exclude_task_feasibility_blocked and generate_fallback_requests:
        mode = "exclude_task_feasibility_blocked_with_fallbacks"
    elif exclude_task_feasibility_blocked:
        mode = "exclude_task_feasibility_blocked"
    elif exclude_prior_covered:
        mode = "exclude_prior_covered"
    else:
        mode = "all_ready"
    if include_request_ids:
        if mode == "all_ready":
            return "request_id_filter"
        return f"request_id_filter_and_{mode}"
    return mode


def _normalized_request_ids(request_ids: Sequence[str] | None) -> list[str]:
    if not request_ids:
        return []
    return _unique_nonempty_values([str(item).strip() for item in request_ids])


def _request_id_filter(
    *,
    requested_ids: list[str],
    requests: list[dict[str, Any]],
    ready_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    if not requested_ids:
        return {
            "enabled": False,
            "requested_request_ids": [],
            "matched_request_ids": [],
            "unavailable_request_ids": [],
        }
    request_ids = {str(item.get("request_id") or "") for item in requests}
    ready_ids = {str(item.get("request_id") or "") for item in ready_requests}
    matched = [request_id for request_id in requested_ids if request_id in ready_ids]
    unavailable = [request_id for request_id in requested_ids if request_id not in ready_ids]
    missing = [request_id for request_id in requested_ids if request_id not in request_ids]
    return {
        "enabled": True,
        "requested_request_ids": requested_ids,
        "requested_count": len(requested_ids),
        "matched_request_ids": matched,
        "matched_count": len(matched),
        "unavailable_request_ids": unavailable,
        "unavailable_count": len(unavailable),
        "missing_request_ids": missing,
        "missing_count": len(missing),
        "evidence_note": ("Explicit proof request filter for bounded local proof-bundle runs."),
    }


def _selected_request_ids(request_selection: dict[str, Any] | None) -> set[str] | None:
    if not request_selection:
        return None
    raw = request_selection.get("selected_request_ids")
    if raw is None:
        return None
    return {str(item) for item in raw}


def _generated_ready_proof_requests(
    request_selection: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not request_selection:
        return []
    fallback_generation = request_selection.get("fallback_generation") or {}
    if not isinstance(fallback_generation, dict):
        return []
    raw = fallback_generation.get("generated_requests") or []
    return [
        dict(item)
        for item in raw
        if isinstance(item, dict) and item.get("ready") and item.get("request_id")
    ]


def _prior_results_by_request_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("request_id") or ""): dict(item)
        for item in summary.get("results") or []
        if isinstance(item, dict) and item.get("request_id")
    }


def _prior_results_by_cleanup_pair(
    summary: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for item in summary.get("results") or []:
        if not isinstance(item, dict):
            continue
        pair = _cleanup_pair_from_result(item)
        if not all(pair):
            continue
        existing = results.get(pair)
        if existing is None or _prior_selection_result_rank(item) >= _prior_selection_result_rank(
            existing
        ):
            results[pair] = dict(item)
    return results


def _prior_results_by_planner_object_target(
    summary: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for item in summary.get("results") or []:
        if not isinstance(item, dict):
            continue
        pair = _planner_object_target_pair_from_result(item)
        if not all(pair):
            continue
        existing = results.get(pair)
        if existing is None or _prior_selection_result_rank(item) >= _prior_selection_result_rank(
            existing
        ):
            results[pair] = dict(item)
    return results


def _prior_result_for_request(
    request: dict[str, Any],
    *,
    prior_results_by_request_id: dict[str, dict[str, Any]],
    prior_results_by_cleanup_pair: dict[tuple[str, str], dict[str, Any]],
    prior_results_by_planner_object_target: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    request_id = str(request.get("request_id") or "")
    prior_by_request_id = prior_results_by_request_id.get(request_id)
    if prior_by_request_id and _request_id_prior_result_matches_request(
        request,
        prior_by_request_id,
    ):
        return prior_by_request_id, "request_id"
    pair = _cleanup_pair_from_request(request)
    prior_by_cleanup_pair = prior_results_by_cleanup_pair.get(pair)
    if prior_by_cleanup_pair and _cleanup_pair_prior_result_matches_request(
        request,
        prior_by_cleanup_pair,
    ):
        return prior_by_cleanup_pair, "object_target"
    planner_pair = _planner_object_target_pair_from_request(request)
    if planner_pair in prior_results_by_planner_object_target:
        return prior_results_by_planner_object_target[planner_pair], "planner_object_target"
    return {}, ""


def _cleanup_pair_from_request(request: dict[str, Any]) -> tuple[str, str]:
    return (
        str(request.get("object_id") or ""),
        str(request.get("target_receptacle_id") or ""),
    )


def _cleanup_pair_from_result(result: dict[str, Any]) -> tuple[str, str]:
    return (
        str(result.get("object_id") or ""),
        str(result.get("target_receptacle_id") or ""),
    )


def _planner_object_target_pair_from_request(request: dict[str, Any]) -> tuple[str, str]:
    args = request.get("planner_probe_args") or {}
    planner_object_id = _planner_arg(args, "--cleanup-planner-object-id")
    planner_target_id = _planner_arg(args, "--cleanup-planner-target-receptacle-id")
    return (
        planner_object_id,
        str(request.get("target_receptacle_id") or planner_target_id),
    )


def _planner_object_target_pair_from_result(result: dict[str, Any]) -> tuple[str, str]:
    config = _proof_cleanup_task_config(result)
    planner_object_id = str(config.get("planner_object_id") or "")
    planner_target_id = str(config.get("planner_target_receptacle_id") or "")
    return (
        planner_object_id,
        str(
            result.get("target_receptacle_id")
            or config.get("target_receptacle_id")
            or planner_target_id
        ),
    )


def _request_id_prior_result_matches_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
) -> bool:
    if _planner_object_target_pairs_conflict(request, prior_result):
        return False
    request_cleanup_pair = _cleanup_pair_from_request(request)
    prior_cleanup_pair = _cleanup_pair_from_result(prior_result)
    if all(request_cleanup_pair) and all(prior_cleanup_pair):
        return request_cleanup_pair == prior_cleanup_pair
    request_planner_pair = _planner_object_target_pair_from_request(request)
    prior_planner_pair = _planner_object_target_pair_from_result(prior_result)
    if all(request_planner_pair) and all(prior_planner_pair):
        return request_planner_pair == prior_planner_pair
    return True


def _cleanup_pair_prior_result_matches_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
) -> bool:
    return not _planner_object_target_pairs_conflict(request, prior_result)


def _planner_object_target_pairs_conflict(
    request: dict[str, Any],
    prior_result: dict[str, Any],
) -> bool:
    request_planner_pair = _planner_object_target_pair_from_request(request)
    prior_planner_pair = _planner_object_target_pair_from_result(prior_result)
    return (
        all(request_planner_pair)
        and all(prior_planner_pair)
        and (request_planner_pair != prior_planner_pair)
    )


def _prior_selection_result_rank(item: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(str(item.get("task_feasibility_status") or "") == "blocked"),
        int(str(item.get("status") or "") == "blocked_capability"),
        int(bool(item.get("run_result_exists") or item.get("run_result"))),
    )


def _prior_result_has_cleanup_binding_coverage(
    item: dict[str, Any],
    *,
    min_proof_steps: int,
) -> bool:
    if not bool(item.get("planner_backed")) or not bool(item.get("cleanup_binding_promoted")):
        return False
    if min_proof_steps <= 1 and not _has_prior_quality_inputs(item):
        return True
    quality = planner_proof_quality_evidence(item)
    return (
        bool(quality.get("one_step_motion"))
        and int(quality.get("steps_executed") or 0) >= min_proof_steps
        and float(quality.get("max_abs_qpos_delta") or 0.0) > 0.0
    )


def _has_prior_quality_inputs(item: dict[str, Any]) -> bool:
    return any(
        key in item
        for key in (
            "proof_quality",
            "steps_executed",
            "max_abs_qpos_delta",
            "containment_proven",
            "object_state_evidence",
        )
    )


def _selected_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    prior_result_match_kind: str,
) -> dict[str, Any]:
    fallback = request.get("fallback_request") or {}
    is_fallback = isinstance(fallback, dict) and bool(fallback)
    item = {
        "request_id": str(request.get("request_id") or ""),
        "request_type": "fallback_generated" if is_fallback else "source",
        "source_request_id": str(fallback.get("source_request_id") or ""),
        "object_id": str(request.get("object_id") or ""),
        "target_receptacle_id": str(request.get("target_receptacle_id") or ""),
        "prior_task_feasibility_status": str(
            prior_result.get("task_feasibility_status")
            or fallback.get("prior_task_feasibility_status")
            or "unknown"
        ),
    }
    item.update(
        _nonempty_prior_blocker_fields(
            prior_result.get("task_feasibility_blocker_kind")
            or fallback.get("prior_task_feasibility_blocker_kind"),
            prior_result.get("task_feasibility_blocker_summary")
            or fallback.get("prior_task_feasibility_blocker_summary"),
        )
    )
    match_kind = prior_result_match_kind or str(fallback.get("prior_result_match_kind") or "")
    if match_kind:
        item["prior_result_match_kind"] = match_kind
    if prior_result:
        item.update(_prior_result_evidence_fields(prior_result))
    return item


def _excluded_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    reason: str,
    prior_result_match_kind: str,
) -> dict[str, Any]:
    item = {
        "request_id": str(request.get("request_id") or ""),
        "object_id": str(request.get("object_id") or ""),
        "target_receptacle_id": str(request.get("target_receptacle_id") or ""),
        "reason": reason,
        "prior_status": str(prior_result.get("status") or ""),
        "prior_task_feasibility_status": str(prior_result.get("task_feasibility_status") or ""),
        "prior_blockers": _blockers(prior_result.get("blockers") or []),
        **_prior_result_evidence_fields(prior_result),
    }
    item.update(_prior_result_blocker_fields(prior_result))
    if prior_result_match_kind:
        item["prior_result_match_kind"] = prior_result_match_kind
    return item


def _target_feasibility_blockers(
    *,
    excluded_requests: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in excluded_requests:
        if str(item.get("prior_task_feasibility_status") or "") != "blocked":
            continue
        blockers.append(
            _target_feasibility_blocker(
                item,
                kind="source_request",
                source_request_id=str(item.get("request_id") or ""),
                object_id=str(item.get("object_id") or ""),
                target_receptacle_id=str(item.get("target_receptacle_id") or ""),
            )
        )
    for item in filtered_pairs:
        if str(item.get("reason") or "") != "prior_task_feasibility_blocked_pair":
            continue
        blockers.append(
            _target_feasibility_blocker(
                item,
                kind="fallback_pair",
                source_request_id=str(item.get("source_request_id") or ""),
                object_alias=str(item.get("object_alias") or ""),
                target_alias=str(item.get("target_alias") or ""),
                derived_from=str(item.get("derived_from") or ""),
            )
        )
    return blockers


def _target_feasibility_blocker(
    item: dict[str, Any],
    *,
    kind: str,
    source_request_id: str,
    object_id: str = "",
    target_receptacle_id: str = "",
    object_alias: str = "",
    target_alias: str = "",
    derived_from: str = "",
) -> dict[str, Any]:
    blocker = {
        "kind": kind,
        "source_request_id": source_request_id,
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "object_alias": object_alias,
        "target_alias": target_alias,
        "derived_from": derived_from,
        "reason": str(item.get("reason") or ""),
        "prior_status": str(item.get("prior_status") or ""),
        "prior_task_feasibility_status": str(item.get("prior_task_feasibility_status") or ""),
        "prior_blockers": _blockers(item.get("prior_blockers") or []),
        "prior_run_result": str(item.get("prior_run_result") or ""),
        "prior_report": str(item.get("prior_report") or ""),
        "prior_stdout": str(item.get("prior_stdout") or ""),
        "prior_stderr": str(item.get("prior_stderr") or ""),
        "last_worker_stage": str(item.get("last_worker_stage") or ""),
        "execution_attempted": bool(item.get("execution_attempted")),
    }
    blocker.update(
        _nonempty_prior_blocker_fields(
            item.get("prior_task_feasibility_blocker_kind"),
            item.get("prior_task_feasibility_blocker_summary"),
        )
    )
    if item.get("prior_result_match_kind"):
        blocker["prior_result_match_kind"] = str(item.get("prior_result_match_kind") or "")
    return blocker


def _grasp_feasibility_blockers(
    target_feasibility_blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in target_feasibility_blockers
        if str(item.get("prior_task_feasibility_blocker_kind") or "") == "grasp_feasibility"
    ]


def _prior_result_evidence_fields(result: dict[str, Any]) -> dict[str, Any]:
    quality = planner_proof_quality_evidence(result)
    return {
        "prior_run_result": str(result.get("run_result") or ""),
        "prior_report": str(result.get("report") or ""),
        "prior_stdout": str(result.get("stdout") or ""),
        "prior_stderr": str(result.get("stderr") or ""),
        "last_worker_stage": str(result.get("last_worker_stage") or ""),
        "execution_attempted": bool(result.get("execution_attempted")),
        "prior_proof_quality": str(quality.get("quality_tier") or ""),
        "prior_steps_executed": int(quality.get("steps_executed") or 0),
        "prior_max_abs_qpos_delta": float(quality.get("max_abs_qpos_delta") or 0.0),
    }


def _prior_result_blocker_fields(result: dict[str, Any]) -> dict[str, Any]:
    return _nonempty_prior_blocker_fields(
        result.get("task_feasibility_blocker_kind"),
        result.get("task_feasibility_blocker_summary"),
    )


def _nonempty_prior_blocker_fields(kind: Any, summary: Any) -> dict[str, str]:
    fields = {}
    kind_text = str(kind or "")
    summary_text = str(summary or "")
    if kind_text:
        fields["prior_task_feasibility_blocker_kind"] = kind_text
    if summary_text:
        fields["prior_task_feasibility_blocker_summary"] = summary_text
    return fields


def _fallback_generation(
    *,
    enabled: bool,
    ready_request_count: int,
    excluded_requests: list[dict[str, Any]],
    generated_requests: list[dict[str, Any]],
    filtered_aliases: list[dict[str, Any]],
    discovered_aliases: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
    normalized_aliases: list[dict[str, Any]],
    fallback_alias_limit: int,
) -> dict[str, Any]:
    if not enabled and not generated_requests:
        return {
            "schema": PLANNER_PROOF_REQUEST_FALLBACK_GENERATION_SCHEMA,
            "status": "disabled",
            "enabled": False,
            "generated_request_count": 0,
            "generated_requests": [],
            "filtered_alias_count": 0,
            "filtered_aliases": [],
            "discovered_alias_count": 0,
            "discovered_aliases": [],
            "filtered_pair_count": 0,
            "filtered_pairs": [],
            "normalized_alias_count": 0,
            "normalized_aliases": [],
        }
    generated_source_ids = {str(item.get("source_request_id") or "") for item in generated_requests}
    unavailable_count = len(excluded_requests) - len(generated_source_ids)
    status = _fallback_generation_status(
        enabled=enabled,
        excluded_request_count=len(excluded_requests),
        generated_request_count=len(generated_requests),
    )
    exhaustion_blockers = _fallback_exhaustion_blockers(
        status=status,
        filtered_aliases=filtered_aliases,
        filtered_pairs=filtered_pairs,
        normalized_aliases=normalized_aliases,
        unavailable_source_request_count=max(unavailable_count, 0),
    )
    return {
        "schema": PLANNER_PROOF_REQUEST_FALLBACK_GENERATION_SCHEMA,
        "status": status,
        "enabled": enabled,
        "ready_request_count": ready_request_count,
        "excluded_request_count": len(excluded_requests),
        "generated_request_count": len(generated_requests),
        "unavailable_source_request_count": max(unavailable_count, 0),
        "fallback_alias_limit": max(int(fallback_alias_limit or 0), 0),
        "generated_requests": generated_requests,
        "filtered_alias_count": len(filtered_aliases),
        "filtered_aliases": filtered_aliases,
        "discovered_alias_count": len(discovered_aliases),
        "discovered_aliases": discovered_aliases,
        "filtered_pair_count": len(filtered_pairs),
        "filtered_pairs": filtered_pairs,
        "normalized_alias_count": len(normalized_aliases),
        "normalized_aliases": normalized_aliases,
        "exhaustion_blocker_count": len(exhaustion_blockers),
        "exhaustion_blockers": exhaustion_blockers,
        "evidence_note": (
            "Private generated fallback proof requests. They preserve cleanup-facing "
            "object and target IDs while trying alternate exact-scene planner aliases."
        ),
    }


def _fallback_generation_status(
    *,
    enabled: bool,
    excluded_request_count: int,
    generated_request_count: int,
) -> str:
    if not enabled:
        return "disabled"
    if generated_request_count > 0:
        return "generated"
    if excluded_request_count > 0:
        return "exhausted"
    return "not_required"


def _fallback_exhaustion_blockers(
    *,
    status: str,
    filtered_aliases: list[dict[str, Any]],
    filtered_pairs: list[dict[str, Any]],
    normalized_aliases: list[dict[str, Any]],
    unavailable_source_request_count: int,
) -> list[dict[str, Any]]:
    if status != "exhausted":
        return []
    blockers = []
    normalized_object_aliases = {
        str(item.get("alias") or "")
        for item in normalized_aliases
        if isinstance(item, dict) and str(item.get("axis") or "") == "object"
    }
    non_root_alias_count = sum(
        1
        for item in filtered_aliases
        if str(item.get("axis") or "") == "object"
        and str(item.get("reason") or "")
        in {"prior_non_root_body_alias", "not_pickup_root_body_alias"}
        and str(item.get("alias") or "") not in normalized_object_aliases
    )
    if non_root_alias_count:
        blockers.append(
            {
                "code": "pickup_root_body_alias_required",
                "count": non_root_alias_count,
                "message": (
                    "Known object-side runtime fallback aliases are filtered as "
                    "non-root pickup bodies; a richer pickup root-body alias source "
                    "is required before more object-side commands can be generated."
                ),
            }
        )
    grasp_feasibility_pair_count = sum(
        1
        for item in filtered_pairs
        if str(item.get("reason") or "") == "prior_task_feasibility_blocked_pair"
        and str(item.get("prior_task_feasibility_blocker_kind") or "") == "grasp_feasibility"
    )
    if grasp_feasibility_pair_count:
        blockers.append(
            {
                "code": "grasp_feasibility_blocked_pairs",
                "count": grasp_feasibility_pair_count,
                "message": (
                    "Known object/target fallback alias pairs clear robot placement "
                    "but are blocked by post-placement grasp/candidate rejection."
                ),
            }
        )
    task_feasibility_pair_count = sum(
        1
        for item in filtered_pairs
        if str(item.get("reason") or "") == "prior_task_feasibility_blocked_pair"
        and str(item.get("prior_task_feasibility_blocker_kind") or "") != "grasp_feasibility"
    )
    if task_feasibility_pair_count:
        blockers.append(
            {
                "code": "target_task_feasibility_blocked_pairs",
                "count": task_feasibility_pair_count,
                "message": (
                    "Known object/target fallback alias pairs are already "
                    "task-feasibility blocked by the upstream sampler."
                ),
            }
        )
    if unavailable_source_request_count:
        blockers.append(
            {
                "code": "no_fallback_candidate_available",
                "count": unavailable_source_request_count,
                "message": (
                    "Excluded source requests have no remaining generated fallback "
                    "candidate after alias and pair filters are applied."
                ),
            }
        )
    if not blockers:
        blockers.append(
            {
                "code": "fallback_candidate_pool_exhausted",
                "count": 0,
                "message": "No generated fallback commands remain for the current evidence pool.",
            }
        )
    return blockers


def _fallback_requests_for_blocked_request(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    limit: int,
    discovered_aliases: dict[str, list[dict[str, Any]]] | None = None,
    prior_candidate_filters: dict[str, Any] | None = None,
    prior_result_match_kind: str = "",
) -> dict[str, list[dict[str, Any]]]:
    if limit <= 0:
        return {
            "generated_requests": [],
            "filtered_aliases": [],
            "discovered_aliases": [],
            "filtered_pairs": [],
            "normalized_aliases": [],
        }
    args = request.get("planner_probe_args") or {}
    current_object_alias = _planner_arg(args, "--cleanup-planner-object-id")
    current_target_alias = _planner_arg(args, "--cleanup-planner-target-receptacle-id")
    discovered = discovered_aliases or {}
    prior_filters = prior_candidate_filters or {}
    prior_alias_filters = prior_filters.get("aliases") if isinstance(prior_filters, dict) else {}
    if not isinstance(prior_alias_filters, dict):
        prior_alias_filters = {}
    (
        pickup_candidates,
        filtered_pickup_aliases,
        normalized_pickup_aliases,
    ) = _executable_candidate_aliases(
        request,
        axis="object",
        candidate_key="candidate_pickup_names",
        current_alias=current_object_alias,
        extra_aliases=_discovered_alias_values(discovered, "object"),
        prior_filtered_aliases=prior_alias_filters.get("object", {}),
    )
    (
        target_candidates,
        filtered_target_aliases,
        normalized_target_aliases,
    ) = _executable_candidate_aliases(
        request,
        axis="target",
        candidate_key="candidate_place_receptacle_names",
        current_alias=current_target_alias,
        extra_aliases=_discovered_alias_values(discovered, "target"),
        prior_filtered_aliases=prior_alias_filters.get("target", {}),
    )
    filtered_aliases = [
        *filtered_pickup_aliases,
        *filtered_target_aliases,
    ]
    normalized_aliases = [
        *normalized_pickup_aliases,
        *normalized_target_aliases,
    ]
    flattened_discovered_aliases = [
        *discovered.get("object", []),
        *discovered.get("target", []),
    ]
    prior_pair_filters = _prior_pair_filter_lookup(prior_filters)
    filtered_pairs = []
    seen_filtered_pairs: set[tuple[str, str]] = set()
    generated: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for object_alias in pickup_candidates:
        for target_alias in target_candidates:
            pair = (object_alias, target_alias)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if pair == (current_object_alias, current_target_alias):
                continue
            prior_pair_filter = prior_pair_filters.get(pair)
            if prior_pair_filter:
                if pair not in seen_filtered_pairs:
                    filtered_pairs.append(dict(prior_pair_filter))
                    seen_filtered_pairs.add(pair)
                continue
            generated.append(
                _fallback_request_with_planner_aliases(
                    request,
                    prior_result,
                    index=len(generated) + 1,
                    planner_object_id=object_alias,
                    planner_target_receptacle_id=target_alias,
                    prior_result_match_kind=prior_result_match_kind,
                )
            )
            if len(generated) >= limit:
                return {
                    "generated_requests": generated,
                    "filtered_aliases": filtered_aliases,
                    "discovered_aliases": flattened_discovered_aliases,
                    "filtered_pairs": filtered_pairs,
                    "normalized_aliases": normalized_aliases,
                }
    return {
        "generated_requests": generated,
        "filtered_aliases": filtered_aliases,
        "discovered_aliases": flattened_discovered_aliases,
        "filtered_pairs": filtered_pairs,
        "normalized_aliases": normalized_aliases,
    }


def _fallback_request_with_planner_aliases(
    request: dict[str, Any],
    prior_result: dict[str, Any],
    *,
    index: int,
    planner_object_id: str,
    planner_target_receptacle_id: str,
    prior_result_match_kind: str,
) -> dict[str, Any]:
    source_request_id = str(request.get("request_id") or "")
    fallback = deepcopy(request)
    fallback["request_id"] = f"{source_request_id}_fallback_{index:02d}"
    fallback["ready"] = True
    fallback["source_request_id"] = source_request_id
    fallback["fallback_request"] = {
        "source_request_id": source_request_id,
        "reason": "prior_task_feasibility_blocked",
        "strategy": "alternate_planner_alias",
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_receptacle_id,
        "prior_status": str(prior_result.get("status") or ""),
        "prior_task_feasibility_status": str(prior_result.get("task_feasibility_status") or ""),
        "prior_blockers": _blockers(prior_result.get("blockers") or []),
        "agent_view_exposed": False,
    }
    fallback["fallback_request"].update(_prior_result_blocker_fields(prior_result))
    if prior_result_match_kind:
        fallback["fallback_request"]["prior_result_match_kind"] = prior_result_match_kind
    args = dict(fallback.get("planner_probe_args") or {})
    if planner_object_id:
        args["--cleanup-planner-object-id"] = planner_object_id
    if planner_target_receptacle_id:
        args["--cleanup-planner-target-receptacle-id"] = planner_target_receptacle_id
    fallback["planner_probe_args"] = args
    binding = fallback.get("binding")
    if isinstance(binding, dict):
        binding["planner_object_id"] = planner_object_id
        binding["planner_target_receptacle_id"] = planner_target_receptacle_id
        binding["planner_probe_args"] = args
        requested = binding.get("requested_cleanup_primitive_binding")
        if isinstance(requested, dict):
            requested["planner_object_id"] = planner_object_id
            requested["planner_target_receptacle_id"] = planner_target_receptacle_id
    return fallback


def _candidate_aliases(
    request: dict[str, Any],
    *,
    candidate_key: str,
    current_alias: str,
) -> list[str]:
    binding = request.get("binding") or {}
    backend_binding = (
        binding.get("backend_planner_task_binding") if isinstance(binding, dict) else {}
    )
    values = [current_alias]
    if isinstance(binding, dict):
        values.extend(str(item) for item in binding.get(candidate_key) or [])
    if isinstance(backend_binding, dict):
        values.extend(str(item) for item in backend_binding.get(candidate_key) or [])
    return _unique_nonempty_values(values)


def _executable_candidate_aliases(
    request: dict[str, Any],
    *,
    axis: str,
    candidate_key: str,
    current_alias: str,
    extra_aliases: list[str] | None = None,
    prior_filtered_aliases: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    source_request_id = str(request.get("request_id") or "")
    candidates = _unique_nonempty_values(
        [
            *_candidate_aliases(
                request,
                candidate_key=candidate_key,
                current_alias=current_alias,
            ),
            *(extra_aliases or []),
        ]
    )
    normalized = []
    if axis == "object":
        for alias in list(candidates):
            root_alias = _runtime_object_root_alias(alias)
            if not root_alias:
                continue
            normalized.append(
                {
                    "source_request_id": source_request_id,
                    "axis": axis,
                    "alias": alias,
                    "normalized_alias": root_alias,
                    "reason": "pickup_root_variant_normalized",
                    "evidence_note": (
                        "Normalized a non-root MolmoSpaces runtime pickup alias to "
                        "the variant-0 root-body alias before command generation."
                    ),
                }
            )
            if root_alias not in candidates:
                candidates.append(root_alias)
    executable = []
    filtered = []
    prior_filters = prior_filtered_aliases or {}
    for alias in candidates:
        prior_filter = prior_filters.get(alias)
        if prior_filter:
            filtered.append(dict(prior_filter))
            continue
        if axis == "object" and _is_non_root_runtime_object_alias(alias):
            filtered.append(
                {
                    "source_request_id": source_request_id,
                    "axis": axis,
                    "alias": alias,
                    "reason": "not_pickup_root_body_alias",
                    "evidence_note": (
                        "Filtered before command generation because pickup aliases "
                        "matching the MolmoSpaces runtime pattern must use variant 0 "
                        "to refer to a root body."
                    ),
                }
            )
            continue
        if _is_exact_scene_planner_alias(alias):
            executable.append(alias)
            continue
        filtered.append(
            {
                "source_request_id": source_request_id,
                "axis": axis,
                "alias": alias,
                "reason": "not_exact_scene_runtime_alias",
                "evidence_note": (
                    "Filtered before command generation because upstream/display aliases "
                    "with '|' fail exact-scene task sampling with KeyError."
                ),
            }
        )
    return executable, filtered, normalized


def _is_exact_scene_planner_alias(alias: str) -> bool:
    return bool(alias) and "|" not in alias


def _is_non_root_runtime_object_alias(alias: str) -> bool:
    match = _RUNTIME_ALIAS_RE.match(alias)
    return bool(match and match.group("variant") != "0")


def _runtime_object_root_alias(alias: str) -> str:
    match = _RUNTIME_ALIAS_RE.match(alias)
    if not match or match.group("variant") == "0":
        return ""
    return f"{match.group('prefix')}_{match.group('group')}_0_{match.group('room')}"


def proof_result_summary_from_commands(commands: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize generated proof outputs without replacing strict proof validation."""
    results = [_proof_result_from_command(item) for item in commands]
    proof_quality_summary = planner_proof_quality_summary(
        item for item in results if item.get("run_result_exists")
    )
    return {
        "schema": PLANNER_PROOF_RESULT_SUMMARY_SCHEMA,
        "expected_count": len(commands),
        "result_count": sum(1 for item in results if item["run_result_exists"]),
        "planner_backed_count": sum(1 for item in results if item["planner_backed"]),
        "blocked_count": sum(1 for item in results if item["status"] == "blocked_capability"),
        "timeout_count": sum(1 for item in results if _has_blocker_code(item, "timeout")),
        "rby1m_config_import_timeout_count": sum(
            1
            for item in results
            if _has_blocker_code(item, "timeout")
            and item.get("last_worker_stage") == "rby1m_config_import"
        ),
        "missing_result_count": sum(1 for item in results if not item["run_result_exists"]),
        "cleanup_binding_promoted_count": sum(
            1 for item in results if item["cleanup_binding_promoted"]
        ),
        "execution_attempted_count": sum(1 for item in results if item["execution_attempted"]),
        "task_feasibility_blocked_count": sum(
            1 for item in results if item["task_feasibility_status"] == "blocked"
        ),
        "grasp_feasibility_blocked_count": sum(
            1
            for item in results
            if item.get("task_feasibility_blocker_kind") == "grasp_feasibility"
        ),
        "grasp_feasibility_signature_count": len(grasp_feasibility_signature_counts(results)),
        "grasp_feasibility_signature_counts": grasp_feasibility_signature_counts(results),
        "worker_stage_event_count": sum(
            int(item.get("worker_stage_event_count") or 0) for item in results
        ),
        "last_worker_stage_counts": _last_worker_stage_counts(results),
        "view_artifact_count": sum(len(item.get("views") or []) for item in results),
        "proof_quality_summary": proof_quality_summary,
        "results": results,
        "evidence_note": (
            "Bundle-level summary of generated proof artifacts. Strict per-proof "
            "checkers still decide whether a proof is planner-backed."
        ),
    }


def _proof_result_from_command(item: dict[str, Any]) -> dict[str, Any]:
    run_result_path = Path(str(item.get("run_result") or ""))
    proof_report_path = Path(str(item.get("report") or ""))
    base = run_result_path.parent if str(run_result_path) else Path(".")
    result = {
        "request_id": str(item.get("request_id") or ""),
        "object_id": str(item.get("object_id") or ""),
        "target_receptacle_id": str(item.get("target_receptacle_id") or ""),
        "run_result": str(run_result_path),
        "report": str(proof_report_path),
        "run_result_exists": run_result_path.is_file(),
        "report_exists": proof_report_path.is_file(),
        "status": "not_run",
        "planner_backed": False,
        "cleanup_binding_promoted": False,
        "execution_attempted": False,
        "task_feasibility_status": "not_run",
        "visual_status": "not_run",
        "blockers": [],
        "cleanup_binding_blockers": [],
        "last_worker_stage": "",
        "worker_stage_event_count": 0,
        "worker_stage_events": [],
        "steps_executed": 0,
        "max_abs_qpos_delta": 0.0,
        "proof_quality": {},
        "stdout": "",
        "stderr": "",
        "views": [],
    }
    if not run_result_path.is_file():
        return result
    try:
        data = read_json_value(run_result_path, label="planner proof run result")
    except ValueError as exc:
        result.update(_unreadable_proof_result_payload(_proof_run_result_source_error(exc)))
        return result
    except OSError as exc:
        result.update(_unreadable_proof_result_payload(f"{type(exc).__name__}: {exc}"))
        return result
    if not isinstance(data, dict):
        result.update(_unreadable_proof_result_payload(f"non-object JSON: {type(data).__name__}"))
        return result
    evidence = data.get("manipulation_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    artifacts = data.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    blockers = _blockers(evidence.get("blockers") or [])
    cleanup_binding_blockers = _blockers(evidence.get("cleanup_primitive_binding_blockers") or [])
    cleanup_task_config = evidence.get("cleanup_task_config") or {}
    task_sampler_robot_placement_profile = (
        evidence.get("task_sampler_robot_placement_profile") or {}
    )
    cleanup_task_sampler_adapter = evidence.get("cleanup_task_sampler_adapter") or {}
    task_sampler_failure_diagnostics = evidence.get("task_sampler_failure_diagnostics") or {}
    blocker_kind = task_feasibility_blocker_kind(
        blockers,
        task_sampler_failure_diagnostics,
    )
    grasp_signature = grasp_feasibility_signature(task_sampler_failure_diagnostics)
    requested_binding = evidence.get("requested_cleanup_primitive_binding") or {}
    sampled_binding = evidence.get("sampled_task_binding") or {}
    cleanup_binding = evidence.get("cleanup_primitive_binding") or {}
    planner_backed = data.get("status") == "planner_backed"
    views = _proof_views(base, evidence)
    worker_stage_events = _compact_worker_stage_events(evidence.get("worker_stage_events") or [])
    proof_quality = planner_proof_quality_evidence(evidence)
    result.update(
        {
            "status": str(data.get("status") or "unknown"),
            "planner_backed": planner_backed,
            "cleanup_binding_promoted": bool(cleanup_binding),
            "execution_attempted": bool(evidence.get("execution_attempted")),
            "task_feasibility_status": _task_feasibility_status(
                status=str(data.get("status") or ""),
                planner_backed=planner_backed,
                cleanup_binding_promoted=bool(cleanup_binding),
                blockers=blockers,
                cleanup_binding_blockers=cleanup_binding_blockers,
                execution_attempted=bool(evidence.get("execution_attempted")),
            ),
            "task_feasibility_blocker_kind": blocker_kind,
            "task_feasibility_blocker_summary": task_feasibility_blocker_summary(
                blocker_kind,
                task_sampler_failure_diagnostics,
            ),
            "grasp_feasibility_signature": grasp_signature,
            "visual_status": "views_recorded" if views else "no_views_recorded",
            "blockers": blockers,
            "cleanup_binding_blockers": cleanup_binding_blockers,
            "last_worker_stage": str(evidence.get("last_worker_stage") or ""),
            "worker_stage_event_count": len(worker_stage_events),
            "worker_stage_events": worker_stage_events,
            "steps_executed": int(proof_quality.get("steps_executed") or 0),
            "max_abs_qpos_delta": float(proof_quality.get("max_abs_qpos_delta") or 0.0),
            "proof_quality": proof_quality,
            "stdout": _proof_artifact_path(base, artifacts, "stdout"),
            "stderr": _proof_artifact_path(base, artifacts, "stderr"),
            "cleanup_task_config": cleanup_task_config,
            "task_sampler_robot_placement_profile": task_sampler_robot_placement_profile,
            "cleanup_task_sampler_adapter": cleanup_task_sampler_adapter,
            "task_sampler_failure_diagnostics": task_sampler_failure_diagnostics,
            "requested_cleanup_primitive_binding": requested_binding,
            "sampled_task_binding": sampled_binding,
            "cleanup_primitive_binding": cleanup_binding,
            "views": views,
        }
    )
    return result


def _unreadable_proof_result_payload(message: str) -> dict[str, Any]:
    return {
        "status": "unreadable",
        "task_feasibility_status": "unknown",
        "visual_status": "unknown",
        "blockers": [
            {
                "code": "proof_run_result_unreadable",
                "message": message,
            }
        ],
    }


def _proof_run_result_source_error(exc: ValueError) -> str:
    cause = exc.__cause__
    if isinstance(cause, json.JSONDecodeError):
        return f"{type(cause).__name__}: {cause}"
    return f"{type(exc).__name__}: {exc}"


def _has_blocker_code(result: dict[str, Any], code: str) -> bool:
    blockers = [*(result.get("blockers") or []), *(result.get("cleanup_binding_blockers") or [])]
    return any(isinstance(item, dict) and str(item.get("code") or "") == code for item in blockers)


def _last_worker_stage_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        stage = str(item.get("last_worker_stage") or "")
        if stage:
            counts[stage] = counts.get(stage, 0) + 1
    return counts


def _compact_worker_stage_events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    events = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        compact = {}
        for key in ("elapsed_s", "event", "stage", "embodiment", "probe_mode"):
            value = item.get(key)
            if value not in (None, "", []):
                compact[key] = value
        if compact:
            events.append(compact)
    return events


def _proof_artifact_path(base: Path, artifacts: dict[str, Any], key: str) -> str:
    value = artifacts.get(key)
    if not value:
        return ""
    path = Path(str(value))
    return str(path if path.is_absolute() else base / path)


def _task_feasibility_status(
    *,
    status: str,
    planner_backed: bool,
    cleanup_binding_promoted: bool,
    blockers: list[dict[str, Any]],
    cleanup_binding_blockers: list[dict[str, Any]],
    execution_attempted: bool,
) -> str:
    codes = {str(item.get("code") or "") for item in blockers}
    messages = " ".join(str(item.get("message") or "") for item in blockers).lower()
    if "HouseInvalidForTask" in codes or "robot placement" in messages:
        return "blocked"
    if cleanup_binding_promoted:
        return "ready"
    if planner_backed:
        return "binding_not_promoted" if cleanup_binding_blockers else "ready"
    if not execution_attempted:
        return "not_reached"
    if status == "blocked_capability":
        return "blocked"
    return "unknown"


def _proof_views(base: Path, evidence: dict[str, Any]) -> list[dict[str, str]]:
    artifacts = evidence.get("image_artifacts") or {}
    if not isinstance(artifacts, dict):
        return []
    views = []
    for label, value in sorted(artifacts.items()):
        if not value:
            continue
        path = Path(str(value))
        views.append(
            {
                "label": str(label),
                "path": str(path if path.is_absolute() else base / path),
            }
        )
    return views


def _blockers(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        return [dict(raw)]
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def build_cleanup_rerun_command(
    *,
    runner_python: Path,
    cleanup_script: Path,
    cleanup_output_dir: Path,
    source_run_result: dict[str, Any],
    proof_run_results: list[Path],
) -> list[str]:
    command = [
        str(runner_python),
        str(cleanup_script),
        "--output-dir",
        str(cleanup_output_dir),
        "--seed",
        str(source_run_result.get("seed", 1)),
        "--static-fixture-projection-mode",
        str(source_run_result.get("static_fixture_projection_mode") or "room_only"),
        "--perception-mode",
        str(source_run_result.get("perception_mode") or "visible_object_detections"),
        "--generated-mess-count",
        str(source_run_result.get("requested_generated_mess_count") or 10),
        "--use-planner-proof-for-cleanup-primitives",
    ]
    backend = source_run_result.get("backend")
    if backend:
        command.extend(["--backend", str(backend)])
    if source_run_result.get("robot_name"):
        command.extend(["--include-robot", "--robot-name", str(source_run_result["robot_name"])])
    if source_run_result.get("robot_view_steps"):
        command.append("--record-robot-views")
    for proof in proof_run_results:
        command.extend(["--planner-proof-run-result", str(proof)])
    return command


def _planner_binding(
    *,
    contract: Any,
    object_id: str,
    target_receptacle_id: str,
    source_receptacle_id: str,
    tools: list[str],
) -> dict[str, Any]:
    binder = getattr(contract, "planner_observed_handle_binding", None)
    if not callable(binder):
        return {
            "ok": False,
            "status": "blocked_capability",
            "object_id": object_id,
            "target_receptacle_id": target_receptacle_id,
            "source_receptacle_id": source_receptacle_id,
            "tools": tools,
            "blockers": [
                {
                    "code": "planner_binding_unavailable",
                    "message": "Cleanup contract does not expose planner observed-handle binding.",
                }
            ],
        }
    return dict(
        binder(
            object_id,
            target_receptacle_id,
            source_receptacle_id=source_receptacle_id,
            tools=tools,
        )
    )


def _planner_scene(contract: Any) -> dict[str, Any]:
    backend = getattr(contract, "backend", None)
    scene_xml = str(getattr(backend, "scene_xml", "") or "")
    if not scene_xml:
        return {
            "schema": "planner_cleanup_proof_scene_v1",
            "available": False,
            "scene_xml": "",
            "backend": str(getattr(backend, "backend", "") or ""),
        }
    return {
        "schema": "planner_cleanup_proof_scene_v1",
        "available": True,
        "scene_xml": scene_xml,
        "backend": str(getattr(backend, "backend", "") or ""),
        "evidence_note": (
            "Real MolmoSpaces cleanup scene used to sample exact planner proof tasks."
        ),
    }


def _cleanup_tools(steps: list[dict[str, Any]]) -> list[str]:
    return canonical_cleanup_tool_sequence(
        [
            phase
            for phase in (str(step.get("phase") or "") for step in steps)
            if phase in SEMANTIC_SUBPHASE_LABELS
        ]
    )


def _request_tools(request: dict[str, Any]) -> list[str]:
    raw_tools = request.get("tools") or []
    if isinstance(raw_tools, str):
        values = raw_tools.split(",")
    else:
        values = [str(item) for item in raw_tools if str(item)]
    if not values:
        cleanup_tools = _planner_arg(request.get("planner_probe_args") or {}, "--cleanup-tools")
        values = cleanup_tools.split(",") if cleanup_tools else []
    return [
        tool for tool in canonical_cleanup_tool_sequence(values) if tool in SEMANTIC_SUBPHASE_LABELS
    ]


def _semantic_subphase_entries(tools: list[str]) -> list[dict[str, str]]:
    entries = []
    for phase in tools:
        label, detail = SEMANTIC_SUBPHASE_LABELS[phase]
        entries.append({"phase": phase, "label": label, "detail": detail})
    return entries


def _request_blockers(request: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    for blocker in request.get("blockers") or []:
        item = dict(blocker)
        item.setdefault("request_id", str(request.get("request_id") or ""))
        item.setdefault("object_id", str(request.get("object_id") or ""))
        item.setdefault("target_receptacle_id", str(request.get("target_receptacle_id") or ""))
        blockers.append(item)
    return blockers


def _proof_dir_name(index: int, request: dict[str, Any]) -> str:
    object_id = _safe_path_part(str(request.get("object_id") or "object"))
    target_id = _safe_path_part(str(request.get("target_receptacle_id") or "target"))
    return f"{index:03d}_{object_id}_to_{target_id}"


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)[:96]
