# Decisions

No ADRs were included in this ingest set.

The source PRD records the following execution decisions (non-locked, PRD-level context):

- State-first context management remains on `openai-agents-sdk` and current MCP/runtime ownership; local domain context management uses a replaceable storage/retrieval adapter seam. `source: docs/plans/2026-09-01-state-first-context-manager.md`
- The July context-management profile/default migration remains current; this plan adds canonical task snapshot, pre-call budget reconstruction, and resumable checkpoint semantics. `source: docs/plans/2026-09-01-state-first-context-manager.md`
- No new ADR is required unless the snapshot becomes a durable public/MCP contract, changes private-data boundaries, or provider-native compaction is accepted. `source: docs/plans/2026-09-01-state-first-context-manager.md`

