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

Current visual development evidence: scene0 and scene10 pass at 4/5; the latest
MiniMax scene12 replay is terminal at 3/5 restored, with 3 complete chains and
9/10 waypoints visited. This is a behavioral/evidence failure, not a provider
failure. The plan's sweep >=0.9 is a grader lower bound; authoritative cleanup
runtime readiness still requires a complete public sweep before `done`.
MiniMax scene12 attempt3 is blocked by provider billing limit after removing
contradictory composite-tool controls. MiMo Responses scene0 passes; scene10
attempt1 is blocked by a model-response stall; attempt2 is now blocked by a
second stall after a successful connectivity probe.
MiMo Responses scene12 attempt1 is terminal: four distinct cleanup chains and
public readiness pass, but private restoration is3/5, so capability fails.
The fresh MapBuild/cleanup suite is terminal: four passed, one failed, one blocked.
All three builders pass; scene0 cleanup passes4/5, scene10 cleanup stalls, and
scene12 cleanup exhausts100 decisions with three chains and unfinished headings.
The backend support-attribution fix passes22 focused tests, the complete
repository gate, and a fresh real backend/CUDA DINO proof (`55f879d8`).
New-code scene12 agent cleanup verification is terminal: it reaches four
complete chains and authoritative `done`, but restores only3/5 targets.
A follow-up 50-view public scan with one bounded0.5m forward reobservation
per waypoint leaves the same visibility pattern: the private RemoteControl
has zero pixels, while Plate has only two low-pixel frames and no public Plate
candidate. This makes scene12 fixture/evidence readiness suspect; it does not
prove the case or the acceptance threshold impossible.
No development replay replaces an old failed cohort row. Full MiniMax real-DINO,
MiMo Responses smoke, matched external cohorts and trusted current-code hosted
proof remain required. No baseline/catalog or full schedule is promoted.

The 2026-10-12 fixed-prior probe reran all five rows that the previous focused
harness execution blocked because no Runtime Map Prior was supplied. Four rows
passed: MiniMax map-consumer, MiniMax open-ended, MiniMax cleanup (3/3 repeated
trials), and MiMo Responses map-consumer. MiMo TP map-consumer passed its
open-ended trial, while its cleanup trial stalled after 32 successful model
responses and remains `environment_blocked` under the unchanged 180-second
stall guard. The prior omission is therefore an execution/configuration gap,
and the TP stall is provider/runtime reliability evidence; neither shows that
the capability thresholds are impossible. Artifacts are retained under
`output/eval-harness/20261012T-fixed-prior-*-live/`.

The current evidence classification is: scene12's 3/5 restoration is a real
case-level capability/evidence miss; scene14 is fixture-infeasible for the
five-target contract; scene15 has public Plate evidence but still lacks a
public RemoteControl candidate; and the 9/10 sweep case is correctly
incomplete because authoritative cleanup `done` requires a complete public
sweep even though the written 0.9 value is a grading lower bound. Keep the
12/15 and 5/6 thresholds unchanged.

The latest scene15 diagnostic (`scene15-feasibility-forward-live-attempt2/`)
replayed the fixed 50-view public-DINO scan with zero provider calls and found
four actionable public Plate candidates but no public RemoteControl candidate.
An offline threshold/query diagnostic on the one selected private-pixel frame
returned a default-threshold remote candidate at IoU0.0 against the private
target; relaxed thresholds produced more low-confidence candidates without a
target match. This keeps scene15 visual readiness open without establishing a
detector code defect.

Fixed-prior rerun identities and outcomes:

| Row | Outcome | Evidence |
| --- | --- | --- |
| `map-build-consumer-openai-agents-sdk-minimax-responses` | PASS | 2/2 trials; map consumer and open-ended anchor pass |
| `map-build-consumer-openai-agents-sdk-mimo-responses` | PASS | 2/2 trials; cleanup restoration 1.0 |
| `map-build-consumer-openai-agents-sdk-mimo-tp-openai-chat` | BLOCKED | open-ended pass; cleanup stalled after 32 successful responses at the unchanged 180s guard |
| `openai-agents-sdk-open-task-live-eval` | PASS | 3/3 open-ended cases pass |
| `openai-agents-sdk-cleanup-live-eval` | PASS | 3/3 repeated cleanup trials pass; restoration 0.8/1.0/1.0 |

All rows consumed the same current-code world-public Runtime Metric Map prior
from `output/eval-harness/20261011T154346Z/rows/direct-map-build-world-public/run/1012_0000/seed-7/runtime_metric_map.json`.

## Latest live work — all listed sessions are terminal

MiniMax scene12 attempt4 is terminal and FAILED checker validation. It started
clean at `f960e7ab` with real CUDA DINO, static-full, scene12 seed7, five targets
and a fresh Runtime Metric Map. After1048.777s and 90 successful model
responses, it produced 3/5 restoration, 3 complete grounded chains, 0
disturbances and 9/10 waypoints, then failed outcome/checker validation. The
missed targets were RemoteControl and Plate; no executed target misplacement is
proven by this artifact. This is a case-level capability/evidence miss, not
proof that the global 12/15 or 5/6 threshold is impossible. The plan's sweep
>=0.9 remains a grading lower bound; the runtime's full-sweep readiness gate is
intentional, so this attempt's 9/10 coverage is incomplete rather than evidence
of a threshold bug.

MiMo Responses scene12 attempt1 is terminal, session `30357` consumed:

- Wrapper/log: `output/convergence-resume-20261008/replay-mimo-scene12-attempt1.py`
  and matching `.log`; root `mimo-scene12-attempt1/` under that output directory.
- Clean start at `ed7b6332`, real CUDA DINO, static-full, scene12 seed7, five
  targets, fresh Runtime Metric Map. Canonical route `mimo`, request model
  `xiaomi/mimo-v2.6-pro`.
- Same100-call /16M-token /3600s-wall /180s-stall bounds, zero automatic retries.
- Terminal at2507.643s with `partial_success`: 41 successful model responses,
  zero provider errors, 35 CUDA-DINO observations, 4 distinct public grounded
  cleanup chains, sweep coverage1.0 and disturbances0. Authoritative private
  scoring restored3/5 (0.6), so this is not a capability pass. The public
  completion snapshot was `ready` before `done`. Placement diagnostics confirm
  four distinct physical objects: three restored targets and one non-target;
  two targets were unacted. No executed action misplacing a target is proven.
  Input/output tokens2,834,447/48,079; ledger charged2,882,526 of16M; dollar cost
  unavailable. `proof-summary.json` and `outcome-diagnosis.json` retain the result.

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

All earlier simulator sessions, including MiMo scene12 `30357`, are terminal.
Keep one simulator at a time. Read compact summaries or selected JSON fields;
never print a raw checker assertion or private report wholesale.

The fresh MapBuild/cleanup suite is TERMINAL; session `8816` is consumed.
Wrapper: `output/convergence-resume-20261008/run-mimo-fresh-map-attempt1.py`.
Root: `output/convergence-resume-20261008/mimo-fresh-map-attempt1/`.
It ran the canonical six-trial suite serially with MiMo Responses, actual CUDA
DINO, static-full,100 calls /16M tokens /3600s wall /180s stall per trial,
zero retries. Clean start `b8da0503`; only docs changed through suite termination
at `7ee92fa2`. All frozen suite/sample content hashes match. Elapsed8383.181s;
CLI exit0 does not imply acceptance. `proof-summary.json` links canonical results:
**4 passed,1 failed,1 blocked; full suite acceptance incomplete**.

| Scene | MapBuild | Cleanup consuming its fresh map |
| --- | --- | --- |
| 0 | Pass;974.261s,67 successful responses | Pass;927.514s,52 responses,4/5 restored,4 chains,sweep1.0,zero disturbances |
| 10 | Pass;890.209s,43 responses | Blocked;2058.316s,85 responses,180s model-response stall,3 placements,no authoritative result |
| 12 | Pass;1408.267s,78 responses | Failed `budget_exhausted`;2112.758s,100 responses,3 chains,unfinished public heading coverage,no authoritative result |

All successful rows pass artifacts/privacy/trajectory/outcome grading. All six
record zero provider errors. Scene0's map digest is
`fe974be564d40ea650dd7a81f87176b4bf33c02830149497bb4a2c457a33a463`;
its consumer imports188 records and passes dependency grading.
Scene0 builder has12 enriched anchors/8 stable categories/188 objects/221
candidates; scene10 has5/4/100/117. Scene12 required MapBuild quality passes in
the canonical bundle. Per-trial maps, usage, token ledgers and tool counts are
in the proof summary; dollar cost unavailable. Successful done runs retain
missing terminal-response usage reservations. Scene10 usage recovered from86
span rows: input/output4,598,773/32,747, unfinished response unknown; original
metrics are not overwritten. Scene12 cleanup input/output6,646,944/28,774,
no usage limitation. These are first-attempt results, not replacement rows.

All six-trial and diagnostic simulator sessions are terminal. Sessions `27674`
(real backend/DINO) and `23229` (full gate) completed successfully and are consumed.

The new-code MiMo scene12 no-prior development smoke, session `30722`, is
terminal. It started clean at `55f879d8`. Wrapper/log:
`output/convergence-resume-20261008/replay-mimo-scene12-support-attempt1.py`
and matching `.log`; root `mimo-scene12-support-attempt1/` under that directory.
Canonical sample `cleanup.convergence_v2.dino.scene12.seed7`, repetition0 only,
static-full, actual CUDA DINO, request `xiaomi/mimo-v2.6-pro`. Bounds remain
100 calls /16M tokens /3600s wall /180s stall, zero retries. Preserve executable
identity during this run. The run has100 successful MiMo responses, zero provider
errors, four complete chains, sweep1.0 and authoritative `done`; private
restoration is3/5. This single development trial cannot replace old rows or
establish a complete cohort; no baseline promotion.

The scene12 public/private mismatch was investigated after termination. The
four chain count comes from four distinct public observed handles, each with a
complete nav→pick→nav→place sequence. Joining placement diagnostics with private
scoring (grader only) proves four distinct physical objects, three restored
targets and one non-target. Both remaining targets were unacted. Earlier wording
claiming an incorrect target placement was unsupported and is superseded here.
This fails the existing0.8 restoration requirement; public readiness remains
independent of private scoring. Diagnose missing discovery/actionability from
public trace before proposing a strategy change. The bounded follow-up scan is
retained at
`output/convergence-resume-20261008/scene12-feasibility-forward-live-attempt1/`;
it adds ten observations but no Plate candidate and does not expose a physical
identity link for the one RemoteControl category candidate.

## Support-attribution investigation — verified repair

The backend `scenario_state.nearest_receptacle` assigns supports by XY distance
to furniture body origins, ignoring support extent and height. Private geometry
diagnosis proves one unchanged direct-support scene12 object is on a countertop
but assigned to an adjacent desk. This affects location/scoring and may feed
visual candidate support estimates. It does not prove the missed discovery was
caused by attribution: the unacted target remote has zero segmented pixels in
all recorded frames, and the public remote candidate previously examined is a
different physical object. The other unacted target appears in two frames,
including one detector source. Evidence stays grader-only; do not use private
target geometry for agent inputs or pose/query selection.

The implementation now ranks3D distance to existing support rectangles, using
recorded3D points for fixtures without surface geometry. No seeded hints,
target identities, thresholds or scene-specific data enter the implementation.
Five new repository regression tests fail before the change and pass after;
all22 new/affected checks pass. Offline candidate comparison covers35 unchanged
direct-support placements across four old runs: two incorrect old attributions
become correct, zero sample regressions. Old outcomes remain unchanged.

Code: `roboclaws/backends/molmospaces/scenario_state.py`; tests:
`tests/unit/molmo_cleanup/test_support_attribution.py`.
Artifacts under `output/convergence-resume-20261008/`:
`support-attribution-repo-before.log`, `support-attribution-repo-after.log`,
`support-attribution-offline-attempt1.json`,
`verify-after-support-attribution-attempt1.log` (exit0), and
`support-attribution-live-attempt1/proof-summary.json` (passed).
The completed live diagnostic freezes scene12/seed7, all public inspection waypoints and
four headings, real DINO, zero provider calls/retries, one simulator,900s cap.
Private geometry is read only after scanning for attribution grading. Its
contract captures HEAD plus working diff/source hashes; no agent acceptance is
claimed. Scene12 target visibility history remains in
`mimo-scene12-attempt1/unacted-target-visibility-counts.json`.

Live proof completed in504.086s:40 public views,280 CUDA stages using
`IDEA-Research/grounding-dino-base`,15 unchanged direct-support placements.
Old attribution is wrong once; repaired attribution is correct for all15, with
zero regressions. The original scene12 defect is reproduced and eliminated.
No model calls or manipulation occurred; missing target discovery and agent
cleanup completion remain unproven by this diagnostic.

The terminal fresh-map scene12 public work audit is retained in
`mimo-fresh-map-attempt1/scene12-consumer-public-work-accounting.json`.
It records100 top-level requests:10 identical empty-argument map calls before
navigation,40 composite observations,27 relative moves,11 waypoint navigations
and12 manipulation-chain steps. Final public completion lacks a fourth chain
and heading coverage at three waypoints. The first observation correctly
prioritizes an unvisited waypoint, so a conflicting sweep/heading priority was
not reproduced. Model text is not retained; repeated-call causality remains
unresolved. Read-only investigation `32626-1791455096-dc522e19` is closed with
that limitation, no lock, code change, budget relaxation or retry.

The full `just agent::verify` passes. Investigation
`32626-1791447476-2d91d8ca` is closed successfully; its owned scope was released
and root-cause learning recorded.

New-code scene12 smoke `mimo-scene12-support-attempt1` is terminal and FAILED
outcome grading: started clean at `55f879d8`, elapsed2255.848s,100 successful
MiMo Responses,0 provider errors,0 retries, input/output7,328,201/42,221,
ledger7,370,422 of16M. It reaches authoritative `done`, sweep1.0, disturbances0
and four complete cleanup chains, but restoration is3/5 (0.6); artifacts,
privacy and trajectory pass, outcome fails. The two wrong target identities are
RemoteControl and Plate; three accepted are Bowl, Book and Pillow. This is a
new-code development result, not a replacement for the original cohort and not
capability acceptance. The public run and private grader remain separate under
`output/convergence-resume-20261008/mimo-scene12-support-attempt1/`.

The support attribution repair therefore passes its own geometry/DINO proof but
does not solve scene12 target discovery/actionability. The new run's unchanged
RemoteControl seed remains on CounterTop; Plate remains an unacted seed on Sofa
in grader diagnostics. Do not infer that either target was misplaced by an
executed action. Keep this failure as the current scene12 bottleneck.

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
before another scene10 replay. Scene12 subsequently completed without a stall;
the fresh MapBuild suite later completed with scene10 stalled again. No scope lock was acquired for the response-stall investigation.

## Latest implementation and checks

- `ed7b6332`: `map_build_cleanup_convergence_v2` adds the plan's missing fresh
  MapBuild-to-cleanup pairs for development0/10/12 using existing ordered suite
  dependencies. It is a separate prior-consuming supplement, not a replacement
  for the15-case no-prior cohort. Builder samples require actual semantic
  enrichment and outcome grading; consumers require their own scene's fresh
  builder output and retain four-chain acceptance.14 focused tests pass;
  live proof is partial (4/6 passed; see terminal suite above). One provider's six trials cap600 calls /96M
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
or cost metrics (256 output-token cap, 30s transport timeout). A fresh three-call
micro-readiness run also passes in5.9/11.9/14.0s. A bounded payload diagnostic
returns explicit `incomplete/max_output_tokens` with reasoning-only usage for
32KB and128KB prompts, rather than a transport error; this explains the
empty-output health probe but does not explain the180s scene10 stall. Evidence:
`mimo-micro-readiness-attempt1.json`,
`mimo-payload-response-diagnostic-attempt1.json` and
`mimo-payload-response-diagnostic-attempt2.json`. A 32KB request with a
4096-token cap also consumes the full cap as reasoning and returns incomplete
in18.6s; this confirms high-reasoning behavior but still does not reproduce the
180s transport stall. Evidence: `mimo-payload-response-diagnostic-attempt3.json`.

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

The first reserved readiness attempt hit init timeout300s for both scenes;
scene15's checked-in Base Metric Map validated while scene14's map was missing.
The follow-up endpoint check reached the configured R2 host (root `404`) while
the official Hugging Face endpoint still timed out. A new readiness attempt
then loaded both maps: scene15 is structurally ready with5/5 feasible targets,
while scene14 fails the five-target contract because its fixed seed7 scene has
only2 objects that satisfy the current cleanup rules. The latest 50-view
scene15 real-DINO scan finds four actionable public Plate candidates but no
public RemoteControl candidate despite two private-pixel frames, so visual
readiness is still open. Its grader-only offline query/threshold diagnostic
found one default-threshold remote candidate with IoU0.0 against the private
target; relaxed thresholds added low-confidence candidates without a target
match. This does not establish a detector-threshold code bug. No
credentials/configuration changed.
Evidence under the same output root:
`reserved-readiness-attempt1/readiness.json`,
`reserved-init-diagnostic-attempt2.log`, `reserved-resource-blocker.json`,
`resource-endpoint-probe-attempt2.log`, `hf-resource-endpoint-probe.log`.
The endpoint rechecks are `resource-endpoints-attempt3.json` and
`resource-endpoints-attempt4.json`; the new fixture result is
`reserved-readiness-attempt2/readiness.json`. Visual evidence is in
`scene15-feasibility-forward-live-attempt1/fixture-feasibility-grader-summary.private.json`
and the current `scene15-feasibility-forward-live-attempt2/proof-summary.json`.
The offline detector diagnostics are
`scene15-remote-dino-threshold-diagnostic/summary.private.json` and
`scene15-remote-dino-threshold-diagnostic-attempt2/summary.private.json`.
Scene14 is now classified as a fixture-content blocker rather than a download
blocker, and scene15 has a remaining visual-evidence blocker; do not substitute
a scene or change the target threshold without a new case-epoch decision.
Provider/DINO readiness itself passes.

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

1. Treat scene12 as a fixture/evidence-readiness issue pending a case-epoch
   decision, while keeping the acceptance threshold unchanged. The current
   evidence does not justify calling the threshold impossible or blaming a
   single planner bug: RemoteControl is unobservable in the sampled public
   views, and Plate is visible only at low pixel count without a public
   candidate. No support-attribution change is justified by this run. Complete
   passing MiMo real-DINO smoke on development10/12 and all
   three fresh MapBuild pairs under a new consistent executable epoch.
   Diagnose recurring MiMo scene10 response stalls before another retry; resume
   MiniMax only after billing readiness is restored. Do not relax budgets or
   substitute development passes for required cohorts.
2. Obtain trusted current-code hosted proof. Both actual blocked-mode preflight
   and a real local provider case pass through the committed shard CLI; see
   `sharding-preflight-attempt1/proof-summary.json` and
   `sharding-live-bread-attempt1/proof-summary.json` under the output root above.
   Compact wiring/local proof alone do not establish hosted acceptance.
3. Resolve reserved14/15 readiness without scene shopping. Scene15 is
   structurally ready but still needs visual evidence for RemoteControl;
   scene14 needs a case-epoch decision because its fixed seed7 contains only2
   eligible cleanup targets. Freeze exact executable epoch, scenes/seeds,
   fixture/map treatment, graders and budgets from the prepared v2 suites and
   full/development manifests. Preserve old v1.
4. Run MiniMax full real-DINO15-case cohort: >=12/15 overall, >=5/6 reserved,
   >=1 pass per scene, zero blocked; each pass requires >=4 grounded chains,
   sweep>=0.9, disturbances<=2 and authoritative done.
5. Complete matching MiniMax/MiMo TP world-label cohorts and current open-ended /
   MapBuild regressions, with aggregate usage/runtime envelopes and bounded
   hosted execution. Do not stitch code/content epochs or enable full schedules
   from compact proof.
   Also run the separate fresh DINO MapBuild-to-cleanup suite across all three
   development scenes; its first live attempt passes only scene0's complete pair.
6. Assemble the plan's complete capability packet and reconcile docs only when
   required evidence supports completion. Baseline promotion stays separate.

## Stop/resume and no-touch scope

Continue ordinary in-scope implementation and independent proof. Stop for a
material provider/resource/cost expansion, credential/privacy change, durable
baseline/catalog publication or real-robot decision. One simulator at a time;
maximum two external shards; zero automatic trial retries. Preserve every
attempt, historical report and unrelated capsule. Do not move a real robot.
