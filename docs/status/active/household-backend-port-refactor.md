# Household Backend Port Refactor

- Capsule status: ACTIVE
- Canonical gate: `docs/plans/2026-08-02-household-backend-port-refactor.md`
- Task control plane: current Codex root goal
- Project-status writer: current Codex root goal
- Latest user intent: execute the approved typed backend seam via `intuitive-flow`
- Current slice: changed-code review and final broader verification
- Blocker fingerprint: none
- Last proven evidence: full household unit/contract, cleanup checker, and architecture graph tests
  pass with only one existing Pillow deprecation warning; Ruff, format, quality ratchet, diff hygiene,
  and runtime architecture graph pass at 528 modules, 1,653 edges, zero SCCs, zero bidirectional
  package pairs, and zero policy violations
- Completed slice batch: typed backend seam complete; five single-implementation Protocols removed in
  favor of concrete type-only annotations; two cross-package private imports replaced by public
  owner APIs; runtime graph now excludes non-executing `TYPE_CHECKING` imports with regression proof
- Next slice: changed-code review, broader repo proof, and final documentation alignment
- Next proof: changed-code review over `a9caee2f..HEAD`, then `just agent::verify` or the documented
  equivalent broad deterministic gate
- Stop condition: canonical checklist complete with no adapter escape hatch and all required proof
  green; stop earlier for a public-contract change or unavailable external proof
- No-touch scope: public launch/MCP/schema/artifact/provider contracts, simulator behavior, Agibot
  hardware, unrelated evals, `TODOS.md`, and `THOUGHTS.md`
- Parked work: physical Agibot validation; public plugin architecture; unrelated module layout
