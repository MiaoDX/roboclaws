# ADR-0145: Scope Eval Harness Profiles To Purposeful Baselines

Status: Accepted

Date: 2026-06-22

## Context

ADR-0140 made eval suites first-class benchmark artifacts. ADR-0141 made
`eval-harness` the maintained maintainer orchestration facade. The harness now
has enough rows to cover deterministic gates, product runs, eval suites,
Grounding DINO perception rows, and OpenAI Agents SDK rows.

That breadth is useful for baseline refreshes after large code changes, but it
can also create the wrong incentive: adding every possible engine, provider,
surface, evidence lane, and intent combination until the repo spends more time
maintaining a provider matrix than proving the core Roboclaws idea.

The current visible dimensions are:

- execution layer: deterministic gate, eval suite, product run, live-agent eval;
- cost/runtime: deterministic, local simulator, Grounding DINO, live agent;
- agent engine: direct runner and OpenAI Agents SDK;
- provider profile family: custom Responses, MiniMax Responses, and Kimi Chat;
- intent: open-ended household goals, cleanup, map-build, and planner proof;
- evidence lane: world-public labels, camera-raw FPV, and camera-grounded
  labels via Grounding DINO;
- eval suite: smoke regression, cleanup capability, map-build consumer,
  open-ended goals, and scene-sampler stress.

## Decision

Keep eval-harness profiles as purposeful maintainer baselines, not a promise to
support the full Cartesian product of all dimensions.

The harness may expose coarse selection groups such as:

- `full` / `baseline-refresh`: the currently accepted complete baseline set;
- `core`: deterministic gates, current eval suites, and local simulator product
  rows;
- `agent-sdk`: OpenAI Agents SDK rows;
- `providers`: explicit provider-route probes and all-provider sweeps;
- `open-ended`, `cleanup`, and `map-build`: capability-intent slices;
- `perception-dino` and `raw-fpv`: evidence-lane/perception slices.

Implement these as row metadata groups in the eval-harness catalog, then keep
Python selection code mechanical: load rows, expand command placeholders, filter
by profile/group/axes, execute or preflight, and write reports. Do not bury
policy in Python conditionals when the row catalog can state it plainly.

Profile and group names must be allowed to shrink. A group is maintained only
while it protects a current Roboclaws product claim, architecture boundary, or
regression class. Provider routes that are unhealthy, validation-only, or not
tied to a current claim should be explicit opt-in evidence rows, not part of a
default baseline.

## Rejected Alternatives

- Support every engine/provider/intent/evidence-lane combination. Rejected
  because it would turn Roboclaws into a provider matrix project and distract
  from the repo's purpose: visible household-robot behavior through MCP tools,
  skills, maps, traces, and reports.
- Keep one monolithic `baseline-refresh` profile forever. Rejected because it
  hides the reason a row exists and makes expensive runs harder to reason
  about.
- Put profile strategy back into Python. Rejected because that recreates the
  complexity we just removed from `eval_harness_rows.py`.
- Treat provider availability as behavioral capability proof. Rejected because
  provider health is useful evidence, but it is not the same as a robot task
  succeeding.

## Consequences

- Future refactors should add `groups` or equivalent row metadata to
  `skills/eval-harness/catalog/rows.json` before adding more selection logic.
- `baseline-refresh` can remain the complete accepted baseline, but smaller
  groups should become the normal way to ask focused questions.
- Broader provider coverage should be added only when there is a clear current
  product claim or regression risk to protect.
- `all-providers` should remain expensive and explicit. It is not a default
  baseline.
- Deprecated or low-value groups may be stripped later without compatibility
  shims when they no longer protect the repo's actual purpose.
