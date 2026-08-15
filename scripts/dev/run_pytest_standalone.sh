#!/usr/bin/env bash
# Run pytest inside a minimal environment to avoid host-global Python contamination
# (e.g., ROS workspaces in PYTHONPATH on systems with ROS jazzy installed).
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
    SOURCE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$SOURCE_DIR/$SOURCE"
done
REPO_ROOT="$(cd "$(dirname "$SOURCE")/../.." && pwd)"
PYTEST_BIN="${PYTEST_BIN:-$REPO_ROOT/.venv/bin/pytest}"

if [[ ! -x "$PYTEST_BIN" ]]; then
    echo "run_pytest_standalone: missing repo pytest at $PYTEST_BIN" >&2
    echo "run_pytest_standalone: run 'uv sync --extra dev' in this checkout" >&2
    exit 1
fi
PYTEST_BIN_DIR="$(cd "$(dirname "$PYTEST_BIN")" && pwd)"
JUST_BIN="$(command -v just 2>/dev/null || true)"
JUST_BIN_DIR="${JUST_BIN:+$(dirname "$JUST_BIN")}"
UV_BIN="$(command -v uv 2>/dev/null || true)"
UV_BIN_DIR="${UV_BIN:+$(dirname "$UV_BIN")}"
ROBOCLAWS_PYTHON="${ROBOCLAWS_PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$ROBOCLAWS_PYTHON" ]]; then
    echo "run_pytest_standalone: missing repo Python at $ROBOCLAWS_PYTHON" >&2
    echo "run_pytest_standalone: run 'uv sync --extra dev' in this checkout" >&2
    exit 1
fi

if [[ "${ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV:-}" == "1" ]]; then
    KIMI_API_KEY=""
    KIMI_OPENAI_BASE_URL=""
    CODEX_RESPONSES_BASE_URL=""
    CODEX_RESPONSES_API_KEY=""
    CODEX_RESPONSES_MODEL=""
    MIMO_RESPONSES_BASE_URL=""
    MIMO_RESPONSES_API_KEY=""
    MIMO_RESPONSES_MODEL=""
    MM_BASE_URL=""
    MM_API_KEY=""
    OPENAI_API_KEY=""
    ANTHROPIC_API_KEY=""
fi

env -i \
  PATH="$PYTEST_BIN_DIR:$REPO_ROOT/.venv/bin${JUST_BIN_DIR:+:$JUST_BIN_DIR}${UV_BIN_DIR:+:$UV_BIN_DIR}:/usr/bin:/bin" \
  HOME="${HOME:-$REPO_ROOT}" \
  ROBOCLAWS_PYTHON="${ROBOCLAWS_PYTHON-}" \
  KIMI_API_KEY="${KIMI_API_KEY-}" \
  KIMI_OPENAI_BASE_URL="${KIMI_OPENAI_BASE_URL-}" \
  CODEX_RESPONSES_BASE_URL="${CODEX_RESPONSES_BASE_URL-}" \
  CODEX_RESPONSES_API_KEY="${CODEX_RESPONSES_API_KEY-}" \
  CODEX_RESPONSES_MODEL="${CODEX_RESPONSES_MODEL-}" \
  MIMO_RESPONSES_BASE_URL="${MIMO_RESPONSES_BASE_URL-}" \
  MIMO_RESPONSES_API_KEY="${MIMO_RESPONSES_API_KEY-}" \
  MIMO_RESPONSES_MODEL="${MIMO_RESPONSES_MODEL-}" \
  MM_BASE_URL="${MM_BASE_URL-}" \
  MM_API_KEY="${MM_API_KEY-}" \
  OPENAI_API_KEY="${OPENAI_API_KEY-}" \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY-}" \
  ROBOCLAWS_PHOENIX_INTEGRATION_ENDPOINT="${ROBOCLAWS_PHOENIX_INTEGRATION_ENDPOINT-}" \
  CI="${CI:-}" \
  GITHUB_ACTIONS="${GITHUB_ACTIONS:-}" \
  "$PYTEST_BIN" "$@"
