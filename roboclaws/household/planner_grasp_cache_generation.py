from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import parse_json_object_text
from roboclaws.household.planner_feasibility_contracts import (
    GRASP_CACHE_GENERATION_PREFLIGHT_SCHEMA,
)
from roboclaws.household.planner_grasp_cache import (
    _resolved_path,
)


def grasp_cache_generation_preflight(
    availability_preflight: dict[str, Any],
    *,
    output_dir: Path | str | None = None,
    molmospaces_python: Path | str | None = None,
    molmospaces_root: Path | str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Preflight the upstream rigid grasp-generation path for missing cache assets."""
    missing_assets = [
        asset
        for asset in availability_preflight.get("assets") or []
        if isinstance(asset, dict) and str(asset.get("status") or "") == "missing_cache"
    ]
    if not missing_assets:
        return {
            "schema": GRASP_CACHE_GENERATION_PREFLIGHT_SCHEMA,
            "status": "not_applicable",
            "asset_count": 0,
            "ready": False,
            "assets": [],
            "checks": [],
            "blockers": [],
            "evidence_note": "No missing rigid grasp-cache assets require generation.",
        }

    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    python_path = Path(molmospaces_python).expanduser() if molmospaces_python else None
    runtime = _molmospaces_runtime_probe(python_path, timeout_s=timeout_s)
    checks.extend(runtime["checks"])
    blockers.extend(runtime["blockers"])

    root_path = (
        Path(molmospaces_root).expanduser()
        if molmospaces_root is not None
        else _optional_path(runtime.get("molmospaces_root"))
    )
    assets_dir = _optional_path(availability_preflight.get("assets_dir")) or _optional_path(
        runtime.get("assets_dir")
    )
    output_root = Path(output_dir).expanduser() if output_dir else Path("output")
    objects_list_path = output_root / "grasp_generation" / "rigid_objects_list.json"

    if python_path is not None and runtime.get("python_ready"):
        for check in _rigid_generation_python_checks(python_path, timeout_s=timeout_s):
            checks.append(check)
            if check.get("status") == "blocked":
                blockers.append(_blocker_from_check(check))

    file_checks = _rigid_generation_file_checks(
        molmospaces_root=root_path,
        assets_dir=assets_dir,
    )
    checks.extend(file_checks)
    for check in file_checks:
        if check.get("status") == "blocked":
            blockers.append(_blocker_from_check(check))

    assets = [
        _grasp_cache_generation_asset_preflight(
            asset,
            molmospaces_root=root_path,
            objects_list_path=objects_list_path,
        )
        for asset in missing_assets
    ]
    for asset in assets:
        if not asset.get("object_xml_exists"):
            blockers.append(
                {
                    "code": "object_xml_missing",
                    "message": f"Object XML is missing for {asset.get('asset_uid')}",
                    "asset_uid": asset.get("asset_uid"),
                }
            )
        if not asset.get("cache_target_path"):
            blockers.append(
                {
                    "code": "cache_target_missing",
                    "message": f"No droid rigid cache target found for {asset.get('asset_uid')}",
                    "asset_uid": asset.get("asset_uid"),
                }
            )

    status = "ready" if not blockers else "blocked"
    command = _rigid_generation_command(
        molmospaces_python=python_path,
        molmospaces_root=root_path,
        objects_list_path=objects_list_path,
    )
    return {
        "schema": GRASP_CACHE_GENERATION_PREFLIGHT_SCHEMA,
        "status": status,
        "ready": status == "ready",
        "asset_count": len(assets),
        "assets": assets,
        "molmospaces_python": str(python_path or ""),
        "molmospaces_root": str(root_path or ""),
        "assets_dir": str(assets_dir or ""),
        "objects_list_path": str(objects_list_path),
        "working_dir": str(_grasp_generation_working_dir(root_path) or ""),
        "command": command,
        "checks": checks,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "mitigation_recommendation": (
            "run_rigid_grasp_generation_then_install_filtered_npz"
            if status == "ready"
            else "install_grasp_generation_prerequisites_before_cache_generation"
        ),
        "evidence_note": (
            "Preflights the upstream MolmoSpaces rigid grasp-generation pipeline. "
            "It does not create or install grasps; generated NPZ output must still "
            "be copied to the loader cache target and pass availability validation."
        ),
    }


def _molmospaces_runtime_probe(
    molmospaces_python: Path | None,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    if molmospaces_python is None:
        blocker = {
            "code": "molmospaces_python_not_configured",
            "message": "No MolmoSpaces Python executable was configured for grasp generation.",
        }
        return {
            "python_ready": False,
            "molmospaces_root": "",
            "assets_dir": "",
            "checks": [{"name": "molmospaces_python", "status": "blocked", **blocker}],
            "blockers": [blocker],
        }
    if not molmospaces_python.is_file():
        blocker = {
            "code": "molmospaces_python_missing",
            "message": f"MolmoSpaces Python executable is missing: {molmospaces_python}",
        }
        return {
            "python_ready": False,
            "molmospaces_root": "",
            "assets_dir": "",
            "checks": [{"name": "molmospaces_python", "status": "blocked", **blocker}],
            "blockers": [blocker],
        }
    command = [
        str(molmospaces_python),
        "-c",
        (
            "import json; "
            "from molmo_spaces.molmo_spaces_constants import "
            "ABS_PATH_OF_TOP_LEVEL_MOLMO_SPACES_DIR, ASSETS_DIR; "
            "print(json.dumps({'molmospaces_root': str(ABS_PATH_OF_TOP_LEVEL_MOLMO_SPACES_DIR), "
            "'assets_dir': str(ASSETS_DIR)}))"
        ),
    ]
    completed = _run_preflight_command(command, timeout_s=timeout_s)
    check = {
        "name": "molmo_spaces_runtime",
        "command": command,
        **completed,
    }
    if completed["status"] != "ready":
        blocker = _blocker_from_check(
            {
                **check,
                "code": "molmo_spaces_runtime_probe_failed",
                "message": completed.get("stderr")
                or completed.get("stdout")
                or "MolmoSpaces runtime probe failed.",
            }
        )
        check.update({"status": "blocked", **blocker})
        return {
            "python_ready": False,
            "molmospaces_root": "",
            "assets_dir": "",
            "checks": [check],
            "blockers": [blocker],
        }
    try:
        payload = parse_json_object_text(
            str(completed.get("stdout") or ""),
            label="MolmoSpaces runtime probe stdout",
        )
    except ValueError as exc:
        blocker = _blocker_from_check(
            {
                **check,
                "status": "blocked",
                "code": "molmo_spaces_runtime_probe_invalid_stdout",
                "message": str(exc),
            }
        )
        check.update({"status": "blocked", **blocker})
        return {
            "python_ready": False,
            "molmospaces_root": "",
            "assets_dir": "",
            "checks": [check],
            "blockers": [blocker],
        }
    root = str(payload.get("molmospaces_root") or "")
    assets_dir = str(payload.get("assets_dir") or "")
    if not root or not assets_dir:
        blocker = _blocker_from_check(
            {
                **check,
                "status": "blocked",
                "code": "molmo_spaces_runtime_probe_missing_paths",
                "message": (
                    "MolmoSpaces runtime probe stdout must include molmospaces_root and assets_dir."
                ),
            }
        )
        check.update({"status": "blocked", **blocker})
        return {
            "python_ready": False,
            "molmospaces_root": "",
            "assets_dir": "",
            "checks": [check],
            "blockers": [blocker],
        }
    check.update({"molmospaces_root": root, "assets_dir": assets_dir})
    return {
        "python_ready": True,
        "molmospaces_root": root,
        "assets_dir": assets_dir,
        "checks": [check],
        "blockers": [],
    }


def _rigid_generation_python_checks(
    molmospaces_python: Path,
    *,
    timeout_s: float,
) -> list[dict[str, Any]]:
    checks = [
        _python_import_check(
            molmospaces_python,
            name="python_module_mujoco",
            import_name="mujoco",
            timeout_s=timeout_s,
        ),
        _python_import_check(
            molmospaces_python,
            name="python_module_trimesh",
            import_name="trimesh",
            timeout_s=timeout_s,
        ),
        _python_import_check(
            molmospaces_python,
            name="python_module_sklearn",
            import_name="sklearn",
            timeout_s=timeout_s,
        ),
    ]
    collision_command = [
        str(molmospaces_python),
        "-c",
        "import trimesh; trimesh.collision.CollisionManager(); print('python-fcl ok')",
    ]
    completed = _run_preflight_command(collision_command, timeout_s=timeout_s)
    check = {
        "name": "python_fcl_runtime",
        "command": collision_command,
        **completed,
    }
    if check["status"] == "blocked":
        check.update(
            {
                "code": "python_fcl_missing",
                "message": check.get("stderr") or check.get("stdout") or "python-fcl unavailable",
            }
        )
    checks.append(check)
    return checks


def _python_import_check(
    molmospaces_python: Path,
    *,
    name: str,
    import_name: str,
    timeout_s: float,
) -> dict[str, Any]:
    command = [str(molmospaces_python), "-c", f"import {import_name}; print('{import_name} ok')"]
    completed = _run_preflight_command(command, timeout_s=timeout_s)
    check = {"name": name, "command": command, **completed}
    if check["status"] == "blocked":
        check.update(
            {
                "code": f"{import_name.replace('.', '_')}_missing",
                "message": check.get("stderr") or check.get("stdout") or f"{import_name} missing",
            }
        )
    return check


def _rigid_generation_file_checks(
    *,
    molmospaces_root: Path | None,
    assets_dir: Path | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if molmospaces_root is None:
        checks.append(
            {
                "name": "molmospaces_root",
                "status": "blocked",
                "code": "molmospaces_root_unknown",
                "message": "MolmoSpaces repository root could not be resolved.",
            }
        )
        return checks
    checks.extend(
        [
            _path_check(
                "run_rigid_script",
                molmospaces_root / "molmo_spaces" / "grasp_generation" / "run_rigid.py",
                must_be_executable=False,
            ),
            _path_check(
                "combine_meshes_script",
                molmospaces_root
                / "molmo_spaces"
                / "grasp_generation"
                / "pipeline"
                / "combine_meshes.py",
                must_be_executable=False,
            ),
            _path_check(
                "generate_grasps_script",
                molmospaces_root
                / "molmo_spaces"
                / "grasp_generation"
                / "pipeline"
                / "generate_grasps.py",
                must_be_executable=False,
            ),
            _path_check(
                "perturbations_test_script",
                molmospaces_root
                / "molmo_spaces"
                / "grasp_generation"
                / "pipeline"
                / "perturbations_test.py",
                must_be_executable=False,
            ),
            _path_check(
                "manifold_executable",
                molmospaces_root / "external_src" / "Manifold" / "build" / "manifold",
                must_be_executable=True,
            ),
            _path_check(
                "simplify_executable",
                molmospaces_root / "external_src" / "Manifold" / "build" / "simplify",
                must_be_executable=True,
            ),
        ]
    )
    if assets_dir is None:
        checks.append(
            {
                "name": "assets_dir",
                "status": "blocked",
                "code": "assets_dir_unknown",
                "message": "MolmoSpaces assets dir could not be resolved.",
            }
        )
    else:
        checks.append(
            _path_check(
                "floating_robotiq_model",
                assets_dir / "robots" / "floating_robotiq" / "model_rigid.xml",
                must_be_executable=False,
            )
        )
    return checks


def _grasp_cache_generation_asset_preflight(
    asset: dict[str, Any],
    *,
    molmospaces_root: Path | None,
    objects_list_path: Path,
) -> dict[str, Any]:
    asset_uid = str(asset.get("asset_uid") or "")
    object_xml = _first_object_asset(asset, kind="xml")
    cache_target = _first_candidate(asset, source="droid")
    generated_npz = (
        molmospaces_root
        / "grasp_results"
        / "rigid_objects"
        / asset_uid
        / f"{asset_uid}_grasps_filtered.npz"
        if molmospaces_root is not None and asset_uid
        else None
    )
    return {
        "asset_uid": asset_uid,
        "object_xml": str(object_xml or ""),
        "object_xml_exists": bool(object_xml and object_xml.exists()),
        "objects_list_entry": {"name": asset_uid, "xml": str(object_xml or "")},
        "objects_list_path": str(objects_list_path),
        "generated_npz_path": str(generated_npz or ""),
        "generated_npz_exists": bool(generated_npz and generated_npz.exists()),
        "cache_target_path": str(cache_target.get("path") or ""),
        "cache_target_resolved_path": str(cache_target.get("resolved_path") or ""),
        "cache_target_relative_path": str(cache_target.get("relative_path") or ""),
    }


def _first_object_asset(asset: dict[str, Any], *, kind: str) -> Path | None:
    for item in asset.get("object_asset_files") or []:
        if isinstance(item, dict) and str(item.get("kind") or "") == kind:
            path = str(item.get("resolved_path") or item.get("path") or "")
            if path:
                return Path(path)
    return None


def _first_candidate(asset: dict[str, Any], *, source: str) -> dict[str, Any]:
    for item in asset.get("candidate_grasp_files") or []:
        if isinstance(item, dict) and str(item.get("source") or "") == source:
            return item
    return {}


def _rigid_generation_command(
    *,
    molmospaces_python: Path | None,
    molmospaces_root: Path | None,
    objects_list_path: Path,
) -> list[str]:
    working_dir = _grasp_generation_working_dir(molmospaces_root)
    script = working_dir / "run_rigid.py" if working_dir is not None else Path("run_rigid.py")
    return [
        str(molmospaces_python or "python"),
        str(script),
        "--objects_list",
        str(objects_list_path),
        "--max_successful_grasps",
        "1000",
        "--num_workers",
        "1",
    ]


def _grasp_generation_working_dir(molmospaces_root: Path | None) -> Path | None:
    if molmospaces_root is None:
        return None
    return molmospaces_root / "molmo_spaces" / "grasp_generation"


def _path_check(name: str, path: Path, *, must_be_executable: bool) -> dict[str, Any]:
    exists = path.exists()
    executable = os.access(path, os.X_OK) if exists else False
    ready = exists and (executable if must_be_executable else path.is_file())
    check = {
        "name": name,
        "path": str(path),
        "resolved_path": _resolved_path(path),
        "exists": exists,
        "executable": executable,
        "status": "ready" if ready else "blocked",
    }
    if not ready:
        check.update(
            {
                "code": f"{name}_missing",
                "message": f"Required path is not ready: {path}",
            }
        )
    return check


def _run_preflight_command(command: list[str], *, timeout_s: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
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
            "code": "preflight_command_timeout",
            "message": f"Preflight command exceeded {timeout_s:.1f}s.",
        }
    return {
        "status": "ready" if completed.returncode == 0 else "blocked",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _blocker_from_check(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(check.get("code") or f"{check.get('name', 'check')}_blocked"),
        "message": str(check.get("message") or check.get("stderr") or "preflight check blocked"),
        "name": str(check.get("name") or ""),
    }


def _optional_path(value: Any) -> Path | None:
    text = str(value or "")
    return Path(text).expanduser() if text else None
