# CloudML Experiment Flow

For new Eval Harness work, use the target-aware `just agent::eval` flow in
`docs/human/evaluation.md`; it owns current submit, poll, collect, resume, and
provider-env staging. The shell workflow below is the older single-suite
experiment prototype and remains only for its already-validated product
cleanup/staging path. Its `cloudml_eval_dry_run.sh` submit implementation still
names a retired executor route and must not be used as the canonical eval
submission command.

This runbook fixes the full executor-backed experiment loop for Roboclaws
cleanup product runs and evaluation trials:

1. stage code and assets as JuiceFS-friendly archives;
2. submit a CloudML job through executor;
3. keep raw artifacts and evaluation output on JuiceFS;
4. publish the completed product or eval report bundle to FDS for browser
   preview and team discussion.

JuiceFS is the durable input and artifact store. It is not the HTML preview surface:
`cloud.mioffice.cn/juicefs/vol-detail?.../report.html` redirects through CAS
and behaves like a file browser, not a static report host. FDS is the preview
surface when a report needs to be shared.

Treat one `ROBOCLAWS_EXPERIMENT_STAMP` as the id for one attempt. Use a new
stamp for each parallel product or eval experiment so the JuiceFS output prefix
and FDS preview prefix never overwrite another run.

## Entry Points

Use the phase wrapper for normal experiments:

```bash
scripts/dev/cloudml_experiment_flow.sh
```

Useful lower-level entry points remain available:

```bash
scripts/dev/stage_cloudml_cleanup_assets.sh
scripts/dev/cloudml_eval_dry_run.sh
scripts/dev/publish_cloudml_report_to_fds.sh
```

Defaults are conservative. The wrapper uses dry-run mode unless
`ROBOCLAWS_EXPERIMENT_DRY_RUN=false` is set.

To stage/upload assets and submit a product cleanup CloudML job in one command:

```bash
ROBOCLAWS_EXPERIMENT_DRY_RUN=false \
ROBOCLAWS_EXPERIMENT_STAMP=<experiment-id> \
ROBOCLAWS_CLOUDML_IMAGE_URL=<pushed-image> \
  scripts/dev/cloudml_experiment_flow.sh
```

Publishing is still a separate phase because CloudML execution is asynchronous.
The same wrapper is used for evaluation jobs by setting
`ROBOCLAWS_CLOUDML_RUN_MODE=eval-focused`.

## 1. Stage Assets And Code

```bash
ROBOCLAWS_EXPERIMENT_PHASE=stage-assets \
  scripts/dev/cloudml_experiment_flow.sh
```

The stage script builds a small upload set:

- `archives/cleanup-focused-molmospaces-val0.tar.gz`
- `archives/cleanup-focused-molmospaces-val0.tar.gz.sha256`
- `archives/roboclaws-code-<commit>.tar.gz`
- `archives/roboclaws-code-<commit>.tar.gz.sha256`
- `roboclaws_cloudml_cleanup_assets.json`

The asset archive contains the MolmoSpaces scene, required offline manifests,
object/robot assets, and the Roboclaws map bundle. CloudML extracts this archive
to local scratch by default:

```bash
ROBOCLAWS_CLOUDML_ASSET_CACHE_MODE=local-scratch
```

Do not extract 100k+ small asset files back into JuiceFS for each run. Keep the
archive on JuiceFS, then extract once per worker-local cache sha.

With `ROBOCLAWS_EXPERIMENT_DRY_RUN=true`, the script only prints and dry-runs the
JuiceFS upload. With `ROBOCLAWS_EXPERIMENT_DRY_RUN=false`, the wrapper sets
`ROBOCLAWS_STAGE_RUN_UPLOAD=true` and uploads the staged archive set to JuiceFS.
Use the dry-run output first when changing the target path.

## 2. Submit The CloudML Experiment

After the assets/code archives are present on JuiceFS, submit the CloudML task:

```bash
ROBOCLAWS_EXPERIMENT_PHASE=submit \
ROBOCLAWS_EXPERIMENT_DRY_RUN=false \
ROBOCLAWS_CLOUDML_STAMP=<experiment-id> \
ROBOCLAWS_CLOUDML_IMAGE_URL=<pushed-image> \
  scripts/dev/cloudml_experiment_flow.sh
```

The current cleanup product command inside CloudML is:

```bash
just run::surface \
  surface=household-world \
  world=molmospaces/val_0 \
  backend=mujoco \
  preset=cleanup \
  agent_engine=direct-runner \
  evidence_lane=world-public-labels \
  seed=7 \
  scenario_setup=relocate-cleanup-related-objects \
  relocation_count=5 \
  map_bundle=assets/maps/molmospaces/procthor-10k-val/0 \
  output_dir=/mnt/cloudml/output/roboclaws-cleanup-runs/<experiment-id>
```

For evaluation-focused jobs, set:

```bash
ROBOCLAWS_CLOUDML_RUN_MODE=eval-focused
ROBOCLAWS_CLOUDML_SUITE=<suite>
ROBOCLAWS_CLOUDML_BUDGET=<budget>
```

Those jobs write `eval_results.json` and `eval_report.html` under the CloudML
eval output directory on JuiceFS. Publish the eval run directory the same way as
a product run; the publish script auto-detects `eval_report.html` when no
`report.html` is present.

CloudML execution is asynchronous. The submit phase returns the CloudML task id
or generated YAML; it does not wait for the product report.

## 3. Publish The Finished Report To FDS

Once the CloudML output directory contains one `report.html` or
`eval_report.html`, publish it:

```bash
ROBOCLAWS_EXPERIMENT_PHASE=publish \
ROBOCLAWS_EXPERIMENT_DRY_RUN=false \
ROBOCLAWS_PREVIEW_JUICEFS_URL='<cloud.mioffice.cn JuiceFS vol-detail URL to the run dir>' \
ROBOCLAWS_PREVIEW_STAMP=<experiment-id> \
ROBOCLAWS_PREVIEW_CLOUDML_JOB_ID=<task-id> \
  scripts/dev/cloudml_experiment_flow.sh
```

If the report is already local:

```bash
ROBOCLAWS_EXPERIMENT_PHASE=publish \
ROBOCLAWS_EXPERIMENT_DRY_RUN=false \
ROBOCLAWS_PREVIEW_LOCAL_DIR=/path/to/seed-7 \
ROBOCLAWS_PREVIEW_STAMP=<experiment-id> \
  scripts/dev/cloudml_experiment_flow.sh
```

By default, preview upload targets:

```text
miaodongxu/roboclaws/reports/<experiment-id>/
```

and uses:

```bash
executor storage fds upload --public --entrypoint <report.html|eval_report.html>
```

The publish script verifies:

- FDS upload succeeded;
- the returned entrypoint URL returns HTTP 200;
- the returned content type is HTML;
- one referenced image asset returns HTTP 200 when an image exists.

The publish script copies the source bundle into
`/tmp/roboclaws-fds-preview/bundles/<experiment-id>` and writes
`cloudml_preview_summary.json` there before upload. For product reports, the
summary includes `run_result.json` status fields when present. For eval reports,
it includes suite id, budget, total/passed/failed/blocked, `pass@1`, `pass@k`,
and `pass^k` when `eval_results.json` is present.

## Output Index

Record these three values for each experiment:

```text
cloudml_task_id:
juicefs_output_prefix:
fds_preview_url:
```

This is enough for later comparison, reruns, and discussion.

For multiple concurrent attempts, keep a tiny table with one row per stamp:

```text
stamp:
mode: product-cleanup|eval-focused
cloudml_task_id:
juicefs_output_prefix:
fds_preview_url:
result: passed|failed|blocked|partial|running
notes:
```

This is a runbook, not a Codex skill yet. The current flow still depends on
operator choices such as image tag, code commit, suite, budget, CloudML task id,
and the exact JuiceFS output URL. After a few repeated/parallel attempts use
the same defaults without adjustment, promote the wrapper into a small skill
that reads this runbook and calls the three scripts.

## Latest Validated Example

On 2026-06-20, the flow was validated with:

```text
cloudml_task_id: t-20260620152632-n0wn2
code_commit: dfb0a395d1cf56121a00ed3f1477e3f7cf8130b3
juicefs_output_prefix: robot-intelligent-planning-data/dongxu/gpu_perf/executor_cloudml_runs/roboclaws-cleanup-runs/cloudml-cleanup-dfb0a395d1cf-20260620-local-scratch-offline-manifest/0620_1527/seed-7
fds_preview_url: https://cnbj1-fds.api.xiaomi.net/miaodongxu/roboclaws/reports/cloudml-cleanup-dfb0a395d1cf-20260620/report.html
```

The infrastructure path completed. The cleanup product gate failed on behavior:
semantic acceptability was partial success with `accepted_count=2/5`, below the
product threshold.
