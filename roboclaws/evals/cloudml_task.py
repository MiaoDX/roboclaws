from __future__ import annotations

import json
import re
import shlex
import urllib.parse
from pathlib import Path
from typing import Any

INPUT_MOUNT = "/mnt/cloudml/input"
ASSET_MOUNT = "/mnt/cloudml/assets"
CODE_MOUNT = "/mnt/cloudml/code"
OUTPUT_MOUNT = "/mnt/cloudml/output"
CLOUDML_OUTPUT_SCRATCH_ROOT = "/tmp/roboclaws-cloudml/output"
CLOUDML_SHARD_OUTPUT_ARCHIVE = "shard-output.tar"
PROVIDER_ENV_MOUNT = "/mnt/cloudml/provider-env"
PROVIDER_ENV_FILENAME = "provider.env"
CLOUDML_VOLUME = "robot-intelligent-planning-data"
CLOUDML_CLUSTER = "wlcb-cloudml"


def juicefs_url(subpath: str) -> str:
    query = urllib.parse.urlencode(
        {"cluster": CLOUDML_CLUSTER, "name": CLOUDML_VOLUME, "path": subpath}
    )
    return f"https://cloud.mioffice.cn/juicefs/vol-detail?{query}"


def validate_image_urls(plan: dict[str, Any], image_urls: dict[str, str]) -> None:
    required_pools = {str(shard["worker_pool"]) for shard in plan["shards"]}
    for pool in required_pools:
        image_url = image_urls.get(pool, "")
        if not image_url:
            raise ValueError(f"CloudML worker pool {pool} has no configured image URL")
        split_image_reference(image_url)


def split_image_reference(image_url: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"(micr\.cloud\.mioffice\.cn/.+:[^/@:]+)@(sha256:[0-9a-f]{64})",
        image_url,
    )
    if not match or match.group(1).endswith(":latest"):
        raise ValueError(
            "CloudML image must use an immutable micr.cloud.mioffice.cn tag plus sha256 digest"
        )
    return match.group(1), match.group(2)


def cml_submit_argv(*, executor_path: Path, yaml_path: Path) -> list[str]:
    return [
        str(executor_path),
        "compute",
        "cloudml",
        "cml",
        "--",
        "custom_train",
        "submit",
        "--filename",
        str(yaml_path),
    ]


def write_cml_task_yaml(
    shard: dict[str, Any],
    *,
    plan: dict[str, Any],
    image_url: str,
    identity: dict[str, str],
    run_input_subpath: str,
    asset_subpath: str,
    code_subpath: str,
    output_subpath: str,
) -> Path:
    mounts = [
        _mount(run_input_subpath, INPUT_MOUNT, read_only=True),
        _mount(asset_subpath, ASSET_MOUNT, read_only=True),
        _mount(code_subpath, CODE_MOUNT, read_only=True),
        _mount(output_subpath, OUTPUT_MOUNT, read_only=False),
    ]
    provider_env_subpath = str(shard.get("provider_env_mount_subpath") or "")
    if provider_env_subpath:
        mounts.append(_mount(provider_env_subpath, PROVIDER_ENV_MOUNT, read_only=True))
    payload = {
        "jobName": _cloudml_name(str(shard["shard_id"])),
        "description": f"Roboclaws eval harness {plan['run_id']} {shard['shard_id']}",
        "accessType": "PRIVATE",
        "imageConfig": {
            "imageUrl": image_url,
            "imageCommand": image_command(shard, identity=identity),
        },
        "queueId": str(shard["queue_id"]),
        "priority": 5,
        "preemptible": bool(shard.get("preemptible")),
        "framework": "pytorch",
        "resourceConfigs": [
            {
                "nodeRole": "worker",
                "nodeNumber": 1,
                "perNodeResourceSpec": {
                    "resourcePriority": str(shard["resource_priority"]),
                    "resourceName": str(shard["resource_name"]),
                    "resourceNumber": int(shard["resource_number"]),
                },
            }
        ],
        "juiceFsMountConfigs": mounts,
    }
    yaml_path = Path(str(shard["yaml_path"]))
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    # JSON is a YAML subset and avoids adding a serializer dependency to the adapter.
    yaml_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return yaml_path


def image_command(shard: dict[str, Any], *, identity: dict[str, str]) -> str:
    values = {
        "ROBOCLAWS_CLOUDML_CODE_COMMIT": identity["code_commit"],
        "ROBOCLAWS_CLOUDML_CODE_ARCHIVE": f"{CODE_MOUNT}/{identity['code_archive_name']}",
        "ROBOCLAWS_CLOUDML_CODE_ARCHIVE_SHA256": identity["code_archive_sha256"],
        "ROBOCLAWS_CLOUDML_ASSET_MANIFEST_SHA256": identity["asset_manifest_sha256"],
        "ROBOCLAWS_CLOUDML_ASSET_MANIFEST": f"{INPUT_MOUNT}/roboclaws_cloudml_cleanup_assets.json",
        "ROBOCLAWS_CLOUDML_MANIFEST": str(shard["manifest_cloud_path"]),
        "ROBOCLAWS_CLOUDML_ROW_IDS": ",".join(shard["row_ids"]),
        "ROBOCLAWS_CLOUDML_SHARD_ID": str(shard["shard_id"]),
        "ROBOCLAWS_CLOUDML_WORKER_POOL": str(shard["worker_pool"]),
        "ROBOCLAWS_CLOUDML_MAX_PARALLEL": str(shard["max_parallel"]),
        "ROBOCLAWS_CLOUDML_OUTPUT_DIR": str(shard["output_scratch_path"]),
        "ROBOCLAWS_CLOUDML_REMOTE_OUTPUT_DIR": str(shard["output_mount_path"]),
    }
    if shard.get("provider_env_keys"):
        values["ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE"] = (
            f"{PROVIDER_ENV_MOUNT}/{PROVIDER_ENV_FILENAME}"
        )
    if shard["worker_pool"] in {"cloudml-cpu-mujoco", "cloudml-r49", "cloudml-r49-isaac"}:
        values["ROBOCLAWS_CLOUDML_ASSET_ARCHIVE"] = (
            f"{ASSET_MOUNT}/{identity['asset_archive_name']}"
        )
        values["ROBOCLAWS_CLOUDML_ASSET_ARCHIVE_SHA256"] = identity["asset_archive_sha256"]
    if shard["worker_pool"] == "cloudml-cpu-mujoco":
        values["MUJOCO_GL"] = "osmesa"
        values["PYOPENGL_PLATFORM"] = "osmesa"
        values["ROBOCLAWS_MOLMOSPACES_MUJOCO_GL"] = "osmesa"
        values["VISUAL_GROUNDING_DEVICE"] = "cpu"
    elif shard["worker_pool"] == "cloudml-r49":
        values["VISUAL_GROUNDING_DEVICE"] = "cuda"
        values["VISUAL_GROUNDING_TORCH_DTYPE"] = "auto"
    elif shard["worker_pool"] == "cloudml-r49-isaac":
        values["OMNI_KIT_ACCEPT_EULA"] = "YES"
        values["ROBOCLAWS_CLOUDML_ISAAC_EULA_ACCEPTED"] = "true"
        values["ROBOCLAWS_ISAACLAB_PYTHON"] = "/opt/roboclaws/.venv-isaaclab/bin/python"
        values["VISUAL_GROUNDING_DEVICE"] = "cuda"
        values["VISUAL_GROUNDING_TORCH_DTYPE"] = "auto"
        values["ROBOCLAWS_CLOUDML_ISAAC_PROOF_CONTRACT_SHA256"] = str(
            shard["isaac_proof_contract_sha256"]
        )
        values["ROBOCLAWS_CLOUDML_ISAAC_ASSET_GROUP"] = str(shard["isaac_asset_group"])
    exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())
    bootstrap = ""
    if shard.get("provider_env_keys"):
        provider_path = f"{PROVIDER_ENV_MOUNT}/{PROVIDER_ENV_FILENAME}"
        bootstrap = f"set +x; set -a; source {shlex.quote(provider_path)}; set +a; "
    scratch_path = shlex.quote(str(shard["output_scratch_path"]))
    remote_path = shlex.quote(str(shard["output_mount_path"]))
    archive_name = shlex.quote(str(shard["output_archive_name"]))
    shard_id = shlex.quote(str(shard["shard_id"]))
    archive_tmp = shlex.quote(f"/tmp/roboclaws-cloudml/{shard['shard_id']}-output.tar")
    bootstrap_root = shlex.quote(f"/tmp/roboclaws-cloudml/{shard['shard_id']}-bootstrap")
    code_archive = shlex.quote(f"{CODE_MOUNT}/{identity['code_archive_name']}")
    shell_command = (
        f"set -Eeuo pipefail; export {exports}; {bootstrap}"
        f"rm -rf {bootstrap_root}; mkdir -p {bootstrap_root}; "
        f"tar -xzf {code_archive} -C {bootstrap_root}; "
        "set +e; "
        f"bash {bootstrap_root}/roboclaws.git/scripts/dev/run_cloudml_eval_worker.sh; "
        "worker_exit=$?; set -e; "
        f"test -d {scratch_path}; mkdir -p /tmp/roboclaws-cloudml {remote_path}/markers; "
        f"tar -cf {archive_tmp} -C {scratch_path} .; "
        f"cp {archive_tmp} {remote_path}/{archive_name}; "
        f"cp {scratch_path}/markers/{shard_id}.json {remote_path}/markers/{shard_id}.json; "
        'exit "$worker_exit"'
    )
    return f"bash -c {shlex.quote(shell_command)}"


def _mount(subpath: str, mount_path: str, *, read_only: bool) -> dict[str, Any]:
    return {
        "volume": CLOUDML_VOLUME,
        "juiceFsCluster": CLOUDML_CLUSTER,
        "subPath": subpath,
        "mountPath": mount_path,
        "readOnly": read_only,
    }


def _cloudml_name(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:63]
