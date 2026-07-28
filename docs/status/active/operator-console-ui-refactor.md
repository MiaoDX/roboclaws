# Operator Console UI Refactor

Status: DONE

Source contract:

- `docs/plans/2026-06-30-operator-console-workflow-simplification.md`
- `docs/plans/2026-07-01-recommended-runtime-map-prior-selection.md`
- `ARCHITECTURE.md`

Completed slice:

Implement the approved console UI contract:

- main workflow actions are `Build Map`, `Open Task`, and `Cleanup`;
- Runtime Map Prior Snapshot use is an optional workflow setting;
- B1 / Map 12 Build Map is visible as an experimental Isaac route;
- digital-twin cleanup and Agibot physical cleanup are visible disabled
  capabilities with concrete reasons;
- evidence lanes have user-facing labels while raw ids remain in command
  previews and advanced metadata;
- workspace tabs are stable across environments and unavailable artifacts render
  explicit unavailable states.

No-touch scope:

- Do not enable physical cleanup manipulation.
- Do not silently select latest Build Map artifacts as prior defaults.
- Do not expose private scoring truth or generated mess details to the agent.

Proof:

```bash
node --check roboclaws/operator_console/static/app.js
./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console -q
git diff --check
```

Result:

- JavaScript syntax check passed.
- Full operator-console unit suite passed with one existing deprecation warning
  from `contextlib.py` / `streamable_http_client`.
- Diff whitespace check passed.
