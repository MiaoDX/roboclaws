# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 bidirectional package-edge removal
- Last proven evidence: operator-message and JSONL protocol ownership is in `core`; full root operator-console, MCP, SDK resume/handoff, session-live, and static ratchets pass
- Completed batch: Wave 0 complete; all six module SCCs are absent, direct/MCP artifacts and provider/operator contracts are converged, and bidirectional package pairs decrease from five to two
- Next slice: remove the remaining `agents -> launch` and `household -> launch` reverse edges while preserving launch dispatch and SDK lifecycle ownership
- Next proof: launch/agent/household caller parity, zero-SCC and zero-bidirectional-edge ratchet, Ruff/format, quality ratchet, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
