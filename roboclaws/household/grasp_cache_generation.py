from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.planner_grasp_cache import (
    grasp_cache_availability_preflight,
    validate_grasp_cache_file,
)

GRASP_CACHE_GENERATION_SCHEMA = "molmospaces_grasp_cache_generation_v1"


def load_generation_preflight_from_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json_object(path, label="grasp cache generation proof bundle manifest")
    preflight = manifest.get("grasp_cache_generation_preflight")
    if not isinstance(preflight, dict):
        raise ValueError(f"No grasp_cache_generation_preflight found in {path}")
    return preflight


def run_grasp_cache_generation(
    *,
    generation_preflight: dict[str, Any],
    output_dir: Path,
    molmospaces_python: Path | None = None,
    max_successful_grasps: int = 1000,
    num_workers: int = 1,
    approach_steps: int | None = None,
    shake_steps: int | None = None,
    timeout_s: float = 3600.0,
    install: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    if generation_preflight.get("status") != "ready":
        return _blocked_result(
            generation_preflight=generation_preflight,
            output_dir=output_dir,
            blockers=[
                {
                    "code": "generation_preflight_not_ready",
                    "message": (
                        "Grasp cache generation preflight must be ready before running generation."
                    ),
                }
            ],
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    objects_list_path = (output_dir / "grasp_generation" / "rigid_objects_list.json").resolve()
    objects_list_path.parent.mkdir(parents=True, exist_ok=True)
    objects_list = objects_list_from_generation_preflight(generation_preflight)
    objects_list_path.write_text(
        json.dumps(objects_list, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    python = Path(molmospaces_python or generation_preflight.get("molmospaces_python") or "python")
    working_dir = Path(str(generation_preflight.get("working_dir") or ""))
    command = [
        str(python),
        str(working_dir / "run_rigid.py"),
        "--objects_list",
        str(objects_list_path),
        "--max_successful_grasps",
        str(max_successful_grasps),
        "--num_workers",
        str(num_workers),
    ]
    if approach_steps is not None:
        command.extend(["--approach_steps", str(approach_steps)])
    if shake_steps is not None:
        command.extend(["--shake_steps", str(shake_steps)])
    assets_symlink = ensure_molmospaces_assets_symlink(
        generation_preflight,
        working_dir=working_dir,
        dry_run=dry_run,
    )
    command_result = run_generation_command(
        command,
        cwd=working_dir,
        molmospaces_python=python,
        timeout_s=timeout_s,
        dry_run=dry_run,
    )
    assets = [
        generation_asset_result(asset, install=install and not dry_run)
        for asset in generation_preflight.get("assets") or []
        if isinstance(asset, dict)
    ]
    blockers = _generation_blockers(
        assets_symlink=assets_symlink,
        command_result=command_result,
        assets=assets,
        install=install,
    )

    availability_after_install = {}
    if install and not dry_run:
        availability_after_install = generation_availability_after_install(generation_preflight)
        if availability_after_install.get("status") != "ready":
            blockers.append(
                {
                    "code": "availability_preflight_not_ready_after_install",
                    "message": "Installed grasp cache did not pass availability preflight.",
                }
            )

    status = "dry_run" if dry_run else ("blocked" if blockers else "ready")
    return {
        "schema": GRASP_CACHE_GENERATION_SCHEMA,
        "status": status,
        "ready": status == "ready",
        "output_dir": str(output_dir),
        "objects_list_path": str(objects_list_path),
        "objects_list": objects_list,
        "command": command,
        "assets_symlink": assets_symlink,
        "command_result": command_result,
        "assets": assets,
        "asset_count": len(assets),
        "availability_after_install": availability_after_install,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "evidence_note": (
            "Runs upstream MolmoSpaces rigid grasp generation from a ready "
            "generation preflight and installs non-empty generated NPZ files into "
            "the loader cache target."
        ),
    }


def _blocked_result(
    *,
    generation_preflight: dict[str, Any],
    output_dir: Path,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": GRASP_CACHE_GENERATION_SCHEMA,
        "status": "blocked",
        "ready": False,
        "output_dir": str(output_dir),
        "objects_list_path": "",
        "objects_list": [],
        "command": [],
        "command_result": {},
        "assets": generation_preflight.get("assets") or [],
        "asset_count": len(generation_preflight.get("assets") or []),
        "availability_after_install": {},
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def _generation_blockers(
    *,
    assets_symlink: dict[str, Any],
    command_result: dict[str, Any],
    assets: list[dict[str, Any]],
    install: bool,
) -> list[dict[str, Any]]:
    blockers = []
    if assets_symlink.get("status") == "blocked":
        blockers.append(
            {
                "code": "molmospaces_assets_symlink_blocked",
                "message": assets_symlink.get("message") or "assets symlink setup failed",
            }
        )
    if command_result.get("status") == "blocked":
        blockers.append(
            {
                "code": "run_rigid_failed",
                "message": command_result.get("stderr")
                or command_result.get("stdout")
                or "run_rigid.py failed",
            }
        )
    for asset in assets:
        asset_uid = asset.get("asset_uid")
        if not asset.get("generated_valid"):
            blockers.append(
                {
                    "code": "generated_grasp_cache_invalid",
                    "message": f"Generated grasp cache invalid for {asset_uid}",
                    "asset_uid": asset_uid,
                }
            )
        elif install and not asset.get("installed_valid"):
            blockers.append(
                {
                    "code": "installed_grasp_cache_invalid",
                    "message": f"Installed grasp cache invalid for {asset_uid}",
                    "asset_uid": asset_uid,
                }
            )
    return blockers


def objects_list_from_generation_preflight(
    generation_preflight: dict[str, Any],
) -> list[dict[str, str]]:
    objects: list[dict[str, str]] = []
    for asset in generation_preflight.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        entry = asset.get("objects_list_entry") or {}
        name = str(entry.get("name") or asset.get("asset_uid") or "")
        xml = str(generation_xml_path(str(entry.get("xml") or asset.get("object_xml") or "")))
        if name and xml:
            objects.append({"name": name, "xml": xml})
    if not objects:
        raise ValueError("Generation preflight did not contain any object list entries.")
    return objects


def generation_xml_path(xml: str) -> Path:
    path = Path(xml)
    mesh_xml = path.with_name(f"{path.stem}_mesh{path.suffix}")
    if mesh_xml.is_file():
        return mesh_xml
    return path


def ensure_molmospaces_assets_symlink(
    generation_preflight: dict[str, Any],
    *,
    working_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    assets_dir = Path(str(generation_preflight.get("assets_dir") or ""))
    checkout_root = working_dir.parents[2] if len(working_dir.parents) > 2 else None
    link_path = checkout_root / "assets" if checkout_root is not None else Path()
    result = {
        "path": str(link_path),
        "target": str(assets_dir),
        "status": "not_run" if dry_run else "ready",
        "created": False,
    }
    if dry_run:
        return result
    if not assets_dir.is_dir():
        return {
            **result,
            "status": "blocked",
            "message": f"MolmoSpaces assets dir is missing: {assets_dir}",
        }
    if link_path.exists() or link_path.is_symlink():
        try:
            if link_path.resolve() == assets_dir.resolve():
                return result
        except OSError:
            pass
        return {
            **result,
            "status": "blocked",
            "message": (
                "MolmoSpaces assets path already exists and does not target "
                f"{assets_dir}: {link_path}"
            ),
        }
    link_path.symlink_to(assets_dir, target_is_directory=True)
    return {**result, "created": True}


def run_generation_command(
    command: list[str],
    *,
    cwd: Path,
    molmospaces_python: Path,
    timeout_s: float,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"status": "not_run", "returncode": "", "stdout": "", "stderr": ""}
    env = os.environ.copy()
    env["PATH"] = str(molmospaces_python.parent) + os.pathsep + env.get("PATH", "")
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "blocked",
            "returncode": "",
            "stdout": str(exc.stdout or "").strip(),
            "stderr": str(exc.stderr or "").strip(),
            "code": "generation_timeout",
            "message": f"Grasp generation exceeded {timeout_s:.1f}s.",
        }
    except OSError as exc:
        return {
            "status": "blocked",
            "returncode": "",
            "stdout": "",
            "stderr": str(exc),
            "code": "generation_command_os_error",
            "message": str(exc),
        }
    return {
        "status": "ready" if completed.returncode == 0 else "blocked",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def generation_asset_result(asset: dict[str, Any], *, install: bool) -> dict[str, Any]:
    """Validate a generated cache asset and optionally install it into the loader path."""
    generated_path = Path(str(asset.get("generated_npz_path") or ""))
    target_path = Path(
        str(asset.get("cache_target_resolved_path") or asset.get("cache_target_path") or "")
    )
    generated_validation = validate_grasp_cache_file(generated_path)
    installed_validation = validate_grasp_cache_file(target_path)
    result = {
        "asset_uid": str(asset.get("asset_uid") or ""),
        "generated_npz_path": str(generated_path),
        "cache_target_path": str(target_path),
        "generated_validation": generated_validation,
        "generated_valid": bool(generated_validation.get("valid")),
        "installed_validation_before": installed_validation,
        "installed_validation": installed_validation,
        "installed_valid": bool(installed_validation.get("valid")),
        "installed": False,
    }
    if install and result["generated_valid"] and str(target_path):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()
        shutil.copy2(generated_path, target_path)
        after = validate_grasp_cache_file(target_path)
        result.update(
            {
                "installed": True,
                "installed_validation": after,
                "installed_valid": bool(after.get("valid")),
            }
        )
    return result


def generation_availability_after_install(generation_preflight: dict[str, Any]) -> dict[str, Any]:
    """Re-run grasp-cache availability after generated cache files are installed."""
    return _availability_after_install(generation_preflight)


def _availability_after_install(generation_preflight: dict[str, Any]) -> dict[str, Any]:
    asset_uids = [
        str(asset.get("asset_uid") or "")
        for asset in generation_preflight.get("assets") or []
        if isinstance(asset, dict) and str(asset.get("asset_uid") or "")
    ]
    decision = {"missing_grasp_asset_uids": asset_uids}
    return grasp_cache_availability_preflight(
        decision,
        assets_dir=generation_preflight.get("assets_dir"),
        assets_dir_source="grasp_cache_generation_install",
    )
