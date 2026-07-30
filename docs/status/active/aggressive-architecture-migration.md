# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 1 long-horizon contract ownership
- Last proven evidence: zero stale manipulation-contract imports, target SCC absent, root affected suite passed, broader worker suite passed except four unchanged loopback tests blocked by worker socket permissions, and Ruff/format/graph/diff gates pass
- Completed batch: Wave 0 complete; Wave 1 manipulation contract slice migrated 39 callers to one canonical owner with no facade and net code deletion
- Next slice: move long-horizon pure spec/value ownership to `evals/long_horizon_contract.py`, migrate all consumers, and remove the grader/runner SCC
- Next proof: long-horizon grader/runner contracts, architecture ratchet, Ruff/format, stale-import absence, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
