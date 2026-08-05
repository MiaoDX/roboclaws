# Eval Evolution With OpenAI Agents SDK

- Status: `ACTIVE`
- Source plan: `docs/plans/2026-08-04-eval-evolution-agent-sdk.md`
- Control plane: root Codex session for goal `019fcf9b-eee3-7f53-865b-1d8467b790d3`
- Project-status writer: this control plane at phase checkpoints only
- Latest intent: execute the approved full five-phase plan through
  `$intuitive-flow`
- Current slice: Phase 1 Skill vertical slice
- Blocker: none
- Last proof: Phase 0 focused tests (30 passed), required eval/agent and command
  contract suites, and repo-wide Ruff/format all passed on 2026-08-05
- Completed slices: Phase 0 contracts and threat model, strict campaign/
  feedback/candidate/selection/promotion loaders, malicious boundary fixtures,
  and blocked-by-default `evolve|evolve-promote` grammar
- Next slice: implement the narrow OpenAI Agents SDK optimizer adapter and
  content-addressed Skill candidate materialization
- Next proof: Phase 1 optimizer tool-boundary and Skill candidate deterministic
  tests before any bounded live provider proof
- Stop condition: stop at every source-plan hard gate; in particular, never
  execute MCP behavior candidates live before Phase 3 malicious isolation passes
- No-touch scope: Codex CLI; automatic promotion/commit/default/baseline/catalog
  changes; public MCP tool shape; physical safety or real-robot authority
- Parked work: source-plan `Rejected Or Parked` section only
