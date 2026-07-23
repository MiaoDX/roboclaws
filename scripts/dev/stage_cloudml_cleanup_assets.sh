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
content_rel="${ROBOCLAWS_JUICEFS_CONTENT_REL:-roboclaws-content}"
content_cache_root="${ROBOCLAWS_STAGE_CONTENT_CACHE_DIR:-/tmp/roboclaws-cloudml-content-cache}"
asset_mode="${ROBOCLAWS_STAGE_ASSET_MODE:-archive}"
default_scene_source="${ROBOCLAWS_STAGE_SCENE_SOURCE:-procthor-10k-val}"
default_scene_index="${ROBOCLAWS_STAGE_SCENE_INDEX:-0}"
scene_specs_raw="${ROBOCLAWS_STAGE_SCENES:-${default_scene_source}/${default_scene_index}}"
archive_name_override="${ROBOCLAWS_STAGE_ARCHIVE_NAME:-}"
code_archive_name="${ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME:-roboclaws-code-${code_short}.tar.gz}"
map_bundle_override="${ROBOCLAWS_STAGE_MAP_BUNDLE:-}"
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
  ROBOCLAWS_STAGE_CONTENT_CACHE_DIR   Default: /tmp/roboclaws-cloudml-content-cache
  ROBOCLAWS_JUICEFS_INPUT_REL         Default: roboclaws-assets/cleanup-focused
                                      under the CloudML /mnt/cloudml/input mount.
  ROBOCLAWS_JUICEFS_CONTENT_REL       Default: roboclaws-content
                                      Immutable assets/code root on JuiceFS.
  ROBOCLAWS_JUICEFS_URL               Full cloud.mioffice.cn JuiceFS vol-detail URL.
  ROBOCLAWS_STAGE_ASSET_MODE          archive. Default: archive.
  ROBOCLAWS_STAGE_ARCHIVE_NAME        Default: cleanup-focused-molmospaces-val0.tar.gz
  ROBOCLAWS_STAGE_SCENE_SOURCE        Default: procthor-10k-val
  ROBOCLAWS_STAGE_SCENE_INDEX         Default: 0
  ROBOCLAWS_STAGE_SCENES              Comma-separated SOURCE/INDEX list. Overrides
                                      the single-scene source/index pair.
  ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME   Default: roboclaws-code-<code>.tar.gz
  ROBOCLAWS_STAGE_MAP_BUNDLE          Default: assets/maps/molmospaces/<scene-source>/<scene-index>
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

IFS=',' read -r -a requested_scene_specs <<< "$scene_specs_raw"
scene_specs=()
scene_sources=()
scene_indices=()
scene_names=()
scene_rels=()
map_bundles=()
declare -A seen_scene_specs=()
for raw_spec in "${requested_scene_specs[@]}"; do
  spec="${raw_spec//[[:space:]]/}"
  scene_source="${spec%/*}"
  scene_index="${spec##*/}"
  if [[ "$scene_source" == "$spec" || ! "$scene_source" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "error: scene must be SOURCE/INDEX with a safe source: $raw_spec" >&2
    exit 2
  fi
  if [[ ! "$scene_index" =~ ^[0-9]+$ ]]; then
    echo "error: scene index must be a non-negative integer: $raw_spec" >&2
    exit 2
  fi
  normalized="${scene_source}/${scene_index}"
  if [[ -n "${seen_scene_specs[$normalized]:-}" ]]; then
    continue
  fi
  seen_scene_specs[$normalized]=1
  scene_specs+=("$normalized")
  scene_sources+=("$scene_source")
  scene_indices+=("$scene_index")
  scene_names+=("val_${scene_index}")
  scene_rels+=("scenes/${scene_source}")
  map_bundles+=("assets/maps/molmospaces/${scene_source}/${scene_index}")
done
if [[ "${#scene_specs[@]}" -eq 0 ]]; then
  echo "error: at least one CloudML staging scene is required" >&2
  exit 2
fi
if [[ -n "$map_bundle_override" ]]; then
  if [[ "${#scene_specs[@]}" -ne 1 ]]; then
    echo "error: ROBOCLAWS_STAGE_MAP_BUNDLE is only valid for one staged scene" >&2
    exit 2
  fi
  map_bundles=("$map_bundle_override")
fi
scene_specs_csv="$(IFS=,; echo "${scene_specs[*]}")"
if [[ -n "$archive_name_override" ]]; then
  archive_name="$archive_name_override"
elif [[ "${#scene_specs[@]}" -eq 1 ]]; then
  archive_name="cleanup-focused-molmospaces-val${scene_indices[0]}.tar.gz"
else
  archive_name="cleanup-focused-molmospaces-scenes.tar.gz"
fi

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  echo "error: repo-local .venv is required to discover MolmoSpaces assets" >&2
  exit 1
fi

if [[ ("$run_upload_dry_run" == "true" || "$run_upload" == "true") && ! -x "$executor_root/exe" ]]; then
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

upload_content_if_missing() {
  local label="$1"
  local local_dir="$2"
  local url="$3"
  local markers="$4"
  local probe_output cache_ready
  if ! probe_output="$(run_executor storage juicefs probe \
    --url "$url" --markers "$markers" --max_depth 0 --json)"; then
    echo "error: failed to probe CloudML $label content cache" >&2
    exit 1
  fi
  if ! cache_ready="$(printf '%s' "$probe_output" | "$repo_root/.venv/bin/python" -c \
    'import json, sys; p=json.load(sys.stdin); assert p.get("status") == "ok" and int(p.get("exit_code") or 0) == 0; markers=sys.argv[1].split(","); print("true" if any(all((hit.get("markers") or {}).get(marker, {}).get("exists") is True for marker in markers) for hit in p.get("hits") or []) else "false")' \
    "$markers")"; then
    echo "error: CloudML $label content cache probe returned invalid JSON" >&2
    exit 1
  fi
  if [[ "$cache_ready" == "true" ]]; then
    echo "${label}_upload=reused"
    return
  fi
  run_executor storage juicefs upload \
    --local_dir "$local_dir" \
    --url "$url" \
    --no_manifest \
    --json
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

declare -A seen_scene_sources=()
cache_resource_paths=()
for index in "${!scene_specs[@]}"; do
  scene_source="${scene_sources[$index]}"
  scene_name="${scene_names[$index]}"
  scene_rel="${scene_rels[$index]}"
  require_path "$assets_source/$scene_rel/${scene_name}.xml" "MolmoSpaces $scene_name scene XML"
  require_path "$assets_source/$scene_rel/${scene_name}.json" "MolmoSpaces $scene_name scene metadata"
  require_path "$assets_source/$scene_rel/${scene_name}_metadata.json" "MolmoSpaces $scene_name scene runtime metadata"
  require_path "$assets_source/$scene_rel/${scene_name}_ceiling.xml" "MolmoSpaces $scene_name ceiling scene XML"
  require_path "$assets_source/$scene_rel/${scene_name}_assets" "MolmoSpaces $scene_name local mesh assets"
  require_path "$assets_source/$scene_rel/mjthor_resources_combined_meta.json.gz" "MolmoSpaces $scene_source combined trie metadata"
  require_path "$assets_source/$scene_rel/mjthor_resource_file_to_size_mb.json" "MolmoSpaces $scene_source remote manifest"
  require_path "$assets_source/$scene_rel/.${scene_source}_${scene_name}.tar.zst_complete_links" "MolmoSpaces $scene_name link completion flag"
  if [[ -z "${seen_scene_sources[$scene_source]:-}" ]]; then
    seen_scene_sources[$scene_source]=1
    cache_resource_paths+=("scenes/$scene_source")
  fi
done
require_path "$assets_source/objects/thor" \
  "MolmoSpaces THOR object assets"
require_path "$assets_source/robots/rby1m" \
  "MolmoSpaces RBY1M robot assets"
require_path "$assets_source/mjthor_data_type_to_source_to_versions.json" \
  "MolmoSpaces installed-source manifest"
require_path "$cache_source/mjthor_data_type_to_source_to_versions.json" \
  "MolmoSpaces cache manifest"
cache_resource_paths+=("objects/objaverse" "grasps/droid_objaverse")
for relative in "${cache_resource_paths[@]}"; do
  require_path "$cache_source/$relative" "MolmoSpaces versioned $relative cache"
done
for map_bundle in "${map_bundles[@]}"; do
  case "$map_bundle" in
    /*|../*|*/../*)
      echo "error: map bundle must be a repo-relative path: $map_bundle" >&2
      exit 1
      ;;
  esac
  require_path "$repo_root/$map_bundle/map.yaml" "Roboclaws Nav2 map bundle map.yaml"
  require_path "$repo_root/$map_bundle/semantics.json" "Roboclaws Nav2 map bundle semantics.json"
done

clean_stage_dir "$stage_dir"
mkdir -p \
  "$content_cache_root/assets/by-source" \
  "$content_cache_root/assets/by-sha256" \
  "$content_cache_root/code/by-commit" \
  "$content_cache_root/code/by-sha256" \
  "$content_cache_root/tmp"

asset_source_fingerprint="$("$repo_root/.venv/bin/python" - \
  "$assets_source" "$cache_source" "$repo_root" "$include_grasps" "$scene_specs_csv" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

assets = Path(sys.argv[1])
cache = Path(sys.argv[2])
repo_root = Path(sys.argv[3])
include_grasps = sys.argv[4] == "true"
scene_specs = []
for value in sys.argv[5].split(","):
    source, raw_index = value.rsplit("/", 1)
    scene_specs.append((source, int(raw_index)))
asset_paths = [Path("mjthor_data_type_to_source_to_versions.json")]
for scene_source, scene_index in scene_specs:
    scene_name = f"val_{scene_index}"
    scene_dir = Path("scenes") / scene_source
    asset_paths.extend(
        [
            scene_dir / f"{scene_name}.xml",
            scene_dir / f"{scene_name}.json",
            scene_dir / f"{scene_name}_metadata.json",
            scene_dir / f"{scene_name}_ceiling.xml",
            scene_dir / f"{scene_name}_assets",
            scene_dir / "mjthor_resources_combined_meta.json.gz",
            scene_dir / "mjthor_resource_file_to_size_mb.json",
            scene_dir / f".{scene_source}_{scene_name}.tar.zst_complete_links",
        ]
    )
asset_paths.extend([Path("objects/thor"), Path("robots/rby1m")])
asset_paths = list(dict.fromkeys(asset_paths))
if include_grasps:
    asset_paths.append(Path("grasps/droid"))
cache_paths = [Path("mjthor_data_type_to_source_to_versions.json")]
cache_paths.extend(Path("scenes") / source for source, _index in scene_specs)
cache_paths.extend([Path("objects/objaverse"), Path("grasps/droid_objaverse")])
cache_paths = list(dict.fromkeys(cache_paths))
map_paths = [
    Path("assets/maps/molmospaces") / source / str(index)
    for source, index in scene_specs
]


def describe(root: Path, path: Path):
    stat = path.stat()
    return {
        "path": path.relative_to(root).as_posix(),
        "kind": "dir" if path.is_dir() else "file",
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "link": os.readlink(path) if path.is_symlink() else "",
    }


def entries(root: Path, relative: Path):
    start = root / relative
    if not start.is_dir():
        yield describe(root, start)
        return
    for current, directories, files in os.walk(start, followlinks=True):
        directories.sort()
        files.sort()
        yield describe(root, Path(current))
        for name in files:
            yield describe(root, Path(current) / name)


digest = hashlib.sha256()
digest.update(
    json.dumps(
        {
            "profile": "cleanup-focused-v4",
            "include_grasps": include_grasps,
            "scenes": [f"{source}/{index}" for source, index in scene_specs],
        },
        sort_keys=True,
    ).encode()
)
for label, root, paths in (
    ("assets", assets, asset_paths),
    ("cache", cache, cache_paths),
    ("map", repo_root, map_paths),
):
    for relative in paths:
        for entry in entries(root, relative):
            digest.update(label.encode())
            digest.update(b"\0")
            digest.update(json.dumps(entry, sort_keys=True).encode())
            digest.update(b"\0")
print(digest.hexdigest())
PY
)"

archive_path=""
archive_sha256=""
archive_bytes=""
asset_cache_reused="false"
code_archive_path=""
code_archive_sha256=""
code_archive_bytes=""
code_cache_reused="false"
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
    asset_ref="$content_cache_root/assets/by-source/${asset_source_fingerprint}.ref"
    exec 9>"${asset_ref}.lock"
    flock 9
    if [[ -f "$asset_ref" ]]; then
      read -r archive_sha256 archive_bytes < "$asset_ref"
      archive_path="$content_cache_root/assets/by-sha256/$archive_sha256/$archive_name"
      if [[ -f "$archive_path" && -f "${archive_path}.sha256" ]]; then
        asset_cache_reused="true"
      else
        archive_sha256=""
        archive_bytes=""
        archive_path=""
      fi
    fi
    if [[ "$asset_cache_reused" != "true" ]]; then
      archive_tmp="$(mktemp "$content_cache_root/tmp/${archive_name}.XXXXXX")"
      archive_manifest_dir="$(mktemp -d "$content_cache_root/tmp/archive-manifest.XXXXXX")"
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
      tar_paths=("objects/thor" "robots/rby1m")
      declare -A staged_scene_sources=()
      for index in "${!scene_specs[@]}"; do
        scene_source="${scene_sources[$index]}"
        scene_name="${scene_names[$index]}"
        scene_rel="${scene_rels[$index]}"
        tar_paths+=(
          "$scene_rel/${scene_name}.xml"
          "$scene_rel/${scene_name}.json"
          "$scene_rel/${scene_name}_metadata.json"
          "$scene_rel/${scene_name}_ceiling.xml"
          "$scene_rel/${scene_name}_assets"
          "$scene_rel/.${scene_source}_${scene_name}.tar.zst_complete_links"
        )
        if [[ -z "${staged_scene_sources[$scene_source]:-}" ]]; then
          staged_scene_sources[$scene_source]=1
          tar_paths+=(
            "$scene_rel/mjthor_resources_combined_meta.json.gz"
            "$scene_rel/mjthor_resource_file_to_size_mb.json"
          )
        fi
      done
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
        "${map_bundles[@]}" \
        | gzip -n > "$archive_tmp"
      rm -rf "$archive_manifest_dir"
      archive_sha256="$(sha256sum "$archive_tmp" | awk '{print $1}')"
      archive_bytes="$(stat -c '%s' "$archive_tmp")"
      asset_cache_dir="$content_cache_root/assets/by-sha256/$archive_sha256"
      mkdir -p "$asset_cache_dir"
      archive_path="$asset_cache_dir/$archive_name"
      if [[ ! -f "$archive_path" ]]; then
        mv "$archive_tmp" "$archive_path"
      else
        rm -f "$archive_tmp"
      fi
      printf '%s  %s\n' "$archive_sha256" "$archive_name" > "${archive_path}.sha256"
      printf '%s %s\n' "$archive_sha256" "$archive_bytes" > "${asset_ref}.tmp"
      mv "${asset_ref}.tmp" "$asset_ref"
    fi
    flock -u 9
    staged_paths+=("assets/$archive_name" "assets/${archive_name}.sha256")
    ;;
  *)
    echo "error: unsupported ROBOCLAWS_STAGE_ASSET_MODE '$asset_mode'" >&2
    echo "expected archive" >&2
    exit 1
    ;;
esac

code_ref_dir="$content_cache_root/code/by-commit/$code_commit"
mkdir -p "$code_ref_dir"
exec 8>"${code_ref_dir}.lock"
flock 8
if [[ -f "$code_ref_dir/archive.ref" ]]; then
  read -r code_archive_sha256 code_archive_bytes < "$code_ref_dir/archive.ref"
  code_archive_path="$content_cache_root/code/by-sha256/$code_archive_sha256/$code_archive_name"
  if [[ -f "$code_archive_path" && -f "${code_archive_path}.sha256" ]]; then
    code_cache_reused="true"
  fi
fi
if [[ "$code_cache_reused" != "true" ]]; then
  code_tmp="$(mktemp -d "$content_cache_root/tmp/code-archive.XXXXXX")"
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
  code_archive_tmp="$(mktemp "$content_cache_root/tmp/${code_archive_name}.XXXXXX")"
  tar "${reproducible_tar_args[@]}" -cf - -C "$code_tmp" roboclaws.git \
    | gzip -n > "$code_archive_tmp"
  rm -rf "$code_tmp"
  code_archive_sha256="$(sha256sum "$code_archive_tmp" | awk '{print $1}')"
  code_archive_bytes="$(stat -c '%s' "$code_archive_tmp")"
  code_cache_dir="$content_cache_root/code/by-sha256/$code_archive_sha256"
  mkdir -p "$code_cache_dir"
  code_archive_path="$code_cache_dir/$code_archive_name"
  if [[ ! -f "$code_archive_path" ]]; then
    mv "$code_archive_tmp" "$code_archive_path"
  else
    rm -f "$code_archive_tmp"
  fi
  printf '%s  %s\n' "$code_archive_sha256" "$code_archive_name" > "${code_archive_path}.sha256"
  printf '%s %s\n' "$code_archive_sha256" "$code_archive_bytes" > "$code_ref_dir/archive.ref.tmp"
  mv "$code_ref_dir/archive.ref.tmp" "$code_ref_dir/archive.ref"
fi
flock -u 8
staged_paths+=("code/$code_archive_name" "code/${code_archive_name}.sha256")

manifest_path="$stage_dir/roboclaws_cloudml_cleanup_assets.json"
export ROBOCLAWS_STAGE_MANIFEST_PATH="$manifest_path"
export ROBOCLAWS_STAGE_REPO_ROOT="$repo_root"
export ROBOCLAWS_STAGE_DIR_RESOLVED="$stage_dir"
export ROBOCLAWS_STAGE_INPUT_REL="$input_rel"
export ROBOCLAWS_STAGE_JUICEFS_URL="$juicefs_url"
export ROBOCLAWS_STAGE_CONTENT_REL="$content_rel"
export ROBOCLAWS_STAGE_CONTENT_CACHE_ROOT="$content_cache_root"
export ROBOCLAWS_STAGE_CODE_COMMIT="$code_commit"
export ROBOCLAWS_STAGE_ASSETS_SOURCE="$assets_source"
export ROBOCLAWS_STAGE_CACHE_SOURCE="$cache_source"
export ROBOCLAWS_STAGE_ASSET_MODE="$asset_mode"
export ROBOCLAWS_STAGE_ARCHIVE_NAME="$archive_name"
export ROBOCLAWS_STAGE_ARCHIVE_PATH="$archive_path"
export ROBOCLAWS_STAGE_ARCHIVE_SHA256="$archive_sha256"
export ROBOCLAWS_STAGE_ARCHIVE_BYTES="$archive_bytes"
export ROBOCLAWS_STAGE_ASSET_SOURCE_FINGERPRINT="$asset_source_fingerprint"
export ROBOCLAWS_STAGE_ASSET_CACHE_REUSED="$asset_cache_reused"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_NAME="$code_archive_name"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_PATH="$code_archive_path"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_SHA256="$code_archive_sha256"
export ROBOCLAWS_STAGE_CODE_ARCHIVE_BYTES="$code_archive_bytes"
export ROBOCLAWS_STAGE_CODE_CACHE_REUSED="$code_cache_reused"
export ROBOCLAWS_STAGE_SCENES="$scene_specs_csv"
export ROBOCLAWS_STAGE_MAP_BUNDLES="$(IFS=,; echo "${map_bundles[*]}")"
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
scene_specs = []
map_bundles = os.environ["ROBOCLAWS_STAGE_MAP_BUNDLES"].split(",")
for position, value in enumerate(os.environ["ROBOCLAWS_STAGE_SCENES"].split(",")):
    source, raw_index = value.rsplit("/", 1)
    index = int(raw_index)
    world = (
        f"molmospaces/val_{index}"
        if source == "procthor-10k-val" and index in {0, 1, 2, 3, 4, 5, 7, 9}
        else f"molmospaces/{source}/{index}"
    )
    scene_specs.append(
        {
            "scene_id": f"{source}/{index}",
            "source": source,
            "index": index,
            "name": f"val_{index}",
            "world": world,
            "map_bundle": map_bundles[position],
        }
    )

def du(path: str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        return "missing"
    try:
        return subprocess.check_output(["du", "-sh", str(candidate)], text=True).split()[0]
    except Exception:
        return "unavailable"

payload = {
    "schema": "roboclaws_cloudml_content_manifest_v2",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "stage_dir": str(stage_dir),
    "juicefs": {
        "run_input_rel": os.environ["ROBOCLAWS_STAGE_INPUT_REL"],
        "run_input_url": os.environ["ROBOCLAWS_STAGE_JUICEFS_URL"],
        "content_rel": os.environ["ROBOCLAWS_STAGE_CONTENT_REL"],
        "run_input_mount_path": "/mnt/cloudml/input",
        "asset_mount_path": "/mnt/cloudml/assets",
        "code_mount_path": "/mnt/cloudml/code",
    },
    "local_cache": {
        "root": os.environ["ROBOCLAWS_STAGE_CONTENT_CACHE_ROOT"],
        "asset_source_fingerprint": os.environ["ROBOCLAWS_STAGE_ASSET_SOURCE_FINGERPRINT"],
        "asset_reused": os.environ["ROBOCLAWS_STAGE_ASSET_CACHE_REUSED"] == "true",
        "code_reused": os.environ["ROBOCLAWS_STAGE_CODE_CACHE_REUSED"] == "true",
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
        "scenes": scene_specs,
        "molmospaces_assets_dir": os.environ["ROBOCLAWS_STAGE_ASSETS_SOURCE"],
        "molmospaces_assets_size": du(os.environ["ROBOCLAWS_STAGE_ASSETS_SOURCE"]),
        "molmospaces_cache_dir": os.environ["ROBOCLAWS_STAGE_CACHE_SOURCE"],
        "molmospaces_cache_size": du(os.environ["ROBOCLAWS_STAGE_CACHE_SOURCE"]),
        "map_bundle_sizes": {
            scene["scene_id"]: du(str(repo_root / scene["map_bundle"]))
            for scene in scene_specs
        },
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
        },
    },
    "required_cloudml_checks": [
        "asset-cache/molmospaces/assets/mjthor_data_type_to_source_to_versions.json",
        "asset-cache/molmospaces/cache/mjthor_data_type_to_source_to_versions.json",
        "asset-cache/molmospaces/cache/grasps/droid_objaverse",
        "asset-cache/molmospaces/assets/objects/thor",
        "asset-cache/molmospaces/assets/robots/rby1m",
    ] + [
        path
        for scene in scene_specs
        for path in (
            f"asset-cache/molmospaces/cache/scenes/{scene['source']}",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/{scene['name']}.xml",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/{scene['name']}.json",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/{scene['name']}_metadata.json",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/{scene['name']}_ceiling.xml",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/{scene['name']}_assets",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/mjthor_resources_combined_meta.json.gz",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/mjthor_resource_file_to_size_mb.json",
            f"asset-cache/molmospaces/assets/scenes/{scene['source']}/.{scene['source']}_{scene['name']}.tar.zst_complete_links",
            f"asset-cache/roboclaws/{scene['map_bundle']}/map.yaml",
            f"asset-cache/roboclaws/{scene['map_bundle']}/semantics.json",
        )
    ],
    "eval": {
        "minimal_real_cleanup_product": (
            f"just run::surface surface=household-world world={scene_specs[0]['world']} "
            "backend=mujoco preset=cleanup agent_engine=direct-runner "
            "evidence_lane=world-public-labels seed=7 "
            "scenario_setup=relocate-cleanup-related-objects relocation_count=5 "
            f"map_bundle={scene_specs[0]['map_bundle']} "
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
echo "content_cache_root=$content_cache_root"
echo "asset_mode=$asset_mode"
if [[ -n "$archive_path" ]]; then
  echo "archive=$archive_path"
  echo "archive_sha256=$archive_sha256"
  echo "archive_bytes=$archive_bytes"
  echo "asset_cache_reused=$asset_cache_reused"
fi
echo "code_archive=$code_archive_path"
echo "code_archive_sha256=$code_archive_sha256"
echo "code_archive_bytes=$code_archive_bytes"
echo "code_cache_reused=$code_cache_reused"

content_url_base="https://cloud.mioffice.cn/juicefs/vol-detail?cluster=wlcb-cloudml&name=robot-intelligent-planning-data&path=/dongxu/gpu_perf/gpu_perf/$content_rel"
asset_url="$content_url_base/assets/by-sha256/$archive_sha256"
code_url="$content_url_base/code/by-sha256/$code_archive_sha256"
echo "asset_upload_command=$executor_root/exe storage juicefs upload --local_dir '$(dirname "$archive_path")' --url '$asset_url' --json"
echo "code_upload_command=$executor_root/exe storage juicefs upload --local_dir '$(dirname "$code_archive_path")' --url '$code_url' --json"
echo "run_input_upload_command=$executor_root/exe storage juicefs upload --local_dir '$stage_dir' --url '$juicefs_url' --json"

if [[ "$run_upload_dry_run" == "true" ]]; then
  run_executor storage juicefs upload \
    --local_dir "$(dirname "$archive_path")" \
    --url "$asset_url" \
    --dry_run \
    --json
  run_executor storage juicefs upload \
    --local_dir "$(dirname "$code_archive_path")" \
    --url "$code_url" \
    --dry_run \
    --json
  run_executor storage juicefs upload \
    --local_dir "$stage_dir" \
    --url "$juicefs_url" \
    --dry_run \
    --json
fi

if [[ "$run_upload" == "true" ]]; then
  upload_content_if_missing "asset" "$(dirname "$archive_path")" "$asset_url" \
    "$archive_name,${archive_name}.sha256"
  upload_content_if_missing "code" "$(dirname "$code_archive_path")" "$code_url" \
    "$code_archive_name,${code_archive_name}.sha256"
  run_executor storage juicefs upload \
    --local_dir "$stage_dir" \
    --url "$juicefs_url" \
    --json
fi
