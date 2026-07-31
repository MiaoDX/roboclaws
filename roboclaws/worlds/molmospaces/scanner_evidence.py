"""Scanner evidence helpers for the MolmoSpaces scene sampler."""

from __future__ import annotations

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


def source_prep_next_action(prep_status: str) -> str:
    return _SOURCE_PREP_ACTIONS.get(prep_status, "inspect_source_prep")


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
