# Household Backend Port Refactor

- Capsule status: ACTIVE
- Canonical gate: `docs/plans/2026-08-02-household-backend-port-refactor.md`
- Task control plane: current Codex root goal
- Project-status writer: current Codex root goal
- Latest user intent: execute the approved typed backend seam via `intuitive-flow`
- Current slice: define `HouseholdBackendPort`, privatize the adapter, and migrate the direct
  planner/navigation/runtime leak callers
- Blocker fingerprint: none
- Last proven evidence: pre-change architecture graph has 527 modules, 1,647 edges, zero SCCs,
  zero bidirectional package pairs, and zero policy violations; worktree was clean at entry
- Completed slice batch: architecture discovery and engineering review complete; direction A
  selected as phased delivery of the full clean target
- Next slice: protocol internalization and cross-package private-import cleanup
- Next proof: focused backend/planner/navigation tests, Ruff, format check, stale-reference search,
  and architecture graph
- Stop condition: canonical checklist complete with no adapter escape hatch and all required proof
  green; stop earlier for a public-contract change or unavailable external proof
- No-touch scope: public launch/MCP/schema/artifact/provider contracts, simulator behavior, Agibot
  hardware, unrelated evals, `TODOS.md`, and `THOUGHTS.md`
- Parked work: physical Agibot validation; public plugin architecture; unrelated module layout
