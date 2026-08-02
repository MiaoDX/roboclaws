# Post-Review Architecture Simplification

Owner/session: root Codex intuitive-flow
Started: 2026-08-02
State: active

## Scope

Execute the five approved architecture cleanup candidates without changing public contracts.

## Source Of Truth

- Plan: `docs/plans/2026-08-02-post-review-architecture-simplification.md`

## Current State

- Latest user intent: execute all approved candidates via intuitive-flow.
- Current slice: changed-code review and final verification.
- Last proof: scratchpad unit/skill/MCP tests passed (11 tests); `cleanup_scratch` has no live code,
  skill, test, Just, or script references, and migration logic is removed.
- Completed slices: session-live environment restoration; MolmoSpaces authoring backend ownership;
  direct/MCP household artifact ownership; eval mapping dispatch; canonical scratchpad filename.

## Next Action

Run diff-scoped changed-code review, full deterministic proof, and human-doc alignment; then close
the canonical plan and remove this capsule.

## Stop Condition

All five plan checklist items complete with focused and final proof; public contracts unchanged.

## No-Touch Scope

- baseline/catalog publication
- live providers, simulators, or physical robots
- unrelated plans, `TODOS.md`, and `THOUGHTS.md`

## Parked

See the canonical plan.
