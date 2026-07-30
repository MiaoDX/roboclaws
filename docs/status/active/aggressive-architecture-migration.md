# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 5 product subsystem package ownership
- Last proven evidence: the MolmoSpaces worker has one package module CLI, all fourteen replaced script paths and callers are absent, and 154 protocol/backend/architecture contracts pass with no package-to-scripts regression
- Completed batch: Waves 0-4 and the Wave 5 MolmoSpaces slice are complete; 74 retired files/recipes and 42,128 raw lines are removed or moved while historical outputs and current product behavior remain intact; the graph is 261 modules / 770 edges with zero SCCs or bidirectional pairs, and oversized modules decrease to 66
- Next slice: move the active Isaac Lab worker and generic runtime-smoke implementation into `roboclaws/backends/isaaclab` while keeping Isaac packages outside the normal `.venv`
- Next proof: Isaac worker protocol and standalone module CLI, generic guarded runtime smoke, zero replaced script callers, architecture/static ratchets, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
