from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLOUDML_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_cloudml.py"
CLOUDML_LIFECYCLE_PATH = (
    REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_cloudml_lifecycle.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloudml = _load_module("eval_harness_cloudml_test", CLOUDML_PATH)
cloudml_lifecycle = _load_module("eval_harness_cloudml_lifecycle_test", CLOUDML_LIFECYCLE_PATH)


def _row(
    row_id: str,
    requirements: tuple[str, ...],
    *,
    provider_profile: str = "",
    depends_on: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "schema": "roboclaws_eval_harness_row_v1",
        "row_id": row_id,
        "row_kind": "test",
        "selected": True,
        "status": "not_run",
        "outcome": "",
        "requirement": "required",
        "execution_requirements": list(requirements),
        "depends_on": list(depends_on),
        "timeout_s": 30,
        "axes": {"provider_profile": provider_profile},
        "row_dir": f"/local/harness/rows/{row_id}",
        "command": ["tool", f"output_dir=/local/harness/evals/{row_id}"],
        "command_display": f"tool output_dir=/local/harness/evals/{row_id}",
    }


def _manifest(*rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "roboclaws_eval_harness_manifest_v1",
        "mode": "execute",
        "budget": "focused",
        "profile": "adaptive",
        "signals": [],
        "summary": {"selected_row_count": len(rows)},
        "output_dir": "/local/harness",
        "rows": list(rows),
    }


def _asset_manifest(tmp_path: Path, *, code_commit: str = "a" * 40) -> Path:
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


def _image_urls() -> dict[str, str]:
    return {
        "cloudml-cpu": (f"micr.cloud.mioffice.cn/team/roboclaws-cpu:commit-abc@sha256:{'c' * 64}"),
        "cloudml-r49": (f"micr.cloud.mioffice.cn/team/roboclaws-cuda:commit-abc@sha256:{'d' * 64}"),
    }


def _set_image_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    images = _image_urls()
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_CPU_IMAGE_URL", images["cloudml-cpu"])
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_GPU_IMAGE_URL", images["cloudml-r49"])


def _minimal_molmospaces_assets(tmp_path: Path) -> tuple[Path, Path]:
    assets = tmp_path / "assets"
    cache = tmp_path / "cache"
    files = (
        "scenes/procthor-10k-val/val_0.xml",
        "scenes/procthor-10k-val/val_0.json",
        "scenes/procthor-10k-val/val_0_metadata.json",
        "scenes/procthor-10k-val/val_0_ceiling.xml",
        "scenes/procthor-10k-val/val_0_assets/mesh.obj",
        "scenes/procthor-10k-val/mjthor_resources_combined_meta.json.gz",
        "scenes/procthor-10k-val/mjthor_resource_file_to_size_mb.json",
        "scenes/procthor-10k-val/.procthor-10k-val_val_0.tar.zst_complete_links",
        "objects/thor/object.txt",
        "robots/rby1m/robot.txt",
        "mjthor_data_type_to_source_to_versions.json",
    )
    for relative in files:
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture:{relative}\n", encoding="utf-8")
    cache.mkdir()
    (cache / "mjthor_data_type_to_source_to_versions.json").write_text(
        '{"fixture": true}\n', encoding="utf-8"
    )
    return assets, cache


def _stage_fixture_assets(stage_dir: Path, assets: Path, cache: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "MLSPACES_ASSETS_DIR": str(assets),
            "MLSPACES_CACHE_DIR": str(cache),
            "ROBOCLAWS_CLOUDML_CODE_COMMIT": "HEAD",
            "ROBOCLAWS_STAGE_DIR": str(stage_dir),
            "ROBOCLAWS_STAGE_RUN_UPLOAD_DRY_RUN": "false",
            "ROBOCLAWS_STAGE_RUN_UPLOAD": "false",
        }
    )
    subprocess.run(
        [str(REPO_ROOT / "scripts" / "dev" / "stage_cloudml_cleanup_assets.sh")],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads((stage_dir / "roboclaws_cloudml_cleanup_assets.json").read_text())


def test_cloudml_plan_uses_cpu_and_r49_capability_pools() -> None:
    deterministic = _row("deterministic", ("cpu", "python-env", "artifact-storage"))
    simulator = _row(
        "simulator",
        ("gpu", "python-env", "artifact-storage", "simulator:mujoco"),
    )

    plan = cloudml.build_cloudml_plan(
        _manifest(deterministic, simulator), execution_target="cloudml", run_id="run-1"
    )

    assert [(shard["worker_pool"], shard["row_ids"]) for shard in plan["shards"]] == [
        ("cloudml-cpu", ["deterministic"]),
        ("cloudml-r49", ["simulator"]),
    ]
    assert plan["summary"] == {
        "selected_row_count": 2,
        "cloudml_row_count": 2,
        "local_row_count": 0,
        "blocked_row_count": 0,
        "shard_count": 2,
    }


def test_dependency_pair_stays_in_one_ordered_shard() -> None:
    requirements = ("gpu", "python-env", "artifact-storage", "simulator:mujoco")
    producer = _row("producer", requirements)
    consumer = _row("consumer", requirements, depends_on=("producer",))

    plan = cloudml.build_cloudml_plan(
        _manifest(producer, consumer), execution_target="cloudml", run_id="run-1"
    )

    assert len(plan["shards"]) == 1
    assert plan["shards"][0]["row_ids"] == ["producer", "consumer"]


def test_cloudml_run_id_rejects_path_components() -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))

    with pytest.raises(ValueError, match="CloudML run id"):
        cloudml.build_cloudml_plan(_manifest(row), execution_target="cloudml", run_id="../escape")


def test_auto_keeps_provider_rows_on_local_network_pool() -> None:
    internal = _row(
        "router",
        (
            "gpu",
            "python-env",
            "artifact-storage",
            "simulator:mujoco",
            "network:internal-api-router",
            "provider:codex-router-responses",
        ),
        provider_profile="codex-router-responses",
    )
    external = _row(
        "kimi",
        ("network:external-egress", "provider:kimi-openai-chat"),
        provider_profile="kimi-openai-chat",
    )

    plan = cloudml.build_cloudml_plan(
        _manifest(internal, external), execution_target="auto", run_id="run-1"
    )

    assert plan["local_row_ids"] == ["router", "kimi"]
    assert plan["blocked_rows"] == []


def test_cloudml_provider_row_blocks_without_secure_secret_reference() -> None:
    row = _row(
        "router",
        ("network:internal-api-router", "provider:codex-router-responses"),
        provider_profile="codex-router-responses",
    )
    manifest = _manifest(row)

    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    cloudml.apply_blocked_placements(manifest, plan)

    assert plan["blocked_rows"][0]["category"] == "secure_secret_injection_unavailable"
    assert row["status"] == "blocked"
    assert "secret-reference" in row["blockers"][0]["detail"]


def test_frozen_shard_manifest_relocates_only_selected_rows(tmp_path: Path) -> None:
    first = _row("first", ("cpu", "python-env", "artifact-storage"))
    second = _row("second", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(first, second)
    plan = cloudml.build_cloudml_plan(
        manifest, execution_target="cloudml", row_ids=["first"], run_id="run-1"
    )

    cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path)

    shard = plan["shards"][0]
    payload = json.loads(Path(shard["manifest_local_path"]).read_text(encoding="utf-8"))
    by_id = {row["row_id"]: row for row in payload["rows"]}
    assert payload["output_dir"].startswith("/mnt/cloudml/output/shards/")
    assert by_id["first"]["selected"] is True
    assert by_id["second"]["selected"] is False
    assert by_id["first"]["row_dir"].startswith("/mnt/cloudml/output/shards/")


def test_executor_dry_run_uses_current_target_pinned_inputs_and_safe_mounts(
    tmp_path: Path,
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path)
    executor = tmp_path / "exe"
    executor.write_text(
        '#!/usr/bin/env bash\necho \'{"dry_run":true,"yaml_path":"/tmp/task.yaml"}\'\n',
        encoding="utf-8",
    )
    executor.chmod(0o755)
    image = _image_urls()["cloudml-cpu"]

    cloudml.executor_dry_run(
        plan,
        image_urls=_image_urls(),
        asset_manifest_path=_asset_manifest(tmp_path, code_commit=plan["code_commit"]),
        executor_path=executor,
        input_subpath="/team/evals/run-1/input",
        output_subpath="/team/evals/run-1/output",
    )

    argv = plan["shards"][0]["executor_argv"]
    assert argv[1:5] == ["compute", "cloudml", "custom_train", "submit"]
    assert argv[argv.index("--dry_run") + 1] == "true"
    assert argv[argv.index("--image_url") + 1] == image.rsplit("@", 1)[0]
    assert plan["shards"][0]["image_url"] == image
    assert plan["shards"][0]["image_digest"] == image.rsplit("@", 1)[1]
    mounts = json.loads(argv[argv.index("--juicefs_mount_configs") + 1])
    assert mounts[0]["readOnly"] is True
    assert mounts[0]["mountPath"] == "/mnt/cloudml/input"
    assert mounts[1]["readOnly"] is False
    assert mounts[1]["mountPath"] == "/mnt/cloudml/output"
    serialized = json.dumps(plan)
    assert "API_KEY" not in serialized
    assert "SECRET" not in serialized


@pytest.mark.parametrize(
    "image",
    [
        "micr.cloud.mioffice.cn/team/roboclaws:latest",
        f"micr.cloud.mioffice.cn/team/roboclaws:latest@sha256:{'c' * 64}",
        f"micr.cloud.mioffice.cn/team/roboclaws@sha256:{'c' * 64}",
    ],
)
def test_executor_dry_run_rejects_unpinned_image(tmp_path: Path, image: str) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    plan = cloudml.build_cloudml_plan(_manifest(row), execution_target="cloudml", run_id="run-1")

    with pytest.raises(ValueError, match="immutable.*tag plus sha256"):
        cloudml.executor_dry_run(
            plan,
            image_urls={"cloudml-cpu": image},
            asset_manifest_path=_asset_manifest(tmp_path, code_commit=plan["code_commit"]),
            executor_path=tmp_path / "exe",
            input_subpath="/input",
            output_subpath="/output",
        )


def test_executor_dry_run_selects_image_per_worker_pool(tmp_path: Path) -> None:
    cpu = _row("cpu", ("cpu", "python-env", "artifact-storage"))
    gpu = _row("gpu", ("gpu", "python-env", "artifact-storage", "simulator:mujoco"))
    plan = cloudml.build_cloudml_plan(
        _manifest(cpu, gpu), execution_target="cloudml", run_id="run-1"
    )
    cloudml.write_cloudml_plan(plan, _manifest(cpu, gpu), output_dir=tmp_path)
    executor = tmp_path / "exe"
    executor.write_text(
        '#!/usr/bin/env bash\necho \'{"dry_run":true,"yaml_path":"/tmp/task.yaml"}\'\n',
        encoding="utf-8",
    )
    executor.chmod(0o755)

    cloudml.executor_dry_run(
        plan,
        image_urls=_image_urls(),
        asset_manifest_path=_asset_manifest(tmp_path, code_commit=plan["code_commit"]),
        executor_path=executor,
        input_subpath="/input",
        output_subpath="/output",
    )

    shards = {shard["worker_pool"]: shard for shard in plan["shards"]}
    assert shards["cloudml-cpu"]["image_url"] == _image_urls()["cloudml-cpu"]
    assert shards["cloudml-r49"]["image_url"] == _image_urls()["cloudml-r49"]
    assert shards["cloudml-cpu"]["platform_image_url"] == _image_urls()["cloudml-cpu"].split("@")[0]
    assert shards["cloudml-r49"]["image_digest"] == f"sha256:{'d' * 64}"
    gpu_command = shards["cloudml-r49"]["executor_argv"]
    image_command = gpu_command[gpu_command.index("--image_command") + 1]
    assert "VISUAL_GROUNDING_DEVICE=cuda" in image_command
    assert "VISUAL_GROUNDING_TORCH_DTYPE=auto" in image_command


def test_environment_requires_only_images_for_selected_pools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    plan = cloudml.build_cloudml_plan(_manifest(row), execution_target="cloudml", run_id="run-1")
    asset_manifest = _asset_manifest(tmp_path, code_commit=plan["code_commit"])
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_ASSET_MANIFEST", str(asset_manifest))
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_IMAGE_URL", _image_urls()["cloudml-cpu"])

    with pytest.raises(ValueError, match="ROBOCLAWS_CLOUDML_CPU_IMAGE_URL"):
        cloudml.executor_dry_run_from_environment(plan)


def test_environment_dry_run_stages_worker_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path / "harness")
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    asset_manifest = _asset_manifest(stage_dir, code_commit=plan["code_commit"])
    executor = tmp_path / "exe"
    executor.write_text(
        '#!/usr/bin/env bash\necho \'{"dry_run":true,"yaml_path":"/tmp/task.yaml"}\'\n',
        encoding="utf-8",
    )
    executor.chmod(0o755)
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_CPU_IMAGE_URL", _image_urls()["cloudml-cpu"])
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_ASSET_MANIFEST", str(asset_manifest))
    monkeypatch.setenv("ROBOCLAWS_EXECUTOR_PATH", str(executor))

    cloudml.executor_dry_run_from_environment(plan)

    assert (stage_dir / "manifests" / "run-1-cpu-001.json").is_file()
    assert plan["staging"]["local_dir"] == str(stage_dir)
    assert plan["staging"]["upload_required"] is True


def test_real_submit_uploads_first_and_persists_each_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpu = _row("cpu", ("cpu", "python-env", "artifact-storage"))
    gpu = _row("gpu", ("gpu", "python-env", "artifact-storage", "simulator:mujoco"))
    manifest = _manifest(cpu, gpu)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    harness_dir = tmp_path / "harness"
    plan_path = cloudml.write_cloudml_plan(plan, manifest, output_dir=harness_dir)
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    asset_manifest = _asset_manifest(stage_dir, code_commit=plan["code_commit"])
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_ASSET_MANIFEST", str(asset_manifest))
    _set_image_environment(monkeypatch)
    monkeypatch.setenv("CODEX_API_KEY", "do-not-leak")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "upload" in argv:
            payload = {"status": "ok", "exit_code": 0, "files": 3}
        else:
            submit_index = sum("submit" in call for call in calls)
            if submit_index == 2:
                persisted = json.loads(plan_path.read_text(encoding="utf-8"))
                assert persisted["shards"][0]["task_id"] == "task-1"
            payload = {
                "task_id": f"task-{submit_index}",
                "job_id": f"task-{submit_index}",
                "console_url": f"https://cloudml/jobs/task-{submit_index}",
                "yaml_path": "/tmp/task.yaml",
                "dry_run": False,
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml.subprocess, "run", fake_run)
    cloudml.executor_from_environment(plan, dry_run=False, plan_path=plan_path)

    assert calls[0][1:4] == ["storage", "juicefs", "upload"]
    assert calls[1][1:4] == ["storage", "juicefs", "upload"]
    assert "--no_manifest" in calls[1]
    assert calls[2][1:5] == ["compute", "cloudml", "custom_train", "submit"]
    assert [shard["task_id"] for shard in plan["shards"]] == ["task-1", "task-2"]
    assert plan["staging"]["upload_required"] is False
    assert plan["staging"]["output_init"]["status"] == "completed"
    assert "do-not-leak" not in json.dumps(plan)


def test_partial_submit_plan_resumes_without_resubmitting_completed_shard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpu = _row("cpu", ("cpu", "python-env", "artifact-storage"))
    gpu = _row("gpu", ("gpu", "python-env", "artifact-storage", "simulator:mujoco"))
    manifest = _manifest(cpu, gpu)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    plan_path = cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path / "harness")
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    asset_manifest = _asset_manifest(stage_dir, code_commit=plan["code_commit"])
    monkeypatch.setenv("ROBOCLAWS_CLOUDML_ASSET_MANIFEST", str(asset_manifest))
    _set_image_environment(monkeypatch)
    submit_calls: list[str] = []

    def fail_second(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "upload" in argv:
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"status": "ok", "exit_code": 0, "files": 3}), ""
            )
        submit_calls.append(argv[argv.index("--job_name") + 1])
        if len(submit_calls) == 2:
            return subprocess.CompletedProcess(argv, 1, "", "submit failed")
        payload = {"task_id": "task-1", "job_id": "task-1", "dry_run": False}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml.subprocess, "run", fail_second)
    with pytest.raises(RuntimeError, match="submit failed"):
        cloudml.executor_from_environment(plan, dry_run=False, plan_path=plan_path)

    resumed = json.loads(plan_path.read_text(encoding="utf-8"))
    assert resumed["shards"][0]["task_id"] == "task-1"
    resumed_calls: list[str] = []
    resumed_uploads: list[list[str]] = []

    def resume(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "upload" in argv:
            resumed_uploads.append(argv)
            payload = {"status": "ok", "exit_code": 0, "files": 3}
        else:
            resumed_calls.append(argv[argv.index("--job_name") + 1])
            payload = {"task_id": "task-2", "job_id": "task-2", "dry_run": False}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml.subprocess, "run", resume)
    cloudml.executor_from_environment(resumed, dry_run=False, plan_path=plan_path)

    assert len(resumed_calls) == 1
    assert resumed_uploads == []
    assert resumed["shards"][1]["task_id"] == "task-2"


def test_status_normalizes_terminal_cloudml_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    harness_dir = tmp_path / "harness"
    manifest["output_dir"] = str(harness_dir)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    plan["shards"][0]["task_id"] = "task-1"
    plan_path = cloudml.write_cloudml_plan(plan, manifest, output_dir=harness_dir)
    (harness_dir / "eval_harness.json").write_text(json.dumps(manifest), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        payload = {"jobId": "task-1", "state": "Successful"}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_lifecycle.subprocess, "run", fake_run)
    summary, resolved_path = cloudml_lifecycle.status_cloudml_run(
        str(harness_dir), executor_path=tmp_path / "exe"
    )

    assert resolved_path == plan_path.resolve()
    assert summary["all_terminal"] is True
    assert summary["all_succeeded"] is True
    assert calls[0][1:5] == ["compute", "cloudml", "custom_train", "describe"]
    assert calls[0][calls[0].index("--job_id") + 1] == "task-1"


def test_status_does_not_treat_partial_submission_as_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpu = _row("cpu", ("cpu", "python-env", "artifact-storage"))
    gpu = _row("gpu", ("gpu", "python-env", "artifact-storage", "simulator:mujoco"))
    manifest = _manifest(cpu, gpu)
    harness_dir = tmp_path / "harness"
    manifest["output_dir"] = str(harness_dir)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    plan["shards"][0]["task_id"] = "task-1"
    cloudml.write_cloudml_plan(plan, manifest, output_dir=harness_dir)
    (harness_dir / "eval_harness.json").write_text(json.dumps(manifest), encoding="utf-8")

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        payload = {"jobId": "task-1", "state": "succeed"}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_lifecycle.subprocess, "run", fake_run)
    summary, _ = cloudml_lifecycle.status_cloudml_run(
        str(harness_dir), executor_path=tmp_path / "exe"
    )

    assert summary["terminal_shard_count"] == 1
    assert summary["all_terminal"] is False
    assert summary["shards"][1]["status"] == "not_submitted"


def test_collect_downloads_and_merges_terminal_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    harness_dir = tmp_path / "harness"
    manifest["output_dir"] = str(harness_dir)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    shard = plan["shards"][0]
    shard["task_id"] = "task-1"
    plan["staging"] = {"output_url": "https://cloud.mioffice.cn/juicefs/vol-detail?run=1"}
    plan_path = cloudml.write_cloudml_plan(plan, manifest, output_dir=harness_dir)
    (harness_dir / "eval_harness.json").write_text(json.dumps(manifest), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if "describe" in argv:
            payload: Any = {"jobId": "task-1", "state": "succeed"}
        else:
            collected_root = Path(argv[argv.index("--output_dir") + 1])
            shard_root = collected_root / "shards" / shard["shard_id"]
            (shard_root / "markers").mkdir(parents=True)
            (shard_root / "rows" / "first").mkdir(parents=True)
            (shard_root / "markers" / f"{shard['shard_id']}.json").write_text(
                json.dumps({"shard_id": shard["shard_id"], "status": "succeeded", "exit_code": 0}),
                encoding="utf-8",
            )
            (shard_root / "rows" / "first" / "row_result.json").write_text(
                json.dumps(
                    {
                        **row,
                        "status": "ran",
                        "outcome": "passed",
                        "execution_target": "cloudml",
                        "shard_id": shard["shard_id"],
                    }
                ),
                encoding="utf-8",
            )
            payload = {"status": "ok", "exit_code": 0, "files": 2}
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml_lifecycle.subprocess, "run", fake_run)
    collected_plan, collected_manifest, resolved_path = cloudml_lifecycle.collect_cloudml_run(
        cloudml, str(harness_dir), executor_path=tmp_path / "exe"
    )

    assert resolved_path == plan_path.resolve()
    assert calls[1][1:4] == ["storage", "juicefs", "download"]
    assert collected_plan["collection"]["collected_row_count"] == 1
    assert collected_manifest["rows"][0]["outcome"] == "passed"


def test_collector_merges_remote_results_idempotently(tmp_path: Path) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    shard = plan["shards"][0]
    shard_root = tmp_path / "shards" / shard["shard_id"]
    marker_dir = shard_root / "markers"
    row_dir = shard_root / "rows" / "first"
    marker_dir.mkdir(parents=True)
    row_dir.mkdir(parents=True)
    (marker_dir / f"{shard['shard_id']}.json").write_text(
        json.dumps({"shard_id": shard["shard_id"], "status": "succeeded", "exit_code": 0})
    )
    (row_dir / "row_result.json").write_text(
        json.dumps(
            {
                **row,
                "status": "ran",
                "outcome": "passed",
                "execution_target": "cloudml",
                "worker_pool": "cloudml-cpu",
                "shard_id": shard["shard_id"],
            }
        )
    )

    first = cloudml.collect_cloudml_results(plan, manifest, collected_root=tmp_path)
    second = cloudml.collect_cloudml_results(plan, manifest, collected_root=tmp_path)

    assert (
        first
        == second
        == {
            "collected_row_count": 1,
            "failed_shard_count": 0,
            "missing_result_count": 0,
        }
    )
    assert row["outcome"] == "passed"


def test_collector_rejects_mismatched_marker_identity(tmp_path: Path) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    shard = plan["shards"][0]
    marker_dir = tmp_path / "shards" / shard["shard_id"] / "markers"
    marker_dir.mkdir(parents=True)
    (marker_dir / f"{shard['shard_id']}.json").write_text(
        json.dumps({"shard_id": "wrong", "status": "succeeded", "exit_code": 0})
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        cloudml.collect_cloudml_results(plan, manifest, collected_root=tmp_path)


def test_eval_image_contains_cloudml_worker_entrypoint() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile.eval").read_text(encoding="utf-8")
    build_script = (REPO_ROOT / "scripts" / "dev" / "build_push_eval_image.sh").read_text(
        encoding="utf-8"
    )
    worker = (REPO_ROOT / "scripts" / "dev" / "run_cloudml_eval_worker.sh").read_text(
        encoding="utf-8"
    )

    assert "run_cloudml_eval_worker.sh /opt/roboclaws/bin/run-cloudml-eval-worker" in dockerfile
    assert "ROBOCLAWS_EVAL_EXECUTION_TARGET=cloudml" in worker
    assert '"$ROBOCLAWS_CLOUDML_ASSET_MANIFEST"' in worker
    assert '"$ROBOCLAWS_CLOUDML_ASSET_MANIFEST_SHA256"' in worker
    assert "EVAL_IMAGE_VARIANT" in dockerfile
    assert dockerfile.index("RUN uv sync --extra dev") < dockerfile.index("ARG EVAL_IMAGE_VARIANT")
    assert "--extra cuda --frozen" in dockerfile
    assert "VISUAL_GROUNDING_DINO_MODEL_REVISION" in dockerfile
    assert "from=grounding-dino-cache" in dockerfile
    assert "model.safetensors" in worker
    assert '"VISUAL_GROUNDING_DINO_MODEL_REVISION"' in worker
    assert "torch.cuda.is_available()" in worker
    assert "just agent::eval execute" in worker
    assert "ROBOCLAWS_EVAL_DINO_CACHE_DIR" in build_script
    assert '--build-context "grounding-dino-cache=$dino_cache_dir"' in build_script


def test_cloudml_staging_archives_are_reproducible(tmp_path: Path) -> None:
    assets, cache = _minimal_molmospaces_assets(tmp_path)

    first = _stage_fixture_assets(tmp_path / "stage-first", assets, cache)
    time.sleep(1.1)
    second = _stage_fixture_assets(tmp_path / "stage-second", assets, cache)

    assert (
        first["staged_assets"]["archive"]["sha256"] == second["staged_assets"]["archive"]["sha256"]
    )
    assert first["git"]["code_archive"]["sha256"] == second["git"]["code_archive"]["sha256"]
