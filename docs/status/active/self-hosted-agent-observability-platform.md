# Self-Hosted Agent Observability Platform

Owner/session: `/root` task control plane
Started: 2026-08-07
State: ACTIVE

## Scope

Implement the approved self-hosted observability plan through Intuitive Flow,
starting with the Phase 0 contracts and GSD handoff. Preserve all named privacy,
live-provider, production-adapter, deployment, and real-robot stop gates.

## Source Of Truth

- Plan: `docs/plans/2026-08-06-self-hosted-agent-observability-platform.md`
- Host goal: implement the plan via `intuitive-flow`

## Current Slice

Phase 1 is complete through both live wire families. On 2026-08-08 the user
selected Phoenix and approved the simplified topology: one opt-in Phoenix
container on the local developer workstation, loopback-only and outside robot
runtime processes. Shared deployment, cross-machine ingress, authentication
gateways, backup services, and production cluster sizing are out of scope.

## Last Proven Evidence

- Planning-loop review and focused eval recommendation are recorded in the plan.
- User explicitly requested implementation on 2026-08-07.
- Existing `.planning/STATE.md` reports no active GSD execution phase.
- Phase 0 contract, ADR-0149, lifecycle router, privacy denial fixtures, and
  caller/parity inventory are complete.
- Independent focused proof passed: Ruff, format, 39 telemetry/runtime/driver
  tests, and diff hygiene. The worker also passed the full agents unit suite.
- GSD handoff was unavailable because `$gsd-ingest-docs` and `$gsd-plan-phase`
  are not installed; bounded one-phase Intuitive Flow workers are the active
  fallback.
- The changed-code review retains `DeterministicProjectionProcessor` as the fake
  fixture and adds the real opt-in, run-owned `PhoenixTelemetryAdapter` behind
  registration-once local routing.
- Independent Phase 1 proof passes lock/sync, repo-wide Ruff/format, the
  agent/eval focused suites, and healthy Phoenix 11.20.0 ingestion.
- The live eval subprocess now preserves canonical suite/sample/trial,
  repetition, and launch-axis identity through a closed internal envelope; the
  normal product path remains unchanged and the adapter overwrites protected
  run/engine/provider fields from the request.
- The post-audit repository-wide standalone pytest suite passes at 100%. Its
  only output beyond expected skips is one Pillow and one MCP-client
  deprecation warning unrelated to this change.
- Phoenix received one correlated four-span hierarchy with closed run/session
  identity and zero forbidden values. Real callback work was at most 0.206031
  ms in the proof; paired deterministic SDK overhead was 0.532821%.
- Kimi Chat live proof is complete: one trace, 18 spans, closed identity, usage parity, zero raw
  sensitive values, and zero model retries.
- MiniMax Responses live proof is complete after one retained four-turn budget-failure attempt and
  one explicit eight-turn repair: the successful trace has 26 spans, closed identity, zero export
  failures/drops, and zero raw sensitive values. Model/token attributes are unavailable in the
  OpenInference projection for this route and are preserved only in the local sanitized event
  stream, without synthetic Phoenix fields.

Blocker fingerprint: none. The prior
`human_gate:phase2_phoenix_production_selection_and_topology` gate was resolved
by the 2026-08-08 local-workstation approval.

## Next Action

Implement the Phase 2 fail-open and control-path proofs for the localhost-only
topology, then continue through prompt identity, eval projection, and the
evidence-led deletion matrix.

## Next Proof

The next proof is Phoenix-disabled versus Phoenix-down product parity plus
non-loopback endpoint denial and recorded no-movement control-path separation.

## Stop Condition

Stop for any named user-review gate, material privacy/security/service/cost
choice, destructive deletion, real-robot movement, or an unresolvable locked-doc
conflict. Completion requires every plan acceptance criterion and proof.

## No-Touch Scope

- `STATUS.md` without explicit project-integrator ownership
- unrelated active capsules or existing user changes
- durable Phoenix/catalog publication before its review gate

## Parked Work

- durable local spool unless disconnected trace loss proves demand
- any shared Phoenix placement, cross-machine ingress, authentication gateway,
  backup service, or larger resource envelope
