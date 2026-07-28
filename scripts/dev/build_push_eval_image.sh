#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
date_stamp="${ROBOCLAWS_EVAL_DATE:-$(date +%Y%m%d)}"
env_ref="${ROBOCLAWS_EVAL_ENV_REF:-HEAD}"
code_ref="${ROBOCLAWS_EVAL_CODE_REF:-mi/main}"
image_variant="${ROBOCLAWS_EVAL_IMAGE_VARIANT:-cpu}"
case "$image_variant" in
  cpu|cuda) ;;
  *)
    echo "error: ROBOCLAWS_EVAL_IMAGE_VARIANT must be cpu or cuda, got '$image_variant'" >&2
    exit 2
    ;;
esac
dino_model_revision="${ROBOCLAWS_EVAL_DINO_MODEL_REVISION:-12bdfa3120f3e7ec7b434d90674b3396eccf88eb}"
dino_cache_dir="${ROBOCLAWS_EVAL_DINO_CACHE_DIR:-$HOME/.cache/huggingface/hub/models--IDEA-Research--grounding-dino-base}"
env_short="$(git -C "$repo_root" rev-parse --short=8 "$env_ref")"
code_short="$(git -C "$repo_root" rev-parse --short=12 "$code_ref")"
registry_repo="${ROBOCLAWS_EVAL_REGISTRY_REPO:-micr.cloud.mioffice.cn/cc-proxy/miuniverse-staging}"
tag="${ROBOCLAWS_EVAL_TAG:-roboclaws-eval-${image_variant}-env-${env_short}-code-${code_short}-${date_stamp}}"
remote_image="${ROBOCLAWS_EVAL_REMOTE_IMAGE:-${registry_repo}:${tag}}"
local_image="${ROBOCLAWS_EVAL_LOCAL_IMAGE:-roboclaws-eval:${image_variant}-local}"
build_context="${ROBOCLAWS_EVAL_BUILD_CONTEXT:-$repo_root}"
smoke_repo_dir="${ROBOCLAWS_EVAL_SMOKE_REPO_DIR:-$repo_root}"
smoke_output_dir="${ROBOCLAWS_EVAL_OUTPUT_DIR:-/tmp/roboclaws-eval-output-${tag}}"
smoke_stamp="${ROBOCLAWS_EVAL_STAMP:-offline-smoke-${code_short}}"
push_log="${ROBOCLAWS_EVAL_PUSH_LOG:-/tmp/roboclaws-eval-image-push-${tag}.log}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage:
  scripts/dev/build_push_eval_image.sh

Builds Dockerfile.eval, proves the tagged image with Docker --network none, and
pushes the tag to the CloudML-accessible registry.

Environment overrides:
  ROBOCLAWS_EVAL_REGISTRY_REPO  Default: micr.cloud.mioffice.cn/cc-proxy/miuniverse-staging
  ROBOCLAWS_EVAL_TAG            Default: roboclaws-eval-<variant>-env-<HEAD>-code-<mi/main>-<date>
  ROBOCLAWS_EVAL_REMOTE_IMAGE   Full image URL override.
  ROBOCLAWS_EVAL_IMAGE_VARIANT  cpu or cuda. Default: cpu.
  ROBOCLAWS_EVAL_DINO_CACHE_DIR Hugging Face model cache root required by cuda.
  ROBOCLAWS_EVAL_BUILD_CONTEXT  Docker build context. Default: current repo.
  ROBOCLAWS_EVAL_SMOKE_REPO_DIR Checkout mounted into the offline smoke. Default: current repo.
  ROBOCLAWS_EVAL_PUSH           Set false to skip docker push. Default: true.
USAGE
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required" >&2
  exit 1
fi

echo "build_context=$build_context"
echo "smoke_repo_dir=$smoke_repo_dir"
echo "remote_image=$remote_image"
echo "image_variant=$image_variant"

build_args=(
  -f "$repo_root/Dockerfile.eval"
  --build-arg "EVAL_IMAGE_VARIANT=$image_variant"
)
if [[ "$image_variant" == "cuda" ]]; then
  dino_snapshot="$dino_cache_dir/snapshots/$dino_model_revision"
  if [[ ! -f "$dino_snapshot/config.json" || ! -f "$dino_snapshot/model.safetensors" ]]; then
    echo "error: missing pinned Grounding DINO snapshot: $dino_snapshot" >&2
    exit 2
  fi
  build_args+=(
    --build-arg "GROUNDING_DINO_MODEL_REVISION=$dino_model_revision"
    --build-context "grounding-dino-cache=$dino_cache_dir"
  )
  echo "dino_model_revision=$dino_model_revision"
  echo "dino_cache_dir=$dino_cache_dir"
fi

docker build "${build_args[@]}" \
  -t "$local_image" \
  -t "$remote_image" \
  "$build_context"

ROBOCLAWS_EVAL_IMAGE="$remote_image" \
ROBOCLAWS_EVAL_REPO_DIR="$smoke_repo_dir" \
ROBOCLAWS_EVAL_OUTPUT_DIR="$smoke_output_dir" \
ROBOCLAWS_EVAL_STAMP="$smoke_stamp" \
  "$repo_root/scripts/dev/run_eval_image_offline_smoke.sh"

local_image_id="$(docker image inspect --format '{{.Id}}' "$local_image")"
echo "local_image=$local_image"
echo "local_image_id=$local_image_id"

if [[ "${ROBOCLAWS_EVAL_PUSH:-true}" == "false" ]]; then
  echo "push_skipped=true"
  exit 0
fi

mkdir -p "$(dirname "$push_log")"
docker push "$remote_image" | tee "$push_log"
image_digest="$(awk '/digest: sha256:/ {print $3}' "$push_log" | tail -n 1)"
echo "image_url=$remote_image"
echo "image_digest=$image_digest"
echo "push_log=$push_log"
