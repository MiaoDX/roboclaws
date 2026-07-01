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
just agent::eval execute profile=baseline-refresh budget=focused
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=map_build_consumer budget=smoke
just agent::eval suite=cleanup_capability budget=smoke
just agent::eval suite=scene_sampler_stress budget=smoke
just agent::eval suite=long_horizon_tasks budget=smoke
just agent::eval session-live budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=<profile> live_execution=run
```

Use `profile=baseline-refresh` after large code changes when the goal is to
refresh the whole current baseline instead of selecting rows from a diff. It
selects the catalog baseline: deterministic gates, current eval suites listed
in the eval catalog, direct product rows, Grounding DINO product rows, Codex CLI
live evals, and OpenAI Agents SDK live evals. Selected live or DINO rows run
when their preflight is ready and otherwise record blocked evidence; they are
not `skipped_by_budget`.

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

`long_horizon_tasks` currently contains the first snack-restock pilot. It uses
the public household-world open-task route plus a private `long_horizon` grader
that checks target final placement, empty hands at `done`, required public tool
sequence, source/destination progress, artifact readiness, and private-truth
leakage. The v1 task deliberately stays within existing sim primitives:
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
to override the whole-run wall-clock budget for a specific run.

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
