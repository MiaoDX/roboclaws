#!/usr/bin/env bash
# openclaw-bootstrap.sh — idempotent first-run setup for a local OpenClaw Gateway
# with N named agents (agent-0, agent-1, ...), each with its own isolated
# workspace, auth profile, and bind-mounted skill. The Gateway reaches a
# host-side Roboclaws MCP server such as the household cleanup server.
#
# Does:
#   1. Pre-create every dir the Gateway + all N agents will need (as root).
#   2. Seed openclaw.json:
#        - gateway.http.endpoints.chatCompletions.enabled = true
#        - agents map: each agent-i entry with its own workspace + model pin
#   3. Seed each agent-i's auth-profiles.json with the provider api_key.
#   4. Chown the volume to uid 1000 (node user).
#   5. Start the Gateway — one --mount per agent so each has its own skill dir,
#      plus host-gateway routing for autonomous-loop tool calls back to the host.
#   6. Wait for /readyz.
#   7. Probe /v1/chat/completions on agent-0 with a PONG turn (fail fast if
#      anything in the skill/auth/model chain is broken).
#   8. Echo the live bearer token on stdout (only thing on stdout — everything
#      else goes to stderr so `TOKEN=$(scripts/openclaw/openclaw-bootstrap.sh)` works).
#
# Environment (all optional unless marked required, sensible defaults):
#   AGENTS       Number of named agents to create    (default: 2; must be 1..8)
#   AGENT_PREFIX Name prefix for agents              (default: agent-)
#   CONTAINER    Container name                      (default: openclaw-gateway)
#   IMAGE        Gateway image                       (default:
#                             openclaw-defaults.env:OPENCLAW_IMAGE_DEFAULT)
#   VOLUME       Named volume for /home/node/.openclaw (default: openclaw-gateway-config)
#   HOST_IP      Bind address on the host            (default: 127.0.0.1)
#   PORT         Gateway port                        (default: 18789)
#   ROBOCLAWS_MCP_ENABLED  Seed Roboclaws MCP tools  (default: 1)
#   ROBOCLAWS_MCP_URL      URL for the host-side MCP server
#                                                     (default: http://host.docker.internal:18788/mcp)
#   PROVIDER     Upstream LLM provider               (auto-detected from env —
#                                                     nvidia | mimo | kimi)
#   MODEL        Model id each agent uses            (default per PROVIDER — see below)
#   IMAGE_MODEL  Vision model for the Gateway's      (default: same as MODEL;
#                generic `image` tool path             set this explicitly when
#                                                       you want deterministic
#                                                       image routing)
#   SKILLS_DIR   Host path of the skill to mount     (default: $PWD/skills/household-world)
#   READY_TIMEOUT  Seconds to wait for /readyz       (default: 180)
#   TIMEOUT_SECONDS  Per-turn wall-clock cap         (default: 7200 = 2h;
#                                                     written to agents.defaults.
#                                                     timeoutSeconds.  NOT an
#                                                     idle watchdog — Gateway's
#                                                     scheduleAbortTimer is set
#                                                     once at run start and is
#                                                     never reset on activity
#                                                     (verified 2026-04-24 in
#                                                     pi-embedded-runner).  Sized
#                                                     as a backstop; the real
#                                                     stop path is the agent's
#                                                     own end_turn / roboclaws__
#                                                     done, or the UI Stop button
#                                                     on an active stream.  The
#                                                     autonomous loop overrides
#                                                     with wall_budget + 60.)
#
# Provider-specific vars (only the one matching PROVIDER is required):
#   KIMI_API_KEY   (PROVIDER=kimi)   Moonshot/Kimi API key
#   NV_API_KEY     (PROVIDER=nvidia) NVIDIA NIM API key (NVIDIA_API_KEY also accepted)
#   MIMO_TP_KEY    (PROVIDER=mimo)   MiMo token-plan key
#
# Provider-specific mode overrides:
#   KIMI_PROVIDER_MODE  (PROVIDER=kimi)  custom (default) | plugin
#   MIMO_PROVIDER_MODE  (PROVIDER=mimo)  openai (default) | anthropic
#
# Supported providers + default model (curated to just the one verified-
# working vision model per provider):
#
#   nvidia → nvidia/nvidia/nemotron-nano-12b-v2-vl  (free; vision; multi-image)
#   kimi   → kimi/k2p5                              (free coding tier; vision;
#                                                    aliases to kimi-for-coding
#                                                    upstream which is currently
#                                                    Kimi 2.6 — see
#                                                    /app/dist/provider-catalog-BCrO6TZn.js)
#   mimo   → mimo_openai/mimo-v2.5                 (token-plan; vision+tool-calls
#                                                    confirmed 2026-05-28)
#
# Auto-detection order when PROVIDER is unset: nvidia → mimo → kimi (prefers
# the verified-working provider; first provider with an API key in env wins).
#
# Why these providers and not more: household visual evidence can include
# image-bearing tool outputs, so the model must support image input. NVIDIA NIM's
# nvidia/nemotron-nano-12b-v2-vl is the only NIM vision model that
# survives the end-to-end constraints (image input + tool use from the
# Gateway's agent framework). Kimi's coding-tier provider via the
# Gateway plugin accepts multi-image too. Other models we probed hit
# one of: 1-image cap, no tool-use support on :free, or server-side
# errors. History lives in docs/human/openclaw/local.md if you want to
# re-evaluate after NIM / OpenRouter update their free-tier lineup.
#
# Exit codes:
#   0  success (token on stdout)
#   1  missing provider api key or AGENTS out of range
#   2  docker pull / run / volume / pre-seed error
#   3  Gateway /readyz never returned 200 within READY_TIMEOUT seconds
#   4  /v1/chat/completions probe against agent-0 failed
#   5  personality divergence probe failed (agents returned identical strategies)
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULTS_FILE="${SCRIPT_DIR}/openclaw-defaults.env"
if [[ -f "$DEFAULTS_FILE" ]]; then
    # shellcheck source=/dev/null
    . "$DEFAULTS_FILE"
fi
: "${OPENCLAW_IMAGE_DEFAULT:=ghcr.io/openclaw/openclaw:2026.4.25-beta.11}"

AGENTS="${AGENTS:-2}"
AGENT_PREFIX="${AGENT_PREFIX:-agent-}"
CONTAINER="${CONTAINER:-openclaw-gateway}"
IMAGE="${IMAGE:-${OPENCLAW_IMAGE:-$OPENCLAW_IMAGE_DEFAULT}}"
VOLUME="${VOLUME:-openclaw-gateway-config}"
HOST_IP="${HOST_IP:-127.0.0.1}"
PORT="${PORT:-18789}"

# Optional: host-side dir for the `roboclaws__snapshot` tool. When set, we
# bind-mount it into every agent's workspace at ``./snapshots`` so the
# agent can inline PNGs written there via `MEDIA:./snapshots/<file>.png`.
# The Gateway's agent-scoped media allow-list rooted at the workspace dir
# lets relative MEDIA paths resolve (see
# /app/dist/local-roots-*.js:getAgentScopedMediaLocalRoots).
ROBOCLAWS_SNAPSHOTS_DIR="${ROBOCLAWS_SNAPSHOTS_DIR:-}"

# ROBOCLAWS_MCP_ENABLED gates whether openclaw.json exposes the Roboclaws MCP
# server to Gateway agents. Keep the default enabled for household cleanup runs
# that start a host-side MCP server.
ROBOCLAWS_MCP_ENABLED="${ROBOCLAWS_MCP_ENABLED:-1}"
case "$ROBOCLAWS_MCP_ENABLED" in
    1|true|TRUE|yes|YES|on|ON) ROBOCLAWS_MCP_ENABLED="1" ;;
    0|false|FALSE|no|NO|off|OFF) ROBOCLAWS_MCP_ENABLED="0" ;;
    *)
        printf '[bootstrap] ERROR: %s\n' "Unsupported ROBOCLAWS_MCP_ENABLED: '$ROBOCLAWS_MCP_ENABLED' (expected 1 or 0)" >&2
        exit 1
        ;;
esac

# ROBOCLAWS_MCP_URL seeds mcp.servers.roboclaws.url in openclaw.json when MCP is
# enabled, so the Gateway exposes our MCP tool surface (observe/move/done) to
# the agent. Must be set BEFORE first container start — mutating mcp.* on a
# running Gateway triggers SIGUSR1 → PID-1 exit → container stop (spike F-3).
# Default uses host.docker.internal (container→host loopback).
ROBOCLAWS_MCP_URL="${ROBOCLAWS_MCP_URL:-http://host.docker.internal:18788/mcp}"

# ROBOCLAWS_TOOL_PROFILE controls which tool allowlist the Gateway applies to
# every agent. Default "minimal" keeps the surface tight; when MCP is enabled
# the bootstrap also splices in bundle-mcp so Roboclaws tools are reachable.
# "coding" and "messaging" exist for local probes only; a typo dies 1 rather
# than silently broadening the attack surface.
ROBOCLAWS_TOOL_PROFILE="${ROBOCLAWS_TOOL_PROFILE:-minimal}"
case "$ROBOCLAWS_TOOL_PROFILE" in
    minimal|coding|messaging) ;;
    *)
        printf '[bootstrap] ERROR: %s\n' "Unsupported ROBOCLAWS_TOOL_PROFILE: '$ROBOCLAWS_TOOL_PROFILE' (supported: minimal, coding, messaging)" >&2
        exit 1
        ;;
esac

SKILLS_DIR="${SKILLS_DIR:-${PWD}/skills/household-world}"
SOULS_DIR="${SOULS_DIR:-${PWD}/skills/household-world/souls}"
AGENT_SOULS="${AGENT_SOULS:-}"
PERSONALITY_PROBE="${PERSONALITY_PROBE:-1}"
READY_TIMEOUT="${READY_TIMEOUT:-180}"

gateway_started=0
preseed_py=""
_cleanup_on_exit() {
    local rc=$?
    if [[ -n "$preseed_py" && -f "$preseed_py" ]]; then
        rm -f "$preseed_py"
    fi
    if [[ $rc -ne 0 && "${gateway_started:-0}" == "1" ]]; then
        log "removing Gateway container after bootstrap failure"
        docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    fi
}
trap _cleanup_on_exit EXIT
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-7200}"

# Auto-detect PROVIDER when unset:
#   1) nvidia — if NV_API_KEY / NVIDIA_API_KEY is set (verified-working,
#      free NIM vision model with multi-image support)
#   2) kimi   — otherwise (free coding tier, vision; resolves to the
#      current kimi-for-coding upstream alias)
if [[ -z "${PROVIDER:-}" ]]; then
    if [[ -n "${NV_API_KEY:-}${NVIDIA_API_KEY:-}" ]]; then
        PROVIDER="nvidia"
    elif [[ -n "${MIMO_TP_KEY:-}" ]]; then
        PROVIDER="mimo"
    else
        PROVIDER="kimi"
    fi
fi

log() { printf '[bootstrap] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit "${2:-1}"; }

command -v docker >/dev/null 2>&1 || die "docker not found in PATH" 2
command -v python3 >/dev/null 2>&1 || die "python3 not found in PATH (needed for JSON)" 2

# Provider-specific defaults + api-key lookup + custom model catalog entries.
#
# EXTRA_MODELS_JSON is a JSON array of extension entries injected into
# openclaw.json → models.providers.<provider>.models so the Gateway's
# catalog merger recognizes models that aren't in the pinned image's
# built-in provider plugin catalog. Without this, the Gateway rejects the
# model with 400 "Unknown model".
case "$PROVIDER" in
    kimi)
        # Two Kimi provider modes are supported:
        #   custom (default) → register our explicit anthropic-messages
        #                      provider override at the same Kimi host
        #   plugin           → leave the Gateway's built-in kimi-coding
        #                      plugin untouched and route via kimi/k2p5
        #
        # Keep the default on "custom" because the built-in plugin
        # historically advertised reasoning-heavy behavior that pushed
        # multi-image turns into 60-120s and tripped the
        # Gateway's idle watchdog. The explicit switch exists so local
        # debugging can A/B the two provider paths without editing code.
        KIMI_PROVIDER_MODE="${KIMI_PROVIDER_MODE:-custom}"
        PROVIDER_API_KEY="${KIMI_API_KEY:-}"
        PROVIDER_ENV_VAR="KIMI_API_KEY"
        [[ -n "$PROVIDER_API_KEY" ]] || \
            die "KIMI_API_KEY env var is required for PROVIDER=kimi" 1

        case "$KIMI_PROVIDER_MODE" in
            custom)
                # Register Kimi as a **custom** anthropic-messages provider
                # (id=anthropic_kimi) rather than using the Gateway's built-in
                # `kimi-coding` plugin.  The built-in plugin advertises
                # `reasoning: true` in its catalog and drives api.kimi.com/coding/
                # in a mode that burns 3000+ CoT tokens per turn, pushing each
                # multi-image call to 60-120s and regularly tripping
                # the Gateway's idle watchdog (observed on 2026-04-20).
                #
                # Our custom registration points at the SAME host
                # (api.kimi.com/coding/) but pins the request shape we want —
                # plain anthropic-messages, no reasoning mode implied, canonical
                # User-Agent.  Same KIMI_API_KEY works for both paths.  Probed
                # 2026-04-20: PONG returns in ~5s vs 60-120s on the built-in.
                MODEL="${MODEL:-anthropic_kimi/k2.6}"
                PROVIDER_ID_OVERRIDE="anthropic_kimi"
                PROVIDER_BASE_URL=""   # unused — baseUrl lives in PROVIDER_ENTRY_JSON
                EXTRA_MODELS_JSON="[]" # unused when PROVIDER_ENTRY_JSON is set
                # Full custom provider entry — injected into openclaw.json with
                # models.mode=replace so only this entry drives routing (i.e. the
                # built-in kimi plugin's catalog is excluded from the merge).
                # Mirrors the ``anthropic_mm`` MiniMax pattern used in production.
                PROVIDER_ENTRY_JSON=$(cat <<JSON
{
  "baseUrl": "https://api.kimi.com/coding/",
  "apiKey": "${PROVIDER_API_KEY}",
  "auth": "api-key",
  "api": "anthropic-messages",
  "headers": {
    "User-Agent": "Claude-Code/1.0",
    "anthropic-version": "2023-06-01"
  },
  "models": [
    {
      "id": "k2p5",
      "name": "Kimi K2.5 (anthropic-messages)",
      "input": ["text", "image"],
      "reasoning": false,
      "contextWindow": 262144,
      "maxTokens": 32768
    },
    {
      "id": "k2.6",
      "name": "Kimi 2.6 (anthropic-messages)",
      "input": ["text", "image"],
      "reasoning": false,
      "contextWindow": 262144,
      "maxTokens": 32768
    }
  ]
}
JSON
)
                ;;
            plugin)
                # Keep the stock Gateway Kimi provider/plugin active:
                # `kimi/k2p5` is the built-in alias to Kimi's coding tier.
                MODEL="${MODEL:-kimi/k2p5}"
                PROVIDER_ID_OVERRIDE=""
                PROVIDER_BASE_URL=""
                EXTRA_MODELS_JSON="[]"
                PROVIDER_ENTRY_JSON=""
                ;;
            *)
                die "Unsupported KIMI_PROVIDER_MODE: '$KIMI_PROVIDER_MODE' (supported: custom, plugin)" 1
                ;;
        esac
        ;;
    nvidia)
        # nvidia/nvidia/nemotron-nano-12b-v2-vl — the only NVIDIA NIM
        # vision model verified end-to-end with the demo:
        #   • free (cost=$0 in the Gateway's built-in catalog)
        #   • supports ≥2 images (FPV + overhead map per turn)
        #   • survives the Gateway's tool-bearing agent framework
        # Models like meta/llama-3.2-*-vision-instruct cap at 1 image
        # and 400 on every demo step; minimax/kimi-thinking on NIM
        # either don't support vision or hit server-side errors.
        MODEL="${MODEL:-nvidia/nvidia/nemotron-nano-12b-v2-vl}"
        # NV_API_KEY (roboclaws convention) or NVIDIA_API_KEY (Gateway plugin default).
        PROVIDER_API_KEY="${NV_API_KEY:-${NVIDIA_API_KEY:-}}"
        PROVIDER_ENV_VAR="NVIDIA_API_KEY"
        # NVIDIA NIM OpenAI-compatible endpoint — matches the built-in
        # Gateway catalog's NVIDIA_BASE_URL
        # (/app/dist/provider-catalog-C9xZ5Sl52.js) so our override merges
        # cleanly with the implicit plugin.
        PROVIDER_BASE_URL="https://integrate.api.nvidia.com/v1"
        # Single curated entry. Keeping the list short means every model
        # the bootstrap advertises is known to work; the tests assert on
        # this invariant so accidental "let me add another" edits trip
        # the CI free-tier / multi-image checks.
        EXTRA_MODELS_JSON='[
            {"id":"nvidia/nemotron-nano-12b-v2-vl","name":"NVIDIA Nemotron Nano 12B V2 VL","input":["text","image"],"reasoning":false,"contextWindow":131072,"maxTokens":4096}
        ]'
        PROVIDER_ENTRY_JSON=""  # legacy merge path: nvidia plugin stays in play
        [[ -n "$PROVIDER_API_KEY" ]] || \
            die "NV_API_KEY (or NVIDIA_API_KEY) env var is required for PROVIDER=nvidia" 1
        ;;
    mimo)
        PROVIDER_API_KEY="${MIMO_TP_KEY:-}"
        PROVIDER_ENV_VAR="MIMO_TP_KEY"
        [[ -n "$PROVIDER_API_KEY" ]] || \
            die "MIMO_TP_KEY env var is required for PROVIDER=mimo" 1

        MIMO_PROVIDER_MODE="${MIMO_PROVIDER_MODE:-openai}"
        case "$MIMO_PROVIDER_MODE" in
            openai)
                # OpenAI-compatible endpoint; mimo-v2.5 is image-capable
                # (direct vision), so no image-delegation model is needed.
                MODEL="${MODEL:-mimo_openai/mimo-v2.5}"
                PROVIDER_ID_OVERRIDE="mimo_openai"
                PROVIDER_BASE_URL=""
                EXTRA_MODELS_JSON="[]"
                PROVIDER_ENTRY_JSON=$(cat <<JSON
{
  "baseUrl": "https://token-plan-cn.xiaomimimo.com/v1",
  "apiKey": "${PROVIDER_API_KEY}",
  "auth": "api-key",
  "api": "openai-completions",
  "models": [
    {"id":"mimo-v2.5","name":"MiMo V2.5 (vision+tools)","input":["text","image"],"reasoning":false,"contextWindow":1048576,"maxTokens":32768}
  ]
}
JSON
)
                ;;
            anthropic)
                # Anthropic-compatible endpoint — mimo-v2.5 vision + tool-calls.
                MODEL="${MODEL:-mimo_anthropic/mimo-v2.5}"
                PROVIDER_ID_OVERRIDE="mimo_anthropic"
                PROVIDER_BASE_URL=""
                EXTRA_MODELS_JSON="[]"
                PROVIDER_ENTRY_JSON=$(cat <<JSON
{
  "baseUrl": "https://token-plan-cn.xiaomimimo.com/anthropic",
  "apiKey": "${PROVIDER_API_KEY}",
  "auth": "api-key",
  "api": "anthropic-messages",
  "headers": {"anthropic-version": "2023-06-01"},
  "models": [
    {"id":"mimo-v2.5","name":"MiMo V2.5 (anthropic vision+tools)","input":["text","image"],"reasoning":false,"contextWindow":1048576,"maxTokens":32768}
  ]
}
JSON
)
                ;;
            *)
                die "Unsupported MIMO_PROVIDER_MODE: '$MIMO_PROVIDER_MODE' (supported: openai, anthropic)" 1
                ;;
        esac
        ;;
    *)
        die "Unsupported PROVIDER: '$PROVIDER' (supported: kimi, nvidia, mimo)" 1
        ;;
esac

[[ -d "$SKILLS_DIR" ]] || die "Skill directory not found: $SKILLS_DIR" 2
if ! [[ "$AGENTS" =~ ^[0-9]+$ ]] || (( AGENTS < 1 || AGENTS > 8 )); then
    die "AGENTS must be an integer 1..8 (got: $AGENTS)" 1
fi
# agentId regex from /app/dist/http-utils-*.js: [a-z0-9][a-z0-9_-]{0,63}
if ! [[ "$AGENT_PREFIX" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
    die "AGENT_PREFIX must match [a-z0-9][a-z0-9_-]* (got: $AGENT_PREFIX)" 1
fi

log "image        : $IMAGE"
log "container    : $CONTAINER"
log "volume       : $VOLUME"
log "bind         : ${HOST_IP}:${PORT}"
log "mcp enabled  : $ROBOCLAWS_MCP_ENABLED"
if [[ "$ROBOCLAWS_MCP_ENABLED" == "1" ]]; then
    log "mcp url      : $ROBOCLAWS_MCP_URL"
fi
log "tool profile : $ROBOCLAWS_TOOL_PROFILE"
log "agents       : $AGENTS (prefix=$AGENT_PREFIX → ${AGENT_PREFIX}0 .. ${AGENT_PREFIX}$((AGENTS-1)))"
log "provider     : $PROVIDER"
[[ "$PROVIDER" == "kimi" ]] && log "provider mode: $KIMI_PROVIDER_MODE"
[[ "$PROVIDER" == "mimo" ]] && log "provider mode: $MIMO_PROVIDER_MODE"
log "model        : $MODEL"
log "image model  : ${IMAGE_MODEL:-<auto>}"
log "skill        : $SKILLS_DIR"
[[ -n "$AGENT_SOULS" ]] && log "souls        : $AGENT_SOULS (dir: $SOULS_DIR)"

# Build the list of agent ids once so the pre-seed and docker-run stages agree.
agent_ids=()
for ((i=0; i<AGENTS; i++)); do
    agent_ids+=("${AGENT_PREFIX}${i}")
done
AGENT_IDS_CSV="$(IFS=,; printf '%s' "${agent_ids[*]}")"

# ----- Parse + validate AGENT_SOULS ------------------------------------------
# Builds soul_assignments[] indexed by agent integer (0..AGENTS-1).
# Accepts two forms:
#   csv positional: "aggressive,defensive"   → agent-0=aggressive, agent-1=defensive
#   dict form:      "agent-0:aggressive,agent-2:cooperative" → sparse; unset slots = ""
# Empty AGENT_SOULS → all slots empty (no SOUL.md written → stock OpenClaw SOUL).
declare -a soul_assignments
for ((i=0; i<AGENTS; i++)); do soul_assignments[i]=""; done

if [[ -n "$AGENT_SOULS" ]]; then
    # Detect form: if any entry contains ':', it's dict form; else csv positional.
    if [[ "$AGENT_SOULS" == *:* ]]; then
        # Dict form: agent-N:soulname
        IFS=',' read -ra _dict_entries <<< "$AGENT_SOULS"
        for _entry in "${_dict_entries[@]}"; do
            _aname="${_entry%%:*}"
            _soul="${_entry#*:}"
            # Map agent name to index
            _found=0
            for ((i=0; i<AGENTS; i++)); do
                if [[ "${agent_ids[$i]}" == "$_aname" ]]; then
                    soul_assignments[$i]="$_soul"
                    _found=1
                    break
                fi
            done
            [[ $_found -eq 1 ]] || die "AGENT_SOULS dict entry '$_aname' does not match any agent (agents: $AGENT_IDS_CSV)" 1
        done
    else
        # Positional csv: count must match AGENTS
        IFS=',' read -ra _soul_csv <<< "$AGENT_SOULS"
        if [[ "${#_soul_csv[@]}" -ne "$AGENTS" ]]; then
            die "AGENT_SOULS count (${#_soul_csv[@]}) must match AGENTS ($AGENTS)" 1
        fi
        for ((i=0; i<AGENTS; i++)); do
            soul_assignments[$i]="${_soul_csv[$i]}"
        done
    fi

    # Validate each non-empty soul name against files in SOULS_DIR.
    _available_souls="$(ls "$SOULS_DIR"/*.md 2>/dev/null | xargs -n1 basename | sed 's/\.md$//' | paste -sd, - 2>/dev/null || true)"
    for ((i=0; i<AGENTS; i++)); do
        _soul="${soul_assignments[$i]}"
        [[ -z "$_soul" ]] && continue
        if [[ ! -f "$SOULS_DIR/${_soul}.md" ]]; then
            die "unknown SOUL '${_soul}'; available: ${_available_souls:-<none found in $SOULS_DIR>}" 1
        fi
    done

    # Log assignments
    for ((i=0; i<AGENTS; i++)); do
        _soul="${soul_assignments[$i]}"
        if [[ -n "$_soul" ]]; then
            log "${agent_ids[$i]} → SOUL: $_soul"
        else
            log "${agent_ids[$i]} → SOUL: (default)"
        fi
    done
fi

# ----- 1. Clean slate for the container name ------------------------------
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "removing existing container $CONTAINER"
    docker rm -f "$CONTAINER" >/dev/null
fi

# ----- 2. Pull image ------------------------------------------------------
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    log "pulling $IMAGE (first run only)"
    docker pull "$IMAGE" >&2 || die "docker pull failed" 2
fi

# ----- 3. Ensure config volume exists and is writable by uid 1000 --------
docker volume create "$VOLUME" >/dev/null || die "docker volume create failed" 2

# Build AGENT_SOUL_CSV: positional csv of soul names for agent-0..agent-(AGENTS-1).
# Empty slot = "" (stock SOUL). Passed into the pre-seed container as one env var.
_soul_csv_for_preseed=""
for ((i=0; i<AGENTS; i++)); do
    [[ $i -gt 0 ]] && _soul_csv_for_preseed+=","
    _soul_csv_for_preseed+="${soul_assignments[$i]}"
done

log "pre-seeding config volume + $AGENTS agent(s)"
# Read the canonical OpenClaw plugin allow-list from its single source of
# truth (``scripts/openclaw/openclaw_plugin_allowlist.py``) and forward it to the
# pre-seed container as JSON. See that file for rationale + per-entry
# justification.
PLUGIN_ALLOW_JSON="$(python3 -c "
import json, sys
sys.path.insert(0, '${SCRIPT_DIR}')
from openclaw_plugin_allowlist import ALLOWED
print(json.dumps(ALLOWED))
")"
[[ -n "$PLUGIN_ALLOW_JSON" ]] || die "failed to read openclaw_plugin_allowlist.py" 2

# Write the pre-seed Python to a host temp file and bind-mount it into the
# container instead of streaming it through `sh -lc '...heredoc...'`. The
# wrapped-heredoc approach silently breaks the moment any character in the
# Python body needs bash escaping — most recently, an apostrophe in a comment
# (commit 934fa88) terminated the outer single-quoted string and Python died
# with a misleading SyntaxError. A temp file decouples Python content from
# bash quoting entirely; cleanup runs from the EXIT trap above.
preseed_py="$(mktemp -t openclaw-preseed.XXXXXX.py)"
cat > "$preseed_py" <<'PY'
import json, os, shutil
agent_ids = os.environ["AGENT_IDS_CSV"].split(",")
provider_id = os.environ["PROVIDER_ID"]
# When a custom catalog entry is supplied (PROVIDER_ENTRY_JSON), it lives
# under its own provider id (e.g. ``anthropic_kimi`` for the fast Kimi
# path) rather than reusing the plugin id (``kimi``).  This keeps the
# built-in plugin entry intact while letting mode=replace wipe the
# catalog merge and only register our explicit config.
provider_id_override = os.environ.get("PROVIDER_ID_OVERRIDE") or ""
custom_provider_id = provider_id_override or provider_id
provider_key = os.environ["PROVIDER_API_KEY"]
model = os.environ["MODEL"]
extra_models = json.loads(os.environ.get("EXTRA_MODELS_JSON") or "[]")
provider_base_url = os.environ.get("PROVIDER_BASE_URL", "")
provider_entry_json = os.environ.get("PROVIDER_ENTRY_JSON") or ""
agent_soul_csv = os.environ.get("AGENT_SOUL_CSV", "")
# Phase 2.6 additions (D-03, D-04): seed the MCP server block + per-agent
# tool profile BEFORE first container start so the Gateway does not
# SIGUSR1-restart when mcp.servers changes (spike F-3).
mcp_url = os.environ["ROBOCLAWS_MCP_URL"]
mcp_enabled = os.environ.get("ROBOCLAWS_MCP_ENABLED", "1") == "1"
tool_profile = os.environ["ROBOCLAWS_TOOL_PROFILE"]
base = "/home/node/.openclaw"

# Pre-create every dir so Docker doesnt create intermediate bind-mount
# parents as root. Also covers workspace/state which the Gateway writes to
# on first boot and would fail on root-owned parent.
os.makedirs(base, exist_ok=True)
os.makedirs(os.path.join(base, "logs"), exist_ok=True)
for aid in agent_ids:
    os.makedirs(os.path.join(base, "agents", aid, "agent"), exist_ok=True)
    os.makedirs(os.path.join(base, "workspaces", aid, "skills"), exist_ok=True)
    os.makedirs(os.path.join(base, "workspaces", aid, "state"), exist_ok=True)
# Keep the legacy "main" agent around with its own workspace too — the Gateway
# insists on a default agent existing even if we never route to it.
os.makedirs(os.path.join(base, "agents", "main", "agent"), exist_ok=True)
os.makedirs(os.path.join(base, "workspace", "skills"), exist_ok=True)
os.makedirs(os.path.join(base, "workspace", "state"), exist_ok=True)

# Per-agent SOUL.md distribution.
# soul_csv is positional, one entry per agent-id (empty string = leave default).
# Unconditionally remove any stale SOUL.md first (prevents stale persona
# surviving across bootstrap re-runs when AGENT_SOULS changes).
souls_csv_entries = agent_soul_csv.split(",") if agent_soul_csv else []
for idx, aid in enumerate(agent_ids):
    soul_path = os.path.join(base, "workspaces", aid, "SOUL.md")
    # Always clean up any leftover from a previous run.
    if os.path.exists(soul_path):
        os.remove(soul_path)
    soul_name = souls_csv_entries[idx] if idx < len(souls_csv_entries) else ""
    if soul_name:
        src = f"/host-souls/{soul_name}.md"
        shutil.copyfile(src, soul_path)

# openclaw.json: gateway settings + agents.list (array of per-agent entries).
# Schema reference: /app/dist/runtime-schema-*.js:5648 — agents.list items
# have { id, workspace, agentDir, model: {primary, fallbacks?}, ... }.
agent_entries = [
    {
        "id": aid,
        "workspace": f"/home/node/.openclaw/workspaces/{aid}",
        "agentDir": f"/home/node/.openclaw/agents/{aid}/agent",
        "model": {"primary": model},
        # tools.profile restricts the agent tool surface (spike U2).
        # alsoAllow splices `bundle-mcp` into the profile's allow-list via
        # mergeAlsoAllowPolicy in /app/dist/tool-policy-*.js.  Required
        # since image 2026.4.25-beta.11: upstream consolidated MCP-tool
        # exposure under the `bundle-mcp` policy ID, and only `coding` /
        # `messaging` profiles get it for free — `minimal` no longer does.
        # Without this splice, the agent ends up with only `session_status`
        # and every roboclaws__* tool returns "Tool not found".
        # See docs/ai/openclaw/tool-profiles.md for the full image diff and
        # re-validation steps when bumping the gateway image.
        "tools": (
            {"profile": tool_profile, "alsoAllow": ["bundle-mcp"]}
            if mcp_enabled
            else {"profile": tool_profile}
        ),
    }
    for aid in agent_ids
]
timeout_seconds = int(os.environ.get("TIMEOUT_SECONDS") or "7200")
image_model = os.environ.get("IMAGE_MODEL") or model
# Pre-seed the bearer token when OPENCLAW_TOKEN is supplied (default in
# the chat* Makefile targets so operators paste "demo" once per browser
# profile and move on). When unset, the Gateway generates a random token
# on first boot — the readyz loop below reads back whatever the live
# value is, so this branch is safe either way.
auth_cfg = {"mode": "token"}
_fixed_token = (os.environ.get("OPENCLAW_TOKEN") or "").strip()
if _fixed_token:
    auth_cfg["token"] = _fixed_token
defaults_cfg = {
    "model": {"primary": model},
    # Pin the generic `image` tool path to the same model by default
    # so OpenClaw does not auto-pair to the first image-capable
    # catalog entry for the provider (which made the custom Kimi path
    # silently route image analysis through `anthropic_kimi/k2p5`).
    "imageModel": {"primary": image_model},
    "timeoutSeconds": timeout_seconds,
}
if tool_profile == "minimal":
    # Minimal-profile agents only expose navigation/chat tools, not a
    # constrained append-only memory write path. Disable Gateway-side
    # pre-compaction memory flush so it does not inject an impossible
    # "write memory now" turn that the model misroutes into roboclaws__done.
    defaults_cfg["compaction"] = {"memoryFlush": {"enabled": False}}
config = {
    "gateway": {
        "auth": auth_cfg,
        "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
    },
    "agents": {
        # timeoutSeconds is a per-turn WALL-CLOCK cap, not an idle watchdog.
        # Gateway scheduleAbortTimer is set once at run start and is NEVER
        # reset on tool-call activity (verified 2026-04-24 in
        # pi-embedded-runner; despite older docs calling it an "idle
        # watchdog").  7200 = 2h, sized as a backstop; the intended stop path
        # is the agent own end_turn / roboclaws__done or the UI Stop button
        # on an active stream.  Earlier 600s defaulting bit hard on
        # open-ended exploration prompts: the turn aborted mid-tool-call
        # and Gateway surfaced a timeout error without a terminal frame,
        # wedging the Control UI Stop/send controls.  Per-call HTTP stalls
        # (undici headers/bodyTimeout, smithy socket-idle) still fail fast
        # at a shorter horizon — this knob only caps the aggregate tool-call
        # loop inside a single user turn.
        "defaults": defaults_cfg,
        "list": agent_entries,
    },
}
# MCP server block (Phase 2.6, D-04): seeded BEFORE first container start
# because adding mcp.servers to a running Gateway fires SIGUSR1 → container
# exit (spike F-3). The key is `transport` (not `type`); only
# "streamable-http" and "sse" parse — anything else silently fails with
# [bundle-mcp] SSE error: Non-200 status code (400) and the agent reports
# it has no such tool (spike F-1). Source of truth for the loader:
# /app/dist/pi-bundle-mcp-tools-*.js (hash suffix changes per image).
# Note: per-agent tools.alsoAllow=["bundle-mcp"] above is what actually
# exposes these servers' tools to the agent — the config block alone is
# necessary but not sufficient on image 2026.4.25-beta.11+.
if mcp_enabled:
    config["mcp"] = {
        "servers": {
            "roboclaws": {
                "transport": "streamable-http",
                "url": mcp_url,
            }
        }
    }
# Strict plugin allow-list. Anything not in this list is hard-rejected by
# the gateway, regardless of enabledByDefault. Source of truth lives in
# scripts/openclaw/openclaw_plugin_allowlist.py and is forwarded by the host bash
# wrapper as PLUGIN_ALLOW_JSON. See that file for per-entry justification.
plugin_allow = json.loads(os.environ.get("PLUGIN_ALLOW_JSON") or "[]")
if plugin_allow:
    config["plugins"] = {
        "allow": plugin_allow,
        # Pin the embedded-ACP health probe to one of OUR agents instead
        # of the upstream default ``codex`` (which isn't installed and was
        # suspected of stalling the post-pricing-fetch sidecar startup
        # window). ``enabled: true`` is REQUIRED alongside ``config`` —
        # without it the entries-system silently ignores the config block
        # and warns ``plugin disabled (bundled (disabled by default)) but
        # config is present`` (probed live 2026-04-28).
        "entries": {
            "acpx": {
                "enabled": True,
                "config": {"probeAgent": agent_ids[0]},
            },
        },
    }
# Inject extra model catalog entries so the Gateways model-catalog merger
# recognizes the models we want to use. Without this, the Gateway rejects
# models with 400 "Unknown model: <id>" because the pinned images built-in
# provider plugin catalog does not include newer NIM / OpenRouter models.
# Schema: /app/dist/models-config-*.js — cfg.models.providers.<id>.models[]
# with { id, name, input, reasoning?, contextWindow?, maxTokens? }
#
# Two routes, mutually exclusive per bootstrap run:
#   1. PROVIDER_ENTRY_JSON set  → full custom provider entry with apiKey
#      inline, auth=api-key, and models[]; written under mode=replace so
#      only this entry drives routing (sidesteps a misbehaving built-in
#      plugin catalog, e.g. the kimi-coding reasoning-by-default quirk).
#   2. EXTRA_MODELS_JSON set    → just append models to an existing plugin
#      provider (mode=merge); used by the nvidia path.
# "mode: merge" is the default and merges these into the implicit plugin-
# supplied entries (see /app/dist/models-config-*.js:planOpenClawModelsJson).
if provider_entry_json:
    # Parse the injected entry verbatim so authors can tweak headers /
    # auth shape without teaching this script every field.
    provider_entry = json.loads(provider_entry_json)
    config["models"] = {
        "mode": "replace",
        "providers": {
            custom_provider_id: provider_entry,
        },
    }
elif extra_models:
    # The Gateway config validator requires baseUrl when a provider entry
    # is declared explicitly. We pass the same value the built-in plugin
    # uses, so the merger (mode=merge) unions our new model entries with
    # the implicit catalog without shadowing anything.
    provider_entry = {"models": extra_models}
    if provider_base_url:
        provider_entry["baseUrl"] = provider_base_url
        provider_entry["api"] = "openai-completions"
    config["models"] = {
        "mode": "merge",
        "providers": {
            provider_id: provider_entry,
        },
    }
with open(os.path.join(base, "openclaw.json"), "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2)

# Per-agent auth-profiles.json. Schema verified against
# /app/dist/store-*.js:parseCredentialEntry in image 2026.4.14:
#   type in {"api_key", "oauth", "token"} (snake_case)
#   provider must be non-empty
#   key is the credential material
# Provider id matches either the built-in Gateway plugin id (kimi, nvidia)
# or the custom provider id we registered above (anthropic_kimi).  The
# apiKey in PROVIDER_ENTRY_JSON is the authoritative credential when set,
# but we still write a legacy profile under the plugin id so downstream
# code reading auth-profiles.json has a valid entry either way.
profile = {
    "profiles": {
        f"{custom_provider_id}:manual": {
            "type": "api_key",
            "provider": custom_provider_id,
            "key": provider_key,
        }
    }
}
if custom_provider_id != provider_id:
    profile["profiles"][f"{provider_id}:manual"] = {
        "type": "api_key",
        "provider": provider_id,
        "key": provider_key,
    }
for aid in agent_ids + ["main"]:
    path = os.path.join(base, "agents", aid, "agent", "auth-profiles.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2)
    os.chmod(path, 0o600)
PY

# Sanity check the temp file before shipping it into the container — catches
# typos before docker spins up, with a host-side stack trace.
python3 -c "compile(open('$preseed_py').read(), '$preseed_py', 'exec')" \
    || die "pre-seed Python failed to compile (see traceback above)" 2

docker run --rm --user root \
    -v "$VOLUME:/home/node/.openclaw" \
    -v "${SOULS_DIR}:/host-souls:ro" \
    -v "${preseed_py}:/preseed.py:ro" \
    -e PROVIDER_API_KEY="$PROVIDER_API_KEY" \
    -e PROVIDER_ID="$PROVIDER" \
    -e PROVIDER_ID_OVERRIDE="${PROVIDER_ID_OVERRIDE:-}" \
    -e PROVIDER_ENTRY_JSON="${PROVIDER_ENTRY_JSON:-}" \
    -e TIMEOUT_SECONDS="$TIMEOUT_SECONDS" \
    -e MODEL="$MODEL" \
    -e IMAGE_MODEL="${IMAGE_MODEL:-$MODEL}" \
    -e AGENT_IDS_CSV="$AGENT_IDS_CSV" \
    -e EXTRA_MODELS_JSON="$EXTRA_MODELS_JSON" \
    -e PROVIDER_BASE_URL="$PROVIDER_BASE_URL" \
    -e AGENT_SOUL_CSV="$_soul_csv_for_preseed" \
    -e ROBOCLAWS_MCP_ENABLED="$ROBOCLAWS_MCP_ENABLED" \
    -e ROBOCLAWS_MCP_URL="$ROBOCLAWS_MCP_URL" \
    -e ROBOCLAWS_TOOL_PROFILE="$ROBOCLAWS_TOOL_PROFILE" \
    -e OPENCLAW_TOKEN="${OPENCLAW_TOKEN:-}" \
    -e PLUGIN_ALLOW_JSON="$PLUGIN_ALLOW_JSON" \
    "$IMAGE" sh -lc 'set -eu; python3 /preseed.py; chown -R 1000:1000 /home/node/.openclaw' \
    >&2 || die "volume pre-seed failed" 2

# ----- 4. Launch the Gateway — one skill mount per agent -----------------
log "starting Gateway with $AGENTS agent workspace(s)"
skill_basename="$(basename "$SKILLS_DIR")"
mount_args=(
    -p "${HOST_IP}:${PORT}:18789"
    -v "$VOLUME:/home/node/.openclaw"
    --add-host=host.docker.internal:host-gateway
    # Blackhole the two pricing-catalog URLs the gateway fetches at boot.
    # They live in /app/dist/usage-format-*.js as
    #   const OPENROUTER_MODELS_URL  = "https://openrouter.ai/api/v1/models";
    #   const LITELLM_PRICING_URL    = "https://raw.githubusercontent.com/...";
    #   const FETCH_TIMEOUT_MS       = 6e4;   // 60s
    # When unreachable, both fail-fast with ECONNREFUSED instead of waiting
    # the full 60s timeout, and the gateway's pricing layer falls through
    # to ``replaceGatewayModelPricingCache(new Map())``. No config knob is
    # exposed so we shape the network instead of the config.
    --add-host=openrouter.ai:0.0.0.0
    --add-host=raw.githubusercontent.com:0.0.0.0
    -e OPENCLAW_AUTH_MODE=token
    -e "ROBOCLAWS_MCP_ENABLED=${ROBOCLAWS_MCP_ENABLED}"
    -e "ROBOCLAWS_MCP_URL=${ROBOCLAWS_MCP_URL}"
    # Gateway plugins read the provider key from the env var named by the plugin
    # manifest (providerAuthEnvVars); the value comes from the roboclaws-side
    # secret (KIMI_API_KEY or NV_API_KEY, depending on PROVIDER).
    -e "${PROVIDER_ENV_VAR}=${PROVIDER_API_KEY}"
)
# Optional: bump Gateway log level to DEBUG for upstream-traffic debugging.
# Set GATEWAY_DEBUG=1 when you need to see what the Gateway sends to Kimi /
# NVIDIA on a failing call.  Off by default — DEBUG is verbose.
if [[ "${GATEWAY_DEBUG:-0}" == "1" ]]; then
    mount_args+=(-e "OPENCLAW_LOG_LEVEL=debug" -e "DEBUG=*")
    log "GATEWAY_DEBUG=1 — Gateway will log at DEBUG level"
fi
for aid in "${agent_ids[@]}"; do
    mount_args+=(-v "${SKILLS_DIR}:/home/node/.openclaw/workspaces/${aid}/skills/${skill_basename}:ro")
done

# Snapshots bind: one host dir per agent, mounted into that agent's workspace
# at ``./snapshots``. `roboclaws__snapshot` writes PNGs on the host side;
# the agent references them from chat as ``MEDIA:./snapshots/<file>.png``.
if [[ -n "$ROBOCLAWS_SNAPSHOTS_DIR" ]]; then
    for aid in "${agent_ids[@]}"; do
        agent_snap_dir="${ROBOCLAWS_SNAPSHOTS_DIR%/}/${aid}"
        mkdir -p "$agent_snap_dir"
        # Container runs as uid 1000 in the stock image; a too-tight umask on
        # the host would break the bind-write. 0777 is blunt but fine for a
        # single-operator local-dev workstation (same rationale as ``state``
        # dir pre-seed in step 3 above).
        chmod 0777 "$agent_snap_dir" 2>/dev/null || true
        mount_args+=(-v "${agent_snap_dir}:/home/node/.openclaw/workspaces/${aid}/snapshots")
    done
    log "snapshots    : ${ROBOCLAWS_SNAPSHOTS_DIR} (bound into each agent workspace)"
fi
docker run -d --name "$CONTAINER" "${mount_args[@]}" "$IMAGE" >/dev/null \
    || die "docker run failed" 2
gateway_started=1

# ----- 5. Wait for /readyz -----------------------------------------------
# Token is generated on first boot. Read it from the volume so we can auth the
# readyz probe instead of relying on an env-provided value the Gateway ignores.
log "waiting up to ${READY_TIMEOUT}s for Gateway readiness"
deadline=$(( $(date +%s) + READY_TIMEOUT ))
_last_tick=$(date +%s)
ready=0
token=""
while (( $(date +%s) < deadline )); do
    _now=$(date +%s)
    _elapsed=$(( _now - (deadline - READY_TIMEOUT) ))
    # Per-10s progress tick so users don't think the bootstrap hung
    if (( _now - _last_tick >= 10 )); then
        log "readyz: still waiting (${_elapsed}s/${READY_TIMEOUT}s)"
        _last_tick=$_now
    fi
    token=$(docker exec "$CONTAINER" sh -lc \
        'cat /home/node/.openclaw/openclaw.json 2>/dev/null' \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("gateway",{}).get("auth",{}).get("token",""))' \
        2>/dev/null || true)
    if [[ -n "$token" ]] && \
       curl -sf --max-time 3 \
            -H "Authorization: Bearer $token" \
            "http://${HOST_IP}:${PORT}/readyz" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
if [[ $ready -ne 1 ]]; then
    log "Gateway failed to become ready; dumping logs:"
    docker logs --tail 50 "$CONTAINER" >&2 || true
    die "readyz timeout" 3
fi
log "Gateway ready"

# ----- 6. Verify each named agent exists in the live config -------------
log "verifying $AGENTS named agent(s) registered"
docker exec "$CONTAINER" python3 - <<PY >&2 || die "agent registration check failed" 2
import json, sys
with open("/home/node/.openclaw/openclaw.json") as fh:
    cfg = json.load(fh)
want = "$AGENT_IDS_CSV".split(",")
have = {entry.get("id") for entry in cfg.get("agents", {}).get("list", [])}
missing = [a for a in want if a not in have]
if missing:
    print(f"missing agents in openclaw.json: {missing}", file=sys.stderr)
    sys.exit(1)
print("registered:", ", ".join(sorted(have & set(want))))
PY

# ----- 7. Sanity probe: one-shot /v1/chat/completions on agent-0 --------
probe_agent="${agent_ids[0]}"
log "probing /v1/chat/completions via model=openclaw/${probe_agent} (~30s cold start)"
# Bumped 90 → 180 because the model has the full tool surface (bundle-mcp +
# session_status) on this turn and an over-eager model can squeeze in a tool
# call before the PONG reply. Wrap in `if ... else probe_rc=$?` so curl
# failure (e.g. 28 timeout) does not get pre-empted by `set -e` before our
# diagnostic block at line below runs.
PROBE_TIMEOUT="${PROBE_TIMEOUT:-180}"
if probe=$(curl -s --max-time "$PROBE_TIMEOUT" -X POST "http://${HOST_IP}:${PORT}/v1/chat/completions" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"openclaw/${probe_agent}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with only PONG.\"}]}" 2>&1); then
    probe_rc=0
else
    probe_rc=$?
fi
if [[ $probe_rc -ne 0 ]]; then
    log "probe failed (curl exit $probe_rc): $probe"
    docker logs --tail 20 "$CONTAINER" >&2 || true
    die "probe curl failed" 4
fi
case "$probe" in
    *'"PONG"'*|*'"Pong"'*|*'content":"'[Pp][Oo][Nn][Gg]*)
        log "probe ok — openclaw/${probe_agent} is live and skill-aware"
        ;;
    *)
        log "probe response: $probe"
        docker logs --tail 20 "$CONTAINER" >&2 || true
        die "probe failed — see container logs above" 4
        ;;
esac

# ----- 8. Personality divergence probe (when AGENT_SOULS set + distinct) ----
# Ask each agent the same strategy question; assert responses diverge.
# Skipped when: AGENT_SOULS empty, only one agent, all souls identical, or
# PERSONALITY_PROBE=0 override.
_should_probe=0
if [[ -n "$AGENT_SOULS" && "$PERSONALITY_PROBE" != "0" && "$AGENTS" -gt 1 ]]; then
    # Check if all soul assignments are identical (e.g. cooperative,cooperative)
    _all_same=1
    _first_soul="${soul_assignments[0]}"
    for ((i=1; i<AGENTS; i++)); do
        if [[ "${soul_assignments[$i]}" != "$_first_soul" ]]; then
            _all_same=0
            break
        fi
    done
    [[ $_all_same -eq 0 ]] && _should_probe=1
fi

if [[ $_should_probe -eq 1 ]]; then
    log "personality probe: asking all agents 'describe your strategy in one sentence'"
    _probe_strategy_q="In one short sentence, describe your strategy."
    declare -A _strategy_hashes
    _probe_ok=1
    for ((i=0; i<AGENTS; i++)); do
        _agent_name="${agent_ids[$i]}"
        _resp=$(curl -s --max-time 90 -X POST "http://${HOST_IP}:${PORT}/v1/chat/completions" \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"openclaw/${_agent_name}\",\"messages\":[{\"role\":\"user\",\"content\":\"${_probe_strategy_q}\"}]}" 2>&1 || true)
        _content=$(printf '%s' "$_resp" | python3 -c \
            'import json,sys; d=json.load(sys.stdin); print((d.get("choices") or [{}])[0].get("message",{}).get("content","") or "")' \
            2>/dev/null || true)
        # Hash first 64 chars to compare distinctness
        _hash=$(printf '%s' "${_content:0:64}" | sha256sum | cut -c1-16)
        log "  ${_agent_name} (SOUL=${soul_assignments[$i]}): ${_content:0:120}"
        _strategy_hashes[$_agent_name]="$_hash"
    done
    # Check all hashes are distinct
    declare -A _seen_hashes
    for _aname in "${!_strategy_hashes[@]}"; do
        _h="${_strategy_hashes[$_aname]}"
        if [[ -n "${_seen_hashes[$_h]+x}" ]]; then
            log "personality probe FAILED — ${_aname} and ${_seen_hashes[$_h]} returned identical strategy responses"
            log "SOUL assignments: $AGENT_SOULS"
            log "Hint: SOULs may not have loaded — check that SOULS_DIR ($SOULS_DIR) is correct"
            die "agents returned identical strategy responses — SOULs may not have loaded" 5
        fi
        _seen_hashes[$_h]="$_aname"
    done
    log "personality probe ok — $AGENTS distinct strategies confirmed"
fi

# ----- 9. Emit the token (only thing on stdout) --------------------------
printf '%s\n' "$token"
