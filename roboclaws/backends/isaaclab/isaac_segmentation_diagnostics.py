"""Isaac Lab backend runtime support."""

from __future__ import annotations

from typing import Any

SEGMENTATION_SCHEMA = "isaac_segmentation_diagnostics_v1"
ISAAC_SEGMENTATION_DATA_TYPES = (
    "semantic_segmentation",
    "instance_segmentation_fast",
    "instance_id_segmentation_fast",
)
MAX_SEGMENTATION_CANDIDATES = 24


def camera_segmentation_view_diagnostics(
    camera: Any,
    *,
    data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
    view_name: str,
    np: Any,
    max_candidates: int = MAX_SEGMENTATION_CANDIDATES,
) -> dict[str, Any]:
    outputs = getattr(getattr(camera, "data", None), "output", {}) or {}
    info = getattr(getattr(camera, "data", None), "info", {}) or {}
    output_rows: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    for data_type in data_types:
        if data_type not in outputs:
            continue
        array = _segmentation_array(outputs.get(data_type), np=np)
        labels = _segmentation_label_map(_segmentation_info_for_data_type(info, data_type))
        row: dict[str, Any] = {
            "present": array is not None,
            "label_count": len(labels),
            "labels_available": bool(labels),
        }
        if array is not None:
            row.update(
                {
                    "shape": [int(dim) for dim in array.shape],
                    "dtype": str(array.dtype),
                    "unique_id_count": _segmentation_unique_count(array, np=np),
                }
            )
            candidates.extend(
                _segmentation_bbox_candidates(
                    array,
                    labels,
                    data_type=data_type,
                    view_name=view_name,
                    np=np,
                    max_candidates=max_candidates,
                )
            )
        output_rows[data_type] = row
    return {
        "view": view_name,
        "outputs": output_rows,
        "candidate_bboxes": candidates[:max_candidates],
    }


def camera_segmentation_capture_diagnostics(
    views: list[dict[str, Any]],
    *,
    requested_data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
    semantic_label_application: dict[str, Any] | None = None,
    semantic_filter: str | list[str] | None = None,
    max_candidates: int = MAX_SEGMENTATION_CANDIDATES,
) -> dict[str, Any]:
    output_data_types = sorted(
        {
            data_type
            for view in views
            for data_type, row in _dict(view.get("outputs")).items()
            if _dict(row).get("present") is True
        }
    )
    candidates = [
        candidate
        for view in views
        for candidate in view.get("candidate_bboxes", [])
        if isinstance(candidate, dict)
    ]
    return {
        "schema": SEGMENTATION_SCHEMA,
        "source": "isaac_lab_camera",
        "capture_method": "isaac_lab_camera_segmentation",
        "requested_data_types": list(requested_data_types),
        "output_data_types": output_data_types,
        "tensor_output_available": bool(output_data_types),
        "semantic_filter": semantic_filter,
        "candidate_bbox_count": len(candidates),
        "candidate_bboxes": candidates[:max_candidates],
        "view_outputs": views,
        "semantic_label_application": _dict(semantic_label_application),
        "no_simulator_label_fallback": True,
    }


def camera_segmentation_not_requested_diagnostics(
    *,
    requested_data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
) -> dict[str, Any]:
    return {
        "schema": SEGMENTATION_SCHEMA,
        "source": "isaac_lab_camera",
        "capture_method": "not_requested_for_rgb_runtime_smoke",
        "requested_data_types": list(requested_data_types),
        "output_data_types": [],
        "tensor_output_available": False,
        "candidate_bbox_count": 0,
        "candidate_bboxes": [],
        "view_outputs": [],
        "no_simulator_label_fallback": True,
    }


def segmentation_diagnostics(
    runtime_mode: str,
    *,
    real_smoke: dict[str, Any] | None = None,
    scene_binding_diagnostics: dict[str, Any] | None = None,
    requested_data_types: tuple[str, ...] = ISAAC_SEGMENTATION_DATA_TYPES,
    max_candidates: int = MAX_SEGMENTATION_CANDIDATES,
) -> dict[str, Any]:
    selected_paths = _selected_bound_usd_prim_paths(scene_binding_diagnostics)
    selected_unrenderable_paths = _selected_unrenderable_usd_prim_paths(scene_binding_diagnostics)
    if real_smoke is None:
        source = "fake_protocol" if runtime_mode == "fake" else "real_isaac_pending"
        return {
            "schema": SEGMENTATION_SCHEMA,
            "available": False,
            "status": "blocked_capability",
            "source": source,
            "capture_method": "not_attempted",
            "requested_data_types": list(requested_data_types),
            "output_data_types": [],
            "tensor_output_available": False,
            "candidate_overlay_status": "blocked_capability",
            "candidate_bbox_count": 0,
            "selected_usd_prim_match_count": 0,
            "selected_usd_prim_paths": selected_paths,
            "candidate_bboxes": [],
            "blockers": [
                "Isaac semantic/instance segmentation requires a real Isaac camera capture."
            ],
            "agent_facing": False,
            "no_simulator_label_fallback": True,
            "reason": (
                "Semantic or instance segmentation is not exposed by fake protocol "
                "artifacts and no simulator-label fallback was used."
            ),
        }

    captured = _dict(real_smoke.get("segmentation"))
    output_data_types = [str(item) for item in captured.get("output_data_types", []) if str(item)]
    candidates = [
        dict(candidate)
        for candidate in captured.get("candidate_bboxes", [])
        if isinstance(candidate, dict)
    ][:max_candidates]
    selected_matches = _segmentation_selected_matches(candidates, selected_paths)
    blockers: list[str] = []
    if not output_data_types:
        blockers.append("Isaac camera capture returned no segmentation tensors.")
    if not candidates:
        blockers.append("Isaac segmentation tensors did not produce label-mapped bbox candidates.")
    if selected_paths and not selected_matches:
        blockers.append("Isaac segmentation candidates did not match selected cleanup USD prims.")
    if selected_unrenderable_paths:
        blockers.append(
            "Selected cleanup USD prims have no renderable geometry: "
            + ", ".join(selected_unrenderable_paths[:5])
        )
    if not selected_paths:
        blockers.append("Selected cleanup handles are not bound to USD prim paths.")
    status = "available" if not blockers else "blocked_capability"
    reason = (
        "Isaac camera segmentation tensors produced label-mapped bbox candidates "
        "for selected cleanup USD prims."
        if status == "available"
        else " ".join(blockers)
    )
    return {
        "schema": SEGMENTATION_SCHEMA,
        "available": status == "available",
        "status": status,
        "source": captured.get("source") or "isaac_lab_camera",
        "capture_method": captured.get("capture_method") or "isaac_lab_camera_segmentation",
        "requested_data_types": captured.get("requested_data_types") or list(requested_data_types),
        "output_data_types": output_data_types,
        "tensor_output_available": bool(output_data_types),
        "semantic_filter": captured.get("semantic_filter"),
        "candidate_overlay_status": (
            "available" if status == "available" else "blocked_capability"
        ),
        "candidate_bbox_count": len(candidates),
        "selected_usd_prim_match_count": len(selected_matches),
        "selected_usd_prim_paths": selected_paths,
        "selected_usd_unrenderable_prim_paths": selected_unrenderable_paths,
        "selected_candidate_bboxes": selected_matches[:max_candidates],
        "candidate_bboxes": candidates,
        "view_outputs": captured.get("view_outputs", []),
        "semantic_label_application": _dict(captured.get("semantic_label_application")),
        "blockers": blockers,
        "agent_facing": False,
        "no_simulator_label_fallback": captured.get("no_simulator_label_fallback") is not False,
        "reason": reason,
    }


def _segmentation_array(value: Any, *, np: Any) -> Any | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    array = np.asarray(value)
    if array.size == 0:
        return None
    while array.ndim > 2 and array.shape[0] == 1:
        array = array[0]
    if array.ndim == 3 and array.shape[-1] == 1:
        array = array[..., 0]
    if array.ndim != 2:
        return None
    return array


def _segmentation_info_for_data_type(info: Any, data_type: str) -> dict[str, Any]:
    if isinstance(info, dict):
        nested = info.get(data_type)
        if isinstance(nested, dict):
            return nested
        return info
    if isinstance(info, (list, tuple)):
        merged: dict[str, Any] = {}
        for item in info:
            labels = _segmentation_label_map(_segmentation_info_for_data_type(item, data_type))
            if labels:
                merged.setdefault("idToLabels", {}).update(labels)
        return merged
    return {}


def _segmentation_label_map(info: Any) -> dict[int, str]:
    if isinstance(info, (list, tuple)):
        labels: dict[int, str] = {}
        for item in info:
            labels.update(_segmentation_label_map(item))
        return labels
    if not isinstance(info, dict):
        return {}
    raw_labels = (
        info.get("idToLabels")
        or info.get("id_to_labels")
        or info.get("idToSemantics")
        or info.get("id_to_semantics")
        or {}
    )
    if not isinstance(raw_labels, dict):
        return {}
    labels: dict[int, str] = {}
    for raw_id, raw_label in raw_labels.items():
        label_id = _int_or_none(raw_id)
        if label_id is None:
            continue
        label = _segmentation_label_text(raw_label)
        if label:
            labels[label_id] = label
    return labels


def _segmentation_label_text(raw_label: Any) -> str:
    if isinstance(raw_label, str):
        return raw_label
    if isinstance(raw_label, dict):
        for key in (
            "usd_prim_path",
            "prim_path",
            "path",
            "instance",
            "class",
            "semantic",
            "label",
            "name",
        ):
            value = raw_label.get(key)
            if isinstance(value, str) and value:
                return value
        return " ".join(str(value) for value in raw_label.values() if value)
    if raw_label is None:
        return ""
    return str(raw_label)


def _segmentation_unique_count(array: Any, *, np: Any) -> int:
    try:
        return int(np.unique(array).size)
    except Exception:
        return 0


def _segmentation_bbox_candidates(
    array: Any,
    labels: dict[int, str],
    *,
    data_type: str,
    view_name: str,
    np: Any,
    max_candidates: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    height, width = array.shape
    for label_id, label in sorted(labels.items()):
        mask = array == label_id
        pixel_count = int(np.count_nonzero(mask))
        if pixel_count <= 0:
            continue
        ys, xs = np.where(mask)
        if len(xs) == 0 or len(ys) == 0:
            continue
        candidate = {
            "view": view_name,
            "data_type": data_type,
            "label_id": int(label_id),
            "label": label,
            "usd_prim_path": label if label.startswith("/") else "",
            "bbox_xyxy": [
                int(xs.min()),
                int(ys.min()),
                int(xs.max()) + 1,
                int(ys.max()) + 1,
            ],
            "pixel_count": pixel_count,
            "image_size": [int(width), int(height)],
        }
        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break
    return candidates


def _selected_bound_usd_prim_paths(
    scene_binding_diagnostics: dict[str, Any] | None,
) -> list[str]:
    bindings = _dict(scene_binding_diagnostics)
    selected_paths: list[str] = []
    for group_key in ("selected_object_bindings", "selected_target_receptacle_bindings"):
        for binding in _dict(bindings.get(group_key)).values():
            item = _dict(binding)
            if item.get("status") == "bound" and item.get("usd_prim_path"):
                selected_paths.append(str(item["usd_prim_path"]))
    return _dedupe(selected_paths)


def _selected_unrenderable_usd_prim_paths(
    scene_binding_diagnostics: dict[str, Any] | None,
) -> list[str]:
    bindings = _dict(scene_binding_diagnostics)
    selected_paths: list[str] = []
    for group_key in ("selected_object_bindings", "selected_target_receptacle_bindings"):
        for binding in _dict(bindings.get(group_key)).values():
            item = _dict(binding)
            if item.get("status") != "bound":
                continue
            if item.get("has_renderable_geometry") is False and item.get("usd_prim_path"):
                selected_paths.append(str(item["usd_prim_path"]))
    return _dedupe(selected_paths)


def _segmentation_selected_matches(
    candidates: list[dict[str, Any]],
    selected_paths: list[str],
) -> list[dict[str, Any]]:
    selected = set(selected_paths)
    selected_normalized = {_normalize_usd_path(path) for path in selected_paths if path}
    matches: list[dict[str, Any]] = []
    for candidate in candidates:
        prim_path = str(candidate.get("usd_prim_path") or "")
        label = str(candidate.get("label") or "")
        prim_path_normalized = _normalize_usd_path(prim_path)
        label_normalized = _normalize_usd_path(label)
        if (
            prim_path in selected
            or prim_path_normalized in selected_normalized
            or any(path and path in label for path in selected)
            or any(path and path in label_normalized for path in selected_normalized)
        ):
            matches.append(candidate)
    return matches


def _normalize_usd_path(value: str) -> str:
    return str(value or "").strip().casefold()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
