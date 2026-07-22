# Local Runtime Reference

This page holds the small amount of local runtime setup that normal demo users
need. The rule is:

```text
Normal users configure keys only; command shape controls behavior.
```

## Provider Keys

Copy `.env.example` to `.env`, then fill only the keys you have:

```bash
KIMI_API_KEY=        # Kimi / Moonshot
MIMO_TP_KEY=        # MiMo
NV_API_KEY=          # NVIDIA NIM, optional

XM_LLM_BASE_URL=https://api.llm.mioffice.cn/v1  # Internal multi-model aggregator
XM_LLM_API_KEY=      # SDK mimo-mify-responses key only with explicit ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses

CODEX_BASE_URL=      # Default SDK codex-router-responses Responses-compatible endpoint
CODEX_API_KEY=       # Default SDK codex-router-responses endpoint key
```

The launch recipes infer the repo-local runtime route from explicit provider
settings. OpenAI Agents SDK defaults to `codex-router-responses` and requires
`CODEX_BASE_URL` plus `CODEX_API_KEY` (`gpt-5.6-sol`, Responses API). It does not
fall back to mimo-mify-responses when `XM_LLM_API_KEY` is present. To use
mimo-mify-responses, set `ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses`
explicitly; that profile uses `XM_LLM_API_KEY`, `xiaomi/mimo-v2.5-pro`, Responses
API, and web search disabled.

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
