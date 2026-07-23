# Recommended Runtime Map Prior Selection

Status: ACTIVE

Source plan: `docs/plans/2026-07-01-recommended-runtime-map-prior-selection.md`

Latest user intent: reuse one promoted canonical Map Prior across provider and
configuration matrices; keep builder comparison and end-to-end execution
explicit.

Current slice: deterministic runtime-prior selector and console catalog wiring
implemented and verified; the fixed-map consumer-matrix follow-up is approved
but not implemented.

Last proven evidence:

- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals/test_runtime_prior_selection.py tests/unit/evals/test_eval_reports.py tests/unit/evals/test_eval_harness_selector.py tests/unit/evals/test_eval_runner.py::test_eval_runner_regrades_existing_live_artifacts_without_provider_call tests/unit/evals/test_eval_runner.py::test_map_build_consumer_suite_passes_runtime_map_prior_between_samples tests/unit/operator_console/test_routes.py tests/unit/operator_console/test_launcher.py tests/unit/operator_console/test_static_assets.py tests/contract/dev_tools/test_eval_just_recipe.py`
- `ruff check roboclaws/evals/runtime_prior_selection.py roboclaws/evals/cli.py roboclaws/operator_console/workflows.py tests/unit/evals/test_runtime_prior_selection.py tests/unit/operator_console/test_routes.py tests/unit/operator_console/test_launcher.py tests/contract/dev_tools/test_eval_just_recipe.py`
- `ruff format --check roboclaws/evals/runtime_prior_selection.py roboclaws/evals/cli.py roboclaws/operator_console/workflows.py tests/unit/evals/test_runtime_prior_selection.py tests/unit/operator_console/test_routes.py tests/unit/operator_console/test_launcher.py tests/contract/dev_tools/test_eval_just_recipe.py`
- `node --check roboclaws/operator_console/static/app.js`
- `git diff --check`

Completed slice batch:

- Added a Runtime Map Prior selection manifest/report/catalog contract.
- Added selector hard gates for schema, private boundary, source-map mutation,
  map quality thresholds, SimOracle/grader-only metrics, RGB-only pose claims,
  downstream no-regression rows, and non-blocking staleness.
- Wired operator console recommended-prior loading to a JSON catalog while
  preserving the empty catalog default.
- Added focused tests for accepted catalog defaults, blocking stale rejection,
  explicit override, and no latest-artifact fallback.

Next proof:

- Split `map_build_consumer` into MapBuild candidate, no-prior control, and
  fixed-prior consumer modes; run one scene through the new cached path.

Acceptance audit:

- EvalHarness candidate/regrade support: covered by existing map-build consumer
  matrix rows and regrade tests.
- Selector hard gates and accepted-only catalog emission: covered by runtime
  prior selector tests.
- Compatibility classification: covered for `compatible`, `advisory_regrade`,
  `stale`, missing artifact, and source-map mismatch `blocking_stale`.
- Operator console behavior: covered for empty catalog, accepted catalog,
  blocking stale, missing prior artifact, generated launch argv, and explicit
  override.
- No latest-artifact fallback: covered by empty-catalog route/launcher tests and
  catalog-only default wiring.

Stop condition:

- Met for the selector/catalog slice; the follow-up stops after one canonical
  prior is reused by multiple consumers and cache invalidation is proven.

No-touch scope:

- No live provider execution unless explicitly requested and off-work-network
  requirements are satisfied.
- Do not publish a committed recommended prior without an accepted selector
  report.

Parked work:

- Running a real multi-provider live candidate matrix remains provider/runtime
  capacity dependent.
- Full builder-by-consumer Cartesian matrices remain explicit research/nightly
  work rather than the default baseline.
