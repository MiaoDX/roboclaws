#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
executor_root="${ROBOCLAWS_EXECUTOR_ROOT:-/home/mi/executor}"
executor_config_root="${ROBOCLAWS_EXECUTOR_CONFIG_ROOT:-}"
executor_config_path="${ROBOCLAWS_EXECUTOR_CONFIG_PATH:-}"
date_stamp="${ROBOCLAWS_STAGE_DATE:-$(date +%Y%m%d)}"
code_ref="${ROBOCLAWS_EVAL_CODE_REF:-mi/main}"
code_commit="${ROBOCLAWS_CLOUDML_CODE_COMMIT:-$(git -C "$repo_root" rev-parse "$code_ref")}"
if [[ "$code_commit" == "HEAD" && ! -d "$repo_root/.git" && -f "$repo_root/.roboclaws_code_commit" ]]; then
  code_commit="$(<"$repo_root/.roboclaws_code_commit")"
elif [[ ! "$code_commit" =~ ^[0-9a-f]{40}$ ]]; then
  code_commit="$(git -C "$repo_root" rev-parse "$code_commit")"
fi
if [[ ! "$code_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "error: CloudML code commit must resolve to a full 40-character SHA" >&2
  exit 2
fi
code_short="${code_commit:0:12}"
input_rel="${ROBOCLAWS_JUICEFS_INPUT_REL:-roboclaws-assets/cleanup-focused}"
stage_dir="${ROBOCLAWS_STAGE_DIR:-/tmp/roboclaws-cloudml-cleanup-assets-${code_short}-${date_stamp}}"
juicefs_url="${ROBOCLAWS_JUICEFS_URL:-https://cloud.mioffice.cn/juicefs/vol-detail?cluster=wlcb-cloudml&name=robot-intelligent-planning-data&path=/dongxu/gpu_perf/gpu_perf/${input_rel}}"
asset_mode="${ROBOCLAWS_STAGE_ASSET_MODE:-archive}"
archive_name="${ROBOCLAWS_STAGE_ARCHIVE_NAME:-cleanup-focused-molmospaces-val0.tar.gz}"
code_archive_name="${ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME:-roboclaws-code-${code_short}.tar.gz}"
map_bundle="${ROBOCLAWS_STAGE_MAP_BUNDLE:-assets/maps/molmospaces/procthor-10k-val/0}"
include_grasps="${ROBOCLAWS_STAGE_INCLUDE_GRASPS:-false}"
run_upload_dry_run="${ROBOCLAWS_STAGE_RUN_UPLOAD_DRY_RUN:-true}"
run_upload="${ROBOCLAWS_STAGE_RUN_UPLOAD:-false}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage:
  scripts/dev/stage_cloudml_cleanup_assets.sh

Prepares a local CloudML cleanup asset staging directory and, by default, asks
executor for a JuiceFS upload dry-run. The default mode writes one MolmoSpaces
cleanup asset archive plus a sha256 file and manifest, avoiding a 100k-file
JuiceFS upload.

Environment overrides:
  ROBOCLAWS_STAGE_DIR                 Default: /tmp/roboclaws-cloudml-cleanup-assets-<code>-<date>
  ROBOCLAWS_JUICEFS_INPUT_REL         Default: roboclaws-assets/cleanup-focused
                                      under the CloudML /mnt/cloudml/input mount.
  ROBOCLAWS_JUICEFS_URL               Full cloud.mioffice.cn JuiceFS vol-detail URL.
  ROBOCLAWS_STAGE_ASSET_MODE          archive|manifest-only. Default: archive.
  ROBOCLAWS_STAGE_ARCHIVE_NAME        Default: cleanup-focused-molmospaces-val0.tar.gz
  ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME   Default: roboclaws-code-<code>.tar.gz
  ROBOCLAWS_STAGE_MAP_BUNDLE          Default: assets/maps/molmospaces/procthor-10k-val/0
  ROBOCLAWS_STAGE_INCLUDE_GRASPS      Set true to include grasps/droid when materializing.
  ROBOCLAWS_STAGE_RUN_UPLOAD_DRY_RUN  Set false to skip executor upload dry-run.
  ROBOCLAWS_STAGE_RUN_UPLOAD          Set true to upload staged files to JuiceFS.
  ROBOCLAWS_EXECUTOR_ROOT             Default: /home/mi/executor
  ROBOCLAWS_EXECUTOR_CONFIG_ROOT      Optional executor config-root override.
  ROBOCLAWS_EXECUTOR_CONFIG_PATH      Optional executor config-path override.

Real JuiceFS upload runs only when ROBOCLAWS_STAGE_RUN_UPLOAD=true. Otherwise the
script prints the upload command and, by default, performs an upload dry-run.
USAGE
  exit 0
fi

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  echo "error: repo-local .venv is required to discover MolmoSpaces assets" >&2
  exit 1
fi

if [[ ! -x "$executor_root/exe" ]]; then
  echo "error: executor not found at $executor_root" >&2
  exit 1
fi

run_executor() {
  local env_args=()
  if [[ -n "$executor_config_root" ]]; then
    env_args+=("EXECUTOR_CONFIG_ROOT=$executor_config_root")
  fi
  if [[ -n "$executor_config_path" ]]; then
    env_args+=("EXECUTOR_CONFIG_PATH=$executor_config_path")
  fi
  env "${env_args[@]}" "$executor_root/exe" "$@"
}

resolve_molmospaces_paths() {
  "$repo_root/.venv/bin/python" - <<'PY'
from molmo_spaces.molmo_spaces_constants import ASSETS_DIR, DATA_CACHE_DIR
print(ASSETS_DIR)
print(DATA_CACHE_DIR)
PY
}

mapfile -t molmospaces_paths < <(resolve_molmospaces_paths)
assets_source="${MLSPACES_ASSETS_DIR:-${molmospaces_paths[0]}}"
cache_source="${MLSPACES_CACHE_DIR:-${molmospaces_paths[1]}}"

require_path() {
  local path="$1"
  local label="$2"
  if [[ ! -e "$path" ]]; then
    echo "error: missing $label: $path" >&2
    exit 1
  fi
}

clean_stage_dir() {
  local path="$1"
  if [[ -z "$path" || "$path" == "/" || "$path" == "$repo_root" || "$path" == "$HOME" ]]; then
    echo "error: refusing unsafe stage dir: $path" >&2
    exit 1
  fi
  rm -rf "$path"
  mkdir -p "$path/archives"
}

require_path "$assets_source/scenes/procthor-10k-val/val_0.xml" \
  "MolmoSpaces val_0 scene XML"
require_path "$assets_source/scenes/procthor-10k-val/val_0.json" \
  "MolmoSpaces val_0 scene metadata"
require_path "$assets_source/scenes/procthor-10k-val/val_0_metadata.json" \
  "MolmoSpaces val_0 scene runtime metadata"
require_path "$assets_source/scenes/procthor-10k-val/val_0_ceiling.xml" \
  "MolmoSpaces val_0 ceiling scene XML"
require_path "$assets_source/scenes/procthor-10k-val/val_0_assets" \
  "MolmoSpaces val_0 local mesh assets"
require_path "$assets_source/scenes/procthor-10k-val/mjthor_resources_combined_meta.json.gz" \
  "MolmoSpaces procthor val combined trie metadata"
require_path "$assets_source/scenes/procthor-10k-val/mjthor_resource_file_to_size_mb.json" \
  "MolmoSpaces procthor val remote manifest"
require_path "$assets_source/scenes/procthor-10k-val/.procthor-10k-val_val_0.tar.zst_complete_links" \
  "MolmoSpaces val_0 link completion flag"
require_path "$assets_source/objects/thor" \
  "MolmoSpaces THOR object assets"
require_path "$assets_source/robots/rby1m" \
  "MolmoSpaces RBY1M robot assets"
require_path "$assets_source/mjthor_data_type_to_source_to_versions.json" \
  "MolmoSpaces installed-source manifest"
require_path "$cache_source/mjthor_data_type_to_source_to_versions.json" \
  "MolmoSpaces cache manifest"
cache_resource_paths=(
  "scenes/procthor-10k-val"
  "grasps/droid_objaverse"
)
for relative in "${cache_resource_paths[@]}"; do
  require_path "$cache_source/$relative" "MolmoSpaces versioned $relative cache"
done
case "$map_bundle" in
  /*|../*|*/../*)
    echo "error: ROBOCLAWS_STAGE_MAP_BUNDLE must be a repo-relative path: $map_bundle" >&2
    exit 1
    ;;
esac
require_path "$repo_root/$map_bundle/map.yaml" \
  "Roboclaws Nav2 map bundle map.yaml"
require_path "$repo_root/$map_bundle/semantics.json" \
  "Roboclaws Nav2 map bundle semantics.json"

clean_stage_dir "$stage_dir"

archive_path=""
archive_sha256=""
archive_bytes=""
code_archive_path="$stage_dir/archives/$code_archive_name"
code_archive_sha256=""
code_archive_bytes=""
staged_paths=()
reproducible_tar_args=(
  --sort=name
  --mtime=@0
  --owner=0
  --group=0
  --numeric-owner
  --format=gnu
)
case "$asset_mode" in
  archive)
    archive_path="$stage_dir/archives/$archive_name"
    archive_tmp="${archive_path}.tmp"
    archive_manifest_dir="$stage_dir/.archive-manifest"
    mkdir -p "$archive_manifest_dir/molmospaces/assets" "$archive_manifest_dir/molmospaces/cache"
    cp "$assets_source/mjthor_data_type_to_source_to_versions.json" \
      "$archive_manifest_dir/molmospaces/assets/"
    cp "$cache_source/mjthor_data_type_to_source_to_versions.json" \
      "$archive_manifest_dir/molmospaces/cache/"
    for relative in "${cache_resource_paths[@]}"; do
      mkdir -p "$archive_manifest_dir/molmospaces/cache/$(dirname "$relative")"
      cp -a "$cache_source/$relative" \
        "$archive_manifest_dir/molmospaces/cache/$(dirname "$relative")/"
    done
    tar_paths=(
      "scenes/procthor-10k-val/val_0.xml"
      "scenes/procthor-10k-val/val_0.json"
      "scenes/procthor-10k-val/val_0_metadata.json"
      "scenes/procthor-10k-val/val_0_ceiling.xml"
      "scenes/procthor-10k-val/val_0_assets"
      "scenes/procthor-10k-val/mjthor_resources_combined_meta.json.gz"
      "scenes/procthor-10k-val/mjthor_resource_file_to_size_mb.json"
      "scenes/procthor-10k-val/.procthor-10k-val_val_0.tar.zst_complete_links"
      "objects/thor"
      "robots/rby1m"
    )
    if [[ "$include_grasps" == "true" ]]; then
      require_path "$assets_source/grasps/droid" "MolmoSpaces DROID grasp assets"
      tar_paths+=("grasps/droid")
    fi
    tar "${reproducible_tar_args[@]}" -cf - \
      --dereference \
      --transform 's#^\(scenes\|objects\|robots\|grasps\)/#molmospaces/assets/\1/#' \
      --transform 's#^assets/maps/#roboclaws/assets/maps/#' \
      -C "$assets_source" \
      "${tar_paths[@]}" \
      -C "$archive_manifest_dir" \
      "molmospaces" \
      -C "$repo_root" \
      "$map_bundle" \
      | gzip -n > "$archive_tmp"
    rm -rf "$archive_manifest_dir"
    mv "$archive_tmp" "$archive_path"
    archive_sha256="$(sha256sum "$archive_path" | awk '{print $1}')"
    archive_bytes="$(stat -c '%s' "$archive_path")"
    printf '%s  %s\n' "$archive_sha256" "$archive_name" > "${archive_path}.sha256"
    staged_paths+=("archives/$archive_name" "archives/${archive_name}.sha256")
    ;;
  manifest-only)
    ;;
  *)
    echo "error: unsupported ROBOCLAWS_STAGE_ASSET_MODE '$asset_mode'" >&2
    echo "expected archive|manifest-only" >&2
    exit 1
    ;;
esac

code_tmp="$stage_dir/.code-archive-tmp"
rm -rf "$code_tmp"
mkdir -p "$code_tmp/roboclaws.git"
if git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$repo_root" archive --format=tar "$code_commit" | tar -xf - -C "$code_tmp/roboclaws.git"
else
  archive_marker="$repo_root/.roboclaws_code_commit"
  if [[ ! -f "$archive_marker" || "$(<"$archive_marker")" != "$code_commit" ]]; then
    echo "error: source archive commit marker does not match $code_commit" >&2
    exit 2
  fi
  tar -cf - \
    --exclude='./.git' \
    --exclude='./.env' \
    --exclude='./.tmp' \
    --exclude='./.venv' \
    --exclude='./.venv-*' \
    --exclude='./output' \
    --exclude='./.pytest_cache' \
    --exclude='*/__pycache__' \
    --exclude='*.pyc' \
    -C "$repo_root" . \
    | tar -xf - -C "$code_tmp/roboclaws.git"
fi
printf '%s\n' "$code_commit" > "$code_tmp/roboclaws.git/.roboclaws_code_commit"
tar "${reproducible_tar_args[@]}" -cf - -C "$code_tmp" roboclaws.git \
  | gzip -n > "${code_archive_path}.tmp"
mv "${code_archive_path}.tmp" "$code_archive_path"
rm -rf "$code_tmp"
code_archive_sha256="$(sha256sum "$code_archive_path" | awk '{print $1}')"
code_archive_bytes="$(stat -c '%s' "$code_archive_path")"
printf '%s  %s\n' "$code_archive_sha256" "$code_archive_name" > "${code_archive_path}.sha256"
staged_paths+=("archives/$code_archive_name" "archives/${code_archive_name}.sha256")

manifest_path="$stage_dir/roboclaws_cloudml_cleanup_assets.json"
export ROBOCLAWS_STAGE_MANIFEST_PATH="$manifest_path"
export ROBOCLAWS_STAGE_REPO_ROOT="$repo_root"
export ROBOCLAWS_STAGE_DIR_RESOLVED="$stage_dir"
export ROBOCLAWS_STAGE_INPUT_REL="$input_rel"
export ROBOCLAWS_STAGE_JUICEFS_URL="$juicefs_url"
export ROBOCLAWS_STAGE_CODE_COMMIT="$code_commit"
export ROBOCLAWS_STAGE_ASSETS_SOURCE="$assets_source"
export ROBOCLAWS_STAGE_CACHE_SOURCE="$cache_source"
export ROBOCLAWS_STAGE_ASSET_MODE="$asset_mode"
export ROBOCLAWS_STAGE_ARCHIVE_NAME="$archive_name"
export ROBOCLAWS_STAGE_ARCHIVE_PATH="$archive_path"
export ROBOCLAWS_STAGE_ARCHIVE_SHA256="$archive_sha256"
export ROBOCLAWS_STAGE_ARCHIVE_BYTES="$archive_bytes"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME="$code_archive_name"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_PATH="$code_archive_path"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_SHA256="$code_archive_sha256"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_BYTES="$code_archive_bytes"
export ROBOCLAWS_STAGE_MAP_BUNDLE="$map_bundle"
export ROBOCLAWS_STAGE_INCLUDE_GRASPS="$include_grasps"
export ROBOCLAWS_STAGE_STAGED_PATHS="$(IFS=:; echo "${staged_paths[*]}")"

"$repo_root/.venv/bin/python" - <<'PY'
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

repo_root = Path(os.environ["ROBOCLAWS_STAGE_REPO_ROOT"]).resolve()
stage_dir = Path(os.environ["ROBOCLAWS_STAGE_DIR_RESOLVED"]).resolve()
staged_paths = [item for item in os.environ["ROBOCLAWS_STAGE_STAGED_PATHS"].split(":") if item]
archive_path = os.environ["ROBOCLAWS_STAGE_ARCHIVE_PATH"]
code_archive_path = os.environ["ROBOCLAWS_STAGE_CODE_ARCHIVE_PATH"]

def du(path: str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return "missing"
    try:
        return subprocess.check_output(["du", "-sh", str(candidate)], text=True).split()[0]
    except Exception:
        return "unavailable"

payload = {
    "schema": "roboclaws_cloudml_cleanup_assets_v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "stage_dir": str(stage_dir),
    "juicefs": {
        "input_rel": os.environ["ROBOCLAWS_STAGE_INPUT_REL"],
        "url": os.environ["ROBOCLAWS_STAGE_JUICEFS_URL"],
        "cloudml_mount_path": "/mnt/cloudml/input",
        "archive_path": (
            f"/mnt/cloudml/input/{os.environ['ROBOCLAWS_STAGE_INPUT_REL']}"
            f"/archives/{os.environ['ROBOCLAWS_STAGE_ARCHIVE_NAME']}"
        )
        if os.environ["ROBOCLAWS_STAGE_ARCHIVE_NAME"]
        else "",
        "code_archive_path": (
            f"/mnt/cloudml/input/{os.environ['ROBOCLAWS_STAGE_INPUT_REL']}"
            f"/archives/{os.environ['ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME']}"
        ),
    },
    "git": {
        "code_commit": os.environ["ROBOCLAWS_STAGE_CODE_COMMIT"],
        "source_path": "juicefs.code_archive",
        "code_archive": {
            "local_path": code_archive_path,
            "name": os.environ["ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME"],
            "sha256": os.environ["ROBOCLAWS_STAGE_CODE_ARCHIVE_SHA256"],
            "bytes": int(os.environ["ROBOCLAWS_STAGE_CODE_ARCHIVE_BYTES"] or "0"),
        },
    },
    "source_assets": {
        "molmospaces_assets_dir": os.environ["ROBOCLAWS_STAGE_ASSETS_SOURCE"],
        "molmospaces_assets_size": du(os.environ["ROBOCLAWS_STAGE_ASSETS_SOURCE"]),
        "molmospaces_cache_dir": os.environ["ROBOCLAWS_STAGE_CACHE_SOURCE"],
        "molmospaces_cache_size": du(os.environ["ROBOCLAWS_STAGE_CACHE_SOURCE"]),
        "map_bundle": os.environ["ROBOCLAWS_STAGE_MAP_BUNDLE"],
        "map_bundle_size": du(str(repo_root / os.environ["ROBOCLAWS_STAGE_MAP_BUNDLE"])),
    },
    "staged_assets": {
        "mode": os.environ["ROBOCLAWS_STAGE_ASSET_MODE"],
        "include_grasps": os.environ["ROBOCLAWS_STAGE_INCLUDE_GRASPS"] == "true",
        "paths": staged_paths,
        "archive": {
            "local_path": archive_path,
            "name": os.environ["ROBOCLAWS_STAGE_ARCHIVE_NAME"],
            "sha256": os.environ["ROBOCLAWS_STAGE_ARCHIVE_SHA256"],
            "bytes": int(os.environ["ROBOCLAWS_STAGE_ARCHIVE_BYTES"] or "0"),
            "cloudml_cache_root": "/mnt/cloudml/output/roboclaws-asset-cache/cleanup-focused",
        },
    },
    "required_cloudml_checks": [
        "asset-cache/molmospaces/assets/mjthor_data_type_to_source_to_versions.json",
        "asset-cache/molmospaces/cache/mjthor_data_type_to_source_to_versions.json",
        "asset-cache/molmospaces/cache/scenes/procthor-10k-val",
        "asset-cache/molmospaces/cache/grasps/droid_objaverse",
        "asset-cache/molmospaces/assets/scenes/procthor-10k-val/val_0.xml",
        "asset-cache/molmospaces/assets/scenes/procthor-10k-val/val_0.json",
        "asset-cache/molmospaces/assets/scenes/procthor-10k-val/val_0_metadata.json",
        "asset-cache/molmospaces/assets/scenes/procthor-10k-val/mjthor_resources_combined_meta.json.gz",
        "asset-cache/molmospaces/assets/scenes/procthor-10k-val/mjthor_resource_file_to_size_mb.json",
        "asset-cache/molmospaces/assets/objects/thor",
        "asset-cache/molmospaces/assets/robots/rby1m",
        "asset-cache/roboclaws/assets/maps/molmospaces/procthor-10k-val/0/map.yaml",
        "asset-cache/roboclaws/assets/maps/molmospaces/procthor-10k-val/0/semantics.json",
    ],
    "eval": {
        "minimal_real_cleanup_product": (
            "just run::surface surface=household-world world=molmospaces/val_0 "
            "backend=mujoco preset=cleanup agent_engine=direct-runner "
            "evidence_lane=world-public-labels seed=7 "
            "scenario_setup=relocate-cleanup-related-objects relocation_count=5 "
            "map_bundle=assets/maps/molmospaces/procthor-10k-val/0 "
            "output_dir=/mnt/cloudml/output/roboclaws-cleanup-runs/<stamp>"
        ),
        "minimal_real_cleanup_eval": (
            "ROBOCLAWS_CLOUDML_RUN_MODE=eval-focused "
            "just agent::eval suite=smoke_regression budget=focused "
            "output_dir=/mnt/cloudml/output/roboclaws-evals"
        ),
        "pass_k_cleanup": (
            "just agent::eval suite=cleanup_capability budget=focused "
            "output_dir=/mnt/cloudml/output/roboclaws-evals"
        ),
    },
}
Path(os.environ["ROBOCLAWS_STAGE_MANIFEST_PATH"]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

echo "stage_dir=$stage_dir"
echo "manifest=$manifest_path"
echo "juicefs_url=$juicefs_url"
echo "asset_mode=$asset_mode"
if [[ -n "$archive_path" ]]; then
  echo "archive=$archive_path"
  echo "archive_sha256=$archive_sha256"
  echo "archive_bytes=$archive_bytes"
fi
echo "code_archive=$code_archive_path"
echo "code_archive_sha256=$code_archive_sha256"
echo "code_archive_bytes=$code_archive_bytes"
echo "upload_dry_run_command=$executor_root/exe storage juicefs upload --local_dir '$stage_dir' --url '$juicefs_url' --dry_run --json"
echo "upload_command=$executor_root/exe storage juicefs upload --local_dir '$stage_dir' --url '$juicefs_url' --json"

if [[ "$run_upload_dry_run" == "true" ]]; then
  run_executor storage juicefs upload \
    --local_dir "$stage_dir" \
    --url "$juicefs_url" \
    --dry_run \
    --json
fi

if [[ "$run_upload" == "true" ]]; then
  run_executor storage juicefs upload \
    --local_dir "$stage_dir" \
    --url "$juicefs_url" \
    --json
fi
