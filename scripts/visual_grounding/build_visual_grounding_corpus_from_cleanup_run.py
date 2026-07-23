#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object  # noqa: E402
from roboclaws.household import agent_view as agent_view_module  # noqa: E402
from roboclaws.household.household_runtime_contract import (  # noqa: E402
    VISUAL_GROUNDING_CATEGORY_HINTS,
)

CORPUS_SCHEMA = "visual_grounding_benchmark_corpus_v1"
DEFAULT_CATEGORY_FAMILY_MAP = {
    "apple": "food",
    "book": "book",
    "bowl": "dish",
    "bread": "food",
    "cup": "dish",
    "dish": "dish",
    "egg": "food",
    "electronics": "electronics",
    "food": "food",
    "lettuce": "food",
    "linen": "linen",
    "mug": "dish",
    "newspaper": "book",
    "pillow": "pillow",
    "plate": "dish",
    "potato": "food",
    "remote": "electronics",
    "remotecontrol": "electronics",
    "teddybear": "toy",
    "towel": "linen",
    "toy": "toy",
}
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a visual-grounding benchmark corpus from a stored MolmoSpaces "
            "cleanup run_result.json and RAW_FPV image artifacts."
        )
    )
    parser.add_argument(
        "run_result",
        type=Path,
        help="Path to run_result.json or a cleanup run directory containing it.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output corpus JSON path.")
    parser.add_argument(
        "--name",
        default="",
        help="Corpus name. Defaults to the source scenario/run id.",
    )
    parser.add_argument(
        "--max-observations",
        type=int,
        default=0,
        help="Limit exported observations; 0 means all observations.",
    )
    parser.add_argument(
        "--skip-missing-images",
        action="store_true",
        help="Skip observations with missing RAW_FPV files instead of failing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_result_path = _resolve_run_result(args.run_result)
    run_dir = run_result_path.parent
    try:
        run_result = read_json_object(run_result_path, label="cleanup run result")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    observations = build_corpus_observations(
        run_result=run_result,
        run_dir=run_dir,
        output_dir=output_path.parent,
        max_observations=args.max_observations,
        skip_missing_images=args.skip_missing_images,
    )
    corpus = {
        "schema": CORPUS_SCHEMA,
        "name": args.name or _default_corpus_name(run_result, run_result_path),
        "description": (
            "Corpus generated from stored MolmoSpaces RAW_FPV cleanup artifacts. "
            "Private labels are benchmark scoring data only and are not sent to "
            "the visual-grounding service."
        ),
        "source_run_result": str(run_result_path),
        "label_source": "private_evaluation_room_presence",
        "category_family_map": DEFAULT_CATEGORY_FAMILY_MAP,
        "observations": observations,
    }
    output_path.write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"visual grounding corpus: {output_path}")
    print(f"observations: {len(observations)}")
    return 0


def build_corpus_observations(
    *,
    run_result: dict[str, Any],
    run_dir: Path,
    output_dir: Path,
    max_observations: int,
    skip_missing_images: bool,
) -> list[dict[str, Any]]:
    raw_observations = _raw_fpv_observations(run_result)
    if max_observations > 0:
        raw_observations = raw_observations[:max_observations]
    fixtures_by_room = _fixtures_by_room(run_result)
    room_by_fixture_id = _room_by_fixture_id(fixtures_by_room)
    labels_by_room = _private_labels_by_room(
        run_result,
        room_by_fixture_id=room_by_fixture_id,
    )
    output: list[dict[str, Any]] = []
    for raw in raw_observations:
        image_path = _raw_fpv_image_path(raw, run_dir)
        if image_path is None or not image_path.is_file():
            if skip_missing_images:
                continue
            raise SystemExit(f"missing RAW_FPV image for {raw.get('observation_id')}: {image_path}")
        observation_id = _safe_id(str(raw.get("observation_id") or f"raw_fpv_{len(output) + 1}"))
        image_rel = Path("raw_fpv") / f"{observation_id}{image_path.suffix.lower() or '.png'}"
        target_image_path = output_dir / image_rel
        target_image_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, target_image_path)
        width, height = _image_dimensions(target_image_path)
        room_id = str(raw.get("room_id") or "")
        output.append(
            {
                "observation_id": str(raw.get("observation_id") or observation_id),
                "waypoint_id": str(raw.get("waypoint_id") or ""),
                "room_id": room_id,
                "capture_context": {
                    "discovered_during": "waypoint_observe",
                    "source_artifact_status": str(raw.get("artifact_status") or ""),
                },
                "category_hints": list(VISUAL_GROUNDING_CATEGORY_HINTS),
                "static_fixture_projection": fixtures_by_room.get(room_id, []),
                "image": {
                    "source": "path",
                    "path": str(image_rel),
                    "width": width,
                    "height": height,
                },
                "private_labels": labels_by_room.get(room_id, []),
            }
        )
    if not output:
        raise SystemExit("no RAW_FPV observations were exported")
    return output


def _resolve_run_result(path: Path) -> Path:
    if path.is_dir():
        path = path / "run_result.json"
    if not path.is_file():
        raise SystemExit(f"missing run_result.json: {path}")
    return path


def _raw_fpv_observations(run_result: dict[str, Any]) -> list[dict[str, Any]]:
    agent_view = run_result.get("agent_view") or {}
    raw = run_result.get("raw_fpv_observations") or (
        agent_view_module.raw_fpv_observations(agent_view) if agent_view else []
    )
    return [dict(item) for item in raw if isinstance(item, dict)]


def _fixtures_by_room(run_result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    agent_view = run_result.get("agent_view") or {}
    output: dict[str, list[dict[str, Any]]] = {}
    runtime_metric_map = run_result.get("runtime_metric_map") or (
        agent_view_module.runtime_metric_map(agent_view) if agent_view else {}
    )
    for fixture in (runtime_metric_map.get("static_map") or {}).get("fixtures") or []:
        if not isinstance(fixture, dict):
            continue
        room_id = str(fixture.get("room_id") or "")
        output.setdefault(room_id, []).append(_public_static_fixture_projection(fixture))
    return output


def _room_by_fixture_id(fixtures_by_room: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for fallback_room_id, fixtures in fixtures_by_room.items():
        for fixture in fixtures:
            fixture_id = str(fixture.get("fixture_id") or "")
            room_id = str(fixture.get("room_id") or fallback_room_id)
            if fixture_id and room_id:
                output[fixture_id] = room_id
    return output


def _public_static_fixture_projection(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": str(fixture.get("fixture_id") or ""),
        "room_id": str(fixture.get("room_id") or ""),
        "category": str(fixture.get("category") or ""),
        "name": str(fixture.get("name") or ""),
        "affordances": [str(item) for item in fixture.get("affordances") or []],
    }


def _private_labels_by_room(
    run_result: dict[str, Any],
    *,
    room_by_fixture_id: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    private_evaluation = _private_evaluation(run_result)
    generated_set = {str(item) for item in private_evaluation.get("generated_mess_set") or []}
    initial_room_by_object_id = _initial_room_by_object_id(
        run_result,
        room_by_fixture_id=room_by_fixture_id,
    )
    rows = private_evaluation.get("object_results") or []
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        object_id = str(row.get("object_id") or "")
        if generated_set and object_id not in generated_set:
            continue
        room_assignment = initial_room_by_object_id.get(object_id)
        if room_assignment is None:
            room_id = _room_id_from_object_id(object_id)
            room_assignment_source = "object_id_suffix" if room_id else ""
        else:
            room_id = room_assignment["room_id"]
            room_assignment_source = room_assignment["source"]
        family = _category_family(row.get("object_category") or object_id)
        if not room_id or not family:
            continue
        labels = output.setdefault(room_id, [])
        labels.append(
            {
                "category": family,
                "category_family": family,
                "object_id": object_id,
                "object_category": str(row.get("object_category") or ""),
                "label_source": "private_evaluation_room_presence",
                "room_assignment_source": room_assignment_source,
            }
        )
    return output


def _initial_room_by_object_id(
    run_result: dict[str, Any],
    *,
    room_by_fixture_id: dict[str, str],
) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in _mess_placement_diagnostics(run_result):
        object_id = str(row.get("object_id") or "")
        receptacle_id = str(row.get("receptacle_id") or "")
        room_id = room_by_fixture_id.get(receptacle_id, "")
        if not object_id or not room_id:
            continue
        output.setdefault(
            object_id,
            {
                "room_id": room_id,
                "source": "mess_placement_fixture_room",
            },
        )
    return output


def _mess_placement_diagnostics(run_result: dict[str, Any]) -> list[dict[str, Any]]:
    value = run_result.get("mess_placement_diagnostics") or []
    return [dict(item) for item in value if isinstance(item, dict)]


def _private_evaluation(run_result: dict[str, Any]) -> dict[str, Any]:
    value = run_result.get("private_evaluation")
    return dict(value) if isinstance(value, dict) else {}


def _room_id_from_object_id(object_id: str) -> str:
    parts = object_id.rsplit("_", maxsplit=1)
    if len(parts) != 2:
        return ""
    suffix = parts[-1]
    return f"room_{suffix}" if suffix.isdigit() else ""


def _category_family(value: Any) -> str:
    normalized = _NORMALIZE_RE.sub("", str(value or "").lower())
    if not normalized:
        return ""
    exact = DEFAULT_CATEGORY_FAMILY_MAP.get(normalized)
    if exact:
        return exact
    for key, family in sorted(
        DEFAULT_CATEGORY_FAMILY_MAP.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if normalized.startswith(key) or key in normalized:
            return family
    return ""


def _raw_fpv_image_path(raw_observation: dict[str, Any], run_dir: Path) -> Path | None:
    image_artifacts = raw_observation.get("image_artifacts") or {}
    value = image_artifacts.get("fpv") or raw_observation.get("fpv_image")
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else run_dir / path


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _default_corpus_name(run_result: dict[str, Any], run_result_path: Path) -> str:
    scenario_id = str(run_result.get("scenario_id") or "").strip()
    if scenario_id:
        return f"{scenario_id}-raw-fpv"
    return f"{run_result_path.parent.name}-raw-fpv"


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return cleaned or "observation"


if __name__ == "__main__":
    raise SystemExit(main())
