# Simulation Capability And R&D Convergence

State: active  
Owner/session: Codex `/root`  
Source plan: `docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md`

## Current slice

Phase 2/3 provider retirement and showcase acceptance repairs are implemented
incrementally. The new paired compact open-ended local proof passes on MiniMax
and MiMo TP; cleanup, hosted execution, full external matrices, and real-DINO
acceptance remain open. No live process from this compact pair remains running.

## Verification state

Focused provider/catalog and console-route tests pass. Shared console fixtures
and default-path assertions now use the catalog-owned MiMo environment while
retaining explicit Kimi coverage. The full operator-console suite passes.
Eval sample/suite, harness-row, shell-launch, and maintained guidance migration is implemented. Full provider retirement remains incomplete: runtime supported-profile registration, developer probes, and remaining active guidance still expose retired routes. Earlier broad completion claims were premature.
Plan-level checks completed: referenced-path scan and `git diff --check`.
Gate recommendation: `output/eval-harness/20260928T101404Z/`.

## Proven evidence

- Fresh paired compact bread proof: MiniMax `1/1` passed at
  `output/convergence-compact/minimax-attempt-1/` (43.186 seconds), and MiMo TP
  `1/1` passed at `output/convergence-compact/mimo-tp-attempt-1/` (92.818 seconds).
  Both are first attempts with zero failed/blocked trials and zero model failures,
  explicit provider identity, world-public-labels, seed 7, repetition 0, 16-call
  cap, 120-second stall cap, and zero trial retries. Both terminal eval packets
  pass current `derive_row` identity/aggregate validation. These are local compact
  open-ended proofs, not hosted-workflow, cleanup, or real-DINO acceptance.


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
- Active eval-harness catalog now contains only the three supported provider rows; retired Kimi execution policy and row were removed, with selector coverage updated and passing.
- Full `just agent::verify` passes on the current tree: Ruff, format, architecture import graph, and standalone pytest (100% complete; 1015 files formatted), including the active-provider catalog guard.
- Explicit `no-skill` kickoff now states that the Skill body is withheld while tool descriptions and run context remain available.
- Focused facade execution completed at `output/eval-harness/20260928T113410Z/`: 13 passed, 4 failed, 2 blocked; required SDK open-task and cleanup rows were `environment_blocked`, while the no-skill live row executed. This is evidence, not acceptance.
- Exact-identity MiniMax repair attempts with `runtime_map_prior=assets/eval-priors/runtime_map_prior_catalog.json` were recorded under `output/eval-harness/20260928T113410Z/repair/`; both cleanup and open-ended cohorts remained blocked because the cleanup MCP server exited before readiness, before any model call.
- Corrected snapshot-shape and `.env` loading repairs passed independently: MiniMax static-full cleanup `3/3` at `output/eval-harness/20260928T113410Z/repair3/`, and MiniMax open-ended `3/3` at `output/eval-harness/20260928T113410Z/repair3-open/`. These are compatible replacement evidence, not a rewrite of the original blocked packet.
- MiMo TP static-full cleanup compatibility cohort completed at `output/eval-harness/20260928T113410Z/mimo-tp/`: 2/3 passed, 1/3 blocked by the recorded 180-second no-progress stall; no failures. The blocked denominator remains visible and the cohort is not accepted as fully passing.
- Frozen visual case identity is recorded in `evals/household_world/manifests/simulation_convergence_visual_v1.json`: development scenes 0/10/12, reserved scenes 11/13, seed 7 with three trial identities per scene, real DINO lane, and fresh-map treatment. Fixture readiness and live collection remain pending.
- Fresh real-Grounding-DINO MapBuild readiness runs completed for development scenes 0, 10, and 12 with seed 7: `output/convergence-mapbuild/scene0/0928_2122/seed-7/`, `output/convergence-mapbuild/scene10/0928_2125/seed-7/`, and `output/convergence-mapbuild/scene12/0928_2128/seed-7/`. Each exited `household-world ok` with `map_build_baseline complete`, private truth excluded, zero labeler failures, and sweep coverage 1.0; the runs recorded 35/20/50 DINO events and 239/108/327 candidates respectively.
- MiniMax real-DINO first attempts now exist for every development scene in the frozen manifest: scene 0 at `output/convergence-visual/minimax/scene0/trial0/` restored 3/5 targets, scene 10 at `output/convergence-visual/minimax/scene10/trial0/` restored 1/5, and scene 12 at `output/convergence-visual/minimax/scene12/trial0/` restored 2/5. All three completed with `partial_success`, real `grounding-dino` provenance, sweep coverage 1.0, and zero disturbances. These are cross-scene capability evidence, not the 12/15 acceptance cohort.
- Reserved scene 11 first attempt is recorded at `output/convergence-visual/minimax/scene11/trial0/`: the authoritative run artifact reports `completion_status=success`, four grounded cleanup chains, 5-target grading, sweep coverage 1.0, and zero disturbances. The outer cleanup-validation wrapper exited nonzero on a checker mismatch after the successful artifact was written; this remains an explicit validation discrepancy and does not count as a clean accepted cohort row until resolved.
- Reserved scene 13 first attempt is recorded at `output/convergence-visual/minimax/scene13/trial0/`: the authoritative run artifact also reports `completion_status=success`, four grounded cleanup chains, 5-target grading, sweep coverage 1.0, and zero disturbances. Its outer checker likewise exited nonzero on strict robot-view evidence, so it remains behavioral evidence pending validator-clean replay.
- A fresh scene 11 replay after the held-object evidence fix was started at `output/convergence-visual/minimax/scene11/trial1/` but terminated before producing `run_result.json`; it is retained as an incomplete infrastructure attempt and does not replace the earlier scene 11 artifact.
- The scene 11 trial1 terminal packet records MiniMax Token Plan quota exhaustion (`2056`, `provider_quota_failure`, `billing_limit`) after 25 successful model calls. That attempt was non-retryable under the provider contract; later quota recovery enabled the separately identified repair replays below.
- MiMo Responses development smoke scene 0 was attempted at `output/convergence-visual/mimo/scene0/trial0/`; it reached 66 successful model calls and continued making tool progress for roughly 30 minutes without an authoritative `done`/`run_result.json`. It was stopped as an incomplete bounded attempt and does not count as MiMo acceptance.
- After the reported quota recovery, MiniMax trial-1 collection resumed. Scene 0 trial 1 at `output/convergence-visual/minimax/scene0/trial1/` is validator-clean and reports success with 4/5 accepted targets, sweep coverage 1.0, and zero disturbances. Scene 10 trial 1 at `output/convergence-visual/minimax/scene10/trial1/` reports behavioral success with 4/5, sweep 1.0, and zero disturbances, but its historical strict validation still rejects an open-receptacle focused frame with zero object pixels and room mismatch. Scene 12 trial 1 at `output/convergence-visual/minimax/scene12/trial1/` is checker-clean but partial success at 2/5, sweep 1.0, and zero disturbances. Trial-1 outcomes expand the complete cohort evidence but do not alter first-attempt acceptance denominators.
- Reserved trial-1 follow-up artifacts are now present: scene 11 trial 2 at `output/convergence-visual/minimax/scene11/trial2/` and scene 13 trial 1 at `output/convergence-visual/minimax/scene13/trial1/` each report behavioral success at 4/5, sweep coverage 1.0, and zero disturbances. Their historical strict checker failures remain preserved as immutable evidence.
- MiniMax development trial-2 follow-ups are complete: scene 0 at `output/convergence-visual/minimax/scene0/trial2/` reports partial success 3/5, scene 10 at `output/convergence-visual/minimax/scene10/trial2/` reports behavioral success 4/5 with strict checker failure, and scene 12 at `output/convergence-visual/minimax/scene12/trial2/` reports partial success 2/5. All three have sweep coverage 1.0 and zero disturbances; these follow-ups do not alter first-attempt acceptance denominators.
- The final reserved identity, scene 13 trial 2 at `output/convergence-visual/minimax/scene13/trial2/`, completed as an authoritative behavioral failure: 0/5 accepted targets, sweep coverage 1.0, zero disturbances, and no actionable public DINO handle reached navigation authorization. This preserves the complete 15-case identity ledger with explicit failure evidence; the frozen MiniMax acceptance threshold is not met.
- The strict-visual repair replay for scene 13 at `output/convergence-visual/minimax-repair/scene13/repair0/` is checker-clean after the two producer/checker fixes: the open-fridge pose records a 1.8 m stand-off and `same_room`, the focused Apple frame has 3026 FPV and 283 verify object pixels, and `place_inside`/`close_receptacle` report `contained_inside`. The authoritative run remains `partial_success` (3/5 restored), so this is visual-validation evidence rather than an accepted cohort row.
- Exact post-fix replays for scene 10 and scene 11 at `output/convergence-visual/minimax-repair/scene10/repair1/` and `output/convergence-visual/minimax-repair/scene11/repair1/` both exit `household-world ok` with no strict checker rejection. They are behavior-incomplete at 1/4 cleanup chains each: scene 10 rejected four detected candidates as `visual_candidate_not_cleanup_recommended`, while scene 11 returned only one cleanup-recommended candidate. These are behavior evidence, not quota or visual-validation failures.

## Next action

Finish runtime/probe provider retirement and remaining active guidance. The focused live-row blockers are resolved for MiniMax, with compatible repair
evidence preserved. Quota recovery allowed the complete 15-case identity ledger
to be collected. Scene 13's focused fridge-view defect is fixed and checker-clean
in the repair replay, and post-fix scene 10/11 replays are also checker-clean;
their remaining failures are behavior-incomplete candidate selection. Scene 13
trial 2 remains a genuine public-discovery failure. The required first-attempt
threshold is still not met, and MiMo Responses real-DINO smoke is incomplete.
Do not treat the repair replays as visual-cohort acceptance.

## Stop/resume conditions

Stop for a material scope, provider/resource/cost, credential, privacy,
publication, or real-robot decision. Resume ordinary in-scope implementation
under the unchanged contract.

## No-touch scope

Do not rewrite historical evidence, publish a baseline, run live providers or
simulators during phase 1, or modify unrelated active capsules.

- Verification correction: suite retirement checks now inspect nested metadata and enforce provider-cell counts. Focused model-schema tests pass (16 tests); active suite count is corrected to three.
