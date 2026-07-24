#!/usr/bin/env bash
set -Eeuo pipefail

required_env=(
  ROBOCLAWS_CLOUDML_CODE_COMMIT
  ROBOCLAWS_CLOUDML_CODE_ARCHIVE
  ROBOCLAWS_CLOUDML_CODE_ARCHIVE_SHA256
  ROBOCLAWS_CLOUDML_ASSET_MANIFEST
  ROBOCLAWS_CLOUDML_ASSET_MANIFEST_SHA256
  ROBOCLAWS_CLOUDML_MANIFEST
  ROBOCLAWS_CLOUDML_ROW_IDS
  ROBOCLAWS_CLOUDML_SHARD_ID
  ROBOCLAWS_CLOUDML_WORKER_POOL
  ROBOCLAWS_CLOUDML_MAX_PARALLEL
  ROBOCLAWS_CLOUDML_OUTPUT_DIR
)
for name in "${required_env[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "error: missing $name" >&2
    exit 2
  fi
done

if [[ -n "${ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE:-}" ]]; then
  set +x
  if [[ ! -r "$ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE" ]]; then
    echo "error: provider environment file is not readable" >&2
    exit 2
  fi
  set -a
  # The adapter writes shell-quoted assignments for registry-approved keys only.
  source "$ROBOCLAWS_CLOUDML_PROVIDER_ENV_FILE"
  set +a
fi

repo_dir=/tmp/roboclaws-cloudml/repo/roboclaws.git
asset_dir=/tmp/roboclaws-cloudml/assets
marker_dir="${ROBOCLAWS_CLOUDML_OUTPUT_DIR}/markers"
marker_path="${marker_dir}/${ROBOCLAWS_CLOUDML_SHARD_ID}.json"
mkdir -p "$marker_dir"

write_marker() {
  local status="$1"
  local exit_code="$2"
  ROBOCLAWS_CLOUDML_MARKER_STATUS="$status" \
  ROBOCLAWS_CLOUDML_MARKER_EXIT_CODE="$exit_code" \
  ROBOCLAWS_CLOUDML_MARKER_PATH="$marker_path" \
    /opt/roboclaws/.venv/bin/python - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

payload = {
    "schema": "roboclaws_eval_harness_cloudml_terminal_v1",
    "shard_id": os.environ["ROBOCLAWS_CLOUDML_SHARD_ID"],
    "worker_pool": os.environ["ROBOCLAWS_CLOUDML_WORKER_POOL"],
    "row_ids": [
        item for item in os.environ["ROBOCLAWS_CLOUDML_ROW_IDS"].split(",") if item
    ],
    "status": os.environ["ROBOCLAWS_CLOUDML_MARKER_STATUS"],
    "exit_code": int(os.environ["ROBOCLAWS_CLOUDML_MARKER_EXIT_CODE"]),
    "code_commit": os.environ["ROBOCLAWS_CLOUDML_CODE_COMMIT"],
    "asset_manifest_sha256": os.environ.get(
        "ROBOCLAWS_CLOUDML_ASSET_MANIFEST_SHA256", ""
    ),
    "expected_image_digest": os.environ.get(
        "ROBOCLAWS_CLOUDML_EXPECTED_IMAGE_DIGEST", ""
    ),
    "isaac_proof_contract_sha256": os.environ.get(
        "ROBOCLAWS_CLOUDML_ISAAC_PROOF_CONTRACT_SHA256", ""
    ),
    "isaac_asset_group": os.environ.get("ROBOCLAWS_CLOUDML_ISAAC_ASSET_GROUP", ""),
    "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
Path(os.environ["ROBOCLAWS_CLOUDML_MARKER_PATH"]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

on_exit() {
  local exit_code=$?
  local status=failed
  if [[ "$exit_code" -eq 0 ]]; then
    status=succeeded
  fi
  write_marker "$status" "$exit_code"
}
trap on_exit EXIT

verify_sha256() {
  local path="$1"
  local expected="$2"
  local actual
  if [[ ! -f "$path" ]]; then
    echo "error: required checksum target is missing: $path" >&2
    exit 1
  fi
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "error: sha256 mismatch for $path" >&2
    exit 1
  fi
}

verify_sha256 \
  "$ROBOCLAWS_CLOUDML_CODE_ARCHIVE" \
  "$ROBOCLAWS_CLOUDML_CODE_ARCHIVE_SHA256"
verify_sha256 \
  "$ROBOCLAWS_CLOUDML_ASSET_MANIFEST" \
  "$ROBOCLAWS_CLOUDML_ASSET_MANIFEST_SHA256"
rm -rf "$(dirname "$repo_dir")"
mkdir -p "$(dirname "$repo_dir")"
tar -xzf "$ROBOCLAWS_CLOUDML_CODE_ARCHIVE" -C "$(dirname "$repo_dir")"
test -f "$repo_dir/.roboclaws_code_commit"
if [[ "$(cat "$repo_dir/.roboclaws_code_commit")" != "$ROBOCLAWS_CLOUDML_CODE_COMMIT" ]]; then
  echo "error: code archive commit does not match pinned commit" >&2
  exit 1
fi

if [[ -n "${ROBOCLAWS_CLOUDML_ASSET_ARCHIVE:-}" ]]; then
  verify_sha256 \
    "$ROBOCLAWS_CLOUDML_ASSET_ARCHIVE" \
    "$ROBOCLAWS_CLOUDML_ASSET_ARCHIVE_SHA256"
  rm -rf "$asset_dir"
  mkdir -p "$asset_dir"
  tar -xzf "$ROBOCLAWS_CLOUDML_ASSET_ARCHIVE" -C "$asset_dir"
  export MLSPACES_ASSETS_DIR="$asset_dir/molmospaces/assets"
  export MLSPACES_CACHE_DIR="$asset_dir/molmospaces/cache"
fi

isaac_asset_roots=()
if [[ "$ROBOCLAWS_CLOUDML_WORKER_POOL" == "cloudml-r49-isaac" ]]; then
  contract_path="$repo_dir/skills/eval-harness/catalog/cloudml_isaac_proof.json"
  verify_sha256 "$contract_path" "$ROBOCLAWS_CLOUDML_ISAAC_PROOF_CONTRACT_SHA256"
  mapfile -t isaac_asset_roots < <(
    /opt/roboclaws/.venv/bin/python - \
      "$ROBOCLAWS_CLOUDML_ASSET_MANIFEST" \
      "$ROBOCLAWS_CLOUDML_ISAAC_ASSET_GROUP" <<'PY'
import json
import re
import sys
from pathlib import PurePosixPath

payload = json.load(open(sys.argv[1], encoding="utf-8"))
isaac = payload.get("isaac") or {}
expected_group = sys.argv[2]
if isaac.get("asset_group") != expected_group:
    raise SystemExit(f"error: expected Isaac asset group {expected_group}")
for raw in isaac.get("roots") or []:
    path = PurePosixPath(str(raw))
    if path.is_absolute() or ".." in path.parts or not re.fullmatch(r"[A-Za-z0-9._/-]+", str(path)):
        raise SystemExit(f"error: unsafe Isaac asset root {raw!r}")
    print(path)
PY
  )
  for relative in "${isaac_asset_roots[@]}"; do
    source_path="$asset_dir/roboclaws/$relative"
    target_path="$repo_dir/$relative"
    if [[ ! -e "$source_path" ]]; then
      echo "error: staged Isaac asset root is missing: $relative" >&2
      exit 2
    fi
    mkdir -p "$(dirname "$target_path")"
    rm -rf -- "$target_path"
    ln -s "$source_path" "$target_path"
  done
fi

object_cache_root="$MLSPACES_CACHE_DIR/objects"
if [[ -d "$object_cache_root" ]]; then
  mkdir -p "$MLSPACES_ASSETS_DIR/objects"
  for object_source_root in "$object_cache_root"/*; do
    [[ -d "$object_source_root" ]] || continue
    object_versions=("$object_source_root"/*)
    if [[ "${#object_versions[@]}" -ne 1 || ! -d "${object_versions[0]}" ]]; then
      echo "error: expected one staged version under $object_source_root" >&2
      exit 2
    fi
    object_source="$(basename "$object_source_root")"
    object_link="$MLSPACES_ASSETS_DIR/objects/$object_source"
    if [[ -e "$object_link" || -L "$object_link" ]]; then
      rm -rf -- "$object_link"
    fi
    ln -s "${object_versions[0]}" "$object_link"
  done
fi

mapfile -t frozen_scene < <(
  /opt/roboclaws/.venv/bin/python - \
    "$ROBOCLAWS_CLOUDML_ASSET_MANIFEST" \
    "$ROBOCLAWS_CLOUDML_MANIFEST" \
    "$ROBOCLAWS_CLOUDML_ROW_IDS" <<'PY'
import json
import re
import sys

asset_payload = json.load(open(sys.argv[1], encoding="utf-8"))
harness = json.load(open(sys.argv[2], encoding="utf-8"))
row_ids = set(filter(None, sys.argv[3].split(",")))
selected_scenes = {
    scene["scene_id"]: scene
    for row in harness.get("rows", [])
    if row.get("row_id") in row_ids
    if (scene := (row.get("case") or {}).get("scene"))
}
if not selected_scenes:
    raise SystemExit(0)
if len(selected_scenes) != 1:
    raise SystemExit("error: CloudML shard contains more than one benchmark scene")
scene_id, selected = next(iter(selected_scenes.items()))
available = {
    scene.get("scene_id"): scene
    for scene in asset_payload.get("source_assets", {}).get("scenes", [])
    if isinstance(scene, dict)
}
if scene_id not in available:
    raise SystemExit(f"error: staged assets do not contain shard scene {scene_id}")
scene = available[scene_id]
source = scene.get("source")
index = scene.get("index")
map_bundle = scene.get("map_bundle")
world = scene.get("world")
if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", source):
    raise SystemExit("error: asset manifest scene source is invalid")
if isinstance(index, bool) or not isinstance(index, int) or index < 0:
    raise SystemExit("error: asset manifest scene index is invalid")
if not isinstance(map_bundle, str) or not re.fullmatch(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+", map_bundle):
    raise SystemExit("error: asset manifest map bundle is not a safe repo-relative path")
if selected.get("world") != world or selected.get("map_bundle") != map_bundle:
    raise SystemExit("error: staged scene identity does not match frozen benchmark case")
print(source)
print(index)
print(map_bundle)
print(world)
PY
)
if [[ "${#frozen_scene[@]}" -ne 0 && "${#frozen_scene[@]}" -ne 4 ]]; then
  echo "error: asset manifest did not yield a complete frozen scene identity" >&2
  exit 2
fi
map_bundle=""
if [[ "${#frozen_scene[@]}" -eq 4 ]]; then
  scene_source="${frozen_scene[0]}"
  scene_index="${frozen_scene[1]}"
  map_bundle="${frozen_scene[2]}"
  scene_world="${frozen_scene[3]}"
  scene_name="val_${scene_index}"
  scene_dir="$MLSPACES_ASSETS_DIR/scenes/$scene_source"
  test -f "$scene_dir/${scene_name}.xml"
  test -f "$scene_dir/${scene_name}.json"
  test -f "$scene_dir/${scene_name}_metadata.json"
  test -f "$scene_dir/${scene_name}_ceiling.xml"
  test -d "$scene_dir/${scene_name}_assets"
  test -f "$scene_dir/mjthor_resources_combined_meta.json.gz"
  test -f "$scene_dir/mjthor_resource_file_to_size_mb.json"
  test -f "$scene_dir/.${scene_source}_${scene_name}.tar.zst_complete_links"
  echo "cloudml_scene=${scene_world} source=${scene_source} index=${scene_index}"
fi

cd "$repo_dir"
ln -sfn /opt/roboclaws/.venv .venv
if [[ -x /opt/roboclaws/.venv-visual-grounding/bin/python ]]; then
  ln -sfn /opt/roboclaws/.venv-visual-grounding .venv-visual-grounding
fi
uv pip install \
  --python /opt/roboclaws/.venv/bin/python \
  --no-build-isolation \
  --no-deps \
  --editable "$repo_dir"

if [[ -n "$map_bundle" && -f "$asset_dir/roboclaws/$map_bundle/map.yaml" ]]; then
  mkdir -p "$(dirname "$map_bundle")"
  rm -rf "$map_bundle"
  ln -sfn \
    "$asset_dir/roboclaws/$map_bundle" \
    "$map_bundle"
  test -f "$map_bundle/map.yaml"
  test -f "$map_bundle/semantics.json"
fi

export ROBOCLAWS_EVAL_EXECUTION_TARGET=cloudml
export ROBOCLAWS_EVAL_WORKER_POOL="$ROBOCLAWS_CLOUDML_WORKER_POOL"
export ROBOCLAWS_EVAL_CLOUDML_JOB_ID="${CLOUDML_TASK_ID:-${CML_JOB_ID:-}}"
export ROBOCLAWS_EVAL_CLOUDML_POD_NAME="${HOSTNAME:-}"

if [[ "$ROBOCLAWS_CLOUDML_WORKER_POOL" == "cloudml-r49-isaac" ]]; then
  test -n "${ROBOCLAWS_CLOUDML_ISAAC_PROOF_CONTRACT_SHA256:-}"
  test -n "${ROBOCLAWS_CLOUDML_ISAAC_ASSET_GROUP:-}"
  if [[ "${ROBOCLAWS_CLOUDML_ISAAC_EULA_ACCEPTED:-false}" != "true" || "${OMNI_KIT_ACCEPT_EULA:-}" != "YES" ]]; then
    echo "error: Isaac CloudML worker requires explicit EULA acceptance" >&2
    exit 2
  fi
  test -x "${ROBOCLAWS_ISAACLAB_PYTHON:-}"
  "$ROBOCLAWS_ISAACLAB_PYTHON" - <<'PY'
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path

import torch

assert torch.cuda.is_available(), "CloudML Isaac worker did not expose a CUDA device"
versions = {
    "isaac_sim": Path("/isaac-sim/docs/py/VERSION").read_text().strip(),
    "isaac_sim_build": Path("/isaac-sim/VERSION").read_text().strip(),
    "isaac_lab": importlib.metadata.version("isaaclab"),
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
}
assert all(value and value != "unknown" for value in versions.values())
assert versions["isaac_sim"] == os.environ["ROBOCLAWS_ISAACSIM_VERSION"]
assert versions["isaac_sim_build"] == os.environ["ROBOCLAWS_ISAACSIM_BUILD"]
gpu = torch.cuda.get_device_name(0)
driver = subprocess.check_output(
    ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True
).strip()
print(json.dumps({"runtime": versions, "gpu": gpu, "driver": driver, "eula": True}, sort_keys=True))
PY
elif [[ "$ROBOCLAWS_CLOUDML_WORKER_POOL" == "cloudml-r49" ]]; then
  test -x .venv-visual-grounding/bin/python
  .venv-visual-grounding/bin/python - <<'PY'
import os
from pathlib import Path

import torch

assert torch.version.cuda, "CUDA-enabled Torch wheel is required"
assert torch.cuda.is_available(), "CloudML r49 worker did not expose a CUDA device"
model_dir = Path(os.environ["VISUAL_GROUNDING_DINO_MODEL_ID"])
assert (model_dir / "config.json").is_file(), "Grounding DINO config is missing"
assert (model_dir / "model.safetensors").is_file(), "Grounding DINO weights are missing"
assert (model_dir / ".revision").read_text().strip() == os.environ[
    "VISUAL_GROUNDING_DINO_MODEL_REVISION"
], "Grounding DINO revision does not match the image contract"
print(f"cloudml gpu ready: {torch.cuda.get_device_name(0)} cuda={torch.version.cuda}")
PY
fi

just agent::eval execute \
  "manifest=$ROBOCLAWS_CLOUDML_MANIFEST" \
  "row_id=$ROBOCLAWS_CLOUDML_ROW_IDS" \
  "max_parallel=$ROBOCLAWS_CLOUDML_MAX_PARALLEL" \
  "shard_id=$ROBOCLAWS_CLOUDML_SHARD_ID"
