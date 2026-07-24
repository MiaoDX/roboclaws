from __future__ import annotations

import shlex
import subprocess
import tarfile
from pathlib import Path

from roboclaws.evals import cloudml_task


def test_image_command_publishes_archive_and_preserves_worker_exit(tmp_path: Path) -> None:
    scratch_path = tmp_path / "scratch"
    remote_path = tmp_path / "remote"
    shard_id = "shell-publish-proof"
    worker_path = tmp_path / "worker"
    worker_path.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'mkdir -p "$ROBOCLAWS_CLOUDML_OUTPUT_DIR/markers" '
        '"$ROBOCLAWS_CLOUDML_OUTPUT_DIR/rows/first"\n'
        'printf \'{"shard_id":"%s"}\\n\' "$ROBOCLAWS_CLOUDML_SHARD_ID" '
        '> "$ROBOCLAWS_CLOUDML_OUTPUT_DIR/markers/$ROBOCLAWS_CLOUDML_SHARD_ID.json"\n'
        "printf 'result\\n' > \"$ROBOCLAWS_CLOUDML_OUTPUT_DIR/rows/first/result.txt\"\n"
        "exit 7\n",
        encoding="utf-8",
    )
    worker_path.chmod(0o755)
    code_archive = tmp_path / "code.tar.gz"
    with tarfile.open(code_archive, "w:gz") as archive:
        archive.add(
            worker_path,
            arcname="roboclaws.git/scripts/dev/run_cloudml_eval_worker.sh",
        )
    shard = {
        "shard_id": shard_id,
        "worker_pool": "cloudml-cpu",
        "max_parallel": 1,
        "manifest_cloud_path": "/mnt/cloudml/input/manifests/test.json",
        "row_ids": ["first"],
        "output_scratch_path": str(scratch_path),
        "output_mount_path": str(remote_path),
        "output_archive_name": "shard-output.tar",
        "provider_env_keys": [],
    }
    identity = {
        "code_commit": "a" * 40,
        "code_archive_name": "code.tar.gz",
        "code_archive_sha256": "b" * 64,
        "asset_manifest_name": "content.json",
        "asset_manifest_sha256": "c" * 64,
    }
    command = cloudml_task.image_command(shard, identity=identity).replace(
        "/mnt/cloudml/code/code.tar.gz", str(code_archive)
    )

    completed = subprocess.run(shlex.split(command), check=False)

    assert completed.returncode == 7
    assert (remote_path / "markers" / f"{shard_id}.json").is_file()
    archive_path = remote_path / "shard-output.tar"
    assert archive_path.is_file()
    with tarfile.open(archive_path, "r:") as archive:
        assert "./rows/first/result.txt" in archive.getnames()


def test_isaac_image_command_exports_frozen_contract_and_asset_group() -> None:
    shard = {
        "shard_id": "run-r49-isaac-001",
        "worker_pool": "cloudml-r49-isaac",
        "max_parallel": 1,
        "manifest_cloud_path": "/mnt/cloudml/input/manifests/isaac.json",
        "row_ids": ["cloudml-isaac-runtime-smoke"],
        "output_scratch_path": "/tmp/roboclaws-cloudml/output/isaac",
        "output_mount_path": "/mnt/cloudml/output/shards/isaac",
        "output_archive_name": "shard-output.tar",
        "provider_env_keys": [],
        "isaac_proof_contract_sha256": "d" * 64,
        "isaac_asset_group": "generated-smoke",
    }
    identity = {
        "code_commit": "a" * 40,
        "code_archive_name": "code.tar.gz",
        "code_archive_sha256": "b" * 64,
        "asset_manifest_name": "roboclaws_cloudml_isaac_stage_a_assets.json",
        "asset_manifest_sha256": "c" * 64,
        "asset_archive_name": "isaac.tar.gz",
        "asset_archive_sha256": "e" * 64,
    }

    command = cloudml_task.image_command(shard, identity=identity)

    assert "ROBOCLAWS_CLOUDML_ISAAC_EULA_ACCEPTED=true" in command
    assert "OMNI_KIT_ACCEPT_EULA=YES" in command
    assert "ROBOCLAWS_ISAACLAB_PYTHON=/isaac-sim/python.sh" in command
    assert f"ROBOCLAWS_CLOUDML_ISAAC_PROOF_CONTRACT_SHA256={'d' * 64}" in command
    assert "ROBOCLAWS_CLOUDML_ISAAC_ASSET_GROUP=generated-smoke" in command
    assert (
        "ROBOCLAWS_CLOUDML_ASSET_MANIFEST="
        "/mnt/cloudml/input/roboclaws_cloudml_isaac_stage_a_assets.json"
    ) in command
    assert "ROBOCLAWS_CLOUDML_ASSET_ARCHIVE=/mnt/cloudml/assets/isaac.tar.gz" in command
