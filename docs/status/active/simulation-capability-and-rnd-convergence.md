# Simulation Capability And R&D Convergence

State: active
Owner/session: Codex `/root`  
Source plan: `docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md`

## Current slice

Implementation state: active. Verification state: partial; capability acceptance incomplete.
Latest intent: continue implementation and required probes under the approved plan.

Provider/Skill convergence is committed through `a5647ec8`: only static-full is a
product delivery, no-skill is an explicit eval control, and only MiMo Responses,
MiMo TP and MiniMax are executable providers. Historical identities remain readable.
Exact showcase identities and complete cohort thresholds are validated without
rewriting failed trial statuses or averaging away blocked/infrastructure rows.

On 2026-10-08 all three SDK provider probes and managed real-DINO readiness passed.
The complete standard gate passed after the cohort change (session `75547`, exit 0):
`output/convergence-resume-20261008/verify-after-cohorts.log`.
The earlier sandbox/network failures are historical and are no longer blockers.

Preserved pre-fix development evidence: scene0 attempt2 is terminal.
MiniMax real DINO, static-full, seed7, fresh map/no prior: partial_success after
551.359 seconds, 3/5 restored, 3 grounded chains, sweep 1.0, disturbances 0.
Only room2 completed four headings; rooms3–8 remained at one. The agent called
terminal done despite the latest public completion naming room3 recovery.
There were 38 successful model responses, zero provider failures and one
terminal-interrupted response span. Reported input/output tokens: 3,646,813/13,182;
usage has a missing-response-span limitation and dollar cost is unavailable.

Attempt1 failed before any model call because live_token_budget requires a paired
priced output reservation/cost budget. Attempt2 omits it: no cumulative token cap
is claimed. All attempts and exact code/command/limits are preserved under
`output/convergence-resume-20261008/`; diagnostic summary:
`output/convergence-resume-20261008/diagnosis-scene0-attempt2.json`.

## Latest completed experiment

Recovery fix `f77db430` removed contradictory kickoff strategy and clarified
mandatory recovery in the Skill. Same-bounds scene0 attempt3 PASSED: 4/5 restored,
4 grounded chains, sweep 1.0, disturbances 0, authoritative success and checker
exit 0 after 867.553 seconds. The final public pre-done completion was ready.
There are 76 successful response metrics, input/output tokens 6,852,297/11,280,
no usage-span limitation, and unavailable dollar cost. The 23 real-DINO observation
events record CUDA on NVIDIA GeForce RTX 3090. This is new development
evidence, not a replacement in the old 15-case cohort. Summary:
`output/convergence-resume-20261008/minimax-scene0-attempt3/proof-summary.json`.
The experiment establishes that recovery continues beyond the first room; it
makes no claim that every possible heading must be scanned after readiness.
The fix's complete standard gate passed at
`output/convergence-resume-20261008/verify-after-recovery-attempt2.log`.

ADR-0151 is committed (`6631b4d6`), STATUS.md is trimmed, and initial historical
baseline/Skill/state-first capsules plus GSD pointers have explicit dispositions.
Cohort execution deadlines are now distinct from per-trial caps (`21334ee7`);
multi-trial live rows require an explicit deadline covering all selected caps.
Focused showcase/workflow/process checks pass; full gate session `98851`
passed (exit 0), log `output/convergence-resume-20261008/verify-after-showcase-runtime.log`.

Reserved scene fixture readiness attempt1 is terminal: both scenes14/15 were
blocked by `MolmoSpaces subprocess worker timed out (init, 300s)`. Scene15's
checked-in Base Metric Map validates; scene14's map was not produced. No
behavior/image review took place and no scene was substituted. Summary:
`output/convergence-resume-20261008/reserved-readiness-attempt1/readiness.json`.
Environment-key comparison found no relevant dotenv/proxy difference.
The 70-second diagnostic attempt2 is terminal (session36704, exit124).
Faulthandler shows the main worker waiting on scene archive extraction and a
thread stalled in requests/urllib3 TCP connection setup at
`molmospaces_resources/remote_storage.py:69` (`stream_archive`). It has not
reached MuJoCo load. The direct guarded endpoint probe also failed with curl28:
connection to the configured public R2 resource endpoint port443 timed out.
Evidence: `output/convergence-resume-20261008/reserved-init-diagnostic-attempt2.log`
and `resource-endpoint-probe.log` in that same root. This is a concrete scene
resource availability blocker, not provider/DINO unavailability or behavior failure.
Do not silently select another reserved set or change resource credentials.

Development scene10 replay is terminal (session `87633`, exit0): partial_success,
3/5 restored, 3 grounded chains, sweep 1.0, disturbances 0, checker exit 0, 682.46s.
The final public completion still reports insufficient grounded cleanup chains;
the agent terminated after additional headings produced no pending candidates.
There were 66 successful model calls, no provider failures, 24 DINO observations,
input/output tokens 5,287,391/19,167 and no usage-span limitation; dollar cost is
unavailable. This does not establish a new strategy root cause or pass acceptance.
Evidence: `output/convergence-resume-20261008/minimax-scene10-attempt1/proof-summary.json`.

Cumulative token enforcement is implemented in the agent-engine provider boundary;
the eval/showcase seams pass an explicit per-run limit. It reserves native model
input/output capacity before every transport attempt, settles known usage,
retains unknown usage, and shares a locked ledger across continuations. Hidden
client retries are disabled for budgeted runs. Focused checks passed (189 tests).
Real MiniMax bread proof passed 1/1 in 64.067s with a 4M-token limit: five settled
responses total 146,553 tokens plus one terminal-interrupted 2M reservation,
charged 2,146,553. The separate 1-token negative case stops before the first
provider attempt, records zero requests, and correctly remains an eval failure
(`budget_exhausted`), not a capability pass. Both attempts have zero trial retries
and exact worktree identities under
`output/convergence-resume-20261008/token-budget-live-attempt1/`.
The first full gate stopped at a new environment-helper complexity violation;
that helper is repaired. Full gate attempt2 passed (session `24423`, exit 0), log
`output/convergence-resume-20261008/verify-after-total-token-budget-attempt2.log`.
Staging exposed one new-file validator complexity violation that the unstaged
ratchet had not included; simplifying that branch preserved behavior. The 28
budget tests and full gate attempt3 passed (session `41549`, exit 0), log
`output/convergence-resume-20261008/verify-after-total-token-budget-attempt3.log`.
The slice includes engine/eval implementation, tests and human/architecture docs.

Scene12 development replay is RUNNING under session `60527`, wrapper
`output/convergence-resume-20261008/replay-scene12-attempt1.py`, attempt root
`output/convergence-resume-20261008/minimax-scene12-attempt1/`.
It uses MiniMax/DINO/static-full/fresh-map, five targets, 100 calls, 3600 seconds,
180-second stall, zero automatic trial retries and a 16M cumulative-token limit.
Hypothesis: the recovery change can generalize to scene12 within explicit usage
bounds; success enables the next frozen-cohort preparation, while failure keeps
development diagnosis open. This remains independent development evidence with
code/worktree hashes; do not stitch it into an earlier epoch. Poll the handle and
sanitized live_status; do not launch another simulator.

Before this new strategy edit, reserve scenes **14 and 15** (procthor-10k-val)
for the next visual epoch. No images or behavior traces from these scenes were
inspected for this investigation. Scene15 has a checked-in Base Metric Map;
scene14 map/fixture readiness remains to be established before freezing the full
executable case manifest. Selection is fixed before tuning; infrastructure
readiness cannot become a search for favorable behavior. Old reserved scenes
11/13 have been inspected and cannot support an unseen-holdout claim.

## Verification boundaries

The compact bread/cleanup first attempts pass for both external providers, and
the matched MiniMax static-full/no-skill control passes both treatments. These
are local small proofs, not full external, hosted, or visual acceptance.
The control has matching seed/prior/budgets and zero trial retries. Static-full
input/output usage is 3,024,663/9,010; no-skill 2,923,348/4,863. Both have a
missing-response-span limitation; dollar cost is unavailable. No causal Skill
ranking is claimed from one paired case.

The preserved real-DINO v1 ledger covers all 15 identities but fails acceptance.
MiMo Responses development smoke is incomplete; MiMo TP historical cleanup
compatibility is 2/3 with one blocked stall. Repairs remain separate evidence.

Hosted feasibility: `output/convergence-hosted-readiness/full-matrix-feasibility.json`.
Fifteen observed cleanup runtimes imply about 93 minutes MiniMax / 162 minutes
MiMo TP before setup or other tasks. Current 3600-second per-case caps cannot fit
60-minute shards. Full execution remains unenabled pending matched manifests,
aggregate token/runtime envelopes and bounded sharding (maximum two external
shards). The old successful hosted run 36406210330 at becf890c includes retired
Kimi and is not current-code proof.

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

Collect the running scene12 replay. Investigate the remaining development-scene
discovery failures. Resolve
the proven reserved-scene asset-download blocker before reserved execution.
Complete new epoch/full matched manifests,
actual token/runtime budgets, trusted current-code hosted proof and the full visual
gate. Neither compact successes nor green deterministic tests close these gates.
Do not stitch different code/content epochs into the old first-attempt cohort.

## Stop/resume conditions

Stop for a material scope, provider/resource/cost, credential, privacy,
publication, or real-robot decision. Resume ordinary in-scope implementation
under the unchanged contract.

## No-touch scope

Do not rewrite historical evidence, publish a baseline/catalog, change resources
or credentials, move a real robot, or modify unrelated active capsules. Keep one
simulator runtime at a time and retain every new attempt separately.

- Verification correction: suite retirement checks now inspect nested metadata and enforce provider-cell counts. Focused model-schema tests pass (16 tests); active suite count is corrected to three.
