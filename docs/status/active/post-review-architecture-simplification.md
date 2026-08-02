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
- Current slice: canonical scratchpad filename.
- Last proof: 68 eval-harness/CLI/Just tests passed; structured overrides now use the canonical
  parser registry directly, and the unused selector CLI/parser is removed.
- Completed slices: session-live environment restoration; MolmoSpaces authoring backend ownership;
  direct/MCP household artifact ownership; eval mapping dispatch.

## Next Action

Use `agent_scratchpad.json` as the only live scratchpad filename and delete fallback migration.

## Stop Condition

All five plan checklist items complete with focused and final proof; public contracts unchanged.

## No-Touch Scope

- baseline/catalog publication
- live providers, simulators, or physical robots
- unrelated plans, `TODOS.md`, and `THOUGHTS.md`

## Parked

See the canonical plan.
