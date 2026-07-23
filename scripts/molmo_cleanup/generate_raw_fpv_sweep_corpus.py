#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

from roboclaws.core.json_sources import read_json_object  # noqa: E402
from roboclaws.household.household_backend_contract import HouseholdBackendSession  # noqa: E402
from roboclaws.household.household_runtime_contract import (  # noqa: E402
    RAW_FPV_ONLY_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend  # noqa: E402
from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_path  # noqa: E402
from scripts.molmo_cleanup.generate_raw_fpv_private_labels import (  # noqa: E402
    LABEL_SCOPE_CLEANUP_VISIBLE_MOVABLE,
    LABEL_SCOPE_GENERATED_TARGETS,
    MANIFEST_SCHEMA,
    coarse_regions_from_bbox,
    generated_mess_manifest_from_state,
    label_object_ids_for_scope,
    normalize_box_xywh,
    surface_hint_from_focus,
)

REPORT_SCHEMA = "raw_fpv_public_sweep_corpus_report_v1"
DEFAULT_SOURCE_RUN_DIR = Path(
    "output/household/household-cleanup/codex-camera-raw/0606_1537/seed-7"
)
DEFAULT_OUTPUT_ROOT = Path("output/molmo/raw-fpv-sweep-corpus")
DEFAULT_CAMERA_YAWS = (-45.0, 0.0, 45.0)
DEFAULT_CAMERA_PITCHES = (-10.0, 0.0)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = generate_sweep_corpus(args)
    print(json.dumps(_console_summary(report), indent=2, sort_keys=True))
    return 0 if report.get("status") in {"success", "partial"} else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fixed public RAW-FPV sweep corpus from generated exploration "
            "candidates. Public prompt inputs get only frame artifacts and waypoint/camera "
            "metadata; private generated-mess labels are written for scorer use only."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source-run-dir", type=Path, default=DEFAULT_SOURCE_RUN_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--max-waypoints", type=_non_negative_int_arg, default=0)
    parser.add_argument(
        "--camera-yaw-deg",
        action="append",
        type=float,
        default=[],
        help="Camera yaw offsets to capture at each public waypoint.",
    )
    parser.add_argument(
        "--camera-pitch-deg",
        action="append",
        type=float,
        default=[],
        help="Camera pitch offsets to capture at each public waypoint.",
    )
    parser.add_argument("--min-object-pixels", type=_positive_int_arg, default=12)
    parser.add_argument("--render-width", type=_positive_int_arg, default=540)
    parser.add_argument("--render-height", type=_positive_int_arg, default=360)
    parser.add_argument(
        "--label-scope",
        choices=(LABEL_SCOPE_GENERATED_TARGETS, LABEL_SCOPE_CLEANUP_VISIBLE_MOVABLE),
        default=LABEL_SCOPE_GENERATED_TARGETS,
        help=(
            "generated-targets preserves hidden-target recovery truth. "
            "cleanup-visible-movable labels all cleanup-family movable objects for "
            "visible_movable_label_quality."
        ),
    )
    return parser.parse_args(argv)


def generate_sweep_corpus(args: argparse.Namespace) -> dict[str, Any]:
    source_run_dir = args.source_run_dir.expanduser()
    source_state_path = source_run_dir / "molmospaces_backend_state.json"
    if not source_state_path.is_file():
        raise FileNotFoundError(source_state_path)
    source_state = _load_json(source_state_path)

    output_run_dir = _output_run_dir(args.output_dir, args.run_id)
    output_run_dir.mkdir(parents=True, exist_ok=True)

    generated_manifest = generated_mess_manifest_from_state(source_state)
    generated_manifest_path = output_run_dir / "generated_mess_manifest.private.json"
    generated_manifest_path.write_text(
        json.dumps(generated_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    backend = MolmoSpacesSubprocessBackend(
        run_dir=output_run_dir / "backend",
        seed=int(source_state.get("seed") or 7),
        python_executable=Path(str(source_state.get("python_executable") or sys.executable)),
        scene_source=str(source_state.get("scene_source") or "procthor-10k-val"),
        scene_index=int(source_state.get("scene_index") or 0),
        include_robot=True,
        robot_name=str(source_state.get("robot_name") or "rby1m"),
        generated_mess_count=len(generated_manifest["targets"]),
        generated_mess_manifest_path=generated_manifest_path,
    )
    base_contract = HouseholdBackendSession(backend.scenario, backend=backend)
    contract = HouseholdRuntimeContract(
        base_contract,
        perception_mode=RAW_FPV_ONLY_MODE,
        map_bundle_dir=molmospaces_nav2_map_bundle_path(
            scene_source=str(source_state.get("scene_source") or "procthor-10k-val"),
            scene_index=int(source_state.get("scene_index") or 0),
        ),
    )

    yaw_offsets = tuple(args.camera_yaw_deg or DEFAULT_CAMERA_YAWS)
    pitch_offsets = tuple(args.camera_pitch_deg or DEFAULT_CAMERA_PITCHES)
    waypoints = list((contract.metric_map().get("inspection_waypoints") or []))
    if args.max_waypoints and args.max_waypoints > 0:
        waypoints = waypoints[: int(args.max_waypoints)]

    labels: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    image_dir = output_run_dir / "robot_views"
    observation_index = 0
    for waypoint in waypoints:
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        nav = contract.navigate_to_waypoint(waypoint_id)
        if not nav.get("ok"):
            frames.append(
                {
                    "waypoint_id": waypoint_id,
                    "capture_status": "navigate_failed",
                    "navigation": _public_navigation_summary(nav),
                }
            )
            continue
        for yaw in yaw_offsets:
            for pitch in pitch_offsets:
                observation_index += 1
                observation_id = f"raw_fpv_{observation_index:03d}"
                label = f"{observation_index:04d}_{observation_id}"
                view = backend.write_robot_views_with_resolution(
                    image_dir,
                    label=label,
                    width=int(args.render_width),
                    height=int(args.render_height),
                    camera_yaw_offset_deg=float(yaw),
                    camera_pitch_offset_deg=float(pitch),
                )
                frame_id = f"{_run_id_for_path(output_run_dir)}/{observation_id}"
                observation = _public_observation(
                    observation_id=observation_id,
                    waypoint=waypoint,
                    yaw=float(yaw),
                    pitch=float(pitch),
                    view=view,
                    image_artifact=f"robot_views/{label}.fpv.png",
                )
                observations.append(observation)
                frame_labels = _labels_from_view_focuses(
                    backend=backend,
                    frame_id=frame_id,
                    observation_id=observation_id,
                    targets=generated_manifest["targets"],
                    output_dir=image_dir,
                    label_prefix=label,
                    min_object_pixels=int(args.min_object_pixels),
                    width=int(args.render_width),
                    height=int(args.render_height),
                    yaw=float(yaw),
                    pitch=float(pitch),
                    label_scope=str(args.label_scope),
                )
                labels.extend(frame_labels)
                frames.append(
                    {
                        "frame_id": frame_id,
                        "source_observation_id": observation_id,
                        "waypoint_id": waypoint_id,
                        "camera_yaw_offset_deg": float(yaw),
                        "camera_pitch_offset_deg": float(pitch),
                        "image_artifact": observation["image_artifacts"]["fpv"],
                        "capture_status": "ok",
                        "label_count": len(frame_labels),
                        "labeled_objects": sorted(
                            {str(item.get("object_id") or "") for item in frame_labels}
                        ),
                    }
                )

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": _utc_timestamp(),
        "provenance": {
            "label_source": "private_molmospaces_public_sweep_fpv_segmentation",
            "source_run_dir": str(source_run_dir),
            "scorer_only": True,
            "label_scope": str(args.label_scope),
            "private_truth_included_in_prompt_inputs": False,
            "public_frame_policy": (
                "generated_exploration_waypoints_plus_camera_offsets_no_target_handles"
            ),
        },
        "source_run": {
            "run_id": _run_id_for_path(source_run_dir),
            "seed": source_state.get("seed"),
            "scene_source": source_state.get("scene_source"),
            "scene_index": source_state.get("scene_index"),
            "generated_mess_count": len(generated_manifest["targets"]),
        },
        "labels": labels,
    }
    manifest_path = output_run_dir / "raw_fpv_private_label_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    observations_path = output_run_dir / "raw_fpv_observations.json"
    observations_path.write_text(
        json.dumps(
            {
                "schema": "raw_fpv_public_sweep_observations_v1",
                "raw_fpv_observations": observations,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    unique_labeled = sorted({str(item.get("object_id") or "") for item in labels})
    target_ids = {str(item.get("object_id") or "") for item in generated_manifest["targets"]}
    missing_targets = sorted(target_ids.difference(unique_labeled))
    status = (
        "success"
        if labels
        and (str(args.label_scope) == LABEL_SCOPE_CLEANUP_VISIBLE_MOVABLE or not missing_targets)
        else "partial"
    )
    report = {
        "schema": REPORT_SCHEMA,
        "status": status,
        "generated_at": _utc_timestamp(),
        "output_dir": str(output_run_dir),
        "source_run_dir": str(source_run_dir),
        "public_frame_policy": (
            "generated_exploration_waypoints_plus_camera_offsets_no_target_handles"
        ),
        "waypoint_count": len(waypoints),
        "frame_count": len(observations),
        "label_count": len(labels),
        "unique_labeled_object_count": len(unique_labeled),
        "selected_object_count": len(target_ids),
        "missing_private_targets": missing_targets,
        "min_object_pixels": int(args.min_object_pixels),
        "label_scope": str(args.label_scope),
        "camera_yaw_offsets_deg": list(yaw_offsets),
        "camera_pitch_offsets_deg": list(pitch_offsets),
        "privacy": {
            "private_labels_in_prompt_inputs": _contains_any_target_id(observations, target_ids),
            "agent_facing_input_contains_executable_prior_handles": False,
        },
        "artifacts": {
            "observations": str(observations_path),
            "manifest": str(manifest_path),
            "generated_mess_manifest": str(generated_manifest_path),
        },
        "frames": frames,
    }
    (output_run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _labels_from_view_focuses(
    *,
    backend: MolmoSpacesSubprocessBackend,
    frame_id: str,
    observation_id: str,
    targets: list[dict[str, Any]],
    output_dir: Path,
    label_prefix: str,
    min_object_pixels: int,
    width: int,
    height: int,
    yaw: float,
    pitch: float,
    label_scope: str = LABEL_SCOPE_GENERATED_TARGETS,
) -> list[dict[str, Any]]:
    if label_scope == LABEL_SCOPE_CLEANUP_VISIBLE_MOVABLE:
        return _labels_from_single_segmentation(
            backend=backend,
            frame_id=frame_id,
            observation_id=observation_id,
            min_object_pixels=min_object_pixels,
            width=width,
            height=height,
            yaw=yaw,
            pitch=pitch,
            label_scope=label_scope,
        )
    labels = []
    state = backend._read_state()  # noqa: SLF001 - scorer-only corpus generator.
    target_by_id = {str(target.get("object_id") or ""): target for target in targets}
    for object_id in label_object_ids_for_scope(state, label_scope=label_scope):
        if not object_id:
            continue
        result = backend.write_robot_views_with_resolution(
            output_dir,
            label=f"{label_prefix}_{_safe_filename(object_id)}",
            width=width,
            height=height,
            focus_object_id=object_id,
            camera_yaw_offset_deg=yaw,
            camera_pitch_offset_deg=pitch,
        )
        focus = result.get("focus") or {}
        visibility = focus.get("fpv_visibility") or {}
        box = _object_box_from_visibility(visibility)
        pixels = int((box or {}).get("pixels") or 0)
        if box is None or pixels < min_object_pixels:
            continue
        bbox = normalize_box_xywh(box["bbox"], width=width, height=height)
        labels.append(
            {
                "frame_id": frame_id,
                "source_observation_id": observation_id,
                "object_id": object_id,
                "category": str(
                    focus.get("object_category")
                    or (target_by_id.get(object_id) or {}).get("category")
                    or ((state.get("objects") or {}).get(object_id) or {}).get("category")
                    or ""
                ),
                "bbox": bbox,
                "coarse_regions": coarse_regions_from_bbox(bbox),
                "surface_hint": surface_hint_from_focus(focus),
                "label_source": "private_molmospaces_public_sweep_fpv_segmentation",
                "private": True,
                "hidden_target": label_scope == LABEL_SCOPE_GENERATED_TARGETS,
                "pixel_bbox": list(box["bbox"]),
                "object_pixels": pixels,
            }
        )
    return labels


def _labels_from_single_segmentation(
    *,
    backend: MolmoSpacesSubprocessBackend,
    frame_id: str,
    observation_id: str,
    min_object_pixels: int,
    width: int,
    height: int,
    yaw: float,
    pitch: float,
    label_scope: str,
) -> list[dict[str, Any]]:
    os.environ.setdefault("MUJOCO_GL", "egl")
    from scripts.molmo_cleanup import molmospaces_subprocess_worker as worker

    state = backend._read_state()  # noqa: SLF001 - scorer-only corpus generator.
    model, data = worker._load_model_data_for_state(state)  # noqa: SLF001
    worker._apply_qpos(data, state["qpos"])  # noqa: SLF001
    worker._apply_robot_view_camera_offset(  # noqa: SLF001
        model,
        data,
        yaw_offset_deg=float(yaw),
        pitch_offset_deg=float(pitch),
    )
    worker.mujoco.mj_forward(model, data)
    segmentation = worker._render_segmentation(  # noqa: SLF001
        model,
        data,
        "robot_0/head_camera",
        width=width,
        height=height,
    )
    labels = []
    objects = state.get("objects") if isinstance(state.get("objects"), dict) else {}
    for object_id in label_object_ids_for_scope(state, label_scope=label_scope):
        obj = objects.get(object_id) if isinstance(objects.get(object_id), dict) else {}
        body_name = str(obj.get("body_name") or object_id)
        box = worker._segmentation_box(  # noqa: SLF001
            model,
            segmentation,
            body_name,
            label=str(obj.get("category") or object_id),
            color=[239, 68, 68],
        )
        pixels = int((box or {}).get("pixels") or 0)
        if box is None or pixels < min_object_pixels:
            continue
        bbox = normalize_box_xywh(box["bbox"], width=width, height=height)
        labels.append(
            {
                "frame_id": frame_id,
                "source_observation_id": observation_id,
                "object_id": object_id,
                "category": str(obj.get("category") or ""),
                "bbox": bbox,
                "coarse_regions": coarse_regions_from_bbox(bbox),
                "surface_hint": "unknown",
                "label_source": "private_molmospaces_public_sweep_fpv_segmentation",
                "private": True,
                "hidden_target": False,
                "pixel_bbox": list(box["bbox"]),
                "object_pixels": pixels,
            }
        )
    return labels


def _public_observation(
    *,
    observation_id: str,
    waypoint: dict[str, Any],
    yaw: float,
    pitch: float,
    view: dict[str, Any],
    image_artifact: str,
) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "waypoint_id": str(waypoint.get("waypoint_id") or ""),
        "room_id": str(waypoint.get("room_id") or "generated_area"),
        "held_object_id": None,
        "perception_mode": RAW_FPV_ONLY_MODE,
        "structured_detections_available": False,
        "camera_offset": {
            "yaw_offset_deg": yaw,
            "pitch_offset_deg": pitch,
        },
        "image_artifacts": {
            "fpv": image_artifact,
            "map": image_artifact.replace(".fpv.png", ".map.png"),
            "chase": image_artifact.replace(".fpv.png", ".chase.png"),
            "verify": image_artifact.replace(".fpv.png", ".verify.png"),
        },
        "robot_view_label": image_artifact.rsplit("/", 1)[-1].removesuffix(".fpv.png"),
        "camera_control_contract": view.get("camera_control_contract")
        if isinstance(view.get("camera_control_contract"), dict)
        else {},
        "artifact_status": "captured",
        "public_contract_note": (
            "Public sweep frame only: no structured movable-object detections, "
            "categories, target labels, or private scoring truth are included."
        ),
    }


def _object_box_from_visibility(visibility: dict[str, Any]) -> dict[str, Any] | None:
    boxes = [
        item
        for item in visibility.get("boxes") or []
        if isinstance(item, dict) and item.get("source") in {"segmentation", "highlight_diff"}
    ]
    if not boxes:
        return None
    return max(boxes, key=lambda item: int(item.get("pixels") or 0))


def _public_navigation_summary(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(response.get("ok")),
        "tool": str(response.get("tool") or "navigate_to_waypoint"),
        "status": str(response.get("status") or ""),
        "failure_reason": str(response.get("failure_reason") or response.get("reason") or ""),
    }


def _contains_any_target_id(payload: Any, target_ids: set[str]) -> bool:
    text = json.dumps(payload, sort_keys=True)
    return any(target_id and target_id in text for target_id in target_ids)


def _load_json(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="MolmoSpaces backend state")


def _output_run_dir(output_root: Path, run_id: str) -> Path:
    if run_id:
        return output_root / _safe_filename(run_id)
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    return output_root / stamp


def _run_id_for_path(path: Path) -> str:
    parts = [part for part in path.parts[-4:] if part not in {"output", "household"}]
    return _safe_filename("-".join(parts))


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "item"


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _console_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "manifest": (report.get("artifacts") or {}).get("manifest"),
        "observations": (report.get("artifacts") or {}).get("observations"),
        "label_count": report.get("label_count"),
        "frame_count": report.get("frame_count"),
        "unique_labeled_object_count": report.get("unique_labeled_object_count"),
        "missing_private_targets": report.get("missing_private_targets"),
        "report_json": str(Path(str(report.get("output_dir", ""))) / "report.json"),
    }


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


def _non_negative_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a non-negative integer; got {value!r}"
        ) from None
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer; got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
