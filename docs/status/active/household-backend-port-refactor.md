# Household Backend Port Refactor

- Capsule status: ACTIVE
- Canonical gate: `docs/plans/2026-08-02-household-backend-port-refactor.md`
- Task control plane: current Codex root goal
- Project-status writer: current Codex root goal
- Latest user intent: execute the approved typed backend seam via `intuitive-flow`
- Current slice: internalize five runtime-only Protocols and replace two cross-package private
  imports
- Blocker fingerprint: none
- Last proven evidence: slice 1 has 48 focused unit/contract tests passing; Ruff, format, and diff
  hygiene pass; architecture graph has 528 modules, 1,653 edges, zero SCCs, zero bidirectional
  package pairs, and zero policy violations
- Completed slice batch: canonical `HouseholdBackendPort` and typed runtime evidence added; adapter
  is private; planner/navigation/runtime/artifact callers no longer reach concrete adapter state
- Next slice: protocol internalization and cross-package private-import cleanup
- Next proof: focused owner/caller tests, stale-reference searches, Ruff, format, architecture graph,
  then broader standalone household proof
- Stop condition: canonical checklist complete with no adapter escape hatch and all required proof
  green; stop earlier for a public-contract change or unavailable external proof
- No-touch scope: public launch/MCP/schema/artifact/provider contracts, simulator behavior, Agibot
  hardware, unrelated evals, `TODOS.md`, and `THOUGHTS.md`
- Parked work: physical Agibot validation; public plugin architecture; unrelated module layout
