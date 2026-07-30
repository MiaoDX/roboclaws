# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 bidirectional package-edge removal
- Last proven evidence: shared direct/MCP artifact assembly is canonical in `realworld_run_artifacts`; producer, checker, report, privacy/schema, architecture, Ruff/format, quality, duplicate-owner, and diff gates pass
- Completed batch: Wave 0 complete; all six Wave 1 module SCCs are absent and the direct/MCP artifact seam is converged without compatibility facades or schema changes
- Next slice: remove the five bidirectional package edges one owner cluster at a time using the Wave 0 reverse-import matrix
- Next proof: per-edge caller/contract tests, zero-SCC and decreasing bidirectional-edge ratchet, Ruff/format, quality ratchet, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
