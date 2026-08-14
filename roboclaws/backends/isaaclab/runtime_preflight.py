#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from roboclaws.core import nvidia_eula as eula

SCHEMA = "roboclaws_isaac_lab_runtime_preflight_v1"
DEFAULT_MIN_FREE_GB = 80
ISAACSIM_VERSION = "6.0.0"
TORCH_VERSION = "2.7.0"
TORCHVISION_VERSION = "0.22.0"
UV_HTTP_TIMEOUT_SECONDS = "300"
NVIDIA_PYPI_INDEX = "https://pypi.nvidia.com"
PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
ISAACLAB_GIT_URL = "https://github.com/isaac-sim/IsaacLab.git"
DOC_SOURCES = {
    "isaac_lab_pip": (
        "https://isaac-sim.github.io/IsaacLab/develop/source/setup/installation/"
        "pip_installation.html"
    ),
    "isaac_sim_requirements": (
        "https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html"
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or create the isolated Isaac Lab runtime for Roboclaws."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/isaaclab/preflight"))
    parser.add_argument("--stamp", default="")
    parser.add_argument("--runtime-dir", type=Path, default=Path(".venv-isaaclab"))
    parser.add_argument("--python", default="3.12", help="uv Python version spec for the runtime")
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--isaaclab-source", type=Path)
    parser.add_argument("--min-free-gb", type=int, default=DEFAULT_MIN_FREE_GB)
    parser.add_argument("--skip-gpu-probe", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.accept_nvidia_eula = eula.accepted(explicit=args.accept_nvidia_eula)
    repo_root = Path(__file__).resolve().parents[3]
    output_dir = resolve_path(repo_root, args.output_dir)
    runtime_dir = resolve_path(repo_root, args.runtime_dir)
    source_dir = resolve_path(
        repo_root,
        args.isaaclab_source or Path(".venv-isaaclab-src") / "IsaacLab",
    )
    run_dir = output_dir / (args.stamp or timestamp())
    run_dir.mkdir(parents=True, exist_ok=True)

    install_steps = build_install_steps(
        repo_root=repo_root,
        runtime_dir=runtime_dir,
        python_spec=args.python,
        source_dir=source_dir,
        accepted_nvidia_eula=args.accept_nvidia_eula,
    )
    install_script = run_dir / "install_isaac_lab_runtime.sh"
    write_install_script(install_script, install_steps)

    install_attempt = maybe_install(
        install_steps=install_steps,
        accepted_nvidia_eula=args.accept_nvidia_eula,
        requested=args.install,
        repo_root=repo_root,
    )
    report = build_report(
        args=args,
        repo_root=repo_root,
        run_dir=run_dir,
        runtime_dir=runtime_dir,
        source_dir=source_dir,
        install_steps=install_steps,
        install_script=install_script,
        install_attempt=install_attempt,
    )
    report_path = run_dir / "preflight.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema": SCHEMA,
        "status": report["status"],
        "report_path": str(report_path),
        "install_script": str(install_script),
    }
    print(json.dumps(summary, sort_keys=True))

    if args.install and install_attempt["status"] != "succeeded":
        return 2
    if args.strict and report["status"] == "blocked":
        return 2
    return 0


def timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m%d_%H%M%S")


def resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def build_install_steps(
    *,
    repo_root: Path,
    runtime_dir: Path,
    python_spec: str,
    source_dir: Path,
    accepted_nvidia_eula: bool = False,
) -> list[dict[str, Any]]:
    runtime_python = runtime_dir / "bin" / "python"
    uv_env = uv_network_env()
    isaac_env = isaac_runtime_env(accepted_nvidia_eula=accepted_nvidia_eula)
    return [
        {
            "name": "create_runtime_env",
            "argv": ["uv", "venv", "--python", python_spec, "--seed", str(runtime_dir)],
            "cwd": str(repo_root),
        },
        {
            "name": "upgrade_pip",
            "argv": [
                "uv",
                "pip",
                "install",
                "--python",
                str(runtime_python),
                "--upgrade",
                "pip",
            ],
            "cwd": str(repo_root),
        },
        {
            "name": "install_isaacsim",
            "argv": [
                "uv",
                "pip",
                "install",
                "--python",
                str(runtime_python),
                f"isaacsim[all,extscache]=={ISAACSIM_VERSION}",
                "--extra-index-url",
                NVIDIA_PYPI_INDEX,
                "--index-strategy",
                "unsafe-best-match",
                "--prerelease=allow",
            ],
            "cwd": str(repo_root),
            "env": uv_env,
        },
        {
            "name": "install_cuda_torch",
            "argv": [
                "uv",
                "pip",
                "install",
                "--python",
                str(runtime_python),
                f"torch=={TORCH_VERSION}",
                f"torchvision=={TORCHVISION_VERSION}",
                "--index-url",
                PYTORCH_CUDA_INDEX,
            ],
            "cwd": str(repo_root),
            "env": uv_env,
        },
        {
            "name": "create_isaaclab_source_parent",
            "argv": ["mkdir", "-p", str(source_dir.parent)],
            "cwd": str(repo_root),
        },
        {
            "name": "clone_isaac_lab_source",
            "argv": ["git", "clone", "--depth", "1", ISAACLAB_GIT_URL, str(source_dir)],
            "cwd": str(repo_root),
            "skip_if_path_exists": str(source_dir / ".git"),
        },
        {
            "name": "install_isaac_lab_source",
            "argv": ["bash", "./isaaclab.sh", "-i", "none"],
            "cwd": str(source_dir),
            "env": {
                "VIRTUAL_ENV": str(runtime_dir),
                "PATH_PREFIX": str(runtime_dir / "bin"),
                **isaac_env,
            },
        },
    ]


def uv_network_env() -> dict[str, str]:
    return {"UV_HTTP_TIMEOUT": UV_HTTP_TIMEOUT_SECONDS}


def isaac_runtime_env(*, accepted_nvidia_eula: bool) -> dict[str, str]:
    env = uv_network_env()
    if accepted_nvidia_eula:
        eula.record_acceptance(env)
    return env


def write_install_script(path: Path, steps: list[dict[str, Any]]) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review NVIDIA Omniverse license terms before running this script.",
        "# Generated by roboclaws.backends.isaaclab.runtime_preflight.",
        "",
    ]
    for step in steps:
        lines.append(f"echo '==> {step['name']}'")
        command = command_as_shell(step)
        skip_path = step.get("skip_if_path_exists")
        if skip_path:
            quoted_skip = shlex.quote(str(skip_path))
            lines.extend(
                [
                    f"if [[ -e {quoted_skip} ]]; then",
                    f"  echo 'skip: {step['name']} already exists'",
                    "else",
                    f"  {command}",
                    "fi",
                    "",
                ]
            )
        else:
            lines.extend([command, ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)


def command_as_shell(step: dict[str, Any]) -> str:
    command = shlex.join([str(part) for part in step["argv"]])
    env = dict(step.get("env") or {})
    if env:
        assignments = []
        path_prefix = env.pop("PATH_PREFIX", None)
        if path_prefix:
            assignments.append(f"PATH={shlex.quote(str(path_prefix))}:$PATH")
        assignments.extend(f"{key}={shlex.quote(str(value))}" for key, value in env.items())
        command = " ".join(assignments + [command])
    cwd = step.get("cwd")
    if cwd:
        return f"(cd {shlex.quote(str(cwd))} && {command})"
    return command


def maybe_install(
    *,
    install_steps: list[dict[str, Any]],
    accepted_nvidia_eula: bool,
    requested: bool,
    repo_root: Path,
) -> dict[str, Any]:
    if not requested:
        return {"requested": False, "status": "not_requested", "steps": []}
    if not accepted_nvidia_eula:
        return {
            "requested": True,
            "status": "blocked",
            "reason": "--install requires --accept-nvidia-eula before NVIDIA packages are fetched.",
            "steps": [],
        }

    results: list[dict[str, Any]] = []
    for step in install_steps:
        result = run_install_step(step, repo_root=repo_root)
        results.append(result)
        if result["status"] == "failed":
            return {
                "requested": True,
                "status": "failed",
                "failed_step": step["name"],
                "steps": results,
            }
    return {"requested": True, "status": "succeeded", "steps": results}


def run_install_step(step: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    skip_path = step.get("skip_if_path_exists")
    if skip_path and Path(str(skip_path)).exists():
        return {"name": step["name"], "status": "skipped", "reason": "path_exists"}

    env = os.environ.copy()
    for key, value in dict(step.get("env") or {}).items():
        if key == "PATH_PREFIX":
            env["PATH"] = f"{value}{os.pathsep}{env.get('PATH', '')}"
        else:
            env[key] = str(value)
    completed = subprocess.run(
        [str(part) for part in step["argv"]],
        cwd=Path(str(step.get("cwd") or repo_root)),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    status = "succeeded" if completed.returncode == 0 else "failed"
    return {
        "name": step["name"],
        "status": status,
        "returncode": completed.returncode,
        "stdout_tail": tail_text(completed.stdout),
        "stderr_tail": tail_text(completed.stderr),
    }


def build_report(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    run_dir: Path,
    runtime_dir: Path,
    source_dir: Path,
    install_steps: list[dict[str, Any]],
    install_script: Path,
    install_attempt: dict[str, Any],
) -> dict[str, Any]:
    checks = collect_checks(
        args=args,
        repo_root=repo_root,
        runtime_dir=runtime_dir,
        source_dir=source_dir,
    )
    if install_attempt["status"] in {"blocked", "failed"}:
        checks.append(
            check(
                "install_attempt",
                "blocked",
                str(install_attempt.get("reason") or install_attempt["status"]),
            )
        )
    status = overall_status(checks)
    return {
        "schema": SCHEMA,
        "status": status,
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "repo_root": str(repo_root),
        "run_dir": str(run_dir),
        "runtime_dir": str(runtime_dir),
        "isaaclab_source": str(source_dir),
        "core_venv": str(repo_root / ".venv"),
        "checks": checks,
        "install_plan": {
            "status": "visible_only_unless_install_flag_is_set",
            "requires_explicit_flags": ["--install", "--accept-nvidia-eula"],
            "script_path": str(install_script),
            "steps": install_steps,
            "sources": DOC_SOURCES,
        },
        "install_attempt": install_attempt,
    }


def collect_checks(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    runtime_dir: Path,
    source_dir: Path,
) -> list[dict[str, Any]]:
    runtime_python = runtime_dir / "bin" / "python"
    checks: list[dict[str, Any]] = [
        isolation_check(repo_root=repo_root, runtime_dir=runtime_dir),
        gitignore_check(repo_root=repo_root, runtime_dir=runtime_dir),
        uv_check(),
        python_312_check(args=args),
        disk_check(path=runtime_dir.parent, min_free_gb=args.min_free_gb),
        gpu_check(skip=args.skip_gpu_probe),
        path_check("runtime_dir_exists", runtime_dir, "runtime directory"),
        path_check("runtime_python_exists", runtime_python, "runtime Python"),
        path_check("isaaclab_source_exists", source_dir, "Isaac Lab source checkout"),
    ]
    checks.extend(
        package_checks(
            runtime_python,
            accepted_nvidia_eula=args.accept_nvidia_eula,
        )
    )
    return checks


def isolation_check(*, repo_root: Path, runtime_dir: Path) -> dict[str, Any]:
    core_venv = repo_root / ".venv"
    if runtime_dir == core_venv or is_relative_to(runtime_dir, core_venv):
        return check(
            "runtime_isolation",
            "blocked",
            "Isaac runtime must not be the core Roboclaws .venv/.",
        )
    return check("runtime_isolation", "pass", "Isaac runtime is separate from core .venv/.")


def gitignore_check(*, repo_root: Path, runtime_dir: Path) -> dict[str, Any]:
    relative = os.path.relpath(runtime_dir, repo_root).rstrip("/") + "/"
    completed = subprocess.run(
        ["git", "check-ignore", "--quiet", relative],
        cwd=repo_root,
        check=False,
    )
    if completed.returncode == 0:
        return check("runtime_gitignore", "pass", f"{relative} is ignored by git.")
    return check(
        "runtime_gitignore",
        "blocked",
        f"{relative} is not ignored by git; keep heavy Isaac packages out of commits.",
    )


def uv_check() -> dict[str, Any]:
    uv_path = shutil.which("uv")
    if uv_path:
        return check("uv_available", "pass", "uv is available.", executable=uv_path)
    return check("uv_available", "blocked", "uv is required to create .venv-isaaclab/.")


def python_312_check(*, args: argparse.Namespace) -> dict[str, Any]:
    executable = find_python(args)
    if executable is None:
        return check("python_312_available", "blocked", "Could not find a Python 3.12 runtime.")
    try:
        completed = subprocess.run(
            [
                str(executable),
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as exc:
        return check(
            "python_312_available",
            "blocked",
            f"Could not execute requested Python runtime: {exc}.",
            executable=str(executable),
        )
    version = completed.stdout.strip()
    if completed.returncode == 0 and version == "3.12":
        return check(
            "python_312_available",
            "pass",
            "Python 3.12 is available.",
            executable=str(executable),
            version=version,
        )
    return check(
        "python_312_available",
        "blocked",
        f"Isaac Sim 6.x runtime expects Python 3.12; found {version or 'unknown'}.",
        executable=str(executable),
        version=version,
    )


def find_python(args: argparse.Namespace) -> Path | None:
    if args.python_executable:
        return args.python_executable
    uv_path = shutil.which("uv")
    if uv_path:
        completed = subprocess.run(
            [uv_path, "python", "find", args.python],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        candidate = completed.stdout.strip()
        if completed.returncode == 0 and candidate:
            return Path(candidate)
    for candidate in (f"python{args.python}", "python3.12"):
        path = shutil.which(candidate)
        if path:
            return Path(path)
    return None


def disk_check(*, path: Path, min_free_gb: int) -> dict[str, Any]:
    usage = shutil.disk_usage(existing_parent(path))
    free_gb = usage.free / (1024**3)
    if free_gb >= min_free_gb:
        return check(
            "disk_free",
            "pass",
            f"{free_gb:.1f} GiB free; threshold is {min_free_gb} GiB.",
            free_gb=round(free_gb, 2),
            min_free_gb=min_free_gb,
        )
    return check(
        "disk_free",
        "blocked",
        f"{free_gb:.1f} GiB free; Isaac runtime setup needs at least {min_free_gb} GiB.",
        free_gb=round(free_gb, 2),
        min_free_gb=min_free_gb,
    )


def existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def gpu_check(*, skip: bool) -> dict[str, Any]:
    if skip:
        return check("nvidia_gpu", "skipped", "GPU probe skipped by --skip-gpu-probe.")
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return check("nvidia_gpu", "blocked", "nvidia-smi is not available.")
    completed = subprocess.run(
        [
            nvidia_smi,
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return check("nvidia_gpu", "blocked", completed.stderr.strip() or "nvidia-smi failed.")
    first_line = next((line for line in completed.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) < 3:
        return check("nvidia_gpu", "blocked", "Could not parse nvidia-smi GPU output.")
    name, memory_mb, driver = parts[:3]
    return check(
        "nvidia_gpu",
        "pass",
        f"{name}, {memory_mb} MiB VRAM, driver {driver}.",
        gpu_name=name,
        vram_mb=to_int(memory_mb),
        driver_version=driver,
    )


def path_check(name: str, path: Path, label: str) -> dict[str, Any]:
    if path.exists():
        return check(name, "pass", f"{label} exists.", path=str(path))
    return check(name, "blocked", f"{label} is missing.", path=str(path))


def package_checks(runtime_python: Path, *, accepted_nvidia_eula: bool) -> list[dict[str, Any]]:
    if not runtime_python.exists():
        return [
            check("runtime_import_torch", "blocked", "runtime Python is missing."),
            check("runtime_import_isaacsim", "blocked", "runtime Python is missing."),
            check("runtime_import_isaaclab", "blocked", "runtime Python is missing."),
        ]
    return [
        package_check(runtime_python, "torch", accepted_nvidia_eula=accepted_nvidia_eula),
        package_check(runtime_python, "isaacsim", accepted_nvidia_eula=accepted_nvidia_eula),
        package_check(runtime_python, "isaaclab", accepted_nvidia_eula=accepted_nvidia_eula),
    ]


def package_check(
    runtime_python: Path,
    package: str,
    *,
    accepted_nvidia_eula: bool,
) -> dict[str, Any]:
    env = None
    if package == "isaacsim":
        if not accepted_nvidia_eula:
            return check(
                "runtime_import_isaacsim",
                "blocked",
                "Isaac Sim import may prompt for the NVIDIA Omniverse EULA; rerun with "
                "--accept-nvidia-eula after reviewing the license terms.",
            )
        env = os.environ.copy()
        env.update(isaac_runtime_env(accepted_nvidia_eula=True))
    code = (
        "import importlib; "
        f"mod = importlib.import_module({package!r}); "
        "print(getattr(mod, '__version__', 'unknown'))"
    )
    completed = subprocess.run(
        [str(runtime_python), "-c", code],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=30,
    )
    name = f"runtime_import_{package}"
    if completed.returncode == 0:
        return check(
            name,
            "pass",
            f"{package} imports from runtime Python.",
            version=completed.stdout.strip() or "unknown",
        )
    return check(name, "blocked", tail_text(completed.stderr) or f"{package} import failed.")


def check(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    payload = {"name": name, "status": status, "detail": detail}
    payload.update(extra)
    return payload


def overall_status(checks: list[dict[str, Any]]) -> str:
    if any(item["status"] == "blocked" for item in checks):
        return "blocked"
    if any(item["status"] == "warning" for item in checks):
        return "warning"
    return "ready"


def tail_text(text: str, *, max_chars: int = 2000) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
