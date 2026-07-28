# OpenClaw Gateway chat launcher for host-side Roboclaws MCP servers.

set working-directory := '..'

default:
    @just --list chat

run provider="mimo" model="" plugin="false" clean="false" reuse="false" keep_gateway="true" agents="1":
    #!/usr/bin/env bash
    set -euo pipefail

    bash scripts/dev/network_status.sh --assert-off-work "OpenClaw chat run"

    if [[ -z "${ROBOCLAWS_MCP_URL:-}" ]]; then
      echo "error: ROBOCLAWS_MCP_URL is required, for example http://host.docker.internal:18788/mcp" >&2
      exit 1
    fi
    if [[ -z "${SKILLS_DIR:-}" ]]; then
      export SKILLS_DIR="$PWD/skills/household-world"
    fi

    if [[ "{{clean}}" == "true" ]]; then
      docker volume rm openclaw-gateway-config >/dev/null 2>&1 || true
    fi

    if [[ "{{reuse}}" == "true" ]]; then
      token="${OPENCLAW_GATEWAY_TOKEN:-${OPENCLAW_TOKEN:-demo}}"
    else
      bootstrap_env=(PROVIDER="{{provider}}" AGENTS="{{agents}}" OPENCLAW_TOKEN="${OPENCLAW_TOKEN:-demo}")
      if [[ -n "{{model}}" ]]; then
        bootstrap_env+=(MODEL="{{model}}")
      fi
      if [[ "{{plugin}}" == "true" ]]; then
        bootstrap_env+=(KIMI_PROVIDER_MODE=plugin MIMO_PROVIDER_MODE=anthropic)
      fi
      token=$(env "${bootstrap_env[@]}" ./scripts/openclaw/openclaw-bootstrap.sh)
    fi

    echo "OpenClaw Gateway is ready."
    echo "Control UI : http://127.0.0.1:18789"
    echo "Token      : ${token:-${OPENCLAW_TOKEN:-demo}}"
    echo "MCP URL    : ${ROBOCLAWS_MCP_URL}"
    echo "Skill dir  : ${SKILLS_DIR}"
    echo "Agent      : agent-0"
    echo "Use the Control UI chat tab to drive the connected Roboclaws MCP server."
    if [[ "{{keep_gateway}}" != "true" ]]; then
      echo "Press Ctrl-C to stop the Gateway."
      trap 'docker rm -f openclaw-gateway >/dev/null 2>&1 || true' EXIT INT TERM
      while docker ps --format '{{{{.Names}}}}' | grep -qx openclaw-gateway; do
        sleep 2
      done
    fi
