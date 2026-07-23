# Evaluation Harness And Suites

Roboclaws uses four related but separate proof layers:

| Layer | Command shape | Owns |
| --- | --- | --- |
| Product run | `just run::surface ...` | One operator-facing run with prompt, surface, world, backend, agent engine, evidence lane, artifacts, and report. |
| Eval harness | `just agent::eval recommend|execute ...` | Diff- or plan-aware orchestration across deterministic gates, product rows, eval suites, live-agent evals, blocked evidence, and regression-promotion guidance. |
| Eval suite | `just agent::eval suite=<suite> ...` | Versioned capability benchmark across samples, trials, graders, aggregate metrics, and failure replay. |
| Harness recipe | `harness::*` or lower private recipes | Specialist execution mechanics used by product runs and eval flows. |

The maintained user-facing skill is `@eval-harness`. The old separate
`agent-validation-matrix` route is retired; historical evidence may still link
to it, but active plan/diff validation should use `just agent::eval
recommend|execute`.

For the current row, engine, provider, intent, and evidence-lane inventory used
to discuss baseline scoping and pruning, see
[Eval harness dimensions](eval-harness-dimensions.md).

An eval suite answers whether a capability is improving over time, not whether a
single demo happened to complete. The expected flow is:

```text
eval_suite
  -> eval_sample
  -> environment reset
  -> agent trial
  -> trace and artifacts
  -> deterministic and optional advisory graders
  -> aggregate metrics
  -> failure replay or regression sample
```

Initial household graders should cover artifacts, final state/outcome,
trajectory, privacy, and efficiency. Deterministic privacy and safety failures
are authoritative; model or human rubric graders are advisory until calibrated.

Eval results must record enough identity to compare runs: suite/sample/trial,
surface, intent, preset, world, backend, evidence lane, camera labeler, scenario
setup, seed, prompt or goal hash, agent engine, provider/model, skill source,
MCP profile/tool surface, runtime limits, budgets, and artifact schema versions.
Missing relevant fields should be explicit `unavailable` or `not_applicable`.

The current repo-native schema package is `roboclaws.evals`. Versioned suite and
sample definitions live under `evals/<capability>/`, starting with
`evals/household_world/`.

The deterministic runner is available through:

```bash
just agent::eval recommend plan=docs/plans/example.md budget=focused
just agent::eval execute since=origin/main budget=focused
just agent::eval execute profile=baseline-core budget=focused
just agent::eval execute profile=baseline-live-default budget=focused
just agent::eval execute profile=baseline-refresh budget=focused
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=map_build_consumer budget=smoke
just agent::eval suite=cleanup_capability budget=smoke
just agent::eval suite=scene_sampler_stress budget=smoke
just agent::eval suite=long_horizon_tasks budget=smoke
just agent::eval session-live budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=<profile> live_execution=run
```

Use `profile=baseline-core` for the normal broad local refresh. It selects the
deterministic gates, current eval suites, direct product rows, and Grounding
DINO product rows, without live providers. On the current workstation this is
expected to take roughly 10-15 minutes.

Use `profile=baseline-live-default` when the default GPT Router live-agent route
also needs proof. It adds the default live capability rows but excludes the
MiMo, Kimi, and MiniMax provider sweep; budget roughly 1.5-2 hours on the
current single-slot workstation.

Use `profile=baseline-refresh` for a release/nightly complete refresh. It adds
the explicit alternate-provider matrix and currently takes roughly 2.5-3.5
hours. Named baseline profile rows run when their preflight is ready and
otherwise record blocked evidence; they are not `skipped_by_budget`.

Harness execution is target-aware. `execution_target=local` remains the default
and `max_parallel=1` preserves the historical serial behavior. Raising
`max_parallel` runs independent rows concurrently while dependency chains and
shared local visual-backend groups remain ordered.

Scene expansion happens before execution placement. The harness resolves one
execution-neutral benchmark case from the catalog row, suite, provider profile,
seed, and optional `(scene_source, scene_index)` identity, then writes that case
to the frozen manifest. Local and CloudML schedulers consume the same case IDs,
commands, dependencies, and result schema; CloudML shards are only remote
execution packages and do not define a second benchmark model.

Passing `scene=<source>/<index>,...` expands only catalog rows declared
scene-portable. The current portable rows are the world-public and Grounding
DINO MapBuild product rows. Cleanup, open-ended, long-horizon, and provider
matrix rows keep their suite-owned scene contracts until each suite explicitly
defines portable setup and grading. Locally, multiple visual cases may still
serialize through the single MolmoSpaces backend lock. On CloudML, cases from
different scenes are placed in separate workers and may run concurrently.

Build eval images only when `Dockerfile.eval`, the root lockfile, the visual
grounding lockfile, or the pinned DINO snapshot changes. A baseline refresh
normally reuses already-published image digests and does not rebuild images:

```bash
ROBOCLAWS_EVAL_IMAGE_VARIANT=cpu \
ROBOCLAWS_EVAL_CODE_REF=HEAD \
ROBOCLAWS_EVAL_PUSH=false \
  scripts/dev/build_push_eval_image.sh

ROBOCLAWS_EVAL_IMAGE_VARIANT=cuda \
ROBOCLAWS_EVAL_CODE_REF=HEAD \
ROBOCLAWS_EVAL_DINO_CACHE_DIR="$HOME/.cache/huggingface/hub/models--IDEA-Research--grounding-dino-base" \
ROBOCLAWS_EVAL_PUSH=false \
  scripts/dev/build_push_eval_image.sh
```

Both commands run an offline eval smoke. The CUDA build also requires the
pinned DINO revision in the supplied Hugging Face cache and copies it into the
image; it does not fetch model assets from the public Hub. After local proof,
set `ROBOCLAWS_EVAL_PUSH=true` only when publishing is intended, then use the
reported registry `@sha256:` identity below. Cold builds can take tens of
minutes, especially for CUDA wheels, but cached rebuilds and baseline execution
do not pay that setup cost.

CloudML planning uses the same frozen manifest and row identities:

```bash
ROBOCLAWS_CLOUDML_CPU_IMAGE_URL='<cpu-image>@sha256:<digest>' \
ROBOCLAWS_CLOUDML_GPU_IMAGE_URL='<cuda-image>@sha256:<digest>' \
ROBOCLAWS_CLOUDML_ASSET_MANIFEST=/path/to/roboclaws_cloudml_cleanup_assets.json \
  just agent::eval execute profile=baseline-core budget=focused \
  execution_target=cloudml cloudml_dry_run=true cloudml_preemptible=true
```

With `cloudml_dry_run=true`, this generates executor `custom_train` YAML for
CPU and RTX 4090 shards without uploading or submitting. Inputs are mounted
read-only, outputs use a run-owned writable JuiceFS prefix, and
code/image/asset identities are pinned. Only image variables for pools selected
by the plan are required, so a CPU-only run does not need a CUDA image. The CUDA
image contains the pinned Grounding DINO model snapshot and CUDA sidecar venv;
the CPU image stays smaller and does not install those dependencies.
`cloudml_preemptible=true` marks only r49 GPU shards as preemptible so they can
borrow idle capacity from the queue's `GUARANTEED` resource; CPU shards remain
non-preemptible. A preempted shard must be resumed as a new explicit attempt.
The task-level preemptible flag is independent of CloudML resource priority; it
does not require a separate `BEST_EFFORT` r49 resource class.

The 2026-07-22 complete baseline proof selected 27 rows and placed 25 eligible
rows into 15 CloudML shards: one CPU shard and 14 preemptible r49 GPU shards.
All 15 tasks were created within 19 seconds and completed in 54 minutes 12
seconds without preemption. Their row durations summed to about 4 hours 11
minutes, an effective 4.6x reduction against serialized work. Two direct
Kimi/MiniMax rows were explicitly blocked because the internal worker pool
lacks external egress; they were not silently dropped.

A 2026-07-23 two-scene MapBuild proof used the same case IDs for local and
CloudML execution on `procthor-10k-val/0` and
`procthor-objaverse-val/0`. Both local cases passed while respecting the shared
visual-backend lock. CloudML placed them in two one-r49 shards on different
workers; both passed, their execution intervals overlapped, and 107.149 seconds
of summed row work completed in about 59 seconds of row-stage wall time (about
1.82x). This proves placement-level parallelism without changing benchmark
identity or grading.

After reviewing the dry-run and accepting the CloudML cost, omit
`cloudml_dry_run=true` to upload the staging directory and submit detached
jobs. The plan persists each task ID immediately, so a partial submission is
resumable:

```bash
ROBOCLAWS_CLOUDML_CPU_IMAGE_URL='<cpu-image>@sha256:<digest>' \
ROBOCLAWS_CLOUDML_GPU_IMAGE_URL='<cuda-image>@sha256:<digest>' \
ROBOCLAWS_CLOUDML_ASSET_MANIFEST=/path/to/roboclaws_cloudml_cleanup_assets.json \
  just agent::eval execute profile=baseline-core budget=focused \
  execution_target=cloudml output_dir=output/eval-harness/<run>
just agent::eval execute run=output/eval-harness/<run>
```

Status is a single query by default. Waiting is opt-in. Collection downloads
the run-owned JuiceFS output, requires terminal markers and exact row/shard
identities, then rewrites the normal harness JSON, Markdown, and HTML reports:

```bash
just agent::eval status run=output/eval-harness/<run>
just agent::eval status run=output/eval-harness/<run> wait=true timeout_s=3600
just agent::eval collect run=output/eval-harness/<run>
```

Direct Kimi/MiniMax require external egress. API Router and MiMo rows can run on
CloudML from the repo-local `.env`; `ROBOCLAWS_PROVIDER_ENV_FILE` selects a
different local dotenv source. The adapter reads each profile's requirements
from the provider registry, writes only the required values to a `0600`
temporary file, uploads one file per shard to a separate run-owned JuiceFS
prefix, and mounts it read-only at `/mnt/cloudml/provider-env`. The temporary
local file is removed after submission, and the secret mount is separate from
the collected output mount. Commands, generated YAML, plans, logs, reports, and
normal result artifacts contain paths and environment names, not key values.

This is controlled plaintext storage on JuiceFS, not a platform secret manager:
the remote provider file is not automatically deleted. Do not upload the full
`.env`; keep the provider prefix access-controlled and rotate credentials under
the normal provider policy. Missing required values produce
`missing_provider_environment`. `execution_target=auto` currently supports
placement dry-runs only because a real hybrid run still needs dependency-safe
handoff between CloudML producer rows and local provider consumers.

Direct suites run direct-runner household samples without provider keys, write
`output/evals/<suite>/<stamp>/eval_results.json`, and render
`eval_report.html` with links to the underlying product run artifacts. Smoke
budget uses the synthetic cleanup backend for local determinism while eval
identity still records the sample's public surface, world, backend, evidence
lane, and missing live-provider fields explicitly.
The `long_horizon_tasks` pilot is the exception: smoke budget runs the real
MolmoSpaces implementation backend for `molmospaces/val_0` so it can prove
multi-room navigation, visual confirmation, pick/place, and private final-state
grading in the target sim scene.

`long_horizon_tasks` contains Chinese household open-task samples that exercise
longer multi-room manipulation while remaining a focused subset of
open-ended goals, not a separate public task axis. It uses the public
household-world open-task route plus a private `long_horizon` grader that
checks target final placement, empty hands at `done`, required public tool
sequence, source/destination progress, artifact readiness, and private-truth
leakage. The v1 samples deliberately stay within existing sim primitives:
navigation, observation, camera adjustment, pick, place/place_inside, optional
open/close receptacle, and done. Stairs, elevators, parcel unpacking, and
drawer-specific interaction remain future scene/runtime capabilities.

`cleanup_capability` records repeated cleanup trials and reports `pass@k` plus
`pass^k` aggregate metrics. Live-agent eval identity can be requested with
`agent_engine=... provider_profile=...`; by default those trials are recorded
as blocked identity/preflight packets so provider-backed work is not launched
by accident. Use `live_execution=run` only when you intend to run the selected
live provider route. The live bridge calls the public `run::surface` product
route, pins an eval-owned `run_dir`, discovers timestamped product artifacts
when needed, and grades the SDK product artifacts written under that run dir:

```bash
just agent::eval suite=cleanup_capability budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=codex-router-responses \
  live_execution=run
```

Live evals default to a 1200 second wall-clock budget and a 120 second
no-progress stall timeout. Pass `live_timeout_s=<seconds>` only when you intend
to override the whole-run wall-clock budget for a specific run. Catalog rows
may own a larger explicit budget when the suite has a repeatable long-running
contract. The MapBuild provider matrices use 1500 seconds because their cleanup
consumers can exceed 1200 seconds while continuing to make model and tool
progress. A targeted CloudML proof completed those cleanup cells in 1144.758
and 1250.085 seconds and passed the full matrix 5/5.

The eval result records blocked provider/runtime conditions separately from
agent behavior when the selected live route cannot finish.

`session-live` is the Operator Session chaining live eval. It uses the
headless operator-console API to start an OpenAI Agents SDK open-ended parent
run, send active-run Steer, verify the parent consumed Steer through
`check_operator_messages`, wait for terminal parent artifacts, post Next Goal,
verify the child run inherited session and parent metadata plus sanitized
follow-up context, then wait for the child terminal state. Provider keys,
OpenAI Agents SDK package availability, port conflicts, and runtime readiness
blockers are reported as blocked evidence instead of agent behavior failures.

Completed live eval artifacts can be regraded after grader changes without
launching a provider route:

```bash
just agent::eval suite=map_build_consumer budget=focused \
  agent_engine=openai-agents-sdk provider_profile=codex-router-responses \
  regrade_source=output/evals/<suite>/<stamp>
```

MapBuild review can also be rendered as a cross-run matrix report after running
multiple providers or settings:

```bash
just agent::eval map-build-report \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json,output/evals/<suite>/<other-stamp>/eval_results.json \
  output_dir=output/evals/map-build-matrix-review
```

`eval_results=` accepts comma-separated files or directories. Directories are
searched for `eval_results.json`. The command writes
`map_build_matrix_report.html` and `map_build_matrix_summary.json`; the report
compares MapBuild quality, runtime-map enrichment over the Base Metric Map,
downstream open-ended and cleanup deltas between tasks run without the MapBuild
prior and with the fixture-focused MapBuild prior, wall time, model attempts,
and MCP/tool request counts. It uses only eval artifacts and grader outputs;
private fixture/scorer truth remains grader-only and is not converted into
runtime or agent-facing map input.

Recommended Runtime Map Prior selection is a follow-on EvalHarness use case:
run or regrade comparable MapBuild candidates for the same scene/backend,
apply hard gates before ranking, and emit a catalog entry only for an accepted
Runtime Map Prior Snapshot. SimOracle or grader-only truth may choose and
explain the winner in maintainer reports, but selected prior artifacts and
operator-console payloads must remain public/private safe. Catalog entries
should be pinned with provenance while using compatibility classes so minor
report, doc, or non-contract metadata changes do not force live reruns.

`scene_sampler_stress` is the static eval projection for source-aware
MolmoSpaces scene sampling. It currently admits six prepared
`procthor-10k-val` map-build samples and ten prepared `procthor-objaverse-val`
map-build samples; `procthor-10k-val` remains a partial source until more rows
clear the scanner gates.
Sampler selection uses a deterministic seeded-random policy that is scoped per
`scene_source` and prefers different public room counts before filling remaining
slots, so UI/eval rows do not depend on a single contiguous scene-index range.
`ithor` and `holodeck-objaverse-val` remain in the projection as rejected
exhausted source metadata because their candidate evidence fails the current
public-room/actionability gates. Its `sampler_admission` grader checks the
sampler metadata carried by each sample: split-qualified `scene_source`, scene
index, readiness status, room/navigation-area count, waypoint count,
room-category provenance, selected reason, generator version, and
blocked/rejected projection metadata. The grader is deterministic and must not
call live providers.

Scene catalog changes are synchronized through a deterministic guard:

```bash
.venv/bin/python scripts/operator_console/check_scene_catalog_sync.py
```

Run it after changing MolmoSpaces candidate indices, committed map bundles,
room-label manifests, preview assets, or scene-sampler admission logic. It
regenerates the scene-sampler eval suite and samples in a temporary directory,
diffs them against committed fixtures, and checks that every operator-console
MolmoSpaces world has the expected preview coverage. It does not rewrite
`cleanup_capability`, `map_build_consumer`, `open_ended_goals`, or their
household samples unless the scenario contract for those suites changes too.

Sampler readiness exports include a separate
`scene_sampler_candidate_profile.json` for metadata-first curation across all
four scene groups. The profile can recommend new source-scoped candidate ids for
`ithor` and `holodeck-objaverse-val`, but it has no admission effect: a scene
still enters `scene_sampler_stress` only after the normal scanner gates pass.

Blocked live-agent packets include either `roboclaws_live_eval_preflight_v1`
runner metadata, or a live product-route failure classified separately from
agent behavior failures. Provider 5xx/429/model-service failures are
`model_or_provider_unavailable`; missing simulator/runtime dependencies are
`environment_blocked`.

Failed, blocked, or inconclusive eval results can be promoted into a durable
regression sample with:

```bash
just agent::eval promote-regression \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json \
  source_sample_id=<sample-id> \
  regression_sample_id=regression.<name>
```

By default this writes a sample under `evals/household_world/samples/regressions/`
and updates the source suite manifest. Use `sample_output_path=...` and
`suite_output_path=...` for dry runs or review-local promotion artifacts. Human
review labels are `eval-regression:accepted`,
`eval-regression:needs-human-review`, and `eval-regression:do-not-promote`; the
last label is a stop label and will not write a sample.

Keep private scorer truth private. Generated mess sets, acceptable destinations,
hidden target lists, and private manifests may feed graders and reports, but
they must not appear in agent-facing MCP inputs or capability profile metadata.
Eval-harness manifests may link maintainer-only private artifacts, but must not
inline that private truth.
Cleanup evals should classify a live `static_fixture_projection` MCP call as a trajectory
violation while allowing historical artifact fields with the same name to remain
readable for reports and map-bundle compatibility. Regression promotion records
source result links and human labels inside `private_goal_reference` with
`private_truth_scope=grader_only`; that reference is grader input, not agent
input.
