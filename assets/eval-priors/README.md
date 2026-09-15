# Canonical Runtime Map Priors

This directory is the Git-tracked namespace for a small set of maintainer-
approved Runtime Map Prior Snapshot artifacts. The snapshot JSON files use Git
LFS; the Git history stores pointer files while the prior contents live in the
LFS store. Catalog and provenance metadata stay as ordinary Git files.

Only immutable, content-addressed canonical priors belong here. Keep the
selection report, promotion manifest, full eval results, traces, images, and
candidate sets in `output/` or the relevant Actions artifact instead. Large
historical candidate collections belong in the project artifact/object store,
not in Git LFS.

## Layout

Promoted artifacts use the digest directory produced by
`runtime-prior-promote`:

```text
assets/eval-priors/
  by-sha256/<canonical-digest>/
    runtime_map_prior_snapshot.json
    provenance.json
  runtime_map_prior_catalog.json
```

The catalog and provenance are ordinary Git files. A catalog entry must point
to a repository-relative path under this directory, so a checkout on another
machine can resolve it. Do not commit the absolute paths emitted by a local
staging run; normalize them before publishing.

## Promotion and updates

Build and review the selector report in a disposable output directory first:

```bash
just agent::eval runtime-prior-select \
  manifest=<selection-manifest.json> \
  eval_results=output/evals/<suite>/<stamp>/eval_results.json \
  output_dir=output/evals/runtime-prior-selection
```

After maintainer approval, promote into this directory and review the generated
JSON before committing the pointer, prior catalog, and provenance together:

```bash
just agent::eval runtime-prior-promote \
  report=output/evals/runtime-prior-selection/runtime_map_prior_selection_report.json \
  manifest=<maintainer-approved-promotion-manifest.json> \
  output_dir=assets/eval-priors
```

Promotion is intentionally explicit. A new prior is warranted when the source
map, map schema, world/backend contract, evidence lane, camera labeler, or
prior quality changes materially. Provider model changes and weekly Showcase
runs do not refresh a prior by themselves. In a stable scene, check the prior
about monthly and expect roughly zero or one content change per quarter.

Never edit a promoted JSON in place. A changed artifact or identity receives a
new digest directory and catalog entry; the old digest remains available for
reproduction until the normal artifact-retention policy removes it.

## Checkout and CI

Install Git LFS before checking out a prior. A normal clone/checkout fetches
the LFS objects needed by the current checkout, not every object from every
historical commit. To avoid downloading content until it is needed, use:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone <repository-url>
git lfs pull --include="assets/eval-priors/**"
```

To reproduce an older prior, check out the target commit and run the same
path-scoped pull. `git lfs fetch --all` downloads every LFS object reachable
from all refs and is not a normal CI operation. Actions jobs that consume a
prior must use `actions/checkout@v4` with `lfs: true`, or perform the explicit
path-scoped pull after checkout.
