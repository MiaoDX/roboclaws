# Provider Benchmark Ledger

Weekly human-readable summaries of model provider speed checks live here.
Raw benchmark artifacts stay local under `output/dev/model-matrix/<timestamp>/`;
this folder tracks the stable comparison, command, and caveats worth carrying
between weeks.

## Cadence

- Update once per week, usually Monday, using an ISO week filename such as
  `2026-W26.md`.
- Keep one row per current provider route that we actively care about.
- Record p50 health latency, p50 first-token latency, p50 throughput latency,
  throughput tokens/sec, artifact path, and short notes.
- Do not treat one run as a route health promotion by itself. Route health still
  lives in `docs/human/model-route-verdicts.yaml`.

## Standard Run

Prefer the current core-provider case set instead of the full catalog. The full
catalog includes probe rows and unsupported wire variants that can spend minutes
waiting on slow provider timeouts.

```bash
for case_id in \
  'codex-router-responses:gpt-5.5:responses' \
  'mimo-mify-responses:xiaomi-mimo-v2.5:openai-responses' \
  'minimax-responses:MiniMax-M3:responses' \
  'mimo-token-plan:mimo-v2.5:openai-chat' \
  'mimo-inside-openai-chat:mimo-1000:openai-chat' \
  'kimi:kimi-k2.7-code:chat' \
  'nvidia:nemotron-nano-vl:chat'
do
  .venv/bin/python scripts/dev/benchmark_model_matrix.py \
    --case "$case_id" \
    --layer health --layer first-content --layer throughput \
    --iterations 2 --timeout-s 90 \
    --max-tokens 128 \
    --first-content-max-tokens 128 \
    --throughput-max-tokens 1024
done
```

## Reading Results

- `health p50` is a tiny "reply ok" non-stream request.
- `first token p50` is the streaming first-content latency when available.
- `throughput tok/s` is based on provider usage when present, otherwise the
  benchmark's measured token estimate.
- Compare providers within the same weekly run. Cross-week numbers are useful
  for trend direction, not precise ranking.
