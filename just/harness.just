# Household and planner proof harness dispatchers.
#
# Preferred entrypoints:
# - just harness::household-world  public/private household-world cleanup harness
# - just harness::molmo-realworld-agent-mcp  ADR-0003 MCP smoke agent harness
# - just harness::molmo-realworld-agent-dogfood-kit  ADR-0003 direct-agent kit smoke
# - just harness::molmo-realworld-raw-fpv  ADR-0013 raw FPV-only observation evidence
# - just harness::molmo-planner-proof-bundle-runner  proof-request dry-run handoff
# - just harness::molmo-planner-proof-bundle-execute-rerun  local GPU proof-bundle execution
# - just harness::molmo-visual-grounding-benchmark  perception-isolated HTTP grounding harness
# - just harness::isaac-runtime-preflight  Isaac Lab local runtime setup gate
# - just harness::isaac-runtime-smoke  strict Isaac Lab renderer/USD smoke gate
# - just harness::b1-map12-navigation-smoke  B1 / robot_map_12 local navigation smoke

set working-directory := '..'
set positional-arguments
timestamp_cmd := "TZ=Asia/Shanghai date +%m%d_%H%M"

default:
    @just --list harness

# ADR-0003 real-world-style cleanup harness. The default runs the real
# MolmoSpaces subprocess backend over three mess seeds, with the agent limited
# to metric map, preflight room context artifacts, and robot-local observed
# handles.
# Phase 15 requests 10 hidden generated objects by default.
# It also records RBY1M robot views so report.html has the current visual
# review surface.
household-world seeds="1 2 3" output_dir="output/household-world-harness" task="帮我收拾这个房间" generated_mess_count="10":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp="$({{timestamp_cmd}})"
    run_root="{{output_dir}}/${stamp}"
    mkdir -p "$run_root"
    echo "==> run root: ${run_root}"
    for seed in {{seeds}}; do
      run_dir="${run_root}/seed-${seed}"
      .venv/bin/python -m roboclaws.household.household_world_episode \
        --seed "${seed}" \
        --backend molmospaces_subprocess \
        --task "{{task}}" \
        --static-fixture-projection-mode room_only \
        --generated-mess-count "{{generated_mess_count}}" \
        --include-robot \
        --robot-name rby1m \
        --record-robot-views \
        --output-dir "${run_dir}"
    done
    seed_csv="$(printf '%s' "{{seeds}}" | tr ' ' ',')"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend molmospaces_subprocess \
      --expect-seeds "${seed_csv}" \
      --min-generated-mess-count "{{generated_mess_count}}" \
      --require-robot-views \
      --require-advisory-scoring \
      "${run_root}"

# ADR-0003 real-world MCP smoke agent harness. This uses the stricter public
# contract through MCP tools: metric_map, waypoint observe, and observed object
# handles. Static fixture projection may exist as preflight artifacts, but are not exposed as
# callable MCP tools. It intentionally does not expose scene_objects.
molmo-realworld-agent-mcp seeds="1" output_dir="output/molmo-realworld-agent-mcp-harness" task="帮我收拾这个房间" generated_mess_count="10":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp="$({{timestamp_cmd}})"
    run_root="{{output_dir}}/${stamp}"
    mkdir -p "$run_root"
    echo "==> run root: ${run_root}"
    for seed in {{seeds}}; do
      run_dir="${run_root}/seed-${seed}"
      .venv/bin/python scripts/molmo_cleanup/run_molmo_realworld_agent_mcp_smoke.py \
        --seed "${seed}" \
        --backend molmospaces_subprocess \
        --task "{{task}}" \
        --generated-mess-count "{{generated_mess_count}}" \
        --include-robot \
        --robot-name rby1m \
        --record-robot-views \
        --output-dir "${run_dir}"
    done
    seed_csv="$(printf '%s' "{{seeds}}" | tr ' ' ',')"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend molmospaces_subprocess \
      --expect-policy household_contract_smoke_agent \
      --expect-mcp-server household_world \
      --expect-seeds "${seed_csv}" \
      --min-generated-mess-count "{{generated_mess_count}}" \
      --require-robot-views \
      --require-advisory-scoring \
      "${run_root}"

# ADR-0003 direct-agent dogfood kit smoke. This does not launch Codex/Claude;
# it proves the stricter skill/server/checker path against the synthetic backend
# before local external-agent dogfood.
molmo-realworld-agent-dogfood-kit seed="7" output_dir="output/molmo-realworld-agent-dogfood-kit" task="帮我收拾这个房间":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp="$({{timestamp_cmd}})"
    run_dir="{{output_dir}}/${stamp}"
    mkdir -p "$run_dir"
    echo "==> run dir: ${run_dir}"
    .venv/bin/python scripts/molmo_cleanup/run_molmo_realworld_agent_mcp_smoke.py \
      --seed "{{seed}}" \
      --backend api_semantic_synthetic \
      --task "{{task}}" \
      --policy household_contract_smoke_agent \
      --output-dir "$run_dir"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend api_semantic_synthetic \
      --expect-policy household_contract_smoke_agent \
      --expect-mcp-server household_world \
      --min-generated-mess-count 5 \
      --require-agent-driven \
      --require-clean-agent-run \
      --require-advisory-scoring \
      "${run_dir}/run_result.json"

# ADR-0013 raw FPV-only evidence harness. This intentionally proves perception
# boundary and report artifacts, not camera-only cleanup success.
molmo-realworld-raw-fpv seed="7" output_dir="output/molmo-realworld-raw-fpv-harness" task="帮我收拾这个房间" generated_mess_count="10" map_bundle="assets/maps/molmospaces/procthor-10k-val/0":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp="$({{timestamp_cmd}})"
    run_dir="{{output_dir}}/${stamp}"
    mkdir -p "$run_dir"
    echo "==> run dir: ${run_dir}"
    .venv/bin/python -m roboclaws.household.household_world_episode \
      --seed "{{seed}}" \
      --backend molmospaces_subprocess \
      --task "{{task}}" \
      --static-fixture-projection-mode room_only \
      --map-bundle-dir "{{map_bundle}}" \
      --perception-mode raw_fpv_only \
      --generated-mess-count "{{generated_mess_count}}" \
      --include-robot \
      --robot-name rby1m \
      --record-robot-views \
      --output-dir "$run_dir"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend molmospaces_subprocess \
      --min-generated-mess-count "{{generated_mess_count}}" \
      --require-robot-views \
      --require-advisory-scoring \
      --require-raw-fpv-observations \
      "${run_dir}/run_result.json"

# ADR-0042 proof-bundle runner dry-run handoff. This proves fresh ADR-0003
# cleanup artifacts produce checked planner proof commands without executing
# local GPU planner probes.
molmo-planner-proof-bundle-runner output_dir="output/molmo-planner-proof-bundle-runner-harness" seed="7" task="帮我收拾这个房间" generated_mess_count="10" map_bundle="assets/maps/molmospaces/procthor-10k-val/0":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp="$({{timestamp_cmd}})"
    run_root="{{output_dir}}/${stamp}"
    cleanup_dir="${run_root}/cleanup"
    bundle_dir="${run_root}/proof_bundle"
    mkdir -p "$run_root"
    echo "==> run root: ${run_root}"
    .venv/bin/python -m roboclaws.household.household_world_episode \
      --seed "{{seed}}" \
      --backend api_semantic_synthetic \
      --task "{{task}}" \
      --static-fixture-projection-mode room_only \
      --map-bundle-dir "{{map_bundle}}" \
      --generated-mess-count "{{generated_mess_count}}" \
      --output-dir "${cleanup_dir}"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend api_semantic_synthetic \
      --min-generated-mess-count 5 \
      --require-advisory-scoring \
      "${cleanup_dir}/run_result.json"
    .venv/bin/python scripts/molmo_cleanup/run_molmo_planner_proof_bundle_from_requests.py \
      "${cleanup_dir}/run_result.json" \
      --output-dir "${bundle_dir}" \
      --runner-python .venv/bin/python \
      --embodiment rby1m \
      --probe-mode execute \
      --steps 2 \
      --timeout-s 600
    .venv/bin/python scripts/molmo_cleanup/check_molmo_planner_proof_bundle_runner_result.py \
      "${bundle_dir}"

# ADR-0044 local-dev proof-bundle execution gate. This executes real RBY1M/CuRobo
# planner probes against the real MolmoSpaces cleanup scene and reruns cleanup
# with their proof outputs, so keep it out of default CI.
molmo-planner-proof-bundle-execute-rerun output_dir="output/molmo-planner-proof-bundle-execute-rerun" seed="7" task="帮我收拾这个房间" generated_mess_count="10" min_generated_mess_count="5" steps="2" timeout_s="600":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp="$({{timestamp_cmd}})"
    run_root="{{output_dir}}/${stamp}"
    cleanup_dir="${run_root}/cleanup"
    bundle_dir="${run_root}/proof_bundle"
    rerun_dir="${run_root}/cleanup_rerun"
    torch_extensions_dir="${run_root}/torch_extensions"
    mkdir -p "$run_root"
    echo "==> run root: ${run_root}"
    .venv/bin/python -m roboclaws.household.household_world_episode \
      --seed "{{seed}}" \
      --backend molmospaces_subprocess \
      --task "{{task}}" \
      --static-fixture-projection-mode room_only \
      --include-robot \
      --record-robot-views \
      --generated-mess-count "{{generated_mess_count}}" \
      --output-dir "${cleanup_dir}"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend molmospaces_subprocess \
      --min-generated-mess-count "{{min_generated_mess_count}}" \
      --require-robot-views \
      --require-advisory-scoring \
      "${cleanup_dir}/run_result.json"
    .venv/bin/python scripts/molmo_cleanup/run_molmo_planner_proof_bundle_from_requests.py \
      "${cleanup_dir}/run_result.json" \
      --output-dir "${bundle_dir}" \
      --runner-python .venv/bin/python \
      --embodiment rby1m \
      --probe-mode execute \
      --steps "{{steps}}" \
      --timeout-s "{{timeout_s}}" \
      --torch-extensions-dir "${torch_extensions_dir}" \
      --execute-probes \
      --rerun-cleanup \
      --cleanup-output-dir "${rerun_dir}"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_planner_proof_bundle_runner_result.py \
      --require-proof-outputs \
      --require-cleanup-rerun-output \
      "${bundle_dir}"
    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      --expect-task "{{task}}" \
      --expect-backend molmospaces_subprocess \
      --min-generated-mess-count "{{min_generated_mess_count}}" \
      --require-robot-views \
      --require-advisory-scoring \
      --require-planner-proof-attachment \
      --require-planner-backed-cleanup-primitives \
      --require-planner-cleanup-bridge-ready \
      "${rerun_dir}/run_result.json"

# ADR-0133 perception-isolated visual-grounding benchmark. This calls the
# configured HTTP grounding service over fixed public RAW_FPV-style fixtures and
# checks provenance, overlays, and private-label separation. The default expects
# the deployable Grounding-DINO producer; missing sidecar/model readiness should
# fail or record blocked evidence, not fall back to fake transport.
molmo-visual-grounding-benchmark *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    args=("$@")
    pipeline="${VISUAL_GROUNDING_PIPELINE_ID:-grounding-dino}"
    output_dir="output/visual-grounding-benchmark"
    corpus="harness/visual_grounding/smoke_corpus.json"
    matrix=""
    base_url="${VISUAL_GROUNDING_BASE_URL:-}"
    timeout_s="${VISUAL_GROUNDING_TIMEOUT_S:-20}"
    include_private_label_details="false"
    require_success="true"
    require_candidates="false"
    positional_pipeline_set="false"
    pipeline_override_set="false"
    for arg in "${args[@]}"; do
      if [[ "$arg" != *=* ]]; then
        if [[ "$positional_pipeline_set" == "false" ]]; then
          pipeline="$arg"
          positional_pipeline_set="true"
          pipeline_override_set="true"
          continue
        fi
        echo "error: override '$arg' is not key=value" >&2
        exit 1
      fi
      key="${arg%%=*}"
      value="${arg#*=}"
      key="${key#--}"
      key="${key//-/_}"
      case "$key" in
        pipeline|pipelines|output_dir|corpus|matrix|base_url|timeout_s|\
        include_private_label_details|require_success|require_candidates)
          ;;
        *)
          echo "error: unsupported override key '$key'" >&2
          exit 1
          ;;
      esac
      case "$key" in
        pipeline|pipelines) pipeline="$value"; pipeline_override_set="true" ;;
        output_dir) output_dir="$value" ;;
        corpus) corpus="$value" ;;
        matrix) matrix="$value" ;;
        base_url) base_url="$value" ;;
        timeout_s) timeout_s="$value" ;;
        include_private_label_details) include_private_label_details="$value" ;;
        require_success) require_success="$value" ;;
        require_candidates) require_candidates="$value" ;;
      esac
    done
    stamp="$({{timestamp_cmd}})"
    run_dir="${output_dir}/${stamp}"
    mkdir -p "$run_dir"
    echo "==> run dir: ${run_dir}"
    cmd=(.venv/bin/python scripts/visual_grounding/run_visual_grounding_benchmark.py \
      --corpus "$corpus" \
      --output-dir "$run_dir" \
      --timeout-s "$timeout_s")
    if [[ -z "$matrix" || "$pipeline_override_set" == "true" ]]; then
      cmd+=(--pipeline "$pipeline")
    fi
    if [[ -n "$matrix" ]]; then
      cmd+=(--matrix "$matrix")
    fi
    if [[ -n "$base_url" ]]; then
      cmd+=(--base-url "$base_url")
    fi
    if [[ "$include_private_label_details" == "true" ]]; then
      cmd+=(--include-private-label-details)
    fi
    "${cmd[@]}"
    check_cmd=(.venv/bin/python scripts/visual_grounding/check_visual_grounding_benchmark_result.py \
      "$run_dir")
    if [[ "$pipeline" != *","* && ( -z "$matrix" || "$pipeline_override_set" == "true" ) ]]; then
      check_cmd+=(--expect-pipeline "$pipeline")
    fi
    if [[ "$require_success" == "true" ]]; then
      check_cmd+=(--require-success)
    fi
    if [[ "$require_candidates" == "true" ]]; then
      check_cmd+=(--require-candidates)
    fi
    if [[ "$include_private_label_details" == "true" ]]; then
      check_cmd+=(--allow-private-label-details)
    fi
    "${check_cmd[@]}"

# Isaac Lab local runtime preflight. This records host readiness and writes a
# reproducible install script. It creates .venv-isaaclab/ only when both
# install=true and accept_nvidia_eula=true are supplied.
isaac-runtime-preflight *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    args=("$@")
    output_dir="output/isaaclab/preflight"
    runtime_dir=".venv-isaaclab"
    python="3.12"
    python_executable=""
    isaaclab_source=""
    stamp=""
    min_free_gb="80"
    skip_gpu_probe="false"
    install="false"
    accept_nvidia_eula="false"
    strict="false"
    for arg in "${args[@]}"; do
      if [[ "$arg" != *=* ]]; then
        echo "error: override '$arg' is not key=value" >&2
        exit 1
      fi
      key="${arg%%=*}"
      value="${arg#*=}"
      key="${key#--}"
      key="${key//-/_}"
      case "$key" in
        output_dir|runtime_dir|python|python_executable|isaaclab_source|stamp|\
        min_free_gb|skip_gpu_probe|install|accept_nvidia_eula|strict)
          ;;
        *)
          echo "error: unsupported override key '$key'" >&2
          exit 1
          ;;
      esac
      printf -v "$key" '%s' "$value"
    done
    cmd=(.venv/bin/python scripts/isaac_lab_cleanup/check_isaac_lab_runtime.py \
      --output-dir "$output_dir" \
      --runtime-dir "$runtime_dir" \
      --python "$python" \
      --min-free-gb "$min_free_gb")
    if [[ -n "$python_executable" ]]; then
      cmd+=(--python-executable "$python_executable")
    fi
    if [[ -n "$isaaclab_source" ]]; then
      cmd+=(--isaaclab-source "$isaaclab_source")
    fi
    if [[ -n "$stamp" ]]; then
      cmd+=(--stamp "$stamp")
    fi
    if [[ "$skip_gpu_probe" == "true" ]]; then
      cmd+=(--skip-gpu-probe)
    fi
    if [[ "$install" == "true" ]]; then
      cmd+=(--install)
    fi
    if [[ "$accept_nvidia_eula" == "true" ]]; then
      cmd+=(--accept-nvidia-eula)
    fi
    if [[ "$strict" == "true" ]]; then
      cmd+=(--strict)
    fi
    "${cmd[@]}"

# Strict local Isaac Lab runtime smoke. This intentionally fails until the
# worker proves a real Isaac renderer capture and USD stage load; import-only or
# placeholder evidence is rejected by the checker.
isaac-runtime-smoke *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    args=("$@")
    runtime_python=".venv-isaaclab/bin/python"
    output_dir="output/isaaclab/runtime-smoke"
    stamp=""
    scene_source="roboclaws-generic"
    scene_index="0"
    scene_usd_path=""
    generated_scene_kind="roboclaws_smoke"
    seed="7"
    generated_mess_count="1"
    map_bundle=""
    include_robot="true"
    robot_name="rby1m"
    require_real_rendering="true"
    require_usd_stage_loaded="true"
    require_local_scene_usd="false"
    require_usd_scene_index="true"
    require_selected_usd_bindings="true"
    require_robot_view_images="true"
    require_nonblank_image="true"
    enable_segmentation="false"
    require_segmentation_evidence="false"
    segmentation_data_types=""
    segmentation_semantic_filter=""
    accept_nvidia_eula="false"
    for arg in "${args[@]}"; do
      if [[ "$arg" != *=* ]]; then
        echo "error: override '$arg' is not key=value" >&2
        exit 1
      fi
      key="${arg%%=*}"
      value="${arg#*=}"
      key="${key#--}"
      key="${key//-/_}"
      case "$key" in
        runtime_python|output_dir|stamp|scene_source|scene_index|seed|\
        scene_usd_path|generated_scene_kind|generated_mess_count|map_bundle|include_robot|robot_name|\
        require_real_rendering|require_usd_stage_loaded|require_local_scene_usd|\
        require_usd_scene_index|\
        require_selected_usd_bindings|require_robot_view_images|require_nonblank_image|\
        enable_segmentation|require_segmentation_evidence|segmentation_data_types|\
        segmentation_semantic_filter|\
        accept_nvidia_eula)
          ;;
        *)
          echo "error: unsupported override key '$key'" >&2
          exit 1
          ;;
      esac
      printf -v "$key" '%s' "$value"
    done
    if [[ -z "$stamp" ]]; then
      stamp="$({{timestamp_cmd}})"
    fi
    run_dir="${output_dir}/${stamp}"
    state_path="${run_dir}/state.json"
    init_result="${run_dir}/init_result.json"
    robot_views_result="${run_dir}/robot_views_result.json"
    mkdir -p "$run_dir"
    if [[ "$accept_nvidia_eula" == "true" ]]; then
      export OMNI_KIT_ACCEPT_EULA="YES"
    fi
    worker_cmd=("$runtime_python" -m roboclaws.backends.isaaclab.worker \
      --state-path "$state_path" \
      init \
      --run-dir "$run_dir" \
      --seed "$seed" \
      --scene-source "$scene_source" \
      --scene-index "$scene_index" \
      --generated-scene-kind "$generated_scene_kind" \
      --generated-mess-count "$generated_mess_count" \
      --runtime-mode real)
    if [[ -n "$scene_usd_path" ]]; then
      worker_cmd+=(--scene-usd-path "$scene_usd_path")
    fi
    if [[ "$include_robot" == "true" ]]; then
      worker_cmd+=(--include-robot --robot-name "$robot_name")
    fi
    if [[ "$enable_segmentation" == "true" || "$require_segmentation_evidence" == "true" ]]; then
      worker_cmd+=(--enable-segmentation)
      if [[ -n "$segmentation_data_types" ]]; then
        IFS=', ' read -r -a segmentation_type_args <<< "$segmentation_data_types"
        for data_type in "${segmentation_type_args[@]}"; do
          if [[ -n "$data_type" ]]; then
            worker_cmd+=(--segmentation-data-type "$data_type")
          fi
        done
      fi
      if [[ -n "$segmentation_semantic_filter" ]]; then
        IFS=', ' read -r -a semantic_filter_args <<< "$segmentation_semantic_filter"
        for instance_name in "${semantic_filter_args[@]}"; do
          if [[ -n "$instance_name" ]]; then
            worker_cmd+=(--segmentation-semantic-filter "$instance_name")
          fi
        done
      fi
    fi
    if [[ -n "$map_bundle" ]]; then
      worker_cmd+=(--map-bundle-dir "$map_bundle")
    fi
    "${worker_cmd[@]}" 2>&1 | tee "$init_result"
    if [[ ! -s "$state_path" ]]; then
      echo "error: Isaac runtime smoke init did not write state: ${state_path}" >&2
      exit 1
    fi
    robot_views_cmd=("$runtime_python" -m roboclaws.backends.isaaclab.worker \
      --state-path "$state_path" \
      robot_views \
      --output-dir "${run_dir}/robot_views" \
      --label "runtime_smoke")
    "${robot_views_cmd[@]}" 2>&1 | tee "$robot_views_result"
    check_cmd=(.venv/bin/python -m roboclaws.backends.isaaclab.smoke_checker \
      --init-result "$init_result" \
      --state-path "$state_path" \
      --robot-views-result "$robot_views_result")
    if [[ "$require_real_rendering" == "true" ]]; then
      check_cmd+=(--require-real-rendering)
    fi
    if [[ "$require_usd_stage_loaded" == "true" ]]; then
      check_cmd+=(--require-usd-stage-loaded)
    fi
    if [[ "$require_local_scene_usd" == "true" ]]; then
      check_cmd+=(--require-local-scene-usd)
    fi
    if [[ "$require_usd_scene_index" == "true" ]]; then
      check_cmd+=(--require-usd-scene-index)
    fi
    if [[ "$require_selected_usd_bindings" == "true" ]]; then
      check_cmd+=(--require-selected-usd-bindings)
    fi
    if [[ "$require_robot_view_images" == "true" ]]; then
      check_cmd+=(--require-robot-view-images)
    fi
    if [[ "$require_nonblank_image" == "true" ]]; then
      check_cmd+=(--require-nonblank-image)
    fi
    if [[ "$require_segmentation_evidence" == "true" ]]; then
      check_cmd+=(--require-segmentation-evidence)
    fi
    "${check_cmd[@]}"

# Local B1 / robot_map_12 Digital Twin navigation smoke. This is a maintainer
# confidence layer, not a public household-world surface or cleanup intent.
b1-map12-navigation-smoke *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    args=("$@")
    runtime_python=".venv-isaaclab/bin/python"
    b1_root="data/robot-data-lab/scene-engine/data/2rd_floor_seperated"
    map12_root="vendors/agibot_sdk/artifacts/maps/robot_map_12"
    output_dir="output/b1-map12/navigation-smoke"
    readiness_output=""
    alignment_artifact="output/b1-map12/alignment/alignment_residuals.json"
    waypoint_pose_requests=""
    render_scene_usd="data/robot-data-lab/scene-engine/data/B1_floor2_slow/usda/F2_all/default.usda"
    stamp=""
    robot_name="rby1m"
    prepare_robot_usd="true"
    require_navigation_success="true"
    accept_nvidia_eula="false"
    for arg in "${args[@]}"; do
      if [[ "$arg" != *=* ]]; then
        echo "error: override '$arg' is not key=value" >&2
        exit 1
      fi
      key="${arg%%=*}"
      value="${arg#*=}"
      key="${key#--}"
      key="${key//-/_}"
      case "$key" in
        runtime_python|b1_root|map12_root|output_dir|readiness_output|stamp|\
        alignment_artifact|waypoint_pose_requests|render_scene_usd|\
        robot_name|prepare_robot_usd|require_navigation_success|accept_nvidia_eula)
          ;;
        *)
          echo "error: unsupported override key '$key'" >&2
          exit 1
          ;;
      esac
      printf -v "$key" '%s' "$value"
    done
    if [[ -z "$stamp" ]]; then
      stamp="$({{timestamp_cmd}})"
    fi
    run_dir="${output_dir}/${stamp}"
    if [[ -z "$readiness_output" ]]; then
      readiness_output="${run_dir}/readiness.json"
    fi
    mkdir -p "$run_dir"
    if [[ "$accept_nvidia_eula" == "true" ]]; then
      export OMNI_KIT_ACCEPT_EULA="YES"
    fi
    "$runtime_python" scripts/isaac_lab_cleanup/check_b1_map12_readiness.py \
      --b1-root "$b1_root" \
      --map12-root "$map12_root" \
      --alignment-artifact "$alignment_artifact" \
      --output "$readiness_output"
    if [[ "$prepare_robot_usd" == "true" && ! -s output/isaaclab/robots/rby1m/rby1m_holobase_isaac.usda ]]; then
      "$runtime_python" scripts/isaac_lab_cleanup/import_rby1m_robot_usd.py --static-only
    fi
    smoke_args=(
      scripts/isaac_lab_cleanup/run_b1_map12_navigation_smoke.py
      --readiness-artifact "$readiness_output" \
      --output-dir "$run_dir" \
      --robot-name "$robot_name" \
      --render-scene-usd "$render_scene_usd"
    )
    if [[ -n "$waypoint_pose_requests" ]]; then
      smoke_args+=(--waypoint-pose-requests "$waypoint_pose_requests")
    fi
    "$runtime_python" "${smoke_args[@]}"
    final_args=(
      --b1-root "$b1_root"
      --map12-root "$map12_root"
      --output "${run_dir}/readiness_with_navigation.json"
      --alignment-artifact "$alignment_artifact"
      --navigation-artifact "${run_dir}/navigation_smoke.json"
    )
    if [[ "$require_navigation_success" == "true" ]]; then
      final_args+=(--require-navigation-success)
    fi
    "$runtime_python" scripts/isaac_lab_cleanup/check_b1_map12_readiness.py "${final_args[@]}"
    report_args=(
      scripts/isaac_lab_cleanup/render_b1_map12_navigation_report.py
      --run-dir "$run_dir" \
      --navigation-artifact "${run_dir}/navigation_smoke.json" \
      --readiness-artifact "${run_dir}/readiness_with_navigation.json"
    )
    if [[ -n "$waypoint_pose_requests" ]]; then
      report_args+=(--waypoint-pose-requests "$waypoint_pose_requests")
    fi
    .venv/bin/python "${report_args[@]}"
    .venv/bin/python scripts/operator_console/render_scene_previews.py \
      --world b1-map12 \
      --b1-camera-artifact "${run_dir}/navigation_smoke.json" \
      --output-dir "${run_dir}/operator-preview"
    echo "==> report: ${run_dir}/report.html"
    echo "==> preview: ${run_dir}/operator-preview/b1-map12-preview.json"
