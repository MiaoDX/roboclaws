---
plan_scope: live-agent-runtime-sdk-perf-followups
status: PARK
source:
  - docs/plans/live-agent-runtime-sdk-spike.md
  - 2026-06-10 Agent SDK performance optimization pass
  - 2026-06-10 Group 0 speedup foundation preflight
last_reviewed: 2026-06-12
closeout_date: 2026-06-12
---

# Live Agent Runtime SDK Perf Follow-ups

## Closeout

PARK.

The active performance pass is closed. The goal of this pass was to check the
meaningful latency directions for the private `openai-agents-live` route, not
to prove a broad publishable benchmark. The refreshed decision packet covers all
23 candidate IDs, has no unresolved no-row candidates, and classifies every
direction as accepted, accepted-deterministic, rejected, blocked, mixed
evidence, bypassed, merged, deferred, or conditional.

The current accepted speed direction is O+AC:
`camera_grounded_composite_tools` plus `camera_grounded_history_v1`. It is a
paired wall-clock win for the current `camera-grounded-labels` task slice, but
not a publishable normalized model-work claim. Keep it private/opt-in.

This document was intentionally compressed from the execution log. Historical
row-by-row detail remains available through git history, the live-refresh
decision packet, and the linked artifacts below.

## Decision

Do not keep expanding task-specific micro-optimizations for this pass. The
useful outcome is a narrower policy:

- Keep O+AC as the current best private/opt-in Agent SDK latency profile.
- Keep prompt/cache/context observability as a guardrail so future runs do not
  accidentally benchmark a bad prompt or context-management state.
- Do not rerun rejected policies unchanged.
- Prefer the next major speed lever to be a fast-model/provider bake-off under
  the same quality gates, not more broad compaction or racing work.

Token cost is telemetry only for this pass. The optimization target is elapsed
wall time, especially paired-comparable or calibrated/normalized latency. The
current evidence says O+AC reduces wall time mostly by reducing residual
model/SDK/provider waiting and context-growth failure risk; the holdout
calibration is too weak to claim reduced normalized model work.

## Evidence Snapshot

Primary machine-readable artifacts:

- Matrix manifest:
  `docs/status/active/agent-sdk-speedup-live-refresh-matrix.json`
- Decision packet:
  `output/agent-sdk-perf-followups/live-refresh-decision.json`
- O+AC fixed4 comparison:
  `output/agent-sdk-perf-followups/mify-camera-grounded-composite-ac-fixed4-comparison.json`
- O+AC repeat comparison:
  `output/agent-sdk-perf-followups/mify-camera-grounded-composite-ac-repeat-mify-comparison.json`
- Holdout calibration packet:
  `output/agent-sdk-perf-followups/mify-camera-grounded-o-ac-holdout-calibration.json`

Decision packet summary:

| Field | Value |
| --- | --- |
| Decision rows | 12 |
| Status counts | 5 accepted, 4 rejected, 3 blocked |
| Candidate IDs | 23 |
| Unresolved no-row candidates | 0 |
| Accepted-only | `AC`, `W` |
| Accepted deterministic, no live row | `A`, `G`, `J` |
| Rejected-only | `C`, `D`, `F` |
| Blocked-only | `P`, `AA` |
| Mixed evidence | `AB`, `B`, `I`, `N`, `O`, `Q`, `Y` |
| Bypassed no-row | `E`, `H`, `K` |
| Merged no-row | `L` |
| Deferred no-row | `M` |
| Conditional gate | `X` |

Best accepted rows:

| Row | Quality | Wall delta | Model API delta | Holdout model-work delta | Holdout residual delta |
| --- | --- | ---: | ---: | ---: | ---: |
| O+AC fixed4 | `success`, `restored_count=4/5`, `semantic_accepted_count=5/5`, `disturbance_count=0` | `-659.477s` | `-653.563s` | `-13.613s` | `-639.95s` |
| O+AC repeat | `success`, `restored_count=4/5`, `semantic_accepted_count=5/5`, `disturbance_count=0` | `-630.633s` | `-619.022s` | `+35.951s` | `-654.973s` |

Calibration limitation:

- Holdout packet used 76 training rows and 117 holdout rows.
- Holdout explanatory power is weak:
  `validation.r2=-4.79098`, `mae_s=7.72203`, `rmse_s=8.327714`.
- Therefore normalized model-work claims remain diagnostic only.

## What We Tested

| Direction | Result | Conclusion |
| --- | --- | --- |
| A: bounded canonical skill context | Accepted deterministic | Keep metadata/hash/privacy guard. No live speed claim needed. |
| G/J: explicit SDK settings and prompt-cache attribution | Accepted deterministic | Keep observability; run settings/cache A/B only for a concrete hypothesis. |
| Q/Y: shared decision packet and latency buckets | Accepted | This is the canonical comparison/coverage surface. Refresh only when new rows exist. |
| B: provider/model/evidence-lane baseline coverage | Mixed evidence | `mimo-openai-chat` completed as coverage only; `kimi-openai-chat` and `codex-env` are blocked. Extend only when it adds new provider/lane information. |
| O: camera-grounded composite observe tool | Mixed evidence | Mechanism works and promptfix2 was faster; O-only continuation tightening then hit context budget. Keep private/opt-in. |
| AC: camera-grounded history compaction | Accepted | With O, this is the only accepted speed direction. It preserves task quality and gives repeated paired wall-clock wins. |
| F: action-timeline visual capture | Rejected | Capture time dropped, but cleanup quality regressed and total wall/model time increased. |
| I/N/AB: broad model-input compaction / repeated map compaction / Responses feature audit | Rejected for current policy | Bytes/tokens dropped heavily, but behavior broke or slowed. Do not rerun unchanged. |
| C/D: model-call racing plus per-arm observability | Rejected for current policy | Racing reduced wall time but regressed cleanup quality and increased model API work. D observability remains useful for any future racing row. |
| P/AA: raw-FPV repeated-failure rail and image memory | Blocked live, accepted deterministic prep | Retry only with the current `codex-router-responses` route after Codex router upstream availability is healthy, or after another SDK route has verified image transport. |
| H/K/E/M/L/X | Bypassed, deferred, merged, or conditional | No active row is justified by current Q/Y evidence. X is required only before promoting private/opt-in behavior. |

## Interpretation

The pass did not show that arbitrary prompt/context compaction is generally
safe. It showed the opposite: broad compaction and racing can make the system
faster on a narrow timing metric while breaking task completion or cleanup
quality. This is why the decision packet treats faster-but-worse rows as
rejected.

The successful optimization is narrow and task-structure-aware:

- O removes avoidable camera-grounded two-step tool cadence by using
  `observe_camera_grounded_candidates`.
- AC keeps recent actionable camera-grounded state visible while summarizing
  older camera-grounded history in model-facing SDK input.
- Complete MCP traces, reports, and run artifacts remain available.

This means prompt cache, stable prefixes, and context management should remain
observable, but they do not justify a large generic optimization campaign here.
The better next product-level strategy is to compare faster models/providers
under the same quality and context-health gates.

## Current Policy

Keep:

- O+AC private/opt-in for the Agent SDK route.
- Group 0 matrix, quality comparator, privacy/schema gates, and latency bucket
  summaries.
- `wire_api` as a first-class axis; Responses and Chat-compatible rows are not
  interchangeable.
- Prompt/cache/context telemetry as health checks.

Do not:

- Promote O, AC, F, I/N/AB, P/AA, C/D, or other private speed levers to public
  defaults without X cross-client guard evidence.
- Rerun F, broad I/N/AB, C racing, or O-only continuation tightening unchanged.
- Treat token reduction as success when wall time or behavior quality regresses.
- Treat provider HTTP timing as provider-internal model compute time.

Reopen only if one of these changes:

- A faster model/provider candidate is ready for a controlled bake-off.
- A provider with verified raw-FPV image transport is available, or the current
  `codex-router-responses` route is healthy enough to retry P/AA.
- New Q/Y evidence shows a material remaining bucket that O+AC does not address.
- A reviewed calibration or cross-run validation dataset reaches acceptable
  explanatory power.
- A private/opt-in speed lever is being considered for default/public
  promotion, which requires X.

## Verification

Latest closeout gates:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/molmo_cleanup/test_agent_sdk_perf_matrix.py \
  tests/unit/reports/test_live_performance.py

.venv/bin/ruff check \
  scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py \
  tests/unit/molmo_cleanup/test_agent_sdk_perf_matrix.py

.venv/bin/ruff format --check \
  scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py \
  tests/unit/molmo_cleanup/test_agent_sdk_perf_matrix.py

.venv/bin/python scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py \
  --manifest docs/status/active/agent-sdk-speedup-live-refresh-matrix.json \
  --dry-run

.venv/bin/python scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py \
  --manifest docs/status/active/agent-sdk-speedup-live-refresh-matrix.json \
  --offline-preflight \
  --decision-packet output/agent-sdk-perf-followups/live-refresh-decision.json
```

All passed during closeout. The final offline-preflight regenerated the decision
packet with 12 rows, 23 covered candidates, and
`unresolved_no_row_candidate_ids=[]`.
