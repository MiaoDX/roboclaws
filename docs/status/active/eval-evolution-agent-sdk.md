# Eval Evolution With OpenAI Agents SDK

- Status: `ACTIVE`
- Source plan: `docs/plans/2026-08-04-eval-evolution-agent-sdk.md`
- Control plane: root Codex session for goal `019fcf9b-eee3-7f53-865b-1d8467b790d3`
- Project-status writer: this control plane at phase checkpoints only
- Latest intent: execute the approved full five-phase plan through
  `$intuitive-flow`
- Current slice: Phase 2 MCP description-only slice
- Blocker: none
- Last proof: Phase 1 deterministic optimizer/candidate/selection/promotion
  tests, eval/agent suites, smoke/open-ended/map-build eval commands, repo-wide
  Ruff/format, and quality ratchet passed on 2026-08-05. Bounded live Skill
  campaign `output/eval-evolution/20260805-skill-smoke-v4/` completed through
  Agents SDK optimizer plus paired robot training; authoritative training
  status failed, so no holdout or promotion ran.
- Completed slices: Phase 0 contracts and threat model, strict campaign/
  feedback/candidate/selection/promotion loaders, malicious boundary fixtures,
  and blocked-by-default `evolve|evolve-promote` grammar
- Next slice: wire the Phase 2 description target into campaign materialization
  and blocked command contracts. Keep MCP behavior live execution blocked until
  Phase 3 malicious isolation passes.
- Next proof: description target identity and no-behavior-live campaign proof.
- Stop condition: stop at every source-plan hard gate; in particular, never
  execute MCP behavior candidates live before Phase 3 malicious isolation passes
- No-touch scope: Codex CLI; automatic promotion/commit/default/baseline/catalog
  changes; public MCP tool shape; physical safety or real-robot authority
- Parked work: source-plan `Rejected Or Parked` section only
