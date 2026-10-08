# Simulation Capability And R&D Convergence

State: active
Owner/session: Codex `/root`
Source plan: `docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md`

## Current conclusion

Implementation is active; verification is partial; capability acceptance is
incomplete. Latest intent is to continue the approved plan and required probes.
One static-full product Skill and three executable providers (MiMo Responses,
MiMo TP, MiniMax) are implemented. Historical identities remain readable without
re-enabling retired routes. ADR-0151 owns the durable convergence decisions.

Current visual development evidence: scene0 and scene10 pass at 4/5; scene12
visits all waypoints but remains 3/5 with mandatory heading recovery unfinished.
MiniMax scene12 attempt3 is blocked by provider billing limit after removing
contradictory composite-tool controls. MiMo Responses scene0 passes; scene10
attempt1 is blocked by a model-response stall; attempt2 is now blocked by a
second stall after a successful connectivity probe.
MiMo Responses scene12 attempt1 is running under the same per-run bounds.
No development replay replaces an old failed cohort row. Full MiniMax real-DINO,
MiMo Responses smoke, matched external cohorts and trusted current-code hosted
proof remain required. No baseline/catalog or full schedule is promoted.

## Live work — poll before starting another simulator

MiMo Responses scene12 attempt1 is RUNNING, session `30357`:

- Wrapper/log: `output/convergence-resume-20261008/replay-mimo-scene12-attempt1.py`
  and matching `.log`; root `mimo-scene12-attempt1/` under that output directory.
- Clean start at `ed7b6332`, real CUDA DINO, static-full, scene12 seed7, five
  targets, fresh Runtime Metric Map. Canonical route `mimo`, request model
  `xiaomi/mimo-v2.6-pro`.
- Same100-call /16M-token /3600s-wall /180s-stall bounds, zero automatic retries.
- Latest live poll: running-sdk at1320s,18 successful responses, zero provider
  errors; no authoritative run result or terminal capability verdict yet.

MiMo Responses scene10 attempt2 is terminal and BLOCKED, session `87152`:

- Wrapper/log: `output/convergence-resume-20261008/replay-mimo-scene10-attempt2.py`
  and matching `.log`; root: `mimo-scene10-attempt2/` under that output directory.
- Clean start at `b00f64d4`, including response fix `0c00fba2`. Real CUDA DINO,
  static-full, seed7, five targets and fresh Runtime Metric Map.
- Bounds unchanged:100 cumulative calls,16M tokens,3600s wall,180s stall,
  zero automatic retries. Canonical route `mimo`, request `xiaomi/mimo-v2.6-pro`.
- Terminal at1773.084s after a 180s no-progress stall: 68 successful responses,
  no provider errors, three complete cleanup chains, full waypoint/heading
  coverage, but no authoritative run result. Ledger charged4,979,428 of16M;
  original terminal model metrics were absent. Existing span extraction recovers
  input/output4,560,704/18,724 and cached415,104 across69 metrics into separate
  `recovered-model-call-metrics.jsonl`; the unfinished response's usage remains
  unknown (retained400K reservation). `proof-summary.json` preserves this
  infrastructure block and does not establish capability pass.

MiniMax scene12 attempt3 (session `25951`) is terminal:

- Wrapper: `output/convergence-resume-20261008/replay-scene12-attempt3.py`.
- Root: `output/convergence-resume-20261008/minimax-scene12-attempt3/`.
- Log: `output/convergence-resume-20261008/replay-scene12-attempt3.log`.
- Real CUDA DINO, static-full, fresh map, seed7, five targets.
- 100 cumulative decision calls, 3600s wall, 180s stall, 16M cumulative tokens,
  zero automatic trial retries. Model: `MiniMax-M3`.
- Started on `7a9b03f9` plus the staged completion-projection fix. The original
  contract's unstaged-diff hash omitted staged edits; `code-identity-supplement.json`
  and `code-diff.patch` capture unchanged source during the live attempt.
- Terminal at656.374s: 44 successful responses, then `provider_quota_failure` /
  `billing_limit` on request45; no retry. Two public grounded chains completed,
  but no authoritative run result. Ledger charged5,906,328 of16M.
- `proof-summary.json` preserves the blocked result. No conclusion about the
  fix's effect on premature completion is possible from this interrupted run.

All earlier simulator sessions, including MiMo scene10 `80444`, are terminal.
Keep one simulator at a time. Read compact summaries or selected JSON fields;
never print a raw checker assertion or private report wholesale.

The next required independent proof is prepared in
`output/convergence-resume-20261008/run-mimo-fresh-map-attempt1.py`.
After session30357 is confirmed terminal, run it with the repo `.venv/bin/python`.
It invokes the canonical suite CLI for all six fresh MapBuild/cleanup trials,
serially across development0/10/12, using MiMo Responses and the committed
100-call /16M-token /3600s-wall /180s-stall per-trial bounds, zero retries.
It requires a clean checkout and an existing scene12 terminal artifact, records
code/content/command identity, and refuses to overwrite an existing attempt.
It has not launched; its prepared command is not live evidence.

## MiMo response-stall investigation

`output/convergence-resume-20261008/mimo-response-stall-investigation-attempt1.json`
compares sanitized timings from scene0, both scene10 attempts and the active
scene12. Both scene10 stalls occur inside nonstreaming `get_response`; their
unfinished inputs are164,137 and54,675 bytes. No provider error was emitted.
The SDK default read timeout is600s, longer than the frozen180s eval stall
guard, so missing error events cannot rule out an upstream or transport failure.
The guard intentionally ignores status heartbeats and observes actual progress.

The successful scene0/scene10-attempt2 response maxima are101.021/104.957s.
At the captured scene12 snapshot, the longest successful response is154.846s
with5,575 reasoning tokens. Slow reasoning is plausible, but local spans do
not distinguish provider queueing, generation and transport waiting for the
cancelled calls. Input size alone does not establish the cause either.
No product fix, timeout relaxation, thinking-mode change or retry is justified
by this evidence. The investigation closes with root cause unresolved; obtain
provider-side timing or a separately bounded transport-progress diagnostic
before another scene10 replay. The already running scene12 and required fresh
MapBuild proof can continue independently. No scope lock was acquired.

## Latest implementation and checks

- `ed7b6332`: `map_build_cleanup_convergence_v2` adds the plan's missing fresh
  MapBuild-to-cleanup pairs for development0/10/12 using existing ordered suite
  dependencies. It is a separate prior-consuming supplement, not a replacement
  for the15-case no-prior cohort. Builder samples require actual semantic
  enrichment and outcome grading; consumers require their own scene's fresh
  builder output and retain four-chain acceptance.14 focused tests pass;
  live proof is still missing. One provider's six trials cap600 calls /96M
  tokens /6 trial-hours; run serially with zero automatic retries. Blocked-mode
  preflight records all six trials as `model_or_provider_unavailable` with zero
  provider requests (`fresh-map-preflight-attempt1/proof-summary.json`). The
  full standard gate passes after this addition
  (`verify-after-fresh-map-cohort-attempt1.log`, session `8999`, exit0).
- `69de6d14`: prepared v2 suites/sample lists cover development0/10/12 and fixed reserved14/15,
  three seed7 trials each, separate DINO/world-label lanes and no prior reuse.
  Full/development external manifests pair the same cleanup, all three current
  open-ended cases and MapBuild for both external providers. They are not wired
  into the schedule and fixture readiness/final execution freeze remain pending.
  New sample grading requires four distinct complete successful cleanup chains
  reconstructed from public trace. Three negative regressions fail before the
  extension and pass after;65 focused checks pass. Offline verification of real
  development artifacts yields4/4/3 chains for scene0/10/12 and pass/pass/fail,
  without replacing the original attempts. Evidence:
  `convergence-manifests-focused-attempt2.log`,
  `complete-chain-existing-artifact-regrade.json` under the output root.
  Full gate attempt1 caught the grading module size limit; the new chain grader
  now has a focused eval owner, without baseline relaxation. Attempt2 loaded old
  assertions while the prepared-only schedule metadata was removed; final focused
  checks pass. Fixed-file full attempt3 PASSED (session `61771`, exit0,
  `verify-after-convergence-manifests-attempt3.log`).
- Actual committed CLI preflight at `ec5b2d1d` produces both shard plans,
  blocks the selected case with `live_execution_not_requested`, sends zero
  model requests, and retains all10 rows as blocked when merging incomplete
  evidence. Full:38 cases /3,632 calls /584M tokens /34 trial-hours /3,028
  runner-minutes. Development:26 cases /2,432 calls /392M tokens /22 trial-hours
  /1,996 runner-minutes. At most2 shards; zero automatic trial retries.
  Evidence: `convergence-v2-preflight-attempt1/proof-summary.json`.
  These are prepared/preflight identities, not a final accepted epoch or live
  full execution. Check fixture readiness and the material cost boundary before
  activating the full envelope; current schedule remains compact.
- `0c00fba2` completion-projection fix: remove the unconditional declaration
  navigation hint and strip completed-step controls from the composite response.
  Preserve atomic trace controls and evidence; emit one current outer completion.
  A regression reproduces the old no-candidate navigation contradiction and
  passes after repair. Focused tests and full `just agent::verify` pass (session
  `74286`, exit0). Logs: `completion-projection-before.log`,
  `completion-projection-after.log`, and
  `verify-after-completion-projection-attempt1.log` under the output root below.
  Seventeen actual DINO composite responses pass the same projection/evidence
  checks (`minimax-scene12-attempt3/completion-projection-live-check.json`).
  Premature-done causality remains unproven; the live replay hit provider quota.
  The response-contract investigation is closed and its owned scope lock released.
- `b3414001`: cumulative token enforcement at the SDK provider boundary. It
  reserves twice native context capacity for each transport attempt, settles
  known usage, retains unknown usage and shares a locked ledger across
  continuations. Hidden client retries and multi-arm racing are disabled for
  budgeted runs. Eval/showcase propagates explicit per-run limits.
- `6e32fe24`: decision counts persist across continuations; the Skill includes
  one bounded 0.5m forward reobservation after required four-heading recovery
  when its public conditions apply. Scene10 and scene12 current replays both
  contain **zero forward-recovery requests**; no causal strategy gain is proven.
- `b0ba995c`: token accounting resolves and retains the actual wire request
  model for MiMo Responses instead of trying to budget the opaque route `mimo`.
  Both supported names reproduce the old error and pass the regression after
  repair. The 35 budget tests and full standard gate pass; live MiMo responses
  settle in the ledger. That request-model investigation is closed.
  Gate: `output/convergence-resume-20261008/verify-after-mimo-request-model-attempt1.log`.
- `942570b3`: case sharding is implemented; focused and complete deterministic gates pass. The eval-owned
  `showcase_shards` CLI freezes clean code, full suite/sample content, models and
  budgets; executes independent sample/repetition cases through the existing
  showcase/eval CLI; and merges existing result bundles. Duplicate/incompatible
  evidence is rejected; missing cases block the row; trial failures stay intact.
  Trial identity now records the actual execution budgets. Merged reports retain
  links to original shard evidence without copying or rewriting those artifacts.
- Compact workflow wiring now plans five external case jobs, at most two
  concurrently, with provider-only secrets and protected-main gating. Setup is
  bounded to 20 minutes and upload to five. Cleanup jobs require 86 minutes,
  other current jobs 56. Compact envelope: 332 decision calls, 56M tokens,
  12600 trial seconds, 340 runner minutes. Full lists are not enabled.
- Sharding focused checks: 150 passed, including a complete 15-case threshold
  merge with three preserved behavioral failures and every report link.
  `output/convergence-resume-20261008/sharding-focused-attempt3.log`.
  Full gate attempt1 stopped at new helper complexity and the report module's
  size limit; those are repaired without increasing the ratchet baseline.
  Attempt2 passed (session `9436`, exit0):
  `output/convergence-resume-20261008/verify-after-case-sharding-attempt2.log`.

Real local case-sharding proof passes at `5830ce3d`: the canonical MiniMax
bread case executes once and merges into1/1 passed, zero failed/blocked, exact
16-call/1800s/120s-stall/4M-token/zero-retry identity. Runtime57.023s; six successful
responses, zero provider errors; ledger charged2,180,793 including a retained2M
unknown terminal reservation. This proves the real local CLI path, not hosted or
full-cohort acceptance. Evidence:
`output/convergence-resume-20261008/sharding-live-bread-attempt1/proof-summary.json`.

## Visual evidence and interpretation

All paths below are under `output/convergence-resume-20261008/`; each attempt
retains its exact contract and failure history.

| Attempt | Result | Evidence |
| --- | --- | --- |
| scene0 attempt2 | 3/5, coverage 1.0, zero disturbances; stopped despite public recovery requirement | `diagnosis-scene0-attempt2.json` |
| scene0 attempt3, after `f77db430` | Pass 4/5, four chains, coverage 1.0, zero disturbances, checker0; 867.553s | `minimax-scene0-attempt3/proof-summary.json` |
| scene10 attempt1 | Partial 3/5, three chains, coverage1.0, zero disturbances, checker0; 682.46s | `minimax-scene10-attempt1/proof-summary.json` |
| scene10 current replay at `6e32fe24` | Pass 4/5, four chains, coverage1.0, zero disturbances, checker0; 574.407s | `minimax-scene10-forward-attempt1/proof-summary.json` |
| scene12 attempt1 | Partial 3/5, coverage0.8; checker1 for unfinished coverage; 852.569s | `minimax-scene12-attempt1/proof-summary.json` |
| scene12 attempt2 at `9cf40333` | Partial 3/5, three chains, coverage1.0, zero disturbances, checker0; 978.706s | `minimax-scene12-attempt2/proof-summary.json` |

MiMo Responses scene0 attempt1 PASSED at the recorded `f39da4ea`+request-model
fix identity (engine fix committed as `b0ba995c`):4/5, four grounded chains,
sweep1.0, disturbances0, public ready before done, checker0,1701.077s.
Seventy-one model metrics, input/output5,234,605/21,903, no usage-span limitation;
ledger charged5,256,508 of16M. Twenty-six actual DINO observations with CUDA
stage provenance; model `IDEA-Research/grounding-dino-base`. Dollar cost
unavailable. Summary: `mimo-scene0-attempt1/proof-summary.json`.
This closes one of the three local-default development smoke scenes only.

MiMo Responses scene10 attempt1 is BLOCKED: `LiveEvalTimeoutError` after 180s
without progress awaiting the fifth model response, 259.103s total. Four model
responses succeeded; no provider error event or authoritative run result exists.
Input/output85,171/271; ledger charged485,442 of16M including a retained400K
unknown reservation. Terminal-response usage and dollar cost are unavailable.
Zero automatic trial retries. This is stalled infrastructure evidence, not a
capability pass or behavior failure. Summary: `mimo-scene10-attempt1/proof-summary.json`.
A subsequent zero-retry MiMo SDK readiness probe passes in2.086s; this establishes
current connectivity only, not scene10 completion. Evidence:
`mimo-readiness-after-stall-attempt1.json`; this readiness utility exposes no usage
or cost metrics (256 output-token cap, 30s transport timeout).

Scene12 attempt2 recorded 79 model metrics, input/output 7,225,018/18,140;
its ledger charged 9,243,158 of16M including a retained 2M unknown reservation.
Usage has a missing terminal-response-span limitation; dollar cost unavailable.
The 1.0 sweep metric measures waypoint visits. The last public completion still
names insufficient heading coverage at room3 (3/4) and rooms6/7/8/9 (1/4 each),
as well as insufficient grounded chains. The done reason explicitly acknowledges
these unfinished headings. Premature completion therefore remains unresolved;
checker0 is not readiness or capability acceptance.

Scene10 current replay used 60 successful responses, 18 real CUDA DINO
observations, input/output4,828,623/14,971 and ledger charge4,843,594 of16M.
The prior public-only viewpoint diagnostic compared 32 canonical/forward views
without model or manipulation calls. One view gained a recommendation while
another lost one; aggregate unique discovery gain is unproven. Private source
frame diagnosis was grader-only and did not select robot poses or queries.
Evidence: `scene10-viewpoint-diagnostic-attempt1/` and
`minimax-scene10-attempt1/source-frame-visibility-diagnosis.json`.

## Concrete external blockers

MiniMax scene12 attempt3 hits a non-retryable provider billing limit after44
successful responses. Keep MiniMax-dependent capability work blocked until
quota readiness is restored; do not change credentials or substitute providers
for its mandatory acceptance. MiMo work can proceed independently.

New reserved scenes **14/15, procthor-10k-val**, were fixed before this strategy
change. Old11/13 were inspected and cannot support a new unseen-holdout claim.
No new reserved images/behavior were reviewed and no scenes were substituted.

Both new reserved readiness attempts hit init timeout300s. Scene15's checked-in
Base Metric Map validates; scene14's map remains missing. Faulthandler places
the stall in archive download TCP connection setup before MuJoCo load.
Configured public R2 port443 and the official Hugging Face resource endpoint
both return curl28 connection timeout. No credentials/configuration changed.
Evidence under the same output root:
`reserved-readiness-attempt1/readiness.json`,
`reserved-init-diagnostic-attempt2.log`, `reserved-resource-blocker.json`,
`resource-endpoint-probe-attempt2.log`, `hf-resource-endpoint-probe.log`.
The current bounded recheck also times out on both official endpoints:
`resource-endpoints-attempt3.json`; no dependency, endpoint or credential changed.
Provider/DINO readiness itself passes; this is an asset-download blocker.

Remote protected `main` is still `becf890c65106b003c4ba07b0dc7797b53817fe8`.
Successful hosted runs37297221973 and36406210330 execute that historical code,
including retired Kimi; neither is current-code proof. Current implementation
must reach an authorized trusted ref before the new hosted proof can run.

## Preserved proof boundaries

- Three SDK provider readiness probes and managed real DINO readiness pass.
  `sdk-readiness.json` records active routes. MiMo TP currently resolves to
  `mimo-v2.6-pro`; do not infer a different model from stale summary text.
- Real MiniMax cumulative-token proof passes bread1/1 under4M; a separate
  one-token negative probe stops with zero outbound requests.
  `token-budget-live-attempt1/proof-summary.json`.
- Real decision-continuation proof records one outbound request and169 tokens,
  then denies a continuation before a second request.
  `decision-continuation-live-attempt1/proof-summary.json`.
- Both external compact bread/cleanup proofs and paired MiniMax static-full /
  no-skill control pass. These are local compact/world-label evidence, not a
  full external cohort, current hosted proof or causal Skill ranking.
- The historical real-DINO v1 identity ledger covers15 cases but fails
  acceptance. Preserved MiMo TP compatibility is2/3 with one blocked stall.
  Repair replays never rewrite those denominators.
- Historical artifacts remain under `output/convergence-visual/`,
  `output/convergence-compact/` and `output/eval-harness/20260928T113410Z/`.
  Related state: `docs/status/active/local-eval-baseline-refresh.md`,
  `state-first-context-manager.md`, `skill-delivery-multiscene-probe.md`.

## Remaining acceptance and next action

1. Collect MiMo scene12 attempt1 (session30357) before launching another simulator.
   Diagnose recurring MiMo scene10 response stalls before another repair attempt.
   Resume MiniMax scene12 only after billing readiness is restored; the response
   projection itself is verified and committed. Complete passing MiMo real-DINO smoke on development10/12 as separately
   recorded attempts under unchanged bounds.
   Scene0 is now passed with exact attempt identity above.
   Diagnose scene12 premature completion with unfinished mandatory headings
   before the new visual epoch; distinguish waypoint visits from heading coverage.
2. Obtain trusted current-code hosted proof. Both actual blocked-mode preflight
   and a real local provider case pass through the committed shard CLI; see
   `sharding-preflight-attempt1/proof-summary.json` and
   `sharding-live-bread-attempt1/proof-summary.json` under the output root above.
   Compact wiring/local proof alone do not establish hosted acceptance.
3. Resolve reserved14/15 asset readiness without scene shopping. Freeze exact
   executable epoch, scenes/seeds, fixture/map treatment, graders and budgets
   from the prepared v2 suites and full/development manifests. Preserve old v1.
4. Run MiniMax full real-DINO15-case cohort: >=12/15 overall, >=5/6 reserved,
   >=1 pass per scene, zero blocked; each pass requires >=4 grounded chains,
   sweep>=0.9, disturbances<=2 and authoritative done.
5. Complete matching MiniMax/MiMo TP world-label cohorts and current open-ended /
   MapBuild regressions, with aggregate usage/runtime envelopes and bounded
   hosted execution. Do not stitch code/content epochs or enable full schedules
   from compact proof.
   Also run the separate fresh DINO MapBuild-to-cleanup suite across all three
   development scenes; its prepared lists and blocked preflight are not live proof.
6. Assemble the plan's complete capability packet and reconcile docs only when
   required evidence supports completion. Baseline promotion stays separate.

## Stop/resume and no-touch scope

Continue ordinary in-scope implementation and independent proof. Stop for a
material provider/resource/cost expansion, credential/privacy change, durable
baseline/catalog publication or real-robot decision. One simulator at a time;
maximum two external shards; zero automatic trial retries. Preserve every
attempt, historical report and unrelated capsule. Do not move a real robot.
