# Post-Cleanup Saturation Refactors

Capsule status: ACTIVE

Source plan: `docs/plans/2026-07-30-post-cleanup-saturation-refactors.md`

Task control plane: current Codex root session.

Latest user intent: execute and commit all five approved refactor candidates.

Current slice: delete the inert provider timing proxy surface.

Last proven evidence: exact legacy artifact caller search is clean; focused
current report contracts and `just verify::contract` pass; touched Ruff and
diff checks pass.

Completed slices: legacy `roboclaws.core.run_artifacts` and its only test/gate
consumer removed.

Next proof: exact timing-proxy producer/switch/artifact searches, focused
performance-report/eval tests, dependency sync, Ruff, and diff check.

Stop condition: all five plan rows committed and final deterministic/product
proof passes.

No-touch scope: unrelated active capsules and work; public command grammar;
provider/runtime behavior; simulator/hardware/publication actions.

Parked work: see the source plan.
