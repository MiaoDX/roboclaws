# State-First Context Manager

## Core Value

Keep household OpenAI Agents SDK runs within provider context limits by
reconstructing model input from authoritative task state, while preserving
complete artifacts and making context-budget interruption resumable.

## Milestone

**Active milestone:** v1.99 State-First Context Manager

This milestone is initialized from the conflict-free PRD ingest dated
2026-09-01. It extends the shipped context-management/profile contract and
keeps existing MCP, runtime, artifact, and launch-axis ownership.

## Constraints

- Keep `openai-agents-sdk` and existing MCP/runtime ownership.
- Exclude private scoring truth, credentials, raw prompts, and full payloads
  from model context and telemetry.
- Preserve append-only events and immutable, content-addressed artifacts.
- Never raise hard limits silently, fall back to `baseline`, or replay the
  same over-limit payload.
- Public contract, safety, provider infrastructure, or external artifact
  schema changes require a review stop gate.

## Success Metric

All four PRD requirements map exactly once to observable phase criteria, and
the resulting context behavior is checkpointed, bounded, and resumable.
