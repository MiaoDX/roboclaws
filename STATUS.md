# Project Status

Last updated: 2026-07-25

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

Public-core minimization is the current repository focus. The active capsule is
`docs/status/active/public-core-internal-integration-minimization.md`.

The public runtime now has exactly three explicit OpenAI Agents SDK provider profiles:
`custom-responses`, `minimax-responses`, and `kimi-openai-chat`. Private remote-operation ownership,
retired provider routes, bare coding-agent helpers, and unsupported RAW-FPV live transport have
been removed from the public core. Agibot and B1 remain validation-only worlds with injected
dependencies and are omitted from default discovery.

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

Review the sanitized one-commit candidate and its remaining live blockers before authorizing any
publication. Rerun provider and optional-world live gates after network, credentials, disk/EULA,
and the Agibot operator hold are resolved.

## Current Blockers

- Deterministic public-root, runtime, package, and fresh-install verification is complete.
- Kimi and MiniMax configuration is present, but their live proofs are blocked by
  `network: unknown`; the network probe URL is not configured. Custom Responses also lacks its
  required URL, key, and model configuration.
- Agibot validation lacks its injected runner/map paths and remains on operator hold. No real-robot
  movement is authorized.
- B1 validation lacks its injected map/scene paths. Isaac strict preflight is additionally blocked
  by 17.0 GiB free versus 80 GiB required and explicit Omniverse EULA acceptance.
- Publication remains unauthorized until the reviewed candidate evidence is presented for human
  approval.

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
