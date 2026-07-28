# Human-facing surface grammar.
#
# Canonical form:
#   just run::surface surface=<surface> agent_engine=<engine> [world=<world>]
#     [backend=<backend>] [intent=<intent>] [provider_profile=<profile>]
#     [key=value ...]
#
# Surfaces:
#   household-world | planner-proof
#
# Intents:
#   cleanup | open-ended | map-build | planner-proof

set working-directory := '..'
set positional-arguments

[private]
default:
    @just --list run

# Run a canonical surface/intent route through explicit launch axes.
surface *overrides:
    #!/usr/bin/env bash
    set -euo pipefail
    exec .venv/bin/python -m roboclaws.cli.main run surface "$@"
