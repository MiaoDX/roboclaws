from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Sequence

from roboclaws.evals import cloudml_provider_env, cloudml_task

PLAN_SCHEMA = "roboclaws_eval_harness_cloudml_plan_v1"
POOL_CAPABILITIES = {
    "cloudml-cpu": {
        "cpu",
        "python-env",
        "artifact-storage",
    },
    "cloudml-r49": {
        "cpu",
        "gpu",
        "python-env",
        "artifact-storage",
        "simulator:mujoco",
        "detector:grounding-dino",
        "openai-agents-sdk",
        "network:internal-api-router",
        "network:internal-mimo-router",
        "provider:codex-router-responses",
        "provider:mimo-mify-responses",
        "provider:mimo-tp-openai-chat",
        "provider:mimo-inside-openai-chat",
    },
}
POOL_RESOURCES = {
    "cloudml-cpu": {
        "queue_id": "11759",
        "resource_name": "cloudml.cputype1-108.1-8",
        "resource_priority": "GUARANTEED_PUBLIC",
        "resource_number": 4,
    },
    "cloudml-r49": {
        "queue_id": "11759",
        "resource_name": "cloudml.ng1r49-8-8.13-107",
        "resource_priority": "GUARANTEED",
        "resource_number": 1,
    },
}
POOL_IMAGE_ENV = {
    "cloudml-cpu": "ROBOCLAWS_CLOUDML_CPU_IMAGE_URL",
    "cloudml-r49": "ROBOCLAWS_CLOUDML_GPU_IMAGE_URL",
}
INPUT_MOUNT = cloudml_task.INPUT_MOUNT
OUTPUT_MOUNT = cloudml_task.OUTPUT_MOUNT
REPO_ROOT = Path(__file__).resolve().parents[3]


def bool_value(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"expected true or false, got {value!r}")


def build_cloudml_plan(
    manifest: dict[str, Any],
    *,
    execution_target: str,
    row_ids: Sequence[str] = (),
    run_id: str = "",
    provider_environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    if execution_target not in {"cloudml", "auto"}:
        raise ValueError(f"unsupported CloudML execution target: {execution_target}")
    selected = _selected_rows(manifest, row_ids=row_ids)
    resolved_run_id = _validated_run_id(run_id or _default_run_id())
    placed: dict[str, list[dict[str, Any]]] = {name: [] for name in POOL_CAPABILITIES}
    local_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    provider_env = cloudml_provider_env.load_environment(REPO_ROOT, provider_environment)
    provider_env_keys_by_row: dict[str, tuple[str, ...]] = {}

    for row in selected:
        pool, missing = _matching_pool(row)
        provider_profile = str((row.get("axes") or {}).get("provider_profile") or "")
        required_env_keys = cloudml_provider_env.required_env_keys(provider_profile)
        missing_env_keys = [key for key in required_env_keys if not provider_env.get(key)]
        if pool and required_env_keys and missing_env_keys:
            if execution_target == "auto":
                local_rows.append(row)
            else:
                blocked_rows.append(
                    _blocked_placement(
                        row,
                        category="missing_provider_environment",
                        detail=(
                            f"{provider_profile} is eligible for CloudML but requires local "
                            "provider environment variable(s): " + ", ".join(missing_env_keys)
                        ),
                    )
                )
        elif pool:
            placed[pool].append(row)
            if required_env_keys:
                provider_env_keys_by_row[str(row["row_id"])] = required_env_keys
        elif execution_target == "auto" and "network:external-egress" in set(
            row.get("execution_requirements") or []
        ):
            local_rows.append(row)
        else:
            blocked_rows.append(
                _blocked_placement(
                    row,
                    category="no_eligible_worker_pool",
                    detail="no CloudML pool satisfies: " + ", ".join(sorted(missing)),
                )
            )

    shards = _build_shards(
        placed,
        run_id=resolved_run_id,
        provider_env_keys_by_row=provider_env_keys_by_row,
    )
    return {
        "schema": PLAN_SCHEMA,
        "generated_at": _utc_now(),
        "run_id": resolved_run_id,
        "execution_target": execution_target,
        "code_commit": _git_commit(),
        "source_manifest": str(manifest.get("output_dir") or "") + "/eval_harness.json",
        "pools": [
            {
                "pool": name,
                "capabilities": sorted(capabilities),
                **POOL_RESOURCES[name],
            }
            for name, capabilities in POOL_CAPABILITIES.items()
        ],
        "shards": shards,
        "local_row_ids": [str(row["row_id"]) for row in local_rows],
        "blocked_rows": blocked_rows,
        "summary": {
            "selected_row_count": len(selected),
            "cloudml_row_count": sum(len(shard["row_ids"]) for shard in shards),
            "local_row_count": len(local_rows),
            "blocked_row_count": len(blocked_rows),
            "shard_count": len(shards),
        },
    }


def write_cloudml_plan(plan: dict[str, Any], manifest: dict[str, Any], *, output_dir: Path) -> Path:
    cloudml_dir = output_dir / "cloudml"
    manifest_dir = cloudml_dir / "manifests"
    yaml_dir = cloudml_dir / "yaml"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    yaml_dir.mkdir(parents=True, exist_ok=True)
    for shard in plan["shards"]:
        shard_id = str(shard["shard_id"])
        worker_output = f"{cloudml_task.CLOUDML_OUTPUT_SCRATCH_ROOT}/shards/{shard_id}"
        remote_output = f"{OUTPUT_MOUNT}/shards/{shard_id}"
        frozen = _relocated_manifest(
            manifest,
            output_dir=worker_output,
            selected_row_ids=set(shard["row_ids"]),
        )
        local_path = manifest_dir / f"{shard_id}.json"
        local_path.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
        shard["manifest_local_path"] = str(local_path)
        shard["manifest_cloud_path"] = f"{INPUT_MOUNT}/manifests/{shard_id}.json"
        shard["output_scratch_path"] = worker_output
        shard["output_mount_path"] = remote_output
        shard["yaml_path"] = str(yaml_dir / f"{shard_id}.yaml")
    path = cloudml_dir / "cloudml_plan.json"
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def executor_submit(
    plan: dict[str, Any],
    *,
    image_urls: dict[str, str],
    asset_manifest_path: Path,
    executor_path: Path,
    input_subpath: str,
    output_subpath: str,
    dry_run: bool,
    plan_path: Path | None = None,
    retry_shard_ids: Sequence[str] = (),
) -> None:
    identity = _load_asset_identity(asset_manifest_path)
    cloudml_task.validate_image_urls(plan, image_urls)
    if identity["code_commit"] != plan["code_commit"]:
        raise ValueError(
            "asset manifest code commit does not match the eval harness plan: "
            f"{identity['code_commit']} != {plan['code_commit']}"
        )
    retry_ids = _validate_retry_shard_ids(plan, retry_shard_ids)
    for shard in plan["shards"]:
        if shard.get("task_id") and str(shard["shard_id"]) not in retry_ids:
            continue
        _submit_shard(
            shard,
            plan=plan,
            image_url=image_urls[str(shard["worker_pool"])],
            identity=identity,
            executor_path=executor_path,
            input_subpath=input_subpath,
            output_subpath=output_subpath,
            dry_run=dry_run,
        )
        if plan_path is not None:
            _write_json(plan_path, plan)


def _validate_retry_shard_ids(plan: dict[str, Any], retry_shard_ids: Sequence[str]) -> set[str]:
    retry_ids = {str(value) for value in retry_shard_ids}
    known_ids = {str(shard["shard_id"]) for shard in plan["shards"]}
    unknown_retry_ids = retry_ids - known_ids
    if unknown_retry_ids:
        raise ValueError("unknown CloudML retry shard(s): " + ", ".join(sorted(unknown_retry_ids)))
    return retry_ids


def _submit_shard(
    shard: dict[str, Any],
    *,
    plan: dict[str, Any],
    image_url: str,
    identity: dict[str, str],
    executor_path: Path,
    input_subpath: str,
    output_subpath: str,
    dry_run: bool,
) -> None:
    platform_image_url, image_digest = cloudml_task.split_image_reference(image_url)
    previous_attempt = {
        key: shard[key]
        for key in ("task_id", "job_id", "console_url", "submitted_at", "remote_status")
        if shard.get(key)
    }
    yaml_path = cloudml_task.write_cml_task_yaml(
        shard,
        plan=plan,
        image_url=platform_image_url,
        identity=identity,
        input_subpath=input_subpath,
        output_subpath=output_subpath,
    )
    argv = cloudml_task.cml_submit_argv(executor_path=executor_path, yaml_path=yaml_path)
    if dry_run:
        result = subprocess.CompletedProcess(argv, 0, "", "")
        payload = {"dry_run": True, "yaml_path": str(yaml_path)}
    else:
        result = subprocess.run(argv, check=False, capture_output=True, text=True)
        payload = None
    shard["executor_exit_code"] = result.returncode
    if result.returncode != 0:
        raise RuntimeError(
            f"CloudML {'dry-run' if dry_run else 'submit'} failed for {shard['shard_id']}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    if payload is None:
        payload = _parse_cml_submit_output(result.stdout, stderr=result.stderr)
    shard["executor_argv"] = argv
    shard["image_url"] = image_url
    shard["platform_image_url"] = platform_image_url
    shard["image_digest"] = image_digest
    shard["dry_run"] = bool(payload.get("dry_run", dry_run))
    shard["yaml_path"] = str(payload.get("yaml_path") or shard["yaml_path"])
    if dry_run:
        return
    task_id = str(payload.get("task_id") or payload.get("job_id") or "")
    if not task_id:
        raise RuntimeError(f"CloudML submit returned no task id for {shard['shard_id']}")
    if previous_attempt:
        attempts = list(shard.get("previous_attempts") or [])
        attempts.append(previous_attempt)
        shard["previous_attempts"] = attempts
    shard.update(
        {
            "task_id": task_id,
            "job_id": str(payload.get("job_id") or task_id),
            "console_url": str(payload.get("console_url") or ""),
            "submitted_at": _utc_now(),
            "remote_status": "submitted",
        }
    )


def _parse_cml_submit_output(output: str, *, stderr: str = "") -> dict[str, Any]:
    match = re.search(r"CustomTrainJob \[([^\]]+)\]", output)
    if not match:
        detail = (stderr or output).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"CloudML submit did not create a task{suffix}")
    task_id = match.group(1)
    url_match = re.search(r"https://cloudml\.xiaomi\.com/[^\s\x07\x1b]+", output)
    return {
        "task_id": task_id,
        "job_id": task_id,
        "console_url": url_match.group(0) if url_match else "",
        "dry_run": False,
    }


def executor_dry_run(
    plan: dict[str, Any],
    *,
    image_urls: dict[str, str],
    asset_manifest_path: Path,
    executor_path: Path,
    input_subpath: str,
    output_subpath: str,
) -> None:
    executor_submit(
        plan,
        image_urls=image_urls,
        asset_manifest_path=asset_manifest_path,
        executor_path=executor_path,
        input_subpath=input_subpath,
        output_subpath=output_subpath,
        dry_run=True,
    )


def executor_from_environment(
    plan: dict[str, Any],
    *,
    dry_run: bool,
    plan_path: Path | None = None,
    retry_shard_ids: Sequence[str] = (),
) -> None:
    asset_manifest = os.environ.get("ROBOCLAWS_CLOUDML_ASSET_MANIFEST", "")
    if not asset_manifest:
        raise ValueError("execution_target=cloudml requires ROBOCLAWS_CLOUDML_ASSET_MANIFEST")
    required_pools = {str(shard["worker_pool"]) for shard in plan["shards"]}
    image_urls = {pool: os.environ.get(POOL_IMAGE_ENV[pool], "") for pool in sorted(required_pools)}
    missing_image_env = [POOL_IMAGE_ENV[pool] for pool, value in image_urls.items() if not value]
    if missing_image_env:
        raise ValueError(
            "execution_target=cloudml requires image environment variable(s): "
            + ", ".join(missing_image_env)
        )
    asset_manifest_path = Path(asset_manifest)
    payload = json.loads(asset_manifest_path.read_text(encoding="utf-8"))
    input_rel = str((payload.get("juicefs") or {}).get("input_rel") or "")
    if not input_rel:
        raise ValueError("CloudML asset manifest must define juicefs.input_rel")
    input_subpath = os.environ.get(
        "ROBOCLAWS_CLOUDML_INPUT_SUBPATH", f"/dongxu/gpu_perf/gpu_perf/{input_rel}"
    )
    output_subpath = os.environ.get(
        "ROBOCLAWS_CLOUDML_OUTPUT_SUBPATH",
        f"/dongxu/gpu_perf/executor_cloudml_runs/roboclaws-eval-harness/{plan['run_id']}",
    )
    provider_env_subpath = os.environ.get(
        "ROBOCLAWS_CLOUDML_PROVIDER_ENV_SUBPATH",
        (f"/dongxu/gpu_perf/executor_cloudml_provider_env/roboclaws-eval-harness/{plan['run_id']}"),
    )
    _stage_shard_manifests(plan, stage_dir=asset_manifest_path.parent)
    prior_staging = plan.get("staging") or {}
    prior_upload = prior_staging.get("upload")
    prior_output_init = prior_staging.get("output_init")
    prior_provider_environment = prior_staging.get("provider_environment")
    plan["staging"] = {
        "local_dir": str(asset_manifest_path.parent),
        "input_subpath": input_subpath,
        "output_subpath": output_subpath,
        "input_url": cloudml_task.juicefs_url(input_subpath),
        "output_url": cloudml_task.juicefs_url(output_subpath),
        "upload_required": not prior_upload,
    }
    if prior_upload:
        plan["staging"]["upload"] = prior_upload
    if prior_output_init:
        plan["staging"]["output_init"] = prior_output_init
    cloudml_provider_env.configure_staging(
        plan,
        root_subpath=provider_env_subpath,
        juicefs_url=cloudml_task.juicefs_url,
        prior_provider_environment=prior_provider_environment,
    )
    executor_path = Path(os.environ.get("ROBOCLAWS_EXECUTOR_PATH", "/home/mi/executor/exe"))
    provider_env = cloudml_provider_env.load_environment(REPO_ROOT)
    cloudml_provider_env.validate(plan, provider_env)
    if not dry_run and plan["shards"]:
        with tempfile.TemporaryDirectory(prefix="roboclaws-cloudml-provider-env-") as temp_dir:
            cloudml_provider_env.upload(
                plan,
                provider_env=provider_env,
                local_root=Path(temp_dir),
                executor_path=executor_path,
                plan_path=plan_path,
            )
        _upload_staging(plan, executor_path=executor_path, plan_path=plan_path)
        _initialize_output_mount(plan, executor_path=executor_path, plan_path=plan_path)
    executor_submit(
        plan,
        image_urls=image_urls,
        asset_manifest_path=asset_manifest_path,
        executor_path=executor_path,
        input_subpath=input_subpath,
        output_subpath=output_subpath,
        dry_run=dry_run,
        plan_path=plan_path,
        retry_shard_ids=retry_shard_ids,
    )


def executor_dry_run_from_environment(plan: dict[str, Any]) -> None:
    executor_from_environment(plan, dry_run=True)


def prepare_cloudml_execution(
    manifest: dict[str, Any],
    *,
    execution_target: str,
    row_ids: Sequence[str],
    run_id: str,
    dry_run: bool,
    retry_shard_ids: Sequence[str] = (),
) -> dict[str, Any]:
    if execution_target == "auto" and not dry_run:
        raise ValueError(
            "execution_target=auto submission is not enabled until local/cloud dependency handoff "
            "is implemented; use cloudml_dry_run=true or execution_target=cloudml"
        )
    output_dir = Path(manifest["output_dir"])
    plan = build_cloudml_plan(
        manifest,
        execution_target=execution_target,
        row_ids=row_ids,
        run_id=run_id,
    )
    plan_path = write_cloudml_plan(plan, manifest, output_dir=output_dir)
    executor_from_environment(
        plan,
        dry_run=dry_run,
        plan_path=plan_path,
        retry_shard_ids=retry_shard_ids,
    )
    apply_blocked_placements(manifest, plan)
    _write_json(plan_path, plan)
    return plan


def prepare_cloudml_dry_run(
    manifest: dict[str, Any],
    *,
    execution_target: str,
    row_ids: Sequence[str],
    run_id: str,
) -> None:
    prepare_cloudml_execution(
        manifest,
        execution_target=execution_target,
        row_ids=row_ids,
        run_id=run_id,
        dry_run=True,
    )


def apply_blocked_placements(manifest: dict[str, Any], plan: dict[str, Any]) -> None:
    rows = {str(row.get("row_id")): row for row in manifest.get("rows") or []}
    for blocked in plan.get("blocked_rows") or []:
        row = rows.get(str(blocked["row_id"]))
        if row is None:
            continue
        row["status"] = "blocked"
        row["outcome"] = "blocked"
        row["blocker_category"] = blocked["category"]
        row["blockers"] = [{"category": blocked["category"], "detail": blocked["detail"]}]


def collect_cloudml_results(
    plan: dict[str, Any], manifest: dict[str, Any], *, collected_root: Path
) -> dict[str, int]:
    rows = {str(row.get("row_id")): row for row in manifest.get("rows") or []}
    collected = failed_shards = missing_results = 0
    for shard in plan.get("shards") or []:
        shard_id = str(shard["shard_id"])
        shard_root = collected_root / "shards" / shard_id
        _materialize_shard_archive(
            shard_root,
            archive_name=str(
                shard.get("output_archive_name", cloudml_task.CLOUDML_SHARD_OUTPUT_ARCHIVE)
            ),
        )
        marker_path = shard_root / "markers" / f"{shard_id}.json"
        marker = _read_json_object(marker_path, label="CloudML terminal marker")
        if marker.get("shard_id") != shard_id:
            raise ValueError(f"CloudML terminal marker identity mismatch for {shard_id}")
        if marker.get("status") != "succeeded" or int(marker.get("exit_code") or 0) != 0:
            failed_shards += 1
        for row_id in shard["row_ids"]:
            result_path = shard_root / "rows" / str(row_id) / "row_result.json"
            if not result_path.is_file():
                missing_results += 1
                continue
            result = _read_json_object(result_path, label="CloudML row result")
            if result.get("row_id") != row_id:
                raise ValueError(f"CloudML row result identity mismatch for {row_id}")
            if result.get("execution_target") != "cloudml":
                raise ValueError(f"CloudML row result target mismatch for {row_id}")
            if result.get("shard_id") != shard_id:
                raise ValueError(f"CloudML row result shard mismatch for {row_id}")
            if str(row_id) not in rows:
                raise ValueError(f"CloudML row result is not in source manifest: {row_id}")
            _rewrite_collected_paths(result, shard=shard, shard_root=shard_root)
            rows[str(row_id)].update(result)
            collected += 1
        shard["terminal_marker"] = str(marker_path)
        shard["collection_status"] = "collected"
    summary = {
        "collected_row_count": collected,
        "failed_shard_count": failed_shards,
        "missing_result_count": missing_results,
    }
    plan["collection"] = summary
    return summary


def _materialize_shard_archive(shard_root: Path, *, archive_name: str) -> None:
    archive_path = shard_root / archive_name
    if not archive_path.is_file():
        return
    try:
        with tarfile.open(archive_path, "r:") as archive:
            archive.extractall(shard_root, filter="data")
    except (tarfile.TarError, ValueError, OSError) as exc:
        raise ValueError(f"invalid CloudML shard output archive: {archive_path}") from exc


def _rewrite_collected_paths(
    result: dict[str, Any], *, shard: dict[str, Any], shard_root: Path
) -> None:
    scratch_path = str(shard.get("output_scratch_path") or "")
    if scratch_path:
        _replace_prefix(result, scratch_path, str(shard_root))


def _selected_rows(manifest: dict[str, Any], *, row_ids: Sequence[str]) -> list[dict[str, Any]]:
    selected = [row for row in manifest.get("rows") or [] if row.get("selected")]
    if not row_ids:
        return [row for row in selected if row.get("status") != "skipped_by_budget"]
    requested = list(dict.fromkeys(str(row_id) for row_id in row_ids if str(row_id)))
    by_id = {str(row["row_id"]): row for row in selected}
    missing = [row_id for row_id in requested if row_id not in by_id]
    if missing:
        raise ValueError("manifest does not contain selected row(s): " + ", ".join(missing))
    return [by_id[row_id] for row_id in requested]


def _matching_pool(row: dict[str, Any]) -> tuple[str, set[str]]:
    requirements = set(str(value) for value in row.get("execution_requirements") or [])
    best_missing = requirements
    for pool, capabilities in POOL_CAPABILITIES.items():
        missing = requirements - capabilities
        if not missing:
            return pool, set()
        if len(missing) < len(best_missing):
            best_missing = missing
    return "", best_missing


def _blocked_placement(row: dict[str, Any], *, category: str, detail: str) -> dict[str, str]:
    return {"row_id": str(row["row_id"]), "category": category, "detail": detail}


def _build_shards(
    placed: dict[str, list[dict[str, Any]]],
    *,
    run_id: str,
    provider_env_keys_by_row: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    cpu_rows = placed["cloudml-cpu"]
    if cpu_rows:
        shards.append(
            _shard(
                "cpu-001",
                "cloudml-cpu",
                cpu_rows,
                run_id=run_id,
                width=4,
                provider_env_keys_by_row=provider_env_keys_by_row,
            )
        )
    gpu_rows = placed["cloudml-r49"]
    consumed: set[str] = set()
    by_id = {str(row["row_id"]): row for row in gpu_rows}
    for row in gpu_rows:
        row_id = str(row["row_id"])
        if row_id in consumed:
            continue
        dependencies = [str(value) for value in row.get("depends_on") or []]
        chain = [by_id[value] for value in dependencies if value in by_id]
        chain.append(row)
        chain_ids = {str(value["row_id"]) for value in chain}
        consumers = [
            candidate
            for candidate in gpu_rows
            if row_id in {str(value) for value in candidate.get("depends_on") or []}
        ]
        chain.extend(candidate for candidate in consumers if candidate not in chain)
        chain_ids.update(str(candidate["row_id"]) for candidate in consumers)
        consumed.update(chain_ids)
        suffix = len(shards) + 1
        shards.append(
            _shard(
                f"r49-{suffix:03d}",
                "cloudml-r49",
                chain,
                run_id=run_id,
                width=1,
                provider_env_keys_by_row=provider_env_keys_by_row,
            )
        )
    return shards


def _shard(
    suffix: str,
    pool: str,
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    width: int,
    provider_env_keys_by_row: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    shard_id = f"{run_id}-{suffix}"
    provider_env_keys = sorted(
        {key for row in rows for key in provider_env_keys_by_row.get(str(row["row_id"]), ())}
    )
    return {
        "shard_id": shard_id,
        "worker_pool": pool,
        "row_ids": [str(row["row_id"]) for row in rows],
        "max_parallel": width,
        "timeout_s": sum(int(row.get("timeout_s") or 0) for row in rows) + 600,
        "provider_env_keys": provider_env_keys,
        "output_archive_name": cloudml_task.CLOUDML_SHARD_OUTPUT_ARCHIVE,
        **POOL_RESOURCES[pool],
    }


def _relocated_manifest(
    manifest: dict[str, Any], *, output_dir: str, selected_row_ids: set[str]
) -> dict[str, Any]:
    frozen = copy.deepcopy(manifest)
    source_output = str(frozen["output_dir"])
    frozen["output_dir"] = output_dir
    for row in frozen.get("rows") or []:
        row["selected"] = str(row.get("row_id")) in selected_row_ids
        _replace_prefix(row, source_output, output_dir)
    return frozen


def _replace_prefix(value: Any, source: str, destination: str) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            value[key] = _replace_prefix(child, source, destination)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            value[index] = _replace_prefix(child, source, destination)
    elif isinstance(value, str):
        return value.replace(source, destination)
    return value


def _load_asset_identity(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    code = payload.get("git") or {}
    archive = (payload.get("staged_assets") or {}).get("archive") or {}
    code_archive = code.get("code_archive") or {}
    identity = {
        "code_commit": str(code.get("code_commit") or ""),
        "code_archive_name": str(code_archive.get("name") or ""),
        "code_archive_sha256": str(code_archive.get("sha256") or ""),
        "asset_archive_name": str(archive.get("name") or ""),
        "asset_archive_sha256": str(archive.get("sha256") or ""),
        "asset_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    missing = [key for key, value in identity.items() if not value]
    if missing:
        raise ValueError(f"asset manifest is missing identity field(s): {', '.join(missing)}")
    return identity


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must contain valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_json_output(value: str, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must return a JSON object")
    return payload


def _upload_staging(plan: dict[str, Any], *, executor_path: Path, plan_path: Path | None) -> None:
    staging = plan["staging"]
    if (staging.get("upload") or {}).get("status") == "completed":
        return
    result = subprocess.run(
        [
            str(executor_path),
            "storage",
            "juicefs",
            "upload",
            "--local_dir",
            str(staging["local_dir"]),
            "--url",
            str(staging["input_url"]),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"CloudML staging upload failed: {detail}")
    payload = _parse_json_output(result.stdout, label="JuiceFS upload")
    if payload.get("status") != "ok" or int(payload.get("exit_code") or 0) != 0:
        raise RuntimeError(f"CloudML staging upload was not successful: {payload}")
    staging["upload"] = {
        "status": "completed",
        "completed_at": _utc_now(),
        "files": int(payload.get("files") or 0),
    }
    staging["upload_required"] = False
    if plan_path is not None:
        _write_json(plan_path, plan)


def _initialize_output_mount(
    plan: dict[str, Any], *, executor_path: Path, plan_path: Path | None
) -> None:
    staging = plan["staging"]
    if (staging.get("output_init") or {}).get("status") == "completed":
        return
    yaml_dir = Path(plan["shards"][0]["yaml_path"]).parent
    local_dir = yaml_dir.parent / "output-init"
    marker = local_dir / "roboclaws_output_root.json"
    _write_json(
        marker,
        {
            "schema": "roboclaws_cloudml_output_root_v1",
            "run_id": plan["run_id"],
            "code_commit": plan["code_commit"],
        },
    )
    result = subprocess.run(
        [
            str(executor_path),
            "storage",
            "juicefs",
            "upload",
            "--local_dir",
            str(local_dir),
            "--url",
            str(staging["output_url"]),
            "--no_manifest",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"CloudML output mount initialization failed: {detail}")
    payload = _parse_json_output(result.stdout, label="CloudML output mount initialization")
    if payload.get("status") != "ok" or int(payload.get("exit_code") or 0) != 0:
        raise RuntimeError(f"CloudML output mount initialization was not successful: {payload}")
    staging["output_init"] = {
        "status": "completed",
        "completed_at": _utc_now(),
        "files": int(payload.get("files") or 0),
        "marker": marker.name,
    }
    if plan_path is not None:
        _write_json(plan_path, plan)


def _stage_shard_manifests(plan: dict[str, Any], *, stage_dir: Path) -> None:
    manifest_dir = stage_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for shard in plan["shards"]:
        source = Path(shard["manifest_local_path"])
        target = manifest_dir / source.name
        shutil.copy2(source, target)
        shard["manifest_staged_path"] = str(target)


def _default_run_id() -> str:
    return "eval-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _validated_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise ValueError(
            "CloudML run id must use 1-64 letters, digits, dots, underscores, or dashes"
        )
    return value


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        commit = result.stdout.strip()
    else:
        marker = REPO_ROOT / ".roboclaws_code_commit"
        commit = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "cannot resolve the CloudML code commit from git or .roboclaws_code_commit"
            + (f": {detail}" if detail else "")
        )
    return commit


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
