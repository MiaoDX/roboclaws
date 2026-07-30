# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 console interactions/state artifact ownership
- Last proven evidence: launcher/readiness SCC absent, full operator-console suite passes, host console HTTP inventory smoke passes, and Ruff/format/graph/diff gates pass
- Completed batch: Wave 0 complete; four Wave 1 SCC slices reduce the graph from six SCCs to two without compatibility facades
- Next slice: move operator-message artifact reading to state or a narrow artifact reader, preserving interactions-to-state direction
- Next proof: console interactions/state/session/control contracts, host-runtime smoke, architecture ratchet, Ruff/format, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
