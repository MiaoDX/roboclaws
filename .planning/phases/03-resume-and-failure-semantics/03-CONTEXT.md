# Phase 3: Resume And Failure Semantics - Context

**Gathered:** 2026-09-02  
**Status:** Ready for planning  
**Source:** PRD Express Path (`docs/plans/2026-09-01-state-first-context-manager.md`)

## Phase Boundary

Resume a managed SDK run after checkpointed `provider_context_budget_exceeded`
only when the checkpoint is valid and the run is non-terminal; classify invalid,
terminal, exhausted, and non-context provider failures as non-resumable with
actionable aggregate evidence. Phase 1 snapshot/checkpoint and Phase 2
pre-call reconstruction remain canonical owners.

## Locked Decisions

- Keep the OpenAI Agents SDK loop and current household lifecycle ownership.
- Resume from reconstructed snapshot state, never the prior full model input.
- Reuse existing checkpoint/artifact and `run_result.json`/MCP `done` semantics.
- Bound continuation attempts and distinguish recoverable overflow from failures.
- Status/evidence contain digests and aggregate metadata, never sensitive payloads.

## References

- `docs/plans/2026-09-01-state-first-context-manager.md`
- `.planning/phases/01-state-and-checkpoint-schema/01-CONTEXT.md`
- `.planning/phases/02-pre-call-context-assembler/02-CONTEXT.md`
- `.planning/phases/02-pre-call-context-assembler/02-01-PLAN.md`
- `.planning/phases/02-pre-call-context-assembler/02-02-PLAN.md`
- `roboclaws/agents/household_live_lifecycle.py`
- `roboclaws/agents/household_live_continuation.py`

## Non-goals

No provider/model changes, native compaction, public MCP or launch changes,
new event ledger, route rollout, or real-robot authorization.
