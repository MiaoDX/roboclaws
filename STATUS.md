# Project Status

Last updated: 2026-08-24

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

The isolated Opik 2.2.36 eval-observability pilot is complete. Its trace and
Experiment drilldown were strong, but hidden `evaluation_suite` discovery,
missing documented persistent-dashboard provisioning, and a seven-service
self-host footprint did not justify replacing the current stack. The decision
is to retain Phoenix plus the companion report and not keep Opik as a second
production observability system. The reproducible pilot deployment and
projector remain diagnostic evidence only; see
`docs/plans/2026-08-24-opik-self-host-eval-observability-pilot.md`.

Completed Eval Harness decision reports now have a persistent local companion
view through the existing report server. Terminal runs publish
`eval_harness.completed.json` only after the JSON, Markdown, and HTML artifacts
are atomically written and hashed; the server lists only valid completed runs
at `http://127.0.0.1:6100/`, redirects `/latest`, and serves stable run-id
routes while retaining Phoenix Experiment/Run drilldown links. Phoenix remains
the trace and Experiment browser rather than a second metric owner. See
`docs/human/evaluation.md` and
`docs/plans/2026-08-18-observability-decision-report.md`.

The terminal Eval Harness now derives a quality-first observability decision section in the
existing `eval_harness.json`, `eval_harness.md`, and `eval_harness.html`. It separates capability
health, provider-treatment comparison, failure/stall triage, and telemetry coverage; quality,
model-work, and latency eligibility are independent, missing telemetry stays unavailable, and
Phoenix remains trial-linked drilldown only. The persisted `20260817T072338Z` candidate replayed
exact 27/1/1 health, provider coverage, concurrency rejection, and the existing session/stall
owners. The final selector proof passed 17 rows directly and all four fixed-prior provider rows in
a separate explicit-prior attempt. See
`docs/plans/2026-08-18-observability-decision-report.md`.

The automatic-Phoenix full eval baseline candidate is complete at
`output/eval-harness/20260817T072338Z/`. Of 29 selected rows, 27 passed, one
failed, and one was blocked; 20 ran on CloudML and nine ran locally. The
`openai-agents-sdk-session-live-eval` row regressed after
`stopped_by_operator` and was classified `harness_bug_unclassified`. The
`openai-agents-sdk-cleanup-dynamic-full-eval` bundle retained two passing trials
and one `environment_blocked` trial after a 180-second model-call stall. One
CloudML infrastructure retry repaired an eval-unit-tests Git ownership mismatch.
The credential-value scan found no leaks. This candidate is terminal evidence,
not an accepted baseline, and publication remains unauthorized.

Phoenix information architecture simplification is implemented under
`docs/plans/2026-08-10-phoenix-information-architecture-simplification.md`.
Future traces route only to `roboclaws-runtime` or `roboclaws-eval`; arbitrary
Project selection is removed. Eval projection names Datasets by stable suite
task, keeps suite version and content identity in metadata, and binds every
Experiment to one exact immutable Dataset version. Public sample changes require
a suite-version bump plus an explicit local Phoenix rebuild and reprojection
because Phoenix 11.20 cannot modify or remove snapshot examples. Heterogeneous
bundles split into readable homogeneous Experiments, and unchanged Experiments,
runs, and evaluations reuse full immutable identity.

Repo-native suite completion now automatically projects its persisted results
when the loopback Phoenix OTLP endpoint is configured. CLI and Eval Harness
evidence include the adjacent fail-open receipt; accepted CloudML bundles use
the same projector during local collection. Manual `phoenix-project` remains
only for repair, backfill, and dataset-only projection. During the new baseline,
local suite completion visibly advanced the permanent Phoenix 11.20 store from
17 Experiments, 55 Runs, and 249 Evaluations to 23 Experiments, 68 Runs, and 302
Evaluations while retaining seven Datasets. Final collection replaced worker-
local disabled receipts: all 16 repo-suite bundles are `ready`, including the
blocked dynamic-full bundle, while `operator_session_live` remains Trace-only
under its specialist schema. A second complete finalization kept all four
Phoenix counts unchanged, proving immutable projection reuse.

Historical Phoenix backfill is complete for nine prior terminal full baseline
and candidate roots from 2026-07-28 through `20260817T015316Z`. Of 125 canonical
bundles, 105 repo-suite bundles are `ready`, eight specialist session bundles
are explicitly `not_applicable`, and 12 bundles from the oldest 2026-07-28 run
were removed because their recorded sample release does not match the current
suite release. Archive copies and ad-hoc smoke/debug runs were excluded.
The backfill advanced Phoenix to eight Datasets, 42 Experiments, 110 Runs, and
435 Evaluations; a second pass reused the same identities and the credential-
value scan found no leaks. Evidence is under
`output/eval-harness/phoenix-historical-backfill-20260817T105951Z/`.

The live Phoenix 11.20 database now uses the repo-local bind mount
`output/phoenix/` instead of a hidden Docker named volume. Migration preserved
all eight Datasets, 42 Experiments, 110 Runs, 435 Evaluations, and three
Projects; the previous `phoenix_phoenix-data` volume remains as a point-in-time
rollback copy.

## Previous Focus

The reviewed multi-scene Skill-delivery comparison remains inconclusive and did
not change the product default or publish a baseline. See
`docs/status/active/skill-delivery-multiscene-probe.md` and
`docs/plans/2026-08-03-agent-skill-delivery-eval.md` for the paired evidence.

Eval Evolution Phases 0-4 are complete under
`docs/plans/2026-08-04-eval-evolution-agent-sdk.md`. Candidate identity,
isolation, sealed holdout, and human-only promotion are enforced; no candidate
was promoted. The blocked-by-default public facade remains
`just agent::eval evolve|evolve-promote`.

The invalid hybrid candidate at `output/eval-harness/20260803T023049Z/` remains
retained as evidence and unpublished. Its checker/eval ownership regression is
fixed: product checker failures now fail closed, `done` is terminal, and one
canonical completion snapshot is shared across runtime evidence surfaces.

The active product shape is:

- `surface=household-world` for no-preset open household goals.
- `surface=household-world preset=map-build` for Runtime Metric Map evidence.
- `surface=household-world preset=cleanup` for cleanup.
- `surface=planner-proof` for the confidence route.

Current household map/runtime contracts:

- Base Metric Map is the required start-of-run map context.
- Runtime Metric Map owns map-build and observation semantic evidence.
- Runtime Map Prior Snapshot is the downstream prior wrapper.
- Canonical Runtime Map Priors are explicitly promoted, content-addressed, and
  reused read-only across normal provider consumer matrices.
- Product runtime, smoke helpers, and current tests fail loudly when a required
  Base Metric Map bundle is missing.

Eval suites are first-class architecture evidence. Deterministic suites are
available through:

```bash
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=open_ended_goals budget=smoke
just agent::eval suite=map_build_quality budget=smoke
just agent::eval suite=map_consumer_no_prior budget=smoke
```

Live eval execution is opt-in with `live_execution=run`; default non-direct eval
requests record blocked identity/preflight packets instead of launching real
providers.

## Next Action

Use the generated decision section when investigating future terminal candidates. The new required
live proof passed the prior session-live and dynamic-full rows, but it does not publish or accept a
baseline. Keep the product Skill-delivery default unchanged; its separate multi-scene confirmation
requirement still applies.

## Current Blockers

- The `20260817T072338Z` eval candidate is not publishable because it contains
  one behavior failure and one blocked trial bundle.
- Agibot and B1 injected dependency readiness passes with the existing local SDK, Map 12 bundle,
  B1 scene, and alignment/navigation proofs. Real-robot movement remains unauthorized and requires
  a present operator plus the existing localization, run-enablement, and E-stop gates.

## Human Review Surface

- Project orientation: `README.md`
- Architecture and contracts: `ARCHITECTURE.md`
- Public command grammar: `just/README.md`
- Skill-first MCP design:
  `docs/human/mcp-skills-and-semantic-profiles.md`
- Local runtime and provider keys: `docs/human/local-runtime.md`
- Evaluation docs: `docs/human/evaluation.md`
- Current model/provider notes: `docs/human/model-matrix.md`
- Human docs index: `docs/human/README.md`

## Current Source Links

Plans:
`docs/plans/2026-08-02-household-backend-port-refactor.md`,
`docs/plans/2026-07-31-refactor-just-command-surface.md`,
`docs/plans/2026-07-30-aggressive-architecture-migration.md`,
`docs/plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md`,
`docs/plans/2026-07-30-post-cleanup-saturation-refactors.md`,
`docs/plans/2026-07-28-forward-only-post-review-cleanup.md`,
`docs/plans/2026-07-27-restore-codex-mimo-responses-cells.md`,
`docs/plans/2026-07-01-recommended-runtime-map-prior-selection.md`,
`docs/plans/2026-06-26-map-build-quality-eval-harness.md`,
`docs/plans/2026-06-20-cross-environment-map-waypoint-source-of-truth.md`,
`docs/plans/2026-06-18-b1-map12-semantic-and-public-nav-followups.md`,
`docs/plans/2026-06-17-b1-map12-two-map-alignment-blocker.md`,
`docs/plans/2026-06-17-sim-map-surface-simplification.md`,
`docs/plans/2026-06-16-open-ended-eval-matrix-expansion.md`,
`docs/plans/2026-06-15-non-cleanup-eval-support.md`,
`docs/plans/2026-06-14-eval-driven-architecture.md`, and
`docs/plans/2026-06-11-household-map-launch-open-ended-contracts.md`.

ADRs:
`docs/adr/0140-use-eval-suites-as-first-class-architecture-layer.md`,
`docs/adr/0136-use-base-metric-map-and-first-class-household-launch-contracts.md`,
and `docs/adr/0138-use-detector-only-visual-grounding-sidecar.md`.

## AI-Agent Sources

- Agent operating details: `docs/agents/operating-runbook.md`
- GSD execution state: `.planning/STATE.md`
- Current GSD phase details: follow the latest phase link in `.planning/STATE.md`
- Pre-GSD plans: `docs/plans/`
- Durable decisions: `docs/adr/`
- Shipped history: `docs/retrospectives/`
- Concurrent standalone work: `docs/status/active/`

## Repo-Wide Parked Work

- Queued implementation tasks unrelated to the current active focus:
  `TODOS.md`
- Scratch ideas and future directions unrelated to the current active focus:
  `THOUGHTS.md`
- GitHub issues track externally visible work for `MiaoDX/roboclaws`.

The cleanup plan is mechanically archiving only explicitly terminal active
capsules; active, blocked, ambiguous, and JSON evidence surfaces remain in
place.

## Workflow Contract

Use the staged workflow:

`idea -> docs/plans/<slug>.md -> review/autoplan -> GSD plan/execute -> verify -> retrospective`

Rules:

- `STATUS.md` answers "what is happening now?"
- `docs/plans/` owns pre-GSD plans.
- `.planning/` is GSD-owned execution detail.
- `docs/human/` is the human-readable doc set.
- `docs/adr/` records durable decisions, not progress.
- Root `PLAN.md` is a legacy pointer, not an active plan.
- `TODOS.md` and `THOUGHTS.md` are parked-work surfaces, not current status.
- Parallel terminals should use one task-owned file under
  `docs/status/active/`.
- At GSD closeout/verify/ship, update this file only if repo-level current
  focus, latest phase, next action, or blocker changed.
