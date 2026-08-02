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
- Current slice: MolmoSpaces scene-bundle backend ownership.
- Last proof: session-live and operator-console focused tests passed (26 tests); startup failure now
  restores all temporary process-environment changes.
- Completed slices: session-live environment restoration.

## Next Action

Replace the scene-bundle generator's generic household session/private backend access with its
concrete MolmoSpaces authoring owner, then run its contract tests.

## Stop Condition

All five plan checklist items complete with focused and final proof; public contracts unchanged.

## No-Touch Scope

- baseline/catalog publication
- live providers, simulators, or physical robots
- unrelated plans, `TODOS.md`, and `THOUGHTS.md`

## Parked

See the canonical plan.
