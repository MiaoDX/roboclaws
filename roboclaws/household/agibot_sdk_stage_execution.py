"""AgiBot SDK subprocess stage execution and private-path redaction."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object


class AgibotSDKStageExecutionError(RuntimeError):
    pass


def execute_agibot_sdk_stage(
    *,
    stage_name: str,
    args: list[str],
    run_dir: Path,
    runner_python: str,
    runner_script: Path,
    redactions: dict[str, str],
) -> dict[str, Any]:
    stage_dir = run_dir / "subphases" / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    command = [runner_python, str(runner_script), *args]
    try:
        proc = subprocess.run(
            command,
            cwd=runner_script.parent.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise AgibotSDKStageExecutionError(
            f"SDK runner process could not start for {stage_name}: {type(exc).__name__}"
        ) from None
    stdout = redact_text(proc.stdout, redactions)
    stderr = redact_text(proc.stderr, redactions)
    (stage_dir / "runner_stdout.txt").write_text(stdout, encoding="utf-8")
    (stage_dir / "runner_stderr.txt").write_text(stderr, encoding="utf-8")
    result_path = stage_dir / "run_result.json"
    if not result_path.is_file():
        raise AgibotSDKStageExecutionError(
            f"SDK runner failed before writing run_result.json for {stage_name}: "
            f"exit={proc.returncode} stderr={stderr.strip()}"
        )
    result = redact_payload(load_json(result_path), redactions)
    result["returncode"] = proc.returncode
    result["command"] = redact_payload(command, redactions)
    result["report_path"] = str(stage_dir / "report.html")
    result["stdout_path"] = str(stage_dir / "runner_stdout.txt")
    result["stderr_path"] = str(stage_dir / "runner_stderr.txt")
    write_json(result_path, redact_payload(result, redactions))
    redact_artifact_tree(stage_dir, redactions)
    return result


def resolve_executable(value: str | Path) -> str:
    raw = str(value).strip()
    resolved = shutil.which(raw)
    if resolved:
        return str(Path(resolved).resolve())
    candidate = Path(raw).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    raise AgibotSDKStageExecutionError(
        "Agibot SDK runner dependency check failed: invalid runner_python"
    )


def redact_payload(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: redact_payload(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_payload(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(item, replacements) for item in value)
    if isinstance(value, str):
        return redact_text(value, replacements)
    return value


def redact_text(value: str, replacements: dict[str, str]) -> str:
    redacted = value
    for private_value, label in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if private_value:
            redacted = redacted.replace(private_value, label)
    return redacted


def redact_artifact_tree(root: Path, replacements: dict[str, str]) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".html",
            ".json",
            ".jsonl",
            ".log",
            ".txt",
            ".yaml",
            ".yml",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        redacted = redact_text(text, replacements)
        if redacted != text:
            path.write_text(redacted, encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="Agibot SDK runner artifact")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
