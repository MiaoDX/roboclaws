# Project Status

Last updated: 2026-07-30

This is the human-facing dashboard for current repo state. Keep it short,
latest-first, and pointer-based. Do not use this file as a changelog or
execution ledger. When older shipped detail is no longer needed for today's
orientation, move it to plans, ADRs, retrospectives, or `docs/human/**` and
leave a link.

## Current Focus

The aggressive architecture migration is active under
`docs/plans/2026-07-30-aggressive-architecture-migration.md`. Waves 0-2 are
complete: exact baselines and field-level parity are proven, all six module
cycles and five bidirectional package pairs are removed, and the Wave 1-2
reverse/inversion guards are locked green. Wave 3 is retiring unconditional
investigation and rehearsal stacks leaf-to-root.
The migration preserves public launch, artifact, privacy, provider, simulator,
and operator behavior while removing dependency cycles, retiring completed
investigation surfaces, moving product subsystems out of scripts, and splitting
retained oversized owners by behavior.

OpenClaw and repo-owned workstation-local Docker runtime surfaces are retired
under `docs/plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md` and
ADR-0148. The maintained product has exactly two agent engines,
`direct-runner` and `openai-agents-sdk`; CloudML image contracts and historical
evidence remain intact. Deterministic gates, the standalone full suite,
operator-console host-runtime smoke, and canonical direct-runner map-build and
cleanup product proofs pass.

The follow-up architecture simplification pass is complete. Five approved cuts
removed the obsolete Agibot/MolmoSpaces simulation rehearsal, the retired
Codex-only comparison summary, an isolated cleanup policy, unused direct
Jinja2/tyro declarations, and the legacy showcase task identity. Final review
also removed two rehearsal-only launch overrides that had become silent no-ops.
The cumulative change removes more than 5,800 lines while preserving current
`household-world`, `planner-proof`, eval, operator-console, and `agibot-gdk`
behavior. The standalone full suite and direct-runner map-build/cleanup product
proofs pass.

The post-cleanup saturation refactors are complete under
`docs/plans/2026-07-30-post-cleanup-saturation-refactors.md`. The five-slice
queue deleted two stale runtime surfaces, removed the maintainer
command-dispatch loop, canonicalized operator-console phase state, and finished
the typed launch boundary. Public run and maintainer command grammar remain
unchanged; focused gates, direct-runner product proofs, and the standalone full
suite pass.

The post-review forward-only architecture cleanup is implemented and verified
under `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`. Current
callers now use one source-aware world-ID contract, one typed launch executor,
package-owned live household runtime, one household Skill strategy owner, and
direct projection owners. Retired direct-provider code, compatibility aliases,
positional launch lowering, product-to-eval imports, and installable eval CLI
aliases are gone.

The public runtime has exactly four explicit OpenAI Agents SDK provider
profiles: `codex-responses`, `mimo-responses`, `minimax-responses`, and
`kimi-openai-chat`. All four provider health probes and fixed-prior consumer
rows pass. The Kimi open-task and cleanup smoke rows also pass. The accepted
six-row live matrix recorded zero provider failures, privacy leaks, and
trajectory violations; Kimi's two repaired rows stayed within the approved
single-rerun envelope.

The previous sanitized candidate is superseded for publication. The refreshed
candidate built from the final cleanup source is the current publication-review
artifact; publication remains a separate human decision.

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

Complete the Wave 3 unconditional deletion ledger by extracting the grasp-pose
cache's probe runtime dependency, then retiring standalone grasp diagnostics
and their report/test leaves. Cache generation, planner feasibility, and
current cleanup reports remain preservation gates. The refreshed immutable
candidate remains unmodified; publication remains unauthorized and separate
from this campaign.

## Current Blockers

- Agibot and B1 injected dependency readiness passes with the existing local SDK, Map 12 bundle,
  B1 scene, and alignment/navigation proofs. Real-robot movement remains unauthorized and requires
  a present operator plus the existing localization, run-enablement, and E-stop gates.
- Isaac strict preflight now passes disk, GPU, Torch, Isaac Lab, and runtime checks with 602.55 GiB
  free. Importing Isaac Sim remains blocked on explicit Omniverse EULA acceptance; the refactor did
  not accept it on the operator's behalf.

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
