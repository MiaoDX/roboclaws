# Household World Eval Fixtures

This directory contains versioned eval-suite and eval-sample definitions for
the household-world capability. Run the deterministic smoke suite with:

```bash
just agent::eval suite=smoke_regression budget=smoke
```

Run the dedicated open-ended household goal suite with:

```bash
just agent::eval suite=open_ended_goals budget=smoke
```

The open-ended suite currently contains a negative drink-search sample, an
area-inspection sample, and a positive public-waypoint sample. Positive samples
grade against public runtime-map or trace evidence rather than private scorer
truth.

Run the map-build consumer suite with:

```bash
just agent::eval suite=map_build_consumer budget=smoke
```

Run the source-aware scene sampler stress suite with:

```bash
just agent::eval suite=scene_sampler_stress budget=smoke
```

Run the first long-horizon household task pilot with:

```bash
just agent::eval suite=long_horizon_tasks budget=smoke
```

The initial long-horizon sample uses `molmospaces/val_0` and grades a
multi-object snack restock task with private final-state and trajectory checks.
It deliberately stays inside existing sim capabilities: navigation,
observation, pick/place, open/close receptacle, and done. Stairs, elevators,
parcel unpacking, and drawer-specific interaction are follow-on scene/runtime
capabilities, not part of this first pilot.

Scene-sampler fixtures are generated from the MolmoSpaces scene catalog, not
hand-maintained one file at a time. After changing scene candidate indices,
committed Base Metric Map bundles, room-label manifests, or operator-console
preview assets, check the required sync surface with:

```bash
.venv/bin/python scripts/operator_console/check_scene_catalog_sync.py
```

That guard covers `scene_sampler_stress.json`,
`samples/scene_sampler/*.json`, and the MolmoSpaces operator-console previews.
The cleanup, map-build consumer, and open-ended suites are separate capability
samples; they do not need to refresh just because the scene sampler admits a
new scene unless their own world, prompt, grader, or scenario contract changes.

Run repeated cleanup trials for `pass@k` and `pass^k` metrics with:

```bash
just agent::eval suite=cleanup_capability budget=smoke
```

Non-direct selections preserve live-agent identity and produce blocked
provider/runtime evidence unless live execution is explicitly requested:

```bash
just agent::eval suite=cleanup_capability budget=smoke agent_engine=openai-agents-sdk provider_profile=codex-router-responses
```

Run an opt-in live provider route only when local provider/runtime requirements
are available:

```bash
just agent::eval suite=open_ended_goals budget=smoke \
  agent_engine=openai-agents-sdk provider_profile=codex-router-responses \
  live_execution=run
```

Live evals default to a 1200 second wall-clock budget and a 120 second
no-progress stall timeout. Pass `live_timeout_s=<seconds>` only when you intend
to override the whole-run wall-clock budget for a specific run.

The smoke budget writes `output/evals/<suite>/<stamp>/eval_results.json`,
renders `eval_report.html`, and links each eval result back to the underlying
product run artifacts. Repeated suites keep every trial result visible in the
bundle and report `pass_at_k` plus `pass_caret_k`.

Promote a failed, blocked, or inconclusive result into a durable regression
sample with:

```bash
just agent::eval promote-regression \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json \
  source_sample_id=<sample-id> \
  regression_sample_id=regression.<name>
```

Use `sample_output_path=...` and `suite_output_path=...` for review-local dry
runs. Promotion metadata keeps source artifacts and human review labels under
`private_goal_reference` with `private_truth_scope=grader_only`.
