#!/usr/bin/env bash
# Detect whether this machine is on the office work network.
#
# The office network is identified by reachability of an operator-configured
# probe URL. Any HTTP response means the endpoint is reachable; connection
# failure means this is not the work network.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dotenv_path="${ROBOCLAWS_DOTENV_PATH:-$repo_root/.env}"

load_repo_dotenv() {
  [[ -f "$dotenv_path" ]] || return 0

  local probe_url_was_set=0
  local connect_timeout_was_set=0
  local max_time_was_set=0
  local probe_url_override=""
  local connect_timeout_override=""
  local max_time_override=""
  if [[ -v ROBOCLAWS_WORK_NETWORK_PROBE_URL ]]; then
    probe_url_was_set=1
    probe_url_override="$ROBOCLAWS_WORK_NETWORK_PROBE_URL"
  fi
  if [[ -v ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT ]]; then
    connect_timeout_was_set=1
    connect_timeout_override="$ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT"
  fi
  if [[ -v ROBOCLAWS_WORK_NETWORK_MAX_TIME ]]; then
    max_time_was_set=1
    max_time_override="$ROBOCLAWS_WORK_NETWORK_MAX_TIME"
  fi

  set -a
  # shellcheck disable=SC1090
  source "$dotenv_path"
  set +a

  if ((probe_url_was_set)); then
    export ROBOCLAWS_WORK_NETWORK_PROBE_URL="$probe_url_override"
  fi
  if ((connect_timeout_was_set)); then
    export ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT="$connect_timeout_override"
  fi
  if ((max_time_was_set)); then
    export ROBOCLAWS_WORK_NETWORK_MAX_TIME="$max_time_override"
  fi
}

load_repo_dotenv

probe_url="${ROBOCLAWS_WORK_NETWORK_PROBE_URL:-}"
connect_timeout="${ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT:-1}"
max_time="${ROBOCLAWS_WORK_NETWORK_MAX_TIME:-3}"

usage() {
  cat <<'EOF'
Usage:
  scripts/dev/network_status.sh
  scripts/dev/network_status.sh --assert-off-work [label]
  scripts/dev/network_status.sh --is-work-network

Environment:
  ROBOCLAWS_WORK_NETWORK_PROBE_URL       required office-network probe URL
  ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT curl connect timeout in seconds
  ROBOCLAWS_WORK_NETWORK_MAX_TIME        curl max time in seconds
  ROBOCLAWS_DOTENV_PATH                  optional repo dotenv path override
EOF
}

probe_work_network() {
  if [[ -z "$probe_url" ]]; then
    return 2
  fi
  if ! command -v curl >/dev/null 2>&1; then
    return 2
  fi

  local http_code
  http_code="$(
    curl \
      --insecure \
      --silent \
      --show-error \
      --location \
      --output /dev/null \
      --write-out '%{http_code}' \
      --connect-timeout "$connect_timeout" \
      --max-time "$max_time" \
      "$probe_url" 2>/dev/null || true
  )"

  if [[ "$http_code" =~ ^[1-5][0-9][0-9]$ ]]; then
    return 0
  fi
  return 1
}

print_status() {
  local rc="$1"
  case "$rc" in
    0)
      echo "network: work"
      echo "probe: reachable $probe_url"
      echo "guard: system-provider Codex/Claude manual-debug recipes are blocked here"
      echo "guard: repo-local OpenAI Agents SDK provider routes are allowed"
      echo "guard: retired Codex/Claude engines do not fall back to missing repo-local provider routes"
      ;;
    1)
      echo "network: non-work"
      echo "probe: unreachable $probe_url"
      echo "guard: SDK live-agent routes may run, subject to normal provider keys"
      ;;
    *)
      echo "network: unknown"
      if [[ -n "$probe_url" ]]; then
        echo "probe: could not run curl against $probe_url"
      else
        echo "probe: ROBOCLAWS_WORK_NETWORK_PROBE_URL is not configured"
      fi
      echo "guard: SDK live-agent routes fail closed when they require a network decision"
      ;;
  esac
}

mode="${1:-status}"
case "$mode" in
  status)
    set +e
    probe_work_network
    rc=$?
    set -e
    print_status "$rc"
    ;;

  --is-work-network)
    probe_work_network
    ;;

  --assert-off-work)
    label="${2:-this command}"
    set +e
    probe_work_network
    rc=$?
    set -e
    case "$rc" in
      0)
        echo "error: work network detected; ${label} is blocked while ${probe_url} is reachable." >&2
        echo "       Switch off the work network, then rerun this command." >&2
        exit 1
        ;;
      1)
        echo "==> network guard ok: off work network (${probe_url} unreachable)" >&2
        ;;
      *)
        echo "error: cannot determine network status for ${label}; configure ROBOCLAWS_WORK_NETWORK_PROBE_URL and ensure curl is available." >&2
        exit 2
        ;;
    esac
    ;;

  -h|--help)
    usage
    ;;

  *)
    usage >&2
    exit 2
    ;;
esac
