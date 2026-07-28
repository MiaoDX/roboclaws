# MolmoSpaces cleanup operator commands.
#
# This module is the human-facing facade for the ADR-0003 cleanup matrix.
# Use `driver` and cleanup input/evidence lane to make the public run shape explicit.
#
# Drivers:
# - direct          deterministic Python cleanup loop; no MCP server
# - mcp-smoke       deterministic ADR-0003 MCP tool smoke; no live LLM agent
# - openclaw-smoke  OpenClaw-labeled MCP smoke; no live Gateway
# - openai-agents-live OpenAI Agents SDK route connected to the cleanup MCP server
# - openclaw-live   live OpenClaw Gateway connected to the cleanup MCP server
#
# Cleanup evidence lanes:
# - smoke                  cheap verification preset; uses world-public labels
# - world-public-labels    public/sanitized world labels without oracle hints
# - camera-raw-fpv         raw camera artifacts to the agent
# - camera-grounded-labels camera-derived labels; requires camera_labeler
#
# Preferred entrypoints:
# - just molmo::quick-check
# - just molmo::review-report
# - just molmo::mcp-smoke-report
# - just molmo::openclaw-smoke-report
# - just molmo::camera-raw-fpv-report
# - just molmo::openclaw-report

set working-directory := '..'

timestamp_cmd := "TZ=Asia/Shanghai date +%m%d_%H%M"
default:
    @just --list molmo

# Private household-world implementation runner. Public callers should
# enter through `run::surface`; maintainers should enter through `agent::run`.
[private]
household-world-impl driver="mcp-smoke" profile="smoke" seeds="7" output_dir="output/molmo/cleanup" task="帮我收拾这个房间" generated_mess_count="10" host="127.0.0.1" port="18788" map_bundle="auto" cleanup_routine="auto" robot_views="auto" camera_labeler="" visual_grounding_timeout_s="auto" map_build="off" runtime_map_prior="" backend_override="auto" scene_source="procthor-10k-val" scene_index="0" isaac_scene_usd_path="" min_generated_mess_count_override="auto" generated_mess_object_ids="" task_surface="household-world" task_intent="cleanup" operator_messages_path="" b1_alignment_artifact="" b1_navigation_artifact="" skill_name="" goal_contract_json="" goal_contract_path="" run_dir_override="":
    #!/usr/bin/env bash
    set -euo pipefail

    driver="{{driver}}"
    profile="{{profile}}"
    seeds="{{seeds}}"
    output_dir="{{output_dir}}"
    task="{{task}}"
    generated_mess_count="{{generated_mess_count}}"
    host="{{host}}"
    port="{{port}}"
    map_bundle="{{map_bundle}}"
    cleanup_routine="{{cleanup_routine}}"
    robot_views="{{robot_views}}"
    camera_labeler="{{camera_labeler}}"
    visual_grounding=""
    visual_grounding_timeout_s="{{visual_grounding_timeout_s}}"
    map_build="{{map_build}}"
    runtime_map_prior="{{runtime_map_prior}}"
    backend_override="{{backend_override}}"
    scene_source="{{scene_source}}"
    scene_index="{{scene_index}}"
    isaac_scene_usd_path="{{isaac_scene_usd_path}}"
    min_generated_mess_count_override="{{min_generated_mess_count_override}}"
    generated_mess_object_ids="{{generated_mess_object_ids}}"
    generated_mess_manifest_path="${ROBOCLAWS_GENERATED_MESS_MANIFEST_PATH:-}"
    task_surface="{{task_surface}}"
    task_intent="{{task_intent}}"
    operator_messages_path="{{operator_messages_path}}"
    b1_alignment_artifact="{{b1_alignment_artifact}}"
    b1_navigation_artifact="{{b1_navigation_artifact}}"
    skill_name="{{skill_name}}"
    goal_contract_json="{{goal_contract_json}}"
    goal_contract_path="{{goal_contract_path}}"
    run_dir_override="{{run_dir_override}}"

    # Just recipe parameters are positional. Strip optional key= prefixes for
    # the first axes so maintainer callers can use key=value style.
    driver="${driver#driver=}"
    profile="${profile#profile=}"
    seeds="${seeds#seeds=}"
    output_dir="${output_dir#output_dir=}"
    task="${task#task=}"
    generated_mess_count="${generated_mess_count#generated_mess_count=}"
    host="${host#host=}"
    port="${port#port=}"
    map_bundle="${map_bundle#map_bundle=}"
    cleanup_routine="${cleanup_routine#cleanup_routine=}"
    robot_views="${robot_views#robot_views=}"
    robot_views="${robot_views#record_robot_views=}"
    profile="${profile#evidence_lane=}"
    camera_labeler="${camera_labeler#camera_labeler=}"
    camera_labeler="${camera_labeler#camera-labeler=}"
    visual_grounding_timeout_s="${visual_grounding_timeout_s#visual_grounding_timeout_s=}"
    visual_grounding_timeout_s="${visual_grounding_timeout_s#visual_grounding_timeout=}"
    map_build="${map_build#map_build=}"
    runtime_map_prior="${runtime_map_prior#runtime_map_prior=}"
    backend_override="${backend_override#backend=}"
    backend_override="${backend_override#backend_override=}"
    scene_source="${scene_source#scene_source=}"
    scene_index="${scene_index#scene_index=}"
    isaac_scene_usd_path="${isaac_scene_usd_path#isaac_scene_usd_path=}"
    min_generated_mess_count_override="${min_generated_mess_count_override#min_generated_mess_count=}"
    min_generated_mess_count_override="${min_generated_mess_count_override#min_generated_mess_count_override=}"
    generated_mess_object_ids="${generated_mess_object_ids#generated_mess_object_ids=}"
    task_surface="${task_surface#task_surface=}"
    task_surface="${task_surface#task-surface=}"
    task_surface="${task_surface:-household-world}"
    task_intent="${task_intent#task_intent=}"
    task_intent="${task_intent#task-intent=}"
    task_intent="${task_intent#intent=}"
    task_intent="${task_intent:-${ROBOCLAWS_TASK_INTENT:-cleanup}}"
    launch_world_id="${ROBOCLAWS_LAUNCH_WORLD_ID:-}"
    operator_messages_path="${operator_messages_path#operator_messages_path=}"
    operator_messages_path="${operator_messages_path#operator-messages-path=}"
    b1_alignment_artifact="${b1_alignment_artifact#b1_alignment_artifact=}"
    b1_alignment_artifact="${b1_alignment_artifact#b1-alignment-artifact=}"
    b1_navigation_artifact="${b1_navigation_artifact#b1_navigation_artifact=}"
    b1_navigation_artifact="${b1_navigation_artifact#b1-navigation-artifact=}"
    skill_name="${skill_name#skill_name=}"
    skill_name="${skill_name#skill-name=}"
    skill_name="${skill_name:-${ROBOCLAWS_TASK_SKILL:-}}"
    goal_contract_json="${goal_contract_json#goal_contract_json=}"
    goal_contract_json="${goal_contract_json#goal-contract-json=}"
    goal_contract_path="${goal_contract_path#goal_contract_path=}"
    goal_contract_path="${goal_contract_path#goal-contract-path=}"
    run_dir_override="${run_dir_override#run_dir=}"
    run_dir_override="${run_dir_override#run-dir=}"
    run_dir_override="${run_dir_override:-${ROBOCLAWS_MOLMO_RUN_DIR_OVERRIDE:-}}"
    goal_contract_json="${goal_contract_json:-${ROBOCLAWS_GOAL_CONTRACT_JSON:-}}"
    goal_contract_path="${goal_contract_path:-${ROBOCLAWS_GOAL_CONTRACT_PATH:-}}"
    operator_session_context_json="${ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON:-}"
    python_bin="${ROBOCLAWS_DEVTOOLS_PYTHON:-.venv/bin/python}"
    if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
      trace_map_bundle="$map_bundle"
      trace_isaac_scene_usd_path="$isaac_scene_usd_path"
      trace_b1_alignment_artifact="$b1_alignment_artifact"
      trace_b1_navigation_artifact="$b1_navigation_artifact"
      if [[ "$launch_world_id" == "b1-map12" || ( -n "$b1_alignment_artifact" && -n "$b1_navigation_artifact" ) ]]; then
        trace_map_bundle="<configured>"
        trace_isaac_scene_usd_path="<configured>"
        trace_b1_alignment_artifact="<configured>"
        trace_b1_navigation_artifact="<configured>"
      fi
      trace_args=(
        "$driver" "$profile" "$seeds" "$output_dir" "$task"
        "$generated_mess_count" "$host" "$port" "$trace_map_bundle"
        "$cleanup_routine" "$robot_views" "$camera_labeler"
        "$visual_grounding_timeout_s" "$map_build"
        "$runtime_map_prior" "$backend_override" "$scene_source"
        "$scene_index" "$trace_isaac_scene_usd_path"
        "$min_generated_mess_count_override" "$generated_mess_object_ids"
        "$task_surface" "$task_intent" "$operator_messages_path"
        "$trace_b1_alignment_artifact" "$trace_b1_navigation_artifact"
      )
      if [[ -n "$skill_name" || -n "$goal_contract_json" || -n "$goal_contract_path" || -n "$run_dir_override" ]]; then
        trace_args+=("$skill_name" "$goal_contract_json" "$goal_contract_path")
      fi
      if [[ -n "$run_dir_override" ]]; then
        trace_args+=("$run_dir_override")
      fi
      printf 'just\tmolmo::household-world-impl'
      for arg in "${trace_args[@]}"; do
        printf '\t%s' "$arg"
      done
      printf '\n'
      exit 0
    fi
    if [[ -z "$skill_name" ]]; then
      skill_name="household-world"
    fi
    managed_visual_grounding_pid=""
    managed_visual_grounding_stdout=""
    managed_visual_grounding_stderr=""
    open_ended_intent="false"
    if [[ "$task_intent" == "open-ended" ]]; then
      open_ended_intent="true"
    fi
    task_run_id="${task_surface}.${task_intent}"
    if [[ -z "$goal_contract_json" && -z "$goal_contract_path" ]]; then
      goal_contract_json="$(
        ROBOCLAWS_TASK_INTENT="$task_intent" ROBOCLAWS_TASK_PROMPT="$task" .venv/bin/python -c 'import os; from roboclaws.launch.catalog import SURFACE_SPECS; from roboclaws.launch.goals import normalize_goal_contract; from roboclaws.launch.intents import TASK_INTENT_SPECS; print(normalize_goal_contract(surface=SURFACE_SPECS["household-world"], intent=TASK_INTENT_SPECS[os.environ["ROBOCLAWS_TASK_INTENT"]], raw_prompt=os.environ.get("ROBOCLAWS_TASK_PROMPT", "")).to_json())'
      )"
    fi
    goal_contract_args=()
    if [[ -n "$goal_contract_json" ]]; then
      goal_contract_args+=(--goal-contract-json "$goal_contract_json")
    fi
    if [[ -n "$goal_contract_path" ]]; then
      goal_contract_args+=(--goal-contract "$goal_contract_path")
    fi
    generated_mess_success_threshold=$(( (generated_mess_count * 7 + 9) / 10 ))

    if [[ "$camera_labeler" == visual_grounding=* ]]; then
      echo "error: visual_grounding is no longer a public task axis; use camera_labeler=<labeler> with evidence_lane=camera-grounded-labels" >&2
      exit 1
    fi
    if [[ "$profile" == "camera-grounded-labels" ]]; then
      if [[ -z "$camera_labeler" ]]; then
        echo "error: evidence_lane=camera-grounded-labels requires camera_labeler" >&2
        exit 1
      fi
      case "$camera_labeler" in
        grounding-dino|yoloe|omdet-turbo|yolo-world)
          visual_grounding="$camera_labeler"
          ;;
        *)
          echo "error: unsupported camera_labeler '$camera_labeler'" >&2
          exit 1
          ;;
      esac
    else
      if [[ -n "$camera_labeler" ]]; then
        echo "error: camera_labeler is only valid for evidence_lane=camera-grounded-labels" >&2
        exit 1
      fi
      visual_grounding="sim"
    fi

    case "$driver" in
      direct|mcp-smoke|openclaw-smoke|openai-agents-live|openclaw-live)
        ;;
      *)
        echo "error: unsupported driver '$driver'" >&2
        echo "       expected direct|mcp-smoke|openclaw-smoke|openai-agents-live|openclaw-live" >&2
        echo "       use mcp-smoke/openclaw-smoke for deterministic substitutes; live agent names are explicit" >&2
        exit 1
        ;;
    esac

    case "$cleanup_routine" in
      auto|skill)
        ;;
      *)
        echo "error: unsupported cleanup_routine '$cleanup_routine' (expected auto|skill)" >&2
        exit 1
        ;;
    esac

    case "$robot_views" in
      auto|on|off|true|false|1|0)
        ;;
      *)
        echo "error: unsupported robot_views '$robot_views' (expected auto|on|off)" >&2
        exit 1
        ;;
    esac

    map_build_enabled="false"
    case "$map_build" in
      on|true|1|yes|map-build)
        map_build_enabled="true"
        ;;
      off|false|0|no|"")
        ;;
      *)
        echo "error: unsupported map_build '$map_build' (expected on|off)" >&2
        exit 1
        ;;
    esac
    if [[ "$map_build_enabled" == "true" && "$driver" != "direct" && "$driver" != "openai-agents-live" ]]; then
      echo "error: map-build mode currently supports direct or openai-agents-live driver only" >&2
      exit 1
    fi
    perception_mode="visible_object_detections"
    visual_args=()
    checker_visual_args=()
    profile_requires_clean_success="true"
    visual_grounding_args=()
    runtime_map_prior_args=()
    if [[ "$visual_grounding" != "sim" ]]; then
      visual_grounding_args=(--visual-grounding "$visual_grounding")
      if [[ "$visual_grounding_timeout_s" != "auto" && -n "$visual_grounding_timeout_s" ]]; then
        visual_grounding_args+=(--visual-grounding-timeout-s "$visual_grounding_timeout_s")
      fi
    fi
    if [[ -n "$runtime_map_prior" ]]; then
      runtime_map_prior_args=(--runtime-map-prior "$runtime_map_prior")
    fi
    case "$profile" in
      smoke)
        backend="api_semantic_synthetic"
        min_generated_mess_count="$generated_mess_count"
        implementation_evidence_lane="world-public-labels"
        ;;
      world-public-labels)
        backend="molmospaces_subprocess"
        min_generated_mess_count="$generated_mess_count"
        implementation_evidence_lane="$profile"
        visual_args=(--include-robot --robot-name rby1m)
        checker_visual_args=(
          --require-waypoint-honesty
          --require-real-robot-alignment
          --min-semantic-accepted-count 5
          --min-sweep-coverage 1.0
        )
        if [[ "$robot_views" != "off" && "$robot_views" != "false" && "$robot_views" != "0" ]]; then
          visual_args+=(--record-robot-views)
          checker_visual_args=(--require-robot-views "${checker_visual_args[@]}")
        fi
        ;;
      camera-raw-fpv)
        backend="molmospaces_subprocess"
        min_generated_mess_count="$generated_mess_count"
        implementation_evidence_lane="$profile"
        perception_mode="raw_fpv_only"
        raw_fpv_required_cleanup_count="$generated_mess_success_threshold"
        visual_args=(--include-robot --robot-name rby1m --record-robot-views)
        checker_visual_args=(
          --require-robot-views
          --require-raw-fpv-observations
          --require-model-declared-observations
          --min-model-declared-observations "$raw_fpv_required_cleanup_count"
          --min-model-declared-actions "$raw_fpv_required_cleanup_count"
          --min-semantic-accepted-count "$raw_fpv_required_cleanup_count"
          --min-sweep-coverage 1.0
        )
        ;;
      camera-grounded-labels)
        if [[ "$launch_world_id" == "b1-map12" ]]; then
          backend="isaaclab_subprocess"
        else
          backend="molmospaces_subprocess"
        fi
        min_generated_mess_count="$generated_mess_count"
        implementation_evidence_lane="$profile"
        perception_mode="camera_model_policy"
        visual_args=(--include-robot --robot-name rby1m --record-robot-views)
        checker_visual_args=(--require-robot-views --require-camera-model-policy)
        if [[ "$visual_grounding" != "sim" ]]; then
          checker_visual_args+=(
            --expect-visual-grounding-pipeline "$visual_grounding"
            --allow-partial-cleanup
            --min-sweep-coverage 1.0
          )
        fi
        ;;
      *)
        echo "error: unsupported cleanup lane '$profile' (expected smoke|world-public-labels|camera-grounded-labels|camera-raw-fpv)" >&2
        exit 1
        ;;
    esac
    case "$backend_override" in
      auto|"")
        ;;
      *)
        backend="$("$python_bin" -m roboclaws.launch.backends cleanup-implementation-backend "$backend_override")"
        ;;
    esac
    if [[ "$backend" == "isaaclab_subprocess" && "$launch_world_id" != "b1-map12" ]]; then
      echo "error: backend=isaaclab_subprocess is scoped to world=b1-map12; MolmoSpaces household routes use backend=molmospaces_subprocess" >&2
      exit 1
    fi
    if [[ "$backend" == "isaaclab_subprocess" && "$launch_world_id" == "b1-map12" ]]; then
      for required_input in map_bundle isaac_scene_usd_path b1_alignment_artifact b1_navigation_artifact; do
        if [[ -z "${!required_input}" ]]; then
          echo "error: world=b1-map12 requires explicit ${required_input}" >&2
          exit 1
        fi
      done
      if [[ ! -d "$map_bundle" ]]; then
        echo "error: world=b1-map12 received invalid map_bundle" >&2
        exit 1
      fi
      for required_file in isaac_scene_usd_path b1_alignment_artifact b1_navigation_artifact; do
        if [[ ! -f "${!required_file}" ]]; then
          echo "error: world=b1-map12 received invalid ${required_file}" >&2
          exit 1
        fi
      done
      isaac_min_semantic_accepted_count="$generated_mess_count"
      if [[ "$min_generated_mess_count_override" != "auto" && -n "$min_generated_mess_count_override" ]]; then
        isaac_min_semantic_accepted_count="$min_generated_mess_count_override"
      fi
      case "$profile" in
        world-public-labels)
          checker_visual_args=(
            --require-waypoint-honesty
            --require-b1-robot-consumption-proof
            --min-semantic-accepted-count "$isaac_min_semantic_accepted_count"
            --min-sweep-coverage 1.0
          )
          ;;
        camera-grounded-labels)
          checker_visual_args=(
            --require-robot-views
            --require-camera-model-policy
            --expect-visual-grounding-pipeline "$visual_grounding"
            --require-waypoint-honesty
            --require-b1-robot-consumption-proof
            --min-sweep-coverage 1.0
          )
          ;;
        camera-raw-fpv)
          ;;
      esac
      if [[ "$profile" != "camera-grounded-labels" && "$robot_views" != "off" && "$robot_views" != "false" && "$robot_views" != "0" ]]; then
        checker_visual_args=(--require-robot-views "${checker_visual_args[@]}")
      fi
    fi
    if [[ "$cleanup_routine" == "auto" ]]; then
      cleanup_routine="skill"
    fi
    if [[ "$min_generated_mess_count_override" != "auto" && -n "$min_generated_mess_count_override" ]]; then
      min_generated_mess_count="$min_generated_mess_count_override"
    fi
    checker_map_build_args=()
    if [[ "$map_build_enabled" == "true" && "$driver" == "openai-agents-live" ]]; then
      checker_map_build_args=(--require-runtime-metric-map)
      profile_requires_clean_success="false"
      filtered_checker_visual_args=()
      skip_checker_arg_value="false"
      for checker_arg in "${checker_visual_args[@]}"; do
        if [[ "$skip_checker_arg_value" == "true" ]]; then
          skip_checker_arg_value="false"
          continue
        fi
        case "$checker_arg" in
          --min-semantic-accepted-count|--min-model-declared-observations|--min-model-declared-actions)
            skip_checker_arg_value="true"
            ;;
          --require-model-declared-observations)
            ;;
          *)
            filtered_checker_visual_args+=("$checker_arg")
            ;;
        esac
      done
      checker_visual_args=("${filtered_checker_visual_args[@]}")
    elif [[ "$map_build_enabled" == "true" ]]; then
      checker_map_build_args=(--require-map-build)
      profile_requires_clean_success="false"
      filtered_checker_visual_args=()
      skip_checker_arg_value="false"
      for checker_arg in "${checker_visual_args[@]}"; do
        if [[ "$skip_checker_arg_value" == "true" ]]; then
          skip_checker_arg_value="false"
          continue
        fi
        case "$checker_arg" in
          --min-semantic-accepted-count|--min-model-declared-observations|--min-model-declared-actions)
            skip_checker_arg_value="true"
            ;;
          --require-model-declared-observations)
            ;;
          *)
            filtered_checker_visual_args+=("$checker_arg")
            ;;
        esac
      done
      checker_visual_args=("${filtered_checker_visual_args[@]}")
    fi
    if [[ "$open_ended_intent" == "true" ]]; then
      profile_requires_clean_success="false"
      filtered_checker_visual_args=()
      skip_checker_arg_value="false"
      for checker_arg in "${checker_visual_args[@]}"; do
        if [[ "$skip_checker_arg_value" == "true" ]]; then
          skip_checker_arg_value="false"
          continue
        fi
        case "$checker_arg" in
          --min-semantic-accepted-count|--min-model-declared-observations|--min-model-declared-actions|--min-sweep-coverage)
            skip_checker_arg_value="true"
            ;;
          --require-clean-agent-run|--require-model-declared-observations)
            ;;
          *)
            filtered_checker_visual_args+=("$checker_arg")
            ;;
        esac
      done
      checker_visual_args=("${filtered_checker_visual_args[@]}")
    fi
    checker_map_build_args+=(--require-base-metric-map)

    map_bundle_dir="$map_bundle"
    case "$map_bundle_dir" in
      auto)
        map_bundle_dir="$(
          "$python_bin" -m roboclaws.launch.map_bundles \
            --scene-source "$scene_source" \
            --scene-index "$scene_index"
        )"
        ;;
    esac
    if [[ "$map_bundle_dir" =~ ^(none|false|off)$ ]]; then
      echo "error: ${task_surface}/${task_intent} on backend '${backend:-auto}' requires a selected prebuilt Nav2 map bundle; map_bundle=${map_bundle_dir} is not allowed" >&2
      echo "hint: generate the canonical scene bundle with scripts/maps/generate_molmospaces_scene_bundles.py --scene ${scene_source}/${scene_index} --force" >&2
      exit 1
    fi
    if [[ -n "$map_bundle_dir" && "$map_bundle_dir" != */* && -d "assets/maps/${map_bundle_dir}" ]]; then
      map_bundle_dir="assets/maps/${map_bundle_dir}"
    fi
    if [[ "$backend" == "isaaclab_subprocess" && "$launch_world_id" == "b1-map12" ]]; then
      b1_base_map_bundle_dir="${output_dir}/b1-map12-base-metric-map"
      b1_runtime_map_bundle_dir="${output_dir}/b1-map12-base-metric-map-with-proof"
      "$python_bin" scripts/maps/build_b1_map12_base_metric_map.py \
        --map-bundle "$map_bundle_dir" \
        --output-dir "$b1_base_map_bundle_dir" >/dev/null
      "$python_bin" scripts/maps/augment_b1_map12_base_metric_map.py \
        --base-map-bundle "$b1_base_map_bundle_dir" \
        --alignment-artifact "$b1_alignment_artifact" \
        --navigation-artifact "$b1_navigation_artifact" \
        --output-dir "$b1_runtime_map_bundle_dir" >/dev/null
      cp "$b1_runtime_map_bundle_dir/b1_robot_consumption_manifest.json" \
        "${output_dir}/b1_robot_consumption_manifest.json"
      "$python_bin" scripts/maps/convert_nav2_cleanup_bundle.py \
        "$b1_runtime_map_bundle_dir" \
        --output "${output_dir}/runtime_map_prior_snapshot.json" \
        --summary-json "${output_dir}/runtime_map_prior_targets.json" >/dev/null
      map_bundle_dir="$b1_runtime_map_bundle_dir"
    fi
    map_bundle_args=()
    if [[ -n "$map_bundle_dir" ]]; then
      .venv/bin/python scripts/maps/check_bundle.py "$map_bundle_dir" >/dev/null
      map_bundle_args=(--map-bundle-dir "$map_bundle_dir")
    fi
    isaac_scene_args=()
    if [[ -n "$isaac_scene_usd_path" ]]; then
      isaac_scene_args=(--isaac-scene-usd-path "$isaac_scene_usd_path")
    fi
    generated_mess_object_args=()
    if [[ -n "$generated_mess_object_ids" ]]; then
      IFS=',' read -r -a generated_mess_object_id_items <<< "$generated_mess_object_ids"
      for generated_mess_object_id in "${generated_mess_object_id_items[@]}"; do
        generated_mess_object_id="${generated_mess_object_id#"${generated_mess_object_id%%[![:space:]]*}"}"
        generated_mess_object_id="${generated_mess_object_id%"${generated_mess_object_id##*[![:space:]]}"}"
        if [[ -n "$generated_mess_object_id" ]]; then
          generated_mess_object_args+=(--generated-mess-object-id "$generated_mess_object_id")
        fi
      done
    fi
    generated_mess_manifest_args=()
    if [[ -n "$generated_mess_manifest_path" ]]; then
      generated_mess_manifest_args=(--generated-mess-manifest-path "$generated_mess_manifest_path")
    fi
    if [[ -z "$map_bundle_dir" ]]; then
      echo "error: profile '$profile' requires a selected prebuilt Nav2 map bundle" >&2
      echo "hint: generate the canonical scene bundle with scripts/maps/generate_molmospaces_scene_bundles.py --scene ${scene_source}/${scene_index} --force" >&2
      exit 1
    fi

    stamp="$({{timestamp_cmd}})"
    run_root="${output_dir}/${stamp}"
    mkdir -p "$run_root"

    copy_b1_run_artifacts_to_seed_dir() {
      local artifact_run_dir="$1"
      if [[ "$backend" != "isaaclab_subprocess" || "$launch_world_id" != "b1-map12" ]]; then
        return 0
      fi
      for b1_run_artifact in \
        b1_robot_consumption_manifest.json \
        runtime_map_prior_snapshot.json \
        runtime_map_prior_targets.json
      do
        if [[ ! -f "${output_dir}/${b1_run_artifact}" ]]; then
          echo "error: required B1 run artifact is missing: ${output_dir}/${b1_run_artifact}" >&2
          return 1
        fi
        cp "${output_dir}/${b1_run_artifact}" "${artifact_run_dir}/${b1_run_artifact}"
      done
    }

    echo "==> Molmo cleanup matrix"
    echo "    driver   : ${driver}"
    echo "    lane     : ${profile}"
    echo "    evidence : ${implementation_evidence_lane}"
    echo "    backend  : ${backend}"
    echo "    input    : ${perception_mode}"
    echo "    map      : ${map_bundle_dir:-not required}"
    echo "    routine  : ${cleanup_routine}"
    echo "    map build: ${map_build_enabled}"
    echo "    views    : ${robot_views}"
    echo "    seeds    : ${seeds}"
    echo "    run root : ${run_root}"
    check_visual_grounding_readiness_for_run() {
      local readiness_run_dir="$1"
      if [[ "$profile" != "camera-grounded-labels" || "$visual_grounding" == "sim" ]]; then
        return 0
      fi
      ensure_visual_grounding_sidecar_for_run "$readiness_run_dir"
    }
    run_visual_grounding_readiness_for_run() {
      local readiness_run_dir="$1"
      local -a readiness_args=(
        --pipeline "$visual_grounding"
        --require-real-adapter
        --output "${readiness_run_dir}/visual_grounding_readiness.json"
      )
      if [[ "$visual_grounding_timeout_s" != "auto" && -n "$visual_grounding_timeout_s" ]]; then
        readiness_args+=(--timeout-s "$visual_grounding_timeout_s")
      fi
      .venv/bin/python scripts/visual_grounding/check_visual_grounding_readiness.py \
        "${readiness_args[@]}"
    }
    visual_grounding_readiness_reason() {
      local readiness_path="$1"
      if [[ ! -f "$readiness_path" ]]; then
        return 1
      fi
      .venv/bin/python -c 'import json, sys; from pathlib import Path; payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); print(str(payload.get("reason") or ""))' "$readiness_path"
    }
    visual_grounding_autostart_enabled() {
      local value="${ROBOCLAWS_AUTOSTART_VISUAL_GROUNDING_SIDECAR:-1}"
      case "${value,,}" in
        0|false|no|off)
          return 1
          ;;
      esac
      return 0
    }
    visual_grounding_base_url() {
      printf '%s\n' "${VISUAL_GROUNDING_BASE_URL:-http://127.0.0.1:18880}"
    }
    visual_grounding_local_endpoint() {
      .venv/bin/python -c 'import os, sys; from urllib.parse import urlparse; parsed = urlparse(os.environ.get("VISUAL_GROUNDING_BASE_URL", "http://127.0.0.1:18880")); host = parsed.hostname or "127.0.0.1"; port = parsed.port or (443 if parsed.scheme == "https" else 80); sys.exit(1) if parsed.scheme not in {"", "http"} or host not in {"127.0.0.1", "localhost", "::1"} else None; print(f"{host}\t{port}")'
    }
    start_managed_visual_grounding_sidecar() {
      local readiness_run_dir="$1"
      if [[ -n "$managed_visual_grounding_pid" ]]; then
        return 0
      fi
      local endpoint
      if ! endpoint="$(visual_grounding_local_endpoint)"; then
        return 1
      fi
      local sidecar_host="${endpoint%%$'\t'*}"
      local sidecar_port="${endpoint##*$'\t'}"
      local sidecar_python=".venv-visual-grounding/bin/python"
      if [[ ! -x "$sidecar_python" ]]; then
        sidecar_python=".venv/bin/python"
      fi
      if [[ ! -x "$sidecar_python" ]]; then
        return 1
      fi
      local sidecar_dir="${readiness_run_dir}/visual_grounding_sidecar"
      mkdir -p "$sidecar_dir"
      managed_visual_grounding_stdout="${sidecar_dir}/stdout.log"
      managed_visual_grounding_stderr="${sidecar_dir}/stderr.log"
      echo "==> starting managed visual grounding sidecar: $(visual_grounding_base_url) pipeline=real-router adapter_mode=real"
      "$sidecar_python" scripts/visual_grounding/serve_visual_grounding_service.py \
        --host "$sidecar_host" \
        --port "$sidecar_port" \
        --pipeline real-router \
        --adapter-mode real \
        >"$managed_visual_grounding_stdout" \
        2>"$managed_visual_grounding_stderr" &
      managed_visual_grounding_pid="$!"
      for _ in {1..75}; do
        if ! kill -0 "$managed_visual_grounding_pid" >/dev/null 2>&1; then
          wait "$managed_visual_grounding_pid" >/dev/null 2>&1 || true
          managed_visual_grounding_pid=""
          return 1
        fi
        if (echo > /dev/tcp/"$sidecar_host"/"$sidecar_port") >/dev/null 2>&1; then
          return 0
        fi
        sleep 0.2
      done
      return 1
    }
    stop_managed_visual_grounding_sidecar() {
      set +e
      if [[ -n "$managed_visual_grounding_pid" ]]; then
        if kill -0 "$managed_visual_grounding_pid" >/dev/null 2>&1; then
          kill "$managed_visual_grounding_pid" >/dev/null 2>&1 || true
          wait "$managed_visual_grounding_pid" >/dev/null 2>&1 || true
        fi
        managed_visual_grounding_pid=""
      fi
    }
    trap stop_managed_visual_grounding_sidecar EXIT
    ensure_visual_grounding_sidecar_for_run() {
      local readiness_run_dir="$1"
      local readiness_path="${readiness_run_dir}/visual_grounding_readiness.json"
      local readiness_probe_stderr="${readiness_run_dir}/visual_grounding_readiness_probe.stderr.log"
      if run_visual_grounding_readiness_for_run "$readiness_run_dir" 2>"$readiness_probe_stderr"; then
        return 0
      fi
      local reason
      reason="$(visual_grounding_readiness_reason "$readiness_path" || true)"
      if [[ "$reason" != "connection_error" ]]; then
        cat "$readiness_probe_stderr" >&2 || true
        return 1
      fi
      if ! visual_grounding_autostart_enabled; then
        cat "$readiness_probe_stderr" >&2 || true
        return 1
      fi
      if ! start_managed_visual_grounding_sidecar "$readiness_run_dir"; then
        echo "error: failed to auto-start visual grounding sidecar at $(visual_grounding_base_url)" >&2
        if [[ -n "$managed_visual_grounding_stderr" ]]; then
          echo "sidecar stderr: $managed_visual_grounding_stderr" >&2
        fi
        return 1
      fi
      run_visual_grounding_readiness_for_run "$readiness_run_dir"
    }
    interactive_visual_cap="${ROBOCLAWS_MOLMO_INTERACTIVE_VISUAL_BACKEND_CAP:-1}"
    if [[ "${ROBOCLAWS_MOLMO_ALLOW_BATCH_VISUAL_BACKENDS:-0}" == "1" ]]; then
      interactive_visual_cap="${ROBOCLAWS_MOLMO_MAX_VISUAL_BACKENDS:-1}"
    fi

    live_drivers=(openai-agents-live openclaw-live)
    for live_driver in "${live_drivers[@]}"; do
      if [[ "$driver" == "$live_driver" ]]; then
        seed_count="$(wc -w <<<"$seeds" | tr -d ' ')"
        if [[ "$seed_count" != "1" ]]; then
          echo "error: live agent drivers accept exactly one seed per interactive run" >&2
          exit 1
        fi
        seed="$seeds"
        run_dir="${run_root}/seed-${seed}"
        if [[ -n "$run_dir_override" ]]; then
          run_dir="$run_dir_override"
        fi
        mkdir -p "$run_dir"
        check_visual_grounding_readiness_for_run "$run_dir"
        copy_b1_run_artifacts_to_seed_dir "$run_dir"
        policy="${driver%-live}_agent"
        if [[ "$driver" == "openai-agents-live" ]]; then
          policy="openai_agents_agent"
        fi
        server_host="$host"
        client_url="http://${host}:${port}/mcp"
        server_startup_timeout_s="${ROBOCLAWS_MOLMO_LIVE_SERVER_STARTUP_TIMEOUT_S:-600}"
        if [[ "$driver" == "openclaw-live" ]]; then
          bash scripts/dev/network_status.sh --assert-off-work "OpenClaw Molmo cleanup live report"
          server_host="0.0.0.0"
          client_url="http://host.docker.internal:${port}/mcp"
        elif [[ "$driver" == "openai-agents-live" ]]; then
          source scripts/dev/coding_agent_env.sh
          roboclaws_load_dotenv .env
          roboclaws_assert_openai_agents_provider_allowed
        fi
        openai_agents_model=""
        openai_agents_profile=""
        openai_agents_profile_summary=""
        if [[ "$driver" == "openai-agents-live" ]]; then
          openai_agents_profile="$(roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE)"
          openai_agents_model="$(roboclaws_code_agent_model ROBOCLAWS_OPENAI_AGENTS_MODEL ROBOCLAWS_PROVIDER_PROFILE)"
          openai_agents_profile_summary="$(roboclaws_code_agent_profile_summary ROBOCLAWS_PROVIDER_PROFILE ROBOCLAWS_OPENAI_AGENTS_MODEL)"
        fi
        prompt_cleanup_count="$generated_mess_count"
        if [[ "$profile" == "camera-raw-fpv" ]]; then
          prompt_cleanup_count="$generated_mess_success_threshold"
        fi
        prompt_raw_fpv_candidate_budget="${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET:-24}"
        prompt_max_observe_per_waypoint="${ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT:-1}"
        if [[ "$profile" == "camera-raw-fpv" && -z "${ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT:-}" ]]; then
          prompt_max_observe_per_waypoint="4"
        fi
        prompt_done_retry_budget="${ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET:-1}"
        prompt_args=(
          --profile "$profile"
          --intent "$task_intent"
          --task "$task"
          --target-cleanup-count "$prompt_cleanup_count"
          --raw-fpv-candidate-budget "$prompt_raw_fpv_candidate_budget"
          --max-observe-per-waypoint "$prompt_max_observe_per_waypoint"
          --done-retry-budget "$prompt_done_retry_budget"
        )
        if [[ -n "$operator_session_context_json" ]]; then
          prompt_args+=(--operator-session-context-json "$operator_session_context_json")
        fi
        if [[ "$driver" == "openai-agents-live" && "$profile" == "camera-grounded-labels" ]]; then
          case "${ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_COMPOSITE_TOOLS:-}" in
            1|true|True|TRUE|yes|Yes|YES|on|On|ON)
              prompt_args+=(--camera-grounded-composite-tools)
              ;;
          esac
        fi
        prompt_args+=("${goal_contract_args[@]}")
        kickoff_prompt="$(.venv/bin/python -m roboclaws.agents.prompts.household_cleanup "${prompt_args[@]}")"

        server_args=(
          --host "$server_host"
          --port "$port"
          --output-dir "$run_dir"
          --seed "$seed"
          --policy "$policy"
          --intent "$task_intent"
          --backend "$backend"
          --task "$task"
          --generated-mess-count "$generated_mess_count"
          "${generated_mess_object_args[@]}"
          "${generated_mess_manifest_args[@]}"
          --perception-mode "$perception_mode"
          --evidence-lane "$implementation_evidence_lane"
          --scene-source "$scene_source"
          --scene-index "$scene_index"
          "${map_bundle_args[@]}"
          "${visual_args[@]}"
          "${visual_grounding_args[@]}"
          "${runtime_map_prior_args[@]}"
        )
        server_args+=("${goal_contract_args[@]}")
        if [[ -n "$isaac_scene_usd_path" ]]; then
          server_args+=(--isaac-scene-usd-path "$isaac_scene_usd_path")
        fi
        if [[ -n "$operator_messages_path" ]]; then
          server_args+=(--operator-messages-path "$operator_messages_path")
        fi
        operator_resume_requests_path="${ROBOCLAWS_OPERATOR_RESUME_REQUESTS_PATH:-}"
        live_lock_backend="${backend//[^A-Za-z0-9_.-]/-}"
        openai_agents_lock_path="output/molmo/live-locks/${live_lock_backend}.openai-agents.lock"

        if [[ "$driver" == "openai-agents-live" ]]; then
          probe_host="$host"
          if [[ "$probe_host" == "0.0.0.0" || "$probe_host" == "::" ]]; then
            probe_host="127.0.0.1"
          fi
          if (echo > /dev/tcp/"$probe_host"/"$port") >/dev/null 2>&1; then
            echo "error: requested MCP port ${host}:${port} is already accepting connections" >&2
            echo "       refusing to choose another port because each live visual cleanup run owns a MuJoCo-backed backend" >&2
            exit 1
          fi

          status_path="${run_dir}/live_status.json"
          openai_agents_mcp_client_session_timeout_s="${ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S:-30}"
          if [[ -z "${ROBOCLAWS_OPENAI_AGENTS_MCP_CLIENT_SESSION_TIMEOUT_S:-}" && "$backend" == "isaaclab_subprocess" ]]; then
            openai_agents_mcp_client_session_timeout_s="120"
          fi
          runner_args=(
            .venv/bin/python
            scripts/molmo_cleanup/run_live_openai_agents_household.py
            --repo-root "$PWD"
            --run-dir "$run_dir"
            --status-path "$status_path"
            --client-url "$client_url"
            --host "$host"
            --port "$port"
            --lock-path "$openai_agents_lock_path"
            --provider-profile "$openai_agents_profile"
            --model "$openai_agents_model"
            --mcp-client-session-timeout-s "$openai_agents_mcp_client_session_timeout_s"
            --agent-sdk-perf-profile "${ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE:-}"
            --continuation-mode "${ROBOCLAWS_OPENAI_AGENTS_CONTINUATION_MODE:-}"
            --model-thinking-mode "${ROBOCLAWS_OPENAI_AGENTS_THINKING_MODE:-default}"
            --server-startup-timeout-s "$server_startup_timeout_s"
            --kickoff-prompt "$kickoff_prompt"
            --backend "$backend"
            --task-surface "$task_surface"
            --intent "$task_intent"
            --skill-name "$skill_name"
            --policy "$policy"
            --task "$task"
            --min-generated-mess-count "$min_generated_mess_count"
            --profile "$profile"
            --checker-profile "$implementation_evidence_lane"
          )
          if [[ -n "$operator_resume_requests_path" ]]; then
            runner_args+=(--operator-resume-requests-path "$operator_resume_requests_path")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS:-}" ]]; then
            runner_args+=(--max-turns "${ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS:-}" ]]; then
            runner_args+=(--incomplete-turn-continuation-attempts "${ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_CONTEXT_SOFT_LIMIT_TOKENS:-}" ]]; then
            runner_args+=(--context-soft-limit-tokens "${ROBOCLAWS_OPENAI_AGENTS_CONTEXT_SOFT_LIMIT_TOKENS}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_CONTEXT_HARD_LIMIT_TOKENS:-}" ]]; then
            runner_args+=(--context-hard-limit-tokens "${ROBOCLAWS_OPENAI_AGENTS_CONTEXT_HARD_LIMIT_TOKENS}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING:-}" ]]; then
            if [[ "${ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING}" =~ ^(0|false|False|FALSE|no|No|NO|off|Off|OFF)$ ]]; then
              runner_args+=(--no-model-racing)
            else
              runner_args+=(--model-racing)
            fi
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING_ARM_COUNT:-}" ]]; then
            runner_args+=(--model-racing-arm-count "${ROBOCLAWS_OPENAI_AGENTS_MODEL_RACING_ARM_COUNT}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT:-}" ]]; then
            runner_args+=(--max-observe-per-waypoint "${ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET:-}" ]]; then
            runner_args+=(--raw-fpv-candidate-budget "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_REPEATED_FAILURE_LIMIT:-}" ]]; then
            runner_args+=(--raw-fpv-repeated-failure-limit "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_REPEATED_FAILURE_LIMIT}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY:-}" ]]; then
            runner_args+=(--robot-view-capture-policy "${ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY:-}" ]]; then
            if [[ "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY}" =~ ^(0|false|False|FALSE|no|No|NO|off|Off|OFF)$ ]]; then
              runner_args+=(--no-raw-fpv-image-memory)
            else
              runner_args+=(--raw-fpv-image-memory)
            fi
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY_RETAIN:-}" ]]; then
            runner_args+=(--raw-fpv-image-memory-retain "${ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_IMAGE_MEMORY_RETAIN}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_COMPACTION:-}" ]]; then
            if [[ "${ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_COMPACTION}" =~ ^(0|false|False|FALSE|no|No|NO|off|Off|OFF)$ ]]; then
              runner_args+=(--no-camera-grounded-history-compaction)
            else
              runner_args+=(--camera-grounded-history-compaction)
            fi
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_RETAIN:-}" ]]; then
            runner_args+=(--camera-grounded-history-retain "${ROBOCLAWS_OPENAI_AGENTS_CAMERA_GROUNDED_HISTORY_RETAIN}")
          fi
          if [[ -n "${ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET:-}" ]]; then
            runner_args+=(--done-retry-budget "${ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET}")
          fi
          if [[ "${ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST:-true}" =~ ^(0|false|False|FALSE|no|No|NO|off|Off|OFF)$ ]]; then
            runner_args+=(--no-cache-tools-list)
          else
            runner_args+=(--cache-tools-list)
          fi
          for arg in "${server_args[@]}"; do
            runner_args+=("--server-arg=$arg")
          done
          for arg in "${checker_visual_args[@]}"; do
            runner_args+=("--checker-visual-arg=$arg")
          done

          echo "==> OpenAI Agents SDK provider for this run: ${openai_agents_profile_summary}"
          set +e
          "${runner_args[@]}"
          exit_code="$?"
          set -e
          stop_managed_visual_grounding_sidecar
          exit "$exit_code"
        fi

        visual_slot_path=""
        slot_run_id="$(basename "$run_root")/seed-${seed}"
        if [[ "$backend" == "molmospaces_subprocess" ]]; then
          visual_slot_json="$(.venv/bin/python -m roboclaws.household.visual_backend_slots acquire \
            --repo-root "$PWD" \
            --run-id "$slot_run_id" \
            --pid "$$" \
            --backend "$backend" \
            --port "$port" \
            --output-dir "$run_dir" \
            --status-path "${run_dir}/live_status.json" \
            --owner "$driver")"
          printf '%s\n' "$visual_slot_json" > "${run_dir}/visual_backend_slot.json"
          visual_slot_path="$(printf '%s' "$visual_slot_json" | .venv/bin/python -c 'import json, sys; print(json.load(sys.stdin)["path"])')"
        fi
        .venv/bin/python -m roboclaws.cli.agent_server household-world "${server_args[@]}" &
        server_pid="$!"
        cleanup_server() {
          set +e
          if kill -0 "$server_pid" >/dev/null 2>&1; then
            kill "$server_pid" >/dev/null 2>&1 || true
            wait "$server_pid" >/dev/null 2>&1 || true
          fi
          if [[ -n "$visual_slot_path" ]]; then
            .venv/bin/python -m roboclaws.household.visual_backend_slots release \
              --path "$visual_slot_path" \
              --run-id "$slot_run_id" \
              --pid "$$" >/dev/null 2>&1 || true
          fi
          stop_managed_visual_grounding_sidecar
        }
        trap cleanup_server EXIT INT TERM
        wait_for_mcp_ready() {
          local wait_host="$1"
          local wait_port="$2"
          for _ in {1..240}; do
            if (echo > /dev/tcp/"$wait_host"/"$wait_port") >/dev/null 2>&1; then
              return 0
            fi
            if ! kill -0 "$server_pid" >/dev/null 2>&1; then
              wait "$server_pid" >/dev/null 2>&1 || true
              return 1
            fi
            sleep 0.5
          done
          return 1
        }
        if ! wait_for_mcp_ready "$host" "$port"; then
          echo "error: cleanup MCP server did not become ready at ${host}:${port}" >&2
          exit 1
        fi

        echo "==> launching OpenClaw Gateway chat with household-world skill"
        echo "==> MCP URL from Gateway container: ${client_url}"
        SKILLS_DIR="$PWD/skills/household-world" \
          ROBOCLAWS_MCP_URL="$client_url" \
          just chat::run

        echo "==> waiting for cleanup MCP server to finish after agent done"
        wait "$server_pid"
        trap - EXIT INT TERM

        if [[ -f "${run_dir}/run_result.json" ]]; then
          if [[ "$open_ended_intent" == "true" ]]; then
            .venv/bin/python -m roboclaws.launch.open_ended_artifacts \
              "${run_dir}/run_result.json"
            echo "==> report: ${run_dir}/report.html"
            exit 0
          fi
          checker_args=(
            --expect-task "$task"
            --expect-backend "$backend"
            --expect-policy "$policy"
            --expect-profile "$implementation_evidence_lane"
            --expect-mcp-server household_world
            --min-generated-mess-count "$min_generated_mess_count"
            --require-agent-driven
            --require-advisory-scoring
            "${checker_visual_args[@]}"
          )
          if [[ "$driver" == "openclaw-live" ]]; then
            checker_args+=(--require-openclaw-minimum)
          fi
          if [[ "$profile_requires_clean_success" == "true" && "$driver" != "openclaw-live" && "$open_ended_intent" != "true" ]]; then
            checker_args+=(--require-clean-agent-run)
          fi
          .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
            "${checker_args[@]}" \
            "${run_dir}/run_result.json"
          echo "==> report: ${run_dir}/report.html"
        else
          echo "error: live run finished without ${run_dir}/run_result.json" >&2
          exit 1
        fi
        exit 0
      fi
    done

    for seed in $seeds; do
      run_dir="${run_root}/seed-${seed}"
      mkdir -p "$run_dir"
      check_visual_grounding_readiness_for_run "$run_dir"
      copy_b1_run_artifacts_to_seed_dir "$run_dir"
      case "$driver" in
        direct)
          .venv/bin/python -m roboclaws.household.household_world_episode \
            --seed "$seed" \
            --backend "$backend" \
            --task "$task" \
            --static-fixture-projection-mode room_only \
            --perception-mode "$perception_mode" \
            --evidence-lane "$implementation_evidence_lane" \
            "${map_bundle_args[@]}" \
            --generated-mess-count "$generated_mess_count" \
            "${generated_mess_object_args[@]}" \
            "${generated_mess_manifest_args[@]}" \
            --scene-source "$scene_source" \
            --scene-index "$scene_index" \
            "${visual_args[@]}" \
            "${visual_grounding_args[@]}" \
            "${runtime_map_prior_args[@]}" \
            --intent "$task_intent" \
            "${isaac_scene_args[@]}" \
            "${goal_contract_args[@]}" \
            --output-dir "$run_dir"
          ;;
        mcp-smoke|openclaw-smoke)
          policy="household_contract_smoke_agent"
          if [[ "$driver" == "openclaw-smoke" ]]; then
            policy="openclaw_agent"
          fi
          .venv/bin/python scripts/molmo_cleanup/run_molmo_realworld_agent_mcp_smoke.py \
            --seed "$seed" \
            --backend "$backend" \
            --task "$task" \
            "${goal_contract_args[@]}" \
            --policy "$policy" \
            --generated-mess-count "$generated_mess_count" \
            "${generated_mess_object_args[@]}" \
            "${generated_mess_manifest_args[@]}" \
            --perception-mode "$perception_mode" \
            --evidence-lane "$implementation_evidence_lane" \
            "${map_bundle_args[@]}" \
            "${visual_args[@]}" \
            "${visual_grounding_args[@]}" \
            "${runtime_map_prior_args[@]}" \
            --output-dir "$run_dir"
          ;;
      esac
    done

    if [[ "$open_ended_intent" == "true" ]]; then
      .venv/bin/python -m roboclaws.launch.open_ended_artifacts "$run_root"
      echo "==> reports:"
      find "$run_root" -maxdepth 2 -name report.html -print
      exit 0
    fi

    seed_csv="$(printf '%s' "$seeds" | tr ' ' ',')"
    checker_args=(
      --expect-task "$task"
      --expect-backend "$backend"
      --expect-seeds "$seed_csv"
      --expect-profile "$profile"
      --min-generated-mess-count "$min_generated_mess_count"
      --require-advisory-scoring
      "${checker_visual_args[@]}"
      "${checker_map_build_args[@]}"
    )
    case "$driver" in
      mcp-smoke)
        checker_args+=(
          --expect-policy household_contract_smoke_agent
          --expect-mcp-server household_world
          --require-agent-driven
        )
        if [[ "$profile_requires_clean_success" == "true" && "$open_ended_intent" != "true" ]]; then
          checker_args+=(--require-clean-agent-run)
        fi
        ;;
      openclaw-smoke)
        checker_args+=(
          --expect-policy openclaw_agent
          --expect-mcp-server household_world
          --require-agent-driven
          --require-openclaw-minimum
        )
        if [[ "$profile_requires_clean_success" == "true" && "$open_ended_intent" != "true" ]]; then
          checker_args+=(--require-clean-agent-run)
        fi
        ;;
    esac

    .venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
      "${checker_args[@]}" \
      "$run_root"
    echo "==> reports:"
    find "$run_root" -maxdepth 2 -name report.html -print

# Cheap default: deterministic MCP smoke on the synthetic backend.
quick-check driver="mcp-smoke" profile="smoke" seed="7" output_dir="output/molmo/quick-check" task="帮我收拾这个房间" generated_mess_count="10":
    just molmo::household-world-impl "{{driver}}" "{{profile}}" "{{seed}}" "{{output_dir}}" "{{task}}" "{{generated_mess_count}}"

# Canonical human review report: direct cleanup, real MolmoSpaces/RBY1M visuals.
review-report seeds="1 2 3" output_dir="output/molmo/review-report" task="帮我收拾这个房间" generated_mess_count="10":
    just molmo::household-world-impl direct world-public-labels "{{seeds}}" "{{output_dir}}" "{{task}}" "{{generated_mess_count}}"

# Deterministic ADR-0003 MCP tool smoke with real MolmoSpaces/RBY1M visuals.
mcp-smoke-report seed="7" output_dir="output/molmo/mcp-smoke-report" task="帮我收拾这个房间" generated_mess_count="10":
    just molmo::household-world-impl mcp-smoke world-public-labels "{{seed}}" "{{output_dir}}" "{{task}}" "{{generated_mess_count}}"

# OpenClaw-shaped/policy-labeled smoke with real MolmoSpaces/RBY1M visuals.
[private]
openclaw-smoke-report seed="7" output_dir="output/molmo/openclaw-smoke-report" task="帮我收拾这个房间" generated_mess_count="10":
    just molmo::household-world-impl openclaw-smoke world-public-labels "{{seed}}" "{{output_dir}}" "{{task}}" "{{generated_mess_count}}"

# Raw camera-input evidence report. This proves camera artifact plumbing, not cleanup success.
camera-raw-fpv-report seed="7" output_dir="output/molmo/camera-raw-fpv-report" task="帮我收拾这个房间" generated_mess_count="10":
    just molmo::household-world-impl direct camera-raw-fpv "{{seed}}" "{{output_dir}}" "{{task}}" "{{generated_mess_count}}"

# Probe a live-agent run. Defaults to the latest live cleanup report.
status path="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -n "{{path}}" ]]; then
      exec .venv/bin/python scripts/molmo_cleanup/summarize_live_run.py "{{path}}"
    fi
    exec .venv/bin/python scripts/molmo_cleanup/summarize_live_run.py

# Local rehearsal for the opt-in hosted Molmo live CI job.
ci-rehearsal entry="agents-sdk-kimi-k2.7-code" dry_run="":
    #!/usr/bin/env bash
    set -euo pipefail
    entry="{{entry}}"
    dry_run="{{dry_run}}"
    dry_args=()
    case "$dry_run" in
      ""|live)
        ;;
      --dry-run|dry-run|dry|true)
        dry_args=(--dry-run --skip-uv-sync --skip-prewarm)
        ;;
      *)
        echo "error: unsupported ci-rehearsal mode '$dry_run' (expected live or --dry-run)" >&2
        exit 1
        ;;
    esac
    .venv/bin/python scripts/molmo_cleanup/run_ci_live_cleanup_matrix.py \
      --entry "$entry" \
      --output-dir "output/molmo/ci-rehearsal" \
      --published-dir "output/molmo/ci-rehearsal/site/molmo/live" \
      "${dry_args[@]}"

# Serial local rehearsal for all Molmo live CI model/profile entries.
ci-rehearsal-all dry_run="":
    #!/usr/bin/env bash
    set -euo pipefail
    dry_run="{{dry_run}}"
    dry_args=()
    case "$dry_run" in
      ""|live)
        ;;
      --dry-run|dry-run|dry|true)
        dry_args=(--dry-run --skip-uv-sync --skip-prewarm)
        ;;
      *)
        echo "error: unsupported ci-rehearsal-all mode '$dry_run' (expected live or --dry-run)" >&2
        exit 1
        ;;
    esac
    .venv/bin/python scripts/molmo_cleanup/run_ci_live_cleanup_matrix.py \
      --all \
      --continue-on-error \
      --output-dir "output/molmo/ci-rehearsal" \
      --published-dir "output/molmo/ci-rehearsal/site/molmo/live" \
      "${dry_args[@]}"

# Build or execute the current MolmoSpaces apple-to-apple comparison grid.
apple2apple-grid mode="dry-run" output_dir="output/molmo/apple2apple-grid" seed="7" generated_mess_count="10" row="" runtime_map_prior="" visual_grounding_timeout_s="auto":
    #!/usr/bin/env bash
    set -euo pipefail
    mode="{{mode}}"
    output_dir="{{output_dir}}"
    seed="{{seed}}"
    generated_mess_count="{{generated_mess_count}}"
    row="{{row}}"
    runtime_map_prior="{{runtime_map_prior}}"
    visual_grounding_timeout_s="{{visual_grounding_timeout_s}}"

    mode="${mode#mode=}"
    output_dir="${output_dir#output_dir=}"
    seed="${seed#seed=}"
    generated_mess_count="${generated_mess_count#generated_mess_count=}"
    row="${row#row=}"
    runtime_map_prior="${runtime_map_prior#runtime_map_prior=}"
    visual_grounding_timeout_s="${visual_grounding_timeout_s#visual_grounding_timeout_s=}"

    args=(
      --output-dir "$output_dir"
      --seed "$seed"
      --generated-mess-count "$generated_mess_count"
      --visual-grounding-timeout-s "$visual_grounding_timeout_s"
    )
    if [[ -n "$row" ]]; then
      args+=(--row "$row")
    fi
    if [[ -n "$runtime_map_prior" ]]; then
      args+=(--runtime-map-prior "$runtime_map_prior")
    fi
    case "$mode" in
      dry-run|dry|"")
        ;;
      execute|run|live)
        args+=(--execute)
        ;;
      *)
        echo "error: unsupported apple2apple-grid mode '$mode' (expected dry-run or execute)" >&2
        exit 1
        ;;
    esac
    python_bin="${ROBOCLAWS_PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
      if [[ -x ".venv/bin/python" ]]; then
        python_bin=".venv/bin/python"
      elif command -v python3 >/dev/null 2>&1; then
        python_bin="python3"
      else
        python_bin="python"
      fi
    fi
    "$python_bin" scripts/molmo_cleanup/run_molmo_apple2apple_test_grid.py "${args[@]}"

# Live OpenClaw Gateway report. Starts the cleanup MCP server and then chat::run.
[private]
openclaw-report seed="7" output_dir="output/molmo/openclaw-report" task="帮我收拾这个房间" generated_mess_count="10" profile="world-public-labels" port="18788":
    just molmo::household-world-impl openclaw-live "{{profile}}" "{{seed}}" "{{output_dir}}" "{{task}}" "{{generated_mess_count}}" 0.0.0.0 "{{port}}"

# Render-only scene identity probe: same MolmoSpaces scene anchors through MuJoCo and Isaac.
scene-camera-comparison seed="7" generated_mess_count="1" output_dir="output/molmo/scene-camera-comparison" scene_source="procthor-10k-val" scene_index="1" scene_usd_path="output/isaaclab/flattened-semantic-usd/0604_val1_mujoco_body_pose_fix/scene_semantic.usda" render_width="960" render_height="640" lighting_profile="default":
    #!/usr/bin/env bash
    set -euo pipefail
    seed="{{seed}}"
    generated_mess_count="{{generated_mess_count}}"
    output_dir="{{output_dir}}"
    scene_source="{{scene_source}}"
    scene_index="{{scene_index}}"
    scene_usd_path="{{scene_usd_path}}"
    render_width="{{render_width}}"
    render_height="{{render_height}}"
    lighting_profile="{{lighting_profile}}"
    raw_args=(
      "$seed"
      "$generated_mess_count"
      "$output_dir"
      "$scene_source"
      "$scene_index"
      "$scene_usd_path"
      "$render_width"
      "$render_height"
      "$lighting_profile"
    )
    seed="${seed#seed=}"
    generated_mess_count="${generated_mess_count#generated_mess_count=}"
    output_dir="${output_dir#output_dir=}"
    scene_source="${scene_source#scene_source=}"
    scene_index="${scene_index#scene_index=}"
    scene_usd_path="${scene_usd_path#scene_usd_path=}"
    render_width="${render_width#render_width=}"
    render_height="${render_height#render_height=}"
    lighting_profile="${lighting_profile#lighting_profile=}"
    for override in "${raw_args[@]}"; do
      case "$override" in
        seed=*) seed="${override#seed=}" ;;
        generated_mess_count=*) generated_mess_count="${override#generated_mess_count=}" ;;
        output_dir=*) output_dir="${override#output_dir=}" ;;
        scene_source=*) scene_source="${override#scene_source=}" ;;
        scene_index=*) scene_index="${override#scene_index=}" ;;
        scene_usd_path=*) scene_usd_path="${override#scene_usd_path=}" ;;
        render_width=*) render_width="${override#render_width=}" ;;
        render_height=*) render_height="${override#render_height=}" ;;
        lighting_profile=*) lighting_profile="${override#lighting_profile=}" ;;
      esac
    done
    if [[ "$seed" == *=* && "${seed%%=*}" != "seed" ]]; then seed="7"; fi
    if [[ "$generated_mess_count" == *=* && "${generated_mess_count%%=*}" != "generated_mess_count" ]]; then generated_mess_count="1"; fi
    if [[ "$output_dir" == *=* && "${output_dir%%=*}" != "output_dir" ]]; then output_dir="output/molmo/scene-camera-comparison"; fi
    if [[ "$scene_source" == *=* && "${scene_source%%=*}" != "scene_source" ]]; then scene_source="procthor-10k-val"; fi
    if [[ "$scene_index" == *=* && "${scene_index%%=*}" != "scene_index" ]]; then scene_index="1"; fi
    if [[ "$scene_usd_path" == *=* && "${scene_usd_path%%=*}" != "scene_usd_path" ]]; then scene_usd_path="output/isaaclab/flattened-semantic-usd/0604_val1_mujoco_body_pose_fix/scene_semantic.usda"; fi
    if [[ "$render_width" == *=* && "${render_width%%=*}" != "render_width" ]]; then render_width="960"; fi
    if [[ "$render_height" == *=* && "${render_height%%=*}" != "render_height" ]]; then render_height="640"; fi
    if [[ "$lighting_profile" == *=* && "${lighting_profile%%=*}" != "lighting_profile" ]]; then lighting_profile="default"; fi

    molmospaces_python="${ROBOCLAWS_MOLMOSPACES_PYTHON:-.venv/bin/python}"
    isaac_python="${ROBOCLAWS_ISAACLAB_PYTHON:-.venv-isaaclab/bin/python}"
    if [[ ! -x "$molmospaces_python" ]]; then
      echo "error: missing MolmoSpaces runtime: ${molmospaces_python}" >&2
      echo "       run: uv sync --extra dev" >&2
      exit 1
    fi
    if [[ ! -x "$isaac_python" ]]; then
      echo "error: missing Isaac Lab runtime: ${isaac_python}" >&2
      echo "       create .venv-isaaclab/ or set ROBOCLAWS_ISAACLAB_PYTHON" >&2
      exit 1
    fi
    if [[ ! -f "$scene_usd_path" ]]; then
      echo "error: missing prepared scene USD: ${scene_usd_path}" >&2
      echo "       prepare or pass scene_usd_path=..." >&2
      exit 1
    fi

    stamp="$({{timestamp_cmd}})"
    run_dir="${output_dir}/${stamp}"
    OMNI_KIT_ACCEPT_EULA="${OMNI_KIT_ACCEPT_EULA:-YES}" \
      .venv/bin/python scripts/molmo_cleanup/run_molmospaces_scene_camera_comparison.py \
      --output-dir "$run_dir" \
      --scene-usd-path "$scene_usd_path" \
      --seed "$seed" \
      --generated-mess-count "$generated_mess_count" \
      --scene-source "$scene_source" \
      --scene-index "$scene_index" \
      --molmospaces-python "$molmospaces_python" \
      --isaac-python "$isaac_python" \
      --render-width "$render_width" \
      --render-height "$render_height" \
      --lighting-profile "$lighting_profile"
