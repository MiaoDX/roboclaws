# Forward-Only Post-Review Cleanup

Status: ACTIVE

Source plan: `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`

Control plane: root intuitive-flow session / host goal.

Latest intent: execute the approved forward-only cleanup plan. Publication,
physical movement, Omniverse EULA acceptance, compatibility layers, and scope
expansion remain unauthorized.

Current slice: Wave 1 current-truth repair is implemented and awaiting its
semantic checkpoint commit. Wave 0 inventory and recipe freeze are complete.

Last proof: `uv sync --extra dev` passed; the Wave 0 recommendation selected 23
required rows in `output/eval-harness/20260729T014637Z/eval_harness.json`; 123
focused current-source and launch-recipe tests passed; Ruff, format, the Python
quality ratchet, and `git diff --check` pass.

Completed batch: approved execution contract and durable route loaded; current
source absence scope, deletion/move targets, active status surfaces, and prior
receipt sources inventoried. Five explicit DONE capsules moved losslessly to
retrospectives; current docs/navigation and SDK examples repaired; unowned
`CONTEXT.md` and the empty pytest regression layer removed; focused guards added.

Frozen candidate recipe: run `scripts/dev/build_public_candidate.py` into a new
candidate root; run `scripts/dev/check_public_surface.py` and the CI-pinned exact
`detect-secrets` baseline comparison; verify `PUBLIC-MEMBERSHIP.json`; clone the
candidate without recursive submodules into `clean-room`; run `uv sync --extra
dev`, deterministic and documented direct-product gates; run `uv build`; inspect
both `dist/*.tar.gz` and `dist/*.whl`; install each into an isolated environment
and smoke product imports/CLI. Expected receipts are the membership manifest,
public/secret/private-value/import/current-example/artifact scan outputs, eval
manifests and run artifacts, both distributions, and isolated-install logs. The
previous immutable receipt roots remain under `output/public-candidate/` and are
superseded for publication.

Next slice: commit Wave 1, then begin Wave 2 retired direct-provider deletion
after one final active non-test caller check.

Next proof: provider catalog/transport tests plus exact removed-owner searches.

Stop condition: stop for an unexplained active non-test consumer of a deletion
target, a required public/schema boundary beyond the approved modules, a
candidate recipe change, unavailable required live proof, or any unauthorized
publication/hardware action.

No-touch scope: historical plans/ADRs/retrospectives except current runnable
commands, ignored historical output, unrelated Isaac/Agibot/diagnostic tools,
physical movement, EULA acceptance, and public publication.

Parked work: none inside the approved plan; repository-wide unrelated work
remains in `TODOS.md` and `THOUGHTS.md`.
