from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.planner_grasp_cache_generation import grasp_cache_generation_preflight

GRASP_GENERATION_SETUP_SCHEMA = "molmospaces_grasp_generation_setup_v1"
DEFAULT_GRASP_GENERATION_PYTHON_PACKAGES = ("scikit-learn", "python-fcl")
DEFAULT_MANIFOLD_SUBMODULE_URL = "https://github.com/hjwdzh/Manifold.git"


def build_grasp_generation_setup_commands(
    *,
    molmospaces_python: Path,
    molmospaces_root: Path,
    include_python_prereqs: bool = True,
    include_manifold: bool = True,
    parallel_jobs: int | None = None,
) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    if include_python_prereqs:
        commands.append(
            {
                "name": "install_python_prerequisites",
                "cwd": str(molmospaces_root),
                "command": _python_prereq_install_command(molmospaces_python),
            }
        )
    if include_manifold:
        build_jobs = parallel_jobs or max(1, min(8, os.cpu_count() or 1))
        commands.extend(
            [
                {
                    "name": "ensure_manifold_source",
                    "cwd": str(molmospaces_root),
                    "command": ["git", "submodule", "update", "--init", "--recursive"],
                    "expected_path": "external_src/Manifold",
                    "fallback_command": [
                        "git",
                        "clone",
                        DEFAULT_MANIFOLD_SUBMODULE_URL,
                        "external_src/Manifold",
                    ],
                },
                {
                    "name": "configure_manifold",
                    "cwd": str(molmospaces_root),
                    "command": [
                        "cmake",
                        "-S",
                        "external_src/Manifold",
                        "-B",
                        "external_src/Manifold/build",
                    ],
                },
                {
                    "name": "build_manifold",
                    "cwd": str(molmospaces_root),
                    "command": [
                        "cmake",
                        "--build",
                        "external_src/Manifold/build",
                        "--parallel",
                        str(build_jobs),
                    ],
                },
            ]
        )
    return commands


def run_grasp_generation_setup(
    *,
    molmospaces_python: Path,
    molmospaces_root: Path | None = None,
    availability_preflight: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    include_python_prereqs: bool = True,
    include_manifold: bool = True,
    dry_run: bool = False,
    parallel_jobs: int | None = None,
    command_timeout_s: float = 900.0,
    preflight_timeout_s: float = 30.0,
) -> dict[str, Any]:
    runtime = _resolve_molmospaces_runtime(
        molmospaces_python=molmospaces_python,
        molmospaces_root=molmospaces_root,
        timeout_s=preflight_timeout_s,
    )
    root_text = runtime.get("molmospaces_root") or ""
    resolved_root = Path(root_text) if root_text else Path()
    commands = []
    if runtime.get("status") == "ready":
        commands = build_grasp_generation_setup_commands(
            molmospaces_python=molmospaces_python,
            molmospaces_root=resolved_root,
            include_python_prereqs=include_python_prereqs,
            include_manifold=include_manifold,
            parallel_jobs=parallel_jobs,
        )

    command_results = [
        _run_setup_command(item, dry_run=dry_run, timeout_s=command_timeout_s) for item in commands
    ]
    command_blockers = [
        {
            "code": f"{item['name']}_failed",
            "message": item.get("stderr") or item.get("stdout") or "setup command failed",
            "name": item["name"],
        }
        for item in command_results
        if item.get("status") == "blocked"
    ]
    blockers = list(runtime.get("blockers") or []) + command_blockers
    generation_preflight: dict[str, Any] = {}
    if availability_preflight is not None and runtime.get("status") == "ready" and not dry_run:
        generation_preflight = grasp_cache_generation_preflight(
            availability_preflight,
            output_dir=output_dir,
            molmospaces_python=molmospaces_python,
            molmospaces_root=resolved_root,
            timeout_s=preflight_timeout_s,
        )
        blockers.extend(generation_preflight.get("blockers") or [])

    status = _setup_status(
        dry_run=dry_run,
        runtime_status=str(runtime.get("status") or ""),
        blockers=blockers,
        generation_preflight=generation_preflight,
    )
    return {
        "schema": GRASP_GENERATION_SETUP_SCHEMA,
        "status": status,
        "ready": status == "ready",
        "molmospaces_python": str(molmospaces_python),
        "molmospaces_root": str(resolved_root) if root_text else "",
        "output_dir": str(output_dir or ""),
        "python_packages": list(DEFAULT_GRASP_GENERATION_PYTHON_PACKAGES),
        "runtime": runtime,
        "commands": command_results,
        "command_count": len(command_results),
        "generation_preflight": generation_preflight,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "evidence_note": (
            "Sets up local MolmoSpaces rigid grasp-generation prerequisites and "
            "reruns the same generation preflight when availability evidence is supplied."
        ),
    }


def load_availability_preflight_from_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json_object(path, label="grasp generation proof bundle manifest")
    preflight = manifest.get("grasp_cache_availability_preflight")
    if not isinstance(preflight, dict):
        raise ValueError(f"No grasp_cache_availability_preflight found in {path}")
    return preflight


def _resolve_molmospaces_runtime(
    *,
    molmospaces_python: Path,
    molmospaces_root: Path | None,
    timeout_s: float,
) -> dict[str, Any]:
    if not molmospaces_python.is_file():
        blocker = {
            "code": "molmospaces_python_missing",
            "message": f"MolmoSpaces Python executable is missing: {molmospaces_python}",
        }
        return {
            "status": "blocked",
            "checks": [{"name": "molmospaces_python", **blocker}],
            "blockers": [blocker],
        }
    if molmospaces_root is not None:
        root = molmospaces_root.expanduser()
        status = "ready" if root.is_dir() else "blocked"
        check = {
            "name": "molmospaces_root",
            "status": status,
            "path": str(root),
            "exists": root.is_dir(),
        }
        blockers = []
        if status == "blocked":
            blocker = {
                "code": "molmospaces_root_missing",
                "message": f"MolmoSpaces root is missing: {root}",
            }
            check.update(blocker)
            blockers.append(blocker)
        return {
            "status": status,
            "molmospaces_root": str(root),
            "checks": [check],
            "blockers": blockers,
        }
    command = [
        str(molmospaces_python),
        "-c",
        (
            "from molmo_spaces.molmo_spaces_constants import "
            "ABS_PATH_OF_TOP_LEVEL_MOLMO_SPACES_DIR; "
            "print(ABS_PATH_OF_TOP_LEVEL_MOLMO_SPACES_DIR)"
        ),
    ]
    completed = _run_subprocess(command, cwd=None, timeout_s=timeout_s)
    check = {"name": "molmo_spaces_runtime_root", "command": command, **completed}
    if completed["status"] != "ready":
        blocker = {
            "code": "molmo_spaces_runtime_root_failed",
            "message": completed.get("stderr") or completed.get("stdout") or "runtime probe failed",
        }
        check.update(blocker)
        return {"status": "blocked", "checks": [check], "blockers": [blocker]}
    root = str(completed.get("stdout") or "").strip()
    return {
        "status": "ready",
        "molmospaces_root": root,
        "checks": [check],
        "blockers": [],
    }


def _run_setup_command(
    item: dict[str, Any],
    *,
    dry_run: bool,
    timeout_s: float,
) -> dict[str, Any]:
    if dry_run:
        return {**item, "status": "not_run", "returncode": "", "stdout": "", "stderr": ""}
    completed = _run_subprocess(
        list(item["command"]),
        cwd=Path(str(item["cwd"])),
        timeout_s=timeout_s,
    )
    result = {**item, **completed}
    expected_path = str(item.get("expected_path") or "")
    if expected_path and (Path(str(item["cwd"])) / expected_path).exists():
        result["status"] = "ready"
        return result
    fallback_command = item.get("fallback_command")
    if expected_path and isinstance(fallback_command, list):
        fallback = _run_subprocess(
            [str(value) for value in fallback_command],
            cwd=Path(str(item["cwd"])),
            timeout_s=timeout_s,
        )
        result["fallback_result"] = fallback
        if fallback["status"] == "ready" and (Path(str(item["cwd"])) / expected_path).exists():
            result["status"] = "ready"
            result["returncode"] = fallback["returncode"]
            result["stdout"] = _join_output(result.get("stdout"), fallback.get("stdout"))
            result["stderr"] = _join_output(result.get("stderr"), fallback.get("stderr"))
    return result


def _run_subprocess(
    command: list[str],
    *,
    cwd: Path | None,
    timeout_s: float,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
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
            "code": "setup_command_timeout",
            "message": f"Setup command exceeded {timeout_s:.1f}s.",
        }
    return {
        "status": "ready" if completed.returncode == 0 else "blocked",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _setup_status(
    *,
    dry_run: bool,
    runtime_status: str,
    blockers: list[dict[str, Any]],
    generation_preflight: dict[str, Any],
) -> str:
    if runtime_status != "ready":
        return "blocked"
    if dry_run:
        return "dry_run"
    if blockers:
        return "blocked"
    if generation_preflight and generation_preflight.get("status") != "ready":
        return "blocked"
    return "ready"


def _python_prereq_install_command(molmospaces_python: Path) -> list[str]:
    uv = shutil.which("uv")
    if uv:
        return [
            uv,
            "pip",
            "install",
            "--python",
            str(molmospaces_python),
            *DEFAULT_GRASP_GENERATION_PYTHON_PACKAGES,
        ]
    return [
        str(molmospaces_python),
        "-m",
        "pip",
        "install",
        *DEFAULT_GRASP_GENERATION_PYTHON_PACKAGES,
    ]


def _join_output(first: Any, second: Any) -> str:
    parts = [str(value).strip() for value in (first, second) if str(value or "").strip()]
    return "\n".join(parts)
