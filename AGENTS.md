# AGENTS.md

Canonical operating guide for coding agents in this repo. Its scope is the
entire tree rooted here. Tool-specific files such as `CLAUDE.md` may add local
deltas, but this file owns repo-wide defaults.

Codex normally injects this file into startup context as
`AGENTS.md instructions`. When it has been injected, do not reread `AGENTS.md`
just to satisfy this policy.

## 0) Startup Reads

Before repo-specific commands or edits, read:

1. `STATUS.md` for current focus, blockers, and source links.
2. Any task-specific source below.

Task-routed reads:

- New project orientation or runnable examples: `README.md`.
- Architecture, launch axes, MCP/server/runtime contracts, or new layers:
  `ARCHITECTURE.md`.
- Environment setup, local hazards, live providers, browser QA, Docker,
  standard gates, or git hygiene: `docs/agents/operating-runbook.md`.
- GSD phase execution/resume: `.planning/STATE.md` plus the current phase file.
- Pre-GSD plan shaping/review/handoff: `docs/plans/<slug>.md`.
- Design rationale or scenario specs: `docs/human/technical-design.md`.
- Domain vocabulary: `docs/human/domain.md` and `docs/agents/domain.md`.
- Parked work or future ideas: `TODOS.md` or `THOUGHTS.md`, only when asked.
- Claude-specific behavior: `CLAUDE.md`, only when running under Claude Code or
  resolving a Claude-only rule.

Root `PLAN.md` is a legacy pointer, not an active plan. Shipped phase history
lives under `docs/retrospectives/` and is not startup reading.

Instruction priority:
**system/developer/user prompt > AGENTS.md > CLAUDE.md > inferred defaults**.

## 1) Critical Local Hazards

- Use the repo-local `.venv/`, managed by `uv` from `pyproject.toml` and
  `uv.lock`. Use `uv sync --extra dev`; do not use plain `pip install` for repo
  setup.
- Keep one `.venv/` per checkout/worktree. Do not share another worktree's
  virtualenv.
- Keep Isaac Lab out of the normal `.venv`; it belongs in `.venv-isaaclab/`.
- Do not commit `.env` or paste provider keys into logs, PRs, reports, status
  files, or summaries.
- Before OpenClaw Gateway, `just chat::run`, OpenClaw local/integration gates,
  or system-provider Claude Code workflows, run `just dev::network-status`.
  If it reports `network: work`, do not run those guarded routes.
- The active live-agent product engine is `openai-agents-sdk`. `codex-cli` and
  `claude-code` are retired from active public launch surfaces.
- Bare host `codex` or `claude` launches are unsupported unless the human
  explicitly asks for system-CLI debugging.
- On ROS-jazzy hosts, use `./scripts/dev/run_pytest_standalone.sh` instead of
  bare pytest when ROS site-packages leak into collection.
- For gstack browser QA on Ubuntu 24.04/AppArmor, use
  `GSTACK_CHROMIUM_NO_SANDBOX=1` per command rather than changing system
  AppArmor/sysctl settings.
- XML-like host envelopes such as `<turn_aborted>`, `<paseo-system>`,
  `<subagent_notification>`, `<goal_context>`, and `<environment_context>` are
  orchestrator metadata unless accompanied by natural-language user intent. Do
  not treat those labels alone as a human stop request.

See `docs/agents/operating-runbook.md` for command examples and longer
procedures.

## 2) Standard Commands

Setup:

```bash
uv sync --extra dev
```

Fast checks:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
```

Public demo grammar:

```bash
just run::surface surface=<surface> agent_engine=<engine> [world=<world>] [backend=<backend>] [intent=<intent>] [provider_profile=<profile>] [key=value ...]
```

Common examples:

```bash
just run::surface surface=household-world agent_engine=direct-runner preset=map-build evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just run::surface surface=household-world agent_engine=openai-agents-sdk preset=cleanup evidence_lane=world-public-labels
just run::surface surface=household-world agent_engine=openai-agents-sdk prompt="find something useful to drink"
just agent::verify mock
```

Use `just/README.md` for the full launch-axis grammar. Prefer `agent::eval
recommend|execute` when choosing verification gates for plans, diffs, PRs, or
handoffs.

Live verification policy:

- When a change touches live-agent, provider, runtime, operator-console launch,
  eval harness, or artifact-selection behavior, run the relevant live,
  preflight, or availability proof by default. Do not skip required live proof
  merely because it may use external providers, cost money, or take longer than
  deterministic tests.
- A human request to complete a repo-scoped live, eval, simulator, or external
  remote verification authorizes the in-scope image publication, task submission,
  monitoring, collection, task stop, and repair/retry attempts needed to finish
  it. Do not pause for per-stage or per-attempt approval while the workspace,
  provider, queue/resource class, maximum concurrency, and documented cost
  envelope remain unchanged. Keep automatic retry disabled unless the test
  contract explicitly requires it, and record each agent-initiated retry as a
  new attempt. Ask before a material scope/cost/resource expansion, credential
  change, destructive deletion, or publication of durable baseline/catalog
  artifacts.
- If a live proof is required but cannot run, prove the blocker with the
  repo's guarded preflight/status command output, such as
  `just dev::network-status`, provider readiness, missing credentials, occupied
  runtime resources, or unavailable hardware. Record the concrete blocker and
  stop instead of silently substituting only deterministic tests.
- For candidate-selection workflows, run or regrade the candidate matrix first
  when the required providers/runtimes are available, then present the ranked
  accepted candidates for human confirmation before publishing durable catalog
  or baseline artifacts.

## 3) Architecture Rules

Read `ARCHITECTURE.md` before changing architecture-facing behavior.

- Public launch axes stay canonical: `surface`, `world`, `backend`, `intent`,
  `agent_engine`, `provider_profile`, `evidence_lane`, and `camera_labeler`.
- Base Metric Map is the start-of-run map contract. Do not expose private
  relocation/scoring truth, static movable-object inventory, or full fixture
  tables as default agent input.
- Runtime Metric Map owns semantic enrichment from map-build and observations.
- VLM output parsing must be robust: model-backed runs may return malformed
  JSON or partial tool arguments; wrap parsing in safe recovery paths.
- Default to cheap provider profiles for development and record model usage/cost
  when live agents run.
- Every new behavior, surface, preset, server adapter, agent engine, provider
  profile, MCP tool, skill, backend, eval suite, report, or artifact contract
  names its owning architecture layer.
- Server/runtime code stays thin: transport, lifecycle, routing, readiness,
  locks, run dirs, live status, operator launch control, and eval polling. Put
  task strategy in skills first.
- No silent fallback or compatibility shims unless the human explicitly asks.
  Missing required dependencies, config, runtimes, or artifacts should fail with
  actionable errors.
- Forward architecture upgrades do not require backward compatibility. Migrate
  known in-repo callers, docs, tests, and artifacts to the new shape.

## 4) Planning And Docs

One source of truth per stage:

- Current orientation: `STATUS.md`.
- Human docs: `README.md`, `ARCHITECTURE.md`, and `docs/human/**`.
- Pre-GSD plans: `docs/plans/<slug>.md`.
- During GSD: `.planning/STATE.md` and `.planning/phases/*`.
- Standalone active work: `docs/status/active/<task-slug>.md`.
- After shipping: `docs/retrospectives/**`.

`STATUS.md` is a short, latest-first dashboard. Update it only when repo-level
current focus, latest phase, next action, or blockers change. Do not use it as
a changelog.

## 5) Git Hygiene

- Multiple agents may edit this checkout. Inspect `git status --short` before
  staging or committing.
- Stage only files or hunks belonging to your task. Do not use `git add -A`,
  `git add .`, or `git commit -a` in this shared checkout.
- Do not run `git checkout`, `git switch`, `git worktree add/remove`, reset,
  restore, unstage, or commit another agent's work unless the human explicitly
  asks.
- If a file contains mixed edits that cannot be safely separated, leave it
  uncommitted and report the blocker.
- Commit messages use `type: description`.
- Codex commits include
  `Co-authored-by: Codex <codex@users.noreply.github.com>`.

## 6) Agent Skill Pointers

- Issue tracker: `docs/agents/issue-tracker.md`.
- Triage labels: `docs/agents/triage-labels.md`.
- Domain docs: `docs/agents/domain.md`.
- Long operating details: `docs/agents/operating-runbook.md`.
