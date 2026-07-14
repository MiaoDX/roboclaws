#!/usr/bin/env bash
# Shared helpers for Codex / Claude Code demo launchers.
#
# Normal Codex runs use CODEX_BASE_URL / CODEX_API_KEY from the repo-local .env.
# The ROBOCLAWS_* provider/model variables handled in this file are explicit
# overrides for tests, CI, UI-selected routes, and one-off debugging.

roboclaws_load_dotenv() {
  local env_file="${1:-.env}"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

roboclaws_python() {
  if [[ -n "${ROBOCLAWS_PYTHON:-}" ]]; then
    if [[ ! -x "$ROBOCLAWS_PYTHON" ]]; then
      echo "error: ROBOCLAWS_PYTHON is not executable: $ROBOCLAWS_PYTHON" >&2
      return 2
    fi
    printf '%s\n' "$ROBOCLAWS_PYTHON"
  elif [[ -x ".venv/bin/python" ]]; then
    printf '%s\n' ".venv/bin/python"
  else
    echo "error: missing repo Python at .venv/bin/python; run 'uv sync --extra dev'" >&2
    return 2
  fi
}

roboclaws_provider_registry() {
  local python_cmd
  python_cmd="$(roboclaws_python)" || return
  # shellcheck disable=SC2086
  CODEX_BASE_URL="${CODEX_BASE_URL:-}" \
  CODEX_API_KEY="${CODEX_API_KEY:-}" \
  XM_LLM_BASE_URL="${XM_LLM_BASE_URL:-}" \
  XM_LLM_ANTHROPIC_BASE_URL="${XM_LLM_ANTHROPIC_BASE_URL:-}" \
  XM_LLM_API_KEY="${XM_LLM_API_KEY:-}" \
  MM_BASE_URL="${MM_BASE_URL:-}" \
  MM_API_KEY="${MM_API_KEY:-}" \
  MIMO_OPENAI_BASE_URL="${MIMO_OPENAI_BASE_URL:-}" \
  MIMO_ANTHROPIC_BASE_URL="${MIMO_ANTHROPIC_BASE_URL:-}" \
  MIMO_TP_KEY="${MIMO_TP_KEY:-}" \
  KIMI_OPENAI_BASE_URL="${KIMI_OPENAI_BASE_URL:-}" \
  KIMI_API_KEY="${KIMI_API_KEY:-}" \
  $python_cmd -m roboclaws.agents.provider_registry "$@"
}

roboclaws_code_agent_provider() {
  local primary_var="$1"
  local default_provider="${2:-codex-router-responses}"
  local provider=""
  if [[ -n "$primary_var" ]]; then
    provider="${!primary_var:-}"
  fi
  if [[ -z "$provider" ]]; then
    provider="${ROBOCLAWS_PROVIDER_PROFILE:-}"
  fi
  if [[ -z "$provider" ]]; then
    provider="$default_provider"
    if [[ "$provider" == "auto-claude" ]]; then
      if [[ -n "${MIMO_TP_KEY:-}" ]]; then
        provider="mimo-tp-anthropic"
      elif [[ -n "${XM_LLM_API_KEY:-}" ]]; then
        provider="mimo-mify-anthropic"
      else
        provider="system"
      fi
    fi
  fi
  if [[ "$provider" == "system" ]]; then
    printf '%s\n' "$provider"
    return 0
  fi
  local normalized
  if ! normalized="$(roboclaws_provider_registry public-profile "$provider" 2>/dev/null)"; then
    echo "error: unsupported provider profile '${provider}'; use a supported provider profile." >&2
    return 2
  fi
  printf '%s\n' "$normalized"
}

roboclaws_code_agent_profile_default_model() {
  local provider="$1"
  if [[ "$provider" == "system" ]]; then
    printf '\n'
    return 0
  fi
  roboclaws_provider_registry default-model "$provider"
}

roboclaws_code_agent_profile_base_url() {
  local provider="$1"
  if [[ "$provider" == "system" ]]; then
    printf '\n'
    return 0
  fi
  roboclaws_provider_registry base-url "$provider"
}

roboclaws_code_agent_profile_key_env() {
  local provider="$1"
  if [[ "$provider" == "system" ]]; then
    printf '\n'
    return 0
  fi
  roboclaws_provider_registry key-env "$provider"
}

roboclaws_code_agent_profile_wire_api() {
  local provider="$1"
  if [[ "$provider" == "system" ]]; then
    printf '\n'
    return 0
  fi
  roboclaws_provider_registry wire-api "$provider"
}

roboclaws_code_agent_model_id() {
  local model="$1"
  local provider="${2:-}"
  local resolved
  if [[ -n "$provider" && "$provider" != "system" ]]; then
    if ! resolved="$(roboclaws_provider_registry model-id "$model" 2>/dev/null)"; then
      echo "error: unknown coding-agent model '${model}'; add it to roboclaws.agents.provider_registry or use a catalog model" >&2
      return 2
    fi
    local detail
    if resolved="$(roboclaws_provider_registry provider-model-id "$provider" "$resolved" 2>&1)"; then
      printf '%s\n' "$resolved"
      return 0
    fi
    detail="$resolved"
    echo "error: coding-agent model '${model}' is incompatible with provider '${provider}'; use the provider default or a route-compatible catalog model" >&2
    if [[ -n "${detail:-}" ]]; then
      echo "$detail" >&2
    fi
    return 2
  fi
  if resolved="$(roboclaws_provider_registry model-id "$model" 2>/dev/null)"; then
    printf '%s\n' "$resolved"
    return 0
  fi
  echo "error: unknown coding-agent model '${model}'; add it to roboclaws.agents.provider_registry or use a catalog model" >&2
  return 2
}

roboclaws_code_agent_model() {
  local primary_var="$1"
  local provider_var="${2:-}"
  local default_provider="${3:-codex-router-responses}"
  local model="${!primary_var:-}"
  local explicit_model=0
  if [[ -z "$model" ]]; then
    model="${ROBOCLAWS_CODE_AGENT_MODEL:-}"
    if [[ -n "$model" ]]; then
      explicit_model=1
    fi
  else
    explicit_model=1
  fi
  if [[ -n "$provider_var" ]]; then
    local provider
    provider="$(roboclaws_code_agent_provider "$provider_var" "$default_provider")" || return
    if [[ -z "$model" ]]; then
      model="$(roboclaws_code_agent_profile_default_model "$provider")" || return
    elif [[ "$provider" != "system" && "$explicit_model" == "1" ]]; then
      model="$(roboclaws_code_agent_model_id "$model" "$provider")" || return
    fi
  fi
  printf '%s\n' "$model"
}

roboclaws_code_agent_model_args() {
  local -n out_args="$1"
  local primary_var="$2"
  local provider_var="${3:-}"
  local default_provider="${4:-codex-router-responses}"
  local model

  out_args=()
  model="$(roboclaws_code_agent_model "$primary_var" "$provider_var" "$default_provider")"
  if [[ -n "$model" ]]; then
    out_args=(--model "$model")
  fi
}

roboclaws_code_agent_prepare_mcp_env() {
  local model="${1:-}"
  local provider="${2:-}"

  if [[ -n "$model" ]]; then
    export MODEL="$model"
  fi

}

roboclaws_code_agent_require_key() {
  local provider="$1"
  local key_env="$2"
  if [[ -z "$key_env" ]]; then
    return 0
  fi
  if [[ -z "${!key_env:-}" ]]; then
    echo "error: ${provider} requires ${key_env}; add it to the repo-local .env or export it for this shell" >&2
    return 2
  fi
}

roboclaws_toml_string() {
  local value="${1//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

roboclaws_codex_provider_args() {
  local -n out_args="$1"
  local provider_var="${2:-ROBOCLAWS_PROVIDER_PROFILE}"
  local model_var="${3:-ROBOCLAWS_CODEX_MODEL}"
  local provider model base_url key_env wire_api

  out_args=()
  provider="$(roboclaws_code_agent_provider "$provider_var" "codex-router-responses")" || return
  case "$provider" in
    codex-router-responses|mimo-mify-responses|minimax-responses)
      ;;
    system)
      echo "error: Codex repo workflows default to codex-router-responses and require CODEX_BASE_URL and CODEX_API_KEY; set ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses explicitly to use XM_LLM_API_KEY or minimax-responses to use MM_API_KEY" >&2
      return 2
      ;;
    *)
      echo "error: unsupported Codex provider '${provider}'; expected codex-router-responses, mimo-mify-responses, or minimax-responses" >&2
      return 2
      ;;
  esac

  model="$(roboclaws_code_agent_model "$model_var" "$provider_var" "$provider")" || return
  base_url="$(roboclaws_code_agent_profile_base_url "$provider")" || return
  if [[ "$provider" == "codex-router-responses" && -z "$base_url" ]]; then
    echo "error: ${provider} requires CODEX_BASE_URL; add it to the repo-local .env or export it for this shell" >&2
    return 2
  fi
  key_env="$(roboclaws_code_agent_profile_key_env "$provider")" || return
  wire_api="$(roboclaws_code_agent_profile_wire_api "$provider")" || return
  roboclaws_code_agent_require_key "$provider" "$key_env" || return

  out_args=(
    -c "model=$(roboclaws_toml_string "$model")"
    -c "model_provider=$(roboclaws_toml_string "$provider")"
    -c "model_providers.${provider}.name=$(roboclaws_toml_string "$provider")"
    -c "model_providers.${provider}.base_url=$(roboclaws_toml_string "$base_url")"
    -c "model_providers.${provider}.env_key=$(roboclaws_toml_string "$key_env")"
    -c "model_providers.${provider}.wire_api=$(roboclaws_toml_string "$wire_api")"
  )
  if [[ "$provider" == "mimo-mify-responses" ]]; then
    out_args+=(-c "model_providers.${provider}.supports_parallel_tool_calls=false")
    out_args+=(-c 'web_search="disabled"')
  fi
  roboclaws_codex_transport_args out_args
}

roboclaws_codex_transport_args() {
  local -n _codex_transport_out_args="$1"
  local disable_value="${ROBOCLAWS_CODEX_DISABLE_RESPONSES_WEBSOCKETS:-0}"
  if [[ "${ROBOCLAWS_PROVIDER_TIMING_PROXY:-0}" =~ ^(1|true|yes|on)$ ]] && [[ -z "${ROBOCLAWS_CODEX_DISABLE_RESPONSES_WEBSOCKETS+x}" ]]; then
    disable_value="1"
  fi
  case "${disable_value}" in
    1|true|yes)
      _codex_transport_out_args+=(--disable responses_websockets)
      _codex_transport_out_args+=(--disable responses_websockets_v2)
      ;;
  esac
}

roboclaws_claude_provider_args() {
  local model_args_name="$1"
  local env_args_name="$2"
  local provider_var="${3:-ROBOCLAWS_PROVIDER_PROFILE}"
  local model_var="${4:-ROBOCLAWS_CLAUDE_MODEL}"
  local -n out_model_args="$model_args_name"
  local -n out_env_args="$env_args_name"
  local provider model base_url key_env

  out_model_args=()
  out_env_args=()
  provider="$(roboclaws_code_agent_provider "$provider_var" "auto-claude")" || return
  case "$provider" in
    system|mimo-mify-anthropic|mimo-tp-anthropic)
      ;;
    *)
      echo "error: unsupported Claude provider '${provider}'; expected system, mimo-mify-anthropic, or mimo-tp-anthropic" >&2
      return 2
      ;;
  esac

  model="$(roboclaws_code_agent_model "$model_var" "$provider_var" "$provider")" || return
  if [[ -n "$model" ]]; then
    out_model_args=(--model "$model")
  fi
  if [[ "$provider" == "system" ]]; then
    return 0
  fi

  base_url="$(roboclaws_code_agent_profile_base_url "$provider")" || return
  key_env="$(roboclaws_code_agent_profile_key_env "$provider")" || return
  roboclaws_code_agent_require_key "$provider" "$key_env" || return
  out_env_args=(
    "ANTHROPIC_API_KEY=${!key_env}"
    "ANTHROPIC_BASE_URL=${base_url}"
    "CLAUDE_CODE_SIMPLE=${CLAUDE_CODE_SIMPLE:-1}"
  )
}

roboclaws_assert_claude_code_network_allowed() {
  local label="${1:-Claude Code}"
  local provider
  provider="$(roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE "auto-claude")" || return
  case "$provider" in
    system|mimo-mify-anthropic|mimo-tp-anthropic)
      ;;
    *)
      echo "error: unsupported Claude provider '${provider}'; expected system, mimo-mify-anthropic, or mimo-tp-anthropic" >&2
      return 2
      ;;
  esac

  local rc
  if bash scripts/dev/network_status.sh --is-work-network >/dev/null 2>&1; then
    rc=0
  else
    rc=$?
  fi

  case "$rc" in
    0)
      if [[ "$provider" == "system" ]]; then
        echo "error: work network detected; ${label} is blocked while using system Claude Code provider." >&2
        echo "       Configure MIMO_TP_KEY or XM_LLM_API_KEY in the repo-local .env, or switch off the work network." >&2
        return 1
      fi
      echo "==> network guard ok: work network with repo-local Claude provider (${provider})" >&2
      ;;
    1)
      echo "==> network guard ok: off work network" >&2
      ;;
    *)
      echo "error: cannot determine network status; curl is required for ${label}." >&2
      return 2
      ;;
  esac
}

roboclaws_assert_codex_network_allowed() {
  local label="${1:-Codex}"
  local provider
  provider="$(roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE "codex-router-responses")" || return
  case "$provider" in
    codex-router-responses|mimo-mify-responses|minimax-responses)
      ;;
    *)
      echo "error: unsupported Codex provider '${provider}'; expected codex-router-responses, mimo-mify-responses, or minimax-responses" >&2
      return 2
      ;;
  esac

  local rc
  if bash scripts/dev/network_status.sh --is-work-network >/dev/null 2>&1; then
    rc=0
  else
    rc=$?
  fi

  case "$rc" in
    0)
      echo "==> network guard ok: work network with repo-local Codex provider (${provider})" >&2
      ;;
    1)
      echo "==> network guard ok: off work network" >&2
      ;;
    *)
      echo "error: cannot determine network status; curl is required for ${label}." >&2
      return 2
      ;;
  esac
}

roboclaws_assert_openai_agents_network_allowed() {
  local label="${1:-OpenAI Agents SDK}"
  local provider
  provider="$(roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE "codex-router-responses")" || return
  case "$provider" in
    codex-router-responses|mimo-mify-responses|minimax-responses|mimo-tp-openai-chat|mimo-inside-openai-chat|kimi-openai-chat)
      ;;
    *)
      echo "error: unsupported OpenAI Agents SDK provider '${provider}'; expected codex-router-responses, mimo-mify-responses, minimax-responses, mimo-tp-openai-chat, mimo-inside-openai-chat, or kimi-openai-chat" >&2
      return 2
      ;;
  esac

  local rc
  if bash scripts/dev/network_status.sh --is-work-network >/dev/null 2>&1; then
    rc=0
  else
    rc=$?
  fi

  case "$rc" in
    0)
      echo "==> network guard ok: work network with repo-local OpenAI Agents SDK provider (${provider})" >&2
      ;;
    1)
      echo "==> network guard ok: off work network" >&2
      ;;
    *)
      echo "error: cannot determine network status; curl is required for ${label}." >&2
      return 2
      ;;
  esac
}

roboclaws_code_agent_profile_summary() {
  local provider_var="$1"
  local model_var="$2"
  local default_provider="${3:-codex-router-responses}"
  local provider model base_url key_env wire_api

  provider="$(roboclaws_code_agent_provider "$provider_var" "$default_provider")" || return
  model="$(roboclaws_code_agent_model "$model_var" "$provider_var" "$default_provider")" || return
  if [[ "$provider" == "system" ]]; then
    if [[ -n "$model" ]]; then
      printf 'system model=%s\n' "$model"
    else
      printf 'system defaults\n'
    fi
    return 0
  fi

  base_url="$(roboclaws_code_agent_profile_base_url "$provider")" || return
  key_env="$(roboclaws_code_agent_profile_key_env "$provider")" || return
  wire_api="$(roboclaws_code_agent_profile_wire_api "$provider")" || return
  printf '%s model=%s base_url=%s key_env=%s protocol=%s\n' \
    "$provider" "$model" "$base_url" "$key_env" "$wire_api"
}
