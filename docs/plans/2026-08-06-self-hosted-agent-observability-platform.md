---
plan_scope: self-hosted-agent-observability-platform
status: APPROVED
created: 2026-08-06
last_reviewed: 2026-08-06
implementation_allowed: true
current_phase: phase-2-production-selection-gate
source:
  - user request to self-host OpenAI Agents SDK tracing and reduce custom observability
  - user requirement that Phoenix or Langfuse remain outside the real-robot control path
  - agent-planning-loop review requested on 2026-08-06
related_context:
  - STATUS.md
  - ARCHITECTURE.md
  - docs/human/evaluation.md
  - docs/human/domain.md
  - docs/plans/live-agent-runtime-sdk-spike.md
  - docs/plans/live-agent-runtime-sdk-perf-followups.md
approval:
  approved_on: 2026-08-07
  source: user request to implement this plan via intuitive-flow
  preserves_later_review_gates: true
---

# Self-Hosted Agent Observability And Experiment Platform

## Goal

Adopt one self-hosted open-source AI engineering platform as a best-effort
projection of OpenAI Agents SDK runs, prompts, eval datasets, experiments, and
scores, while keeping Roboclaws as the canonical owner of robot execution,
safety, private evaluation, replayable artifacts, and promotion decisions.

The recommended platform is **Arize Phoenix** because its OpenAI Agents SDK
instrumentation is maintained through OpenInference, its trace model is based
on OpenTelemetry, its dataset/experiment/evaluator abstractions match the
current eval model, and its self-host footprint can start smaller than
Langfuse. The implementation must prove those claims with a bounded local PoC
before Phoenix becomes the selected adapter. Langfuse remains the comparison
alternative, not a second production adapter.

```text
Product and eval execution                 Best-effort projection

Operator / Eval Harness
  -> Roboclaws launch/runtime
  -> OpenAI Agents SDK Runner
  -> model provider + MCP tools
  -> robot backend / simulator             SDK/OpenInference spans
  -> local canonical artifacts        ---> Phoenix project/trace/spans
  -> private/local graders             ---> Phoenix scores/annotations
  -> repo prompt/sample identity       ---> Phoenix prompt/dataset metadata
```

Phoenix must never call, schedule, authorize, or gate a physical robot run.
Phoenix unavailability must not change agent behavior, MCP availability,
terminal status, checker output, or local artifact completeness.

## Planning Charter

### In Scope

- One deep `ExperimentTelemetry` module with a small interface. Its mandatory
  local adapter is a facade over the existing canonical artifacts and recorder
  ownership, not a second local telemetry store; its optional adapter projects
  to Phoenix.
- Process-level OpenAI Agents SDK tracing configuration registered once, without
  the default OpenAI remote exporter.
- OpenInference/OTLP export of sanitized Agent, LLM, Tool, and custom runtime
  spans to a self-hosted Phoenix instance.
- Stable correlation among Robot Run, Operator Session, eval sample/trial,
  OpenAI Agents SDK trace, Phoenix project/session/trace, and local artifacts.
- One-way projection of public prompt identity, public eval dataset fields,
  experiment identity, and local grader scores.
- A local-development Phoenix deployment and documented production topology in
  which Phoenix runs off-robot on a self-controlled host.
- Parity and failure proofs before deleting duplicated generic observability.

### Non-Goals

- No Phoenix or Langfuse control of `Runner`, MCP tools, robot backends, launch
  axes, physical safety gates, operator controls, or eval placement.
- No runtime fetch of a mutable "latest" prompt, dataset, evaluator, or config
  from an observability platform.
- No upload of credentials, provider endpoints, raw images, maps, private
  scoring truth, generated mess identity, acceptable destinations, grader
  internals, holdout identity, or unredacted tool payloads.
- No replacement of `run_result.json`, `live_status.json`, MCP `trace.jsonl`,
  Runtime Metric Map, checker reports, eval result bundles, sealed holdout, or
  human-only promotion.
- No permanent dual support for Phoenix and Langfuse.
- No real-robot movement as part of implementation verification. The final
  hardware-facing proof is a no-movement launch/readiness or recorded-replay
  proof unless a present operator separately authorizes movement.

### User-Review Gates

- Approve Phoenix as the selected production adapter after the PoC report.
- Approve the self-host production placement, retention, authentication, and
  resource/cost envelope before Phase 2 shared-deployment work begins. The PoC
  is local-only and opt-in until this decision is recorded.
- Approve the exact live PoC cells before provider calls. The default proposal
  is one cheap Chat Completions profile and one cheap Responses profile, serial,
  with zero automatic retries.
- Keep rendered prompt content out of Phoenix by default. Any content-upload
  policy remains a separate explicit local-development approval.
- Approve any later deletion that removes a local canonical artifact or changes
  an externally reviewed report contract.

### Stop Condition

The plan is execution-ready when platform ownership, privacy policy, failure
semantics, immutable identity, rollout order, acceptance criteria, and proof
commands are explicit; remaining choices are local implementation defaults.

## Durable Architecture Decisions

1. **Execution stays local to Roboclaws.** `just run::surface`,
   `just agent::eval`, the typed launch executor, OpenAI Agents SDK `Runner`,
   MCP, and backend adapters retain their current ownership.
2. **Telemetry is a side effect, not a dependency.** Export is asynchronous,
   bounded, and best-effort. Exporter errors are observable but non-fatal.
3. **Local evidence is canonical.** Every serious run remains auditable and
   regradable without Phoenix. `ExperimentTelemetry` reuses the existing local
   artifact owner; it does not introduce a parallel local event schema.
4. **Projection is one-way.** Git-reviewed prompt, Skill, sample, suite, and
   grader definitions project outward. Phoenix UI edits do not affect runtime
   behavior without an explicit digest-bound repo promotion workflow.
5. **Private truth stays local.** Dataset reference output is omitted whenever
   it would reveal grader-only truth. Only allowlisted public identity and final
   scores/annotations leave the run directory.
6. **One external adapter.** Phoenix is recommended; Langfuse is used only in
   the PoC if Phoenix fails a material acceptance gate.
7. **Open standards at the seam.** Prefer OpenTelemetry/OpenInference resource
   and span attributes over Phoenix-specific calls for tracing. Use the Phoenix
   client only where no open semantic exists, such as prompt/dataset/experiment
   projection.
8. **No silent observability fallback.** Local evidence always runs. External
   export reports `ready`, `degraded`, `disabled`, or `unavailable`; it never
   silently claims success.
9. **One process owns SDK tracing.** A process-level telemetry runtime replaces
   the SDK default processors exactly once. A composite processor contains the
   local routing processor plus the optional OpenInference processor. Run-scoped
   sinks are selected by trace/run context and are registered/unregistered
   without mutating the global SDK processor list.

These decisions are ADR-shaped. Phase 0 creates one short ADR after plan
approval; this plan continues to own execution details and proof.

## Target Domain Mapping

| Roboclaws owner | Phoenix projection | Required identity |
| --- | --- | --- |
| Robot Run | project + root trace | run ID, trace ID, Git SHA |
| Operator Session | Phoenix session | operator session ID |
| SDK Agent/turn/model/tool | Agent/LLM/Tool spans | parent/span IDs |
| provider retry/racing/compaction | custom spans or allowlisted attributes | attempt and policy IDs |
| prompt/Skill source | prompt version metadata | source digest, rendered digest |
| EvalSample | dataset example | sample ID and sample digest |
| EvalSuite | dataset/experiment metadata | suite ID and version |
| EvalTrial | experiment run linked to trace | trial ID and repetition |
| local grader output | score/annotation | grader name/version/status |
| report/map/image artifacts | link + digest metadata only | schema and content digest |

Phoenix is not an artifact store. Large or sensitive artifacts remain under the
existing run directory or an existing self-controlled artifact store.

## Module And Interface

Create one deep module under the existing agents/evals ownership rather than
letting Phoenix calls spread through runners, graders, and report renderers.
It absorbs the current SDK processor lifecycle and routes events to the
existing run-owned local files; it does not wrap those files with a duplicate
store. The exact package split is an implementation default, but callers learn
one interface:

```python
class ExperimentTelemetry:
    def start_run(self, identity: RunIdentity) -> RunTelemetry: ...
    def record_scores(self, run: RunTelemetry, scores: Sequence[Score]) -> None: ...
    def link_artifacts(self, run: RunTelemetry, artifacts: Sequence[ArtifactLink]) -> None: ...
    def finish_run(self, run: RunTelemetry, outcome: RunOutcome) -> None: ...
    def flush(self, deadline_s: float) -> TelemetryStatus: ...
```

Prompt and dataset publication are maintainer operations, not methods required
by the live robot path. Keep them behind a separate narrow projection command
owned by the eval/maintainer layer.

Adapters:

- `LocalEvidenceAdapter`: mandatory facade over the existing run artifacts,
  deterministic and canonical.
- `PhoenixTelemetryAdapter`: optional, asynchronous, sanitized, and fail-open.
- Tests may use an in-memory fake internal to the module; do not expose a
  generic plugin registry before another production adapter exists.

## Data Policy

Default export includes only:

- trace/span/session IDs and timestamps;
- workflow, Agent, model, and public provider-profile labels;
- token usage including cached/reasoning details when the provider returns it;
- MCP server/tool names, duration, status, and sanitized error classification;
- public launch axes, sample/trial/suite identity, Git SHA, and content digests;
- allowlisted numeric/categorical grader scores;
- artifact labels, schema versions, digests, and access-controlled links.

Default export excludes inputs, outputs, tool arguments/results, raw provider
errors, paths outside the normalized artifact link contract, arbitrary metadata,
and all private-evaluation fields. SDK `trace_include_sensitive_data=False` is
necessary but insufficient; exporter-side allowlisting and denial tests are
required.

The external exporter accepts a closed schema. Unexpected SDK span fields are
dropped, not forwarded. Error values are normalized to an allowlisted category
and exception type; raw messages, URLs, query strings, filesystem paths, and
headers are never exported. Artifact links accept only configured self-hosted
origins plus relative artifact identity and digest.

## Runtime And Dependency Ownership

- `TelemetryRuntime` is initialized once by the OpenAI Agents SDK process entry
  point before any run. It calls `set_trace_processors(...)` to replace the SDK
  default processor list; `add_trace_processor(...)` is not used per run.
- A startup contract test covers `OPENAI_API_KEY` absent/present and proves no
  `BackendSpanExporter` or OpenAI ingest request remains installed.
- The local routing processor maps trace IDs to run-scoped sinks. Two sequential
  runs and one continuation must produce no duplicate spans and no writes to a
  closed run sink.
- The product/runtime dependency group contains only the pinned OpenInference
  instrumentor and OTLP exporter required on the robot-side process. Phoenix
  server/client packages and deployment dependencies stay in a maintainer/dev
  extra unless a narrow projection command needs the client.
- The self-hosted Phoenix server/collector version is pinned independently from
  the robot runtime and is never imported by Isaac Lab, MCP, backend, safety,
  checker, or product-domain modules.

External export uses a bounded non-blocking queue and one owned background
worker. Initial implementation defaults are explicit and may be tightened by
the PoC: no adapter-level automatic retry, queue-full drops external spans only,
a two-second terminal flush deadline, and a locally recorded exported/dropped/
failed count. DNS, connect, write, TLS, auth, and server failures occur only in
the worker. The product thread performs no network I/O while handling SDK span
callbacks.

## Phases

### Phase 0: Decision Record And Contract Fixtures

- Create the short ADR for the side-effect-only, one-way projection decision.
- Define typed identity, privacy allowlist, exporter status, and artifact-link
  contracts without a Phoenix dependency in product/domain modules.
- Add malicious fixtures for credentials, provider endpoints, private truth,
  raw tool payloads, absolute paths, and large image/map payloads.
- Record current local trace/cache/latency/eval behavior as the parity fixture.
- Add an SDK lifecycle spike that proves `set_trace_processors(...)` removes the
  OpenAI backend exporter, registers exactly once, routes two sequential runs
  plus one continuation correctly, and performs bounded shutdown.
- Produce a caller/owner inventory for current spans, events, metrics, budget,
  continuation, status, and report consumers. Classify each as canonical local
  evidence, derived domain evidence, or future generic projection.

Gate: contract tests prove forbidden data cannot cross the telemetry seam.

### Phase 1: Bounded Phoenix PoC

- Add a pinned development dependency for the Phoenix/OpenInference Agents SDK
  instrumentor and OTLP exporter.
- Provide an opt-in local Phoenix deployment outside the robot runtime process.
- Register instrumentation once at process initialization; do not append one
  global processor per Robot Run.
- Preserve the local recorder during the PoC and explicitly remove the default
  OpenAI backend exporter.
- Run one deterministic SDK fake plus, after the user-review gate, one cheap
  Chat Completions profile and one cheap Responses profile, serial, with zero
  automatic retries.
- Produce a comparison report covering hierarchy, model/usage/cache fields,
  MCP tools, errors, flush behavior, sanitization, and export overhead.

The PoC passes only when:

- the deterministic fixture and both live wire families produce exactly one
  correlated root trace per Robot Run with no duplicate span IDs;
- required Agent, LLM, and Tool span kinds, run/trial identity, model, usage,
  cache/reasoning availability, status, and error category match the allowlisted
  parity matrix;
- reachable export drops zero spans, and every dropped/failed span in injected
  failure tests is counted locally;
- forbidden-field count is zero over serialized Phoenix-bound payloads;
- span callback enqueue latency is at most 5 ms at p99 in deterministic failure
  injection, deterministic run wall time increases by at most 2%, and terminal
  flush contributes at most two seconds;
- a report estimates trace volume, storage growth, retention implications, and
  shared-deployment resources from the observed runs.

Gate: Phoenix passes the material requirements or the plan stops for a human
decision before trying Langfuse as the only alternative.

### Phase 2: Fail-Open Runtime And Real-Robot Topology

- Stop before shared-deployment work until the user approves host placement,
  network reachability, authentication, retention, backup/deletion policy, and
  resource/cost envelope from the Phase 1 report.
- Put batching, queue limits, retry limits, flush deadlines, and exporter status
  behind `PhoenixTelemetryAdapter`.
- Prove Phoenix DNS refusal, connection refusal, timeout, authentication error,
  server 5xx, full queue, and process shutdown do not fail or materially delay a
  Robot Run.
- Keep Phoenix off-robot in the documented production topology. The robot image
  contains only lightweight instrumentation/export dependencies.
- Add bounded local spool behavior only if the PoC proves that losing traces
  during ordinary disconnected operation is unacceptable. Do not build a
  general durable message queue speculatively.
- Correlate local run IDs and trace IDs with Phoenix URLs without requiring the
  URL to complete the run.

Gate: no-network and Phoenix-down proofs produce complete local artifacts and
the same product/checker outcome as telemetry-disabled controls. A recorded
real-robot-shaped no-movement replay proves topology/control-path separation;
it does not claim physical execution safety.

### Phase 3: Prompt Identity Projection

- Model the composed kickoff prompt as a named/versioned projection with public
  template identity, variable schema, source Git SHA, Skill digest, and rendered
  digest.
- Do not upload rendered prompt bodies. The separately approved local-dev policy
  is out of the default implementation path.
- Phoenix tags can mark experiment candidates, but production selection remains
  a digest-bound repo manifest and bundled deployment input.
- Record the selected prompt identity on every local run and Phoenix trace.

Gate: editing or retagging a Phoenix prompt cannot alter a product or eval run.

### Phase 4: Eval Dataset, Experiment, And Score Projection

- Add a maintainer command that projects public EvalSample/EvalSuite identity to
  Phoenix datasets with idempotent upsert by content digest.
- Never upload `private_goal_reference`, grader config that encodes hidden truth,
  holdout identity, generated mess truth, or acceptable destinations.
- Link each EvalTrial trace to dataset example, experiment, repetition, provider,
  model, Skill digest, and Git SHA.
- Send allowlisted local grader results as scores/annotations after grading.
- Keep `just agent::eval` as the sole execution facade; Phoenix does not schedule
  simulator, CloudML, provider, or hardware work.
- Write the local-to-external reference mapping into local artifacts even when
  projection is disabled or unavailable. Phoenix identifiers and URLs are
  references, never canonical identity.

Gate: a projected experiment can be reconstructed from local artifacts, while a
Phoenix export contains no private truth and cannot be used to launch a run. A
Phoenix-disabled regrade from an existing run directory produces the same local
grader results and aggregate identity.

### Phase 5: Parity Review And Deletion

- Create a deletion matrix before editing code. For every candidate, record its
  current callers, local artifact contract, budget/continuation/status/regrade/
  privacy role, Phoenix replacement, offline proof, rollback, and approval need.
- Inventory generic functionality duplicated by Phoenix: SDK span browsing,
  cross-run token/cache/latency aggregation, generic experiment comparison,
  and generic trace tables. Generic-looking code is not deletable evidence by
  itself.
- Delete only code whose canonical/replay/privacy role is fully preserved.
- Retain minimal local span/evidence needed for offline audit, budget enforcement,
  regrade, failure classification, and regression proof.
- Keep domain reports focused on robot state, maps, trajectory, checker outcome,
  private post-run evaluation, and artifact integrity.
- Update architecture, human evaluation/runtime docs, operator-console links,
  dependency lock, and focused tests in the same phase as each deletion.

Gate: Phoenix-disabled and Phoenix-down test matrices still satisfy all product,
eval, privacy, and artifact contracts.

## Verification

Planning-stage selector:

```bash
just agent::eval recommend \
  plan=docs/plans/2026-08-06-self-hosted-agent-observability-platform.md \
  budget=focused
```

Implementation gates, selected proportionally per phase:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/agents/test_live_runtime_telemetry.py \
  tests/unit/agents/test_live_runtime_budget.py \
  tests/unit/evals \
  tests/contract/molmo_cleanup
just agent::eval execute \
  plan=docs/plans/2026-08-06-self-hosted-agent-observability-platform.md \
  budget=focused
```

Required focused proof matrix:

| Proof | Telemetry state | Expected result |
| --- | --- | --- |
| deterministic fake | disabled / Phoenix | identical product result |
| cheap live SDK run | local-only / Phoenix | trace parity and bounded overhead |
| privacy fixtures | Phoenix | zero forbidden fields |
| Phoenix connection failures | unavailable | complete local artifacts |
| short-lived eval worker | Phoenix | bounded flush, no missing terminal trace |
| recorded real-robot-shaped run | disabled / unavailable | no control-path dependency |
| existing run directory regrade | disabled | identical grader/aggregate result |
| two runs + continuation | Phoenix | one global processor, no duplicate/closed-sink writes |

Live-provider and Docker/self-host proofs follow the repo live verification
policy. They require documented readiness and cost/resource identity; a
material expansion beyond the approved PoC stops for review.

## Acceptance Criteria

- OpenAI remote trace export is absent and no `OPENAI_API_KEY` is required.
- Phoenix is not imported by product domain, MCP, backend, safety, or checker
  modules; integration is concentrated in the telemetry adapter and maintainer
  projection command.
- A Robot Run succeeds with Phoenix disabled, unreachable, unauthorized, or
  returning 5xx, with complete local canonical evidence.
- Phoenix renders one coherent Agent/LLM/Tool hierarchy correlated to the local
  run, operator session, and eval trial.
- Startup with `OPENAI_API_KEY` both absent and present installs no OpenAI
  backend exporter and makes no OpenAI trace-ingest request.
- Provider-returned cache and reasoning usage are preserved when available and
  explicitly unavailable when absent; no synthetic cache-hit inference.
- Dataset/prompt publication is idempotent and one-way by digest.
- Private truth, secrets, raw images/maps, and raw tool/model payloads fail the
  export denial tests.
- No duplicated production support for Langfuse remains.
- Phase 5 removes only proven generic duplication; offline audit, regrade,
  privacy, and robot-domain reports remain functional without Phoenix.

## Risks And Stop Gates

- **Instrumentor ownership:** OpenInference may replace SDK processors when
  configured exclusively. Stop if it cannot coexist predictably with the local
  canonical adapter during migration.
- **Provider usage drift:** non-OpenAI providers may omit or reshape cache and
  reasoning usage. Record unavailability; do not add provider-specific guesses
  to the generic telemetry interface.
- **Sensitive defaults:** OpenInference/Phoenix may capture inputs or outputs by
  default. Stop on any denial-test leak.
- **Global processor lifecycle:** repeated registration can duplicate export and
  retain closed-run processors. Registration-once is an acceptance gate.
- **Short-lived worker loss:** explicit bounded flush is required, but it must
  not make product completion depend on Phoenix acknowledgement.
- **Operational envelope:** production placement, authentication, retention,
  backup/deletion, and resource cost are unresolved until the Phase 1 report and
  user gate. Local PoC approval does not imply shared deployment approval.
- **Two-source drift:** stop any proposal for bidirectional prompt/dataset sync
  or runtime use of mutable Phoenix state.
- **Platform expansion:** Phoenix prompt/eval features do not authorize moving
  simulator lifecycle, private graders, CloudML placement, or promotion policy.

## Alternatives

### Langfuse OSS

Use only if Phoenix fails a material PoC gate and Langfuse demonstrably passes
it. Langfuse offers a broader integrated LLM engineering product, but its
self-host footprint and product-specific surface are larger, and its OpenAI
Agents SDK integration still relies on OpenTelemetry/OpenInference mechanics.

### Retain Current Local-Only System

This remains the fallback if neither platform satisfies privacy and fail-open
requirements. It has the strongest offline determinism and lowest external
operational dependency, but leaves Roboclaws owning generic indexing,
cross-run analysis, prompt/dataset experiment UI, annotation, and visualization.

## Planning Loop Ledger

- Round 1 charter: review demand, canonical/external seam, platform choice,
  privacy, real-robot failure semantics, phase order, and deletion gates.
- Round 1 scouts: entropy, docs-grill, and skeptic reviews all completed with
  `RESULT_STATUS: SUCCESS`; compact artifacts are under
  `~/.cache/skill-runner/runs/20260806-154231-*/`.
- Accepted: canonical-owner inventory, process-level lifecycle spike, explicit
  remote-export suppression, bounded fail-open worker contract, Chat plus
  Responses PoC coverage, production deployment gate, prompt-before-experiment
  phase order, closed redaction schema, replay proof, and deletion matrix.
- Merged: provider fidelity, dependency ownership, and cost/retention evidence
  into the Phase 1 PoC and Phase 2 deployment gate.
- Parked: durable local spool until disconnected trace loss proves demand;
  Langfuse until Phoenix fails a material gate; any broad report deletion until
  the Phase 5 matrix proves it.
- Rejected: permanent dual-platform support, bidirectional prompt/dataset sync,
  generic plugin registry, and report/UI polish without material evidence.
- Round 2 not run: all three scouts converged on the same seam and remaining
  questions are implementation defaults or explicit user-review gates.
- Plan-aware eval recommendation succeeded at
  `output/eval-harness/20260806T075022Z/eval_harness.json`; it selected 29
  potential focused rows and executed none. Live rows remain behind the Phase 1
  provider-readiness gate; user authorization cleared the former cost concern
  because the selected routes use an existing token plan or internal free model.
- Planning-loop status: complete; implementation was approved by the explicit
  2026-08-07 implementation request. The separate
  live-provider, production-adapter, and shared-deployment gates remain hard
  stops.
- Phase 0 status: complete. `roboclaws.agents.experiment_telemetry` owns the
  dependency-free contract and registration-once SDK router; ADR-0149 and the
  Phase 0 owner/parity inventory record the durable decision and current
  evidence ownership. Changed-code review fixed async binding isolation,
  callback/closure races, normalized artifact identity, and observable bounded
  lifecycle degradation. Focused telemetry/runtime tests and the full agents
  unit suite pass.
- Phase 1 status: complete through both authorized live wire families. The bounded
  deterministic fixture, real fail-open OpenInference/OTLP adapter, locked
  dependencies, healthy localhost Phoenix deployment, ingestion hierarchy,
  privacy/failure/latency fixtures, volume estimate, and local report are
  complete. Kimi Chat produced one trace with 18 spans and MiniMax Responses
  produced one successful trace with 26 spans; both have closed run/session/
  trial identity and zero raw sensitive values. The first Responses attempt is
  retained as a real turn-budget error trace. `uv lock --check`, repo-wide
  Ruff/format, the full standalone pytest suite, Compose validation, and
  changed-code reviews pass. MiniMax model/token attributes are unavailable in
  the pinned OpenInference projection but remain in the local sanitized event
  stream; no synthetic Phoenix fields are added.

## Recommended Next Action

Reconcile the completed Phase 1 evidence and stop at the separate Phoenix
production-adapter selection gate. Production placement, authentication,
retention, backup/deletion, and resource decisions remain later review gates.
