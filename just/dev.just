# Dev workflow — git hooks, pytest layers, repo-wide self-check.
#
# Test split invariant:
#   - test-fast        : tight-loop confidence gate; opt into it from
#                        pre-commit with FORCE_TESTS=1.
#   - test-unit        : fast isolated public-API behavior tests.
#   - test-contract    : public schema/tool/report/recipe compatibility tests.
# Local and slow tests are also excluded from commit-time tight loops. Run them
# explicitly when a change touches those contracts.

set working-directory := '..'
set positional-arguments

standalone_pytest := "./scripts/dev/run_pytest_standalone.sh"

# Default: list module recipes (avoids accidentally rewiring git hooks).
default:
    @just --list dev

# Show whether this host appears to be on the office work network.
[group('network')]
network-status:
    @bash scripts/dev/network_status.sh

model-provider-health mode="all" *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    args=("$@")
    override_args=("${args[@]:1}")
    python_bin="${ROBOCLAWS_DEVTOOLS_PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
      if [[ -x ".venv/bin/python" ]]; then
        python_bin=".venv/bin/python"
      elif command -v python3 >/dev/null 2>&1; then
        python_bin="python3"
      else
        python_bin="python"
      fi
    fi
    exec "$python_bin" scripts/dev/check_model_providers.py --mode "{{mode}}" "${override_args[@]}"

model-matrix-benchmark *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    python_bin="${ROBOCLAWS_DEVTOOLS_PYTHON:-}"
    if [[ -z "$python_bin" ]]; then
      if [[ -x ".venv/bin/python" ]]; then
        python_bin=".venv/bin/python"
      elif command -v python3 >/dev/null 2>&1; then
        python_bin="python3"
      else
        python_bin="python"
      fi
    fi
    exec "$python_bin" scripts/dev/benchmark_model_matrix.py "$@"

worktree-preflight *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    python_bin=".venv/bin/python"
    if [[ ! -x "$python_bin" && -n "${ROBOCLAWS_BASELINE_REPO:-}" ]]; then
      python_bin="${ROBOCLAWS_BASELINE_REPO%/}/.venv/bin/python"
    fi
    if [[ ! -x "$python_bin" ]]; then
      echo "error: missing repo Python at .venv/bin/python; run 'uv sync --extra dev'" >&2
      echo "       or run: ROBOCLAWS_BASELINE_REPO=/path/to/main just dev::worktree-bootstrap" >&2
      exit 1
    fi
    "$python_bin" scripts/dev/check_worktree_readiness.py "$@"

worktree-bootstrap *flags:
    @scripts/dev/bootstrap_worktree_env.sh "$@"

install-hooks:
    @git config core.hooksPath .githooks
    @echo "==> git hooks installed (core.hooksPath = .githooks)"
    @echo "    pre-commit : ruff + scoped pytest (FORCE_TESTS=1 for full fast pytest)"
    @echo "    bypass     : git commit --no-verify   or   SKIP_TESTS=1 git commit"

uninstall-hooks:
    -@git config --unset core.hooksPath
    @echo "==> git hooks uninstalled (core.hooksPath reset)"

test kind="all":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{kind}}" in
      fast)
        ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV=1 {{standalone_pytest}} \
          -m "not local and not slow" -q --durations=5
        ;;

      unit)
        ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV=1 {{standalone_pytest}} -m unit -q --durations=5
        ;;

      contract)
        ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV=1 {{standalone_pytest}} -m contract -q --durations=5
        ;;

      all)
        {{standalone_pytest}} -q --durations=5
        ;;

      *)
        echo "error: unknown test kind '{{kind}}' (expected fast|unit|contract|all)" >&2
        exit 1
        ;;
    esac
