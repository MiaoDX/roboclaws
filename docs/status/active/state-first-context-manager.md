# State-First Context Manager

## Route
- Source plan: `docs/plans/2026-09-01-state-first-context-manager.md`
- Mode: durable execution via GSD milestone `v1.99`
- Scope: phases 1-4

## Current State
- Phases 1-3 complete: typed snapshots/checkpoints, bounded pre-call assembly,
  and checkpoint continuation semantics are implemented and verified.
- Phase 4 local proof complete: real Grounding DINO MapBuild and automated
  desktop/mobile operator-console QA pass.
- Latest DINO input recheck passes on both direct and SDK routes. Three fresh
  SDK MapBuild runs using `minimax-responses` (`MiniMax-M3`),
  `kimi-openai-chat` (`kimi-k2.7-code`), and `mimo-responses` (`mimo`) all
  completed with exit status 0, zero model-service failures/retries, seven
  successful Grounding DINO events, and `private_truth_included=false`. Their
  `completion_status=failed` values are the no-target MapBuild checker result,
  not a DINO/provider/input failure. MiMo's largest provider-reported input was
  96,350 tokens against the configured 96,000-token hard limit; the provider
  accepted that final call, so this is an accounting/headroom caveat rather
  than a reproduced overflow. MiniMax peaked at 81,003 tokens. Kimi's span
  usage was available in the raw event artifact but not aggregated into
  `context_metrics` (`span_usage_missing`), with its observed generation spans
  staying below 77,299 tokens.
- Phase 4 focused eval remains partial because of two pre-existing out-of-scope
  failures: a missing historical fixture and one direct-runner behavior row.

## Proven Evidence
- Implementation commits: `5f5727a8`, `47e55fc6`, `45bae24e`, `9212dad2`,
  `d9c0e548`, `c3ec03c5`, `89077e75`, `a3fced62`, `b3199b6d`, `c3e0efd4`.
- Focused route/context/privacy/digest and camera/DINO/operator/Agibot suites pass.
- Full standalone pytest has only three failures, all from the same absent
  historical eval-evolution fixture named below.
- DINO and browser proof: `.planning/phases/04-route-proof-and-rollout/04-LIVE-PROOF.md`.
- Eval packet: `output/eval-harness/20260902T053524Z/`.
- Latest input recheck: `output/state-first-context-manager/dino-sdk-input-recheck/0902_1641/seed-11/`.
- Provider rechecks: `output/state-first-context-manager/provider-recheck-minimax/0902_1651/seed-13/`,
  `output/state-first-context-manager/provider-recheck-kimi/0902_1654/seed-13/`,
  and `output/state-first-context-manager/provider-recheck-mimo/0902_1703/seed-13/`.

## Next Action
No state-first implementation repair is indicated. The old MiMo context
failure did not reproduce. Keep the MiMo accounting/headroom caveat visible
and separately prioritize or explicitly waive the historical fixture and
unmanaged direct-runner failures before calling the canonical focused eval gate
passing.

## No-Touch Scope
Do not publish a durable baseline, substitute providers/lanes, alter public
MCP/launch contracts, or modify unrelated historical eval artifacts under this
plan.
