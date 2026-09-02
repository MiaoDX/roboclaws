# Phase 1 Context

Source: `docs/plans/2026-09-01-state-first-context-manager.md` (PRD express path)

## Decisions

- D-01: Keep `openai-agents-sdk` and current MCP/runtime ownership; add a local,
  dependency-light typed snapshot/checkpoint seam.
- D-02: Project from the existing append-only trace/artifact ledger; do not add a
  second event ledger or expose private evaluation truth.
- D-03: Checkpoints are atomic, privacy-bounded artifacts and retain explicit
  revision/provenance plus stale-observation semantics.

## Scope

Define and test the authoritative task snapshot, project successful MCP/tool
events into it, and persist checkpoints at meaningful action/tool boundaries and
context-budget interruption. Existing traces, reports, DINO files, and
`run_result.json` semantics remain unchanged.

## Non-goals

No pre-call assembler, continuation/resume policy, provider-native compaction,
new launch axes, public MCP contract, or real-robot authorization.
