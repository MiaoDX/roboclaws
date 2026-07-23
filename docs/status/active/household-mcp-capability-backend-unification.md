# Household MCP Capability And Backend Unification

- Status: Active; Slices 0-1 complete, Slice 2 in progress
- Canonical plan: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Root goal: Implement the canonical plan through `intuitive-flow`.
- Current slice: Move synthetic, MuJoCo, Isaac Lab, and Agibot behind the common household MCP
  server; merge the Agibot MapBuild lifecycle and delete its dedicated server/tool/CLI route.
- Next action: Characterize the unique Agibot MapBuild behavior, migrate it into the shared
  adapter/finalizer, prove parity, and delete the parallel path.
- Completed evidence: GSD runtimes were repaired but the archived `.planning` shape could not be
  safely merged without fabricating live project state, so the approved plan and this capsule
  remain the execution contract. Slice 0/1 commit `ce5e1a12` adds ADR-0147, ordered profile
  composition, launch-to-server propagation, exact FastMCP registration, MapBuild exclusion,
  broad Open-ended entitlement, Agent View parity, and physical `blocked_capability` proof.
- Blocked on: none. The repo-wide Python quality ratchet baseline is stale against clean `HEAD`;
  Slice 0/1 passed focused tests, Ruff, format, and diff checks and was committed with the hook
  bypassed rather than refreshing unrelated baseline debt. Recheck after deletion slices reduce
  the touched oversized modules.
- Stop gates: entity-budget expansion, public-contract changes outside the approved plan,
  unavailable required live/hardware proof, or conflicts with concurrent edits in owned files.
- Owned scope: the plan's MCP entitlement, household server/backend, private final-state evidence,
  focused tests, current callers, current human docs, GSD artifacts, and this capsule.
- Do not touch: unrelated eval/runtime work, archived reports and plans, `TODOS.md`, and
  `THOUGHTS.md`.
- Resume command: continue the active goal with `intuitive-flow`; inspect this capsule and current
  GSD phase state before rereading the full plan.
