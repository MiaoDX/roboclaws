from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals import cloudml_content_store

REPO_ROOT = Path(__file__).resolve().parents[3]
CLOUDML_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_cloudml.py"
CLOUDML_LIFECYCLE_PATH = (
    REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_cloudml_lifecycle.py"
)
ROWS_PATH = REPO_ROOT / "skills" / "eval-harness" / "scripts" / "eval_harness_rows.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloudml = _load_module("eval_harness_cloudml_test", CLOUDML_PATH)
cloudml_lifecycle = _load_module("eval_harness_cloudml_lifecycle_test", CLOUDML_LIFECYCLE_PATH)
rows_module = _load_module("eval_harness_rows_cloudml_test", ROWS_PATH)


def _row(
    row_id: str,
    requirements: tuple[str, ...],
    *,
    provider_profile: str = "",
    depends_on: tuple[str, ...] = (),
    packing_group: str = "",
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
        "packing_group": packing_group,
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
    asset_dir = tmp_path / "content-cache" / "asset"
    code_dir = tmp_path / "content-cache" / "code"
    asset_dir.mkdir(parents=True)
    code_dir.mkdir(parents=True)
    asset_path = asset_dir / "assets.tar.gz"
    code_path = code_dir / "code.tar.gz"
    asset_path.write_bytes(b"asset")
    code_path.write_bytes(b"code")
    Path(f"{asset_path}.sha256").write_text("c" * 64 + "  assets.tar.gz\n")
    Path(f"{code_path}.sha256").write_text("b" * 64 + "  code.tar.gz\n")
    path = tmp_path / "assets.json"
    path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_cloudml_content_manifest_v2",
                "juicefs": {"content_rel": "roboclaws-content"},
                "git": {
                    "code_commit": code_commit,
                    "code_archive": {
                        "local_path": str(code_path),
                        "name": code_path.name,
                        "sha256": "b" * 64,
                    },
                },
                "staged_assets": {
                    "archive": {
                        "local_path": str(asset_path),
                        "name": asset_path.name,
                        "sha256": "c" * 64,
                    }
                },
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


def _cml_submit_output(task_id: str) -> str:
    return (
        f"The CustomTrainJob [{task_id}](eval-shard) was created successfully\n"
        f"https://cloudml.xiaomi.com/jobs/{task_id}\n"
    )


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
    cache_scene = cache / "scenes" / "procthor-10k-val" / "20251217"
    cache_scene.mkdir(parents=True)
    cache_grasps = cache / "grasps" / "droid_objaverse" / "20251218"
    cache_grasps.mkdir(parents=True)
    (cache / "mjthor_data_type_to_source_to_versions.json").write_text(
        '{"grasps": {"droid_objaverse": ["20251218"]}, '
        '"scenes": {"procthor-10k-val": ["20251217"]}}\n',
        encoding="utf-8",
    )
    (cache_scene / "mjthor_resource_file_to_size_mb.json").write_text(
        '{"fixture": true}\n', encoding="utf-8"
    )
    (cache_grasps / "mjthor_resource_file_to_size_mb.json").write_text("{}\n", encoding="utf-8")
    return assets, cache


def _stage_fixture_assets(stage_dir: Path, assets: Path, cache: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "MLSPACES_ASSETS_DIR": str(assets),
            "MLSPACES_CACHE_DIR": str(cache),
            "ROBOCLAWS_CLOUDML_CODE_COMMIT": "HEAD",
            "ROBOCLAWS_EXECUTOR_ROOT": str(stage_dir / "missing-executor"),
            "ROBOCLAWS_STAGE_DIR": str(stage_dir),
            "ROBOCLAWS_STAGE_CONTENT_CACHE_DIR": str(stage_dir.parent / "content-cache"),
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
        "preemptible_shard_count": 0,
    }


def test_git_commit_uses_archive_marker_when_git_metadata_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "a" * 40
    (tmp_path / ".roboclaws_code_commit").write_text(commit + "\n", encoding="utf-8")
    monkeypatch.setattr(cloudml, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        cloudml.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 128, "", "not a git repo"),
    )

    assert cloudml._git_commit() == commit


def test_dependency_pair_stays_in_one_ordered_shard() -> None:
    requirements = ("gpu", "python-env", "artifact-storage", "simulator:mujoco")
    producer = _row("producer", requirements)
    consumer = _row("consumer", requirements, depends_on=("producer",))

    plan = cloudml.build_cloudml_plan(
        _manifest(producer, consumer), execution_target="cloudml", run_id="run-1"
    )

    assert len(plan["shards"]) == 1
    assert plan["shards"][0]["row_ids"] == ["producer", "consumer"]


def test_catalog_rows_expose_default_scene_identity_without_forcing_cloud_packing(
    tmp_path: Path,
) -> None:
    rows = rows_module.candidate_rows(output_dir=tmp_path, explicit_axes={})
    scene_row = next(row for row in rows if row["row_id"] == "direct-map-build-world-public")

    assert scene_row["axes"]["scene_source"] == "procthor-10k-val"
    assert scene_row["axes"]["scene_index"] == "0"
    assert scene_row["case_id"] == "direct-map-build-world-public"
    assert scene_row["case"]["scene"]["scene_id"] == "procthor-10k-val/0"
    assert scene_row["scene_group"] == "scene:procthor-10k-val/0"
    assert scene_row["packing_group"] == ""
    assert "world=molmospaces/val_0" in scene_row["command"]


def test_catalog_expands_scene_cases_and_rewrites_dependencies(tmp_path: Path) -> None:
    rows = rows_module.candidate_rows(
        output_dir=tmp_path,
        explicit_axes={},
        scenes=("procthor-10k-val/0", "procthor-objaverse-val/0"),
    )
    by_id = {row["row_id"]: row for row in rows}

    assert list(row["base_row_id"] for row in rows).count("eval-unit-tests") == 1
    first_producer = by_id["direct-map-build-world-public--scene-procthor-10k-val-0"]
    second_producer = by_id["direct-map-build-world-public--scene-procthor-objaverse-val-0"]
    second_consumer = by_id["direct-cleanup-runtime-prior-consumer--scene-procthor-objaverse-val-0"]
    assert first_producer["axes"]["world"] == "molmospaces/val_0"
    assert second_producer["axes"]["world"] == "molmospaces/procthor-objaverse-val/0"
    assert second_consumer["depends_on"] == [second_producer["row_id"]]
    suite = by_id["cleanup-capability-eval-suite--scene-procthor-objaverse-val-0"]
    assert "scene=procthor-objaverse-val/0" in suite["command"]


def test_cloudml_packs_same_scene_rows_and_preserves_dependency_order() -> None:
    requirements = ("gpu", "python-env", "artifact-storage", "simulator:mujoco")
    consumer = _row(
        "consumer",
        requirements,
        depends_on=("producer",),
        packing_group="scene:procthor-10k-val/0",
    )
    peer = _row("peer", requirements, packing_group="scene:procthor-10k-val/0")
    producer = _row("producer", requirements, packing_group="scene:procthor-10k-val/0")
    other_scene = _row("other-scene", requirements, packing_group="scene:procthor-10k-val/1")

    plan = cloudml.build_cloudml_plan(
        _manifest(consumer, peer, producer, other_scene),
        execution_target="cloudml",
        run_id="run-1",
    )

    assert [shard["row_ids"] for shard in plan["shards"]] == [
        ["peer", "producer", "consumer"],
        ["other-scene"],
    ]


def test_cloudml_keeps_independent_scene_cases_in_parallel_shards(tmp_path: Path) -> None:
    rows = rows_module.candidate_rows(
        output_dir=tmp_path,
        explicit_axes={},
        scenes=("procthor-10k-val/0", "procthor-objaverse-val/0"),
    )
    selected_ids = {
        "household-direct-world-public-product--scene-procthor-10k-val-0",
        "household-direct-world-public-product--scene-procthor-objaverse-val-0",
    }
    selected = []
    for row in rows:
        if row["row_id"] in selected_ids:
            row["selected"] = True
            row["status"] = "not_run"
            selected.append(row)

    plan = cloudml.build_cloudml_plan(
        _manifest(*selected), execution_target="cloudml", run_id="run-1"
    )

    assert len(plan["shards"]) == 2
    assert {shard["scene"]["scene_id"] for shard in plan["shards"]} == {
        "procthor-10k-val/0",
        "procthor-objaverse-val/0",
    }


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
        _manifest(internal, external),
        execution_target="auto",
        run_id="run-1",
        provider_environment={},
    )

    assert plan["local_row_ids"] == ["router", "kimi"]
    assert plan["blocked_rows"] == []


def test_cloudml_provider_row_blocks_when_required_environment_is_missing() -> None:
    row = _row(
        "router",
        ("network:internal-api-router", "provider:codex-router-responses"),
        provider_profile="codex-router-responses",
    )
    manifest = _manifest(row)

    plan = cloudml.build_cloudml_plan(
        manifest,
        execution_target="cloudml",
        run_id="run-1",
        provider_environment={},
    )
    cloudml.apply_blocked_placements(manifest, plan)

    assert plan["blocked_rows"][0]["category"] == "missing_provider_environment"
    assert row["status"] == "blocked"
    assert "CODEX_BASE_URL" in row["blockers"][0]["detail"]
    assert "CODEX_API_KEY" in row["blockers"][0]["detail"]


def test_cloudml_provider_row_uses_registry_environment_contract() -> None:
    row = _row(
        "router",
        ("network:internal-api-router", "provider:codex-router-responses"),
        provider_profile="codex-router-responses",
    )

    plan = cloudml.build_cloudml_plan(
        _manifest(row),
        execution_target="cloudml",
        run_id="run-1",
        provider_environment={
            "CODEX_BASE_URL": "https://router.example.test/v1",
            "CODEX_API_KEY": "secret-sentinel",
        },
    )

    assert plan["blocked_rows"] == []
    assert plan["shards"][0]["row_ids"] == ["router"]
    assert plan["shards"][0]["provider_env_keys"] == ["CODEX_API_KEY", "CODEX_BASE_URL"]
    assert "secret-sentinel" not in json.dumps(plan)


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
    assert payload["output_dir"].startswith("/tmp/roboclaws-cloudml/output/shards/")
    assert shard["output_scratch_path"] == payload["output_dir"]
    assert shard["output_mount_path"].startswith("/mnt/cloudml/output/shards/")
    assert shard["output_archive_name"] == "shard-output.tar"
    assert by_id["first"]["selected"] is True
    assert by_id["second"]["selected"] is False
    assert by_id["first"]["row_dir"].startswith("/tmp/roboclaws-cloudml/output/shards/")


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
        run_input_subpath="/team/evals/run-1/input",
        asset_subpath="/team/evals/assets",
        code_subpath="/team/evals/code",
        output_subpath="/team/evals/run-1/output",
    )

    argv = plan["shards"][0]["executor_argv"]
    assert argv[1:7] == ["compute", "cloudml", "cml", "--", "custom_train", "submit"]
    assert argv[argv.index("--filename") + 1] == plan["shards"][0]["yaml_path"]
    assert plan["shards"][0]["image_url"] == image
    assert plan["shards"][0]["image_digest"] == image.rsplit("@", 1)[1]
    task_yaml = json.loads(Path(plan["shards"][0]["yaml_path"]).read_text(encoding="utf-8"))
    assert task_yaml["imageConfig"]["imageUrl"] == image.rsplit("@", 1)[0]
    assert task_yaml["preemptible"] is False
    mounts = task_yaml["juiceFsMountConfigs"]
    assert mounts[0]["readOnly"] is True
    assert mounts[0]["mountPath"] == "/mnt/cloudml/input"
    assert mounts[1] == {
        "volume": "robot-intelligent-planning-data",
        "juiceFsCluster": "wlcb-cloudml",
        "subPath": "/team/evals/assets",
        "mountPath": "/mnt/cloudml/assets",
        "readOnly": True,
    }
    assert mounts[2]["readOnly"] is True
    assert mounts[2]["mountPath"] == "/mnt/cloudml/code"
    assert mounts[3]["readOnly"] is False
    assert mounts[3]["mountPath"] == "/mnt/cloudml/output"
    serialized = json.dumps(plan)
    assert "API_KEY" not in serialized
    assert "SECRET" not in serialized
    image_command = task_yaml["imageConfig"]["imageCommand"]
    assert "ROBOCLAWS_CLOUDML_REMOTE_OUTPUT_DIR" in image_command
    assert "shard-output.tar" in image_command
    assert "tar -cf" in image_command
    assert "exec /opt/roboclaws/bin/run-cloudml-eval-worker" not in image_command


def test_executor_submits_canonical_cml_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path / "harness")
    asset_manifest = _asset_manifest(tmp_path, code_commit=plan["code_commit"])
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, _cml_submit_output("task-official"), "")

    monkeypatch.setattr(cloudml.subprocess, "run", fake_run)
    cloudml.executor_submit(
        plan,
        image_urls=_image_urls(),
        asset_manifest_path=asset_manifest,
        executor_path=tmp_path / "exe",
        run_input_subpath="/input",
        asset_subpath="/assets",
        code_subpath="/code",
        output_subpath="/output",
        dry_run=False,
    )

    shard = plan["shards"][0]
    assert len(calls) == 1
    assert calls[0][1:7] == ["compute", "cloudml", "cml", "--", "custom_train", "submit"]
    assert calls[0][calls[0].index("--filename") + 1] == shard["yaml_path"]
    assert shard["task_id"] == "task-official"
    task_yaml = json.loads(Path(shard["yaml_path"]).read_text(encoding="utf-8"))
    assert task_yaml["imageConfig"]["imageUrl"] == _image_urls()["cloudml-cpu"].split("@")[0]
    assert task_yaml["juiceFsMountConfigs"][0]["readOnly"] is True
    assert task_yaml["juiceFsMountConfigs"][1]["mountPath"] == "/mnt/cloudml/assets"
    assert task_yaml["juiceFsMountConfigs"][2]["mountPath"] == "/mnt/cloudml/code"
    assert task_yaml["juiceFsMountConfigs"][3]["readOnly"] is False


def test_executor_dry_run_writes_yaml_without_submitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path / "harness")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        raise AssertionError("CloudML dry-run must not invoke executor")

    monkeypatch.setattr(cloudml.subprocess, "run", fake_run)
    cloudml.executor_dry_run(
        plan,
        image_urls=_image_urls(),
        asset_manifest_path=_asset_manifest(tmp_path, code_commit=plan["code_commit"]),
        executor_path=tmp_path / "exe",
        run_input_subpath="/input",
        asset_subpath="/assets",
        code_subpath="/code",
        output_subpath="/output",
    )

    assert calls == []
    shard = plan["shards"][0]
    assert shard["dry_run"] is True
    assert Path(shard["yaml_path"]).is_file()
    assert "--filename" in shard["executor_argv"]


def test_executor_rejects_zero_exit_without_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    cloudml.write_cloudml_plan(plan, manifest, output_dir=tmp_path / "harness")

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "account quota exceeded")

    monkeypatch.setattr(cloudml.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="account quota exceeded"):
        cloudml.executor_submit(
            plan,
            image_urls=_image_urls(),
            asset_manifest_path=_asset_manifest(tmp_path, code_commit=plan["code_commit"]),
            executor_path=tmp_path / "exe",
            run_input_subpath="/input",
            asset_subpath="/assets",
            code_subpath="/code",
            output_subpath="/output",
            dry_run=False,
        )

    assert "task_id" not in plan["shards"][0]


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
            run_input_subpath="/input",
            asset_subpath="/assets",
            code_subpath="/code",
            output_subpath="/output",
        )


def test_executor_dry_run_selects_image_per_worker_pool(tmp_path: Path) -> None:
    cpu = _row("cpu", ("cpu", "python-env", "artifact-storage"))
    gpu = _row("gpu", ("gpu", "python-env", "artifact-storage", "simulator:mujoco"))
    plan = cloudml.build_cloudml_plan(
        _manifest(cpu, gpu),
        execution_target="cloudml",
        run_id="run-1",
        preemptible=True,
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
        run_input_subpath="/input",
        asset_subpath="/assets",
        code_subpath="/code",
        output_subpath="/output",
    )

    shards = {shard["worker_pool"]: shard for shard in plan["shards"]}
    assert shards["cloudml-cpu"]["image_url"] == _image_urls()["cloudml-cpu"]
    assert shards["cloudml-r49"]["image_url"] == _image_urls()["cloudml-r49"]
    assert shards["cloudml-cpu"]["platform_image_url"] == _image_urls()["cloudml-cpu"].split("@")[0]
    assert shards["cloudml-r49"]["image_digest"] == f"sha256:{'d' * 64}"
    assert shards["cloudml-cpu"]["preemptible"] is False
    assert shards["cloudml-r49"]["preemptible"] is True
    assert plan["summary"]["preemptible_shard_count"] == 1
    cpu_yaml = json.loads(Path(shards["cloudml-cpu"]["yaml_path"]).read_text(encoding="utf-8"))
    gpu_yaml = json.loads(Path(shards["cloudml-r49"]["yaml_path"]).read_text(encoding="utf-8"))
    assert cpu_yaml["preemptible"] is False
    assert gpu_yaml["preemptible"] is True
    image_command = gpu_yaml["imageConfig"]["imageCommand"]
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
    assert plan["staging"]["run_input"]["local_dir"] == str(stage_dir)
    assert plan["staging"]["run_input"]["upload_required"] is True


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
        if "probe" in argv:
            payload = {"status": "ok", "exit_code": 0, "hit_count": 0}
        elif "upload" in argv:
            payload = {"status": "ok", "exit_code": 0, "files": 3}
        else:
            submit_index = sum("submit" in call for call in calls)
            if submit_index == 2:
                persisted = json.loads(plan_path.read_text(encoding="utf-8"))
                assert persisted["shards"][0]["task_id"] == "task-1"
            return subprocess.CompletedProcess(
                argv, 0, _cml_submit_output(f"task-{submit_index}"), ""
            )
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml.subprocess, "run", fake_run)
    monkeypatch.setattr(cloudml_content_store.subprocess, "run", fake_run)
    cloudml.executor_from_environment(plan, dry_run=False, plan_path=plan_path)

    assert [call[3] for call in calls[:5]] == ["probe", "upload", "probe", "upload", "upload"]
    assert "--no_manifest" in calls[1]
    assert calls[6][1:7] == ["compute", "cloudml", "cml", "--", "custom_train", "submit"]
    assert [shard["task_id"] for shard in plan["shards"]] == ["task-1", "task-2"]
    assert plan["staging"]["asset"]["upload_required"] is False
    assert plan["staging"]["code"]["upload_required"] is False
    assert plan["staging"]["run_input"]["upload_required"] is False
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
        if "probe" in argv:
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"status": "ok", "exit_code": 0, "hit_count": 0}), ""
            )
        if "upload" in argv:
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"status": "ok", "exit_code": 0, "files": 3}), ""
            )
        submit_calls.append(argv[argv.index("--filename") + 1])
        if len(submit_calls) == 2:
            return subprocess.CompletedProcess(argv, 1, "", "submit failed")
        return subprocess.CompletedProcess(argv, 0, _cml_submit_output("task-1"), "")

    monkeypatch.setattr(cloudml.subprocess, "run", fail_second)
    monkeypatch.setattr(cloudml_content_store.subprocess, "run", fail_second)
    with pytest.raises(RuntimeError, match="submit failed"):
        cloudml.executor_from_environment(plan, dry_run=False, plan_path=plan_path)

    resumed = json.loads(plan_path.read_text(encoding="utf-8"))
    assert resumed["shards"][0]["task_id"] == "task-1"
    resumed_calls: list[str] = []
    resumed_uploads: list[list[str]] = []

    def resume(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "probe" in argv:
            raise AssertionError("completed content cache must not be probed again")
        if "upload" in argv:
            resumed_uploads.append(argv)
            payload = {"status": "ok", "exit_code": 0, "files": 3}
        else:
            resumed_calls.append(argv[argv.index("--filename") + 1])
            return subprocess.CompletedProcess(argv, 0, _cml_submit_output("task-2"), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(cloudml.subprocess, "run", resume)
    monkeypatch.setattr(cloudml_content_store.subprocess, "run", resume)
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
    assert calls[0][1:7] == ["compute", "cloudml", "cml", "--", "custom_train", "describe"]
    assert calls[0][7] == "task-1"


def test_status_uses_canonical_cml_describe_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    harness_dir = tmp_path / "harness"
    manifest["output_dir"] = str(harness_dir)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    plan["shards"][0]["task_id"] = "task-1"
    cloudml.write_cloudml_plan(plan, manifest, output_dir=harness_dir)
    (harness_dir / "eval_harness.json").write_text(json.dumps(manifest), encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"jobId": "task-1", "state": "succeed"}), ""
        )

    monkeypatch.setattr(cloudml_lifecycle.subprocess, "run", fake_run)
    summary, _ = cloudml_lifecycle.status_cloudml_run(
        str(harness_dir), executor_path=tmp_path / "exe"
    )

    assert summary["all_succeeded"] is True
    assert len(calls) == 1
    assert calls[0][1:7] == ["compute", "cloudml", "cml", "--", "custom_train", "describe"]
    assert calls[0][7] == "task-1"


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


def test_collector_materializes_single_file_shard_archive(tmp_path: Path) -> None:
    row = _row("first", ("cpu", "python-env", "artifact-storage"))
    manifest = _manifest(row)
    plan = cloudml.build_cloudml_plan(manifest, execution_target="cloudml", run_id="run-1")
    shard = plan["shards"][0]
    shard_root = tmp_path / "shards" / shard["shard_id"]
    marker_dir = shard_root / "markers"
    marker_dir.mkdir(parents=True)
    (marker_dir / f"{shard['shard_id']}.json").write_text(
        json.dumps({"shard_id": shard["shard_id"], "status": "succeeded", "exit_code": 0})
    )
    archive_source = tmp_path / "archive-source"
    row_dir = archive_source / "rows" / "first"
    row_dir.mkdir(parents=True)
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
    with tarfile.open(shard_root / shard["output_archive_name"], "w") as archive:
        archive.add(archive_source, arcname=".")

    summary = cloudml.collect_cloudml_results(plan, manifest, collected_root=tmp_path)

    assert summary["collected_row_count"] == 1
    assert (shard_root / "rows" / "first" / "row_result.json").is_file()
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
    stage_script = (REPO_ROOT / "scripts" / "dev" / "stage_cloudml_cleanup_assets.sh").read_text(
        encoding="utf-8"
    )
    worker = (REPO_ROOT / "scripts" / "dev" / "run_cloudml_eval_worker.sh").read_text(
        encoding="utf-8"
    )

    assert "run_cloudml_eval_worker.sh /opt/roboclaws/bin/run-cloudml-eval-worker" in dockerfile
    assert "ROBOCLAWS_EVAL_EXECUTION_TARGET=cloudml" in worker
    assert 'source "$ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE"' in worker
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
    assert '"$executor_root/exe"' in stage_script
    assert "profiles/nvs/miaodongxu.yaml" not in stage_script
    assert "storage juicefs probe" in stage_script
    assert "upload_content_if_missing" in stage_script


def test_cloudml_staging_archives_are_reproducible(tmp_path: Path) -> None:
    assets, cache = _minimal_molmospaces_assets(tmp_path)

    first = _stage_fixture_assets(tmp_path / "stage-first", assets, cache)
    time.sleep(1.1)
    second = _stage_fixture_assets(tmp_path / "stage-second", assets, cache)

    assert (
        first["staged_assets"]["archive"]["sha256"] == second["staged_assets"]["archive"]["sha256"]
    )
    assert first["git"]["code_archive"]["sha256"] == second["git"]["code_archive"]["sha256"]
    assert first["local_cache"]["asset_reused"] is False
    assert second["local_cache"]["asset_reused"] is True
    assert second["local_cache"]["code_reused"] is True
    assert (
        first["staged_assets"]["archive"]["local_path"]
        == second["staged_assets"]["archive"]["local_path"]
    )
    assert first["git"]["code_archive"]["local_path"] == second["git"]["code_archive"]["local_path"]
    assert list((tmp_path / "stage-first" / "archives").iterdir()) == []
    assert list((tmp_path / "stage-second" / "archives").iterdir()) == []
    with tarfile.open(first["staged_assets"]["archive"]["local_path"], "r:gz") as archive:
        assert (
            "molmospaces/cache/scenes/procthor-10k-val/20251217/"
            "mjthor_resource_file_to_size_mb.json"
        ) in archive.getnames()
        assert (
            "molmospaces/cache/grasps/droid_objaverse/20251218/mjthor_resource_file_to_size_mb.json"
        ) in archive.getnames()


def test_cloudml_staging_invalidates_cache_when_archived_asset_changes(tmp_path: Path) -> None:
    assets, cache = _minimal_molmospaces_assets(tmp_path)

    first = _stage_fixture_assets(tmp_path / "stage-first", assets, cache)
    (assets / "scenes/procthor-10k-val/val_0_assets/mesh.obj").write_text(
        "changed mesh fixture\n", encoding="utf-8"
    )
    second = _stage_fixture_assets(tmp_path / "stage-second", assets, cache)

    assert second["local_cache"]["asset_reused"] is False
    assert (
        first["local_cache"]["asset_source_fingerprint"]
        != second["local_cache"]["asset_source_fingerprint"]
    )
    assert (
        first["staged_assets"]["archive"]["sha256"] != second["staged_assets"]["archive"]["sha256"]
    )
