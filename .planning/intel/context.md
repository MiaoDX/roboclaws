# Context

## Current implementation gap

The existing filter performs item-level compaction after the budget guard, so the configured 64k soft limit is not a canonical reconstruction trigger and observed MiMo runs reached approximately 97-98k input tokens against a 96k fail-closed hard limit. The July plan's profile plumbing is implemented, but canonical snapshot reconstruction and resumable checkpoint semantics remain incomplete. `source: docs/plans/2026-09-01-state-first-context-manager.md`

## Target flow

Append-only run events and immutable artifacts project into a typed task snapshot/checkpoint, which feeds a pre-call estimator and context assembler containing fixed system contract, canonical snapshot, current subgoal evidence, bounded recent raw overlap, and expected-output reserve. `source: docs/plans/2026-09-01-state-first-context-manager.md`

## Stop gates

Pause for review before changing public MCP/tool/launch contracts, private-data boundaries, safety policy, provider infrastructure, or durable artifact schemas consumed outside this runtime. Avoid duplicate canonical owners and narrow scope if action-critical state is lost. `source: docs/plans/2026-09-01-state-first-context-manager.md`

## Verification

Required commands are `ruff check .`, `ruff format --check .`, standalone pytest, and focused eval recommendation/execution. Local camera-grounded product proof is conditional on network/provider/runtime readiness; unavailable prerequisites must be recorded with guarded preflight output. `source: docs/plans/2026-09-01-state-first-context-manager.md`

