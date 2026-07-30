# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 6 runtime inventory behavior split
- Last proven evidence: the operator-console client loads ten native ES modules with one mutable state owner and a 180-line composition entrypoint; focused tests, browser bundle/syntax, real Chromium workflows, responsive layouts, and static ratchets pass
- Completed batch: Waves 0-5 and Wave 6 item 1 are complete; the Python graph remains 338 modules / 993 edges with zero SCCs, bidirectional pairs, or package-to-script violations, and oversized Python modules remain at 63
- Next slice: split `operator_console/runtime_inventory.py` into inventory sources, task model, blocker policy, and host probes without facades or duplicated state
- Next proof: focused inventory/readiness/launcher/server contracts, unchanged runtime payloads, static ratchets, architecture graph, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
