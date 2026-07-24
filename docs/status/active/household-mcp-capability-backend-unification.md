# Household MCP Capability And Backend Unification

- Status: BLOCKED_NEEDS_LOCAL_VALIDATION; all locally modifiable work and B1/Isaac proof complete
- Canonical plan: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Root goal: Implement the canonical plan through `intuitive-flow`.
- Latest user intent: Defer real Agibot testing; complete every other locally modifiable item.
- Current slice: Slices 0-4 are complete. B1 route validation uses the authoritative bundle
  occupancy grid, and direct/live recipes copy required B1 proof artifacts into each seed run.
- Last proven evidence: `output/household-mcp-proof/b1-mapbuild-direct-fixed/0724_0947` passes the
  strict checker with 5/5 public waypoints, 25/25 Grounding DINO observations, 100 robot-view
  images, 1.0 sweep coverage, Runtime Metric Map, Base Metric Map, waypoint honesty, and B1 robot
  consumption proof. The focused map/recipe contract set passes 182 tests; repo-wide Ruff, format,
  and diff checks pass. Full pytest reaches 100% with seven reproducible out-of-scope failures in
  Mimo default-model assertions, CloudML `/mnt` archive handling, and operator-console wrapper-lock
  readiness.
- Completed slice summary: Exact task-scoped profiles, one household MCP server/runner/checker,
  evaluator-private final-state evidence, canonical owner renames, stale surface deletion, SDK and
  eval matrices, Isaac runtime smoke, and B1 product proof are complete.
- Next action: None while the Agibot hold remains. After explicit operator resume and restored
  discovery access, rerun the non-motion raw-FPV status gate before considering movement.
- Blocker fingerprint: `external-hardware/agibot-discovery-unreachable-and-user-deferred`.
- Blocked on: Agibot discovery at `10.42.1.101:2379` is unreachable, and physical validation is
  deferred by operator request. Real movement still requires localization, E-stop, safety gates,
  and operator authorization. The unrelated repo-wide Python quality-ratchet debt remains
  untouched.
- Stop gates: Any Agibot hardware probe or movement while deferred; entity-budget expansion;
  public-contract changes outside the approved plan; conflicts with concurrent owned-file edits.
- Do not touch: Real Agibot testing, unrelated eval/runtime work, quality-ratchet baselines,
  archived reports/plans, `TODOS.md`, and `THOUGHTS.md`.
- Resume command: After explicit Agibot-validation approval, continue this goal with
  `intuitive-flow` and read this capsule first.
