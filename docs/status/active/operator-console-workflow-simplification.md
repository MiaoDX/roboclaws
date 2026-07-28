# Operator Console Workflow Simplification

Status: DONE

Source plan: `docs/plans/2026-06-30-operator-console-workflow-simplification.md`

Latest user intent: execute full plan via `$intuitive-flow`; do not stop mid-plan.

Current slice: complete; source plan shipped in
`239f6dcc feat: simplify operator console workflows`.

Last proven evidence:

- `./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console -q`
- focused workflow/static tests
- touched-file `ruff check`, `ruff format --check`, and `node --check`
- browser smoke on `http://127.0.0.1:8876`: MolmoSpaces shows normal
  workflow actions, with-map actions disabled as `NEEDS MAP`, and the command
  preview uses `evidence_lane=camera-grounded-labels`

Next proof: none for this plan; future prior-catalog population is parked.

Stop condition: every plan acceptance gate is covered by current code, tests,
and aligned docs, with a completion audit against the plan.

No-touch scope: provider keys, live model launches, hardware/simulator live
runs, generated output artifacts outside explicitly owned test fixtures.

Parked work: populate the recommended-prior catalog through
`docs/plans/2026-07-01-recommended-runtime-map-prior-selection.md` once accepted
tracked Runtime Map Prior Snapshot artifacts exist for scenes.
