from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals import cloudml_content_store


def _manifest(tmp_path: Path) -> Path:
    asset_dir = tmp_path / "cache" / "asset"
    code_dir = tmp_path / "cache" / "code"
    asset_dir.mkdir(parents=True)
    code_dir.mkdir(parents=True)
    asset = asset_dir / "assets.tar.gz"
    code = code_dir / "code.tar.gz"
    asset.write_bytes(b"asset")
    code.write_bytes(b"code")
    Path(f"{asset}.sha256").write_text("a" * 64 + "  assets.tar.gz\n")
    Path(f"{code}.sha256").write_text("b" * 64 + "  code.tar.gz\n")
    path = tmp_path / "run" / "content.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "schema": cloudml_content_store.MANIFEST_SCHEMA,
                "git": {
                    "code_commit": "c" * 40,
                    "code_archive": {
                        "local_path": str(code),
                        "name": code.name,
                        "sha256": "b" * 64,
                    },
                },
                "staged_assets": {
                    "archive": {
                        "local_path": str(asset),
                        "name": asset.name,
                        "sha256": "a" * 64,
                    }
                },
            }
        )
    )
    return path


def _plan() -> dict[str, Any]:
    return {"run_id": "run-1", "staging": {}, "shards": []}


def test_content_store_uses_digest_paths_and_reuses_remote_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    manifest = _manifest(tmp_path)
    cloudml_content_store.configure_staging(
        plan,
        manifest_path=manifest,
        juicefs_url=lambda subpath: f"https://juicefs.test{subpath}",
        output_subpath="/outputs/run-1",
    )
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "probe" in argv:
            payload = {"status": "ok", "exit_code": 0, "hit_count": 2}
        else:
            payload = {"status": "ok", "exit_code": 0, "files": 2}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_content_store.subprocess, "run", fake_run)
    persisted: list[dict[str, Any]] = []
    cloudml_content_store.upload(
        plan,
        executor_path=tmp_path / "exe",
        persist=lambda: persisted.append(json.loads(json.dumps(plan))),
    )

    assert plan["staging"]["asset"]["subpath"].endswith("/assets/by-sha256/" + "a" * 64)
    assert plan["staging"]["code"]["subpath"].endswith("/code/by-sha256/" + "b" * 64)
    assert [call[3] for call in calls] == ["probe", "probe", "upload"]
    assert plan["staging"]["asset"]["upload"]["status"] == "reused"
    assert plan["staging"]["code"]["upload"]["status"] == "reused"
    assert plan["staging"]["run_input"]["upload"]["status"] == "completed"
    assert len(persisted) == 3


def test_content_store_does_not_reuse_partial_remote_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    manifest = _manifest(tmp_path)
    cloudml_content_store.configure_staging(
        plan,
        manifest_path=manifest,
        juicefs_url=lambda subpath: f"https://juicefs.test{subpath}",
        output_subpath="/outputs/run-1",
    )
    calls: list[list[str]] = []

    def partial_hit(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        payload = (
            {"status": "ok", "exit_code": 0, "hit_count": 1}
            if "probe" in argv
            else {"status": "ok", "exit_code": 0, "files": 2}
        )
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_content_store.subprocess, "run", partial_hit)
    cloudml_content_store.upload(plan, executor_path=tmp_path / "exe", persist=lambda: None)

    assert [call[3] for call in calls] == ["probe", "upload", "probe", "upload", "upload"]


def test_content_manifest_rejects_mismatched_checksum_marker(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text())
    asset = Path(payload["staged_assets"]["archive"]["local_path"])
    Path(f"{asset}.sha256").write_text("f" * 64 + "  assets.tar.gz\n")

    with pytest.raises(ValueError, match="asset archive checksum marker"):
        cloudml_content_store.load_identity(manifest)


def test_content_store_uploads_each_cache_once_then_resumes_without_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    manifest = _manifest(tmp_path)
    cloudml_content_store.configure_staging(
        plan,
        manifest_path=manifest,
        juicefs_url=lambda subpath: f"https://juicefs.test{subpath}",
        output_subpath="/outputs/run-1",
    )
    calls: list[list[str]] = []

    def miss(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        payload = (
            {"status": "ok", "exit_code": 0, "hit_count": 0}
            if "probe" in argv
            else {"status": "ok", "exit_code": 0, "files": 2}
        )
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_content_store.subprocess, "run", miss)
    cloudml_content_store.upload(plan, executor_path=tmp_path / "exe", persist=lambda: None)
    assert [call[3] for call in calls] == ["probe", "upload", "probe", "upload", "upload"]

    resumed = _plan()
    cloudml_content_store.configure_staging(
        resumed,
        manifest_path=manifest,
        juicefs_url=lambda subpath: f"https://juicefs.test{subpath}",
        output_subpath="/outputs/run-1",
        prior_staging=plan["staging"],
    )
    resumed_calls: list[list[str]] = []
    monkeypatch.setattr(
        cloudml_content_store.subprocess,
        "run",
        lambda argv, **_kwargs: resumed_calls.append(argv),
    )
    cloudml_content_store.upload(resumed, executor_path=tmp_path / "exe", persist=lambda: None)
    assert resumed_calls == []
