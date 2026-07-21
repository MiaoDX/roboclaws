# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: execute the approved standard CloudML Eval Harness support
through `intuitive-flow`, committing coherent slices along the way.

Current slice: implement execution-neutral row timing, capability/dependency
metadata, exact-row workers, bounded local parallelism, and aggregation.

Current blocker: none for deterministic implementation or CloudML dry-run.
Real CloudML submit is a cost-bearing stop gate; formal live rows additionally
require a native secret reference or workload identity.

Blocker fingerprint: none

Last proven evidence:

- Existing offline Docker `smoke_regression` passed with `--network none`.
- Existing CloudML dry-run and JuiceFS upload dry-run completed in the 2026-06
  prototype.
- Current executor readiness is `ready` through
  `exe compute cloudml check_deps --json`.
- Current queue probe exposes RTX 4090-class `r49-24g` resources in
  `robot-dev-common`; availability is a snapshot, not a quota guarantee.
- The 2026-07-21 local `baseline-refresh` completed serially in about 2 hours
  42 minutes and exposes no per-row duration fields in its manifest.

Completed slice batch: approved preflight contract reconciled into the existing
canonical plan; stale single-suite scope and retired executor naming removed
from current guidance.

Next hypothesis: a frozen manifest plus dependency-safe worker protocol can
support both local parallel execution and CloudML without duplicating selection
or report policy.

Next proof:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/evals/test_eval_harness_baseline_profiles.py \
  tests/unit/evals/test_eval_harness_selector.py \
  tests/contract/dev_tools/test_eval_just_recipe.py
```

Stop condition: stop before the first real CloudML submission, any plaintext
secret workaround, provider identity substitution, or new cross-repo executor
API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: none inside the accepted plan; FDS publication remains optional.
