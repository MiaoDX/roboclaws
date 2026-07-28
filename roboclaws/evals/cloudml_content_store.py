from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "roboclaws_cloudml_content_manifest_v2"
DEFAULT_CONTENT_SUBPATH = "/dongxu/gpu_perf/gpu_perf/roboclaws-content"


def load_identity(path: Path) -> dict[str, str]:
    payload = _read_json(path, label="CloudML content manifest")
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"CloudML content manifest must use schema {MANIFEST_SCHEMA}")
    code = payload.get("git") or {}
    code_archive = code.get("code_archive") or {}
    asset_archive = (payload.get("staged_assets") or {}).get("archive") or {}
    identity = {
        "code_commit": str(code.get("code_commit") or ""),
        "code_archive_name": str(code_archive.get("name") or ""),
        "code_archive_sha256": str(code_archive.get("sha256") or ""),
        "code_archive_local_path": str(code_archive.get("local_path") or ""),
        "asset_archive_name": str(asset_archive.get("name") or ""),
        "asset_archive_sha256": str(asset_archive.get("sha256") or ""),
        "asset_archive_local_path": str(asset_archive.get("local_path") or ""),
        "asset_manifest_name": path.name,
        "asset_manifest_sha256": _sha256_file(path),
    }
    missing = [key for key, value in identity.items() if not value]
    if missing:
        raise ValueError(
            "CloudML content manifest is missing identity field(s): " + ", ".join(missing)
        )
    _validate_archive_identity(identity, kind="asset")
    _validate_archive_identity(identity, kind="code")
    return identity


def configure_staging(
    plan: dict[str, Any],
    *,
    manifest_path: Path,
    juicefs_url: Callable[[str], str],
    output_subpath: str,
    prior_staging: dict[str, Any] | None = None,
    content_root_subpath: str = DEFAULT_CONTENT_SUBPATH,
    run_input_subpath: str = "",
) -> dict[str, str]:
    identity = load_identity(manifest_path)
    prior = prior_staging or {}
    root = content_root_subpath.rstrip("/")
    run_subpath = run_input_subpath or f"{root}/runs/{plan['run_id']}"
    asset_subpath = f"{root}/assets/by-sha256/{identity['asset_archive_sha256']}"
    code_subpath = f"{root}/code/by-sha256/{identity['code_archive_sha256']}"
    asset = _cache_entry(
        kind="asset",
        local_path=identity["asset_archive_local_path"],
        sha256=identity["asset_archive_sha256"],
        subpath=asset_subpath,
        juicefs_url=juicefs_url,
        prior=prior.get("asset"),
    )
    code = _cache_entry(
        kind="code",
        local_path=identity["code_archive_local_path"],
        sha256=identity["code_archive_sha256"],
        subpath=code_subpath,
        juicefs_url=juicefs_url,
        prior=prior.get("code"),
    )
    run_input = {
        "local_dir": str(manifest_path.parent),
        "subpath": run_subpath,
        "url": juicefs_url(run_subpath),
        "upload_required": True,
    }
    prior_run_upload = (prior.get("run_input") or {}).get("upload")
    if prior_run_upload and prior_run_upload.get("status") == "completed":
        run_input["upload"] = prior_run_upload
        run_input["upload_required"] = False
    plan["staging"] = {
        "content_root_subpath": root,
        "asset": asset,
        "code": code,
        "run_input": run_input,
        "output_subpath": output_subpath,
        "output_url": juicefs_url(output_subpath),
    }
    return identity


def upload(
    plan: dict[str, Any],
    *,
    executor_path: Path,
    persist: Callable[[], None],
) -> None:
    staging = plan["staging"]
    for kind in ("asset", "code"):
        entry = staging[kind]
        if not entry.get("upload_required"):
            continue
        if _remote_cache_ready(entry, executor_path=executor_path):
            entry["upload"] = {
                "status": "reused",
                "checked_at": _utc_now(),
                "files": len(entry["markers"]),
            }
            entry["upload_required"] = False
            persist()
            continue
        _upload_directory(entry, executor_path=executor_path, label=kind)
        persist()

    run_input = staging["run_input"]
    if run_input.get("upload_required"):
        _upload_directory(run_input, executor_path=executor_path, label="run input")
        persist()


def _cache_entry(
    *,
    kind: str,
    local_path: str,
    sha256: str,
    subpath: str,
    juicefs_url: Callable[[str], str],
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    archive = Path(local_path)
    checksum = Path(f"{archive}.sha256")
    if not archive.is_file() or not checksum.is_file():
        raise ValueError(f"CloudML {kind} cache is incomplete: {archive}")
    entry = {
        "sha256": sha256,
        "local_dir": str(archive.parent),
        "subpath": subpath,
        "url": juicefs_url(subpath),
        "markers": [archive.name, checksum.name],
        "upload_required": True,
    }
    prior_upload = (prior or {}).get("upload")
    if (
        prior_upload
        and (prior or {}).get("sha256") == sha256
        and (prior or {}).get("subpath") == subpath
        and prior_upload.get("status") in {"completed", "reused"}
    ):
        entry["upload"] = prior_upload
        entry["upload_required"] = False
    return entry


def _remote_cache_ready(entry: dict[str, Any], *, executor_path: Path) -> bool:
    result = subprocess.run(
        [
            str(executor_path),
            "storage",
            "juicefs",
            "probe",
            "--url",
            str(entry["url"]),
            "--markers",
            ",".join(entry["markers"]),
            "--max_depth",
            "0",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"CloudML content cache probe failed: {detail}")
    payload = _parse_json(result.stdout, label="JuiceFS content cache probe")
    if payload.get("status") != "ok" or int(payload.get("exit_code") or 0) != 0:
        raise RuntimeError(f"CloudML content cache probe was not successful: {payload}")
    for hit in payload.get("hits") or []:
        reported = hit.get("markers") if isinstance(hit, dict) else None
        if not isinstance(reported, dict):
            continue
        if all(
            isinstance(reported.get(marker), dict) and reported[marker].get("exists") is True
            for marker in entry["markers"]
        ):
            return True
    return False


def _validate_archive_identity(identity: dict[str, str], *, kind: str) -> None:
    sha256 = identity[f"{kind}_archive_sha256"]
    name = identity[f"{kind}_archive_name"]
    archive = Path(identity[f"{kind}_archive_local_path"])
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError(f"CloudML {kind} archive sha256 must be 64 lowercase hex characters")
    if name != archive.name or Path(name).name != name:
        raise ValueError(f"CloudML {kind} archive name must match its local path")
    checksum = Path(f"{archive}.sha256")
    if not checksum.is_file():
        raise ValueError(f"CloudML {kind} archive checksum marker is missing")
    expected_marker = f"{sha256}  {name}"
    if checksum.read_text(encoding="utf-8").strip() != expected_marker:
        raise ValueError(f"CloudML {kind} archive checksum marker does not match its identity")


def _upload_directory(
    entry: dict[str, Any],
    *,
    executor_path: Path,
    label: str,
) -> None:
    result = subprocess.run(
        [
            str(executor_path),
            "storage",
            "juicefs",
            "upload",
            "--local_dir",
            str(entry["local_dir"]),
            "--url",
            str(entry["url"]),
            "--no_manifest",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"CloudML {label} upload failed: {detail}")
    payload = _parse_json(result.stdout, label=f"JuiceFS {label} upload")
    if payload.get("status") != "ok" or int(payload.get("exit_code") or 0) != 0:
        raise RuntimeError(f"CloudML {label} upload was not successful: {payload}")
    entry["upload"] = {
        "status": "completed",
        "completed_at": _utc_now(),
        "files": int(payload.get("files") or 0),
    }
    entry["upload_required"] = False


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must contain valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _parse_json(value: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must return a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
