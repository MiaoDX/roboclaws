# Aggressive Architecture Migration

- Status: BLOCKED
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: blocked at the final guarded Isaac Sim import proof
- Blocker fingerprint: external EULA acceptance; `runtime_import_isaacsim` requires explicit Omniverse EULA acceptance, which this migration must not perform
- Last proven evidence: Ruff/format and the standalone full suite pass; deterministic and direct product eval rows pass; repaired SDK session-live and cleanup live rows pass; browser QA passes; B1 readiness passes with a verified overlay and navigation support disabled
- Completed batch: Waves 0-7 and every agent-owned final gate are complete; timed-out session evals now stop their console child before returning, preventing visual-backend slot leakage
- Next hypothesis: none within agent authority; Isaac Sim import should become runnable only after a human separately accepts the Omniverse EULA
- Next proof: after that separate human decision, rerun the guarded Isaac runtime smoke; current blocker evidence is `output/isaaclab/preflight/aggressive-architecture-final/0731_112216/preflight.json`
- Stop condition: reached; the plan-defined external local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
