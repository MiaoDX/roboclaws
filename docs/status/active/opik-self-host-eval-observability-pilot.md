---
status: BLOCKED
source_plan: docs/plans/2026-08-24-opik-self-host-eval-observability-pilot.md
control_plane: /root
latest_intent: execute approved Opik self-host eval observability pilot
current_slice: stage-3-clean-retry-gate
blocker_fingerprint: destructive_cleanup_permission:one_malformed_partial_bundle
last_proven: exact Compose up --wait and retained-data restart pass; offline snapshot maps 65 items, 25 native traces, 4994 spans, 40 experiment-only rows, and passes privacy scan; tagged Opik source and stored row prove hash-only UUIDv7 timestamps break partition-aware score lookup; timestamp-corrected IDs, partial-write reconciliation, two-pass receipt preservation, and live API count contract pass seven focused unit tests and Ruff
completed_slices: plan intake and approval; stage-1 isolated deployment/health/restart; stage-2 pure deterministic projection snapshot and focused tests; stage-3 offline client, receipt, and integration contract implementation
next_action: after human approval, delete only experiment item a39642da-ce06-777c-92fc-b7847343d390 and trace d3c8d275-20db-7dce-9c13-5f66882f5c4d with its 33 spans, then rerun the timestamp-corrected projection
next_proof: project exact historical manifest twice with zero new logical objects or scores on pass two, then run live integration contract
stop_condition: stop at external or human-only proof boundary, or any plan stop gate
no_touch_scope: Phoenix deployment/data, companion server, runtime telemetry, launch grammar, canonical eval artifacts
parked_work: migration, automatic projection, production dependency, baseline publication
---
