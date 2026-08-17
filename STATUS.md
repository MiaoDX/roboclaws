# Project Status

Last updated: 2026-08-17

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

The full eval baseline candidate is complete at
`output/eval-harness/20260817T015316Z/`. All 29 selected rows passed: 20 ran on
CloudML and nine ran locally. The matrix has no missing, duplicate, mismatched,
unknown, failed, or blocked rows; it has no outcome regressions against the
previous 25-row durable baseline. Three infrastructure-only retries completed
successfully, and the credential-value scan found no leaks. Publication remains
unauthorized pending human confirmation.

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
only for repair, backfill, and dataset-only projection. The full verification
gate passes, two automatic smoke runs reused identical Phoenix identity, and
the completed 29-row candidate was projected without rerunning providers. Its
16 repo-suite bundles are `ready`; `operator_session_live` remains Trace-only
under its specialist schema. Repeated projection kept the permanent Phoenix
11.20 store stable at seven Datasets, 17 Experiments, 55 Runs, and 249
Evaluations, with no credential values in the new receipts.

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

Review the 29-row candidate at `output/eval-harness/20260817T015316Z/` and
confirm or reject durable baseline publication. Keep the product Skill-delivery
default unchanged; its separate multi-scene confirmation requirement still
applies. Phoenix information architecture has no remaining implementation or
verification action.

## Current Blockers

- Eval baseline publication is awaiting human confirmation of the complete
  `20260817T015316Z` candidate.
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
