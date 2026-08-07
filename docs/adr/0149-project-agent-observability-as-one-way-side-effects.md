# ADR-0149: Project Agent Observability As One-Way Side Effects

Status: Accepted

Date: 2026-08-07

## Context

Roboclaws needs cross-run observability without making an observability service
part of robot execution or duplicating canonical run evidence. SDK tracing also
has a process-global default exporter that can send data to OpenAI when a key is
present, while Roboclaws runs need stricter private-evidence boundaries.

## Decision

Roboclaws owns one dependency-free `ExperimentTelemetry` contract. Its required
local adapter is only a facade over existing artifact owners. Optional external
telemetry is a bounded, best-effort side effect over a closed allowlist; unknown
fields and forbidden values are denied. Prompt, dataset, score, and artifact
identity project outward by immutable identity and digest. External edits never
change runtime behavior, graders, promotion, or physical authorization.

One process-level runtime calls the OpenAI Agents SDK
`set_trace_processors(...)` exactly once, replacing the default remote exporter.
Its stable local router binds traces to run-owned sinks and closes those sinks
without changing the global processor list. External backends remain absent
from this Phase 0 decision and contract fixture.

## Consequences

- Local artifacts remain complete and auditable without an external service.
- `OPENAI_API_KEY` does not enable OpenAI trace ingestion.
- Export cannot carry arbitrary metadata, raw payloads, private truth, host
  paths, secrets, provider endpoints, images, or maps.
- Export failure may degrade observability but cannot alter product outcome.
- A future external adapter must fit this one-way contract and pass its denial
  suite before deployment or dependency approval.

## Rejected Alternatives

- Per-run SDK processor registration, which duplicates callbacks and retains
  closed sinks.
- A second local telemetry event store beside canonical run artifacts.
- Bidirectional prompt, dataset, evaluator, or runtime configuration sync.
- Keeping the SDK default OpenAI backend exporter alongside local routing.
