---
plan_scope: observability-decision-report
status: COMPLETE
created: 2026-08-18
last_reviewed: 2026-08-19
implementation_allowed: true
current_phase: complete
source:
  - user request to predefine recurring observability views for model comparison and troubleshooting
  - user request to run agent-planning-loop before implementation
related_context:
  - STATUS.md
  - ARCHITECTURE.md
  - docs/human/evaluation.md
  - docs/human/eval-harness-dimensions.md
  - docs/adr/0135-use-sanitized-report-performance-artifacts-for-speed-claims.md
  - docs/adr/0149-project-agent-observability-as-one-way-side-effects.md
  - docs/plans/2026-08-06-self-hosted-agent-observability-platform.md
  - docs/plans/2026-08-10-phoenix-information-architecture-simplification.md
approval:
  plan_approved_on: 2026-08-19
  plan_approval_source: user said "LGTM, go ahead for the preflight"
  preflight_status: APPROVED
  preflight_approval_source: user objective "execute docs/plans/2026-08-18-observability-decision-report.md with intuitive-flow"
---

# Eval Harness Observability Decision Report

## Plan Ledger

- Plan status: COMPLETE; implementation, requirement-by-requirement acceptance audit, artifact
  regeneration, product/live proof, browser review, and repository gates pass.
- Session scope: predefined recurring comparison and troubleshooting views derived from terminal
  Eval Harness evidence.
- Current slice: complete.
- Next action: use the generated decision section for future terminal candidates; baseline
  publication remains a separate human decision.
- Blocked on: nothing.
- Do not touch from this planning session: product/runtime behavior, provider routes, eval samples
  or graders, Phoenix storage or information architecture, accepted baselines, promotion policy,
  private-evaluation boundaries, CloudML placement, simulator behavior, or hardware.
- Stop condition: one canonical report owner, comparison eligibility, missing-data behavior,
  aggregation grain, privacy/drilldown rules, acceptance criteria, and verification are explicit;
  remaining layout choices are implementation defaults.

## Goal

Turn the existing terminal Eval Harness report into the recurring maintainer decision surface for:

1. capability health and regressions;
2. fair model/provider comparison; and
3. failure and stall triage.

The report must remove repeated manual joins across harness manifests, eval bundles, performance
packets, and Phoenix filters without creating a second dashboard service or weakening the existing
quality, privacy, fail-open, and human-only promotion contracts.

```text
Terminal Eval Harness manifest
  + linked eval_results.json
  + linked run artifacts / model_call_metrics.jsonl
  + explicit prior-baseline references
  + phoenix_projection.json receipts
                         |
                         v
        pure observability decision projection
                         |
                         v
  eval_harness.json + eval_harness.md + eval_harness.html
                         |
             thin local companion viewer / Phoenix drilldown
```

Phoenix remains the generic Agent/LLM/Tool trace and Experiment browser. It is not the metric,
cohort, quality-policy, private-evidence, or promotion owner.

## Demand And Current Evidence

The new derived section passes the demand gate because maintainers currently need to rediscover and
manually apply rules that already exist across several owners:

- `eval_harness.json` owns selected-row outcome, prior-baseline references, execution placement,
  and latency-comparability evidence.
- `eval_results.json` owns versioned suite/sample/trial identity, `pass@k`, `pass^k`, grader output,
  failure class, wall time, model attempts, trajectory, and tool counts.
- `roboclaws_report_performance_metrics_v1` and `model_call_metrics.jsonl` own sanitized model work,
  token/cache/reasoning availability, observed model time, and residual timing.
- `phoenix_projection.json` owns the local-to-Phoenix Dataset, Experiment, EvalTrial run, and score
  references.

The current candidate at `output/eval-harness/20260817T072338Z/` is the acceptance fixture because
it contains the required hard cases:

- 27 passed harness rows, one failed row, and one blocked row;
- one `harness_bug_unclassified` session regression;
- one `environment_blocked` trial after a 180-second model-call stall;
- peak concurrency of eight and explicit `not_comparable_under_concurrent_execution` latency;
- complete model duration/token coverage for Codex 77/77, MiMo 74/74, and MiniMax 62/62, but
  Kimi 0/19;
- ready Phoenix mappings alongside disabled/unavailable-compatible local artifacts.

Phoenix Experiment `0.00ms` is not runtime evidence. The projector currently records projection
time as both Experiment Run start and end; all runtime timing in this report must come from local
canonical artifacts.

## Decisions

### One Existing Report Surface

Extend the existing `eval_harness.json`, `eval_harness.md`, and `eval_harness.html`. Do not add a
new metric owner, database, or scheduler. The existing report server may serve a
thin local companion viewer over finalized Eval Harness artifacts.

`eval_harness.json` retains `schema=roboclaws_eval_harness_manifest_v1` and gains one nested object:

```json
{
  "observability_decision_report": {
    "schema": "roboclaws_observability_decision_report_v1",
    "state": "ready|ready_with_limitations|not_applicable"
  }
}
```

The implementation adds one pure owner, preferably
`roboclaws/evals/observability_decision_report.py`, for artifact resolution, normalized rows,
comparison eligibility, coverage, aggregation, and render-ready view data. The existing Eval
Harness output owner keeps orchestration and writes the three existing report files.

An internal callable may rebuild the derived section and the same three report files for one
explicitly named terminal manifest. It is used by collection, tests, and bounded repair; it is not
a new `just` or public CLI surface and must never scan for arbitrary historical roots.

### Authoritative Finalization

- `recommend` manifests, nonterminal manifests, and individual CloudML worker shard manifests emit
  `state=not_applicable` with a sanitized reason and no rankings.
- A terminal local execution manifest, including an explicitly scoped execution, may build the
  report for its selected rows.
- A merged local/CloudML collection builds the report only after accepted results have been
  relocated and the authoritative combined manifest is finalized locally.
- Missing optional telemetry yields `ready_with_limitations` and blocks the affected claim only.
- A malformed declared canonical artifact, schema/digest mismatch, or contradictory identity fails
  report finalization with an actionable error without rewriting recorded row outcomes.
- Phoenix disabled or unavailable only reduces Phoenix drilldown coverage; it does not change the
  report's local metrics or eval outcome.

### Aggregation Grain

Use distinct grains and never combine their totals:

| View | Grain | Rule |
| --- | --- | --- |
| Harness health | one selected harness row | Reproduces harness-level passed/failed/blocked totals. |
| Capability health | EvalTrial and sample aggregate | Owns trial status, `pass@k`, `pass^k`, grader and domain metrics. |
| Triage | `(row_id, suite_id, sample_id, trial_id)` | Uses a row-only record when no eval result bundle exists. |
| Model work | sanitized model call within one EvalTrial | Aggregates only inside an eligible comparison cohort. |

A failed suite row and its failed EvalTrial must not be counted twice in any one total. Trace-only
specialists such as Operator Session remain visible as row-level operational evidence and are not
coerced into repo-suite aggregates.

### Artifact Resolution

Resolve evidence from the authoritative harness-attached artifacts and stable identity, not list
order or embedded worker paths.

- Bind eval and Phoenix rows by `(row_id, suite_id, sample_id, trial_id)`.
- Resolve collected run artifacts relative to the accepted collected bundle, including
  bundle-relative `runs/...` paths.
- Never probe arbitrary absolute paths from an artifact payload.
- Never emit stale worker-local paths such as `/tmp/roboclaws-cloudml/...`.
- Treat unresolved optional artifacts as explicit coverage gaps; treat contradictory declared
  canonical identity as a finalization error.

### Comparison Modes

Quality regression and provider comparison answer different questions and use separate eligibility
rules.

1. **Code/baseline regression mode** may intentionally compare different Git SHAs, but only through
   the explicit prior-baseline references already attached to the harness manifest.
2. **Provider treatment mode** varies exactly `(provider_profile, model, wire_api)` while holding
   the comparison invariants fixed. It never auto-selects a latest run or baseline.

The provider comparison invariants are:

- exact Dataset content/version, suite version, sample version and sample ID;
- repetition and seed policy;
- agent engine, prompt source Git SHA, Skill name/digest, and rendered-prompt identity when present;
- surface, intent, preset, world/scene, backend, evidence lane, camera labeler, scenario setup, Tool
  surface, and runtime-prior digest when applicable;
- execution target, hardware/runtime envelope, network scope, and concurrency evidence required by
  the claim.

Do not weaken `roboclaws_report_performance_comparison_v1`, which correctly rejects provider/model
changes for its same-identity baseline/candidate problem. Add a dedicated cohort classifier for
the provider-treatment problem.

### Claim Eligibility

One cohort does not have one global comparable flag. Record state and reasons independently for:

- `quality`;
- `model_work`; and
- `latency`.

Each claim uses `eligible`, `diagnostic_only`, or `incomparable`.

- Quality eligibility precedes all speed or work ranking.
- Failed, blocked, inconclusive, operator-stopped, harness, environment, and provider outcomes keep
  their existing classifications. Do not infer root cause from elapsed time.
- Faster-but-worse is rejected unless an existing explicit quality waiver applies.
- Token/call work can remain descriptive while latency is incomparable.
- Latency ranking is suppressed whenever execution placement/runtime differs or concurrent-provider
  evidence is present. A latency baseline uses at most one active row per provider.
- A single run is diagnostic only. Descriptive percentiles may be shown for small `N`, but every
  value shows `N` and claim eligibility; no significance claim is added.
- Cost is not part of v1 because no versioned price source and complete usage contract exists.

Every metric cell carries enough metadata to prevent null-to-zero mistakes:

```text
value
availability = available | partial | unavailable | not_applicable
source
coverage = numerator / denominator
claim_eligibility
limitations
```

## Report Views

### 1. Capability Health And Regression

Answer: did the candidate preserve or improve behavior?

Show:

- harness row passed/failed/blocked totals and candidate publication state;
- suite/sample/trial `pass@1`, `pass@k`, and `pass^k`;
- explicit current-vs-prior baseline row regressions;
- failure classes and checker/grader status;
- slices by suite, sample, provider route, world/scene, intent, evidence lane, and Skill delivery;
- direct links to the authoritative local row, eval bundle, EvalTrial, and run artifacts.

This view leads the report and is the eligibility gate for performance claims.

### 2. Fair Provider Comparison

Answer: among quality-eligible evidence, which route did less model work or completed faster under
actually comparable conditions?

Show:

- treatment tuple and the fixed cohort identity;
- per-claim eligibility and reasons;
- end-to-end wall time and observed model time with descriptive P50/P95 and `N` when present;
- model-call and MCP Tool-call counts;
- input, uncached input, cached input, output, and reasoning tokens with coverage;
- model duration/token availability by provider;
- same-or-better quality result before any speed label.

If no fair latency cohort exists, the successful result is an explicit `incomparable` state, not an
empty or forced ranking.

### 3. Failure And Stall Triage

Answer: what failed, where did time stop progressing, and who owns the next investigation?

Show:

- row/trial outcome, existing failure class, terminal reason, live phase, and execution target;
- model attempt success/failure counts, longest observed model call, timeout-budget breach, retry,
  continuation, and provider reason when sanitized and available;
- first relevant evidence and first actionable-object discovery time;
- failed/no-op Tool count and Tool breakdown;
- local run/report/trace links and ready Phoenix Experiment Run/Trace drilldown;
- explicit artifact/telemetry limitations.

Do not create a second failure taxonomy or turn an environment/harness failure into a model-quality
regression.

### Supporting Detail

Keep these as secondary sections or row drilldowns, not separate dashboard products:

- trajectory efficiency: Tool calls, repeated observe/navigation, first-evidence timing, model
  attempts, retries, and continuations already present in canonical artifacts;
- Tool/backend health: available Tool counts, handler timing, readiness, sidecar, backend, and scene
  evidence without inventing a cross-backend SLO;
- telemetry quality: a persistent banner with separate coverage for eval bundle, run artifacts,
  model duration, token usage, Phoenix mapping, and trace linkage.

Do not invent productive-action ratios, semantic-redundancy scores, percentile alert thresholds, or
new Tool-latency contracts in this plan.

## Privacy And Drilldown

- Generate metrics only from the existing sanitized/public report contracts.
- Never inline raw Trace records, prompts/model text, function inputs/outputs, Tool payload bodies,
  credentials, provider endpoints, private evaluator truth, generated mess identity, acceptable
  destinations, holdout identity, raw images, or maps.
- Apply harness redaction after the derived section is built and add denial tests over JSON,
  Markdown, and HTML.
- Link local evidence using stable relative artifact identity.
- When a projection receipt is `ready`, link the matching Phoenix EvalTrial run by stable trial
  identity. When disabled/unavailable, show that state and retain local drilldown.
- Preserve the recorded Phoenix mapping URL. Do not add another endpoint setting or rewrite origins
  for trusted-LAN browsing in this plan.

## Review Cadence

The report is generated automatically, not scheduled:

- review after every terminal candidate and before any baseline/promotion decision;
- review failure/stall and telemetry sections during active debugging;
- review provider and trajectory sections weekly during an active eval campaign;
- use the explicit `baseline-refresh` profile for a release/nightly four-provider matrix, without
  turning that profile into an always-on cron job.

External alerts, email/chat delivery, background polling, rolling time-series storage, and shared
hosted publication remain out of scope.

## Implementation Phases

### Phase 1: Contract And Fixtures

- Add compact sanitized fixtures for terminal local, merged collected, recommend, nonterminal,
  shard, missing optional telemetry, malformed declared artifact, Phoenix disabled, and path-rebased
  cases.
- Define `roboclaws_observability_decision_report_v1`, report states, per-cell availability,
  per-claim eligibility, aggregation grains, and sanitized reasons.
- Define the provider-treatment cohort tuple and invariant fields without changing the existing
  same-identity performance comparator.
- Encode privacy denials and stable trial-based local/Phoenix link resolution.

Gate: fixture review proves the schema cannot imply a quality, model-work, latency, or cost claim
when its required evidence is absent or incomparable.

### Phase 2: Pure Artifact Projection

- Implement the pure report builder under `roboclaws.evals`.
- Read only the explicit terminal manifest, its attached eval bundles, run artifacts, performance
  packets/model-call rows, explicit baseline references, and adjacent projection receipts.
- Normalize local and collected artifact paths without arbitrary filesystem probing.
- Build harness health, capability/sample aggregates, triage rows, provider cohorts, metric coverage,
  and per-claim eligibility.
- Reuse current eval aggregation and performance extraction where their contracts match; do not
  duplicate grader or performance parsing.
- Return deterministic render-ready data without network calls or file writes.

Gate: focused tests reproduce the acceptance fixture and classify every unavailable or
incomparable value explicitly.

### Phase 3: Harness Integration And Rendering

- Invoke the builder from authoritative terminal local and merged collection finalization.
- Keep recommend, nonterminal, and worker shard reports `not_applicable`.
- Add the nested object before harness redaction and render the same data into existing Markdown and
  static HTML.
- Add dense, scannable quality, provider, triage, supporting-detail, and telemetry-coverage sections.
- Preserve existing row tables and commands; do not add a second report lifecycle.
- Update `skills/cloudml-eval-ops/SKILL.md` only as needed to require the same package-owned builder
  after verified collection and path relocation.
- Provide the internal single-manifest regeneration callable used by collection, tests, and one
  explicitly named artifact repair.

Gate: equivalent terminal local and merged collected evidence produces semantically identical
decision sections; unchanged regeneration is deterministic and idempotent.

### Phase 4: Documentation And Verification

- Update `ARCHITECTURE.md` to name the derived report under the existing eval-maintainer layer.
- Update `docs/human/evaluation.md` with the three-view mental model, claim-eligibility rules,
  cadence, and Phoenix drilldown boundary.
- Update `docs/human/eval-harness-dimensions.md` only if report slices need a concise pointer; do not
  duplicate catalog membership.
- Do not update the robotics domain glossary; this plan adds no robotics domain term.
- Run focused deterministic, privacy, path-relocation, report-rendering, and artifact-only
  regeneration proofs.
- Regenerate the derived section for the explicitly named `20260817T072338Z` fixture without
  provider, Phoenix API, simulator, CloudML submission, or hardware execution.

Gate: human docs describe what the generated report actually shows, and all verification below
passes or records a concrete required-live/preflight blocker.

## Acceptance Criteria

- Existing `eval_harness.{json,md,html}` remains the only metric/report surface; the existing
  stdlib report server may expose finalized runs through a thin local companion view, without
  re-aggregating metrics or adding a database/scheduler.
- Terminal authoritative manifests contain `roboclaws_observability_decision_report_v1`; recommend,
  nonterminal, and shard manifests are explicitly `not_applicable`.
- The current fixture reports harness health as 27 passed, one failed, and one blocked without
  double counting suite rows and EvalTrials.
- It identifies the session regression and the dynamic-full 180-second model stall under their
  existing failure owners.
- Its latency claim is `incomparable` because peak concurrency is eight; no provider latency ranking
  is rendered.
- Model-call coverage remains exact: Codex 77/77, MiMo 74/74, MiniMax 62/62, and Kimi 0/19. Kimi
  values remain null/unavailable rather than zero.
- Phoenix Experiment `0.00ms` is never read as runtime latency.
- A serial synthetic fixture proves quality, model-work, and latency eligibility can differ inside
  one cohort.
- A collected fixture rebases worker-local artifact paths, resolves rows by stable identity, and
  emits no `/tmp/roboclaws-cloudml` path.
- Failed, blocked, inconclusive, operator-stopped, harness, environment, and provider outcomes stay
  distinct; only quality-eligible passed evidence can receive a speed label.
- Every metric exposes source, availability, coverage, and claim eligibility. Missing values never
  become zero, and cost is absent rather than estimated.
- Local artifact drilldown works with Phoenix disabled; ready projection receipts add the correct
  trial-linked Phoenix run without becoming metric input.
- JSON, Markdown, HTML, and Phoenix-bound references contain zero forbidden private fields or raw
  sensitive values.
- Rebuilding unchanged inputs yields byte-stable normalized JSON and equivalent Markdown/HTML.
- Report generation performs no provider, Phoenix API, simulator, CloudML submission, or hardware
  action.
- Existing eval outcomes, canonical artifacts, promotion decisions, provider selection, and
  fail-open telemetry behavior do not change.

## Verification

Planning-stage selection:

```bash
just agent::eval recommend \
  plan=docs/plans/2026-08-18-observability-decision-report.md \
  budget=focused
```

Focused implementation checks:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/evals/test_observability_decision_report.py \
  tests/unit/evals/test_eval_harness_manifest.py \
  tests/unit/evals/test_eval_reports.py \
  tests/unit/reports/test_live_performance.py \
  tests/unit/evals/test_phoenix_projection.py
```

Artifact-only proof matrix:

| Proof | Expected result |
| --- | --- |
| compact terminal local fixture | full report, correct grains and quality-first ordering |
| compact merged collected fixture | worker paths rebased; semantic parity with local evidence |
| recommend/nonterminal/shard fixtures | `not_applicable`; no ranking |
| missing optional model telemetry | `ready_with_limitations`; local quality remains available |
| malformed declared canonical artifact | finalization error; recorded row outcome unchanged |
| concurrent provider fixture | latency `incomparable`; quality/model work classified separately |
| serial provider fixture | independently eligible quality/model-work/latency claims |
| Phoenix disabled/unavailable | local report complete; Phoenix coverage explicitly degraded |
| unchanged regeneration | deterministic normalized JSON and equivalent Markdown/HTML |
| privacy/path fixtures | zero forbidden fields, endpoints, raw payloads, or worker absolute paths |
| `20260817T072338Z` regeneration | exact 27/1/1, stall, concurrency, and provider coverage evidence |

Because this changes the Eval Harness report, run the plan-aware selector and its relevant
deterministic/preflight proof. The report contract itself requires no new live provider call. If the
selector marks a live row as required, run the documented readiness/preflight and either execute the
required row under the repo live-verification policy or record the concrete blocker; do not silently
substitute deterministic evidence.

## Risks And Stop Gates

| Risk | Mitigation / stop gate |
| --- | --- |
| A polished table creates false speed confidence | Quality first, independent claim eligibility, `N`/coverage, and explicit `incomparable`. |
| Current provider matrix has no fair latency cohort | Treat no eligible cohort as a valid result; do not relax placement or concurrency invariants. |
| Collected artifacts retain worker paths | Resolve from accepted collected roots and stable identity; deny worker absolute paths. |
| Optional telemetry is uneven by provider | `ready_with_limitations`; null is never zero. |
| Derived report starts controlling eval or promotion | Stop. It is read-only evidence and cannot change outcomes or authorize publication. |
| Implementation needs a Phoenix query at render time | Stop. Consume only local projection receipts. |
| Cost comparison requires pricing assumptions | Stop and request a separate versioned pricing/usage decision. |
| Work needs a new service, scheduler, alert channel, shared store, or public command | Stop and request explicit scope/operational ownership. |
| Implementation changes ADR-0135 or ADR-0149 policy | Stop and review the durable decision separately. |
| Broad historical backfill or Phoenix data mutation becomes necessary | Stop. Only explicitly named artifact-only regeneration is in scope. |

## Alternatives

### Six Independent Dashboards

Rejected. Separate quality, provider, failure, trajectory, Tool/backend, and telemetry products
would duplicate filters, links, report ownership, tests, and navigation. Three primary views plus
supporting detail answer the current recurring decisions with less surface.

### New `observability-report` Command And Separate Artifacts

Rejected. Automatic terminal finalization and one internal regeneration callable provide the needed
artifact-only behavior. A public command would add input selection, help/Just grammar, docs,
contract tests, and a second report lifecycle without unlocking new data.

Revisit only if maintainers later need arbitrary ad hoc cross-root cohort composition not owned by
one terminal harness manifest and its explicit baseline references.

### Phoenix As Canonical Dashboard Query Owner

Rejected. Phoenix cannot enforce local quality policy, private/domain evidence, artifact replay,
fair execution cohorts, or promotion. Its Experiment duration is not execution timing. Keep it as
generic browsing and drilldown.

### Grafana, Langfuse, Or Another Analytics Service

Rejected for this scope. A new platform would not remove Roboclaws-specific cohort, quality,
privacy, and failure-ownership rules and would add another service/store before the existing
artifacts have been projected into one useful decision surface.

### Continue With Manual Filters Only

Rejected. The current candidate already demonstrates recurring manual joins and false-confidence
risk around concurrency, missing Kimi telemetry, and Phoenix zero-duration Experiment runs.

## Parked Work

- Cost ranking until a versioned price source and sufficient provider usage coverage exist.
- External alerts, email/chat delivery, cron/nightly scheduling, and rolling time-series storage.
- Shared hosted dashboard publication or shared Phoenix ownership.
- Productive-action ratio and semantic-redundancy scoring.
- New cross-backend Tool latency/error SLOs.
- Dataset difficulty heatmaps.
- Phoenix Experiment timestamp rewriting.
- Trusted-LAN Phoenix-link origin rewriting or a second endpoint setting.
- Bulk historical backfill or directory-wide artifact discovery.

## Completion Evidence

- Focused contract gate: 67 tests passed across observability projection, harness manifest/report,
  live performance, and Phoenix projection coverage, including expanded cohort invariants and
  bundle/model-call/Phoenix identity contradiction checks.
- Repository gate: `just agent::verify` passed lint, format, quality ratchet, architecture graph,
  broad tests, and contract checks.
- Acceptance replay: `output/eval-harness/20260817T072338Z/` regenerated artifact-only with exact
  27 passed / one failed / one blocked harness health, the existing session failure owner, the
  180-second environment-owned model-call stall, concurrency-eight latency rejection, and model
  duration coverage Codex 77/77, MiMo 74/74, MiniMax 62/62, Kimi 0/19.
- Product gate: `output/eval-harness/20260819T114325Z/` passed the scoped smoke-regression suite and
  generated a terminal `ready` decision section.
- Plan-aware selector: `output/eval-harness/20260819T113047Z/` passed 17 of 21 required rows,
  including six live-agent rows, Grounding DINO, and local simulator products. Four provider
  treatment rows recorded the actionable missing-prior blocker.
- Provider repair attempt: `output/eval-harness/20260819T135540Z/` reran exactly those four rows
  serially against the existing immutable prior; all four providers and all eight EvalTrials passed.
- Static HTML review: the acceptance report rendered at 1440x900 and 375x812 with no console
  errors, page overflow, overlap, forbidden private fields, or stale CloudML worker paths.

## Planning Loop Ledger

### Charter

- Goal: one implementation-ready plan for recurring model comparison and troubleshooting views.
- Non-goals: implementation, platform migration, live execution, baseline publication, promotion,
  runtime/control changes, new privacy surface, scheduler, or shared service.
- Worker actions: read-only inspection of canonical docs, report/projection code, and representative
  persisted artifacts.
- User-review gates: any public command/service/store, durable policy change, pricing/cost contract,
  baseline selection/promotion, shared infrastructure, or private-data expansion.
- Stop: scope, non-goals, ownership, contracts, acceptance, verification, and risks are explicit.

### Round 1

Read-only entropy and docs-grill scouts completed.

Accepted:

- dedicated fair-comparison cohort classification without weakening the existing same-identity
  performance comparator;
- one canonical decision report with three primary views;
- metric coverage and statistical honesty as report-wide gates;
- quality-first ranking and preservation of existing failure ownership;
- local canonical artifacts as metric inputs and Phoenix as drilldown only.

Merged:

- trajectory, Tool/backend, and telemetry concerns into supporting detail and a persistent coverage
  banner rather than separate products.

Parked:

- cost, scheduling, external alerts, new service/storage, productivity ratios, dataset heatmaps,
  and new Tool/backend SLO contracts.

Rejected:

- six independent dashboards, Phoenix-owned aggregation, Phoenix Experiment duration as runtime
  evidence, and a second observability platform.

### Round 2

Round 2 narrowed the only material disagreement: extend the existing harness report or add a new
command/artifact lifecycle. Both scouts selected the existing report surface.

Accepted corrections:

- classify quality, model-work, and latency claims independently;
- use `(provider_profile, model, wire_api)` as the treatment tuple;
- define distinct harness, EvalTrial/sample, triage, and model-call grains;
- resolve collected artifacts by stable identity and accepted collected roots, never worker paths;
- make recommend/nonterminal/shard reports `not_applicable` and authoritative terminal reports the
  only full decision surface.

Rejected:

- a new public `observability-report` command and separate JSON/HTML artifacts.

Round 3 was not run. After the Round 2 corrections, both selection scans are saturated; remaining
questions concern local rendering and module layout only.

The plan-aware recommendation succeeded at
`output/eval-harness/20260818T105725Z/eval_harness.json`. It selected 21 potential focused rows,
including 10 live-agent rows, and executed none. Whole-plan preflight must reconcile that
recommendation with the artifact-only report contract and the repo live-verification policy; it may
use the documented readiness/preflight path, but it must not silently ignore a row that remains
required after the implementation diff exists.

Planning-loop status: complete; the whole plan was approved on 2026-08-19.

## Preflight Contract

Preflight status: APPROVED

Task source: approved `agent-planning-loop` plan plus the user's 2026-08-19 preflight request

Canonical source: `docs/plans/2026-08-18-observability-decision-report.md`

Route: durable `intuitive-flow`

Goal: Extend the existing terminal Eval Harness report with one artifact-derived, quality-first
decision section for capability health, fair provider comparison, and failure/stall triage while
preserving canonical local evidence and Phoenix-only drilldown.

Scope:

- Execute all four implementation phases in this plan; Phase 1 is the starting point, not the
  approved scope boundary.
- Define `roboclaws_observability_decision_report_v1`, availability and per-claim eligibility, the
  provider-treatment cohort, aggregation grains, sanitized reason values, and stable drilldown
  identity.
- Add one pure artifact projection owner under `roboclaws.evals`; integrate it into authoritative
  local and merged-collection finalization and the existing JSON/Markdown/HTML renderers.
- Add the internal one-manifest regeneration path, compact local/collected/privacy fixtures, and
  exact artifact-only proof against `output/eval-harness/20260817T072338Z/`.
- Update the current architecture/evaluation docs and the CloudML eval-ops skill only where the
  implemented finalization contract requires it.

Non-goals: no new Phoenix frontend or same-origin gateway, new metric owner, database, scheduler, alert
channel, time-series store, pricing/cost model, automatic baseline selection or promotion, broad
historical scan/backfill, Phoenix query or data mutation, provider/runtime behavior change, eval
sample/grader change, CloudML placement change, simulator change, or hardware action.

Entity budget: reuse=`roboclaws_eval_harness_manifest_v1`, `eval_harness.{json,md,html}`,
`eval_results.json`, `roboclaws_report_performance_metrics_v1`, `model_call_metrics.jsonl`, current
eval aggregation/performance extractors, harness redaction, explicit baseline references, and
`phoenix_projection.json`; remove/merge=manual cross-artifact joins and duplicated render-time
classification only, with no existing canonical artifact removed; new=one pure report module, one
nested versioned report schema, and focused fixtures because no existing owner represents a
provider-treatment cohort or the three combined decision views; expansion triggers=any public
command/API, second artifact family, service/store/scheduler, pricing contract, new metric or
failure taxonomy, private-data expansion, automatic promotion, shared infrastructure, broad
backfill, Phoenix mutation/query dependency, or change to ADR-0135/ADR-0149 requires re-approval.

Context: must-read=this plan, `ARCHITECTURE.md`, `docs/human/evaluation.md`,
`docs/human/eval-harness-dimensions.md`, ADR-0135, ADR-0149,
`roboclaws/evals/harness/runner.py`, `roboclaws/evals/harness/local_execution.py`,
`roboclaws/evals/reports.py`, `roboclaws/core/live_performance.py`,
`roboclaws/core/live_performance_comparison.py`, `roboclaws/evals/phoenix_projection.py`, focused
eval/performance/projection tests, and the explicit `20260817T072338Z` evidence root;
useful=`skills/cloudml-eval-ops/SKILL.md`, the 2026-08-06 observability plan, and the 2026-08-10
Phoenix information-architecture plan; avoid-unless-needed=unrelated historical plans,
retrospectives, arbitrary `output/**` roots, provider logs, simulator/backend internals, Eval
Evolution, and real-robot sources.

Acceptance:

- SUCCESS: the existing three Harness artifacts contain the nested v1 section only for
  authoritative terminal finalization; the current fixture reproduces 27/1/1, the session
  regression, the 180-second stall, concurrent-latency rejection, and exact 77/77, 74/74, 62/62,
  and 0/19 coverage without double counting, null-to-zero conversion, worker paths, or Phoenix
  duration input; local/collected finalization, stable links, privacy, idempotent regeneration,
  docs, static HTML review, and all required selector gates pass.
- BLOCKED_NEEDS_DECISION: implementation needs any expansion trigger, changes a durable ADR policy,
  or requires baseline publication/promotion; none is currently expected.
- BLOCKED_NEEDS_LOCAL_VALIDATION: a required plan-aware integration, product-run, live-provider,
  simulator, Phoenix-disabled, collection-path, or browser report proof cannot run or pass in the
  current environment. Code may remain an intermediate branch but is not complete or merge-ready.
- INTERMEDIATE_ONLY: none; no incomplete checkpoint is approved.
- No regressions: eval row outcomes, canonical artifacts, same-or-better policy, failure ownership,
  provider selection/placement, CloudML receipts, Phoenix fail-open/one-way behavior, privacy
  denials, promotion authority, existing Harness command grammar, and existing row tables/links.

Verification: deterministic=`ruff check .`; `ruff format --check .`;
`./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals/test_observability_decision_report.py
tests/unit/evals/test_eval_harness_manifest.py tests/unit/evals/test_eval_reports.py
tests/unit/reports/test_live_performance.py tests/unit/evals/test_phoenix_projection.py`;
integration=run the compact local/merged/recommend/nonterminal/shard/path/privacy fixture matrix,
regenerate the explicit `20260817T072338Z` report artifact-only, verify normalized output stability,
then run `just agent::eval recommend plan=docs/plans/2026-08-18-observability-decision-report.md
budget=focused` and `just agent::verify`; product-run=`just agent::eval execute
plan=docs/plans/2026-08-18-observability-decision-report.md budget=focused
row_id=smoke-regression-eval-suite max_parallel=1` must produce a terminal static report with the
new section and working local drilldown; local-live-manual=after implementation, record the base
commit, run `just agent::eval recommend since=<base-commit> budget=focused`, execute every row that
the final selector still marks required under documented placement/readiness and zero unplanned
retries, and inspect the generated HTML at desktop and mobile widths for the three decision views,
coverage banner, non-overlap, readable tables, and correct local/Phoenix links. A failed readiness
or required live gate is recorded as `BLOCKED_NEEDS_LOCAL_VALIDATION`, not replaced by artifact-only
tests; optional=read-only comparison with the LAN Phoenix UI and broader historical regeneration,
without publishing or mutating Phoenix/baseline data.

Execution: main=root session owns the root goal, implementation order, integration, selector
reconciliation, required live/preflight gates, HTML inspection, diff review, scoped commits, and
final complete/blocked judgment; worker=none by default because the report contract and renderers
share one ownership boundary; worker-goal=none.

To execute: `/goal execute docs/plans/2026-08-18-observability-decision-report.md with intuitive-flow`

Optional tracking: none

Approval: `LGTM`, `approve`, or `go ahead` approves this preflight; edits request revision.
