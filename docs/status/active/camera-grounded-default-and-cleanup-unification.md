# Camera-Grounded Default And Cleanup Unification

**Status:** ACTIVE
**Source plan:** `docs/plans/2026-08-31-camera-grounded-default-and-cleanup-unification.md`
**Control plane:** root Codex goal `01a055d3-e1cd-79f2-ae76-6c47afe5c0b4`
**Project-status writer:** this standalone task control plane

## Current State

- Latest intent: execute the approved plan through `intuitive-flow`.
- Current slice: extend typed launch and run-result identity and enforce
  fail-closed grounded provenance.
- Last proven evidence: focused and broad cleanup-policy tests prove the direct
  runner drains actionable candidates per waypoint; trace evidence distinguishes
  same-waypoint recovery, delayed cleanup, coverage observes, and immediate
  post-place verification.
- Completed slices: showcase identity repair; shared lane-neutral local-drain
  strategy and honest policy-trace semantics.
- Next slice: verify grounded runs cannot pass with simulator provenance, a
  mismatched pipeline, or zero detector/registration events.
- Next proof: focused showcase, launch-catalog, and evidence-identity tests via
  `./scripts/dev/run_pytest_standalone.sh`.

## Stop Condition

Stop before default migration if real Grounding DINO simulation cleanup or the
fixed real-camera offline portability proof is unavailable or fails. Do not
substitute simulator labels, mocks, physical motion, cloud execution, provider
expansion, or compatibility aliases.

## No-Touch Scope

- Physical robot motion and manipulation.
- Cloud promotion or provider concurrency changes.
- Historical artifacts, ADR rationale, and retrospectives.
- Detector bakeoffs, training, and broad threshold searches.

## Parked Work

- Physical robot cleanup capability.
- Additional detector and provider matrices.
- Future raw-image agent research after any active Raw-FPV retirement.
