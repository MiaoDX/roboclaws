# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 eval CLI/runner dependency direction
- Last proven evidence: long-horizon SCC absent, zero stale old-path value imports, 177 focused eval tests pass, and full Ruff/format/graph/diff gates pass
- Completed batch: Wave 0 complete; Wave 1 manipulation and long-horizon contract slices committed or ready, reducing the graph from six SCCs to four without facades
- Next slice: remove the eval runner back-import into CLI, migrate all callers, and preserve CLI/runner behavior
- Next proof: eval CLI/runner/source contracts, architecture ratchet, Ruff/format, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
