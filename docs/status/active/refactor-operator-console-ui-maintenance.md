# Operator Console UI Maintenance Capsule

Capsule status: ACTIVE

Source gate: `docs/plans/refactor-operator-console-ui-maintenance.md`

Latest user intent classification: execute repo-wide architecture maintenance
for the UI operator console until saturation, using `$intuitive-refactor`.

Current slice: commit selection-id task segment helper merge, then rediscover
from current `HEAD`.

Blocker fingerprint: none.

Last proven evidence:

- `find roboclaws/operator_console scripts/operator_console -maxdepth 1 -name '*.py' -print0 | xargs -0 -n1 .venv/bin/python -m py_compile`
- `node --check roboclaws/operator_console/static/app.js`
- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_console.py::test_operator_console_routes_endpoint_exposes_evidence_lane_matrix tests/unit/operator_console/test_static_assets.py`
- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console tests/unit/operator_console/test_routes.py`
- `.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console`
- exact stale-reference search for `state.routes`, `payload.routes`,
  `payload["routes"]`, and `"routes":` under `roboclaws/operator_console` and
  `tests/unit/operator_console`
- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_session_followup.py::test_followup_launch_request_uses_route_registry_for_selection_axes tests/unit/operator_console/test_operator_session_followup.py::test_followup_launch_request_rejects_unknown_selection_id tests/unit/operator_console/test_operator_session_followup.py::test_next_goal_autostart_retries_visual_slot_wind_down tests/unit/operator_console/test_operator_session_followup.py::test_next_goal_autostart_releases_parent_lock_during_live_status_wind_down tests/unit/operator_console/test_operator_console.py::test_operator_console_next_goal_autostarts_ready_followup`
- `.venv/bin/ruff check roboclaws/operator_console/server.py tests/unit/operator_console/test_operator_session_followup.py`
- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_operator_session_followup.py tests/unit/operator_console/test_operator_console.py::test_operator_console_next_goal_autostarts_ready_followup`
- `node --check roboclaws/operator_console/static/app.js`
- `.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console`
- `git diff --check`
- exact no-reference search for `_selection_launch_parts`,
  `selection_id.split`, and `split("::")` under `roboclaws/operator_console`
  and `tests/unit/operator_console`
- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console/test_routes.py::test_selection_task_selector_keeps_open_tasks_out_of_preset_vocabulary tests/unit/operator_console/test_runtime_inventory.py::test_runtime_inventory_lists_eval_harness_sdk_live_row tests/unit/operator_console/test_launcher.py::test_launcher_rejects_missing_canonical_selection_identity tests/unit/operator_console/test_operator_console.py::test_operator_console_routes_endpoint_exposes_evidence_lane_matrix`
- exact duplication search for inline `open-task` selector expressions under
  `roboclaws/operator_console` and `tests/unit/operator_console`

Completed slice batch summary:

- 2026-06-30: removed the duplicate `/api/routes.routes` alias and frontend
  `state.routes` shadow owner. The API/static proof passed. The full scoped
  operator-console target also exposed and fixed a stale Agibot preview
  expectation in `tests/unit/operator_console/test_routes.py`.
- 2026-06-30: removed the private next-goal selection-id split parser from
  `server.py`; follow-up launch requests now use `get_selection()`. Focused
  follow-up/API proof passed.
- 2026-06-30: moved the non-preset `open-task` selection-id segment rule into
  `routes.selection_task_selector()` and updated launcher, server readiness,
  and runtime inventory callers.

Next proof command:

```bash
node --check roboclaws/operator_console/static/app.js
./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console
.venv/bin/ruff check roboclaws/operator_console tests/unit/operator_console
```

Stop condition: after each clear queue batch passes focused proof, rediscover
from current `HEAD`; stop only when a fresh discovery round finds no new clear
P1/P2 candidate after deduping parked and rejected observations.

No-touch scope: no broad UI redesign, robot task strategy changes, provider
profile changes, live runtime changes, or external contract removals without
current evidence.

Parked work:

- `operator-console/static/app.js/oversized-controller`: reopen only when a
  concrete stale concept, duplicate owner, or owner move is proven.
