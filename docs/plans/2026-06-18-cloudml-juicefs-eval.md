---
plan_scope: cloudml-juicefs-eval
status: active
implementation_allowed: true
created: 2026-06-18
last_reviewed: 2026-07-21
source:
  - user request to make CloudML a standard eval execution target
  - user approval of the hybrid local and CloudML design on 2026-07-21
related_context:
  - ARCHITECTURE.md
  - STATUS.md
  - docs/human/evaluation.md
  - docs/human/cloudml-experiment-flow.md
  - docs/adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md
---

# CloudML Eval Execution

## Plan Ledger

- Plan status: ACTIVE
- Session scope: cloudml-eval-execution
- Parent plan: none
- Child plans: none
- Last updated: 2026-07-21
- Current slice: CPU and RTX 4090 CloudML smokes are proven; reconcile the
  secure provider-injection boundary before live Router rows.
- Next action: add or select a reviewed CloudML native secret reference or
  workload identity contract, then run bounded API Router and MiMo rows.
- Blocked on: executor `custom_train submit` currently exposes no native secret
  reference, environment-secret reference, or workload identity input. The
  accepted security gate forbids plaintext provider credentials in argv, YAML,
  image commands, or JuiceFS.
- Do not touch from this session: product task strategy, MCP semantics, eval
  grader policy, unrelated provider routes, or physical-robot backends.

## Approved Preflight Contract

Preflight status: approved by the user's 2026-07-21 `LGTM, do these via
intuitive flow` instruction.

Task source: user discussion plus this reconciled plan.

Canonical source: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`.

Route: durable `$intuitive-flow`; the main session owns integration and final
verification, with bounded worker phases when they preserve control-plane
context.

Goal: make local and CloudML execution interchangeable, reproducible targets
of the same Eval Harness so normal development checks and full baseline
refreshes can use bounded parallelism without changing eval meaning.

Scope:

- Record row timing, execution capabilities, dependencies, attempts, and
  remote provenance in the harness artifact contract.
- Execute an exact selected row or dependency-safe shard without rerunning
  selection policy inside a worker.
- Add bounded local parallel execution and deterministic artifact aggregation.
- Add `local`, `cloudml`, and capability-matched `auto` execution targets.
- Route deterministic work to CPU-capable pools and MuJoCo, DINO, and live
  simulation work to RTX 4090-class CloudML pools when available.
- Treat provider reachability as a worker-pool capability. CloudML may use the
  internal API Router and MiMo Router; direct Kimi and MiniMax rows stay on an
  external-network pool unless an explicit internal provider profile is added.
- Pin code commit, image digest, asset manifest digest, row command, and output
  root for formal evidence.
- Stage inputs and collect run-owned outputs through JuiceFS, then render the
  normal `eval_harness.json`, Markdown, and HTML reports.
- Support submit, poll, collect, retry/resume, and detached status workflows.
- Keep provider credentials out of commands, YAML, manifests, logs, and normal
  JuiceFS artifacts. Only a native CloudML secret reference or equivalent
  workload identity is acceptable for formal live rows.
- Update the current CloudML runbook and retire the stale single-suite command
  path once the replacement is proven.

Non-goals:

- No new robot product surface, public product backend, task intent, MCP tool,
  eval grader policy, or provider identity alias.
- No silent fallback from direct Kimi/MiniMax profiles to internal Router
  models. A different route is a different explicit provider profile.
- No full Cartesian product of providers, tasks, evidence lanes, and worlds.
- No plaintext secret bundle in source control, task YAML, shell arguments,
  report artifacts, or shared storage.
- No preemptible CloudML evidence jobs until application-level resume is
  independently proven.
- No FDS publication by default; publication remains an explicit sharing step.

Entity budget:

- reuse: the row catalog, selector, harness manifest/report, existing
  `Dockerfile.eval`, CloudML/JuiceFS scripts, provider registry, and executor
  `compute cloudml` targets.
- remove/merge: replace the serial-only run loop with one execution interface;
  merge the single-suite CloudML prototype into the harness adapter; remove
  stale `nvs ... cloudml` command references.
- new: one execution-plan/shard schema and one CloudML adapter boundary are
  necessary because current rows have no placement or remote lifecycle model.
- expansion triggers: a new public command family, executor-repo API change,
  provider alias, plaintext secret fallback, more than three delivery phases,
  or a new durable storage/service dependency requires review before expansion.

Context:

- must-read: this plan, `ARCHITECTURE.md`, `docs/human/evaluation.md`,
  `skills/eval-harness/SKILL.md`, `skills/eval-harness/catalog/rows.json`,
  selector/runner code, and `docs/agents/operating-runbook.md`.
- useful: the latest complete baseline manifest and
  `docs/human/cloudml-experiment-flow.md`.
- avoid-unless-needed: historical CloudML transcripts, retired engine plans,
  broad `.planning/` history, and unrelated provider incidents.

## Acceptance

SUCCESS requires all of the following:

1. `execution_target=local` preserves current row selection, outcome
   classification, artifact paths, and exit semantics.
2. Every executed row records start, finish, duration, attempt, execution
   target, resolved command, and worker provenance.
3. Dependency-safe local parallel execution shortens a representative
   multi-row run and never runs a consumer before its producer artifact exists.
4. A worker can execute an exact row/shard from a frozen manifest without
   reselecting or mutating unrelated rows.
5. CloudML dry-run output uses the current `compute cloudml custom_train`
   target, pinned code/image/input identities, read-only input and run-owned
   output mounts, and contains no provider secret values.
6. A real deterministic CloudML smoke writes valid row and harness artifacts
   to JuiceFS and the local collector reproduces the normal aggregate report.
7. A real RTX 4090-class MuJoCo/DINO smoke proves the GPU image, EGL/rendering,
   detector assets, sidecar readiness, and output collection.
8. Internal API Router and MiMo Router live rows pass from CloudML using secure
   secret injection; direct Kimi/MiniMax rows are placed on an eligible pool or
   explicitly blocked with network capability evidence.
9. `execution_target=auto` completes a hybrid representative baseline with
   stable row identity and a single aggregate report.
10. Documentation gives one standard workflow for development, formal
    baseline refresh, detached monitoring, collection, and failure replay.

BLOCKED_NEEDS_DECISION:

- A real CloudML submission is a cost-bearing external state change and needs
  confirmation immediately before the first submit. The user supplied that
  confirmation for the current CPU/GPU smoke sequence on 2026-07-21.
- If CloudML exposes no native secret reference or workload identity, stop for
  a security decision; do not invent a plaintext fallback.
- If an internal Router model is proposed as a replacement for an existing
  direct provider row, require an explicit provider-profile decision.

BLOCKED_NEEDS_LOCAL_VALIDATION:

- CloudML credentials, queue access, internal registry, JuiceFS mounts, GPU
  capacity, or internal provider reachability are required for final success.
  Missing evidence leaves the plan ACTIVE rather than partially complete.

INTERMEDIATE_ONLY: deterministic implementation, unit/contract proof, and
CloudML dry-run are useful committed checkpoints but do not complete this plan.

No regressions:

- Existing `just agent::eval recommend|execute|suite|promote-regression`
  behavior remains supported.
- Private scorer truth stays grader-only.
- Provider outages remain separate from agent behavior failures.
- A selected required row cannot silently disappear because no pool matches.

## Verification

Deterministic:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/evals/test_eval_harness_baseline_profiles.py \
  tests/unit/evals/test_eval_harness_selector.py \
  tests/unit/evals/test_eval_runner.py \
  tests/contract/dev_tools/test_eval_just_recipe.py
```

Integration:

- Generate local, CloudML, and auto execution plans for `baseline-core`,
  `baseline-live-default`, and `baseline-refresh`.
- Run a dependency pair and a parallel independent-row group locally.
- Generate and inspect CloudML dry-run YAML with redaction assertions.
- Collect synthetic remote row results and prove idempotent aggregation.
- Run the repo's scene-catalog sync guard when staged scene inputs change.

Product and local/live:

- Offline Docker eval smoke with `--network none`.
- Real CloudML deterministic smoke on a pinned image and commit.
- Real CloudML RTX 4090 MuJoCo/DINO product row.
- Real CloudML internal API Router live row.
- Real CloudML MiMo Router live row.
- Hybrid `execution_target=auto` representative baseline and final
  `baseline-refresh` once the earlier gates pass.

Optional:

- Publish a completed report to FDS for team review.
- Compare observed wall time against the 2026-07-21 serial baseline of roughly
  2 hours 42 minutes.

## Implementation Evidence

As of 2026-07-21:

- Focused Eval Harness regression passes 82 tests; Ruff, formatting checks,
  and CloudML shell syntax checks pass.
- Separate local CPU and CUDA images pass offline eval smokes. The CPU image is
  1.88 GB and the CUDA image is 10.84 GB.
- The CUDA image loads the pinned Grounding DINO snapshot offline as
  `GroundingDinoForObjectDetection` from
  `/opt/roboclaws/models/grounding-dino-base`.
- Local image IDs remain build evidence only; formal shard YAML uses the two
  separately verified registry `@sha256:` identities recorded below.
- A cold common dependency build took about 23 minutes and a cold CUDA wheel
  build about 22 minutes. Cached CPU rebuilds take seconds; normal baseline
  refreshes reuse published digests and do not rebuild either image.
- The CUDA build consumes a pinned local Hugging Face cache through a BuildKit
  named context, so image construction does not depend on public Hub access.
- A `baseline-core/focused` CloudML dry-run selected 18 rows
  with zero blocked rows and generated eight shards: one CPU shard containing
  ten rows and seven RTX 4090 shards containing eight rows. The generated YAML
  selected the pool-specific image identity. Grounding DINO now uses
  `cuda`/`auto`: Transformers 4.57.6 generates internal float32 text position
  embeddings and fails when the whole model is converted to float16.
- The CPU and CUDA images were rebuilt from commit `865658f2`, passed offline
  smoke again, and were published and remotely resolved as OCI digests
  `sha256:e715abbd...faa7` and `sha256:d1d4c398...69a4`.
- CPU task `t-20260721202435-8sghy` completed and collected the
  `route-trace-contract-tests` row in 12.969 seconds with zero failed or missing
  results.
- RTX 4090 task `t-20260721211104-0e8nh` completed and collected the
  `direct-camera-grounded-grounding-dino` product row in 238.08 seconds. DINO
  readiness returned five candidates and the full offline MolmoSpaces cleanup
  row passed.
- The staged MolmoSpaces archive includes the versioned scene and
  `droid_objaverse` cache metadata required by the resource manager. Staging
  now calls executor through its supported `exe` entrypoint and inherits the
  executor project's active config unless an explicit override is supplied.
- The current executor `custom_train submit` CLI and implementation expose no
  native secret reference or workload identity field. API Router and MiMo live
  rows therefore remain blocked by the approved no-plaintext-secret gate.

## Architecture Contract

```text
selector
  -> frozen eval harness manifest and dependency DAG
  -> capability scheduler
       -> local worker pool
       -> CloudML CPU worker pool
       -> CloudML RTX 4090 worker pool
  -> row attempt artifacts on local disk or JuiceFS
  -> collector verifies identities and terminal markers
  -> one normal eval_harness.json / .md / .html report
```

CloudML is an Eval Harness execution environment, not a product `backend`.
Workers execute catalog commands; they do not own selection policy or robot
strategy.

### Public Maintainer Command

The intended facade remains `agent::eval`:

```bash
just agent::eval execute profile=baseline-refresh budget=focused execution_target=auto
just agent::eval execute profile=baseline-refresh budget=focused execution_target=cloudml detach=true
just agent::eval status run=<run-id>
just agent::eval collect run=<run-id>
```

Exact spelling may follow the existing `just` parser, but no second public
CloudML-only eval command family should survive closeout.

### Execution Metadata

Row catalog metadata should state policy, not host-specific credentials:

- `execution_requirements`: CPU/GPU, simulator, DINO, provider route, network
  reachability, and writable artifact storage.
- `depends_on`: producer rows whose artifacts must exist first.
- `timeout_s`: row wall-clock bound.
- `concurrency_group`: optional shared-service/rate-limit bound.

Resolved plan/attempt metadata should add:

- `execution_target`, `worker_pool`, `shard_id`, and CloudML job/pod identity;
- `attempt`, `started_at`, `finished_at`, and `duration_s`;
- code commit, image digest, asset-manifest digest, and command digest;
- terminal marker, artifact root, result digest, and collection status.

### Capability Pools

Pool capability configuration is environment-owned and contains names or
secret references only, never secret values.

| Pool | Capabilities | Initial use |
| --- | --- | --- |
| `local` | external egress, local simulator, one visual slot | direct Kimi/MiniMax and debugging |
| `cloudml-cpu` | internal network, CPU, JuiceFS | deterministic gates and static suites |
| `cloudml-r49` | internal network, RTX 4090-class GPU, EGL, MuJoCo, DINO, JuiceFS | simulator, DINO, API Router and MiMo live rows |

Provider concurrency is bounded per route and raised only from measured
evidence. Independent CloudML jobs may reuse container ports because network
namespaces are isolated.

### Sharding Rules

- Group short deterministic rows into one CPU shard to amortize startup.
- Keep producer/consumer artifact chains in one ordered shard unless the
  artifact has been durably committed and verified before dispatch.
- Give 15-30 minute live provider rows independent shards when provider
  concurrency permits.
- Run DINO rows in a GPU shard whose image or mounted cache already contains
  detector dependencies and weights.
- A retry writes a new attempt directory and never overwrites prior evidence.
- Infrastructure retry is allowed only for classified transient failures;
  behavioral failures are not automatically retried as infrastructure.

### Security Rules

- Secret values must never enter argv, generated YAML, Git, report JSON/HTML,
  logs, task labels, FDS bundles, or ordinary JuiceFS artifacts.
- Worker manifests contain provider profile and secret reference names only.
- Logs and exception summaries retain the existing redaction boundary.
- Formal live CloudML execution requires a native secret reference or
  workload identity proven by a redaction test and a real bounded probe.

## Delivery Sequence

1. Execution-neutral harness core: timing, metadata, dependencies, exact-row
   worker, local bounded parallelism, aggregation, and tests.
2. CloudML adapter: current executor path, image/input identities, CPU/GPU
   pools, dry-run, polling, terminal markers, collection, and retry/resume.
3. Network/provider routing and live proof: secure secrets, API Router, MiMo,
   hybrid auto execution, complete baseline timing, docs, and closeout.

Each slice gets focused proof and a semantic commit before the next slice.

## Existing Foundation

The 2026-06-18 through 2026-06-20 prototype already proved:

- `Dockerfile.eval` and an offline `smoke_regression` image run;
- a pinned internal-registry image and digest;
- code and focused MolmoSpaces asset archives with sha256 manifests;
- local deterministic product/eval runs;
- CloudML dry-run generation and JuiceFS upload dry-run;
- report retrieval and optional FDS preview publication.

This implementation must reuse those assets while replacing their stale
single-suite orchestration and old executor target path.

## Stop Condition

The plan is DONE only when all ten SUCCESS items are proven. Deterministic or
dry-run-only progress remains an intermediate checkpoint. Stop immediately at
the cost, security, provider-identity, or unavailable-runtime gates above and
record the exact blocker in the active capsule.
