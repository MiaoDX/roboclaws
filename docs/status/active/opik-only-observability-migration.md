# Opik-Only Observability Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-08-25-opik-only-observability-migration.md`
- Control plane: root Codex session for the active host goal
- Project-status writer: root Codex session
- Latest user intent: execute the approved plan with `intuitive-flow`
- Current slice: Stage 1 suite-result mapping and automatic fail-open receipt integration
- Last proven evidence: the pinned Opik OTLP route exists at
  `/api/v1/private/otel/v1/traces`; 47 runtime/telemetry tests and eight Opik projection tests pass
  with Ruff. The runtime sink derives that route from one loopback `ROBOCLAWS_OPIK_ENDPOINT`, and
  the package-owned REST client proves deterministic replay, privacy denial, atomic receipts, and
  one invocation deadline.
- Completed slices: execution approval/state; replacement-seam inventory; production-shaped Opik
  runtime sink; pilot client/harness mapper promotion into `roboclaws.evals.opik_projection`.
- Next slice: add canonical suite-result mapping, automatic `opik_projection.json` fail-open
  receipts, and wire suite finalization plus accepted CloudML collection without changing results.
- Next proof: focused suite projection tests, disabled/unavailable/deadline receipt tests, and
  unchanged eval outcome tests.
- Stop condition: all plan acceptance and verification gates pass, or a named circuit breaker
  requires user re-approval.
- No-touch scope: provider/evaluator/promotion/simulator/robot behavior; private artifact upload;
  public/authenticated/shared Opik; Phoenix and pilot data deletion.
- Parked work: broad Phoenix history, Opik upgrade, authentication/TLS, backup service design,
  optional Dashboard polish, destructive retained-data cleanup.
