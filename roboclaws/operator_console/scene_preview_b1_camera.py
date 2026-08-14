"""B1 camera-preview candidate validation and promotion."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract
from roboclaws.maps.bundle import (
    static_landmarks_from_fixture_projection,
    write_nav2_map_bundle_snapshot,
)
from roboclaws.operator_console.scene_preview_common import _fit_preview_image, _image_diagnostics

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_molmospaces_backend_state(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="MolmoSpaces backend state")


def _b1_metadata_has_real_camera_previews(
    path: Path,
    *,
    camera_artifact: Path | None = None,
) -> bool:
    payload = read_json_object(path, label="B1 preview metadata")
    if camera_artifact is not None and not _b1_metadata_camera_artifact_matches(
        payload,
        camera_artifact=camera_artifact,
    ):
        return False
    return _b1_metadata_payload_has_real_camera_previews(payload)


def _b1_metadata_camera_artifact_matches(
    payload: dict[str, Any],
    *,
    camera_artifact: Path,
) -> bool:
    artifact = payload.get("camera_preview_artifact")
    if not isinstance(artifact, dict):
        return False
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        artifact_hash = str(artifact.get("source_artifact_sha256") or "").strip()
        if artifact_hash:
            return camera_artifact.is_file() and artifact_hash == _file_sha256(camera_artifact)
        return str(artifact.get("source_artifact_name") or "").strip() == camera_artifact.name
    return Path(raw_path).resolve() == camera_artifact.resolve()


def _portable_b1_artifact_view_ref(*, artifact_path: Path, view_path: Path) -> str:
    artifact_path = artifact_path.resolve()
    view_path = view_path.resolve()
    try:
        return view_path.relative_to(artifact_path.parent).as_posix()
    except ValueError:
        return view_path.name


def _b1_metadata_payload_has_real_camera_previews(payload: dict[str, Any]) -> bool:
    views = payload.get("views")
    if not isinstance(views, dict):
        return False
    fpv = views.get("fpv")
    chase = views.get("chase")
    if not isinstance(fpv, dict) or not isinstance(chase, dict):
        return False
    if not str(fpv.get("provenance") or "").startswith("isaac_runtime_") or not str(
        chase.get("provenance") or ""
    ).startswith("isaac_runtime_"):
        return False
    fpv_waypoint = str(fpv.get("waypoint_id") or "").strip()
    chase_waypoint = str(chase.get("waypoint_id") or "").strip()
    if not fpv_waypoint or fpv_waypoint != chase_waypoint:
        return False
    fpv_alignment = str(fpv.get("alignment_artifact") or "").strip()
    chase_alignment = str(chase.get("alignment_artifact") or "").strip()
    if not fpv_alignment or fpv_alignment != chase_alignment:
        return False
    fpv_transform = str(fpv.get("alignment_transform_source") or "").strip()
    chase_transform = str(chase.get("alignment_transform_source") or "").strip()
    if fpv_transform != "reviewed_correspondence_fit" or chase_transform != fpv_transform:
        return False
    artifact = payload.get("camera_preview_artifact")
    if not isinstance(artifact, dict):
        return False
    if str(artifact.get("selected_waypoint_id") or "").strip() != fpv_waypoint:
        return False
    if str(artifact.get("alignment_artifact") or "").strip() != fpv_alignment:
        return False
    return str(artifact.get("alignment_transform_source") or "").strip() == fpv_transform


def _promote_b1_camera_previews(
    *,
    camera_artifact: Path,
    fpv_path: Path,
    chase_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    if not camera_artifact.is_file():
        return {
            "status": "artifact_missing",
            "artifact_path": str(camera_artifact),
        }
    try:
        payload = read_json_object(camera_artifact, label="B1 camera preview artifact")
    except (OSError, ValueError) as exc:
        return {
            "status": "artifact_unreadable",
            "artifact_path": str(camera_artifact),
            "reason": str(exc),
        }
    candidate_results = _evaluate_b1_camera_preview_candidates(
        payload=payload,
        camera_artifact=camera_artifact,
    )
    candidates = candidate_results["candidates"]
    evaluated = candidate_results["evaluated"]
    accepted = candidate_results["accepted"]
    if not accepted:
        return {
            "status": "no_usable_camera_pair",
            "artifact_path": str(camera_artifact),
            "candidate_count": len(candidates),
            "evaluated_candidates": evaluated,
        }
    selected = accepted[0]
    fpv_source = Path(str(selected["fpv_source"]))
    chase_source = Path(str(selected["chase_source"]))
    _fit_preview_image(Image.open(fpv_source), width=width, height=height).save(fpv_path)
    _fit_preview_image(Image.open(chase_source), width=width, height=height).save(chase_path)
    selected_label = str(selected.get("label") or "")
    selected_action = str(selected.get("action") or "")
    selected_waypoint = str(selected.get("waypoint_id") or "")
    camera_control_contract = selected.get("camera_control_contract")
    if not isinstance(camera_control_contract, dict):
        camera_control_contract = {}
    agent_facing_fpv = (
        camera_control_contract.get("agent_facing_fpv")
        if isinstance(camera_control_contract.get("agent_facing_fpv"), dict)
        else {}
    )
    report_chase = (
        camera_control_contract.get("report_chase_view")
        if isinstance(camera_control_contract.get("report_chase_view"), dict)
        else {}
    )
    return {
        "status": "promoted",
        "selection_status": "selected_first_accepted_real_isaac_camera_pair",
        "artifact": {
            "source_artifact_name": camera_artifact.name,
            "source_artifact_sha256": _file_sha256(camera_artifact),
            "source_artifact_status": "external_local_verification_artifact",
            "schema": payload.get("schema") or payload.get("contract") or "",
            "source_kind": selected.get("source_kind"),
            "selected_label": selected_label,
            "selected_action": selected_action,
            "selected_waypoint_id": selected_waypoint,
            "alignment_artifact": selected.get("alignment_artifact")
            or payload.get("alignment_artifact")
            or "",
            "alignment_transform_source": selected.get("alignment_transform_source")
            or payload.get("alignment_transform_source")
            or "",
            "candidate_count": len(candidates),
            "accepted_candidate_count": len(accepted),
        },
        "evaluated_candidates": evaluated,
        "views": {
            "fpv": {
                "path": fpv_path.name,
                "view": "raw_fpv",
                "waypoint_id": selected_waypoint,
                "alignment_artifact": selected.get("alignment_artifact")
                or payload.get("alignment_artifact")
                or "",
                "alignment_transform_source": selected.get("alignment_transform_source")
                or payload.get("alignment_transform_source")
                or "",
                "action": selected_action,
                "label": selected_label,
                "camera": agent_facing_fpv.get("camera_prim_path") or "/World/robot_0/head_camera",
                "provenance": "isaac_runtime_robot_mounted_head_camera_fpv",
                "source_artifact_view": _portable_b1_artifact_view_ref(
                    artifact_path=camera_artifact,
                    view_path=fpv_source,
                ),
                "source": agent_facing_fpv.get("source")
                or "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
                "robot_mounted": agent_facing_fpv.get("robot_mounted", True),
                "head_camera_equivalent": agent_facing_fpv.get("head_camera_equivalent", False),
                "image_diagnostics": _image_diagnostics(fpv_path),
            },
            "chase": {
                "path": chase_path.name,
                "view": "chase_camera",
                "waypoint_id": selected_waypoint,
                "alignment_artifact": selected.get("alignment_artifact")
                or payload.get("alignment_artifact")
                or "",
                "alignment_transform_source": selected.get("alignment_transform_source")
                or payload.get("alignment_transform_source")
                or "",
                "action": selected_action,
                "label": selected_label,
                "camera": report_chase.get("camera_prim_path") or "robot_relative_chase_camera",
                "provenance": "isaac_runtime_report_chase_camera",
                "source_artifact_view": _portable_b1_artifact_view_ref(
                    artifact_path=camera_artifact,
                    view_path=chase_source,
                ),
                "source": report_chase.get("source") or "backend_local_report_chase_camera",
                "policy_note": "Chase is report evidence, not agent-facing policy input.",
                "image_diagnostics": _image_diagnostics(chase_path),
            },
        },
    }


def _evaluate_b1_camera_preview_candidates(
    *,
    payload: dict[str, Any],
    camera_artifact: Path,
) -> dict[str, Any]:
    candidates = _b1_camera_preview_candidates(payload, artifact_path=camera_artifact)
    evaluated = [
        _evaluate_b1_camera_preview_candidate(
            payload=payload,
            camera_artifact=camera_artifact,
            candidate=candidate,
        )
        for candidate in candidates
    ]
    accepted = [item for item in evaluated if item.get("status") == "accepted"]
    return {"candidates": candidates, "evaluated": evaluated, "accepted": accepted}


def _evaluate_b1_camera_preview_candidate(
    *,
    payload: dict[str, Any],
    camera_artifact: Path,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    fpv_source = _resolve_b1_artifact_view_path(camera_artifact, candidate.get("fpv"))
    chase_source = _resolve_b1_artifact_view_path(camera_artifact, candidate.get("chase"))
    candidate_result = {
        "label": candidate.get("label"),
        "action": candidate.get("action"),
        "waypoint_id": candidate.get("waypoint_id"),
        "source_kind": candidate.get("source_kind"),
        "fpv_source": str(fpv_source) if fpv_source is not None else "",
        "chase_source": str(chase_source) if chase_source is not None else "",
    }
    provenance_errors = _b1_camera_preview_provenance_errors(payload, candidate)
    if provenance_errors:
        return {
            **candidate_result,
            "status": "provenance_rejected",
            "provenance_errors": provenance_errors,
        }
    if fpv_source is None or chase_source is None:
        return {**candidate_result, "status": "missing_view_path"}
    if not fpv_source.is_file() or not chase_source.is_file():
        return {**candidate_result, "status": "missing_view_file"}
    return _evaluate_b1_camera_preview_quality(
        candidate=candidate,
        candidate_result=candidate_result,
        fpv_source=fpv_source,
        chase_source=chase_source,
    )


def _evaluate_b1_camera_preview_quality(
    *,
    candidate: dict[str, Any],
    candidate_result: dict[str, Any],
    fpv_source: Path,
    chase_source: Path,
) -> dict[str, Any]:
    fpv_diagnostics = _image_diagnostics(fpv_source)
    chase_diagnostics = _image_diagnostics(chase_source)
    errors = [
        *(f"fpv: {error}" for error in _b1_camera_preview_quality_errors(fpv_diagnostics)),
        *(f"chase: {error}" for error in _b1_camera_preview_quality_errors(chase_diagnostics)),
    ]
    result = {
        **candidate_result,
        "fpv_diagnostics": fpv_diagnostics,
        "chase_diagnostics": chase_diagnostics,
        "quality_errors": errors,
    }
    if errors:
        return {**result, "status": "quality_rejected"}
    return {
        **result,
        "status": "accepted",
        "score": _b1_camera_preview_score(fpv_diagnostics)
        + (_b1_camera_preview_score(chase_diagnostics) * 0.75),
        "camera_control_contract": candidate.get("camera_control_contract"),
    }


def _b1_camera_preview_candidates(
    payload: dict[str, Any],
    *,
    artifact_path: Path,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, step in enumerate(payload.get("robot_view_steps") or []):
        if not isinstance(step, dict):
            continue
        views = step.get("views")
        if not isinstance(views, dict):
            continue
        candidates.append(
            {
                "source_kind": "run_result_robot_view_step",
                "label": step.get("label")
                or _b1_camera_label_from_view_path(views.get("fpv"))
                or f"robot_view_step_{index:03d}",
                "action": step.get("action"),
                "waypoint_id": step.get("waypoint_id")
                or step.get("current_waypoint_id")
                or step.get("room_id"),
                "robot_pose_applied": step.get("robot_pose_applied"),
                "alignment_artifact": step.get("alignment_artifact"),
                "alignment_transform_source": step.get("alignment_transform_source"),
                "fpv": views.get("fpv"),
                "chase": views.get("chase"),
                "camera_control_contract": step.get("camera_control_contract"),
            }
        )
    if candidates:
        return candidates
    for index, item in enumerate(payload.get("waypoint_evidence") or []):
        if not isinstance(item, dict):
            continue
        views = item.get("views")
        if not isinstance(views, dict):
            continue
        candidates.append(
            {
                "source_kind": "navigation_smoke_waypoint_evidence",
                "label": item.get("waypoint_id") or f"waypoint_evidence_{index:03d}",
                "action": "navigation_smoke",
                "waypoint_id": item.get("waypoint_id"),
                "robot_pose_applied": item.get("robot_pose_applied"),
                "alignment_artifact": item.get("alignment_artifact"),
                "alignment_transform_source": item.get("alignment_transform_source"),
                "fpv": views.get("fpv"),
                "chase": views.get("chase"),
                "camera_control_contract": {},
            }
        )
    del artifact_path
    return candidates


def _b1_camera_preview_provenance_errors(
    payload: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    source_kind = str(candidate.get("source_kind") or "")
    errors = [
        *_b1_camera_preview_candidate_shape_errors(candidate, source_kind=source_kind),
        *_b1_camera_preview_alignment_errors(payload, candidate),
    ]
    if source_kind == "run_result_robot_view_step":
        errors.extend(_b1_camera_preview_contract_errors(candidate.get("camera_control_contract")))
    return errors


def _b1_camera_preview_candidate_shape_errors(
    candidate: dict[str, Any],
    *,
    source_kind: str,
) -> list[str]:
    errors = []
    if not str(candidate.get("waypoint_id") or "").strip():
        errors.append("missing_waypoint_id")
    if _b1_camera_preview_view_pair_mixed(candidate):
        errors.append("mixed_fpv_chase_view_pair")
    if source_kind not in {
        "run_result_robot_view_step",
        "navigation_smoke_waypoint_evidence",
    }:
        errors.append("unsupported_camera_artifact_source")
    if candidate.get("robot_pose_applied") is not True:
        errors.append("robot_pose_not_applied")
    return errors


def _b1_camera_preview_view_pair_mixed(candidate: dict[str, Any]) -> bool:
    fpv_label = _b1_camera_label_from_view_path(candidate.get("fpv"))
    chase_label = _b1_camera_label_from_view_path(candidate.get("chase"))
    return bool(fpv_label and chase_label and fpv_label != chase_label)


def _b1_camera_preview_alignment_errors(
    payload: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    errors = []
    if not (candidate.get("alignment_artifact") or payload.get("alignment_artifact")):
        errors.append("missing_alignment_artifact")
    transform_source = str(
        candidate.get("alignment_transform_source")
        or payload.get("alignment_transform_source")
        or ""
    )
    if transform_source != "reviewed_correspondence_fit":
        errors.append("missing_reviewed_correspondence_transform_source")
    return errors


def _b1_camera_preview_contract_errors(raw_contract: Any) -> list[str]:
    if not isinstance(raw_contract, dict):
        return ["missing_camera_control_contract"]
    return [
        *_b1_camera_preview_fpv_contract_errors(raw_contract.get("agent_facing_fpv")),
        *_b1_camera_preview_chase_contract_errors(raw_contract.get("report_chase_view")),
    ]


def _b1_camera_preview_fpv_contract_errors(raw_fpv_contract: Any) -> list[str]:
    if not isinstance(raw_fpv_contract, dict):
        return ["missing_agent_facing_fpv_contract"]
    errors = []
    if not (
        raw_fpv_contract.get("robot_mounted") is True
        or raw_fpv_contract.get("head_camera_equivalent") is True
    ):
        errors.append("fpv_not_robot_mounted_or_head_camera_equivalent")
    if _b1_camera_preview_forbidden_runtime_source(raw_fpv_contract.get("source")):
        errors.append("fpv_source_not_robot_runtime")
    return errors


def _b1_camera_preview_chase_contract_errors(raw_chase_contract: Any) -> list[str]:
    if not isinstance(raw_chase_contract, dict):
        return ["missing_report_chase_contract"]
    if _b1_camera_preview_forbidden_runtime_source(raw_chase_contract.get("source")):
        return ["chase_source_not_robot_runtime"]
    return []


def _b1_camera_preview_forbidden_runtime_source(raw_source: Any) -> bool:
    source = str(raw_source or "")
    return "scene_probe" in source or "bbox" in source


def _b1_camera_label_from_view_path(raw_path: Any) -> str:
    if not raw_path:
        return ""
    name = Path(str(raw_path)).name
    for suffix in (".fpv.png", ".chase.png", ".fpv.jpg", ".chase.jpg", ".png", ".jpg"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _static_navigation_preview(
    *,
    contract: HouseholdRuntimeContract,
    run_dir: Path,
    width: int,
    height: int,
) -> Image.Image:
    bundle = write_nav2_map_bundle_snapshot(
        run_dir=run_dir,
        metric_map=contract.metric_map(),
        static_landmarks=static_landmarks_from_fixture_projection(
            contract.static_fixture_projection()
        ),
    )
    preview_path = run_dir / str(
        (bundle.get("artifact_paths") or {}).get("preview_png") or "map_bundle/preview.png"
    )
    if not preview_path.is_file():
        raise RuntimeError(f"missing static navigation preview: {preview_path}")
    return _fit_preview_image(Image.open(preview_path), width=width, height=height)


def _resolve_b1_artifact_view_path(artifact_path: Path, raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return None
    base_dir = artifact_path.parent.resolve()
    resolved = (base_dir / path).resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError:
        return None
    if resolved.is_file():
        return resolved
    repo_resolved = (REPO_ROOT / path).resolve()
    try:
        repo_resolved.relative_to(REPO_ROOT)
    except ValueError:
        return None
    if repo_resolved.is_file():
        return repo_resolved
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _b1_camera_preview_quality_errors(diagnostics: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if diagnostics.get("visual_status") != "reviewable":
        errors.append(str(diagnostics.get("visual_status") or "not_reviewable"))
    if float(diagnostics.get("max_channel_range") or 0.0) <= 8.0:
        errors.append("too_little_channel_range")
    if float(diagnostics.get("max_stddev") or 0.0) <= 2.0:
        errors.append("too_little_variance")
    if int(diagnostics.get("thumbnail_color_count") or 0) < 128:
        errors.append("too_few_distinct_colors")
    if float(diagnostics.get("edge_fraction_over_8") or 0.0) < 0.02:
        errors.append("too_few_scene_edges")
    return errors


def _b1_camera_preview_score(diagnostics: dict[str, Any]) -> float:
    return (
        float(diagnostics.get("max_stddev") or 0.0)
        + (float(diagnostics.get("max_channel_range") or 0.0) / 100.0)
        + (float(diagnostics.get("thumbnail_color_count") or 0.0) / 1000.0)
        + (float(diagnostics.get("edge_fraction_over_8") or 0.0) * 10.0)
    )
