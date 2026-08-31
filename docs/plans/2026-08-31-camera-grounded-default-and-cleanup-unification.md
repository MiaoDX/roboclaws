# Camera-Grounded Default And Cleanup Strategy Unification

**Status:** PROPOSED - agent planning loop complete; awaiting human approval  
**Created:** 2026-08-31  
**Last reviewed:** 2026-08-31  
**Owner:** Household World maintainers  
**Related ADRs:** ADR-0138, ADR-0143  

## Decision Summary

Converge household cleanup on one lane-neutral strategy after perception has
produced validated public observed handles:

```text
perception adapter
  -> validated observed handles in Agent View
  -> cleanup_worklist
  -> drain actionable local candidates
  -> resume bounded waypoint sweep when evidence or destinations are missing
  -> navigate / pick / place
  -> completion readiness
  -> done
```

Make detector-backed `camera-grounded-labels` with
`camera_labeler=grounding-dino` the omitted product default only after a real
sidecar-backed cleanup proof passes. Keep `world-public-labels` as an explicit
deterministic, CI, contract-test, and diagnostic baseline. Forward-retire
`camera-raw-fpv` from active product surfaces if it cannot enter the same
observed-handle seam without lane-specific cleanup scheduling or recovery
policy.

This is a public default and active-surface migration. Implementation starts
only after human approval of this plan. Cloud promotion, physical robot motion,
and provider expansion require separate decisions.

## Problem

The repository exposes three evidence lanes, but perception and task strategy
are not cleanly separated:

- `world-public-labels` is the proven cleanup baseline and remains explicit in
  current cleanup/open-ended eval samples and examples.
- `camera-grounded-labels` has the right detector-sidecar contract for both
  simulation and real cameras, but current default ownership is fragmented.
- `camera-raw-fpv` carries its own image transport, heading coverage, bbox,
  revisit, candidate-budget, continuation, and one-candidate policy. It is more
  than an input adapter and has not produced an acceptable product result.
- Live-agent cleanup uses local worklist draining, while deterministic
  direct-runner behavior is closer to scan-first cleanup.

There is also false-positive acceptance evidence. The showcase manifest labels
the accepted map-build row `camera-grounded-labels`, but `showcase.py` does not
forward the row's lane or camera labeler into the eval command. The selected
sample owns `world-public-labels`, and the resulting artifacts report:

```text
evidence_lane=world-public-labels
visual_grounding_pipeline_id=sim
producer=simulator_visible_object_detections
```

That artifact is valid world-label map-build evidence, but it is not Grounding
DINO evidence and cannot justify a product-default migration.

## Appetite

Maximum justified investment: one bounded architecture migration with two
live proof gates. Target 3-5 engineering days before physical-robot work.

Stop and reshape rather than extending the appetite into detector benchmarking,
large threshold searches, model training, provider matrices, or physical motion.

## Architecture Contract

### One post-registration strategy

Lane-specific behavior is allowed only before a public observed handle is
validated. After registration, cleanup scheduling, destination resolution,
tool ordering, recovery, worklist projection, completion readiness, and `done`
must not branch on evidence lane.

The existing Agent View, Model-Declared Observation, observed-handle lifecycle,
and `cleanup_worklist` form the seam. Do not add a parallel perception plugin
framework or a second worklist abstraction.

Acquisition calls may differ:

| Lane | Adapter acquisition | Shared output |
| --- | --- | --- |
| `world-public-labels` | sanitized runtime observation | validated observed handle |
| `camera-grounded-labels` | camera observation -> detector sidecar -> candidate declaration | validated observed handle |
| candidate future image lane | image producer -> candidate declaration | validated observed handle |

Tool traces do not need to be identical before registration. Observable
worklist/action/readiness behavior must be equivalent after registration.

### Product and baseline roles

- Omitted product launches and Operator Console workflows should resolve to
  `camera-grounded-labels` plus `grounding-dino` after proof and migration.
- The low-level launch grammar continues to accept explicit public axes.
- Deterministic evals, smoke, contract tests, and fault isolation explicitly
  request `world-public-labels`; they must not silently inherit the product
  default.
- Missing DINO readiness, model weights, image access, or sidecar availability
  fails closed with actionable blocked evidence. No simulator-label, fake,
  world-label, or alternate-detector fallback is allowed.
- Private scoring truth remains grader-only and may not enter detector requests,
  Agent View, observed handles, or cleanup worklists.

### Raw-FPV retirement rule

Run one bounded structural fit assessment before deletion. `camera-raw-fpv`
remains active only if it can:

1. turn image evidence into the existing validated observed-handle shape;
2. use the same downstream worklist, action, recovery, and readiness policy;
3. avoid lane-specific task scheduling after handle registration; and
4. pass the bounded deterministic contract proof without adding a compatibility
   layer.

If any condition fails, forward-retire it from active launch/profile choices,
Operator Console, current Agent Skill instructions, prompts, continuation
policy, eval catalog, and current human docs. Remove orphaned runtime and test
code. Preserve historical ADRs, retrospectives, and artifact readers as history.
There is no deprecated alias or silent fallback. A future reintroduction must
implement the shared observed-handle contract as a new reviewed change.

## Execution Plan

### Phase 0: Lock identity and sources of truth

1. Reproduce the showcase manifest-to-runtime lane drift with a deterministic
   focused test.
2. Choose one canonical owner for each identity:
   - product default: typed launch catalog;
   - eval execution lane and camera labeler: versioned eval sample;
   - showcase row: selection and expected-identity assertion, not an unchecked
     execution override.
3. Propagate requested lane, camera labeler, effective perception mode, producer,
   and pipeline identity through resolved launch plan, child arguments,
   `run_result.json`, reports, and eval results.
4. Fail the run/eval when requested and effective identity differ.
5. Mark the existing Kimi map-build artifact as world-label evidence in status
   and planning records; do not relabel or delete the immutable run.

Phase gate:

- a row/sample mismatch fails before capability promotion;
- grounded identity cannot pass with `pipeline_id=sim`, simulator producers, or
  zero detector candidate events;
- deterministic world-label baselines retain their current identity and pass.

### Phase 1: Establish the shared cleanup strategy seam

1. State one canonical invariant in `skills/household-world/SKILL.md`:
   observe a waypoint, drain current actionable candidates, continue bounded
   discovery only for missing evidence/destinations, resume the next unvisited
   waypoint after the local worklist is drained, and call `done` once readiness
   is ready.
2. Keep perception-specific instructions limited to candidate acquisition and
   registration.
3. Make world-label and detector-declared observations produce equivalent
   observed-handle lifecycle, actionability, public destination policy,
   worklist, and completion shapes.
4. Align direct-runner and live agent at the strategy-invariant level. Do not
   require identical internal calls, but reject scan-all-then-clean when an
   actionable local candidate should be drained.
5. Repair policy-trace/report evidence so it proves prompt action after an
   actionable worklist and labels coverage observes separately from post-place
   verification.

Phase gate:

- equivalent world-label and detector fixtures yield equivalent downstream
  worklist/readiness transitions;
- downstream task policy does not read `evidence_lane`;
- no new strategy-mode matrix or adapter framework is introduced;
- privacy and terminal-`done` contracts remain unchanged.

### Phase 2: Normalize Grounding DINO acquisition

1. Use the existing detector-only HTTP sidecar and Model-Declared Observation
   contract.
2. Prefer the existing `observe_camera_grounded_candidates` composite tool for
   OpenAI Agents SDK so observe and declaration remain one adapter operation
   while retaining both underlying trace events.
3. Ensure direct-runner uses the same declaration/observed-handle seam rather
   than a separate cleanup strategy.
4. Add guarded preflight for `.venv-visual-grounding`, CUDA/runtime readiness,
   model weights, image artifact access, sidecar port, and startup latency.
5. Write terminal blocked artifacts on unavailable detector infrastructure;
   never fall back.

Phase gate:

- a real FPV image reaches an external Grounding DINO process;
- candidate evidence records model/pipeline provenance, bbox, confidence,
  source observation, and public handle registration;
- no simulator-projected label is accepted as detector output.

### Phase 3: Prove detector-backed cleanup in simulation

Run serially after deterministic gates:

1. one MolmoSpaces direct-runner cleanup through the real DINO sidecar;
2. one Kimi OpenAI Agents SDK cleanup through the same sidecar and shared Skill.

The proof must record:

- requested and effective lane `camera-grounded-labels`;
- camera labeler and external pipeline `grounding-dino`;
- `perception_mode=camera_model_policy`;
- non-`sim` producer/pipeline provenance;
- nonzero camera candidate and observed-handle registration events;
- candidates entering the normal cleanup worklist;
- shared local-drain strategy evidence;
- complete report/assets/privacy bundle;
- cleanup capability pass: at least 4/5 restored, at least 90% sweep, at most
  two disturbances, and authoritative terminal `done` within the declared
  safety envelope.

Permit only a small, documented DINO threshold adjustment within existing
configuration. Stop if success requires detector-specific destination logic,
cleanup scheduling, broad prompt exceptions, model training, or a larger
threshold search.

### Phase 4: Prove camera-contract portability without robot motion

Use a fixed, reviewable real-camera corpus from the supported robot camera
contract. Do not command physical motion.

Prove that the same sidecar request/response, provenance, declaration,
observed-handle, worklist, and report schema works for real-camera frames with
bounded readiness and latency. This proves contract deployability, not
real-robot cleanup capability; reports and docs must state that distinction.

Phase gate:

- detector readiness and latency fit the documented operator envelope;
- representative cleanup objects produce reviewable candidate evidence;
- no simulator metadata is required;
- the same registration and worklist code is exercised.

If a suitable fixed corpus is unavailable, record a concrete blocker and do
not promote the default based on simulation alone.

### Phase 5: Atomically migrate the product default

Only after Phases 0-4 pass:

1. Make the typed launch catalog the canonical omitted evidence-lane default
   for cleanup, map-build, and open-ended household product launches.
2. Default `camera_labeler=grounding-dino` with that lane.
3. Align Operator Console, prompt preview, server/runner defaults, public
   examples, README, just docs, and report rerun commands.
4. Keep all deterministic world-label samples and commands explicit.
5. Update showcase/eval rows so grounded acceptance selects a grounded sample
   and asserts effective identity; retain separately named world-label controls.
6. Add a short ADR recording the public default, the post-registration
   lane-neutral strategy, baseline role, no-fallback rule, and conditional
   Raw-FPV retirement. Explicitly supersede the conflicting active-lane portion
   of ADR-0143 while preserving its historical rationale.

Phase gate:

- every omitted product entrypoint resolves to grounded+DINO;
- every baseline entrypoint explicitly resolves to world labels;
- requested/effective/report identity agrees across the launch matrix;
- unavailable DINO produces a clear blocked result rather than alternate input.

### Phase 6: Apply the Raw-FPV fit decision and remove dead paths

Run the structural fit assessment defined above. If it fails, execute the
forward retirement in the same approved plan:

1. remove `camera-raw-fpv` from active evidence-lane/profile catalogs and
   compatibility routing;
2. remove its active Skill/prompt/continuation/budget/revisit/heading strategy;
3. migrate or delete in-repo callers and tests that keep the retired surface
   alive;
4. retire `skills/raw-fpv-visual-labeler` from active skill distribution;
5. update current architecture and human docs while retaining historical
   artifacts and retrospectives;
6. run a changed-scope entropy pass and remove orphaned helpers and flags.

If Raw-FPV passes the fit assessment, keep it only as an explicit experimental
perception adapter. It receives no separate cleanup strategy, is not the
default, and must not add product-default fallback behavior.

## Verification

Deterministic gates:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q <focused showcase/launch/evidence-lane tests>
./scripts/dev/run_pytest_standalone.sh -q <focused MCP/worklist/readiness tests>
./scripts/dev/run_pytest_standalone.sh -q <focused operator-console/report tests>
just agent::eval recommend plan=docs/plans/2026-08-31-camera-grounded-default-and-cleanup-unification.md budget=focused
just agent::eval execute plan=docs/plans/2026-08-31-camera-grounded-default-and-cleanup-unification.md budget=focused
```

Live and external proofs run only after guarded preflight and remain serial:

```text
real Grounding DINO sidecar readiness
-> detector-backed MolmoSpaces direct cleanup
-> detector-backed MolmoSpaces Kimi cleanup
-> fixed real-camera offline portability proof
```

Final active-surface proof:

- no implicit `world-public-labels` product defaults remain;
- no grounded path can report `sim` or world-label provenance;
- no lane-specific cleanup policy remains after observed-handle registration;
- if retired, no active Raw-FPV route/profile/Skill/eval/current-doc references
  remain, excluding historical ADRs, retrospectives, and retained artifacts;
- world-label deterministic controls, grounded product paths, privacy, report
  assets, timeout finalization, and terminal `done` all pass.

Use `./scripts/dev/run_pytest_standalone.sh` rather than bare pytest on this
host because ROS site-packages leak into collection.

## Stop Gates

Stop and report rather than weakening the contract when:

- requested lane, effective lane, producer, or report identity disagrees;
- DINO dependencies, weights, image access, or sidecar readiness are missing;
- detector output depends on simulator state or a fake transport;
- detector candidates cannot enter the standard observed-handle/worklist seam;
- grounded cleanup needs lane-specific task strategy after registration;
- bounded DINO recall cannot meet the cleanup capability threshold;
- the fixed real-camera portability proof is unavailable or fails;
- private scoring/destination truth enters public evidence;
- physical robot movement, cloud execution, provider concurrency, or a new cost
  class would be required.

If Phases 3 or 4 fail, keep `world-public-labels` as the product default and
record grounded+DINO as experimental. The shared-strategy and identity fixes
remain valuable; default migration stops. Raw-FPV retirement may proceed only
as an explicitly reviewed simplification, not as evidence that DINO succeeded.

## Non-goals

- Physical robot navigation or manipulation.
- Claiming real-robot cleanup capability from an offline camera corpus.
- Cloud promotion or provider-matrix expansion.
- Multi-detector ranking, model training, or broad threshold optimization.
- A configurable cleanup scheduling matrix.
- A new general perception plugin framework.
- Backward-compatible aliases for retired evidence lanes.
- Deleting historical reports, retrospectives, or superseded decision records.

## Cut Order

If the appetite is exceeded, cut in this order while preserving the core
decision quality:

1. additional Kimi repetitions beyond the single required grounded proof;
2. report presentation polish beyond accurate identity and sequence labels;
3. cleanup of historical/non-active Raw-FPV references;
4. Raw-FPV structural salvage attempt, proceeding directly to the approved
   retirement decision;
5. default migration, if real-camera portability evidence is unavailable.

Never cut identity correctness, no-fallback behavior, privacy, the shared
strategy contract, or the real detector-backed simulation proof.

## Definition Of Done

The plan is complete when:

1. requested and effective evidence identity is fail-closed and auditable;
2. world-label and grounded adapters converge on one post-registration cleanup
   strategy and equivalent worklist/readiness behavior;
3. real Grounding DINO passes deterministic/direct and Kimi cleanup proof in
   MolmoSpaces with honest provenance;
4. fixed real-camera frames pass the same detector/registration contract without
   simulator dependencies;
5. omitted product launches consistently default to grounded+DINO while
   world-label controls remain explicit;
6. Raw-FPV either conforms as an explicit adapter or is fully removed from
   active surfaces without compatibility shims;
7. the new ADR and current human docs describe the durable contract and honest
   capability boundary; and
8. all focused and eval-selected verification gates pass.

## Planning Loop Judgment

Round 1 used independent plan-entropy, document-grill, and skeptic scouts.
Their findings converged, so no Round 2 was needed.

Accepted:

- identity/provenance correction is Phase 0 and invalidates current grounded
  acceptance claims without deleting immutable evidence;
- use the existing observed-handle/worklist seam instead of a new framework;
- unify strategy after registration, not acquisition calls;
- require real detector-backed cleanup and fixed real-camera portability proof
  before changing the default;
- retain explicit world-label baselines;
- make missing detector infrastructure fail closed;
- conditionally forward-retire Raw-FPV and remove its specialized task policy;
- record the durable public decision in a new ADR because ADR-0138 does not own
  the default and ADR-0143 conflicts with active Raw-FPV retirement.

Rejected:

- treating a manifest string, mocked detector, simulator projection, or
  `pipeline_id=sim` as Grounding DINO proof;
- adding multiple cleanup strategy modes;
- requiring identical pre-registration tool traces across inputs;
- adding a generalized adapter/plugin framework;
- using simulation proof to claim physical-robot cleanup capability;
- keeping deprecated aliases or silent fallbacks.

Parked:

- detector bakeoffs beyond Grounding DINO;
- physical robot manipulation;
- cloud/provider reliability matrices;
- future raw-image agent research after active Raw-FPV retirement.

## Human Approval Gate

Approval of this plan authorizes the full phased migration, including:

- making grounded+DINO the omitted product default only after all proof gates;
- retaining world labels as an explicit baseline; and
- forward-retiring active Raw-FPV without compatibility aliases if its bounded
  structural fit assessment fails.

It does not authorize physical motion, cloud promotion, provider concurrency
changes, or broader detector/model spending.
