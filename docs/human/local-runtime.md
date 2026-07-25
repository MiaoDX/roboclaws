# Local Runtime Reference

This page holds the small amount of local runtime setup that normal demo users
need. The rule is:

```text
Normal users configure keys only; command shape controls behavior.
```

## Provider Keys

Copy `.env.example` to `.env`, then fill only the keys you have:

```bash
KIMI_OPENAI_BASE_URL=
KIMI_API_KEY=
MM_BASE_URL=
MM_API_KEY=
CUSTOM_RESPONSES_BASE_URL=
CUSTOM_RESPONSES_API_KEY=
CUSTOM_RESPONSES_MODEL=
```

Every OpenAI Agents SDK launch selects `custom-responses`, `minimax-responses`,
or `kimi-openai-chat` explicitly. Environment presence never selects a route,
and the runtime does not fall back between Responses and Chat Completions.

Run `just dev::network-status` before validation-required maintainer workflows.
On the work network, guarded OpenClaw routes and system-provider Claude Code
remain blocked. Repo-local OpenAI Agents SDK provider routes are allowed;
provider-specific transport compatibility is internal to each adapter.
Agent-facing work-network
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
