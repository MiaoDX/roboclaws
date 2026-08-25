# ADR-0150: Use Opik As The Sole External Observability Backend

Status: Accepted

Date: 2026-08-25

## Context

Roboclaws previously maintained Phoenix for traces and Experiments plus a
custom Eval Harness HTML companion. A reviewed Opik 2.2.36 Dashboard proved the
required runtime hierarchy, Dataset/Experiment projection, score display,
privacy, idempotency, and retained-data restart behavior. Keeping all three
surfaces would duplicate deployment, code, and operator workflows.

## Decision

Opik is the sole supported external observability backend and human browser
surface. Runtime traces and canonical eval evidence project to exactly
`roboclaws-runtime` and `roboclaws-eval` through one loopback base origin,
`ROBOCLAWS_OPIK_ENDPOINT`. The explicit LAN overlay exposes only the web UI.

ADR-0149 remains authoritative for the one-way, fail-open privacy boundary.
Local JSON, Markdown, run artifacts, graders, and human promotion decisions are
canonical. Opik owns no execution, evaluation, ranking, or authorization
policy. Projection never invents traces for Dataset-only evidence.

Phoenix deployment/code and the Eval Harness HTML companion are retired without
compatibility aliases or dual-write. Retained `output/phoenix/` and
`output/opik-poc/` data remain inactive historical evidence.

## Consequences

- Maintainers use one Dashboard, Dataset, Experiment, and trace browser.
- Opik failure can reduce observability but cannot change product/eval results.
- Dashboard reconciliation and repair remain explicit bounded operations.
- Opik 2.2.36 Dashboard mobile review may require horizontal navigation; the
  canonical JSON/Markdown artifacts remain portable review surfaces.

## Rejected Alternatives

- Retain Phoenix plus the companion, which preserves duplicate operations.
- Permanent Phoenix/Opik dual-write, which violates the one-backend goal.
- Move canonical graders or promotion into Opik, which reverses the one-way
  diagnostic boundary.
