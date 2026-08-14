# Evaluation Harness And Suites

Roboclaws keeps four proof layers separate:

| Layer | Command shape | Owns |
| --- | --- | --- |
| Product run | `just run::surface ...` | One operator-facing run and its artifacts. |
| Eval harness | `just agent::eval recommend\|execute ...` | Plan- or diff-aware selection of deterministic gates, product rows, suites, and opt-in live rows. |
| Eval suite | `just agent::eval suite=<suite> ...` | Versioned samples, trials, graders, aggregate metrics, and replay. |
| Harness recipe | `harness::*` | Lower-level mechanics used by product and eval flows. |

The maintained user-facing skill is `@eval-harness`. Current row, engine,
provider, intent, and evidence-lane dimensions are summarized in
[Eval harness dimensions](eval-harness-dimensions.md).

An eval suite answers whether a capability is improving over time, not whether
one demo happened to complete:

```text
eval suite
  -> sample
  -> environment reset
  -> agent trial
  -> trace and artifacts
  -> deterministic and optional advisory graders
  -> aggregate metrics
  -> failure replay or regression sample
```

Deterministic privacy and safety failures are authoritative. Model or human
rubric graders remain advisory until calibrated. Results record the relevant
surface, intent, preset, world, backend, evidence lane, scenario, prompt hash,
agent engine, provider/model, skill, MCP profile, limits, budgets, and artifact
schema versions. Missing identity is explicit `unavailable` or
`not_applicable`.

Versioned definitions live under `evals/<capability>/`; the first package is
`evals/household_world/`. The Python schema and runner code lives under
`roboclaws.evals`.

Evaluation is a Git-checkout-owned maintainer layer. The sdist and wheel omit
`roboclaws.evals`, `evals/**`, and the eval-harness skill; installed product
runtimes therefore do not expose `roboclaws eval`, top-level `eval`, or
`roboclaws agent eval`. Run evals from a repository checkout through
`just agent::eval`, which invokes the repo eval CLI directly.

## Running Evals

Common commands:

```bash
just agent::eval recommend plan=docs/plans/example.md budget=focused
just agent::eval execute since=origin/main budget=focused
just agent::eval execute profile=baseline-core budget=focused
just agent::eval execute profile=baseline-live-default budget=focused
just agent::eval execute profile=baseline-refresh budget=focused
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=map_build_quality budget=smoke
just agent::eval suite=map_consumer_no_prior budget=smoke
just agent::eval suite=cleanup_capability budget=smoke
just agent::eval suite=scene_sampler_stress budget=smoke
just agent::eval suite=long_horizon_tasks budget=smoke
```

`baseline-core` is the normal broad local refresh without live providers.
`baseline-live-default` adds the normal Kimi live rows. `baseline-refresh` adds
the explicit four-profile comparison. Rows whose live preflight is not ready
record blocked evidence instead of being silently skipped.

The built-in `just agent::eval execute` worker runs locally. The harness itself
is execution-neutral: maintainers can freeze selected rows and dispatch them to
CloudML with the repo-owned
[`cloudml-eval-ops`](../../skills/cloudml-eval-ops/SKILL.md) skill. That skill
uses the official `cml` lifecycle commands and executor-backed JuiceFS transfer,
then returns verified row results to the normal harness report. CloudML remains
an eval execution environment, not a product `backend`.

This is intentionally a Markdown operations layer rather than a second Python
control plane or a private companion repository. A request to run or refresh a
repo-scoped CloudML eval authorizes the bounded preflight, staging, submission,
monitoring, collection, and repair/retry work described by the skill and
`AGENTS.md`; material workspace, resource, concurrency, credential, or cost
expansion still requires confirmation. Durable baseline or catalog publication
also remains a separate human decision.

For local execution, `max_parallel=1` preserves serial behavior; raising it
runs independent rows concurrently while dependency chains and shared
visual-backend groups remain ordered. For CloudML, parallel proof requires
independent task row intervals that actually overlap, not merely multiple
successful submissions. Each run retains `plan.json`, append-only task
receipts, terminal markers, collection verification, and the normal JSON,
Markdown, and HTML reports under `output/eval-harness/<run-id>/cloudml-ops/`.

The full `baseline-refresh` placement policy uses one selected CloudML row per
CloudML task, one worker Pod per task, and `max_parallel=1` inside every worker,
including deterministic CPU rows. Task count is derived from the frozen
manifest rather than a fixed historical shard count or observed concurrency
peak. Physical-host isolation is not required. A producer/consumer dependency
chain runs in two stages: the producer task must durably commit and verify its
artifact before the consumer task is submitted in a separate Pod.

The default result/capability refresh allows at most two active rows per
provider. It records provider throttling and does not treat concurrent-run
latency as comparable performance evidence. A latency or cost baseline instead
uses at most one active row per provider. Kimi and MiniMax are external-provider
rows and always run locally with `max_parallel=1`; a successful ad hoc CloudML
probe cannot override that placement. Codex and MiMo are internal-provider rows
eligible for local or CloudML execution after route readiness passes. Local
provider rows may overlap the CloudML wave and merge into the same hybrid
report. A terminal report may preserve explicitly blocked external rows, but it
is not an accepted complete baseline and must not be published as one.

Grounding DINO remains colocated with its corresponding MuJoCo row: the worker
Pod runs the simulator/runtime and its local HTTP visual-grounding sidecar. The
baseline does not use a shared cross-Pod DINO service. r49 tasks use
`GUARANTEED` resources with `preemptible=true`; CPU tasks remain
non-preemptible. Scheduler retries stay disabled, and only a classified
preemption or infrastructure failure may create one additional attempt.

Scene expansion resolves an execution-neutral case from the catalog row,
suite, provider profile, seed, and optional `(scene_source, scene_index)`
identity. Only rows declared scene-portable may be expanded with
`scene=<source>/<index>,...`.

## Provider Evals

OpenAI Agents SDK runs always select one profile explicitly:

| Profile | Wire API | Required configuration |
| --- | --- | --- |
| `kimi-openai-chat` | Chat Completions | `KIMI_OPENAI_BASE_URL`, `KIMI_API_KEY` |
| `codex-responses` | Responses | `CODEX_RESPONSES_BASE_URL`, `CODEX_RESPONSES_API_KEY`, `CODEX_RESPONSES_MODEL` |
| `mimo-responses` | Responses | `MIMO_RESPONSES_BASE_URL`, `MIMO_RESPONSES_API_KEY`, `MIMO_RESPONSES_MODEL` |
| `minimax-responses` | Responses | `MM_BASE_URL`, `MM_API_KEY` |

Non-direct suite selections preserve live-agent identity and produce blocked
provider/runtime evidence unless `live_execution=run` is explicit:

```bash
just agent::eval suite=cleanup_capability budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat

just agent::eval suite=open_ended_goals budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat \
  live_execution=run
```

Live evals use a 1200-second wall-clock budget and a 120-second no-progress
timeout unless the catalog row owns a larger contract. Provider availability,
missing credentials, port conflicts, and runtime readiness are classified
separately from agent behavior.

The `session-live` route verifies an Operator Session parent run, active-run
steering, terminal artifacts, and a linked child goal. It is also opt-in:

```bash
just agent::eval session-live budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat \
  live_execution=run
```

## Map Evaluation

`map_build_quality` compares builders and produces candidate artifacts.
`map_consumer_no_prior` runs controls from the Base Metric Map.
`map_consumer_fixed_prior` consumes one explicit read-only canonical prior.
The legacy `map_build_consumer` suite is an explicit same-provider end-to-end
research profile, not the normal comparison baseline.

After maintainer approval, promote an accepted selector report to the
content-addressed catalog:

```bash
just agent::eval runtime-prior-promote report=<selection-report.json> \
  manifest=<promotion-manifest.json> \
  output_dir=output/evals/canonical-runtime-map-priors
```

The promotion manifest records approval, scene/source-map, backend, builder
provider/model, prompt or skill version, evidence lane, camera labeler, seed,
and map schema identity. Any identity change produces a different digest.

Completed provider artifacts can be regraded without another live call:

```bash
just agent::eval suite=map_build_consumer budget=focused \
  agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat \
  regrade_source=output/evals/<suite>/<stamp>
```

Cross-run MapBuild reports are artifact-only:

```bash
just agent::eval map-build-report \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json,output/evals/<suite>/<other-stamp>/eval_results.json \
  output_dir=output/evals/map-build-matrix-review
```

## Regression Promotion

Failed, blocked, or inconclusive results can become durable regression
samples:

```bash
just agent::eval promote-regression \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json \
  source_sample_id=<sample-id> \
  regression_sample_id=regression.<name>
```

Human labels are `eval-regression:accepted`,
`eval-regression:needs-human-review`, and
`eval-regression:do-not-promote`. The final label is a stop signal and writes
nothing.

Keep grader truth private. Generated mess sets, acceptable destinations,
hidden targets, and private manifests may feed graders and maintainer reports,
but they must not appear in agent-facing MCP inputs, capability metadata, or
public map artifacts.
