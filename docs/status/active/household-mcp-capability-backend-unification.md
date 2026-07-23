# Household MCP Capability And Backend Unification

- Status: BLOCKED_NEEDS_LOCAL_VALIDATION; Slices 0-4 and available proof complete
- Canonical plan: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Root goal: Implement the canonical plan through `intuitive-flow`.
- Current slice: Canonical household owners and stale active surfaces are migrated; available
  deterministic and repo-local SDK product proof is complete.
- Next action: Restore B1 static-costmap connectivity and robot-network access, then rerun B1/Isaac
  MapBuild and the non-motion Agibot status gate. Real Agibot movement still requires localization,
  E-stop, safety gates, and operator authorization.
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
  Isaac logs. The supported `world=b1-map12 backend=isaaclab` MapBuild product route then completed
  real rendering and 25 Grounding DINO observations, but its checker correctly failed at 0.2 sweep
  coverage: four of five canonical waypoints returned `blocked_capability/no_static_costmap_path`.
  MolmoSpaces+Isaac is intentionally retired and is not a missing proof route.
  Agibot's non-motion raw-FPV status probe is blocked because robot discovery at
  `10.42.1.101:2379` is unreachable. All four SDK profile health probes now pass, and the canonical
  `codex-router-responses` focused MapBuild-consumer matrix passes 5/5 across producer, cleanup,
  and open-ended prior/no-prior cases.
- Blocked on: B1 static-costmap paths from `meeting_room_b_inspection` to the other four public
  waypoints are unavailable, and the Agibot discovery service is unreachable. The repo-wide Python
  quality ratchet also reports unrelated stale baseline growth; do not refresh that baseline.
- Stop gates: entity-budget expansion, public-contract changes outside the approved plan,
  unavailable required live/hardware proof, or conflicts with concurrent edits in owned files.
- Owned scope: the plan's MCP entitlement, household server/backend, private final-state evidence,
  focused tests, current callers, current human docs, GSD artifacts, and this capsule.
- Do not touch: unrelated eval/runtime work, archived reports and plans, `TODOS.md`, and
  `THOUGHTS.md`.
- Resume command: continue the active goal with `intuitive-flow`; inspect this capsule and current
  GSD phase state before rereading the full plan.
