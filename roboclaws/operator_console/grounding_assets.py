"""Camera-grounded frame assets for the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object


def grounding_frames_payload(root: Path, run_dir: Path) -> dict[str, Any]:
    frames = _grounding_frames(root, run_dir)
    if not frames:
        return {}
    return {
        "frames": frames,
        "frame_count": len(frames),
        "candidate_count": sum(int(frame.get("candidate_count") or 0) for frame in frames),
        "visual_role": "visual_grounding_frame_gallery",
        "artifact_source_family": "camera_grounded_labels",
    }


def _grounding_frames(root: Path, run_dir: Path) -> list[dict[str, Any]]:
    active_perception = _active_perception(run_dir)
    raw_observations = active_perception.get("raw_fpv_observations")
    if not isinstance(raw_observations, list):
        return []
    candidates_by_observation = _grounding_candidates_by_observation(
        root, run_dir, active_perception
    )
    frames: list[dict[str, Any]] = []
    for index, raw_observation in enumerate(raw_observations, start=1):
        if not isinstance(raw_observation, dict):
            continue
        observation_id = str(raw_observation.get("observation_id") or "").strip()
        image = _raw_fpv_asset(root, run_dir, raw_observation)
        if not observation_id or not image:
            continue
        candidates = candidates_by_observation.get(observation_id, [])
        if candidates:
            frames.append(
                {
                    "observation_id": observation_id,
                    "frame_index": index,
                    "candidate_count": len(candidates),
                    "image": image,
                    "candidates": candidates,
                }
            )
    return frames


def _active_perception(run_dir: Path) -> dict[str, Any]:
    try:
        agent_view = read_json_object(run_dir / "agent_view.json", label="Agent View")
    except (OSError, ValueError):
        return {}
    active_perception = agent_view.get("active_perception")
    return active_perception if isinstance(active_perception, dict) else {}


def _grounding_candidates_by_observation(
    root: Path,
    run_dir: Path,
    active_perception: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    rows = active_perception.get("model_declared_observations")
    if not isinstance(rows, list):
        evidence = active_perception.get("model_declared_observation_evidence")
        rows = evidence.get("observations") if isinstance(evidence, dict) else []
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        candidate = _grounding_candidate(root, run_dir, row)
        if candidate:
            output.setdefault(candidate["source_observation_id"], []).append(candidate)
    return output


def _grounding_candidate(root: Path, run_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("visual_grounding_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    observation_id = str(
        evidence.get("source_observation_id") or row.get("source_observation_id") or ""
    ).strip()
    bbox = _normalized_bbox_xywh(
        evidence.get("image_bbox")
        or _region_value(evidence.get("image_region"))
        or _region_value(row.get("image_region"))
    )
    if not observation_id or bbox is None:
        return {}
    return {
        "source_observation_id": observation_id,
        "object_id": str(row.get("object_id") or ""),
        "declaration_id": str(row.get("declaration_id") or ""),
        "category": str(row.get("category") or "candidate"),
        "confidence": _float_or_none(row.get("confidence")),
        "bbox_xywh": bbox,
        "grounding_status": str(
            evidence.get("grounding_status") or row.get("grounding_status") or ""
        ),
        "candidate_state": str(evidence.get("candidate_state") or row.get("candidate_state") or ""),
        "actionability_status": str(
            evidence.get("actionability_status") or row.get("actionability_status") or ""
        ),
        "reviewability_status": str(evidence.get("reviewability_status") or ""),
        "overlay": _relative_artifact_asset(
            root,
            run_dir,
            str(
                evidence.get("visual_grounding_overlay")
                or row.get("visual_grounding_overlay")
                or ""
            ),
        ),
    }


def _region_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else None


def _raw_fpv_asset(root: Path, run_dir: Path, raw_observation: dict[str, Any]) -> dict[str, Any]:
    image_artifacts = raw_observation.get("image_artifacts")
    if not isinstance(image_artifacts, dict):
        image_artifacts = {}
    return _relative_artifact_asset(
        root,
        run_dir,
        str(image_artifacts.get("fpv") or raw_observation.get("fpv_image") or ""),
    )


def _relative_artifact_asset(root: Path, run_dir: Path, relative_path: str) -> dict[str, Any]:
    if not relative_path:
        return {}
    path = (run_dir / relative_path).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError:
        return {}
    if not path.is_file():
        return {}
    return {
        "path": str(path),
        "href": _artifact_href(root, path),
        "mtime": str(path.stat().st_mtime),
    }


def _normalized_bbox_xywh(value: Any) -> list[float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    width = max(0.0, min(1.0 - x, width))
    height = max(0.0, min(1.0 - y, height))
    if width <= 0.0 or height <= 0.0:
        return None
    return [round(item, 6) for item in (x, y, width, height)]


def _float_or_none(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _artifact_href(root: Path, path: Path) -> str:
    if not path.is_relative_to(root):
        return ""
    return f"/artifacts/{path.relative_to(root)}?v={path.stat().st_mtime_ns}"
