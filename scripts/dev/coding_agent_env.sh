#!/usr/bin/env bash
# Shared provider helpers for OpenAI Agents SDK launchers.

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
  CUSTOM_RESPONSES_BASE_URL="${CUSTOM_RESPONSES_BASE_URL:-}" \
  CUSTOM_RESPONSES_API_KEY="${CUSTOM_RESPONSES_API_KEY:-}" \
  CUSTOM_RESPONSES_MODEL="${CUSTOM_RESPONSES_MODEL:-}" \
  MM_BASE_URL="${MM_BASE_URL:-}" \
  MM_API_KEY="${MM_API_KEY:-}" \
  KIMI_OPENAI_BASE_URL="${KIMI_OPENAI_BASE_URL:-}" \
  KIMI_API_KEY="${KIMI_API_KEY:-}" \
  $python_cmd -m roboclaws.agents.provider_registry "$@"
}

roboclaws_code_agent_provider() {
  local primary_var="$1"
  local default_provider="${2:-}"
  local provider=""
  if [[ -n "$primary_var" ]]; then
    provider="${!primary_var:-}"
  fi
  if [[ -z "$provider" ]]; then
    provider="${ROBOCLAWS_PROVIDER_PROFILE:-}"
  fi
  if [[ -z "$provider" ]]; then
    provider="$default_provider"
  fi
  if [[ -z "$provider" ]]; then
    echo "error: OpenAI Agents SDK requires explicit ROBOCLAWS_PROVIDER_PROFILE selection" >&2
    return 2
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
  roboclaws_provider_registry default-model "$provider"
}

roboclaws_code_agent_profile_base_url() {
  local provider="$1"
  roboclaws_provider_registry base-url "$provider"
}

roboclaws_code_agent_profile_key_env() {
  local provider="$1"
  roboclaws_provider_registry key-env "$provider"
}

roboclaws_code_agent_profile_wire_api() {
  local provider="$1"
  roboclaws_provider_registry wire-api "$provider"
}

roboclaws_code_agent_model_id() {
  local model="$1"
  local provider="${2:-}"
  local resolved
  if [[ -n "$provider" ]]; then
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
  local default_provider="${3:-}"
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
    elif [[ "$explicit_model" == "1" ]]; then
      model="$(roboclaws_code_agent_model_id "$model" "$provider")" || return
    fi
  fi
  printf '%s\n' "$model"
}

roboclaws_assert_openai_agents_provider_allowed() {
  local provider
  provider="$(roboclaws_code_agent_provider ROBOCLAWS_PROVIDER_PROFILE)" || return
  case "$provider" in
    custom-responses|minimax-responses|kimi-openai-chat)
      ;;
    *)
      echo "error: unsupported OpenAI Agents SDK provider '${provider}'; expected custom-responses, minimax-responses, or kimi-openai-chat" >&2
      return 2
      ;;
  esac
  echo "==> OpenAI Agents SDK provider gate ok (${provider})" >&2
}

roboclaws_code_agent_profile_summary() {
  local provider_var="$1"
  local model_var="$2"
  local default_provider="${3:-}"
  local provider model base_url key_env wire_api

  provider="$(roboclaws_code_agent_provider "$provider_var" "$default_provider")" || return
  model="$(roboclaws_code_agent_model "$model_var" "$provider_var" "$default_provider")" || return
  base_url="$(roboclaws_code_agent_profile_base_url "$provider")" || return
  key_env="$(roboclaws_code_agent_profile_key_env "$provider")" || return
  wire_api="$(roboclaws_code_agent_profile_wire_api "$provider")" || return
  printf '%s model=%s base_url=%s key_env=%s protocol=%s\n' \
    "$provider" "$model" "$base_url" "$key_env" "$wire_api"
}
