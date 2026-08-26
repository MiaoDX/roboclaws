# CI Capability Showcase

Status: ACTIVE
Source: `docs/plans/2026-08-26-ci-capability-showcase.md`
Control plane: root Codex goal
Latest intent: implement the full approved plan through intuitive-flow

Current slice: implementation complete; broad verification remains blocked by a
pre-existing long-running deterministic eval test.
Last proof: ruff/format clean; focused showcase unit/workflow contract tests
passed (5 tests); CLI fixture rehearsal produced passed and blocked rows,
manifest digest, and HTML/Markdown/JSON projections.
Completed: versioned manifest; sanitized summary and projections; per-row
last-success reconciliation; weekly/manual advisory workflow; trusted-main live
guard; canonical artifact and Pages upload; README and CI/runtime docs.
Next: isolate the long-running existing eval test or obtain its completion;
then rerun `just agent::verify` and the requested eval/contract suites.
Stop condition: every plan acceptance criterion has direct current-state proof.
No-touch: required `.github/workflows/ci.yml`, Opik schemas/deployment, frozen
historical report site, unrelated dirty worktree files.
Parked: real provider showcase run remains separate operator proof per plan.
