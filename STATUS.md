# Project Status

Last updated: 2026-08-04

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

Eval Evolution Phase 0 is complete under
`docs/plans/2026-08-04-eval-evolution-agent-sdk.md`. The accepted contracts bind
both optimizer and robot roles to OpenAI Agents SDK, keep optimizer-visible
feedback sanitized, freeze campaign/candidate identity, require sealed holdout
and human promotion, and expose blocked-by-default `just agent::eval
evolve|evolve-promote` commands. Phase 1 is the current Skill vertical slice.
Codex CLI remains outside the implementation, and MCP behavior candidates
remain barred from live execution until Phase 3 malicious isolation passes.

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

Phase 2/4 MCP description-only evolution is implemented through deterministic
profile snapshots, immutable tool-set validation, content-addressed candidate
materialization, and a campaign gate. Keep MCP behavior candidate live
execution blocked until Phase 3 malicious isolation passes.

The local Phase 3 isolation contract is proven by
`output/eval-harness/20260804T121407Z/preflight/sandbox-isolation-sanitized.json`
and the Sandbox boundary tests. The required remote placement is blocked:
CloudML has no Docker-capable worker, so MCP behavior live execution remains
disabled. Phase 4 may run description-only deterministic/live proof when its
provider preflight is available; it must not substitute behavior execution.

## Current Blockers

- Eval baseline publication remains blocked until a new full candidate replaces
  the invalid `20260803T023049Z` evidence and receives human confirmation.
- CloudML still cannot host the Docker-backed Sandbox row because its current
  worker has no Docker runtime. Local restricted Sandbox evaluation is proven;
  enabling a CloudML sandbox backend or worker image remains a runtime/cost
  decision.
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
