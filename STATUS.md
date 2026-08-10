# Project Status

Last updated: 2026-08-10

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

Phoenix information architecture simplification is implemented under
`docs/plans/2026-08-10-phoenix-information-architecture-simplification.md`.
Future traces route only to `roboclaws-runtime` or `roboclaws-eval`; arbitrary
Project selection is removed. Eval projection names immutable Datasets by suite
version and requires a version bump for public sample changes, avoiding Phoenix
11.20's missing modify/remove snapshot APIs. It resolves exact Dataset versions,
partitions heterogeneous bundles into readable homogeneous Experiments, and
reuses Experiments, runs, and evaluations by full immutable identity.

Focused tests, the full repo verification gate, and two consecutive projections
against a fresh task-owned Phoenix 11.20 service pass. Live Kimi evidence
exported a normal runtime trace and three serial EvalTrial traces with ready
telemetry and no drops or failures; Phoenix's built-in `default` Project has
zero spans. The standalone product attempt reached `agent_done` but failed an
existing cleanup checker on post-place observation coverage. The eval bundle
completed `2/3`.

## Previous Focus

The reviewed multi-scene Skill-delivery probe is complete at
`output/eval-probes/20260805-skill-delivery-multiscene/`. It paired
`static-full` and `no-skill` on MolmoSpaces scenes 0, 10, and 12 with
`kimi-k2.7-code`, identical runtime/tool identity, local serial execution, and
zero automatic retries. Both cells are authoritative eval `0/3`; each has one
behaviorally successful `run_result` at 0.8 restoration, but the checker rejects
the semantic evidence. All six trials reached the product checker without
provider, network, runtime, or privacy failures. The result is inconclusive;
the product default remains unchanged and no baseline/catalog was published.

See `docs/status/active/skill-delivery-multiscene-probe.md` for the paired table
and evidence paths.

Eval Evolution Phases 0-4 are complete under
`docs/plans/2026-08-04-eval-evolution-agent-sdk.md`. Optimizer and robot roles
use OpenAI Agents SDK, feedback is sanitized, campaign/candidate identity is
frozen, holdout is sealed, and promotion is human-only. Skill, MCP-description,
and isolated existing-tool response-projection candidates are available through
the blocked-by-default `just agent::eval evolve|evolve-promote` facade. Codex
CLI remains outside the implementation.

Final proof includes local and CloudML candidate-isolation denial, an equivalent
paired baseline/candidate product smoke, and the diff-selected live matrix at
`output/eval-harness/20260805T101810Z/`. The live session row passed. Across the
five cleanup delivery rows, `static-full`, `no-skill`, `dynamic-routed`, and
`sandbox-skills` each passed 1/3 while `dynamic-full` passed 0/3. Every failed
trial reached the product checker; none was a provider, network, or harness
failure. No candidate was promoted and no default or durable baseline changed.

The post-refactor Skill delivery comparison is terminal at
`output/eval-harness/20260804T121407Z/`. It tested five cells with the kickoff
goal only in user input, using `kimi-openai-chat` / `kimi-k2.7-code`, cleanup
seed 7, and three serial repetitions per cell. `no-skill` passed 3/3;
`static-full` passed 2/3; `dynamic-full` and restricted `sandbox-skills` each
passed 1/3; `dynamic-routed` passed 0/3. The failed trials were checker/behavior
failures, not provider or infrastructure failures.

This one-scene matrix challenges `static-full`, but it is insufficient to
remove the Skill globally. The product default remains unchanged pending a
reviewed multi-scene `no-skill` versus `static-full` confirmation. Dynamic and
Sandbox delivery have no promotion case. The Sandbox runtime passed its local
Docker isolation contract with network disabled, no mounts or sensitive
environment, and only the selected Skill reader exposed. No durable
baseline/catalog artifact was published. See
`docs/plans/2026-08-03-agent-skill-delivery-eval.md`.

Phase 1 Eval Evolution Skill smoke completed at
`output/eval-evolution/20260805-skill-smoke-v4/`. The Agents SDK optimizer
materialized a content-addressed candidate and the paired robot training
matrix ran with frozen identity and zero retries. Deterministic gates passed,
but authoritative training status failed, so selection returned
`no_improving_candidate`; sealed holdout and promotion were correctly skipped.

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

Keep the product Skill-delivery default unchanged; its separate multi-scene
confirmation requirement still applies. Phoenix information architecture has
no remaining implementation or verification action.

## Current Blockers

- Eval baseline publication remains blocked until a new full candidate replaces
  the invalid `20260803T023049Z` evidence and receives human confirmation.
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
