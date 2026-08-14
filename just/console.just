# Standalone Codex operator console.

set working-directory := '..'

# Prevent namespace-only invocation from running the first public recipe.
[private]
default:
    @just --list console

# Run the standalone local operator console.
run host="0.0.0.0" port="8765":
    @exec .venv/bin/python -m roboclaws.operator_console --host "{{host}}" --port "{{port}}" --repo-root "$PWD"
