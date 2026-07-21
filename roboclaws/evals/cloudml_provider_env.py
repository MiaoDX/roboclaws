from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roboclaws.agents.provider_registry import provider_route_spec
from roboclaws.core.dotenv import load_dotenv_file


def required_env_keys(provider_profile: str) -> tuple[str, ...]:
    if not provider_profile:
        return ()
    try:
        return provider_route_spec(provider_profile).required_env_keys
    except KeyError:
        return ()


def load_environment(
    repo_root: Path,
    provider_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    if provider_environment is not None:
        return dict(provider_environment)
    dotenv_path = Path(os.environ.get("ROBOCLAWS_PROVIDER_ENV_FILE", repo_root / ".env"))
    return load_dotenv_file(dotenv_path, os.environ)


def configure_staging(
    plan: dict[str, Any],
    *,
    root_subpath: str,
    juicefs_url: Callable[[str], str],
    prior_provider_environment: dict[str, Any] | None = None,
) -> None:
    prior = (prior_provider_environment or {}).get("shards") or {}
    shards: dict[str, dict[str, Any]] = {}
    for shard in plan["shards"]:
        env_keys = list(shard.get("provider_env_keys") or [])
        if not env_keys:
            continue
        shard_id = str(shard["shard_id"])
        subpath = f"{root_subpath.rstrip('/')}/{shard_id}"
        entry = {
            "env_keys": env_keys,
            "subpath": subpath,
            "url": juicefs_url(subpath),
            "upload_required": True,
        }
        prior_upload = (prior.get(shard_id) or {}).get("upload")
        if prior_upload:
            entry["upload"] = prior_upload
            entry["upload_required"] = prior_upload.get("status") != "completed"
        shards[shard_id] = entry
        shard["provider_env_mount_subpath"] = subpath
    plan["staging"]["provider_environment"] = {
        "transport": "juicefs-read-only-dotenv",
        "root_subpath": root_subpath,
        "shards": shards,
    }


def validate(plan: dict[str, Any], provider_env: dict[str, str]) -> None:
    missing = sorted(
        {
            key
            for shard in plan["shards"]
            for key in shard.get("provider_env_keys") or []
            if not provider_env.get(key)
        }
    )
    if missing:
        raise ValueError(
            "CloudML provider rows require local environment variable(s): " + ", ".join(missing)
        )


def write_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={shlex.quote(value)}" for key, value in sorted(values.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def upload(
    plan: dict[str, Any],
    *,
    provider_env: dict[str, str],
    local_root: Path,
    executor_path: Path,
    plan_path: Path | None,
) -> None:
    staging = plan["staging"]["provider_environment"]
    for shard_id, entry in staging["shards"].items():
        if (entry.get("upload") or {}).get("status") == "completed":
            continue
        local_dir = local_root / shard_id
        local_dir.mkdir(parents=True, mode=0o700)
        write_file(
            local_dir / "provider.env",
            {key: provider_env[key] for key in entry["env_keys"]},
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
                str(entry["url"]),
                "--no_manifest",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"CloudML provider environment upload failed: {detail}")
        payload = _parse_json_object(result.stdout)
        if payload.get("status") != "ok" or int(payload.get("exit_code") or 0) != 0:
            raise RuntimeError(f"CloudML provider environment upload was not successful: {payload}")
        entry["upload"] = {
            "status": "completed",
            "completed_at": dt.datetime.now(dt.UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "files": int(payload.get("files") or 0),
        }
        entry["upload_required"] = False
        if plan_path is not None:
            plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("JuiceFS provider environment upload returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("JuiceFS provider environment upload must return a JSON object")
    return payload
