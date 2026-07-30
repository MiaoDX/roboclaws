# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 console launcher/readiness contract ownership
- Last proven evidence: eval CLI/runner SCC absent, only CLI imports runner, 245 worker tests and 150 root source/CLI contracts pass, and graph/diff gates pass
- Completed batch: Wave 0 complete; three Wave 1 SCC slices reduce the graph from six SCCs to three without compatibility facades
- Next slice: move the console launcher/readiness shared error/value into a console-owned contract so readiness no longer imports launcher
- Next proof: console launcher/readiness/routes contracts, architecture ratchet, Ruff/format, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
