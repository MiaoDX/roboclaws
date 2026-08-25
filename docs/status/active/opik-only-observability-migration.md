# Opik-Only Observability Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-08-25-opik-only-observability-migration.md`
- Control plane: root Codex session for the active host goal
- Project-status writer: root Codex session
- Latest user intent: execute the approved plan with `intuitive-flow`
- Current slice: complete; execute gate and Opik projection closeout passed
- Last proven evidence: automatic local suite projection is `ready`; reviewed candidate projection
  is `ready` with 65 Dataset items, 25 native traces/Experiments, 40 Dataset-only rows, 56 scores,
  zero privacy findings, and a second replay with zero creations and unchanged identity digest.
  The 60-second invocation deadline recovered a partial timeout without changing source evidence.
  Dashboard reconciliation preserved stable ID `01a03341-1292-74dd-9699-ff57164bf346` across two
  passes. Live product attempt 2 created one `roboclaws-runtime` trace with 255 spans, one root and
  254 parented spans; exporter status was ready with 255 exported, zero failed, and zero dropped.
  The live cleanup EvalTrial bundle produced three ready exporters with zero failures/drops and a
  ready projection containing 3 Dataset items, 3 Experiment items/traces, 686 spans, and 15 scores.
- Completed slices: execution approval/state; replacement-seam inventory; production-shaped Opik
  runtime sink; package-owned projection; automatic suite finalization and `opik-project` repair
  route; candidate fidelity/idempotency proof.
  route; candidate fidelity/idempotency proof; stable Dashboard reconciliation; live runtime
  hierarchy and closed-project routing.
  hierarchy and closed-project routing; live EvalTrial routing and automatic/repair projection.
- Next slice: none; remove this terminal capsule after committing canonical closeout.
- Next proof: final status, process, and stale-reference audit.
- Blocker: none.
- Stop condition: all plan acceptance and verification gates pass, or a named circuit breaker
  requires user re-approval.
- No-touch scope: provider/evaluator/promotion/simulator/robot behavior; private artifact upload;
  public/authenticated/shared Opik; Phoenix and pilot data deletion.
- Parked work: broad Phoenix history, Opik upgrade, authentication/TLS, backup service design,
  optional Dashboard polish, destructive retained-data cleanup.
