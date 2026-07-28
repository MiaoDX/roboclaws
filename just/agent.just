# Agent-maintainer dispatchers.
#
# This namespace is intentionally compact. It exposes a small set of axes and
# delegates to private implementation modules.

set working-directory := '..'
set positional-arguments

[private]
default:
    @just --list agent

# Run a normalized private dispatch target / agent-engine tuple.
run dispatch_target agent_engine mode="" *overrides:
    #!/usr/bin/env bash
    set -euo pipefail

    args=("$@")
    dispatch_target="${args[0]}"
    agent_engine="${args[1]}"
    mode="${args[2]}"
    raw_overrides=("${args[@]:3}")

    dispatch_target="${dispatch_target#dispatch_target=}"
    dispatch_target="${dispatch_target#task=}"
    agent_engine="${agent_engine#agent_engine=}"
    agent_engine="${agent_engine#driver=}"

    has_raw_override_key() {
      local wanted="$1"
      local override
      for override in "${raw_overrides[@]}"; do
        if [[ "$override" == "$wanted="* || "$override" == "--$wanted="* ]]; then
          return 0
        fi
      done
      return 1
    }

    dispatch_surface="${dispatch_target%%.*}"
    dispatch_intent="${dispatch_target##*.}"
    case "$dispatch_target" in
      household-world.cleanup)
        dispatch_surface="household-world"
        dispatch_intent="cleanup"
        ;;
      household-world.map-build)
        dispatch_surface="household-world"
        dispatch_intent="map-build"
        ;;
      household-world.open-ended)
        dispatch_surface="household-world"
        dispatch_intent="open-ended"
        if ! has_raw_override_key task_intent; then
          raw_overrides+=("task_intent=open-ended")
        fi
        ;;
      planner-proof.planner-proof)
        dispatch_surface="planner-proof"
        dispatch_intent="planner-proof"
        ;;
      *)
        dispatch_surface="$dispatch_target"
        dispatch_intent="$dispatch_target"
        ;;
    esac
    household_run_path="${dispatch_surface}/${dispatch_intent}"
    household_run_token="${dispatch_surface}.${dispatch_intent}"

    case "$agent_engine" in
      codex-cli)
        echo "error: unsupported agent_engine 'codex-cli'; expected direct-runner|openai-agents-sdk" >&2
        exit 1
        ;;
      claude-code)
        echo "error: unsupported agent_engine 'claude-code'; expected direct-runner|openai-agents-sdk" >&2
        exit 1
        ;;
      openai-agents-sdk)
        driver="openai-agents-live"
        ;;
      direct-runner)
        driver="direct"
        if [[ "$mode" == "smoke" && ( "$dispatch_intent" == "cleanup" || "$dispatch_intent" == "open-ended" ) ]]; then
          driver="mcp-smoke"
        fi
        ;;
      openclaw-gateway)
        driver="openclaw"
        ;;
      *)
        driver="$agent_engine"
        ;;
    esac
    case "$mode" in
      report=*)
        mode="${mode#report=}"
        ;;
      profile=*)
        mode="${mode#profile=}"
        ;;
      evidence_lane=*)
        mode="${mode#evidence_lane=}"
        ;;
      *=*)
        raw_overrides=("$mode" "${raw_overrides[@]}")
        mode=""
        ;;
    esac

    run_just() {
      if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
        printf 'just'
        for arg in "$@"; do
          printf '\t%s' "$arg"
        done
        printf '\n'
        exit 0
      fi
      exec just "$@"
    }

    run_cmd() {
      if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
        printf 'cmd'
        for arg in "$@"; do
          printf '\t%s' "$arg"
        done
        printf '\n'
        exit 0
      fi
      exec "$@"
    }

    declare -A kv=()
    for override in "${raw_overrides[@]}"; do
      [[ -z "$override" ]] && continue
      if [[ "$override" != *=* ]]; then
        echo "error: override '$override' is not key=value" >&2
        exit 1
      fi
      key="${override%%=*}"
      value="${override#*=}"
      key="${key#--}"
      key="${key//-/_}"
      case "$key" in
        agibot_map_artifact_dir|backend|baseline|candidate|cap|context_json|\
        generated_mess_count|\
        cleanup_object_count|\
        cleanup_routine|record_robot_views|robot_views|\
        host|max_wall_seconds|min_generated_mess_count|\
        b1_alignment_artifact|b1_navigation_artifact|map_bundle|mode|model|output_dir|policy|port|prompt|provider|provider_profile|\
        regrade_source|\
        camera_labeler|evidence_lane|profile|real_movement_enabled|rehearsal_mode|robot_name|run_dir|runner_python|runner_script|\
        runtime|runtime_map_prior|molmospaces_python|generated_mess_object_ids|generated_mess_manifest_path|\
        operator_messages_path|operator_resume_requests_path|operator_session_context_json|skill_name|task_intent|task_preset|task_surface|goal_contract_json|goal_contract_path|\
        scene_index|scene_source|seed|seeds|map_build|task|timeout_s|world|\
        isaac_scene_usd_path|\
        visual_grounding|visual_grounding_timeout|visual_grounding_timeout_s|wall_budget|waypoint_id)
          ;;
        *)
          echo "error: unsupported override key '$key'" >&2
          exit 1
          ;;
      esac
      kv["$key"]="$value"
    done

    get() {
      local key="$1"
      local default="$2"
      if [[ -v "kv[$key]" && -n "${kv[$key]}" ]]; then
        printf '%s\n' "${kv[$key]}"
      else
        printf '%s\n' "$default"
      fi
    }

    map_build_prompt() {
      local default_prompt="帮我建立这个房间的 Runtime Metric Map"
      if [[ -v "kv[prompt]" && -n "${kv[prompt]}" ]]; then
        printf '%s\n' "${kv[prompt]}"
      elif [[ -v "kv[task]" && -n "${kv[task]}" ]]; then
        printf '%s\n' "${kv[task]}"
      else
        printf '%s\n' "$default_prompt"
      fi
    }

    cleanup_prompt() {
      local default_prompt="帮我收拾这个房间"
      if [[ -v "kv[prompt]" && -n "${kv[prompt]}" ]]; then
        printf '%s\n' "${kv[prompt]}"
      elif [[ -v "kv[task]" && -n "${kv[task]}" ]]; then
        printf '%s\n' "${kv[task]}"
      else
        printf '%s\n' "$default_prompt"
      fi
    }

    shell_join() {
      local first=1
      local quoted
      for arg in "$@"; do
        printf -v quoted '%q' "$arg"
        if [[ "$first" == "1" ]]; then
          printf '%s' "$quoted"
          first=0
        else
          printf ' %s' "$quoted"
        fi
      done
    }

    if [[ "$dispatch_surface" == "household-world" ]]; then
      profile="${mode:-$(get profile "$(get evidence_lane world-public-labels)")}"
      case "$profile" in
        smoke|world-public-labels|camera-raw-fpv|camera-grounded-labels)
          ;;
        *)
          echo "error: unsupported household-world evidence_lane '$profile' (expected smoke|world-public-labels|camera-grounded-labels|camera-raw-fpv)" >&2
          exit 1
          ;;
      esac
    else
      report="${mode:-visual}"
      case "$report" in
        visual|minimal)
          ;;
        *)
          echo "error: unsupported report '$report' (expected visual|minimal)" >&2
          exit 1
          ;;
      esac
    fi

    report_rerun_parts=("just" "run::surface")
    case "$dispatch_surface.$dispatch_intent" in
      household-world.map-build)
        report_rerun_parts+=("surface=household-world" "preset=map-build")
        ;;
      household-world.cleanup|household-world.open-ended)
        if [[ "${kv[task_preset]:-}" == "cleanup" ]]; then
          report_rerun_parts+=("surface=household-world" "preset=cleanup")
        elif [[ "${kv[task_intent]:-cleanup}" == "open-ended" ]]; then
          report_rerun_parts+=("surface=household-world")
        else
          report_rerun_parts+=("surface=household-world" "preset=${kv[task_intent]:-cleanup}")
        fi
        ;;
      planner-proof.planner-proof)
        report_rerun_parts+=("surface=planner-proof" "intent=planner-proof")
        ;;
    esac
    case "$driver" in
      openai-agents-live)
        report_rerun_parts+=("agent_engine=openai-agents-sdk")
        ;;
      direct)
        report_rerun_parts+=("agent_engine=direct-runner")
        ;;
      mcp-smoke)
        report_rerun_parts+=("agent_engine=direct-runner")
        ;;
      openclaw)
        report_rerun_parts+=("agent_engine=openclaw-gateway")
        ;;
    esac
    if [[ "$dispatch_surface" == "household-world" ]]; then
      if [[ "$profile" == "smoke" ]]; then
        report_rerun_parts+=("run_preset=smoke" "evidence_lane=world-public-labels")
      else
        report_rerun_parts+=("evidence_lane=$profile")
      fi
    else
      report_rerun_parts+=("$report")
    fi
    for override in "${raw_overrides[@]}"; do
      [[ -n "$override" ]] && report_rerun_parts+=("$override")
    done
    export ROBOCLAWS_REPORT_RERUN_COMMAND="$(shell_join "${report_rerun_parts[@]}")"

    case "$dispatch_surface.$dispatch_intent:$driver" in
      household-world.map-build:direct|household-world.map-build:openai-agents-live|\
      household-world.cleanup:direct|household-world.cleanup:mcp-smoke|household-world.cleanup:openclaw-smoke|\
      household-world.cleanup:openai-agents-live|household-world.cleanup:openclaw|\
      household-world.open-ended:direct|household-world.open-ended:mcp-smoke|household-world.open-ended:openclaw-smoke|\
      household-world.open-ended:openai-agents-live|household-world.open-ended:openclaw)
        case "$driver" in
          direct|mcp-smoke|openclaw-smoke)
            impl_driver="$driver"
            ;;
          openai-agents-live)
            impl_driver="openai-agents-live"
            ;;
          openclaw)
            impl_driver="openclaw-live"
            ;;
        esac
        if [[ "$dispatch_intent" == "map-build" && "$driver" != "direct" && "$driver" != "openai-agents-live" ]]; then
          echo "error: household-world.map-build currently supports direct-runner or openai-agents-sdk only" >&2
          exit 1
        fi

        case "$profile" in
          smoke)
            default_output_dir="output/household/${household_run_path}/${driver}-smoke"
            ;;
          *)
            default_output_dir="output/household/${household_run_path}/${driver}-${profile}"
            ;;
        esac
        default_seeds="7"
        seeds="$(get seeds "$(get seed "$default_seeds")")"
        output_dir="$(get output_dir "$default_output_dir")"
        if [[ "$dispatch_intent" == "map-build" ]]; then
          prompt="$(map_build_prompt)"
        else
          prompt="$(cleanup_prompt)"
        fi
        skill_name="$(get skill_name "${ROBOCLAWS_TASK_SKILL:-}")"
        resolved_task_intent="$(get task_intent "${ROBOCLAWS_TASK_INTENT:-}")"
        if [[ -z "$resolved_task_intent" ]]; then
          if [[ "$dispatch_intent" == "map-build" ]]; then
            resolved_task_intent="map-build"
          else
            resolved_task_intent="cleanup"
          fi
        fi
        if [[ -z "$skill_name" ]]; then
          if [[ "$dispatch_intent" == "map-build" || "$resolved_task_intent" == "open-ended" ]]; then
            skill_name="household-open-task"
          else
            skill_name="molmo-realworld-cleanup"
          fi
        fi
        goal_contract_json="$(get goal_contract_json "${ROBOCLAWS_GOAL_CONTRACT_JSON:-}")"
        goal_contract_path="$(get goal_contract_path "${ROBOCLAWS_GOAL_CONTRACT_PATH:-}")"
        operator_session_context_json="$(get operator_session_context_json "${ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON:-}")"
        goal_contract_args=()
        if [[ -n "$goal_contract_json" ]]; then
          goal_contract_args+=(--goal-contract-json "$goal_contract_json")
        fi
        if [[ -n "$goal_contract_path" ]]; then
          goal_contract_args+=(--goal-contract "$goal_contract_path")
        fi
        generated_mess_count="$(get generated_mess_count 10)"
        generated_mess_manifest_path="$(get generated_mess_manifest_path "")"
        host="$(get host 127.0.0.1)"
        port="$(get port "${ROBOCLAWS_EVAL_HARNESS_MCP_PORT:-18788}")"
        map_bundle="$(get map_bundle auto)"
        b1_alignment_artifact="$(get b1_alignment_artifact "")"
        b1_navigation_artifact="$(get b1_navigation_artifact "")"
        cleanup_routine="$(get cleanup_routine skill)"
        case "$cleanup_routine" in
          auto|skill)
            ;;
          *)
            echo "error: unsupported cleanup_routine '$cleanup_routine' (expected auto|skill)" >&2
            exit 1
            ;;
        esac
        robot_views="$(get robot_views "$(get record_robot_views auto)")"
        camera_labeler="$(get camera_labeler "")"
        visual_grounding="$(get visual_grounding "")"
        if [[ -n "$visual_grounding" ]]; then
          echo "error: visual_grounding is no longer a public task axis; use camera_labeler=<labeler> with evidence_lane=camera-grounded-labels" >&2
          exit 1
        fi
        case "$profile" in
          camera-grounded-labels)
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
            ;;
          *)
            if [[ -n "$camera_labeler" ]]; then
              echo "error: camera_labeler is only valid for evidence_lane=camera-grounded-labels" >&2
              exit 1
            fi
            visual_grounding="sim"
            ;;
        esac
        visual_grounding_timeout_s="$(get visual_grounding_timeout_s "$(get visual_grounding_timeout auto)")"
        map_build="$(get map_build off)"
        if [[ "$dispatch_intent" == "map-build" ]]; then
          map_build="on"
        fi
        runtime_map_prior="$(get runtime_map_prior "")"
        operator_messages_path="$(get operator_messages_path "")"
        backend="$(get backend auto)"
        min_generated_mess_count="$(get min_generated_mess_count auto)"
        generated_mess_object_ids="$(get generated_mess_object_ids "")"
        world_id="$(get world "")"
        scene_source="$(get scene_source procthor-10k-val)"
        scene_index="$(get scene_index 0)"
        isaac_scene_usd_path="$(get isaac_scene_usd_path "")"
        if [[ "$dispatch_intent" == "map-build" ]]; then
          case "$backend" in
            auto|molmospaces_subprocess|isaaclab_subprocess|agibot_gdk)
              ;;
            agibot_molmospaces_sim)
              if [[ "$driver" != "direct" ]]; then
                echo "error: backend=agibot_molmospaces_sim currently supports direct driver only" >&2
                exit 1
              fi
              ;;
            *)
              echo "error: household-world.map-build ${agent_engine} unsupported backend '$backend' (expected auto|molmospaces_subprocess|isaaclab_subprocess|agibot_gdk)" >&2
              exit 1
              ;;
          esac
        fi
        if [[ "$backend" == "agibot_molmospaces_sim" && ! -v "kv[seeds]" && ! -v "kv[seed]" ]]; then
          seeds="7"
        fi
        if [[ "$backend" == "isaaclab_subprocess" && "$world_id" != "b1-map12" ]]; then
          echo "error: backend=isaaclab_subprocess is scoped to world=b1-map12; MolmoSpaces household routes use backend=molmospaces_subprocess" >&2
          exit 1
        fi
        if [[ "$backend" == "agibot_molmospaces_sim" ]]; then
          if [[ "$driver" != "direct" ]]; then
            echo "error: backend=agibot_molmospaces_sim currently supports direct driver only" >&2
            exit 1
          fi
          default_rehearsal_mode="contract"
          if [[ "$dispatch_intent" == "cleanup" || "$dispatch_intent" == "open-ended" ]]; then
            default_rehearsal_mode="cleanup-actions"
          fi
          rehearsal_mode="$(get rehearsal_mode "$default_rehearsal_mode")"
          case "$rehearsal_mode" in
            contract|cleanup-actions)
              ;;
            *)
              echo "error: unsupported rehearsal_mode '$rehearsal_mode' (expected contract|cleanup-actions)" >&2
              exit 1
              ;;
          esac
          runtime="$(get runtime fixture)"
          case "$runtime" in
            fixture|molmospaces-subprocess)
              ;;
            *)
              echo "error: unsupported runtime '$runtime' (expected fixture|molmospaces-subprocess)" >&2
              exit 1
              ;;
          esac
          seed_count="$(wc -w <<<"$seeds" | tr -d ' ')"
          if [[ "$seed_count" != "1" ]]; then
            echo "error: backend=agibot_molmospaces_sim accepts exactly one seed per run" >&2
            exit 1
          fi
          cleanup_object_count="$(get cleanup_object_count 2)"
          sim_args=(.venv/bin/python scripts/molmo_cleanup/run_molmospaces_agibot_contract_rehearsal.py
            --output-dir "$output_dir"
            --seed "$seeds"
            --generated-mess-count "$generated_mess_count"
            --runtime "$runtime"
            --flow prehardware
            --intent "$resolved_task_intent"
            --profile "$profile"
            --task-prompt "$prompt"
            --rehearsal-mode "$rehearsal_mode"
            --cleanup-object-count "$cleanup_object_count")
          if [[ "$profile" == "camera-grounded-labels" ]]; then
            sim_args+=(--camera-labeler "$camera_labeler")
            if [[ "$visual_grounding_timeout_s" != "auto" && -n "$visual_grounding_timeout_s" ]]; then
              sim_args+=(--visual-grounding-timeout-s "$visual_grounding_timeout_s")
            fi
          fi
          molmospaces_python="$(get molmospaces_python "")"
          if [[ -n "$molmospaces_python" ]]; then
            sim_args+=(--molmospaces-python "$molmospaces_python")
          fi
          robot_name="$(get robot_name "")"
          if [[ -n "$robot_name" ]]; then
            sim_args+=(--robot-name "$robot_name")
          fi
          waypoint_id="$(get waypoint_id "")"
          if [[ -n "$waypoint_id" ]]; then
            sim_args+=(--waypoint-id "$waypoint_id")
          fi
          run_dir="$(get run_dir "")"
          if [[ -n "$run_dir" ]]; then
            sim_args+=(--run-dir "$run_dir")
          fi
          context_json="$(get context_json "")"
          if [[ -n "$context_json" ]]; then
            sim_args+=(--context-json "$context_json")
          fi
          agibot_map_artifact_dir="$(get agibot_map_artifact_dir "")"
          if [[ -n "$agibot_map_artifact_dir" ]]; then
            sim_args+=(--agibot-map-artifact-dir "$agibot_map_artifact_dir")
          fi
          case "$robot_views" in
            on|true|1|yes)
              sim_args+=(--include-robot --record-robot-views)
              ;;
            auto|"")
              if [[ "$runtime" == "molmospaces-subprocess" ]]; then
                sim_args+=(--include-robot --record-robot-views)
              fi
              ;;
            off|false|0|no)
              ;;
            *)
              echo "error: unsupported robot_views '$robot_views' (expected auto|on|off)" >&2
              exit 1
              ;;
          esac
          run_cmd "${sim_args[@]}"
        fi
        if [[ "$backend" == "agibot_gdk" ]]; then
          context_json="$(get context_json "")"
          if [[ "$dispatch_intent" == "map-build" && "$driver" == "openai-agents-live" ]]; then
            if [[ -z "$context_json" ]]; then
              echo "error: backend=agibot_gdk household-world.map-build ${agent_engine} requires context_json=<agibot map context JSON>" >&2
              exit 1
            fi
            seed_count="$(wc -w <<<"$seeds" | tr -d ' ')"
            if [[ "$seed_count" != "1" ]]; then
              echo "error: Agibot household-world.map-build ${agent_engine} accepts exactly one seed per live run" >&2
              exit 1
            fi
            seed="$seeds"
            stamp="$(TZ=Asia/Shanghai date +%m%d_%H%M)"
            run_dir="$(get run_dir "")"
            if [[ -z "$run_dir" ]]; then
              run_dir="${output_dir}/${stamp}/seed-${seed}"
            fi
            policy="$(get policy openai_agents_agibot_map_build)"
            server_startup_timeout_s="${ROBOCLAWS_AGIBOT_MAP_BUILD_LIVE_SERVER_STARTUP_TIMEOUT_S:-600}"
            client_url="http://${host}:${port}/mcp"

            server_host="$host"
            server_args=(
              --host "$server_host"
              --port "$port"
              --output-dir "$run_dir"
              --context-json "$context_json"
              --policy "$policy"
              --task "$prompt"
              --evidence-lane "$profile"
            )
            if [[ "$profile" == "camera-grounded-labels" ]]; then
              server_args+=(--camera-labeler "$camera_labeler")
            fi
            if [[ "$visual_grounding_timeout_s" != "auto" && -n "$visual_grounding_timeout_s" ]]; then
              server_args+=(--visual-grounding-timeout-s "$visual_grounding_timeout_s")
            fi
            runner_python="$(get runner_python "")"
            if [[ -n "$runner_python" ]]; then
              server_args+=(--runner-python "$runner_python")
            fi
            runner_script="$(get runner_script "")"
            if [[ -n "$runner_script" ]]; then
              server_args+=(--runner-script "$runner_script")
            fi
            agibot_map_artifact_dir="$(get agibot_map_artifact_dir "")"
            if [[ -n "$agibot_map_artifact_dir" ]]; then
              server_args+=(--agibot-map-artifact-dir "$agibot_map_artifact_dir")
            fi
            real_movement_enabled="$(get real_movement_enabled false)"
            case "$real_movement_enabled" in
              true|1|yes|on)
                server_args+=(--real-movement-enabled)
                ;;
              false|0|no|off|"")
                ;;
              *)
                echo "error: unsupported real_movement_enabled '$real_movement_enabled' (expected true|false)" >&2
                exit 1
                ;;
            esac

            if [[ "$driver" == "openai-agents-live" ]]; then
              provider_profile="$(get provider_profile "${ROBOCLAWS_PROVIDER_PROFILE:-codex-router-responses}")"
              model="$(get model "${ROBOCLAWS_OPENAI_AGENTS_MODEL:-${ROBOCLAWS_CODEX_MODEL:-}}")"
              runner_args=(
                .venv/bin/python
                scripts/molmo_cleanup/run_live_openai_agents_agibot_map_build.py
                --repo-root "$PWD"
                --run-dir "$run_dir"
                --status-path "${run_dir}/live_status.json"
                --client-url "$client_url"
                --host "$host"
                --port "$port"
                --provider-profile "$provider_profile"
                --model "$model"
                --server-startup-timeout-s "$server_startup_timeout_s"
                --kickoff-prompt "$prompt"
                --backend "$backend"
                --policy "$policy"
                --task "$resolved_task_intent"
              )
              for arg in "${server_args[@]}"; do
                runner_args+=("--server-arg=$arg")
              done
              run_cmd "${runner_args[@]}"
            fi

          fi
          agibot_args=(.venv/bin/python scripts/molmo_cleanup/run_physical_agibot_cleanup_pilot.py
            --output-dir "$output_dir")
          if [[ -n "$context_json" ]]; then
            agibot_args+=(--context-json "$context_json")
          fi
          waypoint_id="$(get waypoint_id "")"
          if [[ -n "$waypoint_id" ]]; then
            agibot_args+=(--waypoint-id "$waypoint_id")
          fi
          run_dir="$(get run_dir "")"
          if [[ -n "$run_dir" ]]; then
            agibot_args+=(--run-dir "$run_dir")
          fi
          runner_python="$(get runner_python "")"
          if [[ -n "$runner_python" ]]; then
            agibot_args+=(--runner-python "$runner_python")
          fi
          runner_script="$(get runner_script "")"
          if [[ -n "$runner_script" ]]; then
            agibot_args+=(--runner-script "$runner_script")
          fi
          agibot_map_artifact_dir="$(get agibot_map_artifact_dir "")"
          if [[ -n "$agibot_map_artifact_dir" ]]; then
            agibot_args+=(--agibot-map-artifact-dir "$agibot_map_artifact_dir")
          fi
          real_movement_enabled="$(get real_movement_enabled false)"
          case "$real_movement_enabled" in
            true|1|yes|on)
              agibot_args+=(--real-movement-enabled)
              ;;
            false|0|no|off|"")
              ;;
            *)
              echo "error: unsupported real_movement_enabled '$real_movement_enabled' (expected true|false)" >&2
              exit 1
              ;;
          esac
          run_cmd "${agibot_args[@]}"
        fi
        molmo_args=(
          "$impl_driver" "$profile" "$seeds"
          "$output_dir" "$prompt" "$generated_mess_count" "$host" "$port"
          "$map_bundle" "$cleanup_routine" "$robot_views" "$camera_labeler"
          "$visual_grounding_timeout_s" "$map_build" "$runtime_map_prior" "$backend"
          "$scene_source" "$scene_index" "$isaac_scene_usd_path"
          "$min_generated_mess_count" "$generated_mess_object_ids" "$dispatch_surface"
          "$resolved_task_intent" "$operator_messages_path" "$b1_alignment_artifact"
          "$b1_navigation_artifact"
        )
        operator_resume_requests_path="$(get operator_resume_requests_path "")"
        if [[ -n "$operator_resume_requests_path" ]]; then
          export ROBOCLAWS_OPERATOR_RESUME_REQUESTS_PATH="$operator_resume_requests_path"
        fi
        run_dir_override="$(get run_dir "")"
        if [[ -n "$run_dir_override" ]]; then
          molmo_args+=("" "" "" "$run_dir_override")
        fi
        ROBOCLAWS_GOAL_CONTRACT_JSON="$goal_contract_json" \
          ROBOCLAWS_GOAL_CONTRACT_PATH="$goal_contract_path" \
          ROBOCLAWS_OPERATOR_SESSION_CONTEXT_JSON="$operator_session_context_json" \
          ROBOCLAWS_LAUNCH_WORLD_ID="$world_id" \
          ROBOCLAWS_MOLMO_RUN_DIR_OVERRIDE="$run_dir_override" \
          ROBOCLAWS_TASK_INTENT="$resolved_task_intent" \
          ROBOCLAWS_TASK_PRESET="${kv[task_preset]:-}" \
          ROBOCLAWS_TASK_SKILL="$skill_name" \
          ROBOCLAWS_GENERATED_MESS_MANIFEST_PATH="$generated_mess_manifest_path" \
          run_just molmo::household-world-impl "${molmo_args[@]}"
        ;;

      planner-proof.planner-proof:direct|planner-proof.planner-proof:mcp-smoke)
        mode="$(get mode dry-run)"
        mode="${mode//_/-}"
        output_dir="$(get output_dir "")"
        seed="$(get seed 7)"
        prompt="$(cleanup_prompt)"
        generated_mess_count="$(get generated_mess_count 10)"
        case "$mode" in
          dry-run|dry)
            if [[ -n "$output_dir" ]]; then
              run_just harness::molmo-planner-proof-bundle-runner \
                "$output_dir" "$seed" "$prompt" "$generated_mess_count"
            fi
            run_just harness::molmo-planner-proof-bundle-runner
            ;;
          execute-rerun|execute|local)
            min_generated_mess_count="$(get min_generated_mess_count 5)"
            steps="$(get steps 2)"
            timeout_s="$(get timeout_s 600)"
            if [[ -z "$output_dir" ]]; then
              output_dir="output/molmo-planner-proof-bundle-execute-rerun"
            fi
            run_just harness::molmo-planner-proof-bundle-execute-rerun \
              "$output_dir" "$seed" "$prompt" "$generated_mess_count" \
              "$min_generated_mess_count" "$steps" "$timeout_s"
            ;;
          *)
            echo "error: unsupported molmo-planner-proof mode '$mode' (expected dry-run|execute-rerun)" >&2
            exit 1
            ;;
        esac
        ;;

      *)
        echo "error: unsupported surface/intent/driver route '$dispatch_surface.$dispatch_intent:$driver'" >&2
        exit 1
        ;;
    esac

# Dispatch to a private verification gate.
verify target="mock" *args:
    #!/usr/bin/env bash
    set -euo pipefail

    args=("$@")
    target="${args[0]}"
    target="${target#target=}"
    rest=("${args[@]:1}")

    trace_or_exec() {
      if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
        printf 'just'
        for arg in "$@"; do printf '\t%s' "$arg"; done
        printf '\n'
        exit 0
      fi
      exec just "$@"
    }

    case "$target" in
      static|mock|ci-required|contract|\
      molmo-realworld-cleanup|molmo-realworld-agent-mcp|molmo-realworld-agent-dogfood-kit|\
      molmo-realworld-openclaw-dogfood-kit|\
      molmo-realworld-openclaw-visual-dogfood-kit|molmo-realworld-raw-fpv|\
      molmo-planner-proof-bundle-runner|molmo-planner-proof-bundle-execute-rerun|\
      molmo-planner-manipulation-probe|full-local)
        trace_or_exec verify::"$target" "${rest[@]}"
        ;;
      *)
        echo "error: unsupported verify target '$target'" >&2
        exit 1
        ;;
    esac

# Dispatch to a private harness recipe.
harness target *args:
    #!/usr/bin/env bash
    set -euo pipefail

    args=("$@")
    target="${args[0]}"
    target="${target#target=}"
    rest=("${args[@]:1}")

    trace_or_exec() {
      if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
        printf 'just'
        for arg in "$@"; do printf '\t%s' "$arg"; done
        printf '\n'
        exit 0
      fi
      exec just "$@"
    }

    case "$target" in
      molmo-realworld-cleanup|\
      molmo-realworld-agent-mcp|molmo-realworld-agent-dogfood-kit|\
      molmo-realworld-openclaw-dogfood-kit|\
      molmo-realworld-openclaw-visual-dogfood-kit|molmo-realworld-raw-fpv|\
      molmo-planner-proof-bundle-runner|molmo-planner-proof-bundle-execute-rerun|\
      molmo-planner-manipulation-probe|molmo-visual-grounding-benchmark|\
      isaac-runtime-preflight|isaac-runtime-smoke|\
      b1-map12-navigation-smoke)
        trace_or_exec harness::"$target" "${rest[@]}"
        ;;
      *)
        echo "error: unsupported harness target '$target'" >&2
        exit 1
        ;;
    esac

# Manage a household MCP server.
mcp action="up" server="household-world.cleanup" host="127.0.0.1" port="18788" output_dir=".tmp/roboclaws-mcp/run":
    #!/usr/bin/env bash
    set -euo pipefail

    action="$1"
    action="${action#action=}"

    trace_or_exec() {
      if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
        printf 'just'
        for arg in "$@"; do printf '\t%s' "$arg"; done
        printf '\n'
        exit 0
      fi
      exec just "$@"
    }

    case "$action" in
      up)
        server="$2"
        case "$server" in
          household-world.cleanup|cleanup)
            server="household-world.cleanup"
            ;;
          household-world.map-build|map-build)
            server="household-world.map-build"
            ;;
          *)
            echo "error: unsupported MCP dispatch target '$server' (expected household-world.cleanup|household-world.map-build)" >&2
            exit 1
            ;;
        esac
        trace_or_exec mcp::up "$server" "$3" "$4" "$5"
        ;;
      down)
        trace_or_exec mcp::down
        ;;
      *)
        echo "error: unsupported mcp action '$action' (expected up|down)" >&2
        exit 1
        ;;
    esac

# Manage the OpenClaw Gateway lifecycle.
gateway action="up" token_file=".openclaw-token" provider="kimi" agents="2":
    #!/usr/bin/env bash
    set -euo pipefail

    action="$1"
    action="${action#action=}"

    trace_or_exec() {
      if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
        printf 'just'
        for arg in "$@"; do printf '\t%s' "$arg"; done
        printf '\n'
        exit 0
      fi
      exec just "$@"
    }

    case "$action" in
      up|down)
        trace_or_exec openclaw::gateway "$action" "$2" "$3" "$4"
        ;;
      pull-image|pull)
        trace_or_exec openclaw::pull-image
        ;;
      *)
        echo "error: unsupported gateway action '$action' (expected up|down|pull-image)" >&2
        exit 1
        ;;
    esac

# Run a repo-native eval suite.
eval *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    python_bin="${ROBOCLAWS_DEVTOOLS_PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
      if [[ -x .venv/bin/python ]]; then
        python_bin=".venv/bin/python"
      elif command -v python3 >/dev/null 2>&1; then
        python_bin="python3"
      else
        python_bin="python"
      fi
    fi
    if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
      printf 'cmd\t%s\t-m\troboclaws.cli.main\teval' "$python_bin"
      for arg in "$@"; do
        printf '\t%s' "$arg"
      done
      printf '\n'
      exit 0
    fi
    exec "$python_bin" -m roboclaws.cli.main eval "$@"
