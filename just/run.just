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

# Prevent namespace-only invocation from running the first public recipe.
[private]
default:
    @just --list run

# Run a canonical surface/intent route through explicit launch axes.
surface *overrides:
    @exec .venv/bin/python -m roboclaws.cli.main run surface "$@"
