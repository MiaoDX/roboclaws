# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: execute the approved standard CloudML Eval Harness support
through `intuitive-flow`, committing coherent slices along the way.

Current slice: add CloudML submit/poll lifecycle around the proven CPU/RTX 4090
dry-run, exact-row worker, and idempotent collector contracts.

Current blocker: none for deterministic implementation or CloudML dry-run.
Real CloudML submit is a cost-bearing stop gate; formal live rows additionally
require a native secret reference or workload identity.

Blocker fingerprint: none

Last proven evidence:

- Local execution defaults to serial behavior, supports bounded parallel rows,
  serializes shared concurrency groups, and enforces dependency ordering.
- Frozen manifests execute exact row IDs without rerunning selection; each
  attempt writes redacted timing/provenance in `row_result.json`, while launched
  subprocess rows retain stdout and stderr logs.
- Focused Eval Harness unit and contract suite passed: 59 tests.
- CloudML placement, frozen-shard relocation, safe mounts, pinned identities,
  worker provenance, and current executor dry-run contracts passed: 70 focused
  tests. A schema-only executor smoke generated YAML without submission.
- Synthetic terminal-marker collection now validates shard/row identities and
  idempotently merges remote row results into the normal harness manifest.
- Existing offline Docker `smoke_regression` passed with `--network none`.
- Existing CloudML dry-run and JuiceFS upload dry-run completed in the 2026-06
  prototype.
- Current executor readiness is `ready` through
  `exe compute cloudml check_deps --json`.
- Current queue probe exposes RTX 4090-class `r49-24g` resources in
  `robot-dev-common`; availability is a snapshot, not a quota guarantee.
- The 2026-07-21 local `baseline-refresh` completed serially in about 2 hours
  42 minutes and exposes no per-row duration fields in its manifest.

Completed slice batch: execution-neutral local core plus CloudML CPU/RTX 4090
placement, frozen manifests, run-owned mounts, pinned image/code/asset checks,
container worker entrypoint, and executor dry-run rendering are implemented.

Next hypothesis: submitted shard task ids and terminal markers can drive
idempotent polling/collection into the same aggregate manifest.

Next proof:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/evals/test_eval_harness_baseline_profiles.py \
  tests/unit/evals/test_eval_harness_selector.py \
  tests/unit/evals/test_eval_harness_cloudml.py \
  tests/unit/evals/test_eval_harness_execution.py \
  tests/unit/evals/test_eval_harness_live_ports.py \
  tests/unit/evals/test_eval_harness_manifest.py \
  tests/contract/dev_tools/test_eval_just_recipe.py
```

Stop condition: stop before the first real CloudML submission, any plaintext
secret workaround, provider identity substitution, or new cross-repo executor
API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: none inside the accepted plan; FDS publication remains optional.
