# OpenClaw Gateway lifecycle helpers.

set working-directory := '..'

default:
    @just --list openclaw

[group('gateway')]
pull-image:
    #!/usr/bin/env bash
    set -euo pipefail

    bash scripts/dev/network_status.sh --assert-off-work "OpenClaw image pull"

    OPENCLAW_DEFAULT_IMAGE="$(awk -F= '$1=="OPENCLAW_IMAGE_DEFAULT"{print $2}' scripts/openclaw/openclaw-defaults.env | tr -d '"')"
    if [[ -z "$OPENCLAW_DEFAULT_IMAGE" ]]; then
      echo "error: missing OPENCLAW_IMAGE_DEFAULT in scripts/openclaw/openclaw-defaults.env" >&2
      exit 1
    fi

    OPENCLAW_IMG="${OPENCLAW_IMG:-${IMAGE:-${OPENCLAW_IMAGE:-$OPENCLAW_DEFAULT_IMAGE}}}"

    if ! command -v docker >/dev/null 2>&1; then
      echo "error: docker not found in PATH" >&2
      exit 1
    fi

    if ! docker image inspect "$OPENCLAW_IMG" >/dev/null 2>&1; then
      echo "==> pulling $OPENCLAW_IMG"
      docker pull "$OPENCLAW_IMG"
    else
      echo "==> already cached: $OPENCLAW_IMG"
    fi

[group('gateway')]
gateway action="up" token_file=".openclaw-token" provider="mimo" agents="1":
    #!/usr/bin/env bash
    set -euo pipefail

    case "{{action}}" in
      up)
        bash scripts/dev/network_status.sh --assert-off-work "OpenClaw Gateway"
        if [[ -z "${ROBOCLAWS_MCP_URL:-}" ]]; then
          echo "error: ROBOCLAWS_MCP_URL is required for OpenClaw Gateway runs" >&2
          exit 1
        fi
        TOKEN=$(
          env \
            PROVIDER="{{provider}}" \
            AGENTS="{{agents}}" \
            OPENCLAW_TOKEN="${OPENCLAW_TOKEN:-demo}" \
            SKILLS_DIR="${SKILLS_DIR:-$PWD/skills/household-world}" \
            ./scripts/openclaw/openclaw-bootstrap.sh
        )
        [ -n "$TOKEN" ] || { echo "bootstrap failed — no token"; exit 1; }
        printf '%s\n' "$TOKEN" > "{{token_file}}"
        echo "==> gateway-up done. Token saved to {{token_file}}"
        ;;

      down)
        docker rm -f openclaw-gateway
        docker volume rm openclaw-gateway-config
        rm -f "{{token_file}}"
        echo "==> gateway-down done"
        ;;

      *)
        echo "error: unknown openclaw gateway action '{{action}}' (expected up|down)" >&2
        exit 1
        ;;
    esac
