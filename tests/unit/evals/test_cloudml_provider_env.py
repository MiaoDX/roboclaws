from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals import cloudml_provider_env

REPO_ROOT = Path(__file__).resolve().parents[3]
CLOUDML_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_cloudml.py"


def _load_cloudml_module():
    spec = importlib.util.spec_from_file_location(
        "eval_harness_cloudml_provider_test", CLOUDML_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloudml = _load_cloudml_module()


def _row() -> dict[str, Any]:
    return {
        "row_id": "router",
        "row_kind": "live_agent_eval",
        "selected": True,
        "status": "not_run",
        "outcome": "",
        "requirement": "required",
        "execution_requirements": [
            "gpu",
            "python-env",
            "artifact-storage",
            "openai-agents-sdk",
            "network:internal-api-router",
            "provider:codex-router-responses",
        ],
        "depends_on": [],
        "timeout_s": 30,
        "axes": {"provider_profile": "codex-router-responses"},
        "row_dir": "/local/harness/rows/router",
        "command": ["tool", "output_dir=/local/harness/evals/router"],
        "command_display": "tool output_dir=/local/harness/evals/router",
    }


def _manifest(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "budget": "focused",
        "profile": "adaptive",
        "signals": [],
        "output_dir": "/local/harness",
        "rows": [row],
    }


def _asset_manifest(tmp_path: Path, *, code_commit: str) -> Path:
    path = tmp_path / "assets.json"
    path.write_text(
        json.dumps(
            {
                "juicefs": {"input_rel": "roboclaws-assets/test"},
                "git": {
                    "code_commit": code_commit,
                    "code_archive": {"name": "code.tar.gz", "sha256": "b" * 64},
                },
                "staged_assets": {"archive": {"name": "assets.tar.gz", "sha256": "c" * 64}},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_mimo_inside_environment_contract_comes_from_registry() -> None:
    assert cloudml_provider_env.required_env_keys("mimo-inside-openai-chat") == (
        "MIMO_BASE_URL",
        "MIMO_API_KEY",
    )


def test_provider_environment_loads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "CODEX_BASE_URL=https://router.example.test/v1\nCODEX_API_KEY=secret-sentinel\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROBOCLAWS_PROVIDER_ENV_FILE", str(dotenv))
    monkeypatch.delenv("CODEX_BASE_URL", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)

    loaded = cloudml_provider_env.load_environment(REPO_ROOT)

    assert loaded["CODEX_BASE_URL"] == "https://router.example.test/v1"
    assert loaded["CODEX_API_KEY"] == "secret-sentinel"


def test_provider_environment_is_scoped_uploaded_mounted_and_not_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = "secret value with 'quotes'"
    provider_env = {
        "CODEX_BASE_URL": "https://router.example.test/v1",
        "CODEX_API_KEY": sentinel,
    }
    row = _row()
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(
        manifest,
        execution_target="cloudml",
        run_id="run-1",
        provider_environment=provider_env,
    )
    plan_path = cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path / "harness")
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    asset_manifest = _asset_manifest(stage_dir, code_commit=plan["code_commit"])
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_ASSET_MANIFEST", str(asset_manifest))
    monkeypatch.setenv(
        "ROBOCLAWS_CLOUDML_GPU_IMAGE_URL",
        f"micr.cloud.mioffice.cn/team/roboclaws-cuda:test@sha256:{'d' * 64}",
    )
    for key, value in provider_env.items():
        monkeypatch.setenv(key, value)
    calls: list[list[str]] = []
    provider_local_dir: Path | None = None
    real_run = subprocess.run

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal provider_local_dir
        calls.append(argv)
        if "upload" in argv:
            url = argv[argv.index("--url") + 1]
            if "executor_cloudml_provider_env" in url:
                provider_local_dir = Path(argv[argv.index("--local_dir") + 1])
                env_path = provider_local_dir / "provider.env"
                assert env_path.stat().st_mode & 0o777 == 0o600
                shell = real_run(
                    ["bash", "-c", f"set -a; source {env_path}; env"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                assert f"CODEX_API_KEY={sentinel}" in shell
            payload = {"status": "ok", "exit_code": 0, "files": 1}
        else:
            payload = {"task_id": "task-1", "job_id": "task-1", "dry_run": False}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_provider_env.subprocess, "run", fake_run)
    cloudml.executor_from_environment(plan, dry_run=False, plan_path=plan_path)

    assert provider_local_dir is not None
    assert not provider_local_dir.exists()
    argv = plan["shards"][0]["executor_argv"]
    mounts = json.loads(argv[argv.index("--juicefs_mount_configs") + 1])
    assert mounts[2]["mountPath"] == "/mnt/cloudml/provider-env"
    assert mounts[2]["readOnly"] is True
    image_command = argv[argv.index("--image_command") + 1]
    assert "ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE" in image_command
    assert "source /mnt/cloudml/provider-env/provider.env" in image_command
    assert sentinel not in json.dumps(plan)
    assert sentinel not in json.dumps(calls)
