# Agent-maintainer dispatchers.

set working-directory := '..'
set positional-arguments

[private]
default:
    @just --list agent

python_bin := env_var_or_default("ROBOCLAWS_DEVTOOLS_PYTHON", ".venv/bin/python")

# Dispatch to a private verification gate.
verify target="mock" *args:
    #!/usr/bin/env bash
    set -euo pipefail
    target="$1"
    shift
    if ! just --show "verify::${target}" >/dev/null 2>&1; then
      echo "error: unsupported verify target '$target'" >&2
      exit 1
    fi
    command=(just "verify::${target}" "$@")
    if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
      printf 'just'
      printf '\t%s' "${command[@]:1}"
      printf '\n'
      exit 0
    fi
    exec "${command[@]}"

# Dispatch to a private harness recipe.
harness target *args:
    #!/usr/bin/env bash
    set -euo pipefail
    target="$1"
    shift
    if ! just --show "harness::${target}" >/dev/null 2>&1; then
      echo "error: unsupported harness target '$target'" >&2
      exit 1
    fi
    command=(just "harness::${target}" "$@")
    if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
      printf 'just'
      printf '\t%s' "${command[@]:1}"
      printf '\n'
      exit 0
    fi
    exec "${command[@]}"

# Manage a household MCP server.
mcp action="up" server="household-world" host="127.0.0.1" port="18788" output_dir=".tmp/roboclaws-mcp/run":
    #!/usr/bin/env bash
    set -euo pipefail
    action="$1"
    case "$action" in
      up) command=(just mcp::up "$2" "$3" "$4" "$5") ;;
      down) command=(just mcp::down) ;;
      *) echo "error: unsupported mcp action '$action' (expected up|down)" >&2; exit 1 ;;
    esac
    if [[ "${ROBOCLAWS_JUST_TRACE:-}" == "1" ]]; then
      printf 'just'
      printf '\t%s' "${command[@]:1}"
      printf '\n'
      exit 0
    fi
    exec "${command[@]}"

# Run a repo-native eval suite.
eval *overrides:
    @exec {{python_bin}} -m roboclaws.evals.cli "$@"
