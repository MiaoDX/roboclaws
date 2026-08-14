# Local Runtime Reference

This page holds the small amount of local runtime setup that normal demo users
need. The rule is:

```text
Normal users configure keys only; command shape controls behavior.
```

## Optional Local Phoenix

Phoenix is an opt-in observability service for the developer workstation. It is
not started by Roboclaws and is not part of a robot runtime process. The
supported deployment is pinned to Phoenix 11.20.0, binds only to loopback, uses
at most 2 CPU and 4 GiB of memory, and persists data in a named local volume.

```bash
./scripts/dev/validate_phoenix_deployment.sh
docker compose -f deploy/phoenix/compose.yaml up -d
```

To project sanitized live OpenAI Agents SDK traces into that service, set:

```bash
export ROBOCLAWS_PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces
export ROBOCLAWS_PHOENIX_PROJECT=roboclaws-local
```

Tracing remains disabled when the endpoint is unset and fails open when the
local service is unavailable. Non-loopback endpoints are rejected. Shared or
cross-machine Phoenix, authentication/TLS gateways, backups, larger resource
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
