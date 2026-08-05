from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from roboclaws.evals.candidate_isolation_probe import ProbeManifest, main, run_probe


def _scrub_sensitive_environment(monkeypatch) -> None:
    for key in tuple(os.environ):
        if any(
            token in key.upper() for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        ):
            monkeypatch.delenv(key, raising=False)


def _manifest(tmp_path: Path) -> ProbeManifest:
    approved = tmp_path / "approved"
    approved.mkdir()
    (approved / "public.txt").write_text("public", encoding="utf-8")
    forbidden = tmp_path / "private"
    forbidden.mkdir()
    (forbidden / "truth.txt").write_text("private", encoding="utf-8")
    return ProbeManifest(
        approved_read_roots=(approved,),
        output_root=tmp_path / "output",
        forbidden_paths=(forbidden / "truth.txt", tmp_path / "durable" / "artifact.json"),
        network_targets=(("127.0.0.1", 9),),
        expected_env_absent=("ROBOCLAWS_TEST_PROVIDER_TOKEN",),
    )


def test_probe_fails_when_private_path_is_visible(tmp_path: Path) -> None:
    result = run_probe(_manifest(tmp_path))
    assert result["ok"] is False
    assert result["checks"]["forbidden_paths_unreadable"] is False
    assert result["checks"]["subprocess_private_read_denied"] is False
    assert result["checks"]["forbidden_writes_denied"] is False


def test_probe_passes_when_private_paths_are_not_mounted(tmp_path: Path, monkeypatch) -> None:
    _scrub_sensitive_environment(monkeypatch)
    manifest = ProbeManifest(
        approved_read_roots=(tmp_path / "approved",),
        output_root=tmp_path / "output",
        forbidden_paths=(tmp_path / "missing" / "truth.json",),
        network_targets=(("127.0.0.1", 9),),
        expected_env_absent=("ROBOCLAWS_TEST_PROVIDER_TOKEN",),
    )
    manifest.approved_read_roots[0].mkdir()
    (manifest.approved_read_roots[0] / "public.txt").write_text("public", encoding="utf-8")
    result = run_probe(manifest)
    assert result["ok"] is True
    assert all(result["checks"].values())


def test_manifest_rejects_relative_or_output_forbidden_paths(tmp_path: Path) -> None:
    payload = {
        "schema": "candidate_isolation_probe_manifest_v1",
        "approved_read_roots": ["approved"],
        "output_root": str(tmp_path / "output"),
        "forbidden_paths": [],
        "network_targets": [],
        "expected_env_absent": [],
    }
    try:
        ProbeManifest.from_mapping(payload)
    except ValueError as exc:
        assert "absolute" in str(exc)
    else:
        raise AssertionError("relative path was accepted")


def test_cloudml_probe_image_is_pinned_and_minimal() -> None:
    dockerfile = Path("docker/eval-evolution-isolation/Dockerfile").read_text(encoding="utf-8")
    assert "FROM python@sha256:" in dockerfile
    assert "COPY candidate_isolation_probe.py" in dockerfile
    assert "COPY ." not in dockerfile
    assert "candidate-isolation-probe.py" in dockerfile


def test_supervisor_rejects_unknown_placement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setenv("ROBOCLAWS_ISOLATION_PLACEMENT", "unknown")
    try:
        from roboclaws.evals.candidate_isolation_probe import run_supervised_probe

        run_supervised_probe(
            work_root=tmp_path / "work",
            durable_output=tmp_path / "output" / "result.json",
        )
    except ValueError as exc:
        assert "placement" in str(exc)
    else:
        raise AssertionError("unknown placement was accepted")


def test_cli_result_is_json_without_private_content(tmp_path: Path, monkeypatch) -> None:
    _scrub_sensitive_environment(monkeypatch)
    manifest = ProbeManifest(
        approved_read_roots=(tmp_path / "approved",),
        output_root=tmp_path / "output",
        forbidden_paths=(tmp_path / "missing" / "artifact.json",),
        network_targets=(("127.0.0.1", 9),),
        expected_env_absent=("ROBOCLAWS_TEST_PROVIDER_TOKEN",),
    )
    manifest.approved_read_roots[0].mkdir()
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "result.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "candidate_isolation_probe_manifest_v1",
                "approved_read_roots": [str(path) for path in manifest.approved_read_roots],
                "output_root": str(manifest.output_root),
                "forbidden_paths": [str(path) for path in manifest.forbidden_paths],
                "network_targets": [
                    {"host": host, "port": port} for host, port in manifest.network_targets
                ],
                "expected_env_absent": list(manifest.expected_env_absent),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candidate-isolation-probe",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ],
    )
    assert main() == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["schema"] == "candidate_isolation_probe_result_v1"
    rendered = json.dumps(result)
    assert str(manifest.forbidden_paths[0]) not in rendered
    assert "private-content" not in rendered
    assert sys.version_info >= (3, 12)
