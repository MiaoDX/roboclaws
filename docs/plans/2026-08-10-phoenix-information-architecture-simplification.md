---
plan_scope: phoenix-information-architecture-simplification
status: DONE
created: 2026-08-10
last_reviewed: 2026-08-11
implementation_allowed: true
current_phase: complete
source:
  - user request to reduce Phoenix concept and navigation cost
  - user preference to preserve Projects as a meaningful first-tab abstraction
  - official Arize Phoenix project, dataset, and experiment documentation
related_context:
  - docs/plans/2026-08-06-self-hosted-agent-observability-platform.md
  - ARCHITECTURE.md
  - docs/human/evaluation.md
  - docs/human/local-runtime.md
---

# Phoenix Information Architecture Simplification

## Plan Ledger

- Plan status: DONE; implementation and all required verification are complete.
- Session scope: Phoenix Project, Dataset, and Experiment ownership and naming.
- Parent plan: `2026-08-06-self-hosted-agent-observability-platform.md`.
- Current slice: none.
- Next action: none for this plan.
- Blocked on: nothing.
- Do not touch from this session beyond the approved local Phoenix volume rebuild: runtime
  behavior, eval execution, provider calls, canonical artifacts, privacy policy, or durable
  baseline/catalog data.
- Final proof: focused Phoenix and endpoint-owner tests, all eval/launch/operator-console unit
  tests, two consecutive projections against a fresh Phoenix 11.20 service, both required live SDK
  proofs from the preceding implementation slice, and `just agent::verify` all pass. The permanent
  local store was then rebuilt and the eight existing baseline bundles were projected twice: the
  API reports six task-only Datasets, eight Experiments, 32 Runs, and an empty `default` Project;
  the ready v3 mappings record 151 Evaluations.

## Decision Summary

Use Phoenix's three concepts, but give each exactly one job:

| Phoenix concept | Roboclaws meaning | Cardinality |
| --- | --- | --- |
| Project | Stable observability context for Robot Run trace browsing | Exactly two |
| Dataset | Stable eval task containing one immutable public sample release | One per `suite_id` |
| Experiment | One homogeneous tested configuration against one exact dataset version | One per configuration partition of a projected result bundle |

The default Project taxonomy is:

- `roboclaws-runtime`: product/operator Robot Runs, including ad-hoc and demo runs.
- `roboclaws-eval`: Robot Runs executed as EvalTrials.

There is no third Project in this plan. Optimizer role, provider, model, task, surface, world,
backend, intent, Skill delivery, prompt digest, suite, sample, trial, Git SHA, and time remain
searchable attributes. They never create Projects. A future Project requires a separate plan backed
by observed trace-navigation noise.

## Why This Shape

Phoenix opens on Projects, so using one catch-all Project would discard a useful high-level split.
Using a Project for every model, provider, task, date, or eval execution would produce an unstable
navigation tree and duplicate dimensions already present in span attributes and experiments.

Phoenix's official model supports this boundary:

- Projects group trace data for an application/use case, environment, initiative, or team; traces
  for one application are typically grouped into one Project.
- Datasets are versioned collections of examples.
- Experiments run one task/application configuration against examples in a Dataset and attach
  evaluations for comparison.

For Roboclaws, Projects answer **where did this workflow run and what happened?** Datasets and
Experiments answer **how did this fixed sample set perform under this tested configuration?**

Official sources reviewed on 2026-08-10:

- <https://arize.com/docs/phoenix/tracing/llm-traces/projects>
- <https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-projects>
- <https://arize.com/docs/phoenix/datasets-and-experiments/overview-datasets>
- <https://arize.com/docs/phoenix/datasets-and-experiments/concepts-datasets>

## Scope

### In Scope

- Route trace export to a stable Project from closed observability context at the telemetry composition
  root.
- Replace the current single global default Project and arbitrary Project-name environment override
  with the two-project taxonomy.
- Give every eval suite task one stable human-readable Phoenix Dataset name and fail projection
  when its immutable public content no longer matches the deployed local store.
- Partition every projected result bundle by homogeneous public tested-configuration identity and
  give each resulting Experiment a concise, human-readable name while retaining exact identity in
  metadata.
- Preserve idempotent projection: projecting the same suite content or result bundle again reuses
  the same Phoenix objects and does not duplicate runs or annotations.
- Update focused tests and human docs so a reader can understand the UI through the two-question
  mental model above.

### Non-Goals

- No new generic project registry, plugin system, or user-configurable routing DSL.
- No arbitrary Project-name override. Telemetry remains opt-in through its endpoint setting.
- No Project per provider, model, task, suite, sample, trial, date, branch, Git SHA, or run.
- No change to eval suite/sample/trial identity, graders, execution, promotion, or canonical local
  artifacts.
- No Phoenix-driven runtime configuration or mutable prompt/dataset fetch.
- No expansion of exported data. Existing closed-schema, privacy, loopback OTLP, asynchronous,
  bounded, fail-open, and one-way projection contracts remain invariant.
- No deletion, merge, rename, or mutation of existing Phoenix Projects/Datasets/Experiments in the
  implementation phase without a separate explicit human-approved migration action.
- No Phoenix upgrade, authentication topology change, cross-machine collector, or LAN exposure
  change.

## Target Ownership And Flow

```text
observability context
  |-- normal/operator run ----------------------> Project: roboclaws-runtime
  `-- eval trial -------------------------------> Project: roboclaws-eval
                                                    |
eval suite task -> immutable Dataset version -> exact examples |
eval result bundle -> Experiment -> runs/scores ---+
```

Ownership rules:

1. The eval launch owner supplies an internal closed `observability_context=eval`; normal launches
   supply `observability_context=runtime`. This is telemetry identity, not a new public launch axis.
   The telemetry composition root maps only those two values to Project constants. Missing,
   malformed, or contradictory eval context disables external export for that run and records a
   local limitation; product execution remains fail-open.
2. The eval projection owner maps `suite_id` to stable Dataset display identity and verifies the
   exact `(suite_version, public content)` release against an explicit Phoenix Dataset version. It
   never launches eval work or relies on an implicit latest version.
3. The result bundle owns one or more Experiment identities. Each Experiment has exactly one public
   tested-configuration key; provider/model/configuration fields partition Experiments rather than
   Projects.
4. Local artifacts remain canonical. Phoenix IDs and URLs remain projection results only.

## Naming Contract

Names optimize scanning; metadata provides exact identity.

- Project: fixed constants `roboclaws-runtime` and `roboclaws-eval`.
- Dataset: `roboclaws-<suite-id>` after canonical path-token normalization.
- Dataset version identity: Phoenix `dataset_version_id` plus a digest recomputed from the public
  examples fetched for that exact version. The local mapping records suite ID, suite version, full
  dataset digest, version ID, and projection schema.
- Experiment: a deterministic readable label derived from suite version and tested configuration,
  with a short uniqueness suffix only where Phoenix requires it.
- Tested-configuration key: the closed public configuration fields present in `EvalResult` identity,
  initially `agent_engine`, `provider_profile`, `model`, `skill_name`, `prompt_source_git_sha`, and
  `prompt_skill_sha256`, with explicit missing markers. Sample, trial, repetition, trace, status,
  and rendered-prompt identity do not partition configurations.
- Experiment metadata: exact Dataset version ID, tested-configuration key and digest, full source
  bundle digest, Experiment projection digest, and projection schema.

The implementation must not depend on parsing display names. Exact lookup and idempotency use
immutable metadata/digests and Phoenix IDs.

The final Experiment display-name grammar is intentionally left for implementation preflight after
fixtures inventory the public result fields. The preferred order is human configuration first,
then a short digest suffix; timestamps are not identity.

## Migration Inventory And Policy

Known Projects observed on 2026-08-10:

- `default`
- `roboclaws-phase1-live-poc`
- `roboclaws-phase1-overhead`
- `roboclaws-phase1-poc`
- `roboclaws-phase1-verified`
- `roboclaws-phase1-verified-v2`

Known Datasets observed on 2026-08-10:

- `roboclaws-household_world_cleanup_capability-b41dd238efa89670`
- `roboclaws-household_world_smoke_regression-bb7f48f1a608acc5`

These are historical evidence, not implementation debris. The code migration changes only future
routing/projection. They remain untouched; this plan creates no later archive, rename, or deletion
track.

## Implementation Plan

### Phase 1: Freeze Identity And Routing

- Add focused fixtures covering normal product runs, eval trials, missing context, partial eval
  identity, and contradictory context.
- Define the small closed mapping from observability context to the two Project constants at the
  existing telemetry composition boundary.
- Remove `ROBOCLAWS_PHOENIX_PROJECT`; no compatibility shim or alternate arbitrary-name path remains.
- For invalid telemetry context, skip Phoenix export and record an actionable local limitation; do
  not silently route to a catch-all Project and do not fail product execution.
- Preserve opt-in telemetry and the existing loopback-only OTLP endpoint contract.

### Phase 2: Prove Exact Dataset Versions And Use Stable Task Identity

- First run a disposable pinned-Phoenix 11.20 API fixture proving exact version reads and explicit
  Experiment binding. This is a projection contract test only; it does not use production datasets.
- The proof must rediscover versions through supported public APIs, query examples with the
  supported `version_id` request parameter, recompute the full public-content digest, and create an
  Experiment using that resolved version ID. The returned Experiment must report the same exact ID
  as `dataset_version_id`.
- Name the Dataset from `suite_id`. Unchanged projection reuses that Dataset and exact version.
  Add, modify, or remove changes require a suite-version bump followed by an explicit local Phoenix
  rebuild and reprojection; content drift or append history fails with an actionable reason.
- Do not use Phoenix private APIs, destructive history mutation, a custom version registry, or a
  client dependency to emulate modify/remove snapshots under one Dataset.
- Failure to create and rediscover an Experiment bound to an exact `dataset_version_id` blocks
  Phase 3; implicit latest-version binding is never an allowed fallback.
- Correctness depends on version ID plus recomputed public-example digest and the canonical local
  mapping. Remote description or metadata is supplemental only where Phoenix 11.20 demonstrably
  supports immutable version-scoped fields.

### Phase 3: Make Experiments Readable

- Run against the exact version resolved from the immutable task Dataset.
- Partition results by the tested-configuration key before creating Experiments. A homogeneous
  bundle creates one Experiment; a heterogeneous comparison bundle creates one Experiment per
  unique configuration, linked by the source bundle digest. Repetitions remain runs inside that
  Experiment.
- Define Experiment identity from the exact Dataset version, configuration key, public trial
  identities, public run status, allowlisted evaluation labels, and grader contract identity. A
  corrected or regraded bundle creates a new immutable Experiment rather than mutating old evidence.
- Move full digests out of the primary label and into metadata; retain a short suffix only to avoid
  collision or ambiguity.
- Reuse by full Experiment projection digest. Reuse runs by exported trial/run digest, not only by
  `(dataset_example_id, repetition_number)`, and reject ambiguous collisions.
- Choose one bounded display grammar from configuration fixtures. Names are never parsed for
  correctness.

### Phase 4: Documentation

- Update `docs/human/local-runtime.md` with the two Project meanings and removal of arbitrary
  Project selection.
- Update `docs/human/evaluation.md` with the Dataset/Experiment mental model and naming examples.
- Update `ARCHITECTURE.md` only if the implemented ownership contract is more specific than its
  current Experiment Telemetry description.

## Acceptance Criteria

- A normal product trace appears in `roboclaws-runtime`; an eval-trial trace appears in
  `roboclaws-eval`.
- The same provider/model/task can appear in both Projects without creating additional Projects.
- Reprojecting unchanged suite content reuses the same exact task Dataset version. Add, modify, and
  remove changes require a suite-version bump plus an explicit local Phoenix rebuild and
  reprojection.
- Public sample content changing without a suite-version bump fails projection explicitly.
- Reprojecting an older suite version is supported only when it is the immutable release currently
  loaded for that task Dataset; local artifacts retain older canonical evidence across rebuilds.
- Reprojecting the same result bundle reuses its Experiment(s), runs, and evaluations.
- A heterogeneous bundle produces one Experiment per unique tested configuration with no
  sample/repetition collision across providers or models.
- A human can identify the suite task from the Dataset label and the suite version plus tested
  configuration from the Experiment label without reading a content hash.
- Full immutable identity remains available in metadata and the local projection mapping.
- The local Phoenix store is rebuilt once during the task-only Dataset-name migration, then
  reprojected from canonical local artifacts. No provider or simulator rerun is required.
- Phoenix unavailable/disabled behavior, queue bounds, terminal flush bounds, privacy denial tests,
  and local canonical artifacts remain unchanged.
- No provider, simulator, CloudML, or hardware execution occurs in projection tests.

## Verification

- Focused unit tests for Project routing, configuration validation, Dataset version lookup/create,
  Experiment naming/idempotency, and unavailable/disabled projection.
- Existing Phoenix telemetry privacy, lifecycle, projection, and CLI contract tests.
- A disposable local pinned-Phoenix integration proof covering immutable task Dataset
  creation/reuse, exact version reads, homogeneous and heterogeneous bundles, and unchanged bundle
  reprojection. Unit contracts cover rejection of same-version public-content drift.
- Stale-name searches proving no active default emits `roboclaws-local`, phase-specific Project
  names, or reads `ROBOCLAWS_PHOENIX_PROJECT`.
- `ruff check` and format checks for changed files.
- `./scripts/dev/run_pytest_standalone.sh` for the focused and relevant broader suites.
- Two bounded live SDK proofs are required because Project routing is visible only through the real
  product/eval composition path. Use the cheapest ready local provider, serial execution, and zero
  agent-initiated retries; no hardware or CloudML work is required.

## Stop Gates

Stop and return for review if:

- Phoenix 11.20 cannot create or resolve the immutable task Dataset through supported APIs;
- Phoenix 11.20 cannot create and rediscover an Experiment bound to the resolved exact
  `dataset_version_id`; in that case block Phase 3 and return for review rather than use implicit
  latest-version behavior;
- the telemetry identity cannot distinguish normal product runs from eval trials without widening
  the public runtime contract;
- readable Experiment naming would require private fields or name parsing for correctness;
- implementation requires deleting or mutating data outside the explicitly approved local Phoenix
  volume rebuild;
- privacy, fail-open behavior, local artifact ownership, or eval identity would change.

## Planning Loop Ledger

Round 1 used three read-only Paseo scouts: `intuitive-reduce-entropy` plan mode, a
`grill-with-docs-batch` review against official Phoenix docs and the live 11.20 OpenAPI, and a
skeptical architecture review.

Accepted:

- Keep the three native concepts but give each one owner and question.
- Use exactly two Projects and remove speculative `roboclaws-optimizer`.
- Remove arbitrary Project-name override and use one closed internal observability context.
- Treat invalid context as telemetry degradation, preserving product fail-open behavior.
- Bind Experiments and example lookup to an explicit Dataset version; never implicit latest.
- Use stable task Dataset identity and reject public-content drift or append history.
- Partition heterogeneous bundles into homogeneous Experiments and strengthen digest/run reuse.
- Remove the repeated historical inventory and any future deletion/classification track.

Rejected:

- Collapse Dataset and Experiment into one concept; they own different native Phoenix contracts.
- Merge Dataset and Experiment implementation phases; Dataset version feasibility has independent
  external API risk.
- Keep an arbitrary Project override for debugging; it recreates the Project-cardinality problem.

Parked:

- Any optimizer-specific Project, pending a separate observed-noise case.
- Historical object rename/archive/delete work.
- Historical digest-named Dataset objects; forward projection does not mutate or reuse them.
- The final Experiment display grammar, which is a bounded fixture-driven implementation default.

Round 2 re-ran all three scouts against the revised plan. Two identified the same narrow version
gate ambiguity; the third found no remaining P0/P1. The gate now distinguishes optional stable
Dataset naming from mandatory exact Experiment-to-Dataset-version binding. No P0/P1 remains after
main-session judgment, the selection scan is saturated, and the planning loop is converged.

Implementation evidence: the disposable Phoenix 11.20 proof confirmed exact `version_id` reads and
explicit Experiment binding, while the supported upload API exposes only create/append. The
forward-only contract therefore gives each suite task one stable Dataset name and treats the loaded
content as one immutable release. Add/modify/remove changes require a suite-version bump followed
by a local Phoenix rebuild and reprojection. Exact version reconciliation, heterogeneous
Experiment partitioning, corrected-evidence immutability, and unchanged reprojection passed against
the task-owned service. On 2026-08-11 the approved permanent local volume rebuild and artifact
reprojection completed without provider or simulator execution. All eight mappings are ready under
`output/eval-harness/20260811-phoenix-baseline-live-default/phoenix-task-names/`; they resolve six
task-only Datasets, eight Experiments, 32 Runs, and 151 Evaluations. A second identical projection
reused the same server objects.

## Preflight Contract

Preflight status: APPROVED AND EXECUTING

Task source: reviewed plan plus the user's request to execute it through intuitive-flow

Canonical source: `docs/plans/2026-08-10-phoenix-information-architecture-simplification.md`

Route: durable `$intuitive-flow`

Goal: Make Phoenix navigation expose exactly two meaningful trace Projects and controlled,
version-bound Dataset/Experiment comparisons without weakening local evidence, privacy, or
fail-open runtime behavior.

Scope:

- Add one closed internal `observability_context=runtime|eval` field at the existing telemetry
  identity/composition boundary and map it directly to `roboclaws-runtime` or `roboclaws-eval`.
- Remove `ROBOCLAWS_PHOENIX_PROJECT` from code, tests, examples, and human documentation without a
  compatibility shim.
- Prove exact Phoenix 11.20 Dataset version reads and Experiment binding in an isolated, task-owned
  Phoenix instance; name each immutable Dataset from suite ID alone, and reject
  same-version public-content drift.
- Partition projected result bundles by the closed homogeneous tested-configuration key, bind each
  Experiment to an exact Dataset version, strengthen immutable projection/run identity, and make
  display names readable without parsing them for correctness.
- Update focused tests, `docs/human/local-runtime.md`, `docs/human/evaluation.md`, and
  `ARCHITECTURE.md` only where the implemented ownership contract requires it.

Non-goals: no Phoenix upgrade; no new dependency solely for Dataset naming; no private Phoenix API;
no registry, plugin, routing DSL, or third Project; no Phoenix mutation beyond the approved local
volume rebuild and artifact reprojection; no eval,
grader, promotion, privacy-schema, artifact, provider-route, LAN/OTLP topology, CloudML, simulator
behavior, or hardware change.

Entity budget: reuse=`PhoenixTelemetryAdapter`, the closed telemetry identity, existing eval result
identity, `PhoenixHttp`, `phoenix-project`, pinned Compose deployment, and local mapping artifacts;
remove/merge=arbitrary Project override, implicit/latest Dataset-version assumptions, hash-first
Experiment labels, and `(example, repetition)`-only run reuse; new=one closed
`observability_context` field and focused disposable Phoenix integration fixture because current
identity/API mocks cannot prove routing or version semantics; expansion triggers=new dependency,
private API, data mutation beyond the approved local Phoenix rebuild, public launch axis, third
Project, cross-machine collector,
provider/resource expansion, or changed privacy/artifact/eval contracts requires re-approval.

Context: must-read=this plan,
`docs/plans/2026-08-06-self-hosted-agent-observability-platform.md`, relevant Experiment Telemetry
sections of `ARCHITECTURE.md`, `roboclaws/agents/phoenix_telemetry.py`,
`roboclaws/agents/household_live_handoff.py`,
`roboclaws/agents/drivers/openai_agents_live.py`, `roboclaws/evals/live_execution.py`,
`roboclaws/evals/phoenix_projection.py`, focused Phoenix tests, `docs/human/local-runtime.md`, and
`docs/human/evaluation.md`; useful=official Phoenix Project/Dataset/Experiment docs and the pinned
11.20 `/openapi.json`; avoid-unless-needed=`STATUS.md` history, shipped retrospectives, unrelated
eval evolution, simulator/backend modules, CloudML, and real-robot sources.

Acceptance:

- SUCCESS: normal product Robot Run traces appear only in `roboclaws-runtime`; EvalTrial traces
  appear only in `roboclaws-eval`; no arbitrary/new Project is emitted; unchanged projection is
  idempotent; every Experiment references the exact intended `dataset_version_id`; heterogeneous
  bundles split without provider/model collisions; corrected/regraded evidence is immutable;
  the rebuilt local Phoenix store contains only task-named Datasets projected from unchanged
  canonical local artifacts; privacy and
  unavailable/disabled fail-open gates pass; docs match the observable UI.
- BLOCKED_NEEDS_DECISION: implementation requires any expansion trigger or data mutation beyond the
  approved local Phoenix volume rebuild.
- BLOCKED_NEEDS_LOCAL_VALIDATION: the isolated Phoenix 11.20 contract proof, normal product trace,
  eval-trial trace, or UI/API hierarchy inspection cannot run or pass locally; code may be an
  intermediate branch but is not complete or merge-ready.
- INTERMEDIATE_ONLY: none.
- No regressions: product/eval outcomes, provider selection, SDK span contents, local artifact
  completeness, privacy allowlist/denials, bounded queue/flush behavior, loopback-only OTLP,
  trusted-LAN web-only exposure, projection fail-open behavior, and canonical local artifacts.

Verification: deterministic=`ruff check .`; `ruff format --check .`;
`./scripts/dev/run_pytest_standalone.sh tests/unit/agents/test_phoenix_telemetry.py
tests/unit/agents/test_live_runtime_contracts.py tests/unit/evals/test_phoenix_projection.py
tests/contract/dev_tools/test_eval_just_recipe.py -q`; relevant broader standalone tests selected by
`just agent::eval recommend plan=docs/plans/2026-08-10-phoenix-information-architecture-simplification.md
budget=focused`; integration=start a separate Compose project named
`roboclaws-phoenix-ia-proof` from `deploy/phoenix/compose.yaml` on loopback ports 16006/14317 with
its own task-owned volume, run immutable task Dataset reuse and exact-version Experiment
proof, then query exact Dataset/version/Experiment/run/evaluation identity; after validating the
Compose project name and volume ownership, tear down only that task-owned project with `down -v`;
product-run=with `ROBOCLAWS_PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:16006/v1/traces`, run one cheapest
ready serial `just run::surface surface=household-world agent_engine=openai-agents-sdk
preset=cleanup evidence_lane=world-public-labels provider_profile=kimi-openai-chat` and one
`just agent::eval suite=smoke_regression budget=smoke agent_engine=openai-agents-sdk
provider_profile=kimi-openai-chat live_execution=run live_retry_limit=0`, using task-owned output
directories; local-live-manual=query the temporary Phoenix API/UI and prove the two Project names,
trace hierarchy, exact Dataset version binding, homogeneous Experiments, readable labels, and zero
unexpected Projects, then run `just agent::verify`; if the named provider is unavailable, select
the cheapest ready documented local profile without expanding to CloudML or hardware and record the
substitution; optional=inspect the permanent LAN UI read-only after success, without publishing or
migrating data.

Execution: main=root session supervises staged implementation, stop gates, disposable service,
live proofs, cleanup, changed-code review, and final complete/blocked judgment; worker=none;
worker-goal=none.

To execute: `/goal execute docs/plans/2026-08-10-phoenix-information-architecture-simplification.md with intuitive-flow`

Optional tracking: none

Approval: `LGTM`, `approve`, or `go ahead` approves; edits request revision.
