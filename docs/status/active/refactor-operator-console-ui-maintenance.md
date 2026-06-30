# Operator Console UI Maintenance Capsule

Capsule status: ACTIVE

Source gate: `docs/plans/refactor-operator-console-ui-maintenance.md`

Latest user intent classification: execute repo-wide architecture maintenance
for the UI operator console until saturation, using `$intuitive-refactor`.

Current slice: rediscover from current `HEAD` after completing the first clear
queue item.

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

Completed slice batch summary:

- 2026-06-30: removed the duplicate `/api/routes.routes` alias and frontend
  `state.routes` shadow owner. The API/static proof passed. The full scoped
  operator-console target also exposed and fixed a stale Agibot preview
  expectation in `tests/unit/operator_console/test_routes.py`.

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
