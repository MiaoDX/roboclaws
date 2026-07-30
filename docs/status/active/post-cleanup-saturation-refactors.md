# Post-Cleanup Saturation Refactors

Capsule status: ACTIVE

Source plan: `docs/plans/2026-07-30-post-cleanup-saturation-refactors.md`

Task control plane: current Codex root session.

Latest user intent: execute and commit all five approved refactor candidates.

Current slice: remove the maintainer `Just -> CLI -> Just` dispatch loop.

Last proven evidence: timing-proxy stale-reference search is clean; dependency
sync, Ruff/format, and 153 focused report/eval/CI/command contract tests pass.

Completed slices: legacy run artifacts removed; provider timing proxy and its
reader/switch/test/dependency surface removed.

Next proof: public `agent::*` trace parity, exact duplicate-registry search,
focused CLI/launch tests, Ruff, and diff check.

Stop condition: all five plan rows committed and final deterministic/product
proof passes.

No-touch scope: unrelated active capsules and work; public command grammar;
provider/runtime behavior; simulator/hardware/publication actions.

Parked work: see the source plan.
