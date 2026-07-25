# Project Status

Last updated: 2026-07-25

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

Household MCP capability/backend unification has completed implementation Slices 0-4 and all
currently available deterministic, SDK, eval, and B1/Isaac product proof. The supported B1
MapBuild route now visits all five public waypoints and passes the strict robot-consumption and
1.0 sweep-coverage gates. The active capsule is
`docs/status/active/household-mcp-capability-backend-unification.md`.

MapBuild optimization and testing has reached the current acceptance target:
`preset=map-build` builds a richer, reliable Runtime Metric Map that helps
downstream open-ended and cleanup tasks in the focused eval harness.

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

Hold physical Agibot validation until the operator explicitly resumes it. When robot discovery at
`10.42.1.101:2379` is reachable again, rerun the non-motion status gate first. Real movement still
requires localization, E-stop, safety gates, and operator authorization.

For the completed MapBuild quality/eval harness, use:

`docs/status/active/map-build-quality-eval-harness.md`

Use:

```bash
just agent::eval recommend plan=docs/plans/2026-06-26-map-build-quality-eval-harness.md budget=focused
```

for plan/diff-driven verification recommendations.

## Current Blockers

- No current human blocker for deterministic MapBuild quality-gate work.
- The opt-in CloudML B1/Isaac digital-twin proof remains stopped before Stage A acceptance. The
  pinned Isaac image now carries an exact `580.105.08` NVIDIA Vulkan userspace overlay and selects
  native libraries for exact `570.124.06`; local RTX/Vulkan smoke and both selector branches pass.
  Bounded 2026-07-25 sampling now totals 84 one-GPU tasks plus the earlier 8-GPU and 4-GPU placement
  diagnostics. The latest 56 one-GPU tasks included six same-second eight-task waves and covered
  `slave559`, `slave563`, `slave564`, `slave574`, `slave580`, and `slave589`, but every sampled host
  still reported exact driver `570.124.06`. Those tasks correctly failed before Isaac startup with
  platform retries disabled. A normal one-GPU Stage A must still land on the known `580.105.08`
  host group and pass before Stage B/C can run. No new EULA or per-attempt test approval is required.
  See
  `docs/status/active/cloudml-isaac-digital-twin-proof.md`.
- No current implementation blocker for deterministic or OpenAI Agents SDK smoke
  eval work when using a provider route available on the current network.
- Agibot hardware validation is deferred by operator request, and the discovery service at
  `10.42.1.101:2379` remains unreachable. No real-robot movement should run while this hold is in
  place.
- The focused MapBuild consumer live matrix has historical evidence across the
  target SDK provider profiles. The default `codex-router-responses` route now
  uses `gpt-5.6-sol` and handles Router transport compatibility internally.
- Broader live-agent `pass^k`, RAW-FPV live cleanup, and
  validation-required maintainer routes still depend on provider/runtime
  capacity and route-specific availability proof.

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

Current MapBuild optimization work is not parked. Its active state lives in
`docs/status/active/map-build-quality-eval-harness.md`.

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
