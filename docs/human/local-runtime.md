# Local Runtime Reference

This page holds the small amount of local runtime setup that normal demo users
need. The rule is:

```text
Normal users configure keys only; command shape controls behavior.
```

## Optional Local Phoenix

Phoenix is an opt-in observability service for the developer workstation. It is
not started by Roboclaws and is not part of a robot runtime process. The
supported deployment is pinned to Phoenix 11.20.0, uses at most 2 CPU and 4 GiB
of memory, and persists data in a named local volume. Its default deployment
binds only to loopback.

```bash
./scripts/dev/validate_phoenix_deployment.sh
docker compose -f deploy/phoenix/compose.yaml up -d
```

To expose only the Phoenix web UI/API on one trusted private-LAN interface,
create the gitignored `deploy/phoenix/.env` from `.env.example`, set
`PHOENIX_LAN_BIND_HOST` to that interface's address, and start the LAN override:

```bash
docker compose \
  -f deploy/phoenix/compose.yaml \
  -f deploy/phoenix/compose.lan.yaml \
  up -d
```

The override adds `<PHOENIX_LAN_BIND_HOST>:6006`; it does not expose OTLP port
4317. Local trace export continues through `127.0.0.1:6006`. Phoenix has no
authentication or TLS in this mode, so use it only on an explicitly trusted
private network and do not bind `0.0.0.0`.

To project sanitized live OpenAI Agents SDK traces and completed eval suite
results into that service, set:

```bash
export ROBOCLAWS_PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

Roboclaws routes traces to exactly two Projects. `roboclaws-runtime` contains
normal product, operator, ad-hoc, and demo Robot Runs. `roboclaws-eval` contains
Robot Runs executed as EvalTrials. Provider, model, task, suite, sample, and
trial remain searchable trace attributes; they do not create Projects. Project
selection is not configurable.

Tracing and automatic eval result projection remain disabled when the endpoint
is unset and fail open when the local service is unavailable. Eval runs write
an adjacent `phoenix_projection.json` receipt, and the manual `phoenix-project`
command remains available for repair/backfill. A missing, partial, malformed,
or contradictory runtime/eval telemetry identity disables Phoenix export for
that run and leaves an actionable local limitation without changing product
execution. Non-loopback OTLP endpoints are rejected. Shared Phoenix ownership,
cross-machine collectors, authentication/TLS gateways, backups, larger resource
envelopes, and onboard robot deployment are not supported by this topology.

## Provider Keys

Copy `.env.example` to `.env`, then fill only the keys you have:

```bash
KIMI_OPENAI_BASE_URL=
KIMI_API_KEY=
MM_BASE_URL=
MM_API_KEY=
CODEX_RESPONSES_BASE_URL=
CODEX_RESPONSES_API_KEY=
CODEX_RESPONSES_MODEL=
MIMO_RESPONSES_BASE_URL=
MIMO_RESPONSES_API_KEY=
MIMO_RESPONSES_MODEL=
```

Every OpenAI Agents SDK launch selects `codex-responses`, `mimo-responses`,
`minimax-responses`, or `kimi-openai-chat` explicitly. Environment presence
never selects a route, and the runtime does not fall back between Responses and
Chat Completions.

Run `scripts/dev/network_status.sh` before system-provider Claude Code debugging.
Repo-local OpenAI Agents SDK provider routes are allowed; provider-specific
transport compatibility is internal to each adapter. Agent-facing work-network
restrictions and examples are documented in
[`docs/agents/operating-runbook.md`](../agents/operating-runbook.md).

For the current model/provider compatibility table, see
[`model-matrix.md`](model-matrix.md).

## Local Report Artifacts

Most demo commands write under `output/` and print the exact run directory.
Common examples:

| Run type | Typical output |
| --- | --- |
| Product household run | `output/molmo/<recipe-or-run>/<stamp>/seed-7/` or the explicit `output_dir=...` passed to `just run::surface` |
| Eval harness | `output/eval-harness/<stamp>/` |
| Eval suite | `output/evals/<suite>/<stamp>/` with eval results plus links to product run artifacts |
| Planner proof bundle | `output/molmo/planner-proof*/` |
| Historical semantic-map/cleanup roots | `output/household/semantic-map-build/<driver>-*/`, `output/household/household-cleanup/<driver>-*/` |

Each report directory is meant to be reviewable without re-running the model.
Historical roots may appear in old reports and tests, but new eval evidence
should be found through the eval-suite output and its linked product artifacts.
