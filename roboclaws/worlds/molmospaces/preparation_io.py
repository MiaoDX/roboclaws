"""Source-preparation helpers for the MolmoSpaces scene sampler."""

from __future__ import annotations

import importlib
import io
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

FamilySplitFn = Callable[[str], tuple[str, str]]
CandidateListFn = Callable[[dict[str, Any]], list[dict[str, Any]]]


def molmospaces_module_status() -> tuple[bool, str, str]:
    stdout = io.StringIO()
    try:
        with redirect_stdout(stdout):
            importlib.import_module("molmo_spaces.molmo_spaces_constants")
    except ModuleNotFoundError as exc:
        return False, f"module_not_importable:{exc.name}", stdout.getvalue()
    except Exception as exc:  # pragma: no cover - dependency import failures vary by host.
        return False, f"module_import_failed:{type(exc).__name__}:{exc}", stdout.getvalue()
    return True, "module_importable", stdout.getvalue()


def molmospaces_scene_root_status(
    *,
    module_available: bool,
) -> tuple[Path | None, str, str]:
    if not module_available:
        return None, "molmo_spaces_module_unavailable", ""
    stdout = io.StringIO()
    try:
        with redirect_stdout(stdout):
            constants = importlib.import_module("molmo_spaces.molmo_spaces_constants")
            root = Path(constants.get_scenes_root())
    except Exception as exc:  # pragma: no cover - dependency import failures vary by host.
        return None, f"scene_root_unavailable:{type(exc).__name__}:{exc}", stdout.getvalue()
    if not root.is_dir():
        return root, "scene_root_missing", stdout.getvalue()
    return root, "scene_root_available", stdout.getvalue()


def source_availability_blocked_reason(
    *,
    module_available: bool,
    module_reason: str,
    root: Path | None,
    root_reason: str,
    source: str,
    source_exists: bool,
    missing_files: list[int],
    invalid_candidate_indices: list[int],
    scene_index_map: dict[str, Any],
) -> str:
    if not module_available:
        return (
            "MolmoSpaces Python module is not importable in this environment "
            f"({module_reason}); run uv sync --extra dev or install the declared MolmoSpaces "
            "runtime before source admission."
        )
    if root is None or not root.is_dir():
        return (
            "MolmoSpaces scene root is unavailable "
            f"({root_reason}); configure MLSPACES_ASSETS_DIR or install scene assets before "
            "source admission."
        )
    if not source_exists:
        return (
            f"MolmoSpaces scene source directory is missing for {source}: {root / source}; "
            "install that source before scanner admission."
        )
    if scene_index_map.get("status") != "available":
        return (
            f"MolmoSpaces get_scenes index map is unavailable for {source} "
            f"({scene_index_map.get('reason')}); source preparation must resolve the index "
            "map before sampler admission."
        )
    if invalid_candidate_indices:
        return (
            f"MolmoSpaces scene source {source} has no get_scenes entries for candidate "
            f"indices {invalid_candidate_indices}; choose valid source-specific indices before "
            "scanner admission."
        )
    if missing_files:
        return (
            f"MolmoSpaces scene source {source} has missing get_scenes file paths for indices "
            f"{missing_files}; run source preparation before sampler admission."
        )
    return ""


def source_availability_summary(
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_count": len(sources),
        "available_source_count": sum(
            1 for source in sources.values() if source.get("status") == "available"
        ),
        "blocked_source_count": sum(
            1 for source in sources.values() if source.get("status") != "available"
        ),
        "scene_root_available_source_count": sum(
            1 for source in sources.values() if source.get("scene_root_available")
        ),
        "source_dir_available_count": sum(
            1 for source in sources.values() if source.get("source_dir_available")
        ),
        "scene_index_map_available_count": sum(
            1 for source in sources.values() if source.get("scene_index_map_status") == "available"
        ),
        "missing_candidate_count": sum(
            len(source.get("missing_candidate_indices") or []) for source in sources.values()
        ),
        "invalid_candidate_count": sum(
            len(source.get("invalid_candidate_indices") or []) for source in sources.values()
        ),
    }


def molmospaces_get_scenes_args(scene_source: str) -> tuple[str, str]:
    if scene_source == "ithor":
        return "ithor", "train"
    family, split = _family_split(scene_source)
    if split == "not_applicable":
        split = "train"
    return family, split


def molmospaces_scene_index_map(
    *,
    source: str,
    dataset_name: str,
    split: str,
    candidate_indices: tuple[int, ...],
    module_available: bool,
) -> dict[str, Any]:
    if not module_available:
        return {
            "source": source,
            "dataset_name": dataset_name,
            "split": split,
            "status": "blocked",
            "reason": "molmo_spaces_module_unavailable",
            "version": "",
            "stdout": "",
            "candidate_scene_refs": [],
        }
    stdout = io.StringIO()
    try:
        with redirect_stdout(stdout):
            constants = importlib.import_module("molmo_spaces.molmo_spaces_constants")
            mapping, version = constants.get_scenes(dataset_name, split, return_version=True)
    except Exception as exc:  # pragma: no cover - dependency failures vary by host.
        return {
            "source": source,
            "dataset_name": dataset_name,
            "split": split,
            "status": "blocked",
            "reason": f"get_scenes_failed:{type(exc).__name__}:{exc}",
            "version": "",
            "stdout": stdout.getvalue(),
            "candidate_scene_refs": [],
        }
    split_mapping = mapping.get(split) if isinstance(mapping, dict) else None
    if not isinstance(split_mapping, dict):
        return {
            "source": source,
            "dataset_name": dataset_name,
            "split": split,
            "status": "blocked",
            "reason": "split_map_missing",
            "version": str(version or ""),
            "stdout": stdout.getvalue(),
            "candidate_scene_refs": [],
        }
    candidate_scene_refs = [
        _candidate_scene_ref(
            source=source,
            scene_index=index,
            raw_ref=split_mapping.get(index),
        )
        for index in candidate_indices
    ]
    return {
        "source": source,
        "dataset_name": dataset_name,
        "split": split,
        "status": "available",
        "reason": "",
        "version": str(version or ""),
        "stdout": stdout.getvalue(),
        "candidate_scene_refs": candidate_scene_refs,
    }


def candidate_scene_ref_from_availability(candidate_file: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": candidate_file.get("scene_source", ""),
        "scene_index": candidate_file.get("scene_index"),
        "status": candidate_file.get("status", ""),
        "source": candidate_file.get("source", ""),
        "raw_ref_type": candidate_file.get("raw_ref_type", ""),
        "paths": candidate_file.get("paths", []),
        "primary_path": candidate_file.get("path", ""),
        "all_paths_exist": bool(candidate_file.get("exists")),
        "missing_paths": candidate_file.get("missing_paths", []),
    }


def _family_split(scene_source: str) -> tuple[str, str]:
    if scene_source == "ithor":
        return "ithor", "not_applicable"
    for split in ("-train", "-val", "-test"):
        if scene_source.endswith(split):
            return scene_source[: -len(split)], split.removeprefix("-")
    return scene_source, "not_applicable"


def _candidate_scene_ref(
    *,
    source: str,
    scene_index: int,
    raw_ref: Any,
) -> dict[str, Any]:
    paths = _scene_ref_paths(raw_ref)
    return {
        "scene_source": source,
        "scene_index": scene_index,
        "status": "available" if paths else "missing_from_index_map",
        "raw_ref_type": type(raw_ref).__name__,
        "paths": paths,
        "primary_path": _primary_scene_ref_path(paths),
        "all_paths_exist": bool(paths) and all(path["exists"] for path in paths),
        "missing_paths": [
            path["path"] for path in paths if path.get("path") and not path["exists"]
        ],
    }


def _scene_ref_paths(raw_ref: Any) -> list[dict[str, Any]]:
    if raw_ref is None:
        return []
    if isinstance(raw_ref, str | Path):
        path = Path(raw_ref)
        return [{"role": "base", "path": str(raw_ref), "exists": path.is_file()}]
    if isinstance(raw_ref, dict):
        paths = []
        for role, raw_path in sorted(raw_ref.items()):
            if raw_path is None:
                continue
            path = Path(str(raw_path))
            paths.append({"role": str(role), "path": str(raw_path), "exists": path.is_file()})
        return paths
    return []


def _primary_scene_ref_path(paths: list[dict[str, Any]]) -> str:
    for role in ("base", "physics", "ceiling"):
        for path in paths:
            if path.get("role") == role:
                return str(path.get("path") or "")
    if paths:
        return str(paths[0].get("path") or "")
    return ""
