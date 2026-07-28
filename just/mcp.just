# Roboclaws MCP lifecycle helpers for household agent-server runs.

set working-directory := '..'

default:
    @just --list mcp

server_dir := ".tmp/roboclaws-mcp"
server_pid_file := ".tmp/roboclaws-mcp/server.pid"
server_log_file := ".tmp/roboclaws-mcp/server.log"
server_url_file := ".tmp/roboclaws-mcp/server.url"

_wait_for_port host port:
    #!/usr/bin/env bash
    set -euo pipefail

    for _ in {1..80}; do
      if (echo > /dev/tcp/"{{host}}"/"{{port}}") >/dev/null 2>&1; then
        echo "==> MCP server is listening on {{host}}:{{port}}" >&2
        exit 0
      fi
      sleep 0.25
    done
    echo "error: MCP endpoint not ready at {{host}}:{{port}}" >&2
    exit 1

up server="household-world" host="127.0.0.1" port="18788" output_dir=".tmp/roboclaws-mcp/run":
    #!/usr/bin/env bash
    set -euo pipefail
    server="{{server}}"

    if [[ ! -x .venv/bin/python ]]; then
      echo "error: .venv/bin/python not found — run 'uv sync --extra dev' first" >&2
      exit 1
    fi

    if [[ "$server" != "household-world" ]]; then
      echo "error: unsupported MCP server '$server' (expected household-world)" >&2
      exit 1
    fi

    mkdir -p "{{server_dir}}"

    if [[ -f "{{server_pid_file}}" ]]; then
      existing_pid="$(cat "{{server_pid_file}}" || true)"
      if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
        mcp_url="http://{{host}}:{{port}}/mcp"
        printf '%s\n' "$mcp_url" > "{{server_url_file}}"
        just mcp::_kickoff_banner "$mcp_url" "$server" >&2
        echo "$mcp_url"
        exit 0
      fi
    fi

    echo "==> starting roboclaws MCP server (server=$server, host={{host}}, port={{port}})" >&2
    server_args=(.venv/bin/python -m roboclaws.cli.agent_server "$server" --host "{{host}}" --port "{{port}}" --output-dir "{{output_dir}}")
    "${server_args[@]}" > "{{server_log_file}}" 2>&1 &
    SERVER_PID=$!
    printf '%s\n' "$SERVER_PID" > "{{server_pid_file}}"

    just mcp::_wait_for_port "{{host}}" "{{port}}" || {
      echo "error: failed to start MCP server" >&2
      cat "{{server_log_file}}" >&2
      exit 1
    }

    mcp_url="http://{{host}}:{{port}}/mcp"
    printf '%s\n' "$mcp_url" > "{{server_url_file}}"
    just mcp::_kickoff_banner "$mcp_url" "$server" >&2
    echo "$mcp_url"

_kickoff_banner url server="household-world":
    #!/usr/bin/env bash
    echo "==> roboclaws MCP ready at {{url}}"
    echo "==> Server: {{server}}"
    echo "==> Use the task skill and public household MCP tools for the selected run."

down:
    #!/usr/bin/env bash
    set -euo pipefail

    echo "==> stopping roboclaws MCP server" >&2

    if [[ -f "{{server_pid_file}}" ]]; then
      server_pid="$(cat "{{server_pid_file}}" || true)"
      if [[ "$server_pid" =~ ^[0-9]+$ ]] && kill -0 "$server_pid" 2>/dev/null; then
        echo "==> stopping tracked roboclaws MCP server (pid=$server_pid)" >&2
        if ! kill "$server_pid" 2>/dev/null; then
          if kill -0 "$server_pid" 2>/dev/null; then
            owner="$(ps -p "$server_pid" -o user= 2>/dev/null | tr -d ' ' || echo '?')"
            echo "==> ERROR: cannot signal tracked pid=$server_pid (owner=$owner) — permission denied; try \`sudo kill $server_pid\`" >&2
          fi
        fi
        wait "$server_pid" 2>/dev/null || true
      else
        echo "==> no live tracked roboclaws MCP server for pid=$server_pid" >&2
      fi
      rm -f "{{server_pid_file}}"
    else
      echo "==> no tracked roboclaws MCP pid file found" >&2
    fi

    # Backstop: reap any orphan roboclaws MCP server processes that lost their
    # PID file (crash, disk wipe, manual rm, recipe family switch).
    if command -v pgrep >/dev/null 2>&1; then
      orphan_pattern='python[^ ]*[ ].*((-m[ ]+)?roboclaws[.]cli[.]agent_server)'
      orphan_pids="$(pgrep -f "$orphan_pattern" || true)"
      if [[ -n "$orphan_pids" ]]; then
        while IFS= read -r orphan_pid; do
          [[ -z "$orphan_pid" ]] && continue
          if kill "$orphan_pid" 2>/dev/null; then
            orphan_cmd="$(ps -p "$orphan_pid" -o comm= 2>/dev/null || echo python)"
            echo "==> reaped orphan roboclaws MCP process (pid=$orphan_pid, cmd=$orphan_cmd)" >&2
          elif kill -0 "$orphan_pid" 2>/dev/null; then
            orphan_owner="$(ps -p "$orphan_pid" -o user= 2>/dev/null | tr -d ' ' || echo '?')"
            echo "==> ERROR: cannot kill orphan pid=$orphan_pid (owner=$orphan_owner) — permission denied; try \`sudo kill $orphan_pid\`" >&2
          fi
        done <<< "$orphan_pids"
      fi
    fi

    rm -f "{{server_log_file}}" "{{server_url_file}}"
