#!/usr/bin/env python3
"""Materialize a reviewed public tree from one exact source commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

EXCLUDED_PATHS = {
    ".gitmodules",
    "CLAUDE.md",
    "PLAN.md",
    "sidecars/visual-grounding/uv.lock",
    "THOUGHTS.md",
    "TODOS.md",
    "vendors/agibot_sdk",
}
EXCLUDED_PREFIXES = (
    ".planning/",
    "docs/adr/archive/",
    "docs/ai/",
    "docs/blog/",
    "docs/plans/",
    "docs/research/",
    "docs/research-checkpoints/",
    "docs/retrospectives/",
    "docs/status/",
    "roboclaws/operator_console/static/previews/b1-map12-",
    "tests/fixtures/runtime_map_prior/robot_map_12/",
)
EXCLUDED_GLOBS = (
    "assets/maps/b1-map12-*",
    "tests/fixtures/agibot_*",
)
PUBLIC_SUBMODULE_PATH = "vendors/molmospaces"
PUBLIC_SUBMODULE_URL = "https://github.com/allenai/molmospaces.git"
MANIFEST_PATH = "PUBLIC-MEMBERSHIP.json"


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    kind: str
    oid: str
    path: str


def _run(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        args,
        cwd=root,
        input=input_bytes,
        check=True,
        capture_output=True,
    ).stdout


def _source_commit(root: Path, source_ref: str) -> str:
    return _run(root, "git", "rev-parse", f"{source_ref}^{{commit}}").decode().strip()


def _tree_entries(root: Path, source_commit: str) -> list[TreeEntry]:
    output = _run(root, "git", "ls-tree", "-r", "-z", "--full-tree", source_commit)
    entries: list[TreeEntry] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        entries.append(TreeEntry(mode, kind, oid, raw_path.decode()))
    return entries


def _included(entry: TreeEntry) -> bool:
    path = Path(entry.path)
    if entry.path in EXCLUDED_PATHS or entry.path.startswith(EXCLUDED_PREFIXES):
        return False
    if any(path.match(pattern) for pattern in EXCLUDED_GLOBS):
        return False
    if entry.kind == "commit":
        return entry.path == PUBLIC_SUBMODULE_PATH
    return entry.kind == "blob"


def _write_blob(root: Path, output: Path, entry: TreeEntry) -> None:
    destination = output / entry.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_run(root, "git", "cat-file", "blob", entry.oid))
    if entry.mode == "100755":
        destination.chmod(destination.stat().st_mode | 0o111)


def _manifest(source_commit: str, entries: list[TreeEntry]) -> dict[str, object]:
    files = [
        {"path": entry.path, "mode": entry.mode, "git_oid": entry.oid}
        for entry in entries
        if entry.kind == "blob"
    ]
    generated_files = [
        {"path": ".gitmodules", "mode": "100644"},
        {"path": MANIFEST_PATH, "mode": "100644"},
    ]
    gitlinks = [
        {"path": entry.path, "mode": entry.mode, "git_oid": entry.oid}
        for entry in entries
        if entry.kind == "commit"
    ]
    payload: dict[str, object] = {
        "schema": "roboclaws_public_membership_v1",
        "source_commit": source_commit,
        "files": files,
        "generated_files": generated_files,
        "gitlinks": gitlinks,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["membership_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def _initialize_public_git(output: Path, gitlinks: list[TreeEntry]) -> str:
    _run(output, "git", "init", "-q", "--initial-branch=main")
    _run(output, "git", "add", "--all")
    for entry in gitlinks:
        _run(
            output,
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{entry.oid},{entry.path}",
        )
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Roboclaws Release",
            "GIT_AUTHOR_EMAIL": "release@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "Roboclaws Release",
            "GIT_COMMITTER_EMAIL": "release@users.noreply.github.com",
        }
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "chore: initialize public source"],
        cwd=output,
        env=env,
        check=True,
    )
    return _run(output, "git", "rev-parse", "HEAD").decode().strip()


def build_candidate(root: Path, output: Path, source_ref: str) -> dict[str, object]:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source_commit = _source_commit(root, source_ref)
    entries = [entry for entry in _tree_entries(root, source_commit) if _included(entry)]
    blobs = [entry for entry in entries if entry.kind == "blob"]
    gitlinks = [entry for entry in entries if entry.kind == "commit"]
    for entry in blobs:
        _write_blob(root, output, entry)
    (output / ".gitmodules").write_text(
        "[submodule \"vendors/molmospaces\"]\n"
        "\tpath = vendors/molmospaces\n"
        f"\turl = {PUBLIC_SUBMODULE_URL}\n",
        encoding="utf-8",
    )
    manifest = _manifest(source_commit, entries)
    (output / MANIFEST_PATH).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest["candidate_commit"] = _initialize_public_git(output, gitlinks)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-ref", default="HEAD")
    args = parser.parse_args()
    manifest = build_candidate(args.root.resolve(), args.output.resolve(), args.source_ref)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
