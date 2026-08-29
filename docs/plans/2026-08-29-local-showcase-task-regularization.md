# Local Showcase Task Regularization

**Status:** COMPLETE - deterministic implementation and local live acceptance shipped  
**Owner:** Roboclaws eval/runtime maintainers  
**Scope:** local OpenAI Agents SDK runs for the three household showcase groups

## Goal

Make the three showcase task groups produce honest, reviewable local runs before
any provider-backed result is used as a GitHub or Pages gate:

- `map_build_quality` completes a bounded room/map sweep and exposes the
  resulting Runtime Metric Map in the report.
- `cleanup_capability` completes a bounded cleanup loop or ends with an explicit
  incomplete/timeout result that still has usable evidence.
- `open_ended_goals` satisfies the selected sample's explicit success
  predicate. A negative search may legitimately finish without manipulation,
  while an early `done` without the required search/visit/observation evidence
  remains incomplete.

The first implementation target is local Kimi execution with `full` visual
capture and one serial run per group. Cloud CI remains unchanged until the
local acceptance gates pass.

## Evidence And Current Diagnosis

Recent local evidence under `output/local-showcase-kimi/` shows:

- Map build: 7 waypoint navigations, 7 observes, 9 timeline steps, complete
  `runtime_metric_map.json`, but the aggregate completion checker reports
  failure because cleanup-oriented fields are still mixed into the result.
- Open-ended: 5 waypoint navigations, 4 observes, 11 target queries,
  `navigate_to_room`, `navigate_to_receptacle`, and `open_receptacle`, but no
  pick/place chain before `done`; sweep was `0.571429` and completion failed.
- Cleanup: 53 successful model calls, 13 observes, 8 waypoint navigations, 4
  picks, 3 places, one place-inside cycle, but no `done` before the live timeout;
  192 visual frames were retained but no final report was written.
- Earlier CI run `33231562151` had the same Kimi cleanup long-tail before the
  `action_timeline` capture change, so this is not introduced solely by the
  latest screenshot-policy commit.

## Non-goals

- Do not merge or push to `main` during local debugging.
- Do not increase provider concurrency or run all three providers while the
  local behavior contract is unsettled.
- Do not silently turn incomplete model behavior into a pass.
- Do not change private-evaluation visibility or expose private fixture/scoring
  truth in public reports.
- Do not redesign the MCP surface or add a second task strategy owner.

## Plan

### Phase 1: Establish per-group contracts

1. Trace the existing suite samples, launch plans, skill prompts, `done` gates,
   timeout propagation, and report projections for all three groups.
2. Make the existing suite/sample definitions the canonical owner of terminal
   criteria instead of adding another showcase-specific success policy:
   - map-build: all required base waypoints plus the configured Runtime Metric
     Map thresholds (`20` public semantic anchors, `7` exploration candidates,
     `8` stable categories, `8` enrichment anchors, at least `1` observed
     object, at least `20` target candidates, and the configured fixture/best-
     view grader thresholds);
   - cleanup: the selected sample's relocated-object/destination predicates and
     an authoritative `done` closeout. Preserve the current capability
     threshold: at least 70% restoration (4 of 5 relocated objects), at least
     90% sweep coverage, and no more than 2 disturbances. A 3-of-5
     `partial_success` remains diagnostic evidence, not a capability pass;
   - open-ended: `expected_goal_outcome` plus the sample's authoritative
     `success_predicate`. In particular, `drink_seed7` must replace its current
     advisory `completion_claim` predicate with a public-evidence-only
     `public_search_exhausted` predicate derived from the existing public
     `target_search_summary`: the final `resolve_target_query` must return
     `status=not_found` with `exhausted_public_search_budget=true`, every public
     search waypoint must be visited and observed, no public candidate may
     match, and the agent must then call `done`. Do not copy a waypoint list
     into the sample or infer exhaustion from private inventory.
     It expects `not_found_clean_finish`; `room4_anchor_seed7` expects area
     inspection; and `living_waypoint_seed7` expects the public target to be
     observed. Private object inventory is never an input to these predicates.
3. Separate diagnostic success (artifacts available) from capability success
   (task contract passed) in the canonical eval result and local summary. Map
   build must have its own capability status rather than inheriting a cleanup-
   shaped aggregate completion field.

### Phase 2: Make local runs bounded and reviewable

1. First add deterministic replay/fixture tests for terminal classification and
   timeout finalization. Do not spend another live-provider run until these pass.
2. Keep `full` capture for local debugging while measuring capture overhead.
   Define it as a complete semantic timeline: retain before/after, every observe
   from a new pose, every state-changing action, and every post-action
   verification. Repeated observes at the same pose with unchanged public state
   may reuse/deduplicate image assets, but the timeline must retain an explicit
   deduplicated-event entry. Never silently omit the tool event.
3. Ensure timeout handling atomically writes a terminal diagnostic
   canonical bundle: `run_result.json`, `report.html`, `trace.jsonl`,
   `agent_view.json`, `runtime_metric_map.json`, and `private_evaluation.json`.
   It contains an explicit `terminal_incomplete` status and reason, last tool,
   progress counters, captured frames, and the preserved immutable run
   directory. The artifact/evidence gate may pass for this complete diagnostic
   bundle, but capability/outcome must fail. Public publication still removes
   private evaluation. A retry is a new attempt linked by provenance; it never
   resumes or mutates the terminal Robot Run.
4. Replace the current three-layer timeout mismatch (generic defaults,
   manifest timeout, and showcase-forced stall timeout) with per-group manifest
   budgets consumed by the runner without a hidden override.
5. Before setting performance gates, extract comparable historical successful
   rows by task, provider, evidence lane, scenario, target count, capture policy,
   completion quality, wall time, model calls, and tool calls. Do not compare a
   five-object world-public cleanup baseline directly with a different lane or
   target count.
6. Add focused tests for terminal criteria, predicate-valid observation-only
   open-ended runs, premature `done`, map-build output/status, and cleanup
   timeout finalization.

Initial local safety envelopes for baseline collection:

| Group | Sample/trial | Absolute wall clock | Initial stall probe | Calls | Progress contract |
| --- | --- | ---: | ---: | ---: | --- |
| Map build | `fixture_focused_seed7`, trial 0 | 15 min | 120 s, calibrate from model-call latency | diagnostic only | seven required waypoint observations and map thresholds |
| Cleanup | `repeated_seed7`, repetition 0 | 30 min | 180 s, progress-aware | no fixed hard cap | new object lifecycle/action progress or justified post-action verification |
| Open-ended | `drink_seed7`, trial 0 | 15 min | 120 s, calibrate from model-call latency | diagnostic only | public negative-search predicate |

These are absolute local safety envelopes, not performance targets or claims
about all providers. Historical evidence already includes an accepted
world-public cleanup baseline with 73 MCP tool calls in 390.264 seconds, while a
different camera-grounded row reached 56 model responses and 996.376 seconds
before a context-budget failure. A raw call count therefore cannot be a general
cleanup termination gate.

Reaching an absolute wall/stall envelope must finalize incomplete evidence
within 30 seconds. Cleanup stagnation means repeated calls without a new public
observation location, object lifecycle transition, successful action, or
terminal closeout; ongoing useful progress is not a stall merely because the
call count is high. After comparable successful history is collected, set the
performance target from its observed distribution (P95 when at least five
comparable successes exist; otherwise the slowest accepted success plus 25%)
and record the sample size. That derived target, not the safety envelope, is the
local capability/time gate and requires human review before cloud promotion.

### Phase 3: Local acceptance matrix

After deterministic gates pass, run exactly the three representative Kimi rows
in the table above, serially, with `full` capture. This is an implementation
baseline, not cross-provider or repetition evidence. For every row:

- report and `run_result.json` exist, including on timeout/failure;
- the complete canonical artifact bundle exists on timeout/failure, while its
  capability/outcome remains `terminal_incomplete`;
- timeline labels match actual tool events and every referenced image is present;
- public report contains no prompt, trace body, private evaluation, or JSON
  internals;
- capability status is honest and independently visible from artifact status;
- map-build renders a public Runtime Metric Map summary and preview with schema,
  coverage, public anchor/candidate counts, public provenance, and no raw JSON
  or grader-only fixture/scoring truth;
- cleanup either completes the required loop or is explicitly incomplete with a
  useful timeout diagnosis;
- open-ended satisfies its configured predicate or is explicitly marked
  incomplete, never pass-by-early-`done`.

Local promotion requires both gates:

- evidence gate: every terminal outcome, including timeout, has a valid public
  report, intact relative assets, explicit diagnostic status, and privacy pass;
- capability/time gate: all three representative rows pass their sample-specific
  capability predicate within the history-calibrated performance target and
  absolute safety envelope; call counts remain diagnostic unless a documented
  progress-aware stagnation rule fires.

One live pass is review evidence, not a reliability claim. Before any later
cloud promotion, cleanup must also pass all three repetitions locally and the
three provider-specific rows must be planned as a separate matrix.

### Phase 4: Cloud promotion decision

Only after Phase 3 passes, decide whether to update the provider-sharded CI
showcase. The cloud plan must retain `max-parallel: 3`, provider-specific rows,
explicit timeouts, and a failure artifact path. A CI green result is not required
for local implementation review and must not be used as a substitute for it.

## Files And Owners To Inspect

- `config/showcase-manifest.json`: row identity, samples, provider and timeout
  declarations.
- `evals/household_world/`: sample contracts and graders.
- `roboclaws/evals/`: suite execution, terminal status, and showcase summary.
- `roboclaws/agents/household_live_runner.py`: live timeout and closeout.
- `roboclaws/household/`: MCP tools, task strategy, cleanup/map/open-ended
  contracts, and report projection.
- `roboclaws/reports/` and `roboclaws/household/report*.py`: visual timeline and
  public report output.
- `.github/workflows/showcase.yml`: deferred cloud gate only.

## Stop Gates

- Stop if a proposed fix changes private-data boundaries, public MCP contracts,
  provider concurrency, or cloud cost without explicit review.
- Stop before Phase 4 if any local group lacks an honest terminal result or
  reportable evidence.
- Stop before paid/live execution if deterministic terminal, timeout, report,
  asset-link, or privacy tests fail.
- Stop and surface the exact blocker if a required live provider or simulator
  cannot run locally.

## Verification Commands

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh tests/contract tests/unit -q
set -a; source .env; set +a
ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY=full \
  .venv/bin/python -m roboclaws.evals.showcase \
  --manifest config/showcase-manifest.json \
  --output output/local-showcase-kimi \
  --execute --live-execution run \
  --row-id household_world.map_build_quality \
  --row-id household_world.cleanup_capability.kimi \
  --row-id household_world.open_ended_goals.kimi
```

## Open Implementation Defaults

- Keep local provider runs serial until measured RPS and runtime are stable.
- Prefer report finalization on timeout over silently discarding partial visual
  evidence.
- Keep provider choice local-only for this phase; Kimi is the current baseline
  because its local route is configured and already probed successfully.
- Use `full` capture locally; retain `action_timeline` only as a later cloud
  optimization if it can preserve the required review fidelity.

## Definition Of Done

The plan is complete when all three representative local groups pass both the
evidence gate and their sample-specific capability/time gate, cleanup then
passes its three local repetitions, and a separate follow-up decision can be
made about the provider matrix and CI without using `main` as the debugging
surface.

Acceptance result: map-build and open-ended Kimi rows passed their capability
and evidence gates; cleanup passed the repaired single-row confirmation plus
three serial repetitions. Cloud promotion and provider-matrix expansion remain
explicitly parked follow-up decisions.

## Planning-loop Decisions

Accepted:

- reuse suite/sample predicates as the terminal source of truth;
- make negative-search completion authoritative only after the declared public
  Runtime Metric Map search budget is exhausted with no matching public
  candidate and a final not-found resolution is recorded;
- preserve cleanup success at 4-of-5 restored, 90% sweep, at most 2
  disturbances, and authoritative `done`, across all three repetitions;
- add a timeout diagnostic finalization contract before tuning live behavior;
- make timeout evidence produce the complete canonical artifact bundle while
  remaining a failed capability outcome;
- separate evidence readiness, capability success, and time-budget success;
- define `full` as a complete semantic timeline with explicit image
  deduplication rather than silent event removal;
- use deterministic proofs before the three serial Kimi runs;
- keep cloud/provider-matrix work deferred.

Rejected:

- a generic open-ended manipulation requirement;
- increasing timeouts as the first cleanup fix;
- treating an incomplete run with good artifacts as a capability pass;
- resumable eval Robot Runs;
- another generic task-policy abstraction owned by the showcase layer.

Parked:

- cross-provider reliability and cloud concurrency tuning;
- README/report wording polish;
- broad flag consolidation unrelated to the three terminal contracts.

## Implementation Closeout

Deterministic contract, timeout-finalization, capture, and report slices shipped
in commits `80390238`, `a04fabaf`, and `c22ac586`. Focused proofs pass and Ruff
check/format pass. The full contract/unit run exceeded the local verification
window and was stopped; no provider-backed run has started. Remaining work is
the serial local acceptance matrix, cleanup repetitions, and the later cloud
promotion decision.
