# Canonical agent and CI tasks.

set working-directory := '..'
set positional-arguments

# Prevent namespace-only invocation from running the first public recipe.
[private]
default:
    @just --list agent

# Run the single required local/CI gate.
verify:
    #!/usr/bin/env bash
    set -euo pipefail
    .venv/bin/ruff check .
    .venv/bin/ruff format --check .
    .venv/bin/python scripts/dev/check_python_quality_ratchet.py
    .venv/bin/python scripts/dev/check_architecture_import_graph.py
    git diff --check
    ROBOCLAWS_PYTEST_CLEAR_PROVIDER_ENV=1 ./scripts/dev/run_pytest_standalone.sh \
      -m "not local and not slow" -q --durations=5
    ./scripts/dev/run_pytest_standalone.sh -q \
      tests/contract/reports/test_molmo_cleanup_report_*.py \
      tests/contract/reports/test_molmo_cleanup_artifact_report.py

# Run a repo-native eval suite.
eval *overrides:
    @exec .venv/bin/python -m roboclaws.evals.cli "$@"
