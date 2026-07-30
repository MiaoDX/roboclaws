#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

from roboclaws.core.json_sources import read_json_object, read_jsonl_object_rows  # noqa: E402
from roboclaws.core.raw_fpv_guidance import (  # noqa: E402
    RAW_FPV_CATEGORY_HINT,
    RAW_FPV_HIGH_CONFIDENCE_TARGETS,
)
from roboclaws.household import agent_view as agent_view_module  # noqa: E402
from scripts.molmo_cleanup.raw_fpv_perception_scoring import score_variant_metrics  # noqa: E402

REPORT_SCHEMA = "raw_fpv_perception_probe_report_v1"
PUBLIC_INPUT_SCHEMA = "raw_fpv_perception_probe_public_input_v1"
PRIVATE_LABEL_SCHEMA = "raw_fpv_private_label_manifest_v1"
PREDICTION_SCHEMA = "raw_fpv_probe_predictions_v1"
RESPONSE_SCHEMA = "raw_fpv_probe_response_v1"
VISUAL_LABELER_RESPONSE_SCHEMA = "raw_fpv_visual_labeler_response_v1"

DEFAULT_RAW_RUN_DIRS: tuple[Path, ...] = ()
DEFAULT_CONTRAST_RUN_DIRS: tuple[Path, ...] = ()
DEFAULT_RUNTIME_MAP_PRIOR = Path(
    "output/household/direct-map-build/direct-camera-grounded-labels/seed-7/runtime_metric_map.json"
)
DEFAULT_OUTPUT_ROOT = Path("output/molmo/raw-fpv-perception-probe")

SCREEN_GRID_REGIONS = (
    "upper_left",
    "upper_center",
    "upper_right",
    "middle_left",
    "center",
    "middle_right",
    "lower_left",
    "lower_center",
    "lower_right",
)
SURFACE_HINTS = (
    "floor",
    "table",
    "shelf",
    "counter",
    "bed",
    "sofa",
    "unknown",
)
MOVABLE_CATEGORY_FAMILIES = (
    "food",
    "dish",
    "book",
    "linen",
    "toy",
    "electronics",
)
FIXTURE_OR_SURFACE_CATEGORIES = {
    "appliance",
    "bed",
    "bookshelf",
    "cabinet",
    "counter",
    "desk",
    "fixture",
    "floor",
    "fridge",
    "refrigerator",
    "shelf",
    "sink",
    "sofa",
    "surface",
    "table",
}
FAILURE_CLASSES = (
    "schema_failure",
    "locality_too_coarse_or_invalid",
    "semantic_mismatch/unresolved",
    "missing_private_label",
)


@dataclass(frozen=True)
class ObservationFrame:
    frame_id: str
    source_run_id: str
    source_kind: str
    source_observation_id: str
    waypoint_id: str
    room_id: str
    image_path: Path
    image_artifact: str
    width: int
    height: int
    image_sha256: str

    def public_payload(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "source_run_id": self.source_run_id,
            "source_kind": self.source_kind,
            "source_observation_id": self.source_observation_id,
            "waypoint_id": self.waypoint_id,
            "room_id": self.room_id,
            "image_artifact": self.image_artifact,
            "image_sha256": self.image_sha256,
            "image_dimensions": {"width": self.width, "height": self.height},
        }


@dataclass(frozen=True)
class ProbeLabel:
    frame_id: str
    source_observation_id: str
    object_id: str
    category: str
    category_family: str
    bbox: tuple[float, float, float, float] | None
    coarse_regions: tuple[str, ...]
    surface_hint: str
    label_source: str
    private: bool
    hidden_target: bool

    def score_payload(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "source_observation_id": self.source_observation_id,
            "object_id": self.object_id,
            "category": self.category,
            "category_family": self.category_family,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "coarse_regions": list(self.coarse_regions),
            "surface_hint": self.surface_hint,
            "label_source": self.label_source,
            "private": self.private,
            "hidden_target": self.hidden_target,
        }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_probe(args)
    print(json.dumps(_console_summary(report), indent=2, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description=(
            "Run a perception-only RAW-FPV probe over fixed cleanup frames. The probe "
            "keeps public model prompts separate from offline private scoring labels."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--raw-run-dir", action="append", type=Path, default=[])
    parser.add_argument("--contrast-run-dir", action="append", type=Path, default=[])
    parser.add_argument("--runtime-map-prior", type=Path, default=DEFAULT_RUNTIME_MAP_PRIOR)
    parser.add_argument("--private-labels", action="append", type=Path, default=[])
    parser.add_argument(
        "--all-visible-labels",
        action="append",
        type=Path,
        default=[],
        help=(
            "Scorer-only all-visible cleanup-relevant movable-object labels. These labels "
            "are private/offline truth and are never included in prompt inputs."
        ),
    )
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--prompt-variant",
        choices=(
            "all",
            "both",
            "baseline_json",
            "skill_json_runtime_map",
            "raw_fpv_visual_labeler",
        ),
        default="both",
    )
    parser.add_argument("--max-frames-per-source", type=_positive_int_arg, default=18)
    parser.add_argument("--threshold", type=_positive_int_arg, default=5)
    parser.add_argument("--max-candidates", type=_candidate_limit_arg, default=3)
    args = parser.parse_args(raw_argv)
    args.runtime_map_prior_explicit = _runtime_map_prior_arg_is_explicit(raw_argv)
    return args


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    output_run_dir = _output_run_dir(args.output_dir, args.run_id)
    output_run_dir.mkdir(parents=True, exist_ok=True)

    raw_run_dirs = tuple(args.raw_run_dir or DEFAULT_RAW_RUN_DIRS)
    contrast_run_dirs = tuple(args.contrast_run_dir or DEFAULT_CONTRAST_RUN_DIRS)
    frames = collect_observation_frames(
        raw_run_dirs=raw_run_dirs,
        contrast_run_dirs=contrast_run_dirs,
        max_frames_per_source=int(args.max_frames_per_source),
    )
    runtime_map_prior = _load_runtime_map_prior(
        args.runtime_map_prior,
        explicit=bool(args.runtime_map_prior_explicit),
    )
    public_inputs = build_public_inputs(
        frames,
        runtime_map_prior=runtime_map_prior,
        max_candidates=int(args.max_candidates),
    )
    labels = load_probe_labels(
        tuple(args.private_labels or ()),
        frames=frames,
        contrast_run_dirs=contrast_run_dirs,
        default_hidden_target=True,
    )
    labels = _dedupe_labels(
        [
            *labels,
            *load_probe_labels(
                tuple(args.all_visible_labels or ()),
                frames=frames,
                contrast_run_dirs=(),
                default_hidden_target=False,
            ),
        ]
    )
    predictions = load_predictions(args.predictions)

    variants = _selected_variants(args.prompt_variant)
    matrix = []
    for variant_id in variants:
        variant_predictions = dict(predictions.get(variant_id) or {})
        execution_status = "predictions_loaded" if variant_predictions else "not_run_offline"
        metrics = score_variant(
            variant_id=variant_id,
            frames=frames,
            labels=labels,
            predictions=variant_predictions,
            threshold=int(args.threshold),
        )
        matrix.append(
            {
                "variant_id": variant_id,
                "provider": "offline",
                "model": "",
                "execution_status": execution_status,
                "provider_errors": [],
                "metrics": metrics,
            }
        )

    prompt_inputs_path = output_run_dir / "prompt_inputs.json"
    prompt_inputs_path.write_text(
        json.dumps(public_inputs, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    score_path = output_run_dir / "private_score.json"
    score_path.write_text(
        json.dumps(
            {
                "schema": "raw_fpv_perception_probe_private_score_v1",
                "label_count": len(labels),
                "private_label_count": sum(1 for item in labels if item.private),
                "hidden_target_label_count": sum(1 for item in labels if item.hidden_target),
                "all_visible_movable_label_count": sum(
                    1 for item in labels if not item.hidden_target
                ),
                "truth_scope": _truth_scope_summary(labels),
                "labels": [item.score_payload() for item in labels],
                "matrix": matrix,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    recommendation = route_recommendation(matrix)
    status = _probe_status(matrix, labels=labels, provider="offline")
    report = {
        "schema": REPORT_SCHEMA,
        "status": status,
        "generated_at": _utc_timestamp(),
        "output_dir": str(output_run_dir),
        "threshold": int(args.threshold),
        "source_runs": {
            "raw": [str(path) for path in raw_run_dirs],
            "contrast": [str(path) for path in contrast_run_dirs],
        },
        "frame_count": len(frames),
        "label_count": len(labels),
        "private_label_count": sum(1 for item in labels if item.private),
        "hidden_target_label_count": sum(1 for item in labels if item.hidden_target),
        "all_visible_movable_label_count": sum(1 for item in labels if not item.hidden_target),
        "missing_label_frame_count": _missing_label_frame_count(frames, labels),
        "truth_scope": _truth_scope_summary(labels),
        "runtime_map_context": {
            "provided": bool(runtime_map_prior),
            "source": str(args.runtime_map_prior) if runtime_map_prior else "",
            "compressed_context_only": True,
            "needs_current_frame_confirm": True,
        },
        "privacy": {
            "private_labels_in_prompt_inputs": _contains_private_label_leak(public_inputs, labels),
            "agent_facing_input_contains_executable_prior_handles": (
                _contains_executable_prior_handle(public_inputs)
            ),
        },
        "artifacts": {
            "prompt_inputs": str(prompt_inputs_path),
            "private_score": str(score_path),
            "html_report": str(output_run_dir / "report.html"),
        },
        "matrix": matrix,
        "route_recommendation": recommendation,
    }
    report_path = output_run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_run_dir / "report.html").write_text(render_html_report(report), encoding="utf-8")
    return report


def collect_observation_frames(
    *,
    raw_run_dirs: tuple[Path, ...],
    contrast_run_dirs: tuple[Path, ...],
    max_frames_per_source: int,
) -> list[ObservationFrame]:
    frames: list[ObservationFrame] = []
    raw_source_frames = []
    for run_dir in raw_run_dirs:
        run_dir = run_dir.expanduser()
        if not run_dir.exists():
            raise FileNotFoundError(f"RAW-FPV source run directory does not exist: {run_dir}")
        raw_source_frames.extend(
            _collect_frames_from_run_dir(run_dir, source_kind="raw_failure")[:max_frames_per_source]
        )
    if not raw_source_frames:
        source_dirs = ", ".join(str(path.expanduser()) for path in raw_run_dirs)
        raise ValueError(
            f"RAW-FPV source run directories did not yield any usable FPV frames: {source_dirs}"
        )
    frames.extend(raw_source_frames)
    for run_dir in contrast_run_dirs:
        run_dir = run_dir.expanduser()
        if not run_dir.exists():
            continue
        collected = _collect_frames_from_run_dir(run_dir, source_kind="contrast")
        frames.extend(collected[:max_frames_per_source])
    return frames


def build_public_inputs(
    frames: list[ObservationFrame],
    *,
    runtime_map_prior: dict[str, Any],
    max_candidates: int,
) -> dict[str, Any]:
    frame_groups = build_frame_groups(frames)
    return {
        "schema": PUBLIC_INPUT_SCHEMA,
        "prompt_contract": {
            "response_schema": RESPONSE_SCHEMA,
            "json_only": True,
            "max_candidates_per_observation": max_candidates,
            "required_candidate_fields": [
                "source_observation_id",
                "category",
                "evidence_note",
                "confidence",
                "locality",
            ],
            "coarse_locality": {
                "screen_grid_regions": list(SCREEN_GRID_REGIONS),
                "surface_hints": list(SURFACE_HINTS),
            },
            "actionability_boundary": (
                "This probe does not authorize cleanup actions. Current-frame RAW-FPV "
                "confirmation would still be required by live cleanup tools."
            ),
        },
        "visual_labeler_contract": {
            "skill_id": "raw-fpv-visual-labeler",
            "response_schema": VISUAL_LABELER_RESPONSE_SCHEMA,
            "perception_only": True,
            "group_size_range": [3, 6],
            "required_label_fields": [
                "evidence_frame_id",
                "category",
                "category_family",
                "coarse_region",
                "confidence",
                "is_cleanup_relevant",
            ],
            "optional_label_fields": [
                "bbox",
                "surface_hint",
                "reason_not_actionable",
            ],
            "category_families": list(MOVABLE_CATEGORY_FAMILIES),
            "fixture_surface_policy": (
                "Fixtures and surfaces may be emitted only as surface_hint or as "
                "non-cleanup-relevant labels; they are not object hits."
            ),
            "privacy_exclusions": [
                "private labels",
                "generated hidden target ids",
                "acceptable destination truth",
                "executable observed-object handles",
                "detector or camera-label producer candidates",
            ],
        },
        "variants": {
            "baseline_json": {
                "description": "Strict JSON RAW-FPV prompt without runtime-map planning context.",
                "frames": [
                    _prompt_payload_for_frame(frame, semantic_context={}) for frame in frames
                ],
            },
            "skill_json_runtime_map": {
                "description": (
                    "Skill-shaped strict JSON prompt with compressed runtime-map planning "
                    "context only. Prior context is not executable."
                ),
                "frames": [
                    _prompt_payload_for_frame(
                        frame,
                        semantic_context=_compressed_semantic_context(
                            frame,
                            runtime_map_prior=runtime_map_prior,
                        ),
                    )
                    for frame in frames
                ],
            },
            "raw_fpv_visual_labeler": {
                "description": (
                    "Dedicated clean-context visual labeler over neighboring RAW-FPV frame "
                    "groups. Labels are perception evidence only and are not executable "
                    "cleanup handles."
                ),
                "frame_groups": [
                    {
                        "group_id": group["group_id"],
                        "grouping_basis": group["grouping_basis"],
                        "frames": [
                            _prompt_payload_for_frame(frame, semantic_context={})
                            for frame in group["frames"]
                        ],
                        "public_context": group["public_context"],
                    }
                    for group in frame_groups
                ],
            },
        },
    }


def build_frame_groups(
    frames: list[ObservationFrame],
    *,
    min_group_size: int = 3,
    max_group_size: int = 6,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[ObservationFrame]] = {}
    for frame in frames:
        grouped.setdefault((frame.source_run_id, frame.waypoint_id or "unknown"), []).append(frame)

    groups: list[dict[str, Any]] = []
    short_groups: dict[str, list[ObservationFrame]] = {}
    fallback_index = 0
    for (source_run_id, waypoint_id), items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: item.source_observation_id)
        if len(ordered) < min_group_size:
            short_groups.setdefault(source_run_id, []).extend(ordered)
            continue
        for chunk in _frame_group_chunks(
            ordered,
            min_group_size=min_group_size,
            max_group_size=max_group_size,
        ):
            fallback_index += 1
            groups.append(
                _frame_group_payload(
                    f"group_{fallback_index:03d}",
                    chunk,
                    grouping_basis="source_waypoint_neighborhood",
                    waypoint_id=waypoint_id,
                    source_run_id=source_run_id,
                )
            )
    for source_run_id, items in sorted(short_groups.items()):
        ordered = sorted(items, key=lambda item: item.source_observation_id)
        for chunk in _frame_group_chunks(
            ordered,
            min_group_size=min_group_size,
            max_group_size=max_group_size,
        ):
            fallback_index += 1
            groups.append(
                _frame_group_payload(
                    f"group_{fallback_index:03d}",
                    chunk,
                    grouping_basis="source_observation_neighborhood",
                    waypoint_id=chunk[0].waypoint_id or "unknown",
                    source_run_id=source_run_id,
                )
            )
    if not groups and frames:
        groups.append(
            _frame_group_payload(
                "group_001",
                frames[:max_group_size],
                grouping_basis="fallback_sequence",
                waypoint_id=frames[0].waypoint_id or "unknown",
                source_run_id=frames[0].source_run_id,
            )
        )
    return groups


def _frame_group_chunks(
    frames: list[ObservationFrame],
    *,
    min_group_size: int,
    max_group_size: int,
) -> list[list[ObservationFrame]]:
    if len(frames) <= max_group_size:
        return [frames]
    group_count = (len(frames) + max_group_size - 1) // max_group_size
    while group_count > 1 and len(frames) // group_count < min_group_size:
        group_count -= 1

    chunks = []
    start = 0
    for index in range(group_count):
        remaining_groups = group_count - index
        remaining_items = len(frames) - start
        size = (remaining_items + remaining_groups - 1) // remaining_groups
        chunks.append(frames[start : start + size])
        start += size
    return chunks


def load_probe_labels(
    paths: Path | tuple[Path, ...] | list[Path] | None,
    *,
    frames: list[ObservationFrame],
    contrast_run_dirs: tuple[Path, ...],
    default_hidden_target: bool,
) -> list[ProbeLabel]:
    labels: list[ProbeLabel] = []
    frame_ids = {frame.frame_id for frame in frames}
    alias_by_key = _frame_aliases(frames)
    if paths is None:
        label_paths: tuple[Path, ...] = ()
    elif isinstance(paths, Path):
        label_paths = (paths,)
    else:
        label_paths = tuple(paths)
    for path in label_paths:
        _require_input_file(path, purpose="RAW-FPV private label manifest")
        payload = _load_json(path, label="RAW-FPV private label manifest")
        rows = payload.get("labels", [])
        if not isinstance(rows, list):
            raise ValueError(
                f"RAW-FPV private label manifest must contain a list in 'labels': {path}"
            )
        for index, item in enumerate(rows):
            label = _label_from_payload(
                item,
                private=True,
                default_hidden_target=default_hidden_target,
                row_index=index,
                source_path=path,
            )
            if label.frame_id in frame_ids:
                labels.append(label)
                continue
            alias = alias_by_key.get(
                (_frame_source_family(label.frame_id), label.source_observation_id)
            )
            if alias:
                labels.append(replace(label, frame_id=alias))
    labels.extend(
        _derive_resolved_contrast_labels(
            contrast_run_dirs=contrast_run_dirs,
            frame_ids=frame_ids,
        )
    )
    unique: dict[tuple[str, str], ProbeLabel] = {}
    for label in labels:
        unique.setdefault((label.frame_id, label.object_id), label)
    return list(unique.values())


def _frame_aliases(frames: list[ObservationFrame]) -> dict[tuple[str, str], str]:
    candidates: dict[tuple[str, str], list[str]] = {}
    for frame in frames:
        candidates.setdefault(
            (_frame_source_family(frame.frame_id), frame.source_observation_id),
            [],
        ).append(frame.frame_id)
    return {key: values[0] for key, values in candidates.items() if len(values) == 1}


def _frame_source_family(frame_id: str) -> str:
    prefix = str(frame_id or "").split("/", 1)[0]
    if prefix.startswith("molmo-raw-fpv-sweep-corpus-"):
        return "molmo-raw-fpv-sweep-corpus"
    if prefix.startswith("household-cleanup-codex-camera-raw-"):
        return "household-cleanup-codex-camera-raw"
    return prefix


def _dedupe_labels(labels: list[ProbeLabel]) -> list[ProbeLabel]:
    unique: dict[tuple[str, str, bool], ProbeLabel] = {}
    for label in labels:
        unique.setdefault((label.frame_id, label.object_id, label.hidden_target), label)
    return list(unique.values())


def load_predictions(path: Path | None) -> dict[str, dict[str, dict[str, Any]]]:
    if path is None:
        return {}
    _require_input_file(path, purpose="RAW-FPV prediction manifest")
    payload = _load_json(path, label="RAW-FPV prediction manifest")
    rows = payload.get("predictions") if "predictions" in payload else payload.get("runs", [])
    if not isinstance(rows, list):
        raise ValueError(
            f"RAW-FPV prediction manifest must contain a list in 'predictions' or 'runs': {path}"
        )
    predictions: dict[str, dict[str, dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"RAW-FPV prediction row {index} must be an object: {path}")
        variant_id = str(row.get("variant_id") or "baseline_json")
        frame_id = str(row.get("frame_id") or "")
        if not frame_id:
            raise ValueError(f"RAW-FPV prediction row {index} is missing frame_id: {path}")
        response = row.get("response")
        if response is None:
            response = row.get("output")
        if isinstance(response, str):
            response = _json_object_from_text(response)
        if not isinstance(response, dict):
            raise ValueError(f"RAW-FPV prediction row {index} response must be an object: {path}")
        predictions.setdefault(variant_id, {})[frame_id] = response
    return predictions


def score_variant(
    *,
    variant_id: str,
    frames: list[ObservationFrame],
    labels: list[ProbeLabel],
    predictions: dict[str, dict[str, Any]],
    threshold: int,
) -> dict[str, Any]:
    return score_variant_metrics(
        variant_id=variant_id,
        frames=frames,
        labels=labels,
        predictions=predictions,
        threshold=threshold,
        response_schema=RESPONSE_SCHEMA,
        visual_labeler_response_schema=VISUAL_LABELER_RESPONSE_SCHEMA,
        failure_classes=FAILURE_CLASSES,
        normalize_response=normalize_response,
        score_candidate=score_candidate,
        ratio=_ratio,
    )


def normalize_response(
    response: dict[str, Any],
    *,
    frame: ObservationFrame,
    variant_id: str = "baseline_json",
) -> dict[str, Any]:
    errors = []
    expected_schema = (
        VISUAL_LABELER_RESPONSE_SCHEMA
        if variant_id == "raw_fpv_visual_labeler"
        else RESPONSE_SCHEMA
    )
    accepted_schemas = {expected_schema, "", None}
    if variant_id != "raw_fpv_visual_labeler":
        accepted_schemas.add(RESPONSE_SCHEMA)
    if response.get("schema") not in accepted_schemas:
        errors.append(f"schema mismatch: {response.get('schema')}")
    raw_candidates = (
        response.get("labels")
        if variant_id == "raw_fpv_visual_labeler" and response.get("labels") is not None
        else response.get("candidates")
    )
    if raw_candidates is None:
        raw_candidates = []
    if not isinstance(raw_candidates, list):
        errors.append(
            "labels must be a list"
            if variant_id == "raw_fpv_visual_labeler"
            else "candidates must be a list"
        )
        raw_candidates = []
    candidates = []
    surface_hint_only_count = 0
    for item in raw_candidates[: 12 if variant_id == "raw_fpv_visual_labeler" else 3]:
        if not isinstance(item, dict):
            errors.append(
                "label must be an object"
                if variant_id == "raw_fpv_visual_labeler"
                else "candidate must be an object"
            )
            continue
        if variant_id == "raw_fpv_visual_labeler":
            candidate, item_errors = _normalize_visual_label(item, frame=frame)
        else:
            candidate, item_errors = _normalize_candidate(item, frame=frame)
        errors.extend(item_errors)
        if candidate:
            if candidate.get("surface_hint_only"):
                surface_hint_only_count += 1
            else:
                candidates.append(candidate)
    return {
        "schema_errors": errors,
        "candidates": candidates,
        "surface_hint_only_count": surface_hint_only_count,
    }


def score_candidate(candidate: dict[str, Any], labels: list[ProbeLabel]) -> dict[str, Any]:
    if not labels:
        return {
            "strict_bbox_confirmable": False,
            "coarse_confirmable": False,
            "matched_object_id": "",
            "failure_class": "missing_private_label",
            "category_match": False,
            "category_match_tier": "mismatch",
            "bbox_iou": 0.0,
            "coarse_region_match": False,
        }
    best: dict[str, Any] | None = None
    for label in labels:
        tier = category_match_tier(
            candidate.get("category", ""),
            label.category,
            candidate_family=str(candidate.get("category_family") or ""),
            label_family=label.category_family,
        )
        category_match = tier != "mismatch"
        bbox_iou = _bbox_iou(candidate.get("bbox"), label.bbox)
        candidate_regions = set(candidate.get("coarse_regions") or [])
        label_regions = set(label.coarse_regions or ())
        coarse_region_match = bool(candidate_regions.intersection(label_regions))
        strict_confirmable = category_match and bbox_iou > 0.1
        coarse_confirmable = category_match and coarse_region_match
        score_value = (10 if strict_confirmable else 0) + (5 if coarse_confirmable else 0)
        score_value += bbox_iou
        item = {
            "strict_bbox_confirmable": strict_confirmable,
            "coarse_confirmable": coarse_confirmable,
            "matched_object_id": (
                label.object_id if strict_confirmable or coarse_confirmable else ""
            ),
            "category_match": category_match,
            "category_match_tier": tier,
            "bbox_iou": round(bbox_iou, 6),
            "coarse_region_match": coarse_region_match,
            "label_category": label.category,
            "label_category_family": label.category_family,
            "label_coarse_regions": list(label.coarse_regions),
        }
        if best is None or score_value > float(best["_score_value"]):
            item["_score_value"] = score_value
            best = item
    assert best is not None
    best.pop("_score_value", None)
    if not best["strict_bbox_confirmable"] and not best["coarse_confirmable"]:
        if not candidate.get("bbox") and not candidate.get("coarse_regions"):
            best["failure_class"] = "locality_too_coarse_or_invalid"
        elif not best["category_match"]:
            best["failure_class"] = "semantic_mismatch/unresolved"
        else:
            best["failure_class"] = "locality_too_coarse_or_invalid"
    else:
        best["failure_class"] = ""
    return best


def route_recommendation(matrix: list[dict[str, Any]]) -> str:
    if any(
        str(item.get("variant_id") or "") == "raw_fpv_visual_labeler"
        and ((item.get("metrics") or {}).get("visible_movable_label_quality") or {}).get("status")
        == "truth_sparse"
        for item in matrix
    ):
        return "needs_all_visible_movable_truth"
    strict_met = any(
        ((item.get("metrics") or {}).get("live_like_top_candidate") or {}).get(
            "strict_bbox_threshold_met"
        )
        for item in matrix
    )
    coarse_met = any(
        ((item.get("metrics") or {}).get("live_like_top_candidate") or {}).get(
            "coarse_threshold_met"
        )
        for item in matrix
    )
    if strict_met:
        return "keep_raw_fpv_baseline_only"
    if coarse_met:
        return "try_live_coarse_locality_contract"
    if any((item.get("metrics") or {}).get("candidate_count") for item in matrix):
        return "prefer_camera_grounded_labels"
    return "keep_raw_fpv_baseline_only"


def _frame_group_payload(
    group_id: str,
    frames: list[ObservationFrame],
    *,
    grouping_basis: str,
    waypoint_id: str,
    source_run_id: str,
) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "grouping_basis": grouping_basis,
        "source_run_id": source_run_id,
        "waypoint_id": waypoint_id,
        "frames": frames,
        "public_context": {
            "source_run_id": source_run_id,
            "waypoint_id": waypoint_id,
            "room_id": next((frame.room_id for frame in frames if frame.room_id), ""),
            "frame_count": len(frames),
            "perception_only": True,
            "non_executable_planning_context_only": True,
        },
    }


def render_prompt(frame_payload: dict[str, Any], *, variant_id: str) -> str:
    if variant_id == "raw_fpv_visual_labeler":
        return _render_visual_labeler_prompt(frame_payload)
    contract = (
        "Return only strict JSON with schema raw_fpv_probe_response_v1. "
        "Return at most three candidates. Each candidate must include "
        "source_observation_id, category, evidence_note, confidence, and locality. "
        "locality may include bbox as normalized [x,y,width,height] and must include "
        "coarse_region from the fixed 3x3 screen grid when bbox is uncertain. "
        "Allowed coarse_region values: "
        + ", ".join(SCREEN_GRID_REGIONS)
        + ". Allowed surface_hint values: "
        + ", ".join(SURFACE_HINTS)
        + ". Do not include markdown, private labels, object handles, fixture ids, "
        "world-label detections, detector outputs, or cleanup action commands."
    )
    target_text = "; ".join(RAW_FPV_HIGH_CONFIDENCE_TARGETS)
    context = frame_payload.get("runtime_map_context") or {}
    semantic_text = ""
    if variant_id == "skill_json_runtime_map":
        semantic_text = (
            "\nCompressed public planning context, not executable handles: "
            + json.dumps(context, sort_keys=True)
        )
    return (
        f"{contract}\nObservation: {frame_payload.get('source_observation_id')} "
        f"at waypoint {frame_payload.get('waypoint_id') or 'unknown'}.\n"
        f"Look only for current-frame cleanup objects: {RAW_FPV_CATEGORY_HINT}. "
        f"Prioritize: {target_text}.{semantic_text}\n"
        'Output shape: {"schema":"raw_fpv_probe_response_v1",'
        '"source_observation_id":"...","candidates":[{"source_observation_id":"...",'
        '"category":"book","evidence_note":"visible book on lower shelf",'
        '"confidence":0.72,"locality":{"bbox":[0.1,0.2,0.3,0.4],'
        '"coarse_region":"lower_left","surface_hint":"shelf"}}]}'
    )


def _render_visual_labeler_prompt(group_payload: dict[str, Any]) -> str:
    frames = [
        {
            "frame_id": frame.get("frame_id"),
            "source_observation_id": frame.get("source_observation_id"),
            "waypoint_id": frame.get("waypoint_id"),
            "room_id": frame.get("room_id"),
            "image_sha256": frame.get("image_sha256"),
        }
        for frame in group_payload.get("frames") or []
        if isinstance(frame, dict)
    ]
    return (
        "Use the raw-fpv-visual-labeler skill. Return only strict JSON with schema "
        "raw_fpv_visual_labeler_response_v1. The attached images are the listed frames "
        "in order. Label visible cleanup-relevant movable objects only; fixtures and "
        "surfaces may appear only as surface_hint or is_cleanup_relevant=false. "
        "Do not include private labels, hidden target ids, acceptable destinations, "
        "observed-object handles, detector candidates, camera-label producer candidates, "
        "or cleanup commands. Required fields per label: evidence_frame_id, category, "
        "category_family, coarse_region, confidence, is_cleanup_relevant. Optional fields: "
        "bbox, surface_hint, reason_not_actionable. Allowed category_family values: "
        + ", ".join(MOVABLE_CATEGORY_FAMILIES)
        + ". Allowed coarse_region values: "
        + ", ".join(SCREEN_GRID_REGIONS)
        + ". Allowed surface_hint values: "
        + ", ".join(SURFACE_HINTS)
        + ".\nGroup public context: "
        + json.dumps(group_payload.get("public_context") or {}, sort_keys=True)
        + "\nFrames: "
        + json.dumps(frames, sort_keys=True)
        + '\nOutput shape: {"schema":"raw_fpv_visual_labeler_response_v1","labels":['
        '{"evidence_frame_id":"run/raw_fpv_001","category":"mug","category_family":"dish",'
        '"coarse_region":"middle_right","confidence":0.82,"is_cleanup_relevant":true,'
        '"bbox":[0.62,0.5,0.12,0.15],"surface_hint":"table",'
        '"reason_not_actionable":""}]}'
    )


def render_html_report(report: dict[str, Any]) -> str:
    rows = []
    for item in report.get("matrix") or []:
        metrics = item.get("metrics") or {}
        live_like = metrics.get("live_like_top_candidate") or {}
        visible = metrics.get("visible_movable_label_quality") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('variant_id') or ''))}</td>"
            f"<td>{html.escape(str(item.get('execution_status') or ''))}</td>"
            f"<td>{metrics.get('candidate_count', 0)}</td>"
            f"<td>{metrics.get('strict_bbox_unique_confirmable_count', 0)}</td>"
            f"<td>{metrics.get('coarse_unique_confirmable_count', 0)}</td>"
            f"<td>{html.escape(str(visible.get('status') or ''))}</td>"
            f"<td>{visible.get('unique_matched_object_count', 0)}</td>"
            f"<td>{visible.get('precision', 0.0)}</td>"
            f"<td>{metrics.get('duplicate_count', 0)}</td>"
            f"<td>{html.escape(str(live_like.get('coarse_threshold_met', False)))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>RAW-FPV Perception Probe</title>"
        "<style>body{font-family:sans-serif;max-width:1100px;margin:32px auto;padding:0 16px;}"
        "table{border-collapse:collapse;width:100%;}td,th{border:1px solid #ccc;padding:6px;}"
        "th{text-align:left;background:#f4f4f4;}code{background:#f4f4f4;padding:2px 4px;}"
        "</style></head><body>"
        "<h1>RAW-FPV Perception Probe</h1>"
        f"<p>Status: <code>{html.escape(str(report.get('status') or ''))}</code></p>"
        "<p>Route recommendation: <code>"
        f"{html.escape(str(report.get('route_recommendation') or ''))}</code></p>"
        f"<p>Frames: {report.get('frame_count', 0)}; labels: {report.get('label_count', 0)}; "
        f"private labels: {report.get('private_label_count', 0)}; "
        f"missing label frames: {report.get('missing_label_frame_count', 0)}</p>"
        "<h2>Split Metrics</h2>"
        "<table><thead><tr><th>Variant</th><th>Execution</th><th>Candidates</th>"
        "<th>Hidden strict unique</th><th>Hidden coarse unique</th>"
        "<th>Visible truth</th><th>Visible unique</th><th>Visible precision</th><th>Duplicates</th>"
        "<th>Coarse threshold met</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        "<h2>Truth Scope</h2><pre>"
        + html.escape(json.dumps(report.get("truth_scope") or {}, indent=2, sort_keys=True))
        + "</pre>"
        "<h2>Privacy</h2><pre>"
        + html.escape(json.dumps(report.get("privacy") or {}, indent=2, sort_keys=True))
        + "</pre></body></html>"
    )


def _collect_frames_from_run_dir(run_dir: Path, *, source_kind: str) -> list[ObservationFrame]:
    run_id = _run_id_for_path(run_dir)
    raw_items: dict[str, dict[str, Any]] = {}
    for item in _raw_observations_from_json_artifacts(run_dir):
        raw_items.setdefault(str(item.get("observation_id") or ""), item)
    for item in _raw_observations_from_codex_events(run_dir):
        raw_items.setdefault(str(item.get("observation_id") or ""), item)
    for item in _raw_observations_from_robot_view_files(run_dir):
        raw_items.setdefault(str(item.get("observation_id") or ""), item)
    frames = []
    for observation_id in sorted(raw_items):
        item = raw_items[observation_id]
        image_artifacts = item.get("image_artifacts") or {}
        image_value = str(image_artifacts.get("fpv") or item.get("fpv_image") or "")
        image_path = _resolve_artifact_path(run_dir, image_value)
        if not image_path.is_file():
            continue
        width, height = _image_dimensions(image_path)
        frame_id = f"{run_id}/{observation_id}"
        frames.append(
            ObservationFrame(
                frame_id=frame_id,
                source_run_id=run_id,
                source_kind=source_kind,
                source_observation_id=observation_id,
                waypoint_id=str(item.get("waypoint_id") or ""),
                room_id=str(item.get("room_id") or ""),
                image_path=image_path,
                image_artifact=image_value,
                width=width,
                height=height,
                image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
            )
        )
    return frames


def _raw_observations_from_json_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    observations = []
    for name in ("raw_fpv_observations.json", "agent_view.json", "run_result.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        payload = _load_json(path, label="RAW-FPV run artifact")
        observations.extend(
            item
            for item in payload.get("raw_fpv_observations") or []
            if isinstance(item, dict) and item.get("observation_id")
        )
        agent_view = payload.get("agent_view") or {}
        if payload.get("schema") == agent_view_module.AGENT_VIEW_SCHEMA:
            agent_view = payload
        observations.extend(
            item
            for item in (agent_view_module.raw_fpv_observations(agent_view) if agent_view else [])
            if isinstance(item, dict) and item.get("observation_id")
        )
    return observations


def _raw_observations_from_codex_events(run_dir: Path) -> list[dict[str, Any]]:
    observations = []
    for path in sorted(run_dir.glob("codex-events*.jsonl")):
        for line_number, event in _load_codex_event_rows(path):
            item = event.get("item") or {}
            if item.get("type") != "mcp_tool_call" or item.get("tool") != "observe":
                continue
            if event.get("type") != "item.completed":
                continue
            payload = _mcp_text_result_json(
                item.get("result") or {},
                source=f"{path}:{line_number}",
            )
            raw = (payload.get("raw_fpv_observation") or {}) if payload else {}
            if raw.get("observation_id"):
                observations.append(raw)
    return observations


def _load_codex_event_rows(path: Path) -> list[tuple[int, dict[str, Any]]]:
    return read_jsonl_object_rows(path, label="RAW-FPV Codex event")


def _raw_observations_from_robot_view_files(run_dir: Path) -> list[dict[str, Any]]:
    robot_views = run_dir / "robot_views"
    if not robot_views.is_dir():
        return []
    observations = []
    pattern = re.compile(r"(?P<label>\d+_raw_fpv_(?P<num>\d{3}))\.fpv\.png$")
    for path in sorted(robot_views.glob("*_raw_fpv_*.fpv.png")):
        match = pattern.search(path.name)
        if not match:
            continue
        observation_id = f"raw_fpv_{match.group('num')}"
        observations.append(
            {
                "observation_id": observation_id,
                "waypoint_id": "",
                "room_id": "generated_area",
                "image_artifacts": {"fpv": f"robot_views/{path.name}"},
                "robot_view_label": match.group("label"),
            }
        )
    return observations


def _derive_resolved_contrast_labels(
    *,
    contrast_run_dirs: tuple[Path, ...],
    frame_ids: set[str],
) -> list[ProbeLabel]:
    labels = []
    for run_dir in contrast_run_dirs:
        run_id = _run_id_for_path(run_dir.expanduser())
        for payload_name in ("run_result.json", "agent_view.json"):
            path = run_dir / payload_name
            if not path.is_file():
                continue
            payload = _load_json(path, label="RAW-FPV contrast artifact")
            observations = payload.get("model_declared_observations") or []
            if payload.get("schema") == agent_view_module.AGENT_VIEW_SCHEMA:
                observations = agent_view_module.model_declared_observations(payload)
            for item in observations:
                if item.get("grounding_status") != "resolved":
                    continue
                observation_id = str(item.get("source_observation_id") or "")
                frame_id = f"{run_id}/{observation_id}"
                if frame_id not in frame_ids:
                    continue
                bbox = _bbox_tuple((item.get("image_region") or {}).get("value"))
                labels.append(
                    ProbeLabel(
                        frame_id=frame_id,
                        source_observation_id=observation_id,
                        object_id=str(item.get("object_id") or ""),
                        category=str(item.get("category") or "object"),
                        category_family=_category_family(str(item.get("category") or "object")),
                        bbox=bbox,
                        coarse_regions=tuple(_coarse_regions_from_bbox(bbox)),
                        surface_hint="unknown",
                        label_source="resolved_camera_label_contrast",
                        private=False,
                        hidden_target=False,
                    )
                )
    return labels


def _label_from_payload(
    item: dict[str, Any],
    *,
    private: bool,
    default_hidden_target: bool,
    row_index: int,
    source_path: Path,
) -> ProbeLabel:
    if not isinstance(item, dict):
        raise ValueError(f"RAW-FPV private label row {row_index} must be an object: {source_path}")
    if not str(item.get("frame_id") or item.get("source_observation_id") or ""):
        raise ValueError(
            "RAW-FPV private label row "
            f"{row_index} is missing frame_id or source_observation_id: {source_path}"
        )
    if not str(item.get("object_id") or ""):
        raise ValueError(
            f"RAW-FPV private label row {row_index} is missing object_id: {source_path}"
        )
    if not str(item.get("category") or ""):
        raise ValueError(
            f"RAW-FPV private label row {row_index} is missing category: {source_path}"
        )
    bbox = _bbox_tuple(item.get("bbox") or item.get("image_bbox"))
    if bbox is None and not item.get("coarse_regions"):
        raise ValueError(
            "RAW-FPV private label row "
            f"{row_index} must include bbox/image_bbox or coarse_regions: {source_path}"
        )
    coarse_regions = tuple(
        region
        for region in (item.get("coarse_regions") or _coarse_regions_from_bbox(bbox))
        if region in SCREEN_GRID_REGIONS
    )
    surface_hint = str(item.get("surface_hint") or "unknown")
    if surface_hint not in SURFACE_HINTS:
        surface_hint = "unknown"
    return ProbeLabel(
        frame_id=str(item.get("frame_id") or ""),
        source_observation_id=str(item.get("source_observation_id") or ""),
        object_id=str(item.get("object_id") or ""),
        category=str(item.get("category") or "object"),
        category_family=_category_family(
            str(item.get("category_family") or item.get("family") or item.get("category") or "")
        ),
        bbox=bbox,
        coarse_regions=coarse_regions,
        surface_hint=surface_hint,
        label_source=str(item.get("label_source") or "private_manifest"),
        private=private,
        hidden_target=bool(item.get("hidden_target", default_hidden_target)),
    )


def _prompt_payload_for_frame(
    frame: ObservationFrame,
    *,
    semantic_context: dict[str, Any],
) -> dict[str, Any]:
    payload = frame.public_payload()
    payload["image_path"] = str(frame.image_path)
    payload["runtime_map_context"] = semantic_context
    payload["needs_confirm"] = True
    payload["private_truth_included"] = False
    payload["executable_prior_handles_included"] = False
    return payload


def _compressed_semantic_context(
    frame: ObservationFrame,
    *,
    runtime_map_prior: dict[str, Any],
) -> dict[str, Any]:
    categories = set()
    historical_directions = []
    for item in runtime_map_prior.get("observed_objects") or []:
        if item.get("source_observation_id") == frame.source_observation_id:
            category = str(item.get("category") or "")
            if category:
                categories.add(category.lower())
    for anchor in runtime_map_prior.get("public_semantic_anchors") or []:
        if anchor.get("waypoint_id") != frame.waypoint_id:
            continue
        category = str(anchor.get("category") or "")
        if category and category not in {"room_area", "observation_waypoint"}:
            categories.add(category.lower())
        pose = anchor.get("pose") or {}
        if "yaw" in pose:
            historical_directions.append({"yaw": pose.get("yaw")})
    if not categories:
        categories.update(("food", "dish", "book", "linen", "toy", "electronics", "pillow"))
    return {
        "waypoint_id": frame.waypoint_id,
        "area": frame.room_id or "generated_area",
        "likely_categories": sorted(categories)[:10],
        "historical_observation_direction": historical_directions[:2],
        "needs_confirm": True,
        "non_executable_planning_context_only": True,
    }


def _normalize_candidate(
    item: dict[str, Any],
    *,
    frame: ObservationFrame,
) -> tuple[dict[str, Any], list[str]]:
    errors = []
    observation_id = str(item.get("source_observation_id") or "")
    if observation_id and observation_id != frame.source_observation_id:
        errors.append("source_observation_id does not match frame")
    category = str(item.get("category") or "").strip().lower()
    if not category:
        errors.append("category is required")
    evidence_note = str(item.get("evidence_note") or "").strip()
    if not evidence_note:
        errors.append("evidence_note is required")
    locality = item.get("locality") or {}
    image_region = item.get("image_region") or {}
    bbox = _bbox_tuple(locality.get("bbox") or image_region.get("value") or item.get("bbox"))
    coarse = locality.get("coarse_region") or locality.get("screen_grid_region")
    coarse_regions = []
    if str(coarse or "") in SCREEN_GRID_REGIONS:
        coarse_regions.append(str(coarse))
    coarse_regions.extend(region for region in _coarse_regions_from_bbox(bbox) if region)
    surface_hint = str(locality.get("surface_hint") or "unknown")
    if surface_hint not in SURFACE_HINTS:
        surface_hint = "unknown"
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("confidence must be numeric")
    candidate = {
        "source_observation_id": observation_id or frame.source_observation_id,
        "category": category,
        "category_family": _category_family(category),
        "evidence_note": evidence_note,
        "confidence": confidence,
        "bbox": bbox,
        "coarse_regions": sorted(set(coarse_regions)),
        "surface_hint": surface_hint,
        "surface_hint_only": False,
    }
    if not bbox and not coarse_regions:
        errors.append("locality must include bbox or coarse_region")
    return candidate, errors


def _normalize_visual_label(
    item: dict[str, Any],
    *,
    frame: ObservationFrame,
) -> tuple[dict[str, Any], list[str]]:
    errors = []
    evidence_frame_id = str(item.get("evidence_frame_id") or item.get("frame_id") or "")
    if evidence_frame_id and evidence_frame_id != frame.frame_id:
        errors.append("evidence_frame_id does not match frame")
    category = str(item.get("category") or "").strip().lower()
    if not category:
        errors.append("category is required")
    category_family = _category_family(str(item.get("category_family") or category))
    if (
        category_family not in MOVABLE_CATEGORY_FAMILIES
        and category not in FIXTURE_OR_SURFACE_CATEGORIES
    ):
        errors.append("category_family is not a supported cleanup family")
    coarse = item.get("coarse_region") or item.get("screen_grid_region")
    locality = item.get("locality") if isinstance(item.get("locality"), dict) else {}
    if not coarse:
        coarse = locality.get("coarse_region") or locality.get("screen_grid_region")
    coarse_regions = []
    if str(coarse or "") in SCREEN_GRID_REGIONS:
        coarse_regions.append(str(coarse))
    else:
        errors.append("coarse_region is required")
    bbox = _bbox_tuple(item.get("bbox") or locality.get("bbox"))
    coarse_regions.extend(region for region in _coarse_regions_from_bbox(bbox) if region)
    surface_hint = str(item.get("surface_hint") or locality.get("surface_hint") or "unknown")
    if surface_hint not in SURFACE_HINTS:
        surface_hint = "unknown"
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("confidence must be numeric")
    cleanup_relevant = item.get("is_cleanup_relevant")
    if not isinstance(cleanup_relevant, bool):
        errors.append("is_cleanup_relevant must be boolean")
        cleanup_relevant = False
    surface_hint_only = (
        not cleanup_relevant
        or _category_norm(category)
        in {_category_norm(value) for value in FIXTURE_OR_SURFACE_CATEGORIES}
        or category_family not in MOVABLE_CATEGORY_FAMILIES
    )
    candidate = {
        "source_observation_id": frame.source_observation_id,
        "evidence_frame_id": evidence_frame_id or frame.frame_id,
        "category": category,
        "category_family": category_family,
        "evidence_note": str(item.get("reason_not_actionable") or item.get("evidence_note") or ""),
        "confidence": confidence,
        "bbox": bbox,
        "coarse_regions": sorted(set(coarse_regions)),
        "surface_hint": surface_hint,
        "is_cleanup_relevant": bool(cleanup_relevant),
        "reason_not_actionable": str(item.get("reason_not_actionable") or ""),
        "surface_hint_only": surface_hint_only,
    }
    return candidate, errors


def category_matches(candidate: str, label: str) -> bool:
    return category_match_tier(candidate, label) != "mismatch"


def category_match_tier(
    candidate: str,
    label: str,
    *,
    candidate_family: str = "",
    label_family: str = "",
) -> str:
    candidate_norm = _category_norm(candidate)
    label_norm = _category_norm(label)
    if candidate_norm == label_norm:
        return "exact"
    if _semantic_category_alias(candidate_norm) == _semantic_category_alias(label_norm):
        return "semantic"
    candidate_family_norm = _category_family(candidate_family or candidate)
    label_family_norm = _category_family(label_family or label)
    if candidate_family_norm and candidate_family_norm == label_family_norm:
        return "coarse_family"
    return "mismatch"


def _category_family(value: str) -> str:
    norm = _category_norm(value)
    families = _category_families()
    for family, members in families.items():
        if norm in members:
            return family
    return norm if norm in MOVABLE_CATEGORY_FAMILIES else ""


def _semantic_category_alias(value: str) -> str:
    aliases = {
        "irishpotato": "potato",
        "remotecontrol": "remote",
        "tvremote": "remote",
        "mug": "cup",
        "teacup": "cup",
        "dishware": "dish",
        "cloth": "linen",
        "blanket": "linen",
        "cushion": "pillow",
    }
    return aliases.get(value, value)


def _category_families() -> dict[str, set[str]]:
    return {
        "dish": {"dish", "dishware", "plate", "bowl", "cup", "mug", "teacup"},
        "food": {"food", "potato", "irishpotato", "apple", "fruit", "vegetable", "bread"},
        "electronics": {
            "electronics",
            "remote",
            "remotecontrol",
            "tvremote",
            "phone",
            "laptop",
        },
        "linen": {"linen", "pillow", "cushion", "towel", "blanket", "cloth"},
        "toy": {"toy", "ball"},
        "book": {"book", "notebook"},
    }


def _category_norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _bbox_iou(
    first: tuple[float, float, float, float] | None,
    second: tuple[float, float, float, float] | None,
) -> float:
    if first is None or second is None:
        return 0.0
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    intersection = iw * ih
    union = aw * ah + bw * bh - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _bbox_tuple(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (
        max(0.0, min(1.0, x)),
        max(0.0, min(1.0, y)),
        max(0.0, min(1.0, width)),
        max(0.0, min(1.0, height)),
    )


def _coarse_regions_from_bbox(
    bbox: tuple[float, float, float, float] | None,
) -> list[str]:
    if bbox is None:
        return []
    x, y, width, height = bbox
    center_x = max(0.0, min(0.999, x + width / 2.0))
    center_y = max(0.0, min(0.999, y + height / 2.0))
    col = 0 if center_x < 1 / 3 else 1 if center_x < 2 / 3 else 2
    row = 0 if center_y < 1 / 3 else 1 if center_y < 2 / 3 else 2
    return [SCREEN_GRID_REGIONS[row * 3 + col]]


def _json_object_from_text(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        return {"schema": RESPONSE_SCHEMA, "candidates": []}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"schema": RESPONSE_SCHEMA, "candidates": []}


def _selected_variants(value: str) -> tuple[str, ...]:
    if value == "all":
        return ("baseline_json", "skill_json_runtime_map", "raw_fpv_visual_labeler")
    if value == "both":
        return ("baseline_json", "skill_json_runtime_map")
    return (value,)


def _probe_status(
    matrix: list[dict[str, Any]],
    *,
    labels: list[ProbeLabel],
    provider: str,
) -> str:
    if not labels:
        return "partial"
    if not any(not label.hidden_target for label in labels):
        return "partial"
    if provider == "offline" and not any(
        (item.get("metrics") or {}).get("candidate_count") for item in matrix
    ):
        return "partial"
    return "success"


def _missing_label_frame_count(frames: list[ObservationFrame], labels: list[ProbeLabel]) -> int:
    labeled = {item.frame_id for item in labels}
    return sum(1 for frame in frames if frame.frame_id not in labeled)


def _contains_private_label_leak(public_inputs: dict[str, Any], labels: list[ProbeLabel]) -> bool:
    text = json.dumps(public_inputs, sort_keys=True)
    return any(label.private and label.object_id and label.object_id in text for label in labels)


def _contains_executable_prior_handle(public_inputs: dict[str, Any]) -> bool:
    text = json.dumps(public_inputs, sort_keys=True)
    return bool(re.search(r"\b(observed_\d+|anchor_fixture_\d+)\b", text))


def _truth_scope_summary(labels: list[ProbeLabel]) -> dict[str, Any]:
    hidden_objects = {label.object_id for label in labels if label.hidden_target}
    visible_objects = {label.object_id for label in labels if not label.hidden_target}
    if visible_objects:
        scope = "all_visible_movable_or_mixed"
    elif hidden_objects:
        scope = "hidden_targets_only"
    else:
        scope = "missing"
    return {
        "scope": scope,
        "hidden_target_object_count": len(hidden_objects),
        "all_visible_movable_object_count": len(visible_objects),
        "visible_movable_quality_claim": "scoreable" if visible_objects else "truth_sparse",
        "hidden_target_recovery_scoreable": bool(hidden_objects),
        "scorer_only": True,
    }


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if float(denominator or 0.0) <= 0.0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _console_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": report.get("status"),
        "report": report.get("artifacts", {}).get("html_report"),
        "report_json": str(Path(str(report.get("output_dir", ""))) / "report.json"),
        "frame_count": report.get("frame_count"),
        "label_count": report.get("label_count"),
        "route_recommendation": report.get("route_recommendation"),
    }


def _mcp_text_result_json(
    result: dict[str, Any], *, source: str = "MCP tool result"
) -> dict[str, Any]:
    for content in result.get("content") or []:
        if not isinstance(content, dict) or content.get("type") != "text":
            continue
        try:
            payload = json.loads(str(content.get("text") or ""))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"RAW-FPV Codex observe result contains invalid JSON at {source}: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"RAW-FPV Codex observe result must be an object at {source}")
        return payload
    return {}


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _resolve_artifact_path(run_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return run_dir / path


def _run_id_for_path(path: Path) -> str:
    parts = [part for part in path.parts[-4:] if part not in {"output", "household"}]
    return _safe_filename("-".join(parts))


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "item"


def _runtime_map_prior_arg_is_explicit(argv: list[str]) -> bool:
    return any(
        arg == "--runtime-map-prior" or arg.startswith("--runtime-map-prior=") for arg in argv
    )


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    return read_json_object(path, label=label)


def _load_runtime_map_prior(path: Path, *, explicit: bool) -> dict[str, Any]:
    if explicit and not path.is_file():
        raise FileNotFoundError(f"RAW-FPV runtime map prior does not exist: {path}")
    return _load_json_if_exists(path, label="RAW-FPV runtime map prior")


def _load_json_if_exists(path: Path, *, label: str) -> dict[str, Any]:
    if path and path.is_file():
        return _load_json(path, label=label)
    return {}


def _require_input_file(path: Path, *, purpose: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{purpose} does not exist: {path}")


def _output_run_dir(output_root: Path, run_id: str) -> Path:
    if run_id:
        return output_root / _safe_filename(run_id)
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    return output_root / stamp


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


def _candidate_limit_arg(value: str) -> int:
    parsed = _positive_int_arg(value)
    if parsed > 3:
        raise argparse.ArgumentTypeError(f"expected a candidate limit from 1 to 3; got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
