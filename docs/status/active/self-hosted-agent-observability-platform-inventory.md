# Self-Hosted Agent Observability: Phase 0 Inventory

Status: PHASE_0_COMPLETE

Source: `docs/plans/2026-08-06-self-hosted-agent-observability-platform.md`

## Contract Fixture

`roboclaws.agents.experiment_telemetry` owns typed run identity, outcomes,
scores, artifact links, telemetry status, the closed outbound schema, and the
process-level SDK trace router. `ExperimentTelemetry` delegates local writes to
the supplied canonical owner; it has no file format, run directory, spool,
retry, network client, or external backend dependency.

Parity invariant: adding, disabling, or failing outward projection does not
change `run_result.json`, `live_status.json`, `live_timing.json`, MCP
`trace.jsonl`, `openai-agents-events.jsonl`, sanitized SDK spans, checker/eval
results, reports, continuation state, or process exit status.

## Current Caller And Owner Inventory

| Evidence | Current owner / callers | Classification | Phase 0 parity fixture |
| --- | --- | --- | --- |
| SDK Agent/LLM/Tool spans and usage | `drivers/openai_agents_spans.py`; installed by `drivers/openai_agents_live.py`; read by `openai_agents_metric_sources.py` and `openai_agents_metrics.py` | canonical local evidence | same sanitized JSONL events and provider-returned cache/reasoning availability |
| SDK runtime events and retry/racing/compaction events | `drivers/openai_agents_event_log.py` and focused driver helpers; read by metric sources | canonical local evidence | same schemas, ordering, counts, and raw-payload exclusions |
| MCP requests/responses | household MCP runtime owns `trace.jsonl`; continuation and timing readers consume it | canonical local evidence | no telemetry replacement or mutation |
| Budget and context policy | `openai_agents_budget.py`, `openai_agents_compaction.py`, and `openai_agents_run_config.py`; live runner consumes decisions | derived domain evidence | same turn/context decisions and terminal classification |
| Cache, reasoning, latency, retry, and racing metrics | `openai_agents_metrics.py`, `openai_agents_artifact_metrics.py`, `live_timing.py`, and core live-performance readers | derived domain evidence | preserve returned values; record unavailable rather than infer missing usage |
| Continuation state | `household_live_continuation.py` plus `openai_agents_continuation_state.py`; live runner owns attempts | derived domain evidence | same run directory, attempt identity, and success gate |
| Live status and heartbeat | `live_status_writer.py`; `live_status_summary.py` and operator/eval pollers consume it | canonical local evidence | identical terminal status and exit behavior |
| Product result, checker, and reports | household runtime/checker/report owners; live and eval summaries consume artifacts | canonical and derived domain evidence | same `run_result`, checker authority, report links, and regrade inputs |
| Eval trial identity, grader output, aggregate | `roboclaws.evals` contracts, grading, result persistence, and reports | canonical private/domain evidence | only explicitly allowlisted final scores and public identity are future projection candidates |
| Public run/span/score/artifact identity | typed Phase 0 contract | future generic projection | one-way, digest-bound, closed schema only |

## Phase 0 Proof Boundary

- Malicious fixtures deny secrets, credentials, endpoints, private truth, raw
  tool arguments/results, absolute paths, oversized strings, raw image fields,
  and large map fields.
- SDK startup with `OPENAI_API_KEY` absent and present leaves exactly one local
  router and no `BackendSpanExporter` in the processor list.
- Two sequential runs, one continuation, and concurrent task contexts receive
  each callback once; closure waits for in-flight callbacks and late callbacks
  cannot write to a closed sink.
- Flush and shutdown return within their caller deadline even when work blocks;
  degraded lifecycle counts are recorded without raw exception details.

Next gate: Phase 1 Phoenix PoC and its user review decisions. It is outside this
artifact and has not been started.
