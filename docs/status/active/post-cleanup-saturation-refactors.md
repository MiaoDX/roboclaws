# Post-Cleanup Saturation Refactors

Capsule status: ACTIVE

Source plan: `docs/plans/2026-07-30-post-cleanup-saturation-refactors.md`

Task control plane: current Codex root session.

Latest user intent: execute and commit all five approved refactor candidates.

Current slice: baseline and canonical plan setup.

Last proven evidence: clean `HEAD fee463f5`; `uv lock --check` passes; focused
eval recommendation recorded at
`output/eval-harness/20260730T034753Z/eval_harness.json`.

Next slice: delete legacy `roboclaws.core.run_artifacts` and its self-only test
gate.

Next proof: exact caller search, focused artifact/report contract tests, Ruff,
and diff check.

Stop condition: all five plan rows committed and final deterministic/product
proof passes.

No-touch scope: unrelated active capsules and work; public command grammar;
provider/runtime behavior; simulator/hardware/publication actions.

Parked work: see the source plan.
