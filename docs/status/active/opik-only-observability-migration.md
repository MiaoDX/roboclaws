# Opik-Only Observability Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-08-25-opik-only-observability-migration.md`
- Control plane: root Codex session for the active host goal
- Project-status writer: root Codex session
- Latest user intent: execute the approved plan with `intuitive-flow`
- Current slice: Stage 1 Dashboard reconciliation and runtime live routing proof
- Last proven evidence: automatic local suite projection is `ready`; reviewed candidate projection
  is `ready` with 65 Dataset items, 25 native traces/Experiments, 40 Dataset-only rows, 56 scores,
  zero privacy findings, and a second replay with zero creations and unchanged identity digest.
  The 60-second invocation deadline recovered a partial timeout without changing source evidence.
- Completed slices: execution approval/state; replacement-seam inventory; production-shaped Opik
  runtime sink; package-owned projection; automatic suite finalization and `opik-project` repair
  route; candidate fidelity/idempotency proof.
- Next slice: add explicit idempotent Dashboard reconciliation, then run live product and EvalTrial
  routing under `roboclaws-runtime` and `roboclaws-eval` with disabled/unavailable proofs.
- Next proof: Dashboard schema/API drift contract, live runtime hierarchy, live EvalTrial project
  routing, and restart/loopback ingestion checks.
- Stop condition: all plan acceptance and verification gates pass, or a named circuit breaker
  requires user re-approval.
- No-touch scope: provider/evaluator/promotion/simulator/robot behavior; private artifact upload;
  public/authenticated/shared Opik; Phoenix and pilot data deletion.
- Parked work: broad Phoenix history, Opik upgrade, authentication/TLS, backup service design,
  optional Dashboard polish, destructive retained-data cleanup.
