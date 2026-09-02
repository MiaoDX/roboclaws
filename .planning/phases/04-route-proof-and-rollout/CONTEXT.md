# Phase 4: Route Proof And Rollout - Context

**Gathered:** 2026-09-02
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-09-01-state-first-context-manager.md)

## Phase Boundary

Prove and roll out the shared state-first context contract across supported household routes and evidence lanes after Phases 1-3. This phase produces executable proof and rollout plans only; it does not implement runtime code.

## Locked Decisions

- Cover cleanup, MapBuild, and no-preset open-ended household SDK paths.
- Include camera-grounded/DINO inputs, operator-console use, and Agibot resolver metadata.
- Reuse the same context contract without adding a profile picker or launch axis.
- Keep `baseline` as an explicit unmanaged comparison; never silently fall back to it.
- Preserve complete traces, reports, MCP artifacts, and DINO artifacts as reviewable content-addressed evidence.
- Enforce privacy boundaries: no private scoring truth, credentials, raw prompts, or full tool payloads in model input or telemetry.
- Run deterministic tests and focused eval recommendation/execution gates.
- Run documented local camera-grounded product proof only when provider/network/runtime readiness passes; otherwise retain guarded blocker output and stop.
- Do not authorize real-robot movement, provider bake-offs, public contract changes, or durable artifact schema changes in this phase.

## Canonical References

- `docs/plans/2026-09-01-state-first-context-manager.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `docs/plans/2026-08-31-camera-grounded-default-and-cleanup-unification.md`
- `docs/plans/2026-08-31-camera-grounded-dino-cleanup-capability.md`
- `docs/plans/2026-08-31-fix-camera-grounded-sdk-dino-acquisition.md`
- `docs/plans/operator-console-layered-launch-gates.md`
- `docs/plans/molmospaces-agibot-contract-rehearsal.md`

## Planning Notes

The plan must name executable tasks, owners, artifacts, and verification for each route and shared evidence/privacy contract. Required gates are deterministic, focused eval, product-run, and guarded local/live/manual gates; unavailable external prerequisites are blockers to live proof, not reasons to substitute only unit tests.
