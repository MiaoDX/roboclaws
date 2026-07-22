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
        "asset_manifest_sha256": "c" * 64,
    }
    command = cloudml_task.image_command(shard, identity=identity).replace(
        "/opt/roboclaws/bin/run-cloudml-eval-worker", str(worker_path)
    )

    completed = subprocess.run(shlex.split(command), check=False)

    assert completed.returncode == 7
    assert (remote_path / "markers" / f"{shard_id}.json").is_file()
    archive_path = remote_path / "shard-output.tar"
    assert archive_path.is_file()
    with tarfile.open(archive_path, "r:") as archive:
        assert "./rows/first/result.txt" in archive.getnames()
