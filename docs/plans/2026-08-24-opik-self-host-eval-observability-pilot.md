---
plan_scope: opik-self-host-eval-observability-pilot
status: DRAFT
created: 2026-08-24
last_reviewed: 2026-08-24
implementation_allowed: false
current_phase: awaiting-plan-approval
source:
  - user request to try Opik self-host after observability platform research
  - user request to run agent-planning-loop before implementation
related_context:
  - STATUS.md
  - ARCHITECTURE.md
  - docs/adr/0149-project-agent-observability-as-one-way-side-effects.md
  - docs/plans/2026-08-06-self-hosted-agent-observability-platform.md
  - docs/plans/2026-08-18-observability-decision-report.md
approval:
  plan_approved_on: null
  plan_approval_source: null
  preflight_status: DRAFT
---

# Opik Self-Hosted Eval Observability Pilot

## Plan Ledger

- Plan status: DRAFT; agent planning loop and preflight shaping are complete, implementation is
  not approved.
- Current slice: one isolated, artifact-only Opik self-host pilot over the historical terminal
  candidate at `output/eval-harness/20260817T072338Z/eval_harness.json`.
- Next action: human reviews this plan, then approves or revises the preflight contract.
- Blocked on: plan approval only.
- Stop condition: the pilot produces enough browser and operational evidence to choose `retain
  Phoenix`, `migrate to Opik`, or `reject Opik`. It does not perform that migration.

## Goal

Determine whether a local single-user Opik deployment provides a materially better recurring eval
experience than the current Phoenix plus companion-report arrangement for:

1. capability and provider comparison;
2. eligibility, failure ownership, and telemetry coverage inspection; and
3. experiment-to-trace drilldown.

The proof uses one already-completed candidate. It executes no eval, agent, model, provider, or
simulator work.

```text
named terminal candidate + attached sanitized artifacts
                         |
                         v
        one-shot allowlist projector + receipt
                         |
                         v
   isolated loopback Opik project / experiments / traces
                         |
                         v
 browser review + footprint report + migration decision
```

Local Eval Harness artifacts and `roboclaws_observability_decision_report_v1` remain canonical.
Opik is a diagnostic projection and never controls execution, scoring, eligibility, publication,
or promotion.

## Fixed Source And Truth Boundary

The only source root is:

`output/eval-harness/20260817T072338Z/eval_harness.json`

It is a completed but unaccepted historical candidate, not a published baseline. The projector
must record `projection_purpose=historical_candidate_projection` and
`candidate_status=unaccepted`. Projection does not create a completion marker, publish a baseline,
or change any source artifact.

Input resolution is closed:

- read the named manifest and only relative artifacts explicitly attached to it;
- validate schemas, identities, paths, and available digests before network writes;
- reject traversal, undeclared inputs, contradictory identity, and malformed required artifacts;
- never use Phoenix, its database, or the report server as an input source;
- construct outbound payloads from an explicit field allowlist rather than serializing then
  redacting source objects.

## Product Decisions

### Pilot, Not A Runtime Adapter

Use a task-owned maintainer projector, not a new production telemetry abstraction. Do not add Opik
to automatic eval finalization, `ExperimentTelemetry`, provider/runtime paths, `pyproject.toml`, or
the public launch-axis grammar. Promotion into `roboclaws.evals` requires a later migration
decision.

The pilot may add one explicit maintainer command for repeatability, scoped to one caller-supplied
terminal manifest. It must never scan historical output roots.

### Copy Policy; Do Not Recompute It

`observability_decision_report` is the sole source for final capability, provider, eligibility,
failure, and coverage facts.

- Numeric or Boolean facts may be copied to `roboclaws.*` feedback scores only when present and
  available in the canonical report.
- Categorical state, reason, limitation, failure owner/class, coverage state, and publication state
  remain namespaced metadata.
- Missing values remain unavailable, never zero.
- No Opik evaluator, online rule, judge, query, widget, or importer code may derive cohorts,
  eligibility, pass rates, rankings, failure ownership, or publication status.

### Honest Trace Coverage

The source contains preserved sanitized SDK span hierarchies for only part of the candidate. The
pilot defines two trace fidelity classes:

- `native_span_trace`: project only allowlisted fields from `openai-agents-spans.jsonl`, preserving
  its timestamps, trace/span identity, parentage, kind, and status;
- `experiment_only`: create experiment evidence and record `trace_unavailable`; do not invent a
  trace when no sanitized hierarchy exists.

Raw MCP `trace.jsonl`, prompts, tool bodies, maps, images, private truth, endpoints, credentials,
and absolute paths are forbidden outbound fields. A synthetic event timeline is deliberately
rejected for this pilot because it adds a second interpretation layer without proving native Opik
trace value.

### Diagnostic Opik Views

Create one task-named Opik project, one dataset/experiment grouping, and three explicitly
non-authoritative views:

1. capability health;
2. provider-treatment comparison; and
3. failure and telemetry coverage.

Use dashboards where Opik's documented widget model fits. Use the experiment table and filters for
dimensions that dashboards cannot express. Each view must identify the canonical report and state
that Opik does not own policy. The pilot fails its product-fit gate if answering the target
questions still requires undocumented queries or reimplementing policy in Opik.

### Stable Identity And Receipt

Every projected logical object receives a deterministic projection key derived from the projection
schema, source-manifest digest, row, suite, sample, trial/repetition identity, and attached artifact
digest where applicable. Opik-specific ID constraints must be validated explicitly; display names
are never identity.

The task-owned receipt under `output/opik-poc/<source-digest>/` records:

- projection schema and purpose;
- source path and digest set;
- Opik release/API version and endpoint origin;
- project, dataset, experiment, item, trace, span, score, and dashboard IDs/counts;
- trace-fidelity and unavailable coverage;
- limitations, privacy scan result, and dashboard URLs;
- first-pass and second-pass counts proving idempotency.

Rerunning against the same source must create zero duplicate logical objects or feedback scores and
must preserve receipt identities.

## Deployment Boundary

Create a separate Opik `2.2.36` Compose deployment under `deploy/opik/` using that release's
official local self-host topology. Record the resolved image digests during implementation; do not
silently track `latest` or a moving branch.

- Publish only the Opik frontend/API gateway on `127.0.0.1` at a port disjoint from Phoenix `6006`
  and the companion `6100`; keep database and worker ports internal.
- Use a distinct Compose project, network, and `output/opik-poc/` data root.
- Disable anonymous/external usage telemetry where supported.
- Add explicit health checks, persistence, and bounded resource configuration where the upstream
  topology permits it.
- Do not edit `deploy/phoenix/`, `output/phoenix/`, the companion server, or existing Phoenix
  projection code.
- `compose down` is the rollback. Retain pilot data by default; deleting it needs separate approval.

Because Opik includes multiple backend and storage services, the proof must record image download
size, healthy startup time, idle/peak CPU and RAM, and disk growth after both projection passes.

## Implementation Stages

### Stage 1: Pin And Validate The Isolated Deployment

Add the smallest task-owned deployment surface, an example environment file, and a deterministic
deployment validator. Prove rendered Compose configuration, loopback-only publication, isolated
network/storage, pinned images, health, persistence, and clean stop/restart before projection work.

Stop if loopback isolation, data ownership, or a repeatable healthy startup cannot be proved.

### Stage 2: Build A Pure Projection Snapshot

Add a pure mapper and fixtures that resolve the exact manifest, copy canonical decision values,
classify trace fidelity, build deterministic identities, and emit only allowlisted payload objects.
The mapper must be testable without Docker or network access.

Stop before network writes if identity, privacy, or canonical-value parity fails.

### Stage 3: Project Through A Thin Maintainer Client

Use documented Opik REST/OTLP surfaces without adding a normal runtime dependency. Perform
read-before-create/upsert as required, create the project/experiment objects and faithful traces,
provision supported dashboards, and write the receipt. Opik unavailability is fail-open with
respect to canonical artifacts but is a failed pilot run.

Run the projection twice and compare IDs and server-side counts.

### Stage 4: Product And Operational Proof

In a browser, verify desktop and mobile layouts and capture evidence for:

- capability filtering and summary;
- provider comparison with incomparability/limitations visible;
- failure owner/class and telemetry-coverage inspection;
- experiment item to a matching faithful trace and span hierarchy;
- clear handling of experiment-only rows with no invented trace.

Record Opik footprint, startup/restart behavior, and isolation. Verify Phoenix and the companion
configuration/artifacts/counts are unchanged.

### Stage 5: Decision Handoff

Write a compact pilot result comparing UX, query/view expressiveness, drilldown fidelity,
repeatability, privacy, and operational cost. End at exactly one recommendation:

- retain Phoenix plus companion;
- migrate the observability projection to Opik in a separately approved plan; or
- reject Opik.

Do not leave Phoenix and Opik as dual production observability systems.

## Expected File Ownership

Exact names may be adjusted during preflight execution only to match established local routing, but
the entity budget may not expand without review.

- `deploy/opik/**`: isolated pinned Compose topology and example configuration.
- `scripts/dev/validate_opik_deployment.sh`: deterministic deployment validation.
- `scripts/reports/project_eval_harness_to_opik.py`: task-local mapper/client and receipt writer.
- `tests/unit/reports/test_project_eval_harness_to_opik.py`: pure mapping, privacy, identity, and
  idempotency tests.
- `tests/integration/test_opik_eval_observability_pilot.py`: live API object/count contract.
- `docs/status/active/opik-self-host-eval-observability-pilot.md`: implementation evidence and final
  decision; created only when execution begins.
- Existing maintainer command/docs: minimal route and operator instructions only if required to run
  the proof repeatably.

## Acceptance Criteria

| Area | Required proof |
| --- | --- |
| Source | Exact manifest and digest set recorded; UI and receipt label it an unaccepted historical candidate. |
| Policy | Spot checks and full serialized values match the canonical decision report; no projector-side policy calculation. |
| Privacy | Denial scan finds no credentials, endpoints, prompts, tool bodies, private truth, absolute paths, images, or maps. |
| Identity | Deterministic keys and returned Opik IDs are recorded without display-name parsing. |
| Idempotency | Second pass leaves all logical object, score, trace, span, and dashboard counts unchanged. |
| Trace fidelity | Preserved sanitized span hierarchies retain timestamp, parentage, kind, and status; missing hierarchies stay experiment-only. |
| Views | The three target questions are answerable using documented Opik UI/filter surfaces without new policy logic. |
| Drilldown | At least one experiment item reaches its matching faithful trace and span hierarchy. |
| Isolation | Only one loopback port is published; Opik network/data/lifecycle are task-owned. |
| Footprint | Image size, startup time, idle/peak CPU/RAM, and disk growth are recorded. |
| Dependencies | No Opik dependency enters the product runtime or normal `.venv`. |
| Regression | Phoenix, companion reports, canonical artifacts, eval outcomes, and public launch grammar remain unchanged. |
| Rollback | Stopping Opik affects no Roboclaws, Phoenix, or companion behavior; retained data restarts consistently. |

## Verification Gates

Required deterministic gates:

```bash
bash scripts/dev/validate_opik_deployment.sh
ruff check scripts/reports/project_eval_harness_to_opik.py tests/unit/reports/test_project_eval_harness_to_opik.py
ruff format --check scripts/reports/project_eval_harness_to_opik.py tests/unit/reports/test_project_eval_harness_to_opik.py
./scripts/dev/run_pytest_standalone.sh -q tests/unit/reports/test_project_eval_harness_to_opik.py
```

Required Docker integration gates:

```bash
docker compose -p roboclaws-opik-poc -f deploy/opik/compose.yaml config
docker compose -p roboclaws-opik-poc -f deploy/opik/compose.yaml up -d --wait
./scripts/dev/run_pytest_standalone.sh -q tests/integration/test_opik_eval_observability_pilot.py
```

Required product run, with the exact route finalized during implementation and documented alongside
the script:

```bash
uv run python scripts/reports/project_eval_harness_to_opik.py \
  --manifest output/eval-harness/20260817T072338Z/eval_harness.json \
  --endpoint http://127.0.0.1:<opik-port>
```

Run that command twice, then inspect the receipt and server-side counts. Required local/manual proof
is browser review of all three target views and trace drilldown at desktop and mobile widths, plus
Compose footprint and stop/restart evidence. The implementation is
`BLOCKED_NEEDS_LOCAL_VALIDATION`, not complete, if Docker or browser proof cannot run.

After focused gates pass, run the repository-recommended gates from `agent::eval recommend` for the
resulting diff; include at least the relevant static, unit, contract/integration, and documentation
checks it selects.

## Stop Gates And Expansion Triggers

Stop the pilot and report evidence if:

- Opik cannot preserve deterministic identity or idempotent replay;
- the desired views require policy recomputation or unsupported/undocumented data access;
- faithful versus unavailable trace coverage cannot be obvious in the UI;
- a forbidden field crosses the projection boundary;
- loopback-only exposure or task-owned storage cannot be verified;
- the operational footprint is disproportionate to the observed UX benefit.

Re-approval is required before any live instrumentation, new eval/provider call, normal runtime
dependency, LAN/public exposure, accepted-baseline publication, automatic projection, durable
`roboclaws.evals` adapter, Phoenix/companion deletion or mutation, migration, or destructive cleanup.

## Agent Planning Loop Judgment

One bounded planning round ran with an entropy scout and a documentation-grill scout. No second
round was needed because both converged on the same architecture and exposed no unresolved product
choice.

| Finding | Judgment | Plan effect |
| --- | --- | --- |
| One-shot artifact projection, not runtime adapter | accept | Task-local importer; no runtime integration. |
| Candidate was incorrectly called a baseline | accept | Exact source pinned and labeled unaccepted historical candidate. |
| Canonical policy must stay local | merge | Copy final report facts only; Opik is diagnostic. |
| Closed identity and second-pass proof | accept | Deterministic keys, receipt, and unchanged-count gate. |
| Privacy by construction | accept | Allowlist payload builder and denial scan. |
| Full trace reconstruction is impossible | accept | Native sanitized spans only; other rows are experiment-only. |
| Synthetic event timelines for missing spans | reject | Added interpretation/privacy cost does not help the product decision. |
| Three dashboards reproduce all report semantics | reject | Dashboards summarize; documented tables/filters handle detail. |
| Measure the multi-service footprint | accept | Resource and persistence evidence is a completion gate. |
| Add a durable Opik module or shared adapter now | reject | Reconsider only after a migration decision. |
| Delete Phoenix or the companion during the pilot | reject | Both remain unchanged until a later migration plan. |
| Add LAN exposure for review | park | Requires explicit later scope and security review. |

## Preflight Contract

Preflight status: DRAFT

Task source: user request plus this plan

Canonical source: `docs/plans/2026-08-24-opik-self-host-eval-observability-pilot.md`

Route: durable `$intuitive-flow`

Goal: prove whether isolated Opik self-host materially improves recurring eval comparison and trace
drilldown without changing Roboclaws truth or runtime ownership.

Scope: execute Stages 1-5 against the one pinned historical candidate; produce tested deployment,
projector, receipt, browser/footprint evidence, and one migration recommendation.

Non-goals: live evals/providers; runtime instrumentation; policy recomputation; baseline
publication; user management; LAN/public exposure; Phoenix/companion mutation or deletion;
migration itself; destructive cleanup.

Entity budget: reuse=`observability_decision_report`, attached sanitized spans, existing report and
deployment validation patterns; remove/merge=none; new=isolated Opik deployment, one task-local
projector, focused tests, receipt, and active evidence note because no existing surface can perform
the product proof; expansion triggers=anything listed in Stop Gates And Expansion Triggers.

Context: must-read=`STATUS.md`, `ARCHITECTURE.md`, ADR-0149, this plan, the decision-report plan, the
exact manifest and attached artifacts; useful=the prior Phoenix platform plan and official Opik
self-host/dashboard/experiment/OTLP API docs for the pinned release; avoid-unless-needed=raw MCP
payloads, unrelated historical outputs, Phoenix storage, private eval evidence.

Acceptance:

- SUCCESS: every acceptance row and deterministic, Docker, product-run, browser, footprint,
  idempotency, privacy, isolation, and no-regression gate passes; one decision recommendation is
  recorded.
- BLOCKED_NEEDS_DECISION: an expansion trigger is required, or the pilot evidence is too ambiguous
  to choose among retain/migrate/reject.
- BLOCKED_NEEDS_LOCAL_VALIDATION: required Docker or browser proof cannot run in the execution
  environment.
- INTERMEDIATE_ONLY: none.
- No regressions: canonical artifacts/outcomes, Phoenix, companion reports, public launch grammar,
  dependencies, and runtime behavior are unchanged.

Verification: deterministic=deployment validator, Ruff, focused unit tests, privacy/identity parity;
integration=Compose config/health and live Opik API contract; product-run=the named manifest
projection twice; local-live-manual=desktop/mobile browser review, trace drilldown, resource and
restart measurements; optional=exploratory Opik filtering that does not alter acceptance.

Execution: main=root session supervises scope, stop gates, worker evidence, final browser review,
and migration judgment; worker=one durable implementation worker is justified by Docker lifecycle
and artifact evidence, with independent final review in the main session; worker-goal=execute only
this approved plan without expanding into migration or runtime integration.

To execute: `/goal execute docs/plans/2026-08-24-opik-self-host-eval-observability-pilot.md with intuitive-flow`

Optional tracking: none

Approval: `LGTM`, `approve`, or `go ahead` approves; edits request revision.

## Official References

- [Opik self-host overview](https://www.comet.com/docs/opik/self-host/overview)
- [Opik self-host architecture](https://www.comet.com/docs/opik/self-host/architecture)
- [OpenTelemetry integration](https://www.comet.com/docs/opik/integrations/opentelemetry)
- [Dashboards](https://www.comet.com/docs/opik/tracing/dashboards/dashboards)
- [Log experiments with REST API](https://www.comet.com/docs/opik/evaluation/advanced/log_experiments_with_rest_api)
- [Create dashboard REST API](https://www.comet.com/docs/opik/reference/rest-api/dashboards/create-dashboard)
