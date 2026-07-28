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
  test -f "$path"
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

if [[ -f "$asset_dir/roboclaws/assets/maps/molmospaces/procthor-10k-val/0/map.yaml" ]]; then
  mkdir -p assets/maps/molmospaces/procthor-10k-val
  rm -rf assets/maps/molmospaces/procthor-10k-val/0
  ln -sfn \
    "$asset_dir/roboclaws/assets/maps/molmospaces/procthor-10k-val/0" \
    assets/maps/molmospaces/procthor-10k-val/0
fi

export ROBOCLAWS_EVAL_EXECUTION_TARGET=cloudml
export ROBOCLAWS_EVAL_WORKER_POOL="$ROBOCLAWS_CLOUDML_WORKER_POOL"
export ROBOCLAWS_EVAL_CLOUDML_JOB_ID="${CLOUDML_TASK_ID:-${CML_JOB_ID:-}}"
export ROBOCLAWS_EVAL_CLOUDML_POD_NAME="${HOSTNAME:-}"

if [[ "$ROBOCLAWS_CLOUDML_WORKER_POOL" == "cloudml-r49" ]]; then
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
