from __future__ import annotations

import json
import re
import shlex
import urllib.parse
from pathlib import Path
from typing import Any

INPUT_MOUNT = "/mnt/cloudml/input"
OUTPUT_MOUNT = "/mnt/cloudml/output"
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


def executor_submit_argv(
    shard: dict[str, Any],
    *,
    plan: dict[str, Any],
    image_url: str,
    identity: dict[str, str],
    executor_path: Path,
    input_subpath: str,
    output_subpath: str,
    dry_run: bool,
) -> list[str]:
    mounts = [
        _mount(input_subpath, INPUT_MOUNT, read_only=True),
        _mount(output_subpath, OUTPUT_MOUNT, read_only=False),
    ]
    provider_env_subpath = str(shard.get("provider_env_mount_subpath") or "")
    if provider_env_subpath:
        mounts.append(_mount(provider_env_subpath, PROVIDER_ENV_MOUNT, read_only=True))
    return [
        str(executor_path),
        "compute",
        "cloudml",
        "custom_train",
        "submit",
        "--job_name",
        _cloudml_name(str(shard["shard_id"])),
        "--description",
        f"Roboclaws eval harness {plan['run_id']} {shard['shard_id']}",
        "--image_url",
        image_url,
        "--image_command",
        image_command(shard, identity=identity),
        "--juicefs_mount_configs",
        json.dumps(mounts, separators=(",", ":")),
        "--queue_id",
        str(shard["queue_id"]),
        "--resource_priority",
        str(shard["resource_priority"]),
        "--resource_name",
        str(shard["resource_name"]),
        "--resource_number",
        str(shard["resource_number"]),
        "--output_yaml_path",
        str(shard["yaml_path"]),
        "--dry_run",
        "true" if dry_run else "false",
        "--json",
    ]


def image_command(shard: dict[str, Any], *, identity: dict[str, str]) -> str:
    values = {
        "ROBOCLAWS_CLOUDML_CODE_COMMIT": identity["code_commit"],
        "ROBOCLAWS_CLOUDML_CODE_ARCHIVE": f"{INPUT_MOUNT}/archives/{identity['code_archive_name']}",
        "ROBOCLAWS_CLOUDML_CODE_ARCHIVE_SHA256": identity["code_archive_sha256"],
        "ROBOCLAWS_CLOUDML_ASSET_MANIFEST_SHA256": identity["asset_manifest_sha256"],
        "ROBOCLAWS_CLOUDML_ASSET_MANIFEST": f"{INPUT_MOUNT}/roboclaws_cloudml_cleanup_assets.json",
        "ROBOCLAWS_CLOUDML_MANIFEST": str(shard["manifest_cloud_path"]),
        "ROBOCLAWS_CLOUDML_ROW_IDS": ",".join(shard["row_ids"]),
        "ROBOCLAWS_CLOUDML_SHARD_ID": str(shard["shard_id"]),
        "ROBOCLAWS_CLOUDML_WORKER_POOL": str(shard["worker_pool"]),
        "ROBOCLAWS_CLOUDML_MAX_PARALLEL": str(shard["max_parallel"]),
        "ROBOCLAWS_CLOUDML_OUTPUT_DIR": str(shard["output_mount_path"]),
    }
    if shard.get("provider_env_keys"):
        values["ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE"] = (
            f"{PROVIDER_ENV_MOUNT}/{PROVIDER_ENV_FILENAME}"
        )
    if shard["worker_pool"] == "cloudml-r49":
        values["ROBOCLAWS_CLOUDML_ASSET_ARCHIVE"] = (
            f"{INPUT_MOUNT}/archives/{identity['asset_archive_name']}"
        )
        values["ROBOCLAWS_CLOUDML_ASSET_ARCHIVE_SHA256"] = identity["asset_archive_sha256"]
        values["VISUAL_GROUNDING_DEVICE"] = "cuda"
        values["VISUAL_GROUNDING_TORCH_DTYPE"] = "auto"
    exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())
    bootstrap = ""
    if shard.get("provider_env_keys"):
        provider_path = f"{PROVIDER_ENV_MOUNT}/{PROVIDER_ENV_FILENAME}"
        bootstrap = f"set +x; set -a; source {shlex.quote(provider_path)}; set +a; "
    shell_command = f"export {exports}; {bootstrap}exec /opt/roboclaws/bin/run-cloudml-eval-worker"
    return f"bash -lc {shlex.quote(shell_command)}"


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
