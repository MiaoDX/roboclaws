# Forward-Only Post-Review Cleanup

Status: ACTIVE

Source plan: `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`

Control plane: root intuitive-flow session / host goal.

Latest intent: execute the approved forward-only cleanup plan. Publication,
physical movement, Omniverse EULA acceptance, compatibility layers, and scope
expansion remain unauthorized.

Current slice: Wave 4 source-aware MolmoSpaces world-ID migration is complete
and awaiting its semantic checkpoint commit.

Last proof: focused scene-sampler, environment setup, operator-console,
task-recipe, eval-model, and current-source contract tests pass; modified JSON,
Ruff, format, the Python quality ratchet, exact legacy-ID search, and
`git diff --check` pass. Direct map-build and cleanup product runs passed for
`molmospaces/procthor-10k-val/0`; receipts are under
`/tmp/roboclaws-wave4-map-build/0729_1041` and
`/tmp/roboclaws-wave4-cleanup/0729_1041`, with cleanup restoring 5/5 objects.

Completed batch: approved execution contract and durable route loaded; current
source absence scope, deletion/move targets, active status surfaces, and prior
receipt sources inventoried. Five explicit DONE capsules moved losslessly to
retrospectives; current docs/navigation and SDK examples repaired; unowned
`CONTEXT.md` and the empty pytest regression layer removed; focused guards added.
Wave 2 deleted the retired direct-provider implementation and provider-only
tests, removed direct-adapter metadata/helpers and obsolete optional extras,
retained `openai` for active SDK/health imports, and refreshed `uv.lock`.
Wave 3 moved Runtime Prior catalog keys, entries, loading, normalization,
compatibility, and auto-enable policy to `roboclaws.maps.runtime_prior_catalog`;
removed product-to-eval imports; made `just agent::eval` call the checkout CLI
directly; removed product CLI aliases; and excluded eval code/assets from both
distribution formats. Wave 4 migrated all current callers, fixtures, examples,
preview metadata, and eval rows to source-aware MolmoSpaces IDs; removed legacy
alias metadata and exports; made legacy IDs fail with an exact replacement; and
kept hidden source-aware sampler candidates dynamically resolvable.

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

Next slice: commit Wave 4, then add the typed launch executor and migrate console
and eval runners before deleting `just agent::run`, `roboclaws.cli.agent_run`,
and positional lowering in Wave 5.

Next proof: focused typed-executor contract tests, exact retired-route and
positional-lowering searches, migrated console/eval caller tests, and direct
product launch proof through the canonical surface grammar.

Stop condition: stop for an unexplained active non-test consumer of a deletion
target, a required public/schema boundary beyond the approved modules, a
candidate recipe change, unavailable required live proof, or any unauthorized
publication/hardware action.

No-touch scope: historical plans/ADRs/retrospectives except current runnable
commands, ignored historical output, unrelated Isaac/Agibot/diagnostic tools,
physical movement, EULA acceptance, and public publication.

Parked work: none inside the approved plan; repository-wide unrelated work
remains in `TODOS.md` and `THOUGHTS.md`.
