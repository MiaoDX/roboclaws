# Simulation Capability And R&D Convergence

State: active  
Owner/session: Codex `/root`  
Source plan: `docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md`

## Current slice

Phase 1 — establish the fixed initiative owner and reconcile current versus
historical status records. The canonical plan owns scope and acceptance; this
capsule owns execution state and evidence links. `.planning/STATE.md` remains
the State-First GSD cursor and links here only when that initiative is relevant.

## Verification state

Focused provider/catalog and console-route tests pass. Shared console fixtures
and default-path assertions now use the catalog-owned MiMo environment while
retaining explicit Kimi coverage. The full operator-console suite passes.
Provider migration remains unfinished outside the console surface.
Plan-level checks completed: referenced-path scan and `git diff --check`.
Gate recommendation: `output/eval-harness/20260928T101404Z/`.

## Proven evidence

- Current dashboard: `STATUS.md`
- Historical baseline: `docs/status/active/local-eval-baseline-refresh.md`
- State-First record: `docs/status/active/state-first-context-manager.md`
- Reviewed Skill probe: `docs/status/active/skill-delivery-multiscene-probe.md`
- Plan gate recommendation: `output/eval-harness/20260928T101404Z/eval_harness.{json,md}`

## Next action

Reconcile the remaining executable versus historical Skill/provider callers,
then migrate the active provider catalog, manifests and documentation before
retiring executable Kimi/Qwen routes.

## Stop/resume conditions

Stop for a material scope, provider/resource/cost, credential, privacy,
publication, or real-robot decision. Resume ordinary in-scope implementation
under the unchanged contract.

## No-touch scope

Do not rewrite historical evidence, publish a baseline, run live providers or
simulators during phase 1, or modify unrelated active capsules.
