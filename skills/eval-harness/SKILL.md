---
name: eval-harness
description: Select and run Roboclaws validation, product, eval-suite, and live-agent eval rows from a plan, diff, or explicit capability request.
---

# Eval Harness

Use this skill when a Roboclaws plan, diff, PR, or agent-facing change needs
one maintainer proof surface. The skill answers:

1. which deterministic gates, product runs, eval suites, and live-agent evals
   are relevant;
2. why each row was selected, skipped, run, failed, or blocked;
3. where the resulting reports and regression-promotion evidence live.

It is an orchestration skill, not a robot behavior skill. Keep household-world
task strategy in `household-world`; keep reusable robot capability semantics
in MCP tools and capability profiles.

## Commands

Recommend rows without running them:

```bash
just agent::eval recommend plan=docs/plans/example.md budget=focused
```

Execute relevant rows for a plan or diff:

```bash
just agent::eval execute plan=docs/plans/example.md budget=focused
just agent::eval execute since=origin/main budget=focused
```

Refresh the current baseline at the appropriate cost tier:

```bash
just agent::eval execute profile=baseline-core budget=focused
just agent::eval execute profile=baseline-live-default budget=focused
just agent::eval execute profile=baseline-refresh budget=focused
```

Run one versioned suite directly as a lower-level row/debugging path:

```bash
just agent::eval suite=cleanup_capability budget=smoke
```

Promote failed, blocked, or inconclusive eval evidence:

```bash
just agent::eval promote-regression \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json \
  source_sample_id=<sample-id> \
  regression_sample_id=regression.<name>
```

## Profiles And Budgets

- `recommend`: never executes rows; it lists commands and preflight needs.
- `profile=adaptive`: default mode; select rows from plan text, diff paths, and
  explicit axes.
- `profile=baseline-core`: select deterministic gates, current eval suites,
  direct local-simulator product rows, and DINO product rows. It excludes all
  live-provider rows and is the normal broad local refresh.
- `profile=baseline-live-default`: select `baseline-core` plus the current
  default GPT Router live-agent capability rows. It excludes the MiMo, Kimi,
  and MiniMax map-build provider sweep.
- `profile=baseline-refresh`: select the catalog baseline set directly:
  deterministic gates, all current eval suites including long-horizon tasks,
  direct product rows, DINO rows, all default live rows, and the explicit
  alternate-provider matrix. This is the release/nightly full refresh.
- All named baseline profiles run selected rows or record explicit blocked
  evidence; their rows are not converted to `skipped_by_budget`.
- `execute budget=smoke`: deterministic confidence only; selected expensive or
  live rows are recorded as skipped by user budget in `profile=adaptive`.
- `execute budget=focused`: default maintainer mode; selected required live
  rows must run or record explicit blocked evidence.
- `execute budget=full`: run required and recommended selected rows unless
  environment, network, provider, hardware, or guard preflight blocks them.

Never downgrade a selected live-agent eval into deterministic-only success.
Missing provider keys, provider 5xx/429, and model-service failures are
`model_or_provider_unavailable`. Missing Docker, simulator/runtime, DINO
sidecar, Python env, or live-session capacity is `environment_blocked`.

## Outputs

Each run writes:

```text
output/eval-harness/<stamp>/
  eval_harness.json
  eval_harness.md
  eval_harness.html
  rows/<row-id>/
  evals/<suite-id>/<stamp>/
```

The manifest schema is `roboclaws_eval_harness_manifest_v1`. Rows use
`roboclaws_eval_harness_row_v1` and may be `deterministic_gate`,
`product_run`, `eval_suite`, `live_agent_eval`, `regression_promotion`, or
`manual_review`.

## Selection Rules

The selector is deterministic and rule-table based over the row catalog, plan
text, git diff paths, and explicit overrides. It does not use an LLM
classifier. Row policy lives in this skill and `catalog/rows.json`; Python
scripts only load rows, expand paths/profiles, select, execute, and write
manifests/reports.

Important signals:

- Eval harness, eval CLI, eval reports, or regression promotion select eval
  unit tests and `smoke_regression`.
- Runtime Metric Map, map-build, actionability, or waypoint files select
  `map_build_consumer`.
- Cleanup skill, prompt, MCP policy, checker, or done-readiness files select
  cleanup contract gates, `cleanup_capability`, and focused/full live eval rows.
- Agent SDK, provider profile, or live-runtime files select route/preflight
  checks and affected live-agent eval rows.
- Visual grounding, DINO, camera labeler, or RAW-FPV files select perception or
  camera product rows.
- Docs-only command taxonomy or skill guidance changes should select docs and
  route checks, with eval rows only when the docs claim behavior changed.

Do not use or recreate a user-facing `agent-validation-matrix` route. Historical
plans may mention it, but maintained guidance should point at `@eval-harness`
and `just agent::eval recommend|execute|suite|promote-regression`.
