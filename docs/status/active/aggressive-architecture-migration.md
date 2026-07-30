# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 5 product subsystem package ownership
- Last proven evidence: the package-owned Isaac worker and smoke checker pass 183 focused tests; every production module is at most 694 lines, the graph has zero SCCs/pairs, all replaced callers are absent, and guarded harness defaults leave EULA acceptance off
- Completed batch: Waves 0-4 plus the Wave 5 MolmoSpaces and Isaac slices are complete; 112 retired files/recipes and 56,021 raw lines are removed or moved while historical outputs and current product behavior remain intact; the graph is 311 modules / 884 edges with zero SCCs or bidirectional pairs, and oversized modules decrease to 65
- Next slice: split the cleanup checker between household structural validation and eval grading, leave a thin CLI, and remove the live runner's package-to-script execution
- Next proof: exact cleanup artifact/schema/privacy parity, product validation and benchmark grading ownership, zero cleanup-checker script execution from packages, architecture/static ratchets, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
