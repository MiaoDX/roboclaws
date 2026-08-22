---
name: cloudml-eval-ops
description: Run frozen Roboclaws Eval Harness rows on CloudML with bounded parallelism, official cml lifecycle commands, executor-backed JuiceFS transfer, durable task receipts, verified collection, and explicit retry/preemption evidence. Use when a user asks to run, refresh, resume, monitor, collect, or debug a Roboclaws baseline/eval on CloudML, especially parallel CPU, MuJoCo, Grounding DINO, provider, or hybrid local/cloud runs.
---

# CloudML Eval Ops

Run CloudML as an execution environment for an existing Roboclaws Eval Harness
manifest. Do not make CloudML a product backend and do not reimplement CloudML
or storage APIs in Roboclaws.

## Ownership

- Let Roboclaws own row selection, commands, graders, result schemas, and final
  reports. Read `../eval-harness/SKILL.md` before selecting rows.
- Use the installed `cml-shared`, `cml-resource`, and `cml-train` skills and the
  official `cml` CLI for context, resources, YAML, submit, describe, logs,
  events, stop, and task status.
- Use the installed `executor` skill only for cross-platform Repo and
  JuiceFS/FDS operations. Read its CloudML defaults before those operations.
- Keep cluster, queue, image, mount, endpoint, and credential values in existing
  environment-owned CML/executor configuration or run-local ignored files. Do
  not add them to this skill, tracked source, commands printed in reports, or
  normal eval artifacts.

## Task Authorization

Treat an explicit human request to run or refresh a repo-scoped CloudML eval as
authorization for all necessary in-scope operations: read-only preflight,
source and asset packaging, scoped upload, image publication when required by
the selected row, task submission, monitoring, logs/events, result download,
collection, stopping a failed or stalled task, and repair followed by a new
attempt. Do not pause for per-command or per-stage approval while workspace,
provider routes, queue/resource class, maximum concurrency, and documented cost
envelope remain unchanged.

Record every agent-initiated retry as a new attempt. Keep scheduler automatic
retry disabled unless the eval contract explicitly requires it. Ask before a
material workspace, provider, credential, queue/resource, concurrency, or cost
expansion; publication of durable baselines/catalog entries; physical robot
movement; or any destructive deletion. Never delete a CloudML task or remote
artifact without explicit authorization for the exact target and consequence.

## Run Contract

Create one ignored run root under `output/eval-harness/<run-id>/` and retain:

```text
eval_harness.json              frozen source manifest
cloudml-ops/plan.json          placement and immutable identities
cloudml-ops/task-receipts.jsonl
cloudml-ops/collection.json
cloudml-ops/yaml/<shard-id>.yaml
cloudml-ops/manifests/<shard-id>.json
cloudml-ops/collected/<shard-id>/
eval_harness.md
eval_harness.html
```

Use these schemas in run-local files:

- `plan.json`: `roboclaws_cloudml_eval_ops_plan_v1`.
- each receipt: `roboclaws_cloudml_eval_task_receipt_v1`.
- `collection.json`: `roboclaws_cloudml_eval_collection_v1`.

Record run ID, source-manifest SHA-256, code commit, image digest, asset digest,
canonical-prior digest when used, shard ID, exact row IDs, command digest,
attempt, task ID, context/workspace label, readable resource label, submitted,
started, and finished timestamps, terminal state, exit status, output prefix,
and collection verdict. Never record secret values or provider endpoint values.

Treat `task-receipts.jsonl` as an append-only event ledger. Write a
`submit_pending` event before submission, then a separate `submitted` event
containing the returned task ID; later state, terminal, and collection changes
are new events with the same `(shard_id, attempt)`. Never edit an earlier JSONL
line. Use JSON strings for unavailable optional digests (`""`), RFC 3339 UTC
timestamps, integer attempts starting at 1, and lowercase lifecycle values.

Canonicalize command identity as the SHA-256 of compact UTF-8 JSON for the
resolved argv array (`sort_keys=true`, separators `(',', ':')`). File digests
are SHA-256 of raw bytes. `plan.json` owns the full current state; JSONL owns the
auditable transitions.

Each worker writes
`markers/<shard-id>.json` with schema
`roboclaws_eval_harness_cloudml_terminal_v1`, shard ID, row IDs, code and asset
digests, worker pool, finished timestamp, status, and exit status. Existing
harness `row_result.json` files remain row-owned and need only row ID, shard ID,
interval, status/outcome, exit code, command, and artifacts. Manifest, image,
attempt, and command identities may come from the immutable YAML and task
receipt when the installed worker predates those marker fields. The collector
validates marker, result, YAML, and receipt as one combined evidence set; it
must never infer a missing identity from a mutable remote path.

## Workflow

### 1. Freeze benchmark identity

1. Read `STATUS.md`, `ARCHITECTURE.md`, and the operating runbook.
2. Generate the normal manifest with `just agent::eval recommend ...`; use
   `profile=baseline-refresh` for a full refresh.
3. Require manifest schema `roboclaws_eval_harness_manifest_v1`, unique selected
   row IDs, and resolved commands. Reject a dirty or moving code identity for a
   retained baseline; a bounded smoke may use a recorded source archive digest.
4. Pass an explicit immutable `runtime_map_prior` for fixed-prior rows. Never
   rebuild MapBuild separately inside provider cells.
5. Copy the manifest into the run root and record its SHA-256 before placement.

For a bounded smoke, preserve that source manifest unchanged and derive a
run-local scoped execution manifest. It may change only `output_dir`, each
selected row's `row_dir`, selection/status fields, and summary counts; row IDs,
commands, cases, dependencies, requirements, timeouts, and grader semantics
must remain byte-for-byte equivalent as structured values. Record both manifest
digests and the explicit included/excluded row IDs in `plan.json`. The identity
equation and completion rule apply to the scoped execution manifest; excluded
source rows are `out_of_scope`, not silently blocked or passed. Never use a
scoped smoke as a completed full baseline refresh.

### 2. Preflight capabilities

1. Resolve the official CLI with `command -v cml`; use the installed
   `~/.cloudml-cli/bin/cml` only when it is the configured CML installation.
2. Check the current CML context without printing credential fields. Query
   queue resources and workspace quota with machine-readable output where
   supported.
3. Before live provider rows, run `scripts/dev/network_status.sh`. Stop guarded
   provider routes when it reports `network: work`.
4. Read each provider row's `provider_network_scope` and
   `allowed_execution_targets` from the frozen manifest before probing any
   route. Kimi and MiniMax are external providers restricted to `local`; never
   probe or submit them from CloudML. Probe only CloudML-eligible internal
   provider routes from the intended worker network. Do not substitute provider
   profiles when a route is unavailable.
5. Resolve pinned image digests, read-only input mounts, one run-owned writable
   output prefix, and the maximum concurrency. Require CPU jobs to request at
   least four CPU units. Do not combine `BEST_EFFORT_PUBLIC` with the training
   `preemptible` flag.
6. Record whether the run is a result/capability refresh or a latency/cost
   baseline. Use at most two active rows per provider for a result/capability
   refresh and at most one for a latency/cost baseline. Concurrent-provider
   latency is not comparable performance evidence.

Treat queue free capacity as the schedulable-slot signal. Quota fields such as
`workspaceLeft` can describe unallocated quota rather than current runnable
slots; record them but do not reinterpret an ambiguous zero as definitive
exhaustion when the target queue reports free units and the same workspace has
a proven task history. In that case a bounded submit is the authoritative
capacity probe, and a backend quota rejection is a terminal preflight blocker.

Write concrete preflight evidence into `plan.json`. A missing capability must
produce an explicit blocked row; it must never silently remove a selected row.

### 3. Place and shard rows

Place solely from each row's `execution_requirements`:

- deterministic CPU rows -> CPU pool;
- MuJoCo rows -> simulator-capable CPU or GPU pool;
- Grounding DINO rows -> CUDA/DINO-capable GPU pool;
- `provider_network_scope=external` or `allowed_execution_targets=["local"]`
  rows -> local only, regardless of any observed CloudML route or probe result;
- `provider_network_scope=internal` rows that include `cloudml` in
  `allowed_execution_targets` -> CloudML only after that profile's route probe
  passes on the intended worker network.

Fail closed when a provider row lacks either placement field. Before submitting
a task, require `cloudml` to occur in every assigned provider row's
`allowed_execution_targets`. The eval worker repeats this check before row
execution so an incorrectly submitted CloudML task cannot issue a provider
request.

For a full `baseline-refresh`, assign exactly one selected CloudML row to each
CloudML task, set `nodeNumber=1`, and set worker `max_parallel=1`, including for
deterministic CPU rows. The scheduler may place different tasks on the same
physical host; physical-host isolation is not required. Derive task count and
the ready set from the frozen manifest rather than carrying forward a historical
shard count or observed peak concurrency. A bounded smoke may pack short
deterministic rows only when its run-local plan explicitly opts out of the full
refresh isolation policy.

Run a producer/consumer dependency chain as separate tasks in separate stages.
Submit the consumer only after the producer artifact is durably committed and
verified. Never mix benchmark scenes in one shard. Give long live rows
independent tasks when provider concurrency allows. A local `concurrency_group`
limits shared local resources; isolated CloudML workers may overlap only when
the plan records their independent resource and provider bounds.

Keep Grounding DINO colocated with its corresponding MuJoCo row. The same worker
Pod runs the simulator/runtime and its local HTTP visual-grounding sidecar; do
not replace this with a shared cross-Pod DINO service during a baseline refresh.
Run external-provider rows locally with `max_parallel=1`. Kimi and MiniMax must
never enter a CloudML shard, even if an ad hoc network probe happens to succeed.
Those local rows may overlap the CloudML wave and must merge into the same final
report.

Require this identity equation before submission:

```text
selected rows = cloud rows + local rows + explicitly blocked rows
```

Require every selected row to occur exactly once on the right-hand side.

### 4. Stage and submit

1. Package the pinned source and required assets content-addressably. Upload
   immutable content only after probing digest marker files; never recursively
   list a known large cache just to test existence.
2. Keep inputs read-only and outputs under the run-owned prefix. Stage only the
   provider environment names required by one shard through the approved secret
   transport; do not upload a complete dotenv.
3. Generate official `custom_train` YAML with the resolved image, real row
   command, framework, queue, readable resource specification, retry disabled,
   preemptible posture, and mounts. Do not use placeholder sleep/echo commands.
   CloudML training may reject Docker `tag@sha256` syntax. When it does, use a
   previously resolved immutable publication tag in YAML, retain the verified
   registry digest in plan/receipt identity, and fail if a later registry check
   shows that tag moved.
4. Persist the YAML and a pre-submit receipt before calling
   `cml custom_train submit --filename <yaml>`.
5. Immediately append the returned task ID to the receipt. On resume, skip a
   shard that already has a task ID unless the plan explicitly creates a new
   attempt.
6. Submit independent shards up to the authorized maximum concurrency. Preserve
   partial submission receipts when capacity is exhausted.

For a full `baseline-refresh`, use `GUARANTEED` r49 resources with
`preemptible: true` and non-preemptible CPU resources. Keep scheduler retry
disabled. Only a classified preemption or infrastructure failure may create one
additional attempt for a row; agent behavior and provider failures are not
retryable infrastructure failures.

The worker may rewrite only the execution manifest's output paths. Set both
manifest `output_dir` and row `row_dir` consistently before hashing and
uploading it. Prefer the writable mount directly. The installed legacy worker
is also allowed to use `/tmp/roboclaws-cloudml/output/shards/<shard-id>` when
the immutable YAML explicitly archives that exact directory and copies its tar
and marker into `/mnt/cloudml/output/shards/<shard-id>` before exiting. Record
both local and remote paths in the receipt; do not use undocumented mount
aliases.

### 5. Monitor and recover

Poll each task with `cml custom_train describe <task-id>`. For unexpected,
failed, or stalled states, inspect events and pod logs according to
`cml-train`. Persist state transitions and timestamps without copying secrets
or full environment dumps.

Unless the run plan sets stricter bounds, review a task after 15 minutes queued
and classify it stalled after 30 minutes without a lifecycle transition or
worker output. A retry creates a new attempt, output prefix, YAML, and task ID.

Stop only a task that is failed, irrecoverably stalled, or no longer useful to
this run. Do not delete it. Retry only a classified infrastructure failure or
preemption, and create a new task receipt with `attempt + 1`; never retry an
agent behavior failure as infrastructure.

### 6. Collect and verify

1. Download only terminal shard output prefixes with executor JuiceFS download.
2. Require one terminal marker per shard and one `row_result.json` per executed
   row. Validate the combined marker/result evidence for shard ID, row ID,
   execution target, attempt, source and scoped-manifest digests,
   code/image/asset/command identities, terminal status, and result digest
   before merging.
3. Reject unknown, duplicate, mismatched, or missing rows. Make repeated
   collection idempotent.
4. For every accepted collected `eval_results.json` whose suite uses
   `roboclaws_eval_suite_v1`, call
   `roboclaws.evals.phoenix_projection.project_completed_eval_to_phoenix`
   locally with the frozen row's suite reference and accepted result path. This
   reads the existing `ROBOCLAWS_PHOENIX_OTLP_ENDPOINT` configuration and
   writes or replaces the adjacent `phoenix_projection.json`; do not carry a
   worker-local disabled receipt forward as final evidence. Project valid
   failed and blocked result bundles, exclude rows without `eval_results.json`,
   and preserve `ready`, `disabled`, or `unavailable` in the row evidence. Mark
   other suite schemas explicitly `not_applicable`; their Trace telemetry keeps
   its own contract and must not be coerced into a repo suite Dataset.
   Projection is fail-open and must not change collection acceptance or the
   eval outcome. Repeated collection must reuse immutable Phoenix identity.
5. Merge results into the frozen manifest without changing row selection,
   command, case, or private-evaluation boundaries. Attach each accepted
   `phoenix_projection.json` and its state/reason summary, write the authoritative
   combined manifest locally, then call
   `roboclaws.evals.harness.runner.regenerate_observability_report` with that one
   explicit manifest path. This package owner rebuilds the normal JSON, Markdown,
   and HTML reports plus the nested decision section after all paths are relocated;
   collection must not implement a second renderer or scan other run roots.
6. Scan YAML, argv displays, logs, receipts, collected outputs, projection
   receipts, and reports for current credential values before accepting the run.

## Acceptance

Do not call the run complete until all selected rows are executed, locally
assigned, or explicitly blocked; every submitted shard is terminal; collection
has zero unknown, duplicate, mismatched, or missing results; and the normal
grader/report exit semantics are preserved. The final evidence must also name
the Phoenix projection state for every accepted repo suite result bundle and
the explicit `not_applicable` reason for other suite schemas; a disabled or
unavailable local Phoenix service remains an observability limitation, not an
eval failure.

Distinguish a terminal report from an accepted complete baseline. A report may
retain explicitly blocked rows as evidence, but a full baseline with any
blocked external-provider row is incomplete and must not be accepted or published
as the durable baseline.

For a parallel proof, additionally record at least two independent task/row
intervals that overlap, peak concurrency greater than one, summed row duration,
execution makespan, queue wait, preemptions, retries, and computed speedup. Use
row `started_at`/`finished_at` intervals: makespan is the union envelope from
the earliest start to latest finish, peak concurrency is the maximum count of
open half-intervals `[start, finish)`, and speedup is summed row duration divided
by makespan. A set of successful serial jobs is not parallel-execution proof.

For a baseline refresh, first hold the current canonical Runtime Map Prior
fixed. Run MapBuild candidate generation and regrading separately, then present
ranked accepted candidates for human confirmation before publishing a new
canonical prior or durable baseline/catalog artifact.

## Failure Rules

- Preserve provider outage, quota exhaustion, harness/infrastructure failure,
  timeout, preemption, and agent behavior as distinct classifications.
- Fail loudly when required config, image, asset, prior, runtime, or output is
  missing. Do not add fallback profiles, images, scenes, or local substitutes.
- Preserve receipts and collected evidence after failure. Report exact task IDs,
  terminal states, commands, and local evidence paths without exposing secrets.
