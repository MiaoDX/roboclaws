from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_value
from roboclaws.household.planner_feasibility_contracts import (
    GRASP_CACHE_AVAILABILITY_PREFLIGHT_SCHEMA,
)


def grasp_cache_availability_preflight(
    decision: dict[str, Any],
    *,
    assets_dir: Path | str | None = None,
    assets_dir_source: str | None = None,
) -> dict[str, Any]:
    """Check the exact rigid grasp-cache files used by MolmoSpaces' loader."""
    missing_assets = list(
        dict.fromkeys(
            str(value or "")
            for value in decision.get("missing_grasp_asset_uids") or []
            if str(value or "")
        )
    )
    resolved_assets_dir, resolved_assets_dir_source = _resolve_assets_dir(
        assets_dir,
        source=assets_dir_source,
    )
    if not missing_assets:
        return {
            "schema": GRASP_CACHE_AVAILABILITY_PREFLIGHT_SCHEMA,
            "status": "not_applicable",
            "assets_dir": str(resolved_assets_dir),
            "assets_dir_resolved": _resolved_path(resolved_assets_dir),
            "assets_dir_source": resolved_assets_dir_source,
            "assets_dir_exists": resolved_assets_dir.exists(),
            "missing_grasp_asset_uids": [],
            "asset_count": 0,
            "ready_asset_count": 0,
            "missing_cache_asset_count": 0,
            "cache_ready_asset_uids": [],
            "cache_missing_asset_uids": [],
            "loader_sources": ["droid", "droid_objaverse", "rum"],
            "assets": [],
            "upstream_loader": "molmo_spaces.utils.grasp_sample.load_grasps_for_object",
            "evidence_note": (
                "No missing grasp-cache asset IDs were present in the mitigation decision."
            ),
        }

    assets = [
        _grasp_cache_asset_preflight(asset_uid, assets_dir=resolved_assets_dir)
        for asset_uid in missing_assets
    ]
    ready_assets = [
        str(item.get("asset_uid") or "")
        for item in assets
        if str(item.get("status") or "") == "ready"
    ]
    missing_cache_assets = [
        str(item.get("asset_uid") or "")
        for item in assets
        if str(item.get("status") or "") == "missing_cache"
    ]
    status = "ready" if len(ready_assets) == len(assets) else "missing_cache"
    recommendation = (
        "cached_rigid_grasps_present_for_retry"
        if status == "ready"
        else "generate_or_install_rigid_grasp_cache_before_retry"
    )
    return {
        "schema": GRASP_CACHE_AVAILABILITY_PREFLIGHT_SCHEMA,
        "status": status,
        "assets_dir": str(resolved_assets_dir),
        "assets_dir_resolved": _resolved_path(resolved_assets_dir),
        "assets_dir_source": resolved_assets_dir_source,
        "assets_dir_exists": resolved_assets_dir.exists(),
        "missing_grasp_asset_uids": missing_assets,
        "asset_count": len(assets),
        "ready_asset_count": len(ready_assets),
        "missing_cache_asset_count": len(missing_cache_assets),
        "cache_ready_asset_uids": ready_assets,
        "cache_missing_asset_uids": missing_cache_assets,
        "loader_sources": ["droid", "droid_objaverse", "rum"],
        "assets": assets,
        "mitigation_recommendation": recommendation,
        "upstream_loader": "molmo_spaces.utils.grasp_sample.load_grasps_for_object",
        "evidence_note": (
            "Preflights the rigid-object grasp files used by MolmoSpaces "
            "load_grasps_for_object. The droid joint file is reported only as a "
            "folder probe and does not make the rigid loader ready."
        ),
    }


def _resolve_assets_dir(
    assets_dir: Path | str | None,
    *,
    source: str | None = None,
) -> tuple[Path, str]:
    if assets_dir is not None:
        return Path(assets_dir).expanduser(), source or "argument"
    env_value = os.environ.get("MLSPACES_ASSETS_DIR")
    if env_value:
        return Path(env_value).expanduser(), "MLSPACES_ASSETS_DIR"
    return Path("~/.cache/molmo-spaces-resources").expanduser(), "default"


def _grasp_cache_asset_preflight(asset_uid: str, *, assets_dir: Path) -> dict[str, Any]:
    candidate_files = _rigid_grasp_loader_files(asset_uid, assets_dir=assets_dir)
    folder_probe_files = _folder_probe_grasp_files(asset_uid, assets_dir=assets_dir)
    ready = any(bool(item.get("valid")) for item in candidate_files)
    present_candidate_count = sum(1 for item in candidate_files if bool(item.get("exists")))
    object_asset_files = _object_asset_files(asset_uid, assets_dir=assets_dir)
    return {
        "asset_uid": asset_uid,
        "status": "ready" if ready else "missing_cache",
        "loader_file_status": _loader_file_status(
            ready=ready, present_candidate_count=present_candidate_count
        ),
        "object_asset_status": "present" if object_asset_files else "missing",
        "candidate_grasp_files": candidate_files,
        "folder_probe_files": folder_probe_files,
        "object_asset_files": object_asset_files,
    }


def _rigid_grasp_loader_files(asset_uid: str, *, assets_dir: Path) -> list[dict[str, Any]]:
    return [
        _file_probe(
            assets_dir / "grasps" / "droid" / asset_uid / f"{asset_uid}_grasps_filtered.npz",
            assets_dir=assets_dir,
            asset_uid=asset_uid,
            source="droid",
            gripper="droid",
            loader_role="rigid_object_loader",
        ),
        _file_probe(
            assets_dir
            / "grasps"
            / "droid_objaverse"
            / asset_uid
            / f"{asset_uid}_grasps_filtered.npz",
            assets_dir=assets_dir,
            asset_uid=asset_uid,
            source="droid_objaverse",
            gripper="droid",
            loader_role="rigid_object_loader",
        ),
        _file_probe(
            assets_dir / "grasps" / "rum" / asset_uid / f"{asset_uid}_grasps_filtered.json",
            assets_dir=assets_dir,
            asset_uid=asset_uid,
            source="rum",
            gripper="rum",
            loader_role="rigid_object_loader",
        ),
    ]


def _folder_probe_grasp_files(asset_uid: str, *, assets_dir: Path) -> list[dict[str, Any]]:
    return [
        _file_probe(
            assets_dir / "grasps" / "droid" / asset_uid / f"{asset_uid}_joint_grasps_filtered.npz",
            assets_dir=assets_dir,
            asset_uid=asset_uid,
            source="droid",
            gripper="droid",
            loader_role="has_grasp_folder_only",
        )
    ]


def _object_asset_files(
    asset_uid: str, *, assets_dir: Path, limit: int = 8
) -> list[dict[str, Any]]:
    if not assets_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    roots = [assets_dir / "objects" / "thor"]
    for root in roots:
        if not root.exists():
            continue
        for pattern, kind in ((f"{asset_uid}.xml", "xml"), (f"{asset_uid}.obj", "obj")):
            for path in root.rglob(pattern):
                results.append(
                    {
                        "kind": kind,
                        "path": str(path),
                        "resolved_path": _resolved_path(path),
                        "relative_path": _relative_to_assets(path, assets_dir),
                        "exists": path.exists(),
                        "size_bytes": _file_size(path),
                    }
                )
                if len(results) >= limit:
                    return results
    return results


def _file_probe(
    path: Path,
    *,
    assets_dir: Path,
    asset_uid: str,
    source: str,
    gripper: str,
    loader_role: str,
) -> dict[str, Any]:
    validation = validate_grasp_cache_file(path) if loader_role == "rigid_object_loader" else {}
    return {
        "asset_uid": asset_uid,
        "source": source,
        "gripper": gripper,
        "loader_role": loader_role,
        "path": str(path),
        "resolved_path": _resolved_path(path),
        "parent_resolved_path": _resolved_path(path.parent),
        "parent_exists": path.parent.exists(),
        "relative_path": _relative_to_assets(path, assets_dir),
        "exists": path.exists(),
        "size_bytes": _file_size(path),
        **validation,
    }


def _loader_file_status(*, ready: bool, present_candidate_count: int) -> str:
    if ready:
        return "valid"
    if present_candidate_count:
        return "present_but_invalid"
    return "missing"


def validate_grasp_cache_file(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return {
            "validation_status": "missing",
            "valid": False,
            "transform_count": 0,
        }
    try:
        if path.suffix == ".npz":
            import numpy as np

            with np.load(path) as data:
                transforms = data.get("transforms", [])
                transform_count = len(transforms)
        elif path.suffix == ".json":
            payload = read_json_value(path, label="planner grasp cache")
            transforms = payload.get("transforms", []) if isinstance(payload, dict) else []
            transform_count = len(transforms)
        else:
            return {
                "validation_status": "unsupported",
                "valid": False,
                "transform_count": 0,
            }
    except Exception as exc:
        return {
            "validation_status": "error",
            "valid": False,
            "transform_count": 0,
            "validation_error_type": type(exc).__name__,
            "validation_error": str(exc),
        }
    return {
        "validation_status": "valid" if transform_count > 0 else "empty",
        "valid": transform_count > 0,
        "transform_count": transform_count,
    }


def _relative_to_assets(path: Path, assets_dir: Path) -> str:
    try:
        return str(path.relative_to(assets_dir))
    except ValueError:
        return str(path)


def _resolved_path(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except OSError:
        return str(path)


def _file_size(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0
