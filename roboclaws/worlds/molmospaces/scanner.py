"""Scanner evidence helpers for the MolmoSpaces scene sampler."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

_SOURCE_PREP_ACTIONS = {
    "complete": "none",
    "ready_for_scanner": "run_scanner_admission",
    "rejected_exhausted": "do_not_scan_without_new_human_curation",
    "gate_mismatch": "do_not_scan_without_gate_change",
    "blocked_prefilter_inconclusive": "run_scene_only_prefilter_or_stop",
    "blocked_molmospaces_module": "install_repo_dev_runtime",
    "blocked_scene_root": "configure_or_install_molmospaces_scene_root",
    "blocked_missing_resources": "run_manual_source_prep",
}


def scanner_required_gates() -> tuple[str, ...]:
    return (
        "source_asset_available",
        "preview_metadata",
        "public_room_count",
        "public_waypoints",
        "trusted_category_provenance",
        "map_build_artifacts",
    )


def scanner_preview_metadata(
    *,
    source: str,
    scene_index: int,
    preview_root: Path,
    backend: str,
) -> dict[str, Any] | None:
    path = preview_root / f"{world_id_slug(f'molmospaces/{source}/{scene_index}')}-preview.json"
    payload = _read_json_if_exists(path)
    if not payload:
        return None
    if (
        payload.get("scene_source") != source
        or payload.get("scene_index") != scene_index
        or payload.get("backend") != backend
    ):
        return None
    return payload


def scanner_product_smoke_artifacts(
    *,
    source: str,
    scene_index: int,
    product_smoke_root: Path,
) -> dict[str, Any]:
    root = product_smoke_root / world_id_slug(f"molmospaces/{source}/{scene_index}")
    run_dirs = sorted(
        [path for path in root.glob("*/seed-*") if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for run_dir in run_dirs:
        runtime_map_path = run_dir / "runtime_metric_map.json"
        run_result_path = run_dir / "run_result.json"
        runtime_map = _read_json_if_exists(runtime_map_path)
        run_result = _read_json_if_exists(run_result_path)
        if (runtime_map or {}).get("schema") != "runtime_metric_map_v1":
            continue
        return {
            "status": "available",
            "run_dir": str(run_dir),
            "runtime_metric_map": str(runtime_map_path),
            "run_result": str(run_result_path) if run_result_path.exists() else "",
            "runtime_map": runtime_map,
            "run_result_payload": run_result,
        }
    return {
        "status": "missing",
        "run_dir": "",
        "runtime_metric_map": "",
        "run_result": "",
        "runtime_map": {},
        "run_result_payload": {},
    }


def scanner_candidate_packet(
    *,
    packet: dict[str, Any],
    preview: dict[str, Any],
    smoke: dict[str, Any],
    preview_root: Path,
    required_views: tuple[str, ...],
) -> dict[str, Any]:
    room_count = max(_preview_room_count(preview), _runtime_room_count(smoke))
    waypoint_count = max(_preview_waypoint_count(preview), _runtime_waypoint_count(smoke))
    preview_statuses = _preview_statuses(preview)
    category_provenance = _scanner_category_provenance(smoke)
    map_build_ready = _scanner_map_build_ready(smoke)
    missing_gates = scanner_missing_gates(
        {
            **packet,
            "preview_statuses": preview_statuses,
            "room_count": room_count,
            "waypoint_count": waypoint_count,
            "category_provenance": category_provenance,
            "eval_ready": map_build_ready,
        },
        required_views=required_views,
    )
    quality_issue = _scanner_quality_issue(missing_gates)
    readiness_status = "blocked"
    failure_class = "environment_blocked"
    blocked_reason = _scanner_blocked_reason(
        source=str(packet.get("scene_source") or ""),
        scene_index=packet.get("scene_index"),
        missing_gates=missing_gates,
        smoke=smoke,
    )
    if map_build_ready and not quality_issue and not missing_gates:
        readiness_status = "ready"
        failure_class = ""
        blocked_reason = ""
    elif quality_issue:
        readiness_status = "rejected"
        failure_class = "map_actionability_failure"
        blocked_reason = quality_issue
    selected_reason = (
        "scanner_evidence_admitted_for_source_sampler"
        if readiness_status == "ready"
        else quality_issue or "scanner_evidence_incomplete_for_source_sampler"
    )
    return {
        **packet,
        "readiness_status": readiness_status,
        "lanes": [],
        "ui_ready": False,
        "eval_ready": readiness_status == "ready",
        "room_count": room_count,
        "waypoint_count": waypoint_count,
        "category_provenance": category_provenance,
        "category_manifest": "",
        "preview_statuses": preview_statuses,
        "preview_assets": scanner_preview_assets(
            source=str(packet.get("scene_source") or ""),
            scene_index=int(packet.get("scene_index") or 0),
            preview_root=preview_root,
            required_views=required_views,
        ),
        "selected_reason": selected_reason,
        "blocked_reason": blocked_reason,
        "failure_class": failure_class,
        "quality_score": _preview_quality_score(preview, required_views=required_views),
        "coverage_score": coverage_score(room_count=room_count, waypoint_count=waypoint_count),
        "scanner_evidence": {
            "preview_metadata": str(
                preview_root / f"{world_id_slug(str(packet.get('world_id') or ''))}-preview.json"
            ),
            "product_smoke_status": smoke.get("status", ""),
            "product_smoke_run_dir": smoke.get("run_dir", ""),
            "runtime_metric_map": smoke.get("runtime_metric_map", ""),
            "run_result": smoke.get("run_result", ""),
        },
    }


def scanner_missing_gates(
    candidate: dict[str, Any],
    *,
    required_views: tuple[str, ...],
) -> list[str]:
    missing = []
    candidate_file = candidate.get("candidate_file")
    if not isinstance(candidate_file, dict) or not candidate_file.get("exists"):
        missing.append("source_asset_available")
    preview_statuses = candidate.get("preview_statuses")
    if not isinstance(preview_statuses, dict) or not all(
        _scanner_preview_status_passes(preview_statuses.get(view)) for view in required_views
    ):
        missing.append("preview_metadata")
    if int(candidate.get("room_count") or 0) < 3:
        missing.append("public_room_count")
    if int(candidate.get("waypoint_count") or 0) < 3:
        missing.append("public_waypoints")
    if candidate.get("category_provenance") not in {
        "source_metadata",
        "prepared_visual_label_manifest",
        "prepared_visual_room_label_manifest",
    }:
        missing.append("trusted_category_provenance")
    if not candidate.get("eval_ready"):
        missing.append("map_build_artifacts")
    return missing


def scanner_next_action(candidate: dict[str, Any], *, missing_gates: list[str]) -> str:
    candidate_file = candidate.get("candidate_file")
    if "source_asset_available" in missing_gates:
        if (
            isinstance(candidate_file, dict)
            and candidate_file.get("status") == "missing_from_index_map"
        ):
            return "choose_valid_source_specific_candidate_index"
        return "run_manual_source_prep_before_scanner"
    if "preview_metadata" in missing_gates:
        return "render_preview_metadata_with_explicit_operator_command"
    if "map_build_artifacts" in missing_gates:
        return "run_map_build_product_smoke_before_eval_admission"
    return "run_scanner_admission_checks"


def scanner_admission_row(
    *,
    candidate: dict[str, Any],
    required_views: tuple[str, ...],
) -> dict[str, Any]:
    status = str(candidate.get("readiness_status") or "")
    if status == "ready":
        return {
            **_scanner_admission_row_base(candidate),
            "admission_status": "admitted",
            "lanes": candidate.get("lanes") or [],
            "passed_gates": list(scanner_required_gates()),
            "missing_gates": [],
            "next_action": "none",
        }
    if status == "rejected":
        return {
            **_scanner_admission_row_base(candidate),
            "admission_status": "rejected",
            "lanes": candidate.get("lanes") or [],
            "passed_gates": [],
            "missing_gates": [],
            "next_action": "do_not_scan_without_new_human_curation",
        }
    missing_gates = scanner_missing_gates(candidate, required_views=required_views)
    return {
        **_scanner_admission_row_base(candidate),
        "admission_status": "blocked",
        "lanes": [],
        "passed_gates": [gate for gate in scanner_required_gates() if gate not in missing_gates],
        "missing_gates": missing_gates,
        "next_action": scanner_next_action(candidate, missing_gates=missing_gates),
    }


def source_prep_next_action(prep_status: str) -> str:
    return _SOURCE_PREP_ACTIONS.get(prep_status, "inspect_source_prep")


def scanner_execution_candidate(
    *,
    install_candidate: dict[str, Any],
    admission: dict[str, Any],
) -> dict[str, Any]:
    world_id = str(install_candidate.get("world_id") or "")
    scene_source = str(install_candidate.get("scene_source") or "")
    scene_index = install_candidate.get("scene_index")
    missing_paths = [str(path) for path in install_candidate.get("missing_paths") or [] if path]
    candidate_file_exists = not missing_paths and bool(install_candidate.get("primary_path"))
    admission_status = str(admission.get("admission_status") or "")
    missing_gates = [str(gate) for gate in admission.get("missing_gates") or [] if gate]
    scanner_status = (
        "ready_for_product_smoke"
        if (
            admission_status != "rejected"
            and candidate_file_exists
            and "source_asset_available" not in missing_gates
        )
        else "blocked_missing_resources"
    )
    if admission_status == "rejected":
        scanner_status = "rejected_by_admission"
    if admission.get("next_action") == "choose_valid_source_specific_candidate_index":
        scanner_status = "blocked_invalid_candidate_index"
    next_action = (
        "run_preview_then_map_build_product_smoke"
        if scanner_status == "ready_for_product_smoke"
        else admission.get("next_action", "run_manual_source_prep_before_scanner")
    )
    if scanner_status == "rejected_by_admission":
        next_action = admission.get("next_action", "do_not_scan_without_new_human_curation")
    return {
        "scene_family": admission.get("scene_family", ""),
        "scene_split": admission.get("scene_split", ""),
        "scene_source": scene_source,
        "scene_index": scene_index,
        "world_id": world_id,
        "scanner_status": scanner_status,
        "admission_status": admission.get("admission_status", ""),
        "readiness_status": admission.get("readiness_status", ""),
        "lanes": admission.get("lanes") or [],
        "failure_class": admission.get("failure_class", ""),
        "blocked_reason": admission.get("blocked_reason", ""),
        "selected_reason": admission.get("selected_reason", ""),
        "room_count": admission.get("room_count", 0),
        "waypoint_count": admission.get("waypoint_count", 0),
        "category_provenance": admission.get("category_provenance", ""),
        "preview_statuses": admission.get("preview_statuses", {}),
        "passed_gates": admission.get("passed_gates") or [],
        "required_gates": admission.get("required_gates") or list(scanner_required_gates()),
        "missing_gates": missing_gates,
        "missing_paths": missing_paths,
        "candidate_file": admission.get("candidate_file", {}),
        "primary_path": install_candidate.get("primary_path", ""),
        "path_status": install_candidate.get("path_status", ""),
        "prefilter_status": install_candidate.get("prefilter_status", ""),
        "prefilter_reason": install_candidate.get("prefilter_reason", ""),
        "prefilter_score": int(install_candidate.get("prefilter_score") or 0),
        "cheap_room_count": int(install_candidate.get("cheap_room_count") or 0),
        "install_command": install_candidate.get("install_command", ""),
        "preview_command": preview_scanner_command(world_id),
        "map_build_product_smoke_command": map_build_product_smoke_command(world_id),
        "next_action": next_action,
    }


def scanner_execution_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_count": len(sources),
        "candidate_count": sum(
            int(source.get("candidate_count") or 0) for source in sources.values()
        ),
        "ready_for_product_smoke_count": sum(
            int(source.get("ready_for_product_smoke_count") or 0) for source in sources.values()
        ),
        "blocked_count": sum(int(source.get("blocked_count") or 0) for source in sources.values()),
        "blocked_source_count": sum(
            1
            for source in sources.values()
            if int(source.get("ready_for_product_smoke_count") or 0) == 0
            and int(source.get("candidate_count") or 0) > 0
        ),
        "ready_source_count": sum(
            1
            for source in sources.values()
            if int(source.get("ready_for_product_smoke_count") or 0) > 0
        ),
    }


def _scanner_admission_row_base(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_family": candidate.get("scene_family", ""),
        "scene_split": candidate.get("scene_split", ""),
        "scene_source": candidate.get("scene_source", ""),
        "scene_index": candidate.get("scene_index"),
        "world_id": candidate.get("world_id", ""),
        "readiness_status": candidate.get("readiness_status", ""),
        "failure_class": candidate.get("failure_class", ""),
        "blocked_reason": candidate.get("blocked_reason", ""),
        "selected_reason": candidate.get("selected_reason", ""),
        "room_count": candidate.get("room_count", 0),
        "waypoint_count": candidate.get("waypoint_count", 0),
        "category_provenance": candidate.get("category_provenance", ""),
        "preview_statuses": candidate.get("preview_statuses", {}),
        "candidate_file": candidate.get("candidate_file", {}),
        "required_gates": list(scanner_required_gates()),
    }


def next_flow_status(
    *,
    readiness_source: dict[str, Any],
    prep_source: dict[str, Any],
    scanner_source: dict[str, Any],
) -> str:
    if (
        readiness_source.get("ui_status") == "ready"
        and readiness_source.get("eval_status") == "complete"
    ):
        return "complete"
    if int(scanner_source.get("ready_for_product_smoke_count") or 0) > 0:
        return "scanner_ready"
    if int(scanner_source.get("gate_mismatch_count") or 0) > 0:
        return "gate_mismatch"
    prep_status = str(prep_source.get("prep_status") or "")
    if prep_status == "gate_mismatch":
        return "gate_mismatch"
    if prep_status == "rejected_exhausted":
        return "rejected_exhausted"
    if prep_status.startswith("blocked_"):
        return prep_status
    return "needs_scanner_or_selection"


def next_flow_next_action(
    *,
    readiness_source: dict[str, Any],
    selection_source: dict[str, Any],
    candidate_profile_source: dict[str, Any] | None = None,
    prep_source: dict[str, Any],
    scanner_source: dict[str, Any],
) -> str:
    if (
        readiness_source.get("ui_status") == "ready"
        and readiness_source.get("eval_status") == "complete"
    ):
        return "none"
    if int(scanner_source.get("ready_for_product_smoke_count") or 0) > 0:
        return "run_scanner_plan_for_ready_candidates"
    if int(scanner_source.get("gate_mismatch_count") or 0) > 0:
        return "do_not_scan_without_gate_change"
    selection_action = str(selection_source.get("next_action") or "")
    if selection_action == "expand_candidate_range":
        return "expand_candidate_range"
    prep_action = source_prep_next_action(str(prep_source.get("prep_status") or ""))
    if prep_action == "run_scene_only_prefilter_or_stop":
        return prep_action
    if prep_action != "inspect_source_prep":
        return prep_action
    profile_action = str((candidate_profile_source or {}).get("next_action") or "")
    if profile_action == "metadata_first_human_curation":
        return "metadata_first_human_curation"
    if selection_action:
        return selection_action
    return "inspect_next_flow_worklist"


def next_flow_missing_gate_counts(source_admission: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in source_admission.get("admission_rows") or []:
        if not isinstance(row, dict):
            continue
        for gate in row.get("missing_gates") or []:
            key = str(gate)
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def next_flow_blocked_reason_samples(
    *,
    projection_source: dict[str, Any],
    prep_source: dict[str, Any],
    scanner_source: dict[str, Any],
) -> list[str]:
    reasons = [
        *_projection_blocked_reasons(projection_source),
        *_prep_missing_resource_reasons(prep_source),
        *_scanner_candidate_blocked_reasons(scanner_source),
    ]
    deduped: list[str] = []
    for reason in reasons:
        if reason and reason not in deduped:
            deduped.append(reason)
        if len(deduped) == 3:
            break
    return deduped


def _projection_blocked_reasons(projection_source: dict[str, Any]) -> list[str]:
    return [
        str(row["blocked_reason"])
        for row in projection_source.get("blocked_rows") or []
        if isinstance(row, dict) and row.get("blocked_reason")
    ]


def _prep_missing_resource_reasons(prep_source: dict[str, Any]) -> list[str]:
    return [
        _missing_resource_reason(resource)
        for resource in prep_source.get("missing_resources") or []
        if isinstance(resource, dict) and _missing_resource_reason(resource)
    ]


def _missing_resource_reason(resource: dict[str, Any]) -> str:
    reason = str(resource.get("reason") or "")
    path = str(resource.get("path") or "")
    if reason and path:
        return f"{reason}: {path}"
    return reason


def _scanner_candidate_blocked_reasons(scanner_source: dict[str, Any]) -> list[str]:
    return [
        str(candidate["blocked_reason"])
        for candidate in scanner_source.get("candidates") or []
        if isinstance(candidate, dict) and candidate.get("blocked_reason")
    ]


def next_flow_artifact_paths(*, output_dir: Path | None) -> dict[str, str]:
    base = output_dir or Path("output/scene-sampler-readiness")
    scanner_dir = Path("output/scene-sampler-scanner")
    return {
        "readiness_output_dir": str(base),
        "scene_prefilter": str(base / "scene_sampler_scene_prefilter.json"),
        "source_prep": str(base / "scene_sampler_source_prep.json"),
        "scanner_execution_plan": str(base / "scene_sampler_scanner_execution_plan.json"),
        "next_flow_worklist": str(base / "scene_sampler_next_flow_worklist.json"),
        "source_prep_run": str(scanner_dir / "source_prep_run.json"),
        "scanner_run": str(scanner_dir / "scanner_run.json"),
    }


def next_flow_recommended_commands(
    *,
    source: str,
    next_action: str,
    recommended_candidate_range: str,
    artifact_paths: dict[str, str],
) -> list[dict[str, str]]:
    if next_action in {
        "none",
        "do_not_scan_without_gate_change",
        "do_not_scan_without_new_human_curation",
    }:
        return []
    source_arg = shlex.quote(source)
    candidate_range = recommended_candidate_range or "0:19"
    if next_action == "metadata_first_human_curation":
        return [
            {
                "name": "refresh_scene_only_prefilter",
                "command": (
                    ".venv/bin/python scripts/operator_console/"
                    "export_scene_sampler_readiness.py "
                    f"--output-dir {_quote_artifact_path(artifact_paths, 'readiness_output_dir')} "
                    f"--candidate-range {shlex.quote(candidate_range)} --no-generated-eval"
                ),
                "execution_policy": "no_download_no_backend_no_vlm_gate",
            },
            {
                "name": "inspect_scene_prefilter",
                "command": (
                    ".venv/bin/python - <<'PY'\n"
                    "import json\n"
                    "from pathlib import Path\n"
                    f"path = Path({artifact_paths['scene_prefilter']!r})\n"
                    "payload = json.loads(path.read_text())\n"
                    f"print(json.dumps(payload['sources'][{source!r}], indent=2))\n"
                    "PY"
                ),
                "execution_policy": "read_only_prefilter_inspection",
            },
        ]
    if next_action == "run_scene_only_prefilter_or_stop":
        return [
            {
                "name": "refresh_scene_only_prefilter",
                "command": (
                    ".venv/bin/python scripts/operator_console/"
                    "export_scene_sampler_readiness.py "
                    f"--output-dir {_quote_artifact_path(artifact_paths, 'readiness_output_dir')} "
                    f"--candidate-range {shlex.quote(candidate_range)} --no-generated-eval"
                ),
                "execution_policy": "no_download_no_backend_no_vlm_gate",
            },
            {
                "name": "inspect_prefilter_stop_reason",
                "command": (
                    ".venv/bin/python - <<'PY'\n"
                    "import json\n"
                    "from pathlib import Path\n"
                    f"path = Path({artifact_paths['scene_prefilter']!r})\n"
                    "payload = json.loads(path.read_text())\n"
                    f"print(json.dumps(payload['sources'][{source!r}], indent=2))\n"
                    "PY"
                ),
                "execution_policy": "read_only_prefilter_inspection",
            },
        ]
    prep_base = (
        ".venv/bin/python scripts/operator_console/run_scene_sampler_source_prep.py "
        f"--prep {_quote_artifact_path(artifact_paths, 'source_prep')} "
        f"--worklist {_quote_artifact_path(artifact_paths, 'next_flow_worklist')} "
        f"--output {_quote_artifact_path(artifact_paths, 'source_prep_run')} "
        f"--source {source_arg}"
    )
    scanner_base = (
        ".venv/bin/python scripts/operator_console/run_scene_sampler_scanner_plan.py "
        f"--plan {_quote_artifact_path(artifact_paths, 'scanner_execution_plan')} "
        f"--worklist {_quote_artifact_path(artifact_paths, 'next_flow_worklist')} "
        f"--output {_quote_artifact_path(artifact_paths, 'scanner_run')} "
        f"--source {source_arg}"
    )
    commands = [
        {
            "name": "source_prep_dry_run",
            "command": prep_base,
            "execution_policy": "dry_run_default",
        },
        {
            "name": "source_prep_execute",
            "command": f"{prep_base} --execute",
            "execution_policy": "manual_operator_only",
        },
        {
            "name": "refresh_readiness_after_prep",
            "command": (
                ".venv/bin/python scripts/operator_console/export_scene_sampler_readiness.py "
                f"--output-dir {_quote_artifact_path(artifact_paths, 'readiness_output_dir')} "
                f"--candidate-range {shlex.quote(candidate_range)} "
                f"--require-selection-capacity-source {source_arg} "
                f"--require-scanner-ready-source {source_arg} "
                "--no-generated-eval"
            ),
            "execution_policy": "no_download_no_vlm_gate",
        },
        {
            "name": "scanner_dry_run",
            "command": f"{scanner_base} --dry-run",
            "execution_policy": "dry_run_default",
        },
        {
            "name": "scanner_execute_ready_candidates",
            "command": scanner_base,
            "execution_policy": "ready_candidates_only",
        },
    ]
    if next_action == "expand_candidate_range":
        commands.insert(
            0,
            {
                "name": "expand_candidate_range",
                "command": (
                    ".venv/bin/python scripts/operator_console/"
                    "export_scene_sampler_readiness.py "
                    f"--output-dir {_quote_artifact_path(artifact_paths, 'readiness_output_dir')} "
                    f"--candidate-range {shlex.quote(candidate_range)} "
                    f"--require-selection-capacity-source {source_arg} --no-generated-eval"
                ),
                "execution_policy": "no_download_no_vlm_gate",
            },
        )
    return commands


def _quote_artifact_path(artifact_paths: dict[str, str], key: str) -> str:
    return shlex.quote(str(artifact_paths[key]))


def next_flow_scan_world_ids(selection_source: dict[str, Any]) -> list[str]:
    world_ids: list[str] = []
    for key in ("next_ui_scan_world_ids", "next_eval_scan_world_ids"):
        for world_id in selection_source.get(key) or []:
            raw_world_id = str(world_id or "")
            if raw_world_id and raw_world_id not in world_ids:
                world_ids.append(raw_world_id)
    for candidate in selection_source.get("next_scan_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        raw_world_id = str(candidate.get("world_id") or "")
        if raw_world_id and raw_world_id not in world_ids:
            world_ids.append(raw_world_id)
    return world_ids


def next_flow_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    actionable_sources = [
        source for source in sources.values() if source.get("next_action") != "none"
    ]
    return {
        "source_count": len(sources),
        "complete_source_count": sum(
            1 for source in sources.values() if source.get("flow_status") == "complete"
        ),
        "incomplete_source_count": len(actionable_sources),
        "ui_supported_source_count": sum(
            1 for source in sources.values() if source.get("ui_status") == "ready"
        ),
        "eval_complete_source_count": sum(
            1 for source in sources.values() if source.get("eval_status") == "complete"
        ),
        "ui_needed_count": sum(
            int(source.get("ui_needed_count") or 0) for source in sources.values()
        ),
        "eval_needed_count": sum(
            int(source.get("eval_needed_count") or 0) for source in sources.values()
        ),
        "scanner_ready_source_count": sum(
            1
            for source in sources.values()
            if int(source.get("scanner_ready_candidate_count") or 0) > 0
        ),
        "source_prep_required_count": sum(
            1
            for source in sources.values()
            if str(source.get("next_action") or "")
            in {
                "run_manual_source_prep",
                "configure_or_install_molmospaces_scene_root",
                "install_repo_dev_runtime",
            }
        ),
        "rejected_exhausted_source_count": sum(
            1 for source in sources.values() if source.get("flow_status") == "rejected_exhausted"
        ),
        "gate_mismatch_source_count": sum(
            1 for source in sources.values() if source.get("flow_status") == "gate_mismatch"
        ),
        "metadata_worklist_source_count": sum(
            1
            for source in sources.values()
            if int(source.get("metadata_worklist_candidate_count") or 0) > 0
        ),
        "metadata_worklist_candidate_count": sum(
            int(source.get("metadata_worklist_candidate_count") or 0) for source in sources.values()
        ),
        "next_actions": _next_flow_action_counts(actionable_sources),
        "worklist": [_next_flow_worklist_item(source) for source in actionable_sources],
    }


def _next_flow_action_counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        action = str(source.get("next_action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))


def _next_flow_worklist_item(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": source.get("scene_source", ""),
        "flow_status": source.get("flow_status", ""),
        "next_action": source.get("next_action", ""),
        "ui_needed_count": int(source.get("ui_needed_count") or 0),
        "eval_needed_count": int(source.get("eval_needed_count") or 0),
        "selection_capacity_status": source.get("selection_capacity_status", ""),
        "candidate_profile_status": source.get("candidate_profile_status", ""),
        "prep_status": source.get("prep_status", ""),
        "metadata_worklist_candidate_count": int(
            source.get("metadata_worklist_candidate_count") or 0
        ),
        "metadata_worklist_world_ids": source.get("metadata_worklist_world_ids") or [],
        "scene_prefilter_status": source.get("scene_prefilter_status", ""),
        "scene_prefilter_candidate_count": int(source.get("scene_prefilter_candidate_count") or 0),
        "scene_prefilter_high_confidence_candidate_count": int(
            source.get("scene_prefilter_high_confidence_candidate_count") or 0
        ),
        "scene_prefilter_expensive_proof_candidate_count": int(
            source.get("scene_prefilter_expensive_proof_candidate_count") or 0
        ),
        "scene_prefilter_expensive_proof_world_ids": source.get(
            "scene_prefilter_expensive_proof_world_ids"
        )
        or [],
        "scanner_ready_candidate_count": int(source.get("scanner_ready_candidate_count") or 0),
        "scanner_gate_mismatch_count": int(source.get("scanner_gate_mismatch_count") or 0),
        "next_scan_world_ids": source.get("next_scan_world_ids") or [],
        "recommended_candidate_range": source.get("recommended_candidate_range", ""),
    }


def scanner_gate_mismatch_count(scanner_source: dict[str, Any]) -> int:
    """Count scanner candidates that ran proof but still fail public admission gates."""

    count = 0
    for candidate in scanner_source.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("scanner_status") != "rejected_by_admission":
            continue
        evidence = candidate.get("scanner_evidence")
        if not isinstance(evidence, dict):
            continue
        if evidence.get("product_smoke_status") == "available":
            count += 1
    return count


def scanner_admission_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing_gate_counts: dict[str, int] = {}
    for source in sources.values():
        for row in source.get("admission_rows") or []:
            if not isinstance(row, dict):
                continue
            for gate in row.get("missing_gates") or []:
                key = str(gate)
                missing_gate_counts[key] = missing_gate_counts.get(key, 0) + 1
    return {
        "source_count": len(sources),
        "admitted_count": sum(
            int((source.get("summary") or {}).get("admitted_count") or 0)
            for source in sources.values()
        ),
        "blocked_count": sum(
            int((source.get("summary") or {}).get("blocked_count") or 0)
            for source in sources.values()
        ),
        "rejected_count": sum(
            int((source.get("summary") or {}).get("rejected_count") or 0)
            for source in sources.values()
        ),
        "missing_gate_counts": dict(sorted(missing_gate_counts.items())),
    }


def preview_scanner_command(world_id: str) -> str:
    return (
        ".venv/bin/python scripts/operator_console/render_scene_previews.py "
        f"--world {world_id} "
        "--output-dir output/scene-sampler-scanner/previews "
        "--work-dir output/scene-sampler-scanner/work"
    )


def map_build_product_smoke_command(world_id: str) -> str:
    return (
        "just run::surface surface=household-world "
        f"world={world_id} "
        "backend=mujoco preset=map-build agent_engine=direct-runner "
        "evidence_lane=world-public-labels seed=7 scenario_setup=baseline "
        f"output_dir=output/scene-sampler-scanner/product-smoke/{world_id_slug(world_id)}"
    )


def scanner_preview_assets(
    *,
    source: str,
    scene_index: int,
    preview_root: Path,
    required_views: tuple[str, ...],
) -> list[dict[str, str]]:
    slug = world_id_slug(f"molmospaces/{source}/{scene_index}")
    return [
        {"view": view, "path": str(preview_root / f"{slug}-{view}.png")} for view in required_views
    ]


def coverage_score(*, room_count: int, waypoint_count: int) -> float:
    return round(min(1.0, (room_count / 10.0 + waypoint_count / 20.0) / 2.0), 3)


def world_id_slug(world_id: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in world_id).strip("-")


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label="scene sampler scanner optional JSON")
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _preview_statuses(preview: dict[str, Any]) -> dict[str, str]:
    views = preview.get("views") if isinstance(preview.get("views"), dict) else {}
    return {
        view: str((payload.get("image_diagnostics") or {}).get("visual_status") or "")
        for view, payload in views.items()
        if isinstance(payload, dict)
    }


def _preview_room_count(preview: dict[str, Any]) -> int:
    return int(preview.get("room_count") or 0)


def _preview_waypoint_count(preview: dict[str, Any]) -> int:
    return int(preview.get("waypoint_count") or 0)


def _preview_quality_score(
    preview: dict[str, Any],
    *,
    required_views: tuple[str, ...],
) -> float:
    statuses = _preview_statuses(preview)
    reviewable_count = sum(1 for view in required_views if statuses.get(view) == "reviewable")
    return round(reviewable_count / len(required_views), 3)


def _runtime_room_count(smoke: dict[str, Any]) -> int:
    runtime_map = smoke.get("runtime_map")
    if not isinstance(runtime_map, dict):
        return 0
    return len(
        {
            str(room.get("room_id") or "")
            for room in runtime_map.get("rooms") or []
            if isinstance(room, dict) and room.get("room_id")
        }
    )


def _runtime_waypoint_count(smoke: dict[str, Any]) -> int:
    runtime_map = smoke.get("runtime_map")
    if not isinstance(runtime_map, dict):
        return 0
    waypoint_ids = {
        str(candidate.get("waypoint_id") or "")
        for candidate in runtime_map.get("generated_exploration_candidates") or []
        if isinstance(candidate, dict) and candidate.get("waypoint_id")
    }
    if waypoint_ids:
        return len(waypoint_ids)
    return len(
        [
            candidate
            for candidate in runtime_map.get("target_candidates") or []
            if isinstance(candidate, dict)
            and candidate.get("candidate_type") == "generated_exploration_candidate"
        ]
    )


def _scanner_category_provenance(smoke: dict[str, Any]) -> str:
    runtime_map = smoke.get("runtime_map")
    if not isinstance(runtime_map, dict):
        return "unavailable"
    rooms = [room for room in runtime_map.get("rooms") or [] if isinstance(room, dict)]
    if any(room.get("public_room_source") == "base_metric_map" for room in rooms):
        return "source_metadata"
    hints = [
        hint for hint in runtime_map.get("room_category_hints") or [] if isinstance(hint, dict)
    ]
    if any(hint.get("classification_status") == "map_prior" for hint in hints):
        return "source_metadata"
    return "unavailable"


def _scanner_map_build_ready(smoke: dict[str, Any]) -> bool:
    runtime_map = smoke.get("runtime_map")
    if not isinstance(runtime_map, dict) or runtime_map.get("schema") != "runtime_metric_map_v1":
        return False
    run_result = smoke.get("run_result_payload")
    if isinstance(run_result, dict) and run_result.get("terminate_reason"):
        return str(run_result.get("terminate_reason") or "").endswith("complete")
    return True


def _scanner_quality_issue(missing_gates: list[str]) -> str:
    if "source_asset_available" in missing_gates or "map_build_artifacts" in missing_gates:
        return ""
    if "preview_metadata" in missing_gates:
        return "preview_not_reviewable"
    if "public_room_count" in missing_gates:
        return "fewer_than_three_public_navigation_areas"
    if "public_waypoints" in missing_gates:
        return "fewer_than_three_public_waypoints"
    if "trusted_category_provenance" in missing_gates:
        return "missing_trusted_category_provenance"
    return ""


def _scanner_blocked_reason(
    *,
    source: str,
    scene_index: Any,
    missing_gates: list[str],
    smoke: dict[str, Any],
) -> str:
    if "source_asset_available" in missing_gates:
        return (
            f"{source}/{scene_index} source asset is unavailable; run manual source prep "
            "before scanner admission."
        )
    if "map_build_artifacts" in missing_gates:
        if smoke.get("status") == "available":
            return (
                f"{source}/{scene_index} map-build smoke artifact did not satisfy scanner "
                "admission."
            )
        return (
            f"{source}/{scene_index} is missing map-build product-smoke runtime_metric_map.json; "
            "run scanner product smoke before eval admission."
        )
    if missing_gates:
        return f"{source}/{scene_index} is missing scanner gates: {', '.join(missing_gates)}"
    return ""


def _scanner_preview_status_passes(status: Any) -> bool:
    return str(status or "") in {"available", "reviewable"}
