#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
executor_root="${ROBOCLAWS_EXECUTOR_ROOT:-/home/mi/executor}"
executor_config_root="${ROBOCLAWS_EXECUTOR_CONFIG_ROOT:-$executor_root/conf}"
executor_config_path="${ROBOCLAWS_EXECUTOR_CONFIG_PATH:-profiles/nvs/miaodongxu.yaml}"
date_stamp="${ROBOCLAWS_CLOUDML_DATE:-$(date +%Y%m%d)}"
env_ref="${ROBOCLAWS_EVAL_ENV_REF:-HEAD}"
code_ref="${ROBOCLAWS_EVAL_CODE_REF:-mi/main}"
env_short="$(git -C "$repo_root" rev-parse --short=8 "$env_ref")"
code_commit="${ROBOCLAWS_CLOUDML_CODE_COMMIT:-$(git -C "$repo_root" rev-parse "$code_ref")}"
platform_code_commit="${ROBOCLAWS_CLOUDML_CODE_COMMIT_FOR_PLATFORM:-$code_commit}"
code_short="$(git -C "$repo_root" rev-parse --short=12 "$code_commit")"
registry_repo="${ROBOCLAWS_EVAL_REGISTRY_REPO:-micr.cloud.mioffice.cn/cc-proxy/miuniverse-staging}"
default_tag="roboclaws-eval-env-${env_short}-code-${code_short}-${date_stamp}"
image_url="${ROBOCLAWS_CLOUDML_IMAGE_URL:-${registry_repo}:${default_tag}}"
run_mode="${ROBOCLAWS_CLOUDML_RUN_MODE:-product-cleanup}"
suite="${ROBOCLAWS_CLOUDML_SUITE:-smoke_regression}"
budget="${ROBOCLAWS_CLOUDML_BUDGET:-focused}"
input_rel="${ROBOCLAWS_CLOUDML_INPUT_REL:-roboclaws-assets/cleanup-focused}"
scene_source="${ROBOCLAWS_CLOUDML_SCENE_SOURCE:-procthor-10k-val}"
scene_index="${ROBOCLAWS_CLOUDML_SCENE_INDEX:-0}"
scene_name="val_${scene_index}"
scene_rel="scenes/${scene_source}"
asset_archive_name="${ROBOCLAWS_CLOUDML_ASSET_ARCHIVE_NAME:-cleanup-focused-molmospaces-val${scene_index}.tar.gz}"
asset_cache_mode="${ROBOCLAWS_CLOUDML_ASSET_CACHE_MODE:-local-scratch}"
asset_cache_root="${ROBOCLAWS_CLOUDML_ASSET_CACHE_ROOT:-/mnt/cloudml/output/roboclaws-asset-cache/cleanup-focused}"
local_asset_cache_root="${ROBOCLAWS_CLOUDML_LOCAL_ASSET_CACHE_ROOT:-/tmp/roboclaws-asset-cache/cleanup-focused}"
code_source_mode="${ROBOCLAWS_CLOUDML_CODE_SOURCE_MODE:-archive}"
code_archive_name="${ROBOCLAWS_CLOUDML_CODE_ARCHIVE_NAME:-roboclaws-code-${code_short}.tar.gz}"
stamp="${ROBOCLAWS_CLOUDML_STAMP:-cloudml-cleanup-${code_short}-${date_stamp}}"
job_name="${ROBOCLAWS_CLOUDML_JOB_NAME:-roboclaws-cleanup-${code_short}}"
output_yaml_path="${ROBOCLAWS_CLOUDML_OUTPUT_YAML:-/tmp/roboclaws-cloudml-${stamp}.yaml}"
code_url="${ROBOCLAWS_CLOUDML_CODE_URL:-https://git.n.xiaomi.com/ipg/infra/roboclaws.git}"
code_branch="${ROBOCLAWS_CLOUDML_CODE_BRANCH:-main}"
map_bundle="${ROBOCLAWS_CLOUDML_MAP_BUNDLE:-assets/maps/molmospaces/${scene_source}/${scene_index}}"
product_output_dir="${ROBOCLAWS_CLOUDML_PRODUCT_OUTPUT_DIR:-/mnt/cloudml/output/roboclaws-cleanup-runs/${stamp}}"
eval_output_dir="${ROBOCLAWS_CLOUDML_EVAL_OUTPUT_DIR:-/mnt/cloudml/output/roboclaws-evals}"
dry_run="${ROBOCLAWS_CLOUDML_DRY_RUN:-true}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
Usage:
  scripts/dev/cloudml_eval_dry_run.sh

Generates or submits a CloudML custom_train task through executor. Default is
dry-run only; set ROBOCLAWS_CLOUDML_DRY_RUN=false to submit.

Environment overrides:
  ROBOCLAWS_CLOUDML_IMAGE_URL     Pushed eval image URL.
  ROBOCLAWS_CLOUDML_CODE_URL      Default: https://git.n.xiaomi.com/ipg/infra/roboclaws.git
  ROBOCLAWS_CLOUDML_CODE_COMMIT   Default: mi/main commit.
  ROBOCLAWS_CLOUDML_CODE_COMMIT_FOR_PLATFORM
                                  Optional CloudML codeConfig commit override.
                                  The entrypoint still verifies ROBOCLAWS_CLOUDML_CODE_COMMIT.
  ROBOCLAWS_CLOUDML_RUN_MODE      Default: product-cleanup.
                                   product-cleanup runs the public cleanup surface
                                   and is compatible with the current mi/main commit.
                                   eval-focused runs just agent::eval and requires
                                   the focused-eval map-bundle fix in the code commit.
  ROBOCLAWS_CLOUDML_SUITE         Default: smoke_regression
                                   Used only for ROBOCLAWS_CLOUDML_RUN_MODE=eval-focused.
                                   Use cleanup_capability for the 3-trial pass@k suite.
  ROBOCLAWS_CLOUDML_BUDGET        Default: focused
                                   Used only for ROBOCLAWS_CLOUDML_RUN_MODE=eval-focused.
  ROBOCLAWS_CLOUDML_INPUT_REL     Default: roboclaws-assets/cleanup-focused
                                   under the /mnt/cloudml/input JuiceFS mount.
  ROBOCLAWS_CLOUDML_ASSET_ARCHIVE_NAME
                                  Default: cleanup-focused-molmospaces-val0.tar.gz
                                  under <input_rel>/archives/.
  ROBOCLAWS_CLOUDML_SCENE_SOURCE   Default: procthor-10k-val
  ROBOCLAWS_CLOUDML_SCENE_INDEX    Default: 0
  ROBOCLAWS_CLOUDML_ASSET_CACHE_MODE
                                  local-scratch|juicefs-sha. Default: local-scratch.
                                  local-scratch avoids writing 100k+ extracted
                                  asset files back to JuiceFS during each run.
  ROBOCLAWS_CLOUDML_ASSET_CACHE_ROOT
                                  JuiceFS cache root used only by juicefs-sha.
                                  Default: /mnt/cloudml/output/roboclaws-asset-cache/cleanup-focused.
  ROBOCLAWS_CLOUDML_LOCAL_ASSET_CACHE_ROOT
                                  Default: /tmp/roboclaws-asset-cache/cleanup-focused.
  ROBOCLAWS_CLOUDML_CODE_SOURCE_MODE
                                  archive|cloudml-codeconfig. Default: archive.
                                  archive avoids CloudML's forced recursive
                                  submodule sync by unpacking code from JuiceFS.
  ROBOCLAWS_CLOUDML_CODE_ARCHIVE_NAME
                                  Default: roboclaws-code-<code>.tar.gz.
  ROBOCLAWS_CLOUDML_MAP_BUNDLE    Default: assets/maps/molmospaces/<scene-source>/<scene-index>
  ROBOCLAWS_CLOUDML_OUTPUT_YAML   Default: /tmp/roboclaws-cloudml-<stamp>.yaml
  ROBOCLAWS_CLOUDML_DRY_RUN       Default: true. Set false for a real submit.
  ROBOCLAWS_EXECUTOR_ROOT         Default: /home/mi/executor
  ROBOCLAWS_EXECUTOR_CONFIG_ROOT  Default: $ROBOCLAWS_EXECUTOR_ROOT/conf
  ROBOCLAWS_EXECUTOR_CONFIG_PATH  Default: profiles/nvs/miaodongxu.yaml
USAGE
  exit 0
fi

if [[ ! "$scene_source" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "error: ROBOCLAWS_CLOUDML_SCENE_SOURCE must be a safe path segment: $scene_source" >&2
  exit 2
fi
if [[ ! "$scene_index" =~ ^[0-9]+$ ]]; then
  echo "error: ROBOCLAWS_CLOUDML_SCENE_INDEX must be a non-negative integer: $scene_index" >&2
  exit 2
fi
if [[ "$scene_source" == "procthor-10k-val" && ",0,1,2,3,4,5,7,9," == *",${scene_index},"* ]]; then
  scene_world="molmospaces/val_${scene_index}"
else
  scene_world="molmospaces/${scene_source}/${scene_index}"
fi

if [[ ! -x "$executor_root/execute.py" ]]; then
  echo "error: executor not found at $executor_root" >&2
  exit 1
fi

case "$run_mode" in
  product-cleanup)
    run_description="Roboclaws product cleanup"
    cloudml_run_command=(
      just run::surface
      surface=household-world
      "world=${scene_world}"
      backend=mujoco
      preset=cleanup
      agent_engine=direct-runner
      evidence_lane=world-public-labels
      seed=7
      scenario_setup=relocate-cleanup-related-objects
      relocation_count=5
      "map_bundle=${map_bundle}"
      "output_dir=${product_output_dir}"
    )
    ;;
  eval-focused)
    run_description="Roboclaws focused cleanup eval ${suite}/${budget}"
    cloudml_run_command=(
      just agent::eval
      "suite=${suite}"
      "budget=${budget}"
      "output_dir=${eval_output_dir}"
      "stamp=${stamp}"
    )
    ;;
  *)
    echo "error: unsupported ROBOCLAWS_CLOUDML_RUN_MODE '$run_mode'" >&2
    echo "expected product-cleanup|eval-focused" >&2
    exit 1
    ;;
esac
printf -v cloudml_run_command_text '%q ' "${cloudml_run_command[@]}"
cloudml_run_command_text="${cloudml_run_command_text% }"

entrypoint_script="$(
  cat <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir=/ml-engine/code/roboclaws.git
expected_code_commit=${code_commit}
input_rel=${input_rel}
archive_name=${asset_archive_name}
archive_path=/mnt/cloudml/input/\${input_rel}/archives/\${archive_name}
sha_path=\${archive_path}.sha256
code_source_mode=${code_source_mode}
code_archive_name=${code_archive_name}
code_archive_path=/mnt/cloudml/input/\${input_rel}/archives/\${code_archive_name}
code_sha_path=\${code_archive_path}.sha256
asset_cache_mode=${asset_cache_mode}
juicefs_asset_cache_root=${asset_cache_root}
local_asset_cache_root=${local_asset_cache_root}
map_bundle=${map_bundle}
scene_source=${scene_source}
scene_index=${scene_index}
scene_name=${scene_name}
scene_world=${scene_world}
scene_rel=${scene_rel}
stamp=${stamp}
run_mode=${run_mode}
product_output_dir=${product_output_dir}
eval_output_dir=${eval_output_dir}

echo roboclaws_cloudml_entrypoint_start=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo archive_path=\${archive_path}
test -f "\${archive_path}"
test -f "\${sha_path}"

archive_sha=\$(awk '{print \$1}' "\${sha_path}")
case "\${archive_sha}" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f]*)
    ;;
  *)
    echo "error: invalid archive sha256 in \${sha_path}: \${archive_sha}" >&2
    exit 1
    ;;
esac
archive_actual_sha=\$(sha256sum "\${archive_path}" | awk '{print \$1}')
if [[ "\${archive_actual_sha}" != "\${archive_sha}" ]]; then
  echo "error: archive sha256 \${archive_actual_sha} != expected \${archive_sha}" >&2
  exit 1
fi

case "\${asset_cache_mode}" in
  local-scratch)
    cache_root=\${local_asset_cache_root}
    ;;
  juicefs-sha)
    cache_root=\${juicefs_asset_cache_root}
    ;;
  *)
    echo "error: unsupported asset cache mode: \${asset_cache_mode}" >&2
    echo "expected local-scratch|juicefs-sha" >&2
    exit 1
    ;;
esac

extract_asset_archive() {
  local source_path="\$1"
  local target_dir="\$2"
  local started_at
  local heartbeat_pid
  started_at=\$(date +%s)
  echo asset_cache_extract=begin mode=\${asset_cache_mode}
  (
    while true; do
      sleep 60
      echo "asset_cache_extract=running mode=\${asset_cache_mode} seconds=\$((\$(date +%s) - started_at))"
    done
  ) &
  heartbeat_pid=\$!
  if tar -xzf "\${source_path}" -C "\${target_dir}"; then
    kill "\${heartbeat_pid}" 2>/dev/null || true
    wait "\${heartbeat_pid}" 2>/dev/null || true
    echo "asset_cache_extract=tar_done mode=\${asset_cache_mode} seconds=\$((\$(date +%s) - started_at))"
  else
    local status=\$?
    kill "\${heartbeat_pid}" 2>/dev/null || true
    wait "\${heartbeat_pid}" 2>/dev/null || true
    return "\${status}"
  fi
}

cache_dir=\${cache_root}/\${archive_sha}
ready=\${cache_dir}/.ready
lock=\${cache_dir}.lock
tmp=\${cache_dir}.tmp.\$\$
mkdir -p "\${cache_root}"

if [[ ! -f "\${ready}" ]]; then
  if mkdir "\${lock}" 2>/dev/null; then
    cleanup_lock() {
      rm -rf "\${tmp}"
      rmdir "\${lock}" 2>/dev/null || true
    }
    trap cleanup_lock EXIT
    rm -rf "\${tmp}"
    mkdir -p "\${tmp}"
    extract_asset_archive "\${archive_path}" "\${tmp}"
    test -f "\${tmp}/molmospaces/assets/\${scene_rel}/\${scene_name}.xml"
    test -f "\${tmp}/molmospaces/assets/\${scene_rel}/\${scene_name}.json"
    test -d "\${tmp}/molmospaces/assets/objects/thor"
    test -d "\${tmp}/molmospaces/assets/robots/rby1m"
    rm -rf "\${cache_dir}"
    mv "\${tmp}" "\${cache_dir}"
    mkdir -p "\${cache_dir}/molmospaces/cache"
    touch "\${ready}"
    rmdir "\${lock}"
    trap - EXIT
    echo asset_cache_extract=done
  else
    echo asset_cache_wait=begin
    while [[ ! -f "\${ready}" ]]; do
      sleep 10
    done
    echo asset_cache_wait=done
  fi
else
  echo asset_cache=ready
fi

export MLSPACES_ASSETS_DIR=\${cache_dir}/molmospaces/assets
export MLSPACES_CACHE_DIR=\${cache_dir}/molmospaces/cache
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/\${scene_name}.xml"
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/\${scene_name}.json"
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/\${scene_name}_metadata.json"
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/\${scene_name}_ceiling.xml"
test -d "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/\${scene_name}_assets"
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/mjthor_resources_combined_meta.json.gz"
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/mjthor_resource_file_to_size_mb.json"
test -f "\${MLSPACES_ASSETS_DIR}/\${scene_rel}/.\${scene_source}_\${scene_name}.tar.zst_complete_links"
test -d "\${MLSPACES_ASSETS_DIR}/objects/thor"
test -d "\${MLSPACES_ASSETS_DIR}/robots/rby1m"
test -f "\${MLSPACES_ASSETS_DIR}/mjthor_data_type_to_source_to_versions.json"
test -f "\${MLSPACES_CACHE_DIR}/mjthor_data_type_to_source_to_versions.json"
export MLSPACES_CACHE_LOCK=false
asset_map_bundle=\${cache_dir}/roboclaws/\${map_bundle}

case "\${code_source_mode}" in
  archive)
    echo code_archive_path=\${code_archive_path}
    ls -lh "\$(dirname "\${code_archive_path}")" || true
    if [[ ! -f "\${code_archive_path}" ]]; then
      echo "error: missing code archive: \${code_archive_path}" >&2
      exit 1
    fi
    if [[ ! -f "\${code_sha_path}" ]]; then
      echo "error: missing code archive sha256: \${code_sha_path}" >&2
      exit 1
    fi
    code_archive_sha=\$(awk '{print \$1}' "\${code_sha_path}")
    echo code_archive_sha256_expected=\${code_archive_sha}
    code_archive_actual_sha=\$(sha256sum "\${code_archive_path}" | awk '{print \$1}')
    echo code_archive_sha256_actual=\${code_archive_actual_sha}
    if [[ "\${code_archive_actual_sha}" != "\${code_archive_sha}" ]]; then
      echo "error: code archive sha256 \${code_archive_actual_sha} != expected \${code_archive_sha}" >&2
      exit 1
    fi
    rm -rf "\${repo_dir}"
    mkdir -p /ml-engine/code
    echo code_archive_extract=begin
    tar -xzf "\${code_archive_path}" -C /ml-engine/code
    echo code_archive_extract=done
    echo code_archive_extract_listing=begin
    find /ml-engine/code -maxdepth 2 -mindepth 1 -printf '%y %p\n' | sort | head -80
    echo code_archive_extract_listing=done
    if [[ ! -f "\${repo_dir}/.roboclaws_code_commit" ]]; then
      echo "error: missing code archive commit marker: \${repo_dir}/.roboclaws_code_commit" >&2
      exit 1
    fi
    if [[ "\$(cat "\${repo_dir}/.roboclaws_code_commit")" != "\${expected_code_commit}" ]]; then
      echo "error: code archive commit \$(cat "\${repo_dir}/.roboclaws_code_commit") != expected \${expected_code_commit}" >&2
      exit 1
    fi
    ;;
  cloudml-codeconfig)
    ;;
  *)
    echo "error: unsupported code source mode: \${code_source_mode}" >&2
    exit 1
    ;;
esac

cd "\${repo_dir}"
if git rev-parse HEAD >/dev/null 2>&1; then
  actual_code_commit=\$(git rev-parse HEAD)
else
  actual_code_commit=\$(cat .roboclaws_code_commit)
fi
if [[ "\${actual_code_commit}" != "\${expected_code_commit}" ]]; then
  echo "error: CloudML checkout commit \${actual_code_commit} != expected \${expected_code_commit}" >&2
  exit 1
fi
if [[ ! -x /opt/roboclaws/.venv/bin/python ]]; then
  echo "error: missing baked Python runtime: /opt/roboclaws/.venv/bin/python" >&2
  exit 1
fi
ln -sfn /opt/roboclaws/.venv .venv
if [[ ! -x .venv/bin/python ]]; then
  echo "error: repo .venv symlink does not expose Python: .venv/bin/python" >&2
  exit 1
fi
if [[ ! -f "\${map_bundle}/map.yaml" && -f "\${asset_map_bundle}/map.yaml" ]]; then
  echo map_bundle_source=asset-cache path=\${asset_map_bundle}
  mkdir -p "\$(dirname "\${map_bundle}")"
  rm -rf "\${map_bundle}"
  ln -sfn "\${asset_map_bundle}" "\${map_bundle}"
fi
if [[ ! -f "\${map_bundle}/map.yaml" ]]; then
  echo "error: missing map bundle map.yaml: \${repo_dir}/\${map_bundle}/map.yaml" >&2
  echo "hint: expected asset-cache map bundle at \${asset_map_bundle}/map.yaml" >&2
  exit 1
fi
if [[ ! -f "\${map_bundle}/semantics.json" ]]; then
  echo "error: missing map bundle semantics.json: \${repo_dir}/\${map_bundle}/semantics.json" >&2
  echo "hint: expected asset-cache map bundle at \${asset_map_bundle}/semantics.json" >&2
  exit 1
fi
uv pip install --python /opt/roboclaws/.venv/bin/python --no-build-isolation --no-deps --editable "\${repo_dir}"

mkdir -p "\${product_output_dir}" "\${eval_output_dir}" /mnt/cloudml/output/roboclaws-cloudml-entrypoints
cat > "/mnt/cloudml/output/roboclaws-cloudml-entrypoints/\${stamp}.json" <<META
{
  "schema": "roboclaws_cloudml_entrypoint_v1",
  "stamp": "\${stamp}",
  "run_mode": "\${run_mode}",
  "code_commit": "\${actual_code_commit}",
  "archive_path": "\${archive_path}",
  "archive_sha256": "\${archive_sha}",
  "asset_cache_mode": "\${asset_cache_mode}",
  "cache_dir": "\${cache_dir}",
  "mlspaces_assets_dir": "\${MLSPACES_ASSETS_DIR}",
  "scene_source": "\${scene_source}",
  "scene_index": \${scene_index}
}
META

${cloudml_run_command_text}
EOF
)"

entrypoint_b64="$(printf '%s\n' "$entrypoint_script" | base64 -w 0)"
image_command="bash -lc 'printf %s ${entrypoint_b64} | base64 -d > /tmp/roboclaws_cloudml_entrypoint.sh; chmod +x /tmp/roboclaws_cloudml_entrypoint.sh; /tmp/roboclaws_cloudml_entrypoint.sh'"

argv=(
  "$executor_root/execute.py"
  nvs miaodongxu cloudml submit
  --job_name "$job_name"
  --description "${run_description} for ${code_commit}"
  --image_url "$image_url"
  --image_command "$image_command"
  --dry_run "$dry_run"
  --output_yaml_path "$output_yaml_path"
  --json
)

case "$code_source_mode" in
  archive)
    ;;
  cloudml-codeconfig)
    argv+=(--code_url "$code_url")
    argv+=(--code_branch "$code_branch")
    argv+=(--code_commit "$platform_code_commit")
    ;;
  *)
    echo "error: unsupported ROBOCLAWS_CLOUDML_CODE_SOURCE_MODE '$code_source_mode'" >&2
    echo "expected archive|cloudml-codeconfig" >&2
    exit 1
    ;;
esac

if [[ -n "${ROBOCLAWS_CLOUDML_CODE_TOKEN:-}" ]]; then
  argv+=(--code_token "$ROBOCLAWS_CLOUDML_CODE_TOKEN")
fi

EXECUTOR_CONFIG_ROOT="$executor_config_root" \
  EXECUTOR_CONFIG_PATH="$executor_config_path" \
  "${argv[@]}"
echo "cloudml_yaml=$output_yaml_path"
