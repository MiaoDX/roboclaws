from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any

from roboclaws.evals.cloudml_content_store import MANIFEST_SCHEMA

CONTRACT_SCHEMA = "roboclaws_cloudml_isaac_proof_contract_v1"
TEXT_SUFFIXES = {".json", ".toml", ".usd", ".usda", ".yaml", ".yml"}
WORKSTATION_PATH = re.compile(r"(?:file://|/home/|/Users/|[A-Za-z]:[\\/])")
ABSOLUTE_USD_REFERENCE = re.compile(r"@/(?:[^@\r\n]+)@")


def prepare_stage(
    *,
    repo_root: Path,
    contract_path: Path,
    stage_id: str,
    output_dir: Path,
    code_archive: Path,
    code_commit: str,
) -> Path:
    repo_root = repo_root.resolve()
    contract_path = contract_path.resolve()
    contract_bytes = contract_path.read_bytes()
    contract = _json_object(contract_bytes, label="Isaac proof contract")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError(f"Isaac proof contract must use schema {CONTRACT_SCHEMA}")
    stage = (contract.get("stages") or {}).get(stage_id)
    if not isinstance(stage, dict):
        raise ValueError(f"Isaac proof contract does not define Stage {stage_id}")
    group_name = str(stage.get("asset_group") or "")
    group = (contract.get("asset_groups") or {}).get(group_name)
    if not isinstance(group, dict) or stage_id not in group.get("stages", []):
        raise ValueError(f"Isaac Stage {stage_id} has an invalid asset group")
    roots = _resolve_roots(repo_root, group.get("roots") or [])
    files = _portable_files(repo_root, roots)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"roboclaws-isaac-{group_name}.tar.gz"
    archive_path = output_dir / archive_name
    file_entries = _write_archive(
        archive_path,
        repo_root=repo_root,
        files=files,
        generated_only=bool(group.get("generated_only")),
        stage_id=stage_id,
        group_name=group_name,
    )
    archive_bytes = archive_path.stat().st_size
    if archive_bytes > int(group.get("maximum_archive_bytes") or 0):
        raise ValueError(
            f"Isaac {group_name} archive exceeds contract maximum: {archive_bytes} bytes"
        )
    archive_sha = _sha256(archive_path)
    Path(f"{archive_path}.sha256").write_text(f"{archive_sha}  {archive_name}\n", encoding="utf-8")
    code_archive = code_archive.resolve()
    _validate_code_archive(code_archive, code_commit=code_commit)
    code_sha = _sha256(code_archive)
    contract_sha = hashlib.sha256(contract_bytes).hexdigest()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "juicefs": {"content_rel": "roboclaws-content"},
        "git": {
            "code_commit": code_commit,
            "code_archive": {
                "local_path": str(code_archive),
                "name": code_archive.name,
                "sha256": code_sha,
                "bytes": code_archive.stat().st_size,
            },
        },
        "isaac": {
            "stage_id": stage_id,
            "asset_group": group_name,
            "proof_contract_sha256": contract_sha,
            "roots": [str(path.relative_to(repo_root)) for path in roots],
            "files": file_entries,
            "total_source_bytes": sum(int(item["bytes"]) for item in file_entries),
        },
        "staged_assets": {
            "mode": "archive",
            "archive": {
                "local_path": str(archive_path),
                "name": archive_name,
                "sha256": archive_sha,
                "bytes": archive_bytes,
            },
        },
    }
    manifest_path = output_dir / f"roboclaws_cloudml_isaac_stage_{stage_id.lower()}_assets.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _resolve_roots(repo_root: Path, raw_roots: list[Any]) -> list[Path]:
    roots: list[Path] = []
    for raw in raw_roots:
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Isaac asset root must be repo-relative: {raw}")
        resolved = (repo_root / relative).resolve()
        if not resolved.is_relative_to(repo_root):
            raise ValueError(f"Isaac asset root escapes the repository: {raw}")
        if not resolved.exists():
            raise ValueError(f"Isaac asset root is missing: {raw}")
        roots.append(resolved)
    return roots


def _portable_files(repo_root: Path, roots: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        candidates = [root] if root.is_file() else list(root.rglob("*"))
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(
                    f"Isaac asset closure contains a symlink: {candidate.relative_to(repo_root)}"
                )
            if not candidate.is_file():
                continue
            _validate_portable_text(candidate, repo_root=repo_root)
            files.add(candidate)
    return sorted(files, key=lambda path: path.relative_to(repo_root).as_posix())


def _validate_portable_text(path: Path, *, repo_root: Path) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 16 * 1024 * 1024:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if WORKSTATION_PATH.search(text) or ABSOLUTE_USD_REFERENCE.search(text):
        raise ValueError(
            f"Isaac asset contains an absolute workstation reference: {path.relative_to(repo_root)}"
        )


def _write_archive(
    archive_path: Path,
    *,
    repo_root: Path,
    files: list[Path],
    generated_only: bool,
    stage_id: str,
    group_name: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with archive_path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|") as archive:
            if generated_only:
                payload = json.dumps(
                    {"asset_group": group_name, "generated_only": True, "stage_id": stage_id},
                    sort_keys=True,
                ).encode()
                info = _tar_info("roboclaws/isaac/generated-smoke.json", len(payload))
                archive.addfile(info, io.BytesIO(payload))
            for path in files:
                relative = path.relative_to(repo_root).as_posix()
                info = _tar_info(f"roboclaws/{relative}", path.stat().st_size)
                with path.open("rb") as source:
                    archive.addfile(info, source)
                entries.append(
                    {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}
                )
    return entries


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _validate_code_archive(path: Path, *, code_commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("CloudML code commit must be a full 40-character SHA")
    if not path.is_file():
        raise ValueError(f"CloudML code archive is missing: {path}")
    marker = Path(f"{path}.sha256")
    expected = f"{_sha256(path)}  {path.name}"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != expected:
        raise ValueError("CloudML code archive checksum marker is missing or invalid")
    try:
        with tarfile.open(path, "r:gz") as archive:
            member = archive.getmember("roboclaws.git/.roboclaws_code_commit")
            stream = archive.extractfile(member)
            embedded_commit = stream.read().decode().strip() if stream is not None else ""
    except (KeyError, tarfile.TarError, UnicodeDecodeError) as exc:
        raise ValueError("CloudML code archive has no readable commit marker") from exc
    if embedded_commit != code_commit:
        raise ValueError("CloudML code archive commit marker does not match requested commit")


def _json_object(value: bytes, *, label: str) -> dict[str, Any]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
