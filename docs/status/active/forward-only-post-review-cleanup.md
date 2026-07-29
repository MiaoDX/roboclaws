# Forward-Only Post-Review Cleanup

Status: ACTIVE

Source plan: `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`

Control plane: root intuitive-flow session / active host goal.

Latest intent: finish the approved cleanup and verification. Publication,
physical movement, Omniverse EULA acceptance, compatibility layers, and scope
expansion remain unauthorized.

Current slice: implementation, deterministic/product/live proof, and human-doc
alignment are complete. Commit the aligned docs, replay the frozen candidate
recipe from that exact commit, then close the plan.

Last proof: all six approved live rows pass in
`output/eval-harness/20260729T041434Z/final/eval_harness.json`; the final
source-derived recommendation is
`output/eval-harness/20260729T080334Z/eval_harness.json`. Focused repairs, Ruff,
format, the Python quality ratchet, the fresh full standalone suite,
`just agent::verify mock`, and all four required deterministic eval suites pass.

Next proof: build a new candidate with `scripts/dev/build_public_candidate.py`,
then run public-surface, pinned secret, membership, clean-room, deterministic,
direct-product, distribution-content, and isolated sdist/wheel install gates.

Stop condition: stop for any candidate recipe change, unexplained gate failure,
publication request, hardware action, EULA acceptance, or scope expansion.

No-touch scope: historical plans/ADRs/retrospectives except the new closeout,
ignored historical output, unrelated Isaac/Agibot/diagnostic tools, physical
movement, EULA acceptance, and public publication.

Parked work: none inside the approved plan. Repository-wide unrelated work
remains in `TODOS.md` and `THOUGHTS.md`.
