---
plan_scope: opik-only-observability-migration
status: DONE
created: 2026-08-25
last_reviewed: 2026-08-25
implementation_allowed: true
current_phase: complete
source:
  - user decision to build on Opik and prefer one observability system
  - browser-reviewed Roboclaws eval review Dashboard in the Opik 2.2.36 pilot
related_context:
  - STATUS.md
  - ARCHITECTURE.md
  - docs/adr/0149-project-agent-observability-as-one-way-side-effects.md
  - docs/plans/2026-08-18-observability-decision-report.md
  - docs/plans/2026-08-24-opik-self-host-eval-observability-pilot.md
approval:
  preflight_status: APPROVED
  plan_approved_on: 2026-08-25
  plan_approval_source: user-execute-request
---

# Opik-Only Observability Migration

## Plan Ledger

- Plan status: DONE; implementation, cutover, execute gate, live proof, restart, browser QA, and
  projection closeout are complete.
- Current slice: Complete.
- Next action: None. Reopen only for a separately scoped Opik upgrade or mobile-UX decision.
- Blocked on: none.
- Planning loop: one entropy, docs-grill, and skeptic round converged on 2026-08-25; no second
  round or additional product decision is needed.
- End state: Opik is the only running external observability backend and the default human eval
  review surface. Phoenix and the Eval Harness HTML companion are retired.
- Canonical boundary: local JSON, Markdown, run artifacts, graders, and human-only promotion remain
  authoritative. "Opik-only" means one external observability product, not moving product policy or
  private evidence into Opik.

## Shaped Bet

- Shaping status: READY.
- Problem: maintainers currently have three overlapping review surfaces: the generated Eval Harness
  HTML plus companion server, Phoenix for traces/Experiments, and Opik for Dashboards, Experiments,
  Datasets, and traces. The reviewed Opik Dashboard is already the preferred UX, while maintaining
  two external backends and one custom web viewer adds code, deployment, documentation, and mental
  overhead.
- Appetite: one bounded migration phase, capped at one engineering week. If runtime-trace or eval-
  projection parity cannot be proven within that appetite, keep the existing systems and reshape;
  do not build a generic observability framework.
- Core outcome: a maintainer opens one Opik origin to review current eval health, provider
  comparison, failures, Datasets, Experiments, and trace/span detail; new runs arrive automatically;
  no Phoenix or companion process is required.
- Core slice: one live OpenAI Agents SDK product trace and one completed repo-native eval suite
  automatically appear in Opik, update the durable review Dashboard, survive restart, and link back
  to immutable local identity without changing execution outcomes.
- Rabbit holes: undocumented Dashboard persistence, Opik runtime ingestion compatibility, Dataset
  discovery, historical Phoenix migration, private artifact uploads, and indefinite dual-write.
  Patch them with a pinned Dashboard schema contract, a live runtime spike before deletion,
  canonical-artifact reprojection rather than database copying, no private uploads, and a bounded
  parity window inside this migration only.
- No-gos: no Opik-owned graders, eligibility, ranking, baseline promotion, provider selection,
  scheduling, simulator control, physical authorization, raw prompts, tool bodies, images, maps,
  secrets, or private evaluation truth. No generic multi-backend plugin layer and no permanent
  Phoenix/Opik dual-write.
- Cut order under pressure: broad historical UI backfill; optional Dashboard widgets; migration of
  nonterminal/ad-hoc Phoenix records. Never cut runtime trace proof, current eval projection,
  privacy, idempotency, restart persistence, or removal of the duplicate active surfaces.
- Circuit breaker: stop before retiring Phoenix or HTML if Opik 2.2.36 cannot preserve sanitized
  runtime trace hierarchy, deterministic eval identity, fail-open behavior, or a reproducible
  Dashboard without recomputing canonical policy.
- Candidates considered: retain all three; replace only HTML; Opik-only. Opik-only wins because it
  yields the preferred review UX and the smallest durable operating model, provided parity gates
  pass.
- Decision: BET.

## Target Architecture

```text
Product / Eval execution
  -> dependency-free ExperimentTelemetry and local run artifacts
  -> bounded, fail-open Opik SDK trace sink

Terminal eval_results.json / Eval Harness manifest
  -> pure canonical observability_decision_report in local JSON + Markdown
  -> automatic, idempotent Opik Dataset / Experiment / score projection

Opik
  -> Roboclaws eval review Dashboard
  -> Dataset and Experiment comparison
  -> runtime and EvalTrial trace/span drilldown

Local artifacts remain canonical; Opik remains a one-way diagnostic projection.
```

The migration reuses the dependency-free local `ExperimentTelemetry`, existing `TraceSink` runtime
composition, privacy allowlist, sanitized span recording, Eval Harness decision-report derivation,
and proven pilot REST client/mapping logic. The external runtime sink and eval projector remain two
narrow owners; they do not become a backend registry or one combined abstraction.

## Product Decisions

### One External Backend

The supported workstation topology runs Opik only. The base deployment remains loopback-only;
trusted-LAN web access remains an explicit, single-interface override. Databases and ingestion
ports stay internal. Opik availability never gates a product run, eval outcome, collection,
publication, or promotion.

The production topology uses Compose project/network `roboclaws-opik`, data root `output/opik/`,
and exactly two supported projection Projects: `roboclaws-runtime` and `roboclaws-eval`. The eval
Dashboard belongs to `roboclaws-eval`. The existing `roboclaws-opik-poc` stack, pilot Project, and
`output/opik-poc/` remain inactive historical evidence and receive no new writes; do not rename or
copy their database into production.

After parity succeeds and cutover begins, add a short ADR recording Opik as the sole external
observability backend and link it from ADR-0149. ADR-0149 remains the accepted generic one-way
contract. Do not mark the new ADR accepted or rewrite current architecture before parity passes;
the circuit-breaker path must leave current Phoenix documentation truthful.

### Canonical Artifacts, Not Canonical Dashboard Logic

Keep:

- `eval_harness.json` and `observability_decision_report` as the structured policy owner;
- `eval_harness.md` as a portable, reviewable local artifact;
- suite results, run artifacts, sanitized span JSONL, completion evidence, and hashes;
- human-only baseline and promotion decisions.

Retire:

- generation and publication of `eval_harness.html` for terminal harness runs;
- `scripts/reports/serve_reports.py` and its tests/documentation;
- HTML companion routes, port `6100`, and completion-marker dependence on HTML;
- Phoenix runtime export, Dataset/Experiment projection, receipts, repair CLI, deployment,
  validators, tests, environment variables, documentation, and active launch references.

Terminal publication moves forward to `roboclaws_eval_harness_completion_v2`, written last and
hashing only `eval_harness.json` plus `eval_harness.md`. Nonterminal rewrites still remove stale
completion markers. Do not remove HTML until the v2 completion contract and publication ordering
pass focused tests.

Domain-specific robot reports, images, maps, and suite result artifacts are not generic
observability UI and remain local. This plan does not upload them to Opik or delete them.

### Durable Opik Projection

Promote the proven pilot mapper/client into one focused `roboclaws.evals` projection owner. Merge
the pilot-only scripts into that owner or delete them after their useful logic moves; do not keep a
second pilot path.

The durable projection must:

- accept one explicitly named canonical suite result or terminal Eval Harness manifest;
- run automatically after local suite persistence, during accepted CloudML result collection, and
  after authoritative terminal Eval Harness finalization;
- include valid passed, failed, blocked, and experiment-only rows without inventing traces;
- preserve deterministic project, Dataset, item, Experiment, trace, span, and score identity;
- write adjacent `opik_projection.json` receipts with `ready`, `disabled`, or `unavailable` state;
- be fail-open and bounded; an unavailable Opik service cannot change the source result;
- support one maintainer repair command by renaming the existing `phoenix-project` route to
  `opik-project`; forward-only migration updates all in-repo callers with no alias;
- reject non-loopback ingestion/API endpoints from runtime and automatic projection. LAN access is
  web review only.

Identity is immutable and content-addressed:

- Dataset identity includes suite id, suite version, and public Dataset content digest;
- item identity includes exact Dataset identity plus sample identity and public content digest;
- Experiment identity includes exact Dataset identity, tested configuration, source/result digest,
  and required evaluation identity;
- Project names are closed routing labels whose server IDs are discovered and reconciled, not
  falsely promised as client-selected UUIDs;
- an existing ID/name with different closed content is a hard mismatch. Never overwrite, append to,
  or silently reuse prior evidence; valid changed content creates a new content-addressed object.

One invocation-wide monotonic deadline covers discovery, reads, writes, batching, polling,
Dashboard reconciliation when explicitly requested, and receipt finalization. Every request uses
the remaining budget and no implicit retry resets it. Deadline expiry writes one sanitized
`unavailable` receipt atomically and never changes the source outcome. Stage 1 fixes the automatic-
projection maximum; the explicit repair command may expose only one documented bounded override.
The runtime trace sink retains its separate existing two-second terminal lifecycle bound.

Do not copy the Phoenix database or scan output roots. Required migration history is exactly
`output/eval-harness/20260817T072338Z/eval_harness.json`, source SHA-256
`7c44b49f2d2a4af3c61a5db61e3af89d738cf80ce6bd80274d797291795dff75`, plus new runs created by
the migration proof and future automatic projection. The nine-root Phoenix historical backfill,
ad-hoc/debug runs, worker shards, and other old terminal roots remain local/offline and are outside
this plan.

The object-by-fidelity contract is explicit for the reviewed candidate: all 65 rows are Dataset
items; only the 25 `native_span_trace` rows become Experiment items, traces, and trace-linked
scores; the 40 `experiment_only` rows remain Dataset-only because no trace may be invented.

### Runtime Trace Parity

Replace `PhoenixTelemetryAdapter` with one Opik SDK trace sink at the existing `TraceSink` /
`CompositeTraceSink` runtime composition boundary. Keep `TelemetryRuntime`, `LocalTraceRouter`, the
required local recorder, dependency-free `ExperimentTelemetry`, OpenInference privacy
configuration, bounded batch/flush lifecycle, closed identity attributes,
`roboclaws-runtime`/`roboclaws-eval` routing, and status counters.

First prove the pinned Opik release's supported ingestion path with a real OpenAI Agents SDK run.
Prefer standard OTLP/OpenTelemetry ingestion when it preserves the required hierarchy and project
routing; otherwise use the smallest Opik-supported adapter. Do not introduce both paths. Runtime
configuration uses one loopback base origin, `ROBOCLAWS_OPIK_ENDPOINT`; fixed REST and supported
ingestion paths derive internally. The repair command uses the same origin contract. Old Phoenix
variables are removed rather than aliased, and Compose-only LAN variables never enable ingestion.

### Reproducible Dashboard

The existing `Roboclaws eval review` layout is the seed, not an untracked manual artifact. Add one
idempotent provisioning/reconciliation operation that creates or updates the pinned Dashboard
shape during explicit deployment/maintenance. It owns only layout and metric selection; all values
come from projected canonical facts.

Required sections:

1. review scope and canonical-source limitation;
2. capability health and native-trace coverage;
3. provider comparison;
4. failure, outcome, and trace-fidelity coverage;
5. links to Dataset and Experiment drilldown, including the experiment-only limitation.

Dashboard trace charts answer native telemetry for 25 rows. Full 65-row review uses the Dataset
under the same Opik origin plus canonical JSON/Markdown; Experiment and trace drilldown cover only
the 25 native rows. The Dashboard must show the 25/40 limitation and provide a stable direct Dataset
link because Opik 2.2.36 may hide the `evaluation_suite` Dataset from normal navigation.

Inventory and pin every private Opik 2.2.36 API used by the narrow client, including Projects,
Datasets/items, Experiments/items, traces, spans, scores, and `insights-views`. If no supported
public Dashboard surface exists, pin the observed schema behind one narrow client method and live
drift tests. API drift must fail explicitly before removal; it must not silently create duplicate
objects or drop Dashboard sections.

## Implementation Stages

### Stage 1: Prove The Replacement Seams

1. Inventory and live-test the pinned private REST surfaces and one supported ingestion path through
   the single loopback Opik origin. Do not change current architecture docs or accepted ADRs yet.
2. Turn the pilot mapping/client into production-shaped unit and integration fixtures without
   deleting Phoenix or writing production state.
3. Prove both closed trace routes: one sanitized product run in `roboclaws-runtime` and one live
   EvalTrial in `roboclaws-eval`, with correct parentage, span count, identity attributes, privacy
   denials, bounded flush, and fail-open behavior.
4. Prove one repo-native suite projects the exact object-by-fidelity matrix twice with unchanged
   counts, then prove changed suite/result content creates new identity or fails closed rather than
   mutating prior evidence.
5. Prove the invocation-wide automatic-projection deadline on local finalization and accepted
   CloudML collection, including atomic `unavailable` receipt behavior.
6. Provision the Dashboard twice and prove one stable Dashboard identity, project binding, shape,
   direct Dataset link, and visible 25/40 limitation.

This is a temporary parity gate, not a shipped dual-backend mode. A failed gate triggers the
circuit breaker before removal work begins.

### Stage 2: Make Opik The Automatic Path

1. Stop the PoC stack and bootstrap the clean `roboclaws-opik` topology from canonical artifacts;
   do not copy the pilot database or write new data to the pilot Project.
2. Replace runtime `TraceSink` composition and environment/configuration references with the Opik
   sink.
3. Replace suite finalization, CloudML collection attachment, terminal-harness projection, receipt
   summaries, drilldown links, and repair command with `opik_projection.json` / `opik-project`.
4. Project only the reviewed candidate and new proof runs, then generate one content-addressed
   migration receipt. Never read Phoenix as an input source.
5. Make Dashboard reconciliation an explicit deployment/maintenance operation, not product
   execution and not an automatic action after every projection.
6. Migrate terminal publication to completion marker v2, then remove HTML from the completion set.
7. After all cutover gates pass, accept the new ADR and update current architecture/human docs to
   Opik. Exercise local and LAN review across Dashboard, Dataset, Experiment, and trace detail.

### Stage 3: Remove The Duplicate Surfaces

Only after Stage 1 and Stage 2 gates pass:

1. stop Phoenix and the companion server;
2. delete Phoenix code, deployment, commands, tests, docs, and active receipt handling;
3. remove Eval Harness HTML rendering, companion server, tests, and completion-marker dependency;
4. delete superseded pilot-only projector paths and names after their logic is merged;
5. run repository-wide searches and architecture/doc cleanup so only historical plans and
   retrospectives retain Phoenix/companion references;
6. record the pre-removal Phoenix store counts/digests and the migration commit. Rollback is a code
   revert plus the pinned Phoenix deployment against retained `output/phoenix/`, not an implicit
   database conversion;
7. keep `output/phoenix/` and `output/opik-poc/` as inactive evidence. Destructive data deletion
   requires separate human approval and is not part of this plan.

There is no compatibility shim, alias, feature flag, or permanent dual-write after this stage.

## Acceptance Criteria

### Functional

- One live product run appears under the Opik runtime project with its complete sanitized
  Agent/LLM/Tool trace hierarchy and correct closed identity.
- One live EvalTrial appears under `roboclaws-eval` through the same closed runtime routing contract.
- One completed repo-native suite and one terminal mixed local/CloudML fixture automatically
  produce ready `opik_projection.json` receipts and visible Dataset/Experiment/score rows.
- A second identical projection creates zero new logical objects, scores, or Dashboards.
- Changed suite/result content never overwrites prior Dataset/items/Experiment evidence and follows
  the content-addressed new-identity or hard-mismatch contract.
- Failed, blocked, missing-telemetry, native-trace, and experiment-only rows remain distinguishable;
  unavailable values are not converted to zero.
- The LAN Dashboard answers native trace telemetry for 25 rows and visibly links to all 65 Dataset
  rows; Experiment/trace drilldown covers the matching 25 native rows and never claims the 40
  Dataset-only rows have traces.
- Opik restart preserves projected data and Dashboard identity.

### Simplification

- No Phoenix container, active deployment file, adapter, projector, command, environment variable,
  receipt field, current documentation, or nonhistorical test remains.
- No Eval Harness HTML file or companion server is generated or required for new terminal runs.
- One Opik projection owner and one Opik runtime sink remain; pilot duplicates are removed.
- The active Compose/network/data/project labels contain no `pilot` or `poc`; inactive pilot
  evidence remains untouched.
- `git grep` finds Phoenix/companion names only in explicitly historical plans, ADR history,
  retrospectives, or retained old artifacts.

### Safety And No Regression

- Local canonical JSON/Markdown and run artifacts are complete when Opik is disabled or unavailable.
- Opik failure is bounded and fail-open; product/eval outcomes and terminal latency stay unchanged.
- Automatic projection obeys one tested invocation-wide deadline rather than resetting a timeout
  per request.
- The closed export allowlist and credential/private-value scan pass for traces, projection
  payloads, receipts, Dashboard metadata, and URLs.
- No provider, evaluator, promotion, simulator, CloudML placement, or physical robot behavior
  changes.
- Phoenix storage is not read as migration truth and is not deleted.
- Completion marker v2 is written last over JSON/Markdown and stale markers are removed on
  nonterminal rewrites.

## Verification

Deterministic gates:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
bash scripts/dev/validate_opik_deployment.sh
git diff --check
```

Focused contract and integration gates must cover the Opik client/mapping, runtime sink,
automatic suite projection, Eval Harness/CloudML receipt attachment, Dashboard reconciliation,
privacy denial, endpoint rejection, fail-open behavior, idempotent replay, and retained-data
restart. Delete the corresponding Phoenix/companion tests rather than preserving compatibility
fixtures.

Required product proofs:

```bash
ROBOCLAWS_OPIK_ENDPOINT=http://127.0.0.1:5174 \
just run::surface surface=household-world agent_engine=openai-agents-sdk \
  prompt="find something useful to drink"

ROBOCLAWS_OPIK_ENDPOINT=http://127.0.0.1:5174 \
just agent::eval suite=smoke_regression budget=smoke
```

The supported ingestion path derives from the base origin after Stage 1 and is fixed in code,
docs, and tests. Run the repository-selected gate as well:

```bash
just agent::eval recommend \
  plan=docs/plans/2026-08-25-opik-only-observability-migration.md budget=focused
just agent::eval execute \
  plan=docs/plans/2026-08-25-opik-only-observability-migration.md budget=focused
```

Required local/live/manual proof:

- Docker-backed Opik health, resource sample, retained-data restart, and loopback-only ingestion;
- browser QA at desktop and mobile widths on loopback plus the explicit LAN web origin;
- visible runtime trace parentage, Experiment-to-trace drilldown, Dataset rows, Dashboard sections,
  direct Dataset discovery, and the honest 25 native Experiment/trace rows plus 40 Dataset-only
  rows for the reviewed candidate;
- both `roboclaws-runtime` product and `roboclaws-eval` live EvalTrial routing;
- Opik-disabled and Opik-unavailable product/eval runs with unchanged canonical outcomes;
- Phoenix and companion processes stopped, their ports absent, and one normal restart path bringing
  up only Opik.

## Stop Gates

- Stop before removal if Opik cannot preserve live trace/span hierarchy or closed project routing.
- Stop before removal if any pinned private Project, Dataset/item, Experiment/item, trace, span,
  score, or Dashboard API drifts from the live contract.
- Stop before removal if automatic projection changes source outcomes, duplicates logical objects,
  or cannot represent failed/blocked/experiment-only evidence honestly.
- Stop before removal if same identity can overwrite different closed content, or if changed suite
  content cannot create a new immutable object or fail with an actionable mismatch.
- Stop before removal if automatic projection cannot enforce one invocation-wide deadline and
  atomically record deadline expiry without changing the source outcome.
- Stop before removal if Dashboard provisioning depends on unbounded browser automation or silently
  drifts under the pinned release.
- Stop before HTML removal if completion marker v2 does not preserve write-last finalization and
  stale-marker invalidation using JSON/Markdown only.
- Stop immediately on any forbidden field, credential value, private truth, raw prompt/tool body,
  image, map, endpoint secret, or absolute worker path crossing the boundary.
- Stop and request re-approval for authentication/TLS, public exposure, shared/multi-user ownership,
  cross-machine ingestion, backup/restore service design, Opik version upgrade, larger resource
  envelope, or deletion of Phoenix data.

## Agent Planning Loop Judgment

One bounded round ran three independent read-only perspectives: plan entropy, docs/domain grilling,
and a skeptic review. All converged after the grill worker retried one interrupted response; a
second planning round would only revisit implementation defaults.

| Finding | Judgment | Plan effect |
| --- | --- | --- |
| Replace at the actual `TraceSink` seam | accept | Keep local telemetry owners; add one external Opik SDK sink. |
| Pin two supported production Projects | accept | `roboclaws-runtime` and `roboclaws-eval`; pilot becomes inactive evidence. |
| Claim full 65-row Dashboard/Experiment coverage | reject | Dataset has 65; Experiment/trace has 25 native; show the 40-row limitation. |
| Migrate all Phoenix historical roots | reject | Reproject only the reviewed candidate and future runs. |
| Write final ADR/current architecture before proof | reject | Accept and publish the decision only after parity gates pass. |
| Reuse names without closed-content equivalence | reject | Add immutable, content-addressed identity and mismatch tests. |
| Rely on per-request timeouts | reject | One invocation-wide projection deadline owns bounded failure. |
| Promote the PoC store in place | reject | Bootstrap clean non-PoC topology; retain pilot data read-only. |
| Keep two Opik endpoint settings | reject | One loopback base origin derives fixed API/ingestion paths. |
| Remove HTML without finalization migration | reject | Completion marker v2 hashes JSON/Markdown and remains write-last. |

Parked: nine-root/125-bundle Phoenix historical UI backfill, authentication/TLS/multi-user/public
exposure, backup service design, Opik upgrades, optional Dashboard polish, and destructive Phoenix
or pilot-data deletion.

Planning-loop status: CONVERGED; no unresolved user decision beyond approval of this revised plan.

## Preflight Contract

Preflight status: APPROVED AND EXECUTED

Task source: user decision plus the reviewed Opik pilot

Canonical source: `docs/plans/2026-08-25-opik-only-observability-migration.md`

Route: durable `$intuitive-flow`

Goal: make Opik the only active external observability backend and human eval review UI while
preserving local canonical evidence and one-way fail-open execution.

Scope: both runtime trace routes; immutable automatic local, CloudML, and terminal-harness eval
projection under one deadline; deterministic Dashboard; reviewed-candidate reprojection; completion
marker v2; retirement of Phoenix and Eval Harness HTML companion.

Non-goals: Opik-owned policy/graders/promotion; private artifact upload; public/shared deployment;
Opik upgrade; provider/simulator/hardware changes; destructive Phoenix data deletion.

Entity budget: reuse=local `ExperimentTelemetry`, `TraceSink` composition, privacy allowlist,
sanitized spans, decision report, pilot Opik mapper/client logic and Dashboard shape;
remove/merge=Phoenix adapter/projector/deployment, HTML renderer/companion, pilot code duplicates;
new=one Opik runtime sink, one durable Opik projection owner containing the narrow Dashboard
reconciler, one completion marker version, and one ADR; expansion triggers=shared/public/
authenticated Opik, cross-machine ingestion, version/resource expansion, broad history, or
destructive data deletion requires re-approval.

Context: must-read=`STATUS.md`, `ARCHITECTURE.md`, ADR-0149, observability decision-report plan,
Opik pilot plan, runtime trace composition, completion publication, projection code and focused
tests; useful=pilot receipt/screenshots and offline Phoenix counts/digests; avoid-unless-needed=
unrelated historical plans, private artifacts, Phoenix database internals and broad backfill roots.

Acceptance:

- SUCCESS: all Functional, Simplification, Safety, deterministic, integration, product-run, and
  local/manual gates above pass; the normal workstation runs only Opik for observability.
- BLOCKED_NEEDS_DECISION: Opik parity needs a public/shared/authenticated deployment, different
  release, private-data expansion, or larger resource envelope.
- BLOCKED_NEEDS_LOCAL_VALIDATION: required live provider, Docker restart, LAN browser, or fail-open
  proof cannot run or pass.
- INTERMEDIATE_ONLY: none; do not land a permanent dual-backend checkpoint.
- No regressions: local canonical artifacts, outcomes, latency, privacy, human-only promotion,
  provider placement, simulator and robot behavior stay unchanged.

Verification: deterministic=full Ruff/format/pytest, deployment validator, diff check;
integration=pinned private API drift, two trace routes, immutable projection, global deadline,
completion marker v2, Dashboard and restart contracts; product-run=one cheapest OpenAI Agents SDK
household run plus one live EvalTrial, smoke regression suite, and repository-selected eval gate;
local-live-manual=LAN/desktop/mobile review, honest 25/40 current-candidate coverage, disabled/
unavailable proof, and only-Opik process/port audit; optional=none in this execution unit.

Execution: main=root session owns stage gates, circuit breaker, removal authorization, browser
judgment, and final audit; worker=none; worker-goal=none.

To execute: `/goal execute docs/plans/2026-08-25-opik-only-observability-migration.md with intuitive-flow`

Optional tracking: none.

Approval: `LGTM`, `approve`, or `go ahead` approves this plan; edits request revision.

## Closeout

Shipped commits: `8b6f3fc7`, `0a9e0e63`, `81d2a328`, `4b4df52c`, and
`232197f8`.

Production proof:

- reviewed candidate: 65 Dataset items, 25 native Experiment/trace rows, 40
  Dataset-only rows, 4,994 spans, 56 scores, zero privacy findings, and
  idempotent replay;
- cleanup suite: 3 Dataset/Experiment/trace items, 686 spans, and 15 scores;
- clean-stack product run `0825_1247/seed-7`: one trace, 253 unique local spans,
  one root, 252 parented spans, zero missing parents, exporter `ready` with 254
  exported and zero failed/dropped. The task truthfully completed as not-found;
  observability did not change its outcome;
- retained-data restart preserved runtime/eval Project IDs, both Datasets, and
  Dashboard `01a03731-da35-72bb-94c1-0a1f73c125cb`;
- browser QA passed Dashboard, Dataset, Experiment, and 234-span trace detail on
  loopback and LAN. Opik 2.2.36 retains a desktop-width Dashboard canvas at
  390px, so mobile review requires horizontal navigation.

Deviation: the literal product-proof command lacked the now-required
`provider_profile`; the first attempt failed before provider execution. The
successful proof added the existing cheap local `kimi-openai-chat` profile.

Retained data: `output/phoenix/` and `output/opik-poc/` were neither copied nor
deleted. Phoenix and companion ports 6006/6100 are absent.
