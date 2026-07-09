#!/usr/bin/env bash
# Detect whether this machine is on the office work network.
#
# The office network is identified by reachability of
# https://api-router.evad.mioffice.cn/. Any HTTP response means the endpoint is
# reachable; connection failure means this is not the work network.

set -euo pipefail

probe_url="${ROBOCLAWS_WORK_NETWORK_PROBE_URL:-https://api-router.evad.mioffice.cn/}"
connect_timeout="${ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT:-1}"
max_time="${ROBOCLAWS_WORK_NETWORK_MAX_TIME:-3}"

usage() {
  cat <<'EOF'
Usage:
  scripts/dev/network_status.sh
  scripts/dev/network_status.sh --assert-off-work [label]
  scripts/dev/network_status.sh --is-work-network

Environment:
  ROBOCLAWS_WORK_NETWORK_PROBE_URL       override the office-network probe URL
  ROBOCLAWS_WORK_NETWORK_CONNECT_TIMEOUT curl connect timeout in seconds
  ROBOCLAWS_WORK_NETWORK_MAX_TIME        curl max time in seconds
EOF
}

probe_work_network() {
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
      echo "guard: OpenClaw and system-provider Codex/Claude manual-debug recipes are blocked here"
      echo "guard: SDK codex-router-responses/gpt-5.5 is blocked here after current HTTP 403 probes"
      echo "guard: SDK mimo-mify-responses/minimax-responses remain available with explicit provider overrides"
      echo "guard: retired Codex/Claude engines do not fall back to missing repo-local provider routes"
      ;;
    1)
      echo "network: non-work"
      echo "probe: unreachable $probe_url"
      echo "guard: OpenClaw and SDK live-agent routes may run, subject to normal provider keys"
      ;;
    *)
      echo "network: unknown"
      echo "probe: could not run curl against $probe_url"
      echo "guard: OpenClaw and SDK live-agent routes fail closed when they require a network decision"
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
        echo "error: cannot determine network status; curl is required for ${label}." >&2
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
