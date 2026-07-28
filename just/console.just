# Standalone Codex operator console.

set working-directory := '..'

[private]
default:
    @just --list console

# Run the standalone local operator console.
run host="0.0.0.0" port="8765":
    #!/usr/bin/env bash
    set -euo pipefail
    exec .venv/bin/python -m roboclaws.operator_console --host "{{host}}" --port "{{port}}" --repo-root "$PWD"
