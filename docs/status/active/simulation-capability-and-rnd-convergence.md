# Simulation Capability And R&D Convergence

State: active  
Owner/session: Codex `/root`  
Source plan: `docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md`

## Current slice

Phase 2/3 provider retirement and showcase acceptance repairs remain active.
Paired local compact bread and cleanup proofs are terminal: MiniMax and MiMo TP
each pass both cases (`1/1` per row, zero failed/blocked). All four first-attempt
packets under `output/convergence-compact/` pass current exact-case showcase
validation. No simulator process from this collection remains active.

Full initiative acceptance is incomplete: full external matrices, trusted
current-code hosted proof, and real-DINO capability acceptance remain open.

## Verification state

Provider readiness and runtime construction now reject retired Kimi/Qwen
profiles; engine launch catalogs advertise only the three active routes.
Readiness probes and the benchmark use active routes, with the public probe
profile excluding internal MiMo Responses. Focused provider, launch, console,
and dev-tool checks passed for those changes; no current-tree full-gate pass is
claimed after the latest migrations. Historical provider identity/model lookup remains read-only; executable Kimi/Qwen
route registrations, request headers and thinking branches are removed. Active
README and contributor guidance now describe the two external providers and
protected-main manual execution.

Showcase aggregation rejects mixed blocked/passed and incomplete counts;
provider-backed passing packets must include every requested sample/repetition
exactly once, matching suite/sample versions, seed, world, backend, provider,
engine and lane. Malformed identities block. Focused showcase tests: 56 passed;
all four new compact live packets pass the stricter checker. Commit `43a276bc`.

Retired delivery rows are removed from the harness catalog. No-skill is selected
only by explicit `profile=skill-control`; the resolved static-full/no-skill
commands have matching provider, suite, budget and canonical prior, differing
only in treatment and output stamp. Selector/profile checks: 32 passed. Latest
control recommendation: `output/eval-harness/20260930T102512Z/`.

The Skill/runtime retirement and remaining eval caller migration are committed
as `2134f313`. The commit hook's complete fast pytest subset passed. Current-tree
Ruff, format (1014 files), quality ratchet and architecture checks pass (558
modules, zero violations), as do the 49 additional report/artifact checks from
the standard gate. The earlier `just agent::verify` invocation was deliberately
interrupted before the retirement slice; its log is partial, not a pass. Full
commit-hook output is `/tmp/convergence-retirement-commit.log`.

Executable dynamic/sandbox Skill delivery, sandbox adapter/probe and the Docker
extra are removed; `uv sync --extra dev` completed and Docker distribution is
absent. No-skill requires an eval-only environment opt-in; cleanup and MapBuild
kickoff preserve that treatment. Historical Kimi/dynamic-routed regrade passes
without provider calls, and Evolution isolation checks pass. The Kimi-only
apple2apple generator and stale active eval fixtures now use MiMo TP.

Paired Skill live proof is terminal: both first attempts passed `1/1`.
Static-full took 316.399 seconds and no-skill 300.399 seconds, with identical
MiniMax cleanup seed7/repetition0, canonical prior, 100-call/3600-second/
180-second-stall bounds and zero retries. Identities match except for the
Skill treatment; the no-skill artifact records zero included Skill bytes/tokens.
Commands, attempts and usage are retained under `output/convergence-skill-control/`
in `paired-commands.json`, `attempts.json` and `paired-proof-summary.json`.
Static-full input/output usage was 3,024,663/9,010 tokens; no-skill was
2,923,348/4,863. Both have a missing-response-span limitation. Prompt sizes were
not extracted and dollar cost is unavailable, not zero. This single paired
case is a control proof, not a statistically meaningful Skill ranking.

SDK availability was previously proven for all three active routes in
`output/convergence-provider-retirement/sdk-readiness.json`; the 2026-10-08
refresh could not complete because provider network calls hung in the restricted
sandbox. Focused agent,
console route and catalog checks pass (413 tests), as do Ruff and formatting.
The current standard gate reached the full suite but could not pass in this sandbox: `uv build` hit its package-source/network restriction and socket-based operator-console tests hit `PermissionError: Operation not permitted`. Ruff, formatting, architecture, quality ratchet, and the focused provider/agent/launch/console/catalog suite pass; no unrestricted full-gate pass is claimed.

Read-only historical development diagnosis is retained at
`output/convergence-visual/diagnosis-scene0-trial2.json`: the agent called done
with explicit heading-coverage and cleanup-chain blockers. Two detected Books
were correctly non-recommended on Desk/ShelvingUnit; the missing misplaced Book
was not those handles. Do not weaken cleanup recommendation or authorization
from this evidence. Current-code scene0 DINO replay remains required.
Previously inspected reserved scenes 11/13 are no longer unseen holdout; a new
reserved set/version is required before any fresh generalization claim.

Hosted full-matrix feasibility is recorded at
`output/convergence-hosted-readiness/full-matrix-feasibility.json`.
Fifteen observed compact cleanup runtimes alone imply about 93 minutes for
MiniMax and 162 minutes for MiMo TP, excluding setup and other tasks. The
3600-second per-case cap implies 15 hours/provider and cannot fit a 60-minute
shard. Full scheduled execution remains unenabled pending a concrete bounded
sharding/envelope decision; no cost/resource expansion is authorized by elapsed time.

GitHub authentication and workflow read access pass. The latest successful
hosted run, `https://github.com/MiaoDX/roboclaws/actions/runs/36406210330`, is at
old commit `becf890c` and includes retired Kimi. It is historical timing evidence,
not proof of the current manifest or two-provider workflow.

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
- Active provider catalog surface: `mimo-responses`, `mimo-tp-openai-chat`, `minimax-responses`; legacy identities remain readable without executable route specs.
- Trusted showcase manifest now contains only active provider rows; Kimi rows remain only in historical evidence/readers.
- Runtime Skill lifecycle now accepts only `static-full`; broad delivery parsing remains available to eval/regrade paths.
- Showcase workflow now runs active provider shards only, with protected-main push/schedule/manual routing and two-shard concurrency.
- Showcase manifest validation now rejects retired provider profiles while summary/report rendering continues to read historical identities.
- Active eval-harness catalog now contains only the three supported provider rows; retired Kimi execution policy and row were removed, with selector coverage updated and passing.
- Earlier `just agent::verify` passed before the subsequent migrations: Ruff, format, architecture import graph, and standalone pytest (100% complete; 1015 files formatted), including the active-provider catalog guard.
- Explicit `no-skill` kickoff now states that the Skill body is withheld while tool descriptions and run context remain available.
- Focused facade execution completed at `output/eval-harness/20260928T113410Z/`: 13 passed, 4 failed, 2 blocked; required SDK open-task and cleanup rows were `environment_blocked`, while the no-skill live row executed. This is evidence, not acceptance.
- Exact-identity MiniMax repair attempts with `runtime_map_prior=assets/eval-priors/runtime_map_prior_catalog.json` were recorded under `output/eval-harness/20260928T113410Z/repair/`; both cleanup and open-ended cohorts remained blocked because the cleanup MCP server exited before readiness, before any model call.
- Corrected snapshot-shape and `.env` loading repairs passed independently: MiniMax static-full cleanup `3/3` at `output/eval-harness/20260928T113410Z/repair3/`, and MiniMax open-ended `3/3` at `output/eval-harness/20260928T113410Z/repair3-open/`. These are compatible replacement evidence, not a rewrite of the original blocked packet.
- MiMo TP static-full cleanup compatibility cohort completed at `output/eval-harness/20260928T113410Z/mimo-tp/`: 2/3 passed, 1/3 blocked by the recorded 180-second no-progress stall; no failures. The blocked denominator remains visible and the cohort is not accepted as fully passing.
- Frozen visual case identity is recorded in `evals/household_world/manifests/simulation_convergence_visual_v1.json`: development scenes 0/10/12, reserved scenes 11/13, seed 7 with three trial identities per scene, real DINO lane, and fresh-map treatment. The v1 collection is now complete by identity but fails acceptance; later reserved-scene inspection prevents an unseen-holdout claim.
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

Finish and commit the provider slice after the current standard gate. Then run
one current-code development scene0 real-DINO replay to distinguish historical
behavior from current behavior before a strategy fix. Full matched external
matrices, trusted hosted proof and visual acceptance remain required. Preserve
all old failures, blocked attempts and repair replays; none becomes acceptance
by combining incompatible epochs. Prepare concrete full-cohort budgets before
requesting any material hosted resource/cost expansion.

## Stop/resume conditions

Stop for a material scope, provider/resource/cost, credential, privacy,
publication, or real-robot decision. Resume ordinary in-scope implementation
under the unchanged contract.

## No-touch scope

Do not rewrite historical evidence, publish a baseline/catalog, change resources
or credentials, move a real robot, or modify unrelated active capsules. Keep one
simulator runtime at a time and retain every new attempt separately.

- Verification correction: suite retirement checks now inspect nested metadata and enforce provider-cell counts. Focused model-schema tests pass (16 tests); active suite count is corrected to three.
