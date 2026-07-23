# Household MCP Capability And Backend Unification

- Status: Active; Slices 0-4 complete; available proof complete, physical/provider proof gated
- Canonical plan: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Root goal: Implement the canonical plan through `intuitive-flow`.
- Current slice: Canonical household owners and stale active surfaces are migrated; available
  deterministic and repo-local SDK product proof is complete.
- Next action: Run MolmoSpaces-backed Isaac MapBuild, physical Agibot, and provider-matrix rows in
  an environment with the required scene asset, robot network/operator authorization, and provider
  profiles.
- Completed evidence: Slice 0/1 commit `ce5e1a12` adds exact profile composition and entitlement.
  Slice 2 converges synthetic, MuJoCo, Isaac Lab, and Agibot on one FastMCP server, one live runner,
  and one checker path; deletes five dedicated Agibot MapBuild implementation modules plus their
  owner-only tests; preserves Runtime Metric Map, trace, Agent View, report, readiness, camera
  grounding, locks, and safety behavior; and passes the affected contract/route/checker suites,
  Ruff, format, and stale-reference checks. Slice 3 adds evaluator-private `FinalStateEvidence`,
  grades simulator completion from authoritative state, classifies unobservable physical final
  state as inconclusive, removes Agibot scenario placeholders, and passes long-horizon, privacy,
  simulator, physical-pilot, MCP artifact, checker, Ruff, format, and leak-search proof.
  Slice 4 renames the canonical household server/runtime/backend owners, migrates current callers,
  recipes, checkers, reports, eval catalog, baseline paths, and human docs, deletes superseded
  active modules/tests, and passes 502 focused tests plus 191 rename-relevant live-runner tests.
  Available product/eval proof also passes open-ended SDK (3/3), cleanup capability SDK (3/3),
  session-live SDK (1/1), map-build quality (1/1), scene sampler (16/16), smoke regression (1/1),
  and the post-fix long-horizon smoke (2/2) suites. Isaac runtime smoke now passes with real RTX
  rendering, a generated Phase A USD stage, selected public USD bindings, and four robot-view
  images after `decaf335` made the checker recover the worker's final JSON object from captured
  Isaac logs. This is renderer/USD plumbing evidence only: MolmoSpaces scene loading was not
  attempted, segmentation remains unavailable, and manipulation remains semantic-pose-only.
  Agibot's non-motion raw-FPV status probe is blocked because robot discovery at
  `10.42.1.101:2379` is unreachable. Provider-model matrix rows remain blocked by unavailable
  profiles.
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
