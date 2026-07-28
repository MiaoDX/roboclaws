# ADR-0147: Use Task-Scoped Household MCP Entitlement

Status: Accepted

Date: 2026-07-23

Plan:
[`docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`](../plans/2026-07-23-household-mcp-capability-backend-unification.md)

## Context

Household launch declarations already name capability profiles, but the active
MCP server registers a cleanup-shaped tool superset. Evidence-lane selection
has also been used to describe the public tool list even though evidence and
authority are independent concerns. This makes prompt-only restrictions look
like authorization and conflates an absent task capability with a backend that
cannot currently execute an entitled capability.

## Decision

Resolve an ordered tuple of required capability profiles before each Robot Run
and keep it immutable for the run. `LaunchPlan` and its serialized
`GoalContract` carry that tuple into the household MCP server process. The MCP
profile router validates the complete composition and the server registers
exactly its ordered public tool union.

Evidence lanes affect observations only. They do not add or remove tool
entitlement. Calls outside the registered union are rejected even when an
internal backend handler exists. Agent View tool metadata is derived from the
actual registered union.

Entitlement and backend availability remain separate:

- a capability not required by the task has no registered tool;
- a required tool that the selected backend cannot execute remains registered
  and returns structured `blocked_capability` evidence.

MapBuild requires `household_world` and `household_episode`. Cleanup and
Open-ended require `household_world`, `household_manipulation`, and
`household_episode`. Open-ended is deliberately broad at the task boundary;
there is no model-backed prompt classifier or dynamic escalation.

The target architecture has one household MCP server with backend adapters.
The server owns transport and immutable registration; adapters own primitive
availability, provenance, and blockers. Private evaluator truth remains
outside profiles, MCP responses, GoalContract, and Agent View.

## Consequences

- SDK tool caching and traces observe a stable tool surface for each run.
- MapBuild cannot discover or invoke manipulation tools through MCP.
- Physical Cleanup may expose manipulation while truthfully returning
  `blocked_capability` until the backend is ready.
- Server startup fails when resolved capability profiles are missing, unknown,
  duplicated, or compose duplicate/conflicting descriptors.
- No compatibility alias or evidence-lane fallback is provided.
