# Local Runtime Reference

Normal users configure provider keys; observability is optional and fail-open.

## Optional Local Opik

Opik 2.2.36 is the supported local observability backend. It never gates a
product run, eval outcome, collection, or promotion. The base deployment is
loopback-only and stores retained data under `output/opik/`.

```bash
bash scripts/dev/validate_opik_deployment.sh
docker compose -p roboclaws-opik -f deploy/opik/compose.yaml up -d --wait
```

The explicit LAN overlay exposes only the web frontend for human review:

```bash
OPIK_LAN_BIND_HOST=192.0.2.60 \
OPIK_LAN_HTTP_PORT=5174 \
docker compose -p roboclaws-opik -f deploy/opik/compose.yaml \
  -f deploy/opik/compose.lan.yaml up -d
```

Set one loopback base origin for automatic runtime and eval projection:

```bash
export ROBOCLAWS_OPIK_ENDPOINT=http://127.0.0.1:5174
```

Roboclaws routes traces to exactly `roboclaws-runtime` and `roboclaws-eval`.
Eval projection writes adjacent `opik_projection.json` receipts and is bounded,
atomic, idempotent, and fail-open. `opik-project` repairs one named result;
`opik-dashboard` is the explicit Dashboard reconciliation command.

Opik receives only sanitized public identity, allowlisted metrics, and span
metadata. It never receives prompts, tool bodies, images, maps, secrets,
private evaluator truth, or provider endpoints. Local JSON, Markdown, run
artifacts, graders, and promotion decisions remain canonical.

## Provider Keys

Start from [`.env.example`](../../.env.example), then fill only the keys for
the selected profile. The [model and provider matrix](model-matrix.md) maps
each profile to its wire API and required environment.

Every OpenAI Agents SDK launch selects a provider profile explicitly.

## Local Report Artifacts

Eval Harness terminal publication contains only `eval_harness.json`,
`eval_harness.md`, `eval_harness.completed.json`, and adjacent Opik receipts.
Domain-specific HTML reports remain available where their owning surface needs
them; the retired Eval Harness HTML companion and report server are gone.

The hosted capability showcase uploads any adjacent `opik_projection.json`
receipt with its canonical suite bundle, but never sends it to Opik. A trusted
maintainer may later project a retained result with `just agent::eval
opik-project suite=<suite> eval_results=<path>` from a loopback-capable host.

## Runtime Map Prior Storage

Maintainer-approved Runtime Map Prior Snapshot files live under
[`assets/eval-priors/`](../../assets/eval-priors/). JSON files in that directory
are managed by Git LFS; Git stores small pointers and the LFS store retains the
content for each promoted digest. Eval outputs, traces, images, and candidate
collections remain under `output/` or remote Actions/object-storage artifacts
and are not added to LFS.

Promote a reviewed selector result explicitly with
`runtime-prior-promote ... output_dir=assets/eval-priors`. Promotion creates a
new content-addressed directory; existing priors are immutable. Updates are
normally checked monthly and only published after a material source-map,
schema, runtime-contract, evidence-lane, camera-labeler, or quality change.
Provider churn and weekly Showcase runs do not rewrite priors. CI consumers
must check out LFS content (`actions/checkout@v4` with `lfs: true`) or run a
path-scoped `git lfs pull --include="assets/eval-priors/**"`; do not use
`git lfs fetch --all` in routine jobs.
