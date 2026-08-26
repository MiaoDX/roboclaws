---
plan_scope: ci-capability-showcase
status: Implementing
created: 2026-08-26
last_reviewed: 2026-08-26
implementation_allowed: true
current_phase: verification
related_context:
  - STATUS.md
  - README.md
  - ARCHITECTURE.md
  - docs/human/ut_ci_design.md
  - docs/human/evaluation.md
  - docs/human/local-runtime.md
  - .github/workflows/ci.yml
related_adrs:
  - docs/adr/0150-use-opik-as-the-sole-external-observability-backend.md
approval:
  cross_review: approved
  planning_loop: approved
  planning_loop_approved_on: 2026-08-26
  planning_loop_approval_source: user-LGTM
---

# CI Capability Showcase

## Goal

Restore a trustworthy, automatically refreshed public capability/effect
showcase without turning ordinary CI into a paid provider gate or reviving the
retired Pages/live-job architecture. A maintainer should be able to see the
latest attempt, the last successful evidence, the exact commit/run, and the
canonical artifacts behind the result.

## Non-goals

- Do not run live providers on every push or pull request.
- Do not make Opik a GitHub-hosted CI dependency. Current Opik ingestion stays
  loopback-only and fail-open; CI may upload a sanitized projection receipt for
  later trusted projection.
- Do not restore Phoenix, OpenClaw, AI2-THOR, the retired Eval Harness HTML
  companion, or the old Molmo live matrix.
- Do not introduce a general report renderer, a second metrics calculator, a
  provider leaderboard, automatic baseline promotion, or infinite history.
- Do not upload prompts, tool bodies, images, maps, secrets, private evaluator
  truth, or provider endpoints.

## Current Baseline

- `.github/workflows/ci.yml` has one required `lint-and-mock` job.
- `just agent::eval suite=... budget=...` is the canonical suite entrypoint.
- Suite persistence already writes `eval_results.json`, `eval_report.html`,
  Markdown harness output where applicable, and an adjacent fail-open
  `opik_projection.json` receipt.
- The previous GitHub Pages site is frozen historical content and still contains
  stale job claims; it must not be treated as a current source.

## Recommended Shape

```text
push / pull_request
  -> existing required deterministic CI
  -> no provider call and no showcase publication

weekly schedule / explicit workflow_dispatch
  -> one serialized showcase workflow
  -> versioned showcase manifest
  -> selected existing eval suites with fixed seeds/budget/timeout
  -> canonical sanitized summary derived from suite results
  -> GitHub artifact and thin Pages latest projection
  -> optional Opik receipt artifact; no CI dependency on Opik
```

The showcase workflow is advisory. It must report failed and blocked attempts
honestly while preserving the last successful evidence. It must not silently
turn unavailable providers into passing evidence.

## Showcase Scope

Start with one small, versioned manifest that exercises the current public
household capability shape:

1. `household_world.smoke_regression` as the deterministic contract baseline.
2. `household_world.map_build_quality` as the map-build capability sample.
3. `household_world.open_ended_goals` only when the explicit live showcase
   input enables a supported provider; otherwise record a blocked row without
   attempting a provider call.

The manifest owns suite id/version, sample ids, agent engine, provider profile,
seed, evidence lane, budget, timeout, and execution mode. Workflow YAML owns
trigger and permissions, not a duplicated matrix of product semantics.

## Artifact And Publication Contract

The only derived showcase owner is a versioned sanitized summary, for example
`showcase-summary-v1.json`. It contains public identity, attempted and
successful timestamps, run/commit URLs, suite/sample/profile labels, status
(`passed`, `failed`, `blocked`), allowlisted metrics, failure class, and links
to the source artifact. It contains no private truth or raw execution content.

The summary is derived from canonical `eval_results.json`/suite bundles. Pages
HTML and Markdown are pure projections and never recompute pass/fail or metrics.
The first publication contains one `latest` page with:

- last attempt and last successful evidence timestamps;
- the three capability rows and their status/reason;
- exact commit and Actions run links;
- links to retained GitHub artifacts and domain-owned reports;
- an explicit statement that this is advisory showcase evidence, not a merge
  gate.

Failed or blocked attempts may update `last attempt`, but cannot overwrite
`last successful evidence`. Full bundles remain GitHub Actions artifacts under
their normal retention. Do not build an unlimited history index in the first
slice.

## Security, Cost, And Trust Boundaries

- Only trusted `main` schedule/manual runs may use provider secrets.
- Pull requests, forks, and ordinary pushes never receive provider secrets.
- No automatic retry; use one serialized run and explicit wall-clock/token/cost
  budgets already supported by the eval runner.
- Pages publication uses least-privilege contents/pages permissions and a
  trusted branch/environment. Publication failure is visible and does not
  alter canonical eval outcomes.
- Opik remains post-processing. CI uploads its existing sanitized receipt or
  payload; a trusted local/maintenance job may run `opik-project` later.

## Implementation Order

### Phase 1: Contract And Fixture Proof

1. Confirm existing suite output fields and define `showcase-summary-v1` from
   them without a new grading owner.
2. Add fixture tests for passed, failed, blocked, partial, malformed/private
   fields, duplicate run ids, and latest-success preservation.
3. Add a manifest fixture and verify every referenced suite resolves through
   the canonical `just agent::eval`/package CLI path.

### Phase 2: Advisory Showcase Workflow

1. Add `.github/workflows/showcase.yml` with weekly and manual triggers,
   concurrency 1, bounded timeout, and trusted-branch secret conditions.
2. Run the manifest rows using existing suite commands; upload canonical
   artifacts and the sanitized summary.
3. Keep Opik projection fail-open and non-blocking; do not add CI-only Opik
   credentials or a new projection schema.

### Phase 3: Thin Latest Publication And Docs

1. Publish one latest static projection from the summary, preserving the last
   successful pointer when the current attempt fails or blocks.
2. Update README, `docs/human/contributing.md`, `docs/human/ut_ci_design.md`,
   and `docs/human/local-runtime.md` to describe the active showcase and the
   frozen historical archive accurately.
3. Add links to the current Actions workflow/artifact and Opik review guidance;
   remove wording that claims every main push regenerates the old site.

## Acceptance Criteria

- Existing required CI remains deterministic and unchanged in merge semantics.
- A manual showcase run can be reproduced from its manifest and produces a
  sanitized summary plus canonical source artifacts.
- Weekly/manual runs are serialized, bounded, non-retrying, and advisory.
- Provider secrets are unavailable to PR/fork paths and are never included in
  published artifacts.
- Passed, failed, and blocked capability outcomes remain distinct; an
  unavailable provider/runtime is represented as a blocked row with an
  explicit unavailable reason.
- A failed run cannot replace the last successful published evidence.
- Pages/Markdown render only the canonical summary; no new scoring logic exists.
- Opik outage does not fail or mutate the source result.
- README and CI docs no longer imply that the frozen historical site updates.

## Verification

```bash
just agent::verify
./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals tests/contract
```

Additional focused proof must cover summary privacy/schema, publication
atomicity, latest-success behavior, manifest routing, workflow YAML validation,
and a trusted-branch negative test for provider secrets. A real live provider
showcase is a separate operator-authorized proof after deterministic fixture
gates pass; it is not required to approve this plan.

## Stop Gates And Implementation Defaults

- Stop before implementation if a summary would require private evaluator truth
  or a second metrics owner.
- Stop before CI-to-Opik direct ingestion unless an ADR explicitly changes the
  loopback-only deployment, authentication, retention, and privacy contract.
- Stop before adding historical retention or provider comparisons unless a
  named consumer and retention budget are approved.
- Implementation defaults still open: exact Pages hosting mechanism, summary
  filename, schedule time, and the initial provider profile for manual live
  runs. Choose these in preflight without changing the public/private boundary.

## Planning Loop Findings

The 2026-08-26 bounded planning loop ran an independent entropy scout and a
docs-grounded grill scout. The entropy pass found no competing architecture;
the plan remains the smallest credible shape. The grill pass found four
durable decisions that must be answered before preflight because they change a
public status contract, recurring spend, or durable publication ownership:

1. **Last-success granularity (recommended):** track last successful evidence
   independently per capability row, while one manifest-level snapshot records
   the latest attempt. A mixed attempt is never globally successful.
2. **Schedule cost (recommended):** weekly runs are deterministic-only;
   provider-backed execution is manual dispatch only with an explicit
   `live_execution=run` input and supported provider profile. The scheduled
   open-ended row is recorded as `blocked` without provider access.
3. **Durable pointer owner (recommended):** Pages stores the sanitized summary
   and the public projection needed for the last-success view. Actions artifacts
   are temporary drilldown only, and expired links must be shown as unavailable
   rather than promised indefinitely.
4. **Status vocabulary (recommended):** capability rows use `passed`, `failed`,
   or `blocked`; `unavailable` is a reason/failure class under `blocked`, and
   `partial` is reserved for an incomplete attempt envelope, never a fourth
   capability outcome.

The following proof gaps are accepted as Phase 1 work once the four decisions
are resolved: manifest digest in every summary; recursive privacy rejection;
fork/PR/push/schedule/manual secret guards; workflow permissions, timeout,
concurrency, and no-retry validation; atomic latest-success transitions;
expired artifact handling; and a fixture publication rehearsal for passed,
failed, blocked, and partial attempts. Map-build must either prove runner
asset readiness or publish an honest blocked row; it must not silently switch
capabilities.

The user approved all four recommendations on 2026-08-26. These are now plan
decisions, not open questions. No CI, Opik, Pages, or report code has been
changed.

Planning loop state: **converged**. A fresh saturation audit found no remaining
product, trust-boundary, cost, public-contract, or phase-order question. The
remaining items are implementation defaults or focused proof cases and belong
in preflight.

## Next Action

Route this approved plan to `$intuitive-preflight`, then execute the whole plan
through `$intuitive-flow`. Preflight must choose only the listed implementation
defaults and preserve the accepted boundaries.
