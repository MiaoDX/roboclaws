---
plan_scope: operator-console-ui-maintenance
status: DONE
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

- Status: DONE
- Current slice: none; maintenance loop saturated.
- Next action: no immediate follow-up. Start a new discovery round only if new
  operator-console UI/API evidence appears or a parked unblocker changes.
- Blocker: none.
- Last proof: three implementation slices committed and the final saturation
  discovery pass found no new clear P1/P2 after dedupe.

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

Consecutive no-clear-candidate passes: 1

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

2. **DONE: Canonicalize next-goal follow-up selection decoding**
   - Severity: P2
   - Entropy source: duplicate owner for route selection identity
   - Demand gate: next-goal autostart reconstructed launch axes by splitting
     `selection_id` in `server.py`, even though `routes.get_selection()` and
     `LaunchRequest.selection_id` already own the canonical route identity.
   - Owner layer: operator-console server/route-registry boundary
   - Expected simplification: remove one private parser and route follow-up
     launch construction through the route registry.
   - Behavior-change class: behavior-preserving internal owner move; invalid
     selections still fail through the existing POST error wrapper.
   - Suggested proof: exact no-reference search for the removed parser,
     focused next-goal helper/autostart tests, ruff.

3. **DONE: Canonicalize selection-id task segment mapping**
   - Severity: P2
   - Entropy source: duplicate owner for `open-task` selection-id vocabulary
   - Demand gate: `routes.py`, `launcher.py`, `server.py`, and
     `runtime_inventory.py` each knew that non-preset intents lower to
     `open-task`; the route registry already owns canonical console selection
     identity.
   - Owner layer: operator-console route registry
   - Expected simplification: one helper owns the selection-id task segment for
     route payloads, launch requests, readiness query fallback, and eval-row
     runtime inventory.
   - Behavior-change class: behavior-preserving internal owner merge.
   - Suggested proof: exact duplication search for inline `open-task` selector
     expressions, focused route/runtime inventory/launcher/API tests, ruff.

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

- 2026-06-30: next-goal follow-up launch request construction now asks
  `get_selection(selection_id)` for world/backend/intent/engine/lane axes
  instead of parsing the selection string inside `server.py`.
  - Value metrics: duplicate private parsers removed: 1; route identity owners
    merged to the route registry: 1; public contracts touched: no.
  - Proof:
    `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_session_followup.py::test_followup_launch_request_uses_route_registry_for_selection_axes tests/unit/operator_console/test_operator_session_followup.py::test_followup_launch_request_rejects_unknown_selection_id tests/unit/operator_console/test_operator_session_followup.py::test_next_goal_autostart_retries_visual_slot_wind_down tests/unit/operator_console/test_operator_session_followup.py::test_next_goal_autostart_releases_parent_lock_during_live_status_wind_down tests/unit/operator_console/test_operator_console.py::test_operator_console_next_goal_autostarts_ready_followup`;
    `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_session_followup.py tests/unit/operator_console/test_operator_console.py::test_operator_console_next_goal_autostarts_ready_followup`;
    `.venv/bin/ruff check roboclaws/operator_console/server.py tests/unit/operator_console/test_operator_session_followup.py`;
    `node --check roboclaws/operator_console/static/app.js`;
    `.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console`;
    `git diff --check`;
    exact no-reference search for `_selection_launch_parts`,
    `selection_id.split`, and `split("::")` under `roboclaws/operator_console`
    and `tests/unit/operator_console`.
  - Skipped browser smoke: this slice changed server-side follow-up request
    construction only; focused API/helper proof covered the observable risk.

- 2026-06-30: selection-id task segment mapping now lives in
  `routes.selection_task_selector()` and is reused by route payloads,
  launch requests, readiness query fallback, and eval-row runtime inventory.
  - Value metrics: duplicate inline selectors removed: 3; canonical owner
    merged to route registry: 1; public route semantics changed: no.
  - Proof:
    `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_routes.py::test_selection_task_selector_keeps_open_tasks_out_of_preset_vocabulary tests/unit/operator_console/test_runtime_inventory.py::test_runtime_inventory_lists_eval_harness_sdk_live_row tests/unit/operator_console/test_launcher.py::test_launcher_rejects_missing_canonical_selection_identity tests/unit/operator_console/test_operator_console.py::test_operator_console_routes_endpoint_exposes_evidence_lane_matrix`;
    `node --check roboclaws/operator_console/static/app.js`;
    `.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console`;
    `git diff --check`;
    exact duplication search for inline `open-task` selector expressions under
    `roboclaws/operator_console` and `tests/unit/operator_console`.
  - Skipped browser smoke: this slice changed route-id construction helpers,
    not rendered layout, interaction behavior, or visual asset loading.

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

- fingerprint: `operator-console/runtime-inventory/route_id-field`
  - owner layer: operator-console runtime inventory
  - park reason: `route_id` remains an output field for task rows and tests, but
    current evidence shows it is a display/linking identifier, not active
    launch input or a preserved legacy relaunch API.
  - exact unblocker: a current consumer or false-green test proves
    `route_id` is being used as primary launch identity instead of
    `launch_selection` / canonical selection fields.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: a consumer path, API contract, or test pins
    `route_id` as launch input.

- fingerprint: `operator-console/history/legacy-route-display-readers`
  - owner layer: operator-console history/state
  - park reason: history and interaction code still reads old `route` payloads
    as best-effort display records; the current plan no-touch scope forbids
    public/external artifact removals without a migration need.
  - exact unblocker: a current artifact migration plan or failing test proves
    old history readers are misleading active launch behavior.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: active run launch uses old `route_id`/`route` input,
    or artifact migration scope is approved.

## Rejected Low-Value Registry

- fingerprint: `operator-console/static/app.js/function-count`
  - reason rejected: function count alone is not a maintenance slice.
  - materiality gap: no current false confidence, stale surface, or duplicate
    owner is proven by the count alone.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: tied to a concrete stale concept or owner move.

- fingerprint: `operator-console/static/route-card-class-name`
  - reason rejected: the CSS/DOM class name remains a visual card class, not a
    launch taxonomy or stale API.
  - materiality gap: renaming the class would be broad UI churn with no current
    false confidence or workflow friction.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: UI code starts using the class name as launch
    identity or external contract.

- fingerprint: `operator-console/prompt-preview/household-cleanup-source-label`
  - reason rejected: `household-cleanup` and `household-open-task` are lower
    skill/source labels in prompt preview and tests, not the active public
    launch taxonomy.
  - materiality gap: current architecture explicitly allows historical/lower
    implementation names outside the public task layer.
  - first seen: 2026-06-30
  - last confirmed: 2026-06-30
  - do-not-reopen-unless: the label reappears as public console route,
    command, or launch selection input.

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

## Discovery Round 2

Surface: next-goal autostart server path, operator-session follow-up tests, and
route-selection helpers.

Evidence sampled:

- `server.py` reconstructed follow-up launch axes by splitting
  `selection_id`.
- `routes.get_selection()` and `LaunchRequest.selection_id` already owned
  canonical route identity.
- Focused next-goal tests covered helper behavior and API autostart behavior.

Maintenance handoff:

- clear candidates: queue item 2.
- parked candidates: none new.
- rejected low-value observations: none new.

## Discovery Round 3

Surface: route-id construction across route payloads, launch requests, readiness
query fallback, and eval-row runtime inventory.

Evidence sampled:

- `routes.py`, `launcher.py`, `server.py`, and `runtime_inventory.py` each knew
  that non-preset intents become `open-task` in selection ids.
- Import direction allowed those callers to reuse a helper from the route
  registry without introducing a cycle.

Maintenance handoff:

- clear candidates: queue item 3.
- parked candidates: runtime-inventory `route_id` display field remains parked
  because current evidence does not show it as launch input.
- rejected low-value observations: `route-card` CSS names, lower
  prompt-preview skill labels, and line/function counts.

## Saturation Discovery Round

Surface: current `HEAD` after commits `6d69cc41`, `65e9ee76`, and
`4e9071b0`; operator-console UI/API code, focused tests, human docs, and high
noise summaries for `docs/plans`, `tests/unit/operator_console`, and
`roboclaws/operator_console`.

Evidence sampled:

- Exact searches no longer find `payload.routes`, `state.routes`,
  `_selection_launch_parts`, `selection_id.split`, `split("::")`, or duplicate
  inline `open-task` selector expressions outside the canonical helper and its
  test.
- Remaining `route_id` hits are runtime inventory display/linking fields or
  tests around legacy route rejection, not accepted launch inputs.
- Remaining `route-card` hits are CSS/DOM class names.
- Remaining `household-cleanup` / `household-open-task` hits are lower
  prompt-preview source labels and tests, consistent with the architecture
  note that older implementation names can remain outside the public task
  layer.
- Oversized files still exist, but no new stale concept, duplicate owner, or
  behavior-preserving owner move was proven beyond the completed queue.

Maintenance handoff:

- clear candidates: none.
- parked candidates: stable fingerprints above.
- rejected low-value observations: stable fingerprints above.
- saturation status: saturated for the current operator-console UI/API
  maintenance scope.
