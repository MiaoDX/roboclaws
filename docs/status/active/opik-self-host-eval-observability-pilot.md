---
status: ACTIVE
source_plan: docs/plans/2026-08-24-opik-self-host-eval-observability-pilot.md
control_plane: /root
latest_intent: execute approved Opik self-host eval observability pilot
current_slice: stage-3-thin-maintainer-client
blocker_fingerprint: none
last_proven: exact Compose up --wait and retained-data restart pass; offline snapshot maps 65 items, 25 native traces, 4994 spans, 40 experiment-only rows, and passes privacy scan
completed_slices: plan intake and approval; stage-1 isolated deployment/health/restart; stage-2 pure deterministic projection snapshot and focused tests
next_action: implement and test the dependency-free loopback Opik REST client, receipt, and two-pass server count proof
next_proof: project exact historical manifest twice, then run live integration contract
stop_condition: stop at external or human-only proof boundary, or any plan stop gate
no_touch_scope: Phoenix deployment/data, companion server, runtime telemetry, launch grammar, canonical eval artifacts
parked_work: migration, automatic projection, production dependency, baseline publication
---
