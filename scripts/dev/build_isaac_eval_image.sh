#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
isaaclab_source="${ROBOCLAWS_ISAACLAB_SOURCE:-$repo_root/.venv-isaaclab-src/IsaacLab-v3}"
isaaclab_revision="ffff603eafc6b74264a5261cc0183d6a65390d78"
local_image="${ROBOCLAWS_ISAAC_LOCAL_IMAGE:-roboclaws-eval:isaac-local}"
remote_image="${ROBOCLAWS_ISAAC_REMOTE_IMAGE:-}"
output_dir="${ROBOCLAWS_ISAAC_OUTPUT_DIR:-/tmp/roboclaws-isaac-image-smoke}"

source_revision="${ROBOCLAWS_ISAACLAB_SOURCE_REVISION:-}"
if [[ -d "$isaaclab_source/.git" ]]; then
  source_revision="$(git -C "$isaaclab_source" rev-parse HEAD)"
elif [[ -f "${isaaclab_source}.revision" ]]; then
  source_revision="$(<"${isaaclab_source}.revision")"
fi
if [[ "$source_revision" != "$isaaclab_revision" ]]; then
  echo "error: Isaac Lab source must be pinned at $isaaclab_revision" >&2
  exit 2
fi
if [[ "${ROBOCLAWS_ISAAC_IMAGE_PUSH:-false}" == "true" ]]; then
  if [[ "${ROBOCLAWS_ISAAC_IMAGE_PUBLICATION_APPROVED:-false}" != "true" ]]; then
    echo "error: image push requires ROBOCLAWS_ISAAC_IMAGE_PUBLICATION_APPROVED=true" >&2
    exit 2
  fi
  if [[ -z "$remote_image" ]]; then
    echo "error: image push requires ROBOCLAWS_ISAAC_REMOTE_IMAGE" >&2
    exit 2
  fi
fi

build_args=(
  -f "$repo_root/Dockerfile.eval.isaac"
  --build-context "isaaclab-source=$isaaclab_source"
  -t "$local_image"
)
if [[ -n "$remote_image" ]]; then
  build_args+=(-t "$remote_image")
fi
docker build "${build_args[@]}" "$repo_root"

ROBOCLAWS_ISAAC_IMAGE="$local_image" \
ROBOCLAWS_ISAAC_OUTPUT_DIR="$output_dir" \
  "$repo_root/scripts/dev/run_isaac_eval_image_offline_smoke.sh"

image_id="$(docker image inspect --format '{{.Id}}' "$local_image")"
image_bytes="$(docker image inspect --format '{{.Size}}' "$local_image")"
echo "local_image=$local_image"
echo "image_id=$image_id"
echo "image_bytes=$image_bytes"

if [[ "${ROBOCLAWS_ISAAC_IMAGE_PUSH:-false}" == "true" ]]; then
  docker push "$remote_image"
else
  echo "push_skipped=true"
fi
