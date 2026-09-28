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
- Plan gate recommendation: `output/eval-harness/20260928T111441Z/eval_harness.{json,md}`
- Active provider catalog surface: `mimo-responses`, `mimo-tp-openai-chat`, `minimax-responses`; legacy route specs remain readable for historical artifacts.
- Trusted showcase manifest now contains only active provider rows; Kimi rows remain only in historical evidence/readers.
- Runtime Skill lifecycle now accepts only `static-full`; broad delivery parsing remains available to eval/regrade paths.
- Showcase workflow now runs active provider shards only, with protected-main push/schedule/manual routing and two-shard concurrency.
- Showcase manifest validation now rejects retired provider profiles while summary/report rendering continues to read historical identities.
- Full `just agent::verify` passes: Ruff, format, architecture import graph, and standalone pytest (100% complete; 1015 files formatted).
- Explicit `no-skill` kickoff now states that the Skill body is withheld while tool descriptions and run context remain available.
- Focused facade execution completed at `output/eval-harness/20260928T113410Z/`: 13 passed, 4 failed, 2 blocked; required SDK open-task and cleanup rows were `environment_blocked`, while the no-skill live row executed. This is evidence, not acceptance.
- Exact-identity MiniMax repair attempts with `runtime_map_prior=assets/eval-priors/runtime_map_prior_catalog.json` were recorded under `output/eval-harness/20260928T113410Z/repair/`; both cleanup and open-ended cohorts remained blocked because the cleanup MCP server exited before readiness, before any model call.
- Corrected snapshot-shape and `.env` loading repairs passed independently: MiniMax static-full cleanup `3/3` at `output/eval-harness/20260928T113410Z/repair3/`, and MiniMax open-ended `3/3` at `output/eval-harness/20260928T113410Z/repair3-open/`. These are compatible replacement evidence, not a rewrite of the original blocked packet.
- MiMo TP static-full cleanup compatibility cohort completed at `output/eval-harness/20260928T113410Z/mimo-tp/`: 2/3 passed, 1/3 blocked by the recorded 180-second no-progress stall; no failures. The blocked denominator remains visible and the cohort is not accepted as fully passing.
- Frozen visual case identity is recorded in `evals/household_world/manifests/simulation_convergence_visual_v1.json`: development scenes 0/10/12, reserved scenes 11/13, seed 7 with three trial identities per scene, real DINO lane, and fresh-map treatment. Fixture readiness and live collection remain pending.

## Next action

The focused live-row blockers are resolved for MiniMax, with compatible repair
evidence preserved. Next, prepare the frozen multiscene visual case manifest
from the existing camera-grounded/DINO harness and collect the required
MiniMax real-DINO cohort. Do not treat compatibility repairs as visual proof.

## Stop/resume conditions

Stop for a material scope, provider/resource/cost, credential, privacy,
publication, or real-robot decision. Resume ordinary in-scope implementation
under the unchanged contract.

## No-touch scope

Do not rewrite historical evidence, publish a baseline, run live providers or
simulators during phase 1, or modify unrelated active capsules.
