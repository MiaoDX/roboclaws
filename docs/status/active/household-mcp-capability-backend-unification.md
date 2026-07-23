# Household MCP Capability And Backend Unification

- Status: Active; Slices 0-2 complete, Slice 3 in progress
- Canonical plan: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Root goal: Implement the canonical plan through `intuitive-flow`.
- Current slice: Define private backend-neutral final-state evidence, exact simulator and
  unavailable/inconclusive physical producers, and migrate long-horizon grading without a public
  evidence leak.
- Next action: Characterize current long-horizon grader inputs and private artifact ownership,
  add `FinalStateEvidence`, migrate producers/consumers, and run privacy-leak proof.
- Completed evidence: Slice 0/1 commit `ce5e1a12` adds exact profile composition and entitlement.
  Slice 2 converges synthetic, MuJoCo, Isaac Lab, and Agibot on one FastMCP server, one live runner,
  and one checker path; deletes five dedicated Agibot MapBuild implementation modules plus their
  owner-only tests; preserves Runtime Metric Map, trace, Agent View, report, readiness, camera
  grounding, locks, and safety behavior; and passes the affected contract/route/checker suites,
  Ruff, format, and stale-reference checks.
- Blocked on: none. The repo-wide Python quality ratchet still reports unrelated stale baseline
  growth plus touched oversized modules; Slice 2 removed its deleted-file baseline entry and its
  local checker complexity delta, while Ruff, format, diff, and focused tests pass. Do not refresh
  unrelated baseline debt.
- Stop gates: entity-budget expansion, public-contract changes outside the approved plan,
  unavailable required live/hardware proof, or conflicts with concurrent edits in owned files.
- Owned scope: the plan's MCP entitlement, household server/backend, private final-state evidence,
  focused tests, current callers, current human docs, GSD artifacts, and this capsule.
- Do not touch: unrelated eval/runtime work, archived reports and plans, `TODOS.md`, and
  `THOUGHTS.md`.
- Resume command: continue the active goal with `intuitive-flow`; inspect this capsule and current
  GSD phase state before rereading the full plan.
