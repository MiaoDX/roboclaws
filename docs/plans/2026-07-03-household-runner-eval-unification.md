---
plan_scope: household-runner-eval-unification
status: DONE
created: 2026-07-03
last_reviewed: 2026-07-03
implementation_allowed: true
source:
  - user discussion about Long Horizon Runner, Cleanup Runner, and Map Builder
  - user decision that Long Horizon is not an eval exception
  - user decision that backward compatibility is not required
  - intuitive-reduce-entropy plan loop
  - grill-with-docs-batch saturation audit
related_context:
  - ARCHITECTURE.md
  - docs/human/domain.md
  - docs/human/evaluation.md
  - docs/human/mcp-skills-and-semantic-profiles.md
  - docs/adr/0139-use-household-open-task-surface-with-presets.md
  - docs/adr/0140-use-eval-suites-as-first-class-architecture-layer.md
  - docs/adr/0141-use-eval-harness-as-maintainer-orchestration-facade.md
  - docs/adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md
---

# Household Runner And Eval Unification

## Plan Ledger

- Plan status: DONE
- Session scope: household-runner-eval-unification
- Last updated: 2026-07-03
- Current slice: implementation complete. Household skill identity, private
  dispatch, direct product episode naming/API, eval identity, Long Horizon eval
  execution, docs, and tests now use `household-world` plus `task_intent` /
  `task_preset` instead of task-named runner concepts.
- Latest deterministic evidence: `ruff check .`, `ruff format --check .`,
  `./scripts/dev/run_pytest_standalone.sh -q`, direct map-build and cleanup
  product routes, all listed smoke eval suites, and eval-harness
  recommendation completed.
- Latest live evidence: the selected `map_build_consumer` OpenAI Agents SDK /
  `codex-router-responses` live row ran through product routes. Provider and
  runtime availability were proven; the MapBuild sample passed and four
  consumer/open-ended samples failed before grading as product
  behavior/runtime-budget failures.
- Next action: none for this migration. Follow-up live policy tuning belongs
  in a separate product-behavior plan.
- Blocked on: none for the migration itself.

## Goal

Make household task execution easier to reason about by removing task-named
runners and making eval coverage uniform.

The target rule is:

```text
Task type does not create a runner.
Execution mechanism creates a runner.
Eval wraps product runs.
```

Long Horizon, Cleanup, MapBuild, and open-ended household goals should all run
through the same household-world product episode path. They differ by
GoalContract, TaskIntentSpec, optional TaskPresetSpec, required capabilities,
and graders. They should not become separate product runner concepts.

## Accepted Decisions

These are already decided for this plan:

1. Do not add a product-run `eval_scenario` axis.
2. Do not treat Long Horizon as a runner, product mode, or product-run special
   case.
3. Every maintained household capability or standard task profile must have an
   eval suite or eval-harness row. Eval is a general maintainer layer, not
   something special to Long Horizon.
4. Keep the public household shape from ADR-0139:
   `surface=household-world prompt=...`, with optional
   `preset=cleanup|map-build`.
5. Do not preserve backward compatibility for old private task runner names,
   skill names, dispatch targets, or tests once the forward migration starts.

## Problem

The repo already has the right public direction, but implementation names still
make task types look like runners:

- `preset=cleanup` still maps to `molmo-realworld-cleanup`.
- `preset=map-build` and no-preset open household goals map to
  `household-open-task`.
- direct MapBuild is implemented as a `map_build` mode on a cleanup runner.
- Long Horizon direct evals bypass the normal product runner through
  `run_scripted_long_horizon_trial`.
- eval docs correctly say Long Horizon is an open-ended eval subset, but code
  still gives it runner-like identity such as `household-long-horizon`.

That creates recurring rediscovery: a maintainer has to remember which runner
names are public concepts, which are historical implementation names, and which
are eval-only proof helpers.

## Target Model

### Product Layer

One product episode path owns household-world execution:

```text
HouseholdWorldRunner
  input:
    GoalContract
    TaskIntentSpec
    optional TaskPresetSpec
    AgentEngineSpec
    BackendSpec
    evidence_lane / camera_labeler
    runtime_map_prior
  output:
    run_result.json
    trace.jsonl
    report.html
    agent_view.json
    runtime_metric_map.json when required by the intent
```

`HouseholdWorldRunner` is a surface-level runner, not a cleanup runner, map
builder runner, or long-horizon runner.

Task-specific behavior is policy, not a runner:

| Intent / preset | Product meaning | Capabilities | Completion/checker role |
| --- | --- | --- | --- |
| no preset, `prompt=...` | open household goal | household world + episode | agent-declared completion and open-ended advisory gates |
| `preset=cleanup` | cleanup-shaped household goal | household world + manipulation + episode | cleanup scorer and checker gates |
| `preset=map-build` | map evidence goal | household world + episode | Runtime Metric Map gates; manipulation disabled |

### Eval Layer

Eval remains outside the product runner:

```text
EvalSuite
  -> EvalSample
     -> private setup and private reference, when needed
     -> public product launch args
     -> same HouseholdWorldRunner
     -> graders
     -> aggregate metrics and failure classes
```

Long Horizon is one eval-suite/grader shape in this layer. It may keep private
sample setup and private final-state references for graders, but those inputs
must never reach the product runner or Agent View.

### Execution Mechanism Layer

The remaining runner axis should be execution mechanism:

- `direct-runner`: deterministic product runner baseline.
- `openai-agents-sdk`: live product runner through the SDK and MCP server.
- backend adapters: `mujoco`, `isaaclab`, and `agibot-gdk`.
- eval harness: maintainer orchestration facade, not a task runner.

## Non-Goals

- Do not remove `preset=cleanup` or `preset=map-build` from the public
  household command shape.
- Do not create a generic workflow engine.
- Do not make evals an operator-facing `run::*` namespace.
- Do not expose private generated mess sets, target objects, acceptable
  destinations, or long-horizon references to the agent.
- Do not keep compatibility aliases for old internal runner or skill names.

## Implementation Plan

### Phase 1: Collapse Skill Identity

Goal: one maintained household-world skill, with intent/preset sections.

Planned changes:

- Create `skills/household-world/` as the single maintained household task
  skill.
- Merge the reusable guidance from `skills/household-open-task/` and
  `skills/molmo-realworld-cleanup/`.
- Encode cleanup, map-build, and open-ended behavior as sections driven by
  GoalContract and TaskIntentSpec, not separate skills.
- Update `roboclaws/launch/intents.py` and `roboclaws/household/tasks.py` so
  all household intents and presets use `skill_name="household-world"`.
- Delete old skill directories and tests that require the old names.
- Update prompt text in `roboclaws/agents/prompts/household_cleanup.py` so the
  SDK kickoff says "Use the bundled household-world skill instructions."

Acceptance:

- Current code and maintained docs no longer treat `molmo-realworld-cleanup`,
  `household-open-task`, or `household-long-horizon` as active skill names.
- Historical plans may mention old names as history, but current first-read
  docs, launch code, prompts, and tests do not.

### Phase 2: Collapse Private Dispatch Targets

Goal: one household-world private dispatch target, with intent/preset carried
as launch context.

Planned changes:

- Replace `household-world.cleanup`, `household-world.map-build`, and
  `household-world.open-ended` as active private dispatch targets with a single
  `household-world` dispatch target.
- Pass `task_intent`, `task_preset`, GoalContract, and required capabilities as
  explicit launch context.
- Update `just agent::run`, `just mcp::up`, server adapters, and launch catalog
  tests around the new dispatch shape.
- Remove old target aliases instead of preserving wrappers.

Acceptance:

- Public `just run::surface surface=household-world ...` still works.
- Maintainer dispatch no longer has task-named household targets.
- Route validation checks agent engine, backend, evidence lane, and required
  capabilities without branching on task-named runner ids.

### Phase 3: Rename And Generalize The Direct Product Episode Path

Goal: direct product code reads as household-world episode execution, not a
cleanup runner with map-build flags.

Planned changes:

- Move or rename `roboclaws/household/realworld_cleanup.py` toward a
  task-neutral episode runner module.
- Move or rename `roboclaws/household/realworld_direct_cleanup_loop.py` toward
  a task-neutral direct episode policy module.
- Replace the `map_build: bool` control path with an explicit episode policy
  derived from TaskIntentSpec and TaskPresetSpec.
- Keep the existing shared scan structure, because it is the right reusable
  primitive:
  `metric_map -> navigate_to_waypoint -> observe -> optional target action -> done`.
- Make cleanup action execution a policy phase enabled by cleanup/manipulation
  requirements, not by the file or runner name.
- Make Runtime Metric Map production an episode artifact requirement for
  map-build, not a map-builder runner output.

Acceptance:

- No active direct product module or function name says "cleanup runner" when it
  owns open-ended and map-build execution too.
- MapBuild is no longer represented by a `map_build` runner mode flag.
- Cleanup, map-build, and open-ended direct rows all use the same product
  episode artifact finalizer.

### Phase 4: Remove Long-Horizon Runner Special Cases

Goal: Long Horizon remains an eval suite/grader, not an alternate product
runner.

Planned changes:

- Delete `run_scripted_long_horizon_trial` from the normal eval-suite product
  path.
- Remove `lh.run_trial(...)` substitution from `roboclaws/evals/runner.py`.
- Remove `household-long-horizon` eval identity.
- Keep `long_horizon` as a private grader and suite label.
- Replace Long Horizon-specific generated-mess plumbing with a generic eval
  private setup mechanism that any sample can use.
- Replace Long Horizon-specific smoke-backend exceptions with generic sample
  runtime requirements, such as "this sample requires the real MolmoSpaces
  implementation backend."
- If an oracle/scripted Long Horizon proof is still useful, move it to an
  explicit harness recipe or oracle baseline that cannot be counted as product
  capability pass evidence.

Acceptance:

- `long_horizon_tasks` eval samples run through the same product launch path as
  other household eval samples.
- Private Long Horizon references remain grader-only.
- The long-horizon suite can still grade placement, trajectory, empty hands,
  completion claim, and privacy.
- No eval product-run code asks "is this a long-horizon sample?" to decide which
  runner to call.

### Phase 5: Normalize Eval Coverage Around Product Capabilities

Goal: every maintained household capability has a clear eval home without
special runner rules.

Planned changes:

- Keep suites for current capability questions:
  `smoke_regression`, `open_ended_goals`, `cleanup_capability`,
  `map_build_consumer`, `scene_sampler_stress`, and `long_horizon_tasks`.
- Ensure every suite records the same identity shape: surface, preset, intent,
  world, backend, evidence lane, agent engine, provider profile, skill,
  required capabilities, private setup scope, and graders.
- Ensure every suite runs product routes first, then grades artifacts.
- Promote shared private setup fields into the eval sample schema instead of
  adding suite-specific runner hooks.
- Keep deterministic privacy, artifact, trajectory, and state/outcome graders
  authoritative; keep model/human rubric graders advisory unless calibrated.

Acceptance:

- Long Horizon is represented the same way as other eval coverage: suite,
  samples, private setup/reference, product run, graders.
- Adding a future "drawer interaction" or "multi-floor" eval does not require a
  new runner; it adds samples, backend capability requirements, and graders.

### Phase 6: Update Docs, Tests, And Eval Harness Selection

Goal: first-read docs and tests enforce the new taxonomy.

Planned changes:

- Update `ARCHITECTURE.md` to say task types do not produce runners and eval
  wraps product runs.
- Update `docs/human/evaluation.md` to remove Long Horizon exception wording
  and describe generic sample runtime requirements.
- Update `docs/human/mcp-skills-and-semantic-profiles.md` and `skills/README.md`
  for the single household-world skill.
- Update eval-harness row selection so changed household-world skill or runner
  files select open-ended, cleanup, map-build, and long-horizon coverage as
  appropriate.
- Update tests that currently assert old skill names, target names, or
  long-horizon direct-runner substitution.

Acceptance:

- `rg -n "molmo-realworld-cleanup|household-open-task|household-long-horizon|run_scripted_long_horizon|eval_scenario" roboclaws skills docs/human evals tests`
  shows no active-contract references except deliberate historical plan text or
  rejected-alternative notes.
- Eval docs describe Long Horizon as an eval suite/grader, not an exception.

## Verification Plan

Deterministic checks:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
```

Focused launch and eval checks:

```bash
just run::surface surface=household-world agent_engine=direct-runner preset=map-build evidence_lane=world-public-labels
just run::surface surface=household-world agent_engine=direct-runner preset=cleanup evidence_lane=world-public-labels
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=open_ended_goals budget=smoke
just agent::eval suite=cleanup_capability budget=smoke
just agent::eval suite=map_build_consumer budget=smoke
just agent::eval suite=long_horizon_tasks budget=smoke
just agent::eval recommend plan=docs/plans/2026-07-03-household-runner-eval-unification.md budget=focused
```

Live proof policy:

- Because this plan touches live-agent launch, MCP server routing, SDK prompt
  skill selection, eval harness rows, and artifact selection, run the relevant
  live or preflight proof by default.
- Before live SDK routes, run:

```bash
just dev::network-status
```

- If network/provider/runtime readiness blocks live proof, record the concrete
  blocker using guarded preflight/status output instead of substituting only
  deterministic tests.

## Stop Gates

Stop and re-plan if any of these occur:

- A required private setup value would need to enter Agent View or MCP tool
  responses.
- A public command shape change would contradict ADR-0139.
- Eval suite execution can only pass by using an oracle/scripted runner instead
  of the product run path.
- A live-agent route silently falls back to direct-runner evidence.
- The single household-world skill becomes too large to review, and the split
  needed is capability-profile based rather than task-runner based.

## Intuitive Reduce Entropy Loop

Selected mode: plan entropy mode.

Why: the target is a draft architecture/refactor plan and the user explicitly
requested an intuitive reduce-entropy loop before grill-batch review.

Redirect: none.

Discovery intensity: saturation scan.

### Round 1: Demand Sanity Gate

Demand gate: pass.

The requested change removes a real maintainer surprise. Existing public docs
already point toward `surface=household-world + prompt/preset`, while current
code and tests preserve task-named skill, dispatch, and eval-runner concepts.
This is live source drift and recurring rediscovery, not wording polish.

### Round 2: Current Source Evidence

Evidence checked:

- `roboclaws/launch/intents.py` still assigns cleanup to
  `molmo-realworld-cleanup` and map-build/open-ended to
  `household-open-task`.
- `roboclaws/household/tasks.py` repeats that split in preset specs.
- `roboclaws/cli/agent_run.py` picks skill names from dispatch intent.
- `roboclaws/household/realworld_direct_cleanup_loop.py` already shares scan
  logic for cleanup and map-build, but exposes `map_build` as a cleanup-loop
  flag.
- `roboclaws/evals/runner.py` calls `lh.run_trial(...)`, which can substitute
  `run_scripted_long_horizon_trial`.
- `docs/human/evaluation.md` correctly says Long Horizon is a focused
  open-ended eval subset, but also documents it as a smoke-budget exception.
- `evals/household_world/README.md` correctly frames Long Horizon as an eval
  subset, not a public task axis.

### Selected Candidates

#### P1: Remove Long-Horizon Product-Runner Substitution

Entropy source: false confidence and stale surface.

Materiality: a suite can appear to prove product capability while bypassing the
same product runner path used by other samples.

Owner: eval suite runner and household eval support.

Proof: `long_horizon_tasks` must pass through product launch and graders, with
no `lh.run_trial(...)` substitution.

Risk: direct deterministic Long Horizon may initially fail if it relied on
private-oracle scripting. That failure is useful; it exposes product capability
gaps instead of hiding them.

#### P1: Collapse Household Skill And Dispatch Identity

Entropy source: live source drift and recurring rediscovery.

Materiality: launch plans, prompt previews, SDK prompts, eval identity, and
tests disagree about whether cleanup/open-task names are current concepts or
old implementation names.

Owner: launch catalog, agent dispatch, SDK prompts, skills.

Proof: all household intents/presets report `skill_name=household-world`, and
active private dispatch is surface-level.

Risk: broad test churn because many tests currently assert old names. No
compatibility shim should be added to reduce that churn.

#### P1: Generalize Eval Private Setup

Entropy source: stale special-case fixture plumbing.

Materiality: Long Horizon generated-mess manifests are useful, but the mechanism
should be available to any eval sample that needs private setup.

Owner: eval sample schema and live/direct eval runtime.

Proof: private setup artifacts are produced from generic sample fields, and
private references stay grader-only.

Risk: sample schema migration touches suite fixtures and regression promotion.

#### P2: Rename Direct Product Episode Modules

Entropy source: architecture discovery friction.

Materiality: current module names make map-build and open-ended runs look like
cleanup internals even when the code is already a shared household episode.

Owner: household runtime modules and tests.

Proof: direct product functions and file names no longer encode cleanup as the
owner of all household episode behavior.

Risk: wide import churn; schedule after skill and dispatch identity are stable.

### Parked Items

- Removing public `preset=cleanup|map-build`: rejected because ADR-0139
  intentionally keeps presets.
- Adding `eval_scenario`: rejected because eval must wrap product runs.
- Adding a generic workflow engine: rejected as unnecessary.
- Moving historical plans to remove old names: parked. Historical plans can
  keep old terms as history.

Saturation status: no additional P0/P1/P2 candidate passed the materiality bar
after the four selected candidates.

Recommended next action: grill this plan against ADR-0139, ADR-0140/0141,
domain private-data rules, and eval docs.

## Grill With Docs Batch Result

Saturation audit target:

- this plan
- `ARCHITECTURE.md`
- `docs/human/domain.md`
- `docs/human/evaluation.md`
- ADR-0139, ADR-0140, ADR-0141, and ADR-0145

Result: no decision-impact batch is required before preflight.

Reasons:

- ADR-0139 already decides the public household command shape:
  no-preset prompt for open tasks and `preset=cleanup|map-build` for repeated
  jobs.
- ADR-0140 and ADR-0141 already decide that eval suites are first-class
  maintainer artifacts and that product runs remain separate.
- Domain docs already define Robot Run, Agent View, Private Evaluation,
  Private Scoring Truth, Generated Mess Set, Base Metric Map, and Runtime
  Metric Map clearly enough to protect the private-data boundary.
- The user's new decision resolves the only missing conceptual point:
  Long Horizon is not an eval exception or runner dimension.
- Remaining choices are implementation defaults: exact module filenames,
  mechanical import ordering, and how to split tests during execution.

Plan state: ready for preflight or direct implementation planning.

Recommended next action: turn this plan into an execution preflight before
editing code.

Shortcut: `LGTM` means prepare the execution preflight for this plan.
