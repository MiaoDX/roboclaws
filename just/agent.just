# Canonical agent and CI tasks.

set working-directory := '..'
set positional-arguments

# Prevent namespace-only invocation from running the first public recipe.
[private]
default:
    @just --list agent

# Run the complete gate locally, or one of the two disjoint CI shards.
verify shard="all":
    #!/usr/bin/env bash
    set -euo pipefail
    shard="$1"
    sampler_paths=(tests/unit/worlds/molmospaces tests/unit/operator_console/test_scene_sampler_readiness_export.py)
    pytest_args=()
    case "$shard" in
      all) ;;
      core)
        for path in "${sampler_paths[@]}"; do pytest_args+=("--ignore=$path"); done
        ;;
      molmospaces) pytest_args+=("${sampler_paths[@]}") ;;
      *) echo "Unknown verification shard: $shard (expected all, core, molmospaces)" >&2; exit 2 ;;
    esac
    if [[ "$shard" != molmospaces ]]; then
      .venv/bin/ruff check .
      .venv/bin/ruff format --check .
      .venv/bin/python scripts/dev/check_python_quality_ratchet.py
      .venv/bin/python scripts/dev/check_architecture_import_graph.py
      git diff --check
    fi
    ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV=1 ./scripts/dev/run_pytest_standalone.sh \
      -m "not local and not slow" -q --durations=10 "${pytest_args[@]}"
    if [[ "$shard" != molmospaces ]]; then
      ./scripts/dev/run_pytest_standalone.sh -q \
        tests/contract/reports/test_molmo_cleanup_report_*.py \
        tests/contract/reports/test_molmo_cleanup_artifact_report.py
    fi

# Run a repo-native eval suite.
eval *overrides:
    @exec .venv/bin/python -m roboclaws.evals.cli "$@"
