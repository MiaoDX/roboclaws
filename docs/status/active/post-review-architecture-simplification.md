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
- Current slice: direct/MCP household artifact ownership.
- Last proof: MolmoSpaces scene-bundle contract tests passed (6 tests); the authoring script now
  owns its concrete backend directly and has no generic session/private-backend escape.
- Completed slices: session-live environment restoration; MolmoSpaces authoring backend ownership.

## Next Action

Consolidate direct and MCP artifact/result composition behind the existing direct artifact owner,
preserve exact serialized output, and run direct/MCP parity tests.

## Stop Condition

All five plan checklist items complete with focused and final proof; public contracts unchanged.

## No-Touch Scope

- baseline/catalog publication
- live providers, simulators, or physical robots
- unrelated plans, `TODOS.md`, and `THOUGHTS.md`

## Parked

See the canonical plan.
