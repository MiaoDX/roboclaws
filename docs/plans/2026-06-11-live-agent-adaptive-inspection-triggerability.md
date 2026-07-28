# Live-Agent Adaptive Inspection Triggerability

**Status:** Implementation-Complete; Live-Proven pending targeted live adaptive gate
**Created:** 2026-06-11
**Last reviewed:** 2026-06-11 closeout
**Source:** Scoped `intuitive-reduce-entropy` pass on live-agent use of
adaptive target inspection.
**Extends:** [`2026-06-11-adaptive-target-inspection.md`](2026-06-11-adaptive-target-inspection.md)
**Related ADRs:** none yet. Create an ADR only if this plan changes public MCP
tool contracts, public profile guarantees, or surface/intent command shape.

## Problem

The adaptive target-inspection infrastructure exists, but current live-agent
map-build gates do not prove that coding agents naturally trigger it.

The completed adaptive-target-inspection plan implemented public target
candidates, camera-adjustment evidence, generated target-inspection candidates,
report/checker support, and target-query recovery. The direct deterministic
path can exercise `adjust_camera`. However, the live Codex map-build prompt
still reads mostly as a one-pass sweep:

```text
navigate_to_waypoint -> observe -> declare_visual_candidates -> done
```

That is good enough to prove waypoint sweep coverage, but not enough to prove
the intended adaptive behavior:

```text
evidence incomplete -> adjust_camera -> observe again
visible but not actionable -> use a public generated inspection waypoint
or relocate to another public candidate -> observe again
```

The result is false confidence: a live-agent gate can pass while the agent never
uses the camera or relocation affordances this behavior was meant to expose.

## Current Evidence

Existing artifacts show the gap:

- Direct Grounding-DINO map-build:
  `output/household/semantic-map-build/direct-camera-grounded-labels/0611_1309/seed-7/run_result.json`
  - `adjust_camera:request = 28`
  - `observe:request = 42`
  - `declare_visual_candidates:request = 42`
  - `model_declared_count = 193`
  - `generated_exploration_candidates = 14`
  - `generated_target_inspection_candidates = 0`
  - `sweep_coverage_rate = 1.0`
- Live Codex RAW-FPV map-build:
  `output/household/semantic-map-build/codex-camera-raw-fpv/0611_1313/seed-7/run_result.json`
  - `adjust_camera:request = 0`
  - `observe:request = 14`
  - `model_declared_count = 0`
  - `generated_exploration_candidates = 14`
  - `generated_target_inspection_candidates = 0`
  - `runtime_timing.total_elapsed_s = 288.347`
- Live Codex Grounding-DINO map-build:
  `output/household/semantic-map-build/codex-camera-grounded-labels/0611_1436/seed-7/run_result.json`
  - `adjust_camera:request = 0`
  - `observe:request = 14`
  - `declare_visual_candidates:request = 14`
  - `model_declared_count = 12`
  - `generated_exploration_candidates = 14`
  - `generated_target_inspection_candidates = 0`
  - `runtime_timing.total_elapsed_s = 1087.095`

Closeout evidence from the implementation pass:

- Prompt, skill, checker, and deterministic contract gates passed on
  2026-06-11 with the focused commands listed in
  [Implementation Closeout](#implementation-closeout).
- Agent-validation recommendation artifact:
  `output/agent-validation-matrix/20260611T082606Z/`.
- Agent-validation execute artifact:
  `output/agent-validation-matrix/20260611T082629Z/`.
- The matrix-selected direct map-build product gate passed at
  `output/agent-validation-matrix/20260611T082629Z/gates/direct-map-build-world-oracle/run/0611_1631/seed-7/report.html`
  with `sweep_coverage_rate = 1.0`,
  `adjust_camera:request = 28`, and
  `runtime_metric_map.json` output.
- The matrix-selected runtime-prior consumer gate initially failed because the
  harness passed the literal unresolved placeholder
  `map-build-world-oracle:runtime_metric_map.json`. The harness has been fixed
  to resolve `${gate:artifact}` placeholders, and a manual rerun passed at
  `output/agent-validation-matrix/20260611T082629Z/gates/direct-cleanup-runtime-prior-consumer-rerun/run/0611_1635/seed-7/report.html`.
- `direct-camera-grounded-grounding-dino` was blocked by unavailable DINO
  sidecar, and `codex-cleanup-camera-raw-fpv` was blocked by an already-active
  live session. These blocks do not prevent `Implementation-Complete`.
- The live Codex cleanup world-oracle matrix gate exited and released its
  backend slot; it is not a targeted map-build adaptive-inspection proof and
  does not promote this plan to `Live-Proven`.

Existing tests prove pieces of the lower-level contract, not the full live-agent
behavior:

- `tests/contract/molmo_cleanup/test_molmo_realworld_contract.py` manually
  exercises `adjust_camera`, `required_next_tool == "adjust_camera"`, and
  generated target-inspection candidate state transitions.
- `tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py` proves MCP
  tool responses can require `adjust_camera`.
- `tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py`
  verifies semantic-sweep camera-adjustment evidence for deterministic runs.
- The live-agent checker gates can still pass with
  `adjust_camera:request = 0` and
  `generated_target_inspection_candidates = 0`.

## Goals

- Make live-agent kickoff prompts and skill guidance explicitly tell agents
  when to use `adjust_camera`, reobserve, and relocate through public
  inspection candidates.
- Add optional checker gates that can prove adaptive behavior when a run claims
  to validate adaptive inspection.
- Add a deterministic MCP/contract regression scenario that forces the
  sequence `observe -> blocked/non-actionable evidence -> adjust_camera or
  generated inspection waypoint -> observe again`.
- Keep ordinary map-build gates cheap: do not require camera adjustment in
  every scan-only sweep when there is no target or ambiguity that demands it.
- Make plan/report language honest: current evidence supports better
  reviewability and coverage, not proven speed or cleanup-success gains.
- Split completion claims into implementation-complete and live-proven states:
  deterministic gates can finish the implementation, but only a targeted live
  adaptive gate can justify saying live agents actually triggered the behavior.

## Non-Goals

- Do not reopen root `TODOS.md`.
- Do not reclassify broader detector/refiner ranking as part of this plan.
- Do not add an opaque `find_and_go`, `go_to_label`, or auto-cleanup tool.
- Do not let agents invent arbitrary coordinates.
- Do not require a global next-best-view planner.
- Do not require live Codex/Grounding-DINO runs for deterministic unit and
  contract acceptance.
- Do not claim performance gains without a benchmark designed to compare the
  same task before and after this change.

## Execution Preflight

**Preflight status:** Drafted for approval, 2026-06-11.

**Route:** durable `$intuitive-flow`.

**Goal:** make adaptive camera/reinspection/target-specific relocation
triggerable from live-agent-facing prompts, skill guidance, checker flags, and
deterministic contract tests.

**Scope:**

- Update semantic-map-build live-agent prompt guidance.
- Add dedicated map-build/adaptive-inspection skill guidance.
- Add opt-in checker flags for adaptive proof.
- Add deterministic MCP/contract regression for a forced adaptive path.
- Preserve the `Implementation-Complete` vs `Live-Proven` split.

**Non-goals:**

- No new MCP tool.
- No arbitrary agent-created coordinates.
- No root `TODOS.md`.
- No detector/refiner benchmark.
- No performance-gain claim.

**Context package:**

- Must read:
  - this plan;
  - [`skills/agent-validation-matrix/SKILL.md`](../../skills/agent-validation-matrix/SKILL.md);
  - [`../../roboclaws/agents/prompts/household_cleanup.py`](../../roboclaws/agents/prompts/household_cleanup.py);
  - [`../../skills/molmo-realworld-cleanup/SKILL.md`](../../skills/molmo-realworld-cleanup/SKILL.md);
  - [`../../scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py`](../../scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py);
  - [`../../tests/contract/dev_tools/test_task_agent_just_recipes.py`](../../tests/contract/dev_tools/test_task_agent_just_recipes.py);
  - [`../../tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py`](../../tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py);
  - [`../../tests/contract/molmo_cleanup/test_molmo_realworld_contract.py`](../../tests/contract/molmo_cleanup/test_molmo_realworld_contract.py);
  - [`../../tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py`](../../tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py).
- Useful evidence:
  - [`2026-06-11-adaptive-target-inspection.md`](2026-06-11-adaptive-target-inspection.md);
  - cited `0611_*` artifacts in this plan;
  - [`../../CONTEXT.md`](../../CONTEXT.md) target/actionability vocabulary.
- Do not read unless needed:
  - root `TODOS.md`;
  - broad `output/**`;
  - unrelated operator-console dirty files.

**Definition of Done / acceptance criteria:**

- SUCCESS / `Implementation-Complete` only if deterministic prompt, skill-doc,
  checker, and MCP/contract gates pass.
- `Live-Proven` only if a targeted live Codex run passes the new adaptive
  checker flags.
- BLOCKED_NEEDS_LOCAL_VALIDATION if trying to claim `Live-Proven` without
  provider, Docker, simulator, or sidecar proof.
- Must not regress existing scan-only map-build, cleanup actionability,
  private-truth exclusion, or minimal-map gates.

**Verification selected with `skills/agent-validation-matrix/SKILL.md`:**

- Deterministic gates:
  - `ruff check roboclaws/agents/prompts/household_cleanup.py scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py tests/contract/dev_tools/test_task_agent_just_recipes.py tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py tests/contract/molmo_cleanup/test_molmo_realworld_contract.py tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py`
  - `./scripts/dev/run_pytest_standalone.sh tests/contract/dev_tools/test_task_agent_just_recipes.py tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py tests/contract/molmo_cleanup/test_molmo_realworld_contract.py tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py -q`
- Integration gates:
  - `just agent::harness agent-validation recommend plan=docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md budget=focused`
  - `just agent::harness agent-validation execute plan=docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md budget=focused`
- Product run gate for deterministic confidence:
  - direct map-build row selected by agent-validation; if manual fallback is
    needed, use a minimal-map
    `surface=household-world intent=map-build agent_engine=direct-runner`
    camera lane.
- Local/live/manual gate for `Live-Proven` only:
  - targeted Codex map-build with `camera-grounded-labels` +
    `grounding-dino`, then checker with new adaptive flags.
- Optional exploratory gates:
  - broader detector/refiner ranking;
  - latency/cost benchmarking.

**Execution surface:**

- Main session: supervise scope, avoid unrelated dirty files, verify results.
- Worker: none required.
- Worker-local goal: none.

**To execute:**

```text
/goal execute docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md with intuitive-flow
```

## Adaptive Validation

Use the adaptive validation matrix before implementation to pick the smallest
proof set for this plan:

```bash
just agent::harness agent-validation recommend \
  plan=docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md \
  budget=focused

just agent::harness agent-validation execute \
  plan=docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md \
  budget=focused
```

Expected validation axes:

- prompt/static axis for semantic-map-build kickoff text;
- skill-doc alignment axis for `skills/molmo-realworld-cleanup/SKILL.md`;
- checker axis for explicit adaptive requirements;
- deterministic MCP/contract axis for forced
  `incomplete evidence -> adjust/reobserve or public relocation` behavior;
- optional local/live axis only after deterministic gates pass.

Do not treat the optional local/live axis as required for the deterministic
implementation. Do not claim live adaptive proof unless the run is created from
a prompt or scenario that actually needs adaptive inspection and the new
adaptive checker flags pass.

## Implementation Slices

### Slice 1: Live-Agent Prompt Affordance

Update `roboclaws/agents/prompts/household_cleanup.py` so
`render_semantic_map_build_prompt()` gives camera lanes an explicit adaptive
inspection rule:

- if a target query, visual candidate, anchor, or waypoint observation is
  incomplete, call `adjust_camera` within budget and then call `observe` again;
- if a target candidate is `visible_only`, `needs_observe`, or requires a
  generated target-inspection waypoint, navigate only to the public waypoint
  candidate returned by `metric_map`, `resolve_target_query`, or tool recovery;
- if public tools return `required_next_tool` or `required_tool`, call that tool
  before moving on;
- do not mark a waypoint or target search complete just because the first
  observation returned no labels.

Add prompt tests under
`tests/contract/dev_tools/test_task_agent_just_recipes.py` that assert
semantic-map-build camera prompts mention:

- `adjust_camera`;
- `observe again` or equivalent fresh-observation wording;
- public generated inspection waypoint / target-inspection candidate guidance;
- no cleanup actions.

### Slice 2: Skill Guidance Alignment

Refresh `skills/molmo-realworld-cleanup/SKILL.md` map-build guidance so the
agent skill and kickoff prompt agree:

- add a dedicated map-build/adaptive-inspection paragraph rather than burying
  the rule inside the generic cleanup loop;
- map-build waypoints are coverage candidates, not one-shot observations;
- camera lanes may need one bounded `adjust_camera -> observe` retry when
  public evidence is incomplete;
- visible-only target candidates must be converted through public generated
  inspection candidates or another public waypoint before navigation/action;
- `not_found` should cite public search budget, inspected viewpoints, and
  camera-adjustment attempts.

This should be concise and should not duplicate the full implementation plan.

### Slice 3: Optional Checker Gates

Add checker flags only for runs meant to prove adaptive inspection, for example:

```text
--min-adjust-camera-count N
--min-generated-target-inspection-candidates N
```

These flags should be independent from `--require-semantic-sweep` and
`--require-camera-model-policy`. Existing scan-only live gates should not start
failing just because they do not need an adaptive retry.

Add tests proving:

- a fixture with `adjust_camera:request = 0` fails when
  `--min-adjust-camera-count 1` is requested;
- a fixture with zero generated target-inspection candidates fails when
  `--min-generated-target-inspection-candidates 1` is requested;
- existing semantic-sweep/map-build checker tests continue to pass without the
  new flags.

### Slice 4: Forced Adaptive Scenario

Add or reuse a deterministic MCP/contract test where the first observation is
insufficient and the next safe step is explicit:

```text
metric_map
navigate_to_waypoint
observe
attempt target use or target query resolution
response requires adjust_camera or generated inspection waypoint
adjust_camera OR navigate_to_waypoint(generated_inspection_...)
observe
candidate becomes actionable or the exhausted public budget is visible
```

The test should prove the behavior through public MCP/contract state, not by
reading private manifests or simulator inventory.

Prefer reusing the current target-candidate and MCP tests before adding a new
fixture. The desired regression is not another broad sweep test; it is a
targeted path where a public response requires the next adaptive tool and the
test fails if the implementation can pass by observing each waypoint exactly
once.

### Slice 5: Evidence And Performance Wording

Update the completed adaptive-target-inspection plan only if necessary to link
this follow-up. Do not change its done status.

Any new wording should distinguish:

- evidence-quality gain: stronger reviewable traces, public budgets, and
  actionability state;
- task-performance gain: speed, cleanup success, fewer tool calls, or better
  target recovery in comparable tasks.

Current artifacts do not prove task-performance gain. The live DINO run was
slower than the live RAW-FPV run, so performance claims need a separate
benchmark gate.

## Acceptance Gates

### Implementation-Complete

The plan can be marked implemented when all deterministic gates below pass:

- Prompt tests prove semantic-map-build camera lanes tell live agents how and
  when to trigger `adjust_camera` and public relocation/reinspection.
- Skill guidance and kickoff prompt do not contradict each other about adaptive
  inspection, one-shot waypoint completion, or target actionability.
- Checker tests prove adaptive behavior can be required explicitly without
  weakening existing scan-only map-build gates.
- A deterministic contract or MCP regression test forces and validates at least
  one adaptive inspection path.
- Existing focused tests still pass:

```bash
./scripts/dev/run_pytest_standalone.sh \
  tests/contract/dev_tools/test_task_agent_just_recipes.py \
  tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_contract.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py \
  -q
```

This state means the agent-facing surface, checker, and deterministic contract
proofs are in place. It does not mean a live Codex run has actually chosen the
adaptive behavior.

### Live-Proven

After implementation-complete, optional local live proof can promote the claim
from "triggerability is encoded" to "a live agent actually triggered adaptive
inspection."

```bash
VISUAL_GROUNDING_BASE_URL=http://127.0.0.1:18881 \
VISUAL_GROUNDING_TIMEOUT_S=120 \
just run::surface surface=household-world world=molmospaces/val_0 \
  backend=mujoco preset=map-build agent_engine=openai-agents-sdk \
  provider_profile=codex-router-responses evidence_lane=camera-grounded-labels \
  camera_labeler=grounding-dino scenario_setup=baseline seed=7 \
  prompt="build a semantic map and inspect the sink/food-storage area until public evidence is actionable or the public search budget is exhausted"
```

Only claim adaptive live-agent proof if the resulting checker is run with the
new adaptive flags and passes. A generic "build a semantic map of this room"
live run is useful sweep evidence, but it is not sufficient adaptive-inspection
evidence because the correct agent behavior may be a one-observe-per-waypoint
sweep.

`Live-proven` requires:

- the run prompt or scenario actually creates a target-search or ambiguous
  evidence need;
- `adjust_camera:request >= 1`;
- target-specific relocation/reinspection is proven by either at least one
  generated target-inspection candidate or a public tool response that sends the
  agent to a target-specific public waypoint/standoff before reobserve;
- cleanup actions remain disabled for `intent=map-build`;
- checker flags for adaptive behavior pass.

## Implementation Defaults

- Default camera-adjustment proof threshold: at least one
  `adjust_camera:request` for adaptive proof runs.
- Default generated-target-inspection proof threshold: at least one generated
  target-inspection candidate only for scenarios that intentionally create a
  visible-only or needs-observe target. Do not require this for generic
  semantic sweeps.
- Default prompt change: concise imperative rules in the semantic-map-build
  prompt, not a long reproduction of the full plan.
- Default checker behavior: new flags are opt-in and default to zero, preserving
  existing scan-only gates.
- Default live proof route: local-only Codex map-build with camera-grounded
  labels and a target-search prompt, after deterministic gates are green.

## Parked Items

- Broader Grounding-DINO/refiner ranking remains parked under visual-grounding
  benchmark work. Why parked: ranking detectors/refiners answers model quality,
  not whether agents can trigger adaptive inspection.
- Hosted-refiner cost and latency benchmarking remains parked. Why parked:
  MiMo refiner smoke already showed the route works but is slow; making agents
  trigger adaptive inspection does not require selecting the default refiner.
- General root backlog cleanup remains parked. Why parked: this plan is scoped
  to live-agent triggerability and should not reopen `TODOS.md`.

## Implementation Closeout

Implemented on 2026-06-11:

- Semantic-map-build live-agent prompts now explicitly instruct camera lanes to
  call `adjust_camera`, observe again, follow `required_next_tool` /
  `required_tool`, and use only public generated target-inspection waypoints for
  `visible_only` / `needs_observe` candidates.
- `skills/molmo-realworld-cleanup/SKILL.md` now has matching concise
  map-build adaptive-inspection guidance.
- The cleanup result checker has opt-in adaptive proof thresholds:
  `--min-adjust-camera-count` and
  `--min-generated-target-inspection-candidates`.
- Focused tests now cover prompt guidance, checker opt-in behavior, and a
  deterministic public contract path where blocked/non-actionable evidence
  requires adaptive public reinspection.
- The agent-validation matrix runner now resolves `${gate:artifact}` placeholders
  before running dependent gates such as cleanup with a runtime-map prior.

Focused verification passed:

```bash
uv sync --extra dev
uv run ruff check roboclaws/agents/prompts/household_cleanup.py scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py tests/contract/dev_tools/test_task_agent_just_recipes.py tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py tests/contract/molmo_cleanup/test_molmo_realworld_contract.py tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py
uv run ruff check skills/agent-validation-matrix/scripts/run_validation_matrix.py tests/unit/molmo_cleanup/test_agent_validation_matrix.py
./scripts/dev/run_pytest_standalone.sh tests/contract/dev_tools/test_task_agent_just_recipes.py tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py tests/contract/molmo_cleanup/test_molmo_realworld_contract.py tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py -q
./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_agent_validation_matrix.py -q
```

Validation matrix evidence:

```bash
just agent::harness agent-validation recommend plan=docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md budget=focused
just agent::harness agent-validation execute plan=docs/plans/2026-06-11-live-agent-adaptive-inspection-triggerability.md budget=focused
```

- Recommend artifact:
  `output/agent-validation-matrix/20260611T082606Z/`.
- Execute artifact:
  `output/agent-validation-matrix/20260611T082629Z/`.
- Manual prior-consumer rerun after placeholder-resolution fix:
  `output/agent-validation-matrix/20260611T082629Z/gates/direct-cleanup-runtime-prior-consumer-rerun/run/0611_1635/seed-7/report.html`.

Remaining `Live-Proven` gate:

- Run a targeted live Codex `intent=map-build` adaptive prompt with
  camera-grounded labels and `grounding-dino`, then run the checker with
  `--min-adjust-camera-count 1` and the appropriate generated
  target-inspection candidate threshold for the chosen scenario.
- Do not claim live adaptive-inspection proof until that targeted live run
  passes the opt-in adaptive checker flags.
