# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: execute the approved standard CloudML Eval Harness support
through `intuitive-flow`, committing coherent slices along the way.

Current slice: upload the pinned commit/assets, then prove the
submit/status/collect lifecycle with real deterministic and RTX 4090 CloudML
smokes.

Current blocker: none for the user-approved CPU/GPU smoke sequence. Formal live
provider rows still require a native secret reference or workload identity.

Blocker fingerprint: none

Last proven evidence:

- Local execution defaults to serial behavior, supports bounded parallel rows,
  serializes shared concurrency groups, and enforces dependency ordering.
- Frozen manifests execute exact row IDs without rerunning selection; each
  attempt writes redacted timing/provenance in `row_result.json`, while launched
  subprocess rows retain stdout and stderr logs.
- Focused Eval Harness unit and contract suite passed: 82 tests.
- CloudML placement, frozen-shard relocation, safe mounts, pinned identities,
  worker provenance, and current executor dry-run contracts passed: 70 focused
  tests. A schema-only executor smoke generated YAML without submission.
- Synthetic terminal-marker collection now validates shard/row identities and
  idempotently merges remote row results into the normal harness manifest.
- Submit uploads staging before jobs, persists each task ID independently,
  resumes missing shards without duplication, and preserves explicit retry
  history. Public status, opt-in polling, download, and report collection route
  through `just agent::eval`.
- Existing offline Docker `smoke_regression` passed with `--network none`.
- Existing CloudML dry-run and JuiceFS upload dry-run completed in the 2026-06
  prototype.
- Current executor readiness is `ready` through
  `exe compute cloudml check_deps --json`.
- Current queue probe exposes RTX 4090-class `r49-24g` resources in
  `robot-dev-common`; availability is a snapshot, not a quota guarantee.
- The 2026-07-21 local `baseline-refresh` completed serially in about 2 hours
  42 minutes and exposes no per-row duration fields in its manifest.
- Separate CPU and CUDA eval images pass offline smokes. Their local sizes are
  1.88 GB and 10.84 GB respectively; the CUDA image also loads the pinned DINO
  snapshot offline as `GroundingDinoForObjectDetection`.
- CUDA dependencies and the pinned DINO snapshot are isolated from the CPU
  image. The model enters the build through a local BuildKit named context, so
  public Hugging Face availability is not part of the image contract.
- Cold common dependencies took about 23 minutes and cold CUDA wheels about 22
  minutes to build. Baseline refreshes reuse published images; cached CPU
  rebuilds complete in seconds.
- Commit `865658f2` staging generated a checksummed 39.7 MB code archive and
  1.80 GB cleanup-asset archive locally, with upload explicitly disabled.
- A `baseline-core/focused` CloudML dry-run for that commit selected 18 rows
  with no blocked rows: ten rows in one CPU shard and eight rows across seven
  RTX 4090 shards. Pool-specific placeholder digests reached the correct YAML,
  and only RTX 4090 commands received `cuda`/`float16`; no job was submitted.
- CPU and CUDA images were rebuilt from clean commit `865658f2`, passed offline
  smoke, pushed to the internal registry, and remotely resolved as OCI digests
  `sha256:e715abbd...faa7` and `sha256:d1d4c398...69a4` respectively.

Completed slice batch: execution-neutral local core plus CloudML CPU/RTX 4090
placement, frozen manifests, run-owned mounts, pinned image/code/asset checks,
container worker entrypoint, resumable submit, status/poll, download, and
idempotent report collection are implemented.

Next hypothesis: the published CPU image and checksummed staged inputs can
complete one bounded deterministic shard and collect it into the normal
aggregate manifest.

Next proof:

```bash
ROBOCLAWS_CLOUDML_CPU_IMAGE_URL='<published-cpu>@sha256:e715...' \
ROBOCLAWS_CLOUDML_ASSET_MANIFEST='<staging>/roboclaws_cloudml_cleanup_assets.json' \
  just agent::eval execute profile=baseline-core budget=focused \
  execution_target=cloudml row_id=route-trace-contract-tests \
  output_dir=output/eval-harness/<run>
```

Stop condition: stop before any plaintext secret workaround, provider identity
substitution, destructive retry, or new cross-repo executor API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: secure provider injection is still required for API Router and
MiMo live rows; the repository quality ratchet baseline has unrelated
pre-existing drift even though full Ruff and pytest gates pass; FDS publication
remains optional.
