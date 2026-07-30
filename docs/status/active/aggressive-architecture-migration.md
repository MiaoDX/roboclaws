# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 direct/MCP run-artifact ownership convergence
- Last proven evidence: all six module SCCs are absent; 123 household runtime/MCP contract tests, architecture ratchet, Ruff/format, quality ratchet, stale-import, and diff gates pass
- Completed batch: Wave 0 complete; six Wave 1 SCC slices reduce the graph from six SCCs to zero without compatibility facades
- Next slice: merge common direct/MCP run-artifact assembly and validation into `realworld_run_artifacts`, retaining thin adapters and the current dictionary schema
- Next proof: direct/MCP artifact fixtures and consumers, privacy/schema parity, architecture ratchet, Ruff/format, quality ratchet, stale-owner absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
