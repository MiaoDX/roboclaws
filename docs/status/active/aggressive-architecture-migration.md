# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 5 product subsystem package ownership
- Last proven evidence: 167 focused planner contracts and the end-to-end proof-bundle product gate pass after retiring the standalone diagnostic harness/checker; the retained low-level runner is explicit-output only and generic Isaac smoke remains current
- Completed batch: Waves 0-4 are complete; 60 retired files/recipes and 34,874 lines are removed while historical outputs and current product behavior remain intact; the graph is 239 modules / 711 edges with zero SCCs or bidirectional pairs, and oversized modules decrease to 67
- Next slice: move the active MolmoSpaces subprocess worker and runtime dependencies into `roboclaws/backends/molmospaces` with a package module CLI and forward-only callers
- Next proof: subprocess protocol/artifact parity, package CLI and backend integration, zero replaced script callers, architecture/static ratchets, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
