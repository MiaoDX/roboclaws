---
plan_scope: operator-console-ui-maintenance
status: ACTIVE
created: 2026-06-30
last_reviewed: 2026-06-30
campaign_overlay: true
accepted_severities:
  - P1
  - P2
active_capsule: docs/status/active/refactor-operator-console-ui-maintenance.md
---

# Operator Console UI Architecture Maintenance

## Plan Ledger

- Status: ACTIVE
- Current slice: rediscover from current `HEAD` after completing the first clear
  queue item.
- Next action: run the next `$intuitive-reduce-entropy` discovery round against
  the operator-console UI/API surface.
- Blocker: none.
- Last proof: route-alias cleanup proof passed on 2026-06-30.

## Refactor Scope

Run repo-wide architecture maintenance for the standalone operator console UI
surface, centered on:

- `roboclaws/operator_console/static/**`
- `roboclaws/operator_console/server.py`
- `roboclaws/operator_console/routes.py`
- focused operator-console tests and current console docs/plans needed to prove
  the selected slice

The console architecture contract from `ARCHITECTURE.md` remains: the console
starts catalog-approved runs and surfaces state, while robot task strategy stays
outside `roboclaws/operator_console/`.

## Accepted Severities

- P1: live source drift, stale reachable API fields, false-green tests, or
  duplicate owners that can mislead future console work.
- P2: bounded cleanup that removes recurring rediscovery or stale concept
  preservation in the console UI/API/test surface.

## No-Touch Scope

- Do not redesign the operator console UI.
- Do not change robot task strategy, launch catalog semantics, provider
  profiles, live-agent runtime behavior, or hardware/simulator proof routes.
- Do not remove public or external contracts without current evidence that
  known in-repo consumers already use the replacement.
- Do not update `STATUS.md` unless this maintenance run becomes the repo-level
  current focus.

## Verification Inventory

- L0 static/search: exact reference searches for stale keys, route IDs, and UI
  state owners.
- L1 static syntax: `node --check roboclaws/operator_console/static/app.js`.
- L1 focused Python syntax:
  `find roboclaws/operator_console scripts/operator_console -maxdepth 1 -name '*.py' -print0 | xargs -0 -n1 .venv/bin/python -m py_compile`.
- L1 focused tests:
  `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console`.
- L1 lint:
  `.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console`.
- L2 public route/API contract tests:
  `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_console.py::test_operator_console_routes_endpoint_exposes_evidence_lane_matrix tests/unit/operator_console/test_static_assets.py`.
- L3 browser smoke is required only when a slice changes rendered layout,
  interaction behavior, or visual asset loading.

## Campaign Loop

Discovery source: `$intuitive-reduce-entropy` repo entropy / discovery-loop
mode, narrowed to the current operator console UI/API surface.

Checkpoint cadence: after every verified implementation slice or at least every
60-120 minutes during a long run.

Continue criteria: execute only clear P1/P2 slices that delete, merge, or
canonicalize a real console concept, preserve behavior or make an accepted
behavior change, and have focused proof available now.

Stop/park criteria: park candidates needing product decisions, external
contract migration, hardware/manual proof, live provider credentials, broad UI
redesign, or proof unavailable in this checkout.

Saturation stop rule: stop only after a fresh discovery round from current
`HEAD` finds no new clear P1/P2 candidate after deduping against the parked and
rejected-low-value registries.

Consecutive no-clear-candidate passes: 0

## Clear Queue

1. **DONE: Canonicalize `/api/routes` route matrix payload**
   - Severity: P1
   - Entropy source: stale reachable API field / duplicate UI state owner
   - Demand gate: the current orthogonal launch refactor made
     `combinations` the canonical axis matrix; keeping a duplicate `routes`
     field and `state.routes` fallback preserves the old route-card concept
     without a current contract.
   - Owner layer: operator-console server/static API boundary
   - Expected simplification: one server payload owner and one frontend state
     owner for the launch matrix.
   - Behavior-change class: internal API cleanup; known in-repo consumers use
     `payload["combinations"]`.
   - Suggested proof: exact stale-reference search, `node --check`, focused
     routes endpoint/static asset tests.

## Completed Slice Batch Summary

- 2026-06-30: `/api/routes` now exposes only the canonical `combinations`
  launch matrix; the duplicate `routes` alias and frontend `state.routes`
  shadow owner were removed. Known in-repo consumers already read
  `payload["combinations"]`, and the latest-run attach path now looks up
  selections from `state.combinations`. The focused hook target also exposed a
  stale route-catalog test expectation for Agibot Map 12 previews; that test now
  matches current `WORLD_SPECS` and the existing static-asset expectation.
  - Value metrics: stale API fields removed: 1; duplicate UI state owners
    removed: 1; new owners added: 0; public route semantics changed: no.
  - Proof:
    `node --check roboclaws/operator_console/static/app.js`;
    `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_console.py::test_operator_console_routes_endpoint_exposes_evidence_lane_matrix tests/unit/operator_console/test_static_assets.py`;
    `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console tests/unit/operator_console/test_routes.py`;
    `.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console`;
    exact stale-reference search for `state.routes`, `payload.routes`,
    `payload["routes"]`, and `"routes":` under
    `roboclaws/operator_console` and `tests/unit/operator_console`.
  - Skipped browser smoke: this slice changed an internal JSON key alias and
    state lookup owner, not rendered layout, interaction behavior, or visual
    asset loading; focused API/static proof covered the observable risk.

## Parked Registry

- fingerprint: `operator-console/static/app.js/oversized-controller`
  - owner layer: operator-console static UI
  - park reason: file size is real pressure, but no decision-ready deletion,
    merge, or owner move has been proven yet.
  - exact unblocker: a future discovery pass must name a stale UI concept,
    duplicate owner, or extractable ownership boundary with focused proof.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: discovery can name a concrete behavior-preserving
    reduction, not only "make the file smaller."

## Rejected Low-Value Registry

- fingerprint: `operator-console/static/app.js/function-count`
  - reason rejected: function count alone is not a maintenance slice.
  - materiality gap: no current false confidence, stale surface, or duplicate
    owner is proven by the count alone.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: tied to a concrete stale concept or owner move.

## Discovery Round 1

Surface: current operator-console UI/API code, focused tests, and current
architecture docs.

Evidence sampled:

- `ARCHITECTURE.md` says `roboclaws/operator_console/` owns launch control and
  state surfacing, not task strategy.
- `docs/plans/operator-console-orthogonal-launch-refactor.md` records the
  current axis/combinations model and treats old route-card identity as
  historical.
- `/api/routes` currently emits both `combinations` and duplicate `routes`.
- `static/app.js` stores both `state.combinations` and `state.routes`, with
  `state.routes` only used to look up the latest result selection.
- Current focused tests read `payload["combinations"]`; no current docs/tests
  rely on `payload["routes"]`.

Maintenance handoff:

- clear candidates: queue item 1.
- parked candidates: oversized static controller until a concrete ownership
  boundary is proven.
- rejected low-value observations: function count/line count alone.
