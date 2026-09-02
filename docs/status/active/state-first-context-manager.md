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
- Latest DINO input recheck passes on both direct and SDK routes. The SDK run
  used `openai-agents-sdk` with `kimi-openai-chat`, made 22 successful model
  calls, and fed 7 camera-grounded histories through `model_input_filter`; the
  run's `completion_status=failed` is the no-target MapBuild checker result,
  not a DINO/provider/input failure.
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

## Next Action
No state-first implementation repair is indicated. Separately prioritize or
explicitly waive the historical fixture and unmanaged direct-runner failures
before calling the canonical focused eval gate passing.

## No-Touch Scope
Do not publish a durable baseline, substitute providers/lanes, alter public
MCP/launch contracts, or modify unrelated historical eval artifacts under this
plan.
