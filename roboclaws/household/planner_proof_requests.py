from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from roboclaws.household.planner_grasp_cache import grasp_cache_availability_preflight
from roboclaws.household.planner_grasp_cache_generation import grasp_cache_generation_preflight
from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA,
    PLANNER_PROOF_EXECUTION_HORIZON_SCHEMA,
    PLANNER_PROOF_REQUESTS_SCHEMA,
)
from roboclaws.household.planner_proof_fallbacks import (
    planner_arg as _planner_arg,
)
from roboclaws.household.planner_proof_fallbacks import (
    prior_fallback_candidate_filters_by_source_request,
)
from roboclaws.household.planner_proof_results import (
    proof_result_summary_from_commands as _proof_result_summary_from_commands,
)
from roboclaws.household.planner_proof_selection import (
    generated_ready_proof_requests,
    selected_request_ids,
)
from roboclaws.household.planner_proof_selection import (
    proof_request_selection_from_summary as _proof_request_selection_from_summary,
)
from roboclaws.household.planner_task_feasibility import grasp_feasibility_mitigation_decision
from roboclaws.household.semantic_timeline import (
    SEMANTIC_SUBPHASE_LABELS,
    canonical_cleanup_tool_sequence,
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
    selected_ids = selected_request_ids(request_selection)
    requests = [
        *(manifest.get("requests") or []),
        *generated_ready_proof_requests(request_selection),
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
    selection = proof_request_selection or _proof_request_selection_from_summary(proof_requests)
    summary = proof_result_summary or _proof_result_summary_from_commands(commands)
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
