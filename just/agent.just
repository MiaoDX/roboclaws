# Agent-maintainer dispatchers.

set working-directory := '..'
set positional-arguments

[private]
default:
    @just --list agent

python_bin := env_var_or_default("ROBOCLAWS_DEVTOOLS_PYTHON", ".venv/bin/python")

# Run a normalized private dispatch target / agent-engine tuple.
run dispatch_target agent_engine mode="" *overrides:
    @exec {{python_bin}} -m roboclaws.cli.main agent run "$@"

# Dispatch to a private verification gate.
verify target="mock" *args:
    @exec {{python_bin}} -m roboclaws.cli.main agent verify "$@"

# Dispatch to a private harness recipe.
harness target *args:
    @exec {{python_bin}} -m roboclaws.cli.main agent harness "$@"

# Manage a household MCP server.
mcp action="up" server="household-world" host="127.0.0.1" port="18788" output_dir=".tmp/roboclaws-mcp/run":
    @exec {{python_bin}} -m roboclaws.cli.main agent mcp "$@"

# Manage the OpenClaw Gateway lifecycle.
gateway action="up" token_file=".openclaw-token" provider="kimi" agents="2":
    @exec {{python_bin}} -m roboclaws.cli.main agent gateway "$@"

# Run a repo-native eval suite.
eval *overrides:
    @exec {{python_bin}} -m roboclaws.evals.cli "$@"
