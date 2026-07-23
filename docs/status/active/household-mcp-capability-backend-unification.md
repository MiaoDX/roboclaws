# Household MCP Capability And Backend Unification

- Status: GSD handoff blocked by incomplete local GSD installation
- Canonical plan: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Root goal: Implement the canonical plan through `intuitive-flow`.
- Current slice: Ingest the approved plan into one coherent GSD phase and generate its executable
  phase plan.
- Next action: Restore the installed `gsd-ingest-docs` and `gsd-plan-phase` skills, then rerun
  the unchanged GSD handoff request.
- Completed evidence: Repo startup state, plan contract, Flow durable-run route, and GSD routing
  rules inspected on 2026-07-23.
- Blocked on: Both Codex and Claude isolated workers report the required GSD skills as
  unavailable. Workflow sources exist under `~/.claude/get-shit-done/workflows/`, but the
  generated runtime skill directories are absent and the documented sync dependency
  `~/.claude/get-shit-done/bin/install.js` is missing. No `.planning` artifact was fabricated.
- Stop gates: entity-budget expansion, public-contract changes outside the approved plan,
  unavailable required live/hardware proof, or conflicts with concurrent edits in owned files.
- Owned scope: the plan's MCP entitlement, household server/backend, private final-state evidence,
  focused tests, current callers, current human docs, GSD artifacts, and this capsule.
- Do not touch: unrelated eval/runtime work, archived reports and plans, `TODOS.md`, and
  `THOUGHTS.md`.
- Resume command: continue the active goal with `intuitive-flow`; inspect this capsule and current
  GSD phase state before rereading the full plan.
