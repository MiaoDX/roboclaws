# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 manipulation contract ownership
- Last proven evidence: focused Wave 0 tests, Ruff/format, quality ratchet, graph self-comparison, and `git diff --check` pass; authoritative baseline is six SCCs and five bidirectional package edges
- Completed batch: Wave 0 complete with exact LOC/disposition baseline, deletion consumer ledger, fixture index, durable six-SCC/five-edge AST baseline, and static-gate integration
- Next slice: move manipulation request/result/backend/provenance values to `household/manipulation_contract.py` and migrate the complete caller set without a facade
- Next proof: manipulation/backend/planner focused contracts, architecture ratchet, Ruff/format, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
