# Retired Docker Coding-Agent Household MCP Driver

This page is historical reference for the retired Docker-backed
`codex-cli` / `claude-code` household routes. Current public live-agent runs use
`agent_engine=openai-agents-sdk`; deterministic local proof uses
`agent_engine=direct-runner`. Do not use the commands below as current launch
guidance.

## Run Through The Public Catalog

Install the repo environment once:

```bash
uv sync --extra dev
```

Use the current SDK route for normal live runs:

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=openai-agents-sdk provider_profile=codex-router-responses evidence_lane=world-public-labels
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco agent_engine=openai-agents-sdk provider_profile=codex-router-responses prompt="find something useful to drink"
```

For map-only work:

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=map-build agent_engine=openai-agents-sdk provider_profile=codex-router-responses evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
```

The launch catalog resolves world, backend, intent, provider profile, goal
contract, MCP server type, artifact paths, and checker policy before the lower
recipes run.

## Credentials And Runtime

Copy `.env.example` to `.env`, then fill the keys you have. OpenAI Agents SDK
defaults to `codex-router-responses` and requires `CODEX_BASE_URL` plus
`CODEX_API_KEY`. To use `mimo-mify-responses`, set
`ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses` explicitly with
`XM_LLM_API_KEY`; this route uses `xiaomi/mimo-v2.5-pro`. To use MiniMax's Responses-compatible route, set
`ROBOCLAWS_PROVIDER_PROFILE=minimax-responses` with `MM_API_KEY`; it defaults to
`MiniMax-M3`. M3 is the only current MiniMax model in the active route catalog.

Provider/model metadata is centralized in
`roboclaws/agents/provider_registry.py`. The launch catalog, operator console,
OpenAI Agents SDK runner, and shell helpers use that registry for default
models, required env keys, wire API, route health, and route capabilities.
Evidence-lane gating stays separate from provider metadata: `camera-raw-fpv`
requires model image input plus verified runtime image transport, while
structured lanes such as `world-public-labels` and `camera-grounded-labels`
can use text-only routes. MiMo defaults use only Mify Pro. The token-plan and
Inside profiles remain addressable for explicit diagnostics but are excluded
from default selection; the Inside `mimo-1000` channel is unavailable. Kimi
OpenAI Chat defaults to `kimi-k2.7-code`; keep
that canonical model id because the provider accepts and echoes arbitrary K2.7
suffixes. OpenAI Agents SDK routes use
`ROBOCLAWS_OPENAI_AGENTS_THINKING_MODE=default|enabled|disabled`. Responses
routes map this to the OpenAI `reasoning` body, while generic Chat-compatible
routes map it to the `thinking` body. Kimi K2.7 Code routes are thinking-only
and do not send the old explicit `thinking` body. Live route verdicts are
recorded in
`docs/human/model-route-verdicts.yaml`.

The old Docker-backed Codex/Claude helper route has been removed. Use
`just run::surface ... agent_engine=openai-agents-sdk` for live provider runs
and `just agent::mcp up|down` for manual MCP server debugging.

## MCP Lifecycle

The private MCP helper is available for manual debugging:

```bash
just agent::mcp up household-world 127.0.0.1 18788 output/debug/household-mcp
just mcp::down
```

The server URL is:

```text
http://127.0.0.1:18788/mcp
```

Normal live-agent runs start and stop the appropriate server themselves. The
private implementation entrypoint is `python -m roboclaws.cli.agent_server`;
the maintainer facade uses the canonical `household-world` dispatch target and
passes task intent through launch context.

## Artifacts

Runs write under `output/` and print the exact run directory. Important files:

- `trace.jsonl` records public MCP/tool events.
- `run_result.json` records public run state and checker inputs.
- `goal_contract.json` records the normalized launch goal.
- `runtime_metric_map.json` is present for map-build runs.
- `report.html` is the human review surface.

Private evaluator truth must not be added to agent-facing inputs or MCP profile
metadata. Reports may display public and private sections separately when the
checker owns that boundary.
