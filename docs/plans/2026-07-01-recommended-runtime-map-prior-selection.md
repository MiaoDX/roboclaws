---
plan_scope: recommended-runtime-map-prior-selection
status: ACTIVE
created: 2026-07-01
last_reviewed: 2026-07-23
implementation_allowed: true
source:
  - user direction to use EvalHarness and SimOracle to prebuild richer map priors
  - parked operator-console recommended-prior catalog work
related_context:
  - ARCHITECTURE.md
  - docs/human/domain.md
  - docs/human/evaluation.md
  - docs/plans/2026-06-26-map-build-quality-eval-harness.md
  - docs/plans/2026-06-30-operator-console-workflow-simplification.md
  - docs/adr/0146-reuse-canonical-map-priors-for-agent-matrices.md
---

# Recommended Runtime Map Prior Selection

## Plan Ledger

Status: ACTIVE

Current slice: deterministic selector/catalog implementation is complete;
the accepted fixed-map consumer-matrix follow-up is not implemented yet.

Next action: split MapBuild candidate generation from fixed-prior consumer
matrices, then publish one explicitly promoted canonical prior per scene/map
identity.

Blocked on: no implementation blocker. Running a fresh live candidate matrix
still depends on provider/runtime availability.

## Goal

Use EvalHarness to run comparable MapBuild candidates for the same scene, grade
them with SimOracle/grader-only truth, and publish the best accepted Runtime Map
Prior Snapshot into the operator-console recommended-prior catalog.

The operator-console result should be:

- the Runtime Map Prior selector auto-selects an accepted catalog prior for the
  selected scene/backend when one exists;
- the generated launch command passes `runtime_map_prior=<catalog path>` only
  when the selector has a catalog prior or explicit operator override;
- no UI path silently falls back to arbitrary latest MapBuild artifacts.

## Terminology

This plan selects a **recommended Runtime Map Prior Snapshot**. It does not
replace the **Base Metric Map** start-of-run contract.

The Base Metric Map remains the required public start-of-run map context:
occupancy/free-space geometry, frame metadata, robot pose, room-category hints
when available, and artifact-authored inspection candidates.

The recommended prior is a downstream artifact selected at the map-artifact
boundary after MapBuild. It may enrich open-ended and cleanup runs, but it must
not mutate the source navigation map or expose private evaluation truth.

## Reusable Map Execution Contract

Accepted 2026-07-23 and recorded in ADR-0146:

- The normal provider/model baseline consumes one immutable canonical Runtime
  Map Prior per `(scene, backend, source_map_identity)`; it does not rebuild the
  map once per provider cell.
- MapBuild candidates remain available in a separate `map_build_quality`
  matrix. Their builder/provider/model provenance is retained even when one
  candidate is promoted as canonical.
- `task_matrix_on_fixed_map` is the default downstream comparison. A full
  builder-by-consumer cross product and same-provider end-to-end flow are
  explicit research/nightly profiles, not implicit baseline work.
- No-prior controls do not execute MapBuild as an incidental suite dependency;
  they run directly against the Base Metric Map. Fixed-prior consumers read the
  promoted artifact read-only.
- Promotion into the default catalog requires explicit maintainer approval of
  an accepted selector report. A passing candidate must not silently replace a
  previously promoted prior.
- Canonical artifacts are immutable and content-addressed. The identity must
  include scene/source-map identity, backend, builder model/provider, prompt or
  skill version, evidence lane/camera labeler, seed, and map schema version.
  Source-map, backend, builder, evidence, seed, or schema changes create a new
  artifact; grader wording changes may use advisory regrade.

The intended execution shape is:

```text
scene + builder profile
  -> MapBuild candidate(s)
  -> quality/private-boundary gates
  -> maintainer promotion
  -> immutable canonical Runtime Map Prior
  -> parallel provider/config consumer matrix
```

## Selection Contract

### Catalog Key

Recommended-prior entries are keyed by stable scene/map identity:

- `world`
- `backend`
- source map or map bundle identity
- scene source/index or equivalent scene identity

Do not key the catalog by cleanup `scenario_setup`, relocation seed, generated
mess set, relocated object identities, or hidden target details. Those belong to
private evaluation and per-run cleanup setup, not to reusable scene-map priors.

### Candidate Generation

For each catalog key, EvalHarness runs MapBuild candidates with the same public
scene input and comparable runtime limits. Candidate axes may include:

- `agent_engine`
- `provider_profile`
- evidence lane and camera labeler when allowed by the product route
- model/runtime timeout class

Each candidate records:

- product route identity;
- MapBuild artifact paths;
- Runtime Map Prior Snapshot path;
- producer profile/model identity;
- run id and output directory;
- cost/usage when available;
- source map identity;
- artifact schema versions.

### Hard Gates Before Ranking

A candidate must pass hard gates before it can be ranked:

- Runtime Map Prior Snapshot schema is valid.
- Source map/Base Metric Map artifacts are not mutated.
- Private scoring truth, generated mess sets, hidden target lists, acceptable
  destinations, and full simulator inventory are absent from agent-facing map
  artifacts.
- Public semantic anchors and target/actionability evidence meet accepted
  thresholds.
- SimOracle/grader-only fixture or scene truth validates map quality, such as
  fixture category recall/precision and best-view waypoint correctness.
- RGB-only observations do not claim trusted object map-frame poses.
- Downstream open-ended and cleanup rows show no accepted utility regression
  against the no-prior baseline.

### Ranking

Only accepted candidates enter ranking. The selector chooses the best accepted
prior using downstream utility first, then quality and operational tie-breaks:

1. open-ended and cleanup prior-vs-no-prior improvement;
2. search-cost reduction and prior-use verdicts such as `stable_anchor_used`;
3. semantic-anchor/actionability quality;
4. cost, latency, provider stability, and model/tool-call reliability.

Provider health alone is not sufficient to select a prior.

### SimOracle Boundary

SimOracle and grader-only truth may score candidates and explain selection in
maintainer reports. They must not inline private truth into:

- Runtime Map Prior Snapshot artifacts;
- operator-console route payloads;
- MCP profile metadata;
- Agent View;
- prompt/context passed to open-ended or cleanup agents.

Selection reports may link maintainer-only private artifacts, following the
eval-harness manifest boundary, but public prior artifacts must remain
public/private safe.

### Staleness Policy

Catalog entries should be reproducible and pinned, but not so strict that every
minor metadata or grader wording change forces a rerun.

Use a compatibility classification:

- `compatible`: source map identity, artifact schema, and public map contract
  are still compatible; keep using the prior.
- `advisory_regrade`: grader/report code changed or better scoring is
  available; regrade existing artifacts when useful, but do not disable the UI
  default.
- `stale`: source map content, Runtime Map Prior Snapshot schema, or public
  map/actionability contract changed in a way that may affect task behavior;
  keep the prior visible with a stale warning and prefer refreshing before
  publishing new baselines.
- `blocking_stale`: source map identity no longer matches the scene/backend,
  the artifact is missing or unreadable, or the public/private boundary cannot
  be verified; do not auto-select this entry in the Runtime Map Prior selector.

Small doc edits, report wording changes, unrelated evaluator refactors, or
non-contract metadata changes should not invalidate a catalog prior.

## Operator Console Behavior

When a selected scene/backend has an accepted non-blocking catalog entry:

- the normal `Open Task` and `Cleanup` workflows show the accepted prior as the
  selected optional Runtime Map Prior.
- The command preview and launch request include the catalog
  `runtime_map_prior` path.
- The UI shows the selected prior provenance and any non-blocking staleness
  warning.
- The operator may still override the prior path explicitly.

When no accepted prior exists, keep the current empty state:

- the Runtime Map Prior selector shows no recommended prior;
- the UI offers Build Map or explicit override, while normal workflows can
  still launch without `runtime_map_prior` when their route is otherwise ready;
- no arbitrary latest artifact becomes the default prior.

## Implementation Slices

1. Add a prior-selection plan/eval manifest shape that groups MapBuild
   candidates by catalog key.
2. Extend EvalHarness or add a thin command to run/regrade candidate matrices
   across model/provider profiles.
3. Add a selector that consumes eval results and emits a recommended-prior
   catalog entry plus selection report.
4. Add operator-console catalog loading for accepted entries and non-blocking
   staleness warnings.
5. Add tests proving hard gates, private-boundary protection, compatibility
   classification, no latest-artifact fallback, and UI default enablement only
   from accepted non-blocking catalog entries.
6. Split the current combined `map_build_consumer` execution into reusable
   MapBuild candidate generation, no-prior controls, and fixed-prior consumer
   matrix modes without changing existing result/grader schemas.
7. Add content-addressed canonical-prior lookup and cache invalidation tests
   for scene/source-map, backend, builder, evidence, seed, and schema changes.
8. Add an explicit end-to-end profile for same-provider MapBuild plus consumer
   runs; keep it out of the normal provider baseline.

## Non-Goals

- Do not expose SimOracle truth, generated mess sets, hidden target lists,
  acceptable destinations, or full simulator inventory to agents.
- Do not make `Base Metric Map` model-selected or provider-selected.
- Do not key reusable priors by one cleanup relocation setup.
- Do not require rerunning live MapBuild for every doc/report/evaluator
  wording change.
- Do not remove operator override.

## Acceptance Gates

- EvalHarness can produce or regrade a comparable candidate set for one scene.
- Selector rejects candidates that fail private-boundary or schema hard gates.
- Selector emits a catalog entry only for an accepted Runtime Map Prior
  Snapshot with pinned provenance.
- Compatibility classification distinguishes minor changes from
  `blocking_stale`.
- Operator console auto-selects Runtime Map Prior entries only for accepted
  non-blocking catalog entries or explicit overrides.
- Unit/contract coverage proves no fallback to latest artifacts.
- The default provider matrix reads one promoted canonical prior and records
  its digest/provenance without launching MapBuild per provider.
- No-prior controls do not launch or depend on a MapBuild producer.
- Builder quality, fixed-prior consumer, and end-to-end reports are separately
  identifiable and cannot be mistaken for one another.
