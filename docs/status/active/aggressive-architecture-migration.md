# Aggressive Architecture Migration

- Status: ACTIVE
- Source plan: `docs/plans/2026-07-30-aggressive-architecture-migration.md`
- Control plane: current Codex root goal session
- Project-status writer: current Codex root goal session
- Latest user intent: execute the complete approved plan through `intuitive-flow`
- Current slice: Wave 6 OpenAI live-runtime behavior split
- Last proven evidence: runtime inventory has four explicit behavior owners and a 61-line composition module; the full operator-console suite, focused contracts, Ruff/format, static ratchets, and no-facade searches pass
- Completed batch: Waves 0-5 and Wave 6 items 1-2 are complete; the graph is 342 modules / 1,011 edges with zero SCCs, bidirectional pairs, or forbidden edges, and oversized Python modules decreased to 62
- Next slice: split OpenAI live runtime into run configuration, retry model, provider racing, event log/history, image and grounded memory, compaction, and event projection while preserving provider and cost behavior
- Next proof: focused SDK runtime/model-input/budget/metrics contracts, provider mock and guarded live proof, artifact/privacy/cost parity, static ratchets, graph, and `git diff --check`
- Stop condition: all eight waves and final deterministic/product gates pass, or a plan-defined external/public/schema/local-validation blocker is proven
- No-touch scope: public launch/schema/privacy/provider behavior; immutable historical evidence; publication; EULA acceptance; real-robot motion; unrelated active capsules
- Parked work: B1 authoring deletion remains parked until package-owned rebuild equivalence is proven
