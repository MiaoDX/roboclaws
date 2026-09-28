# Local evaluation baseline refresh

Date: 2026-09-27

Owner: Eval Harness / Eval Suites architecture layer.

## Result

The first full local refresh after Codex Responses and CloudML batch retirement
completed on commit `ff887106`. It is not a passing or promoted baseline:
**29 selected rows: 24 passed, 3 failed, 2 blocked; zero budget skips.**
The command exited 1 and finalized its evidence normally.

```bash
just agent::eval execute profile=baseline-refresh budget=focused
```

Run: `output/eval-harness/20260927T081341Z/`, from 08:13:41 to 10:40:10 UTC
(16:13:41 to 18:40:10 Asia/Shanghai), approximately 2h 26m.

Canonical local evidence:

- `eval_harness.json`: selected rows, placement, commands, and outcomes.
- `eval_harness.md`: readable scores and links to individual trial evidence.
- `eval_harness.completed.json`: completion v2; both recorded artifact hashes
  were checked against the final JSON and Markdown files.
- Per-row `rows/<row-id>/row_result.json` and per-suite `eval_results.json`.

All five deterministic gates and all seven local product rows passed, including
both Grounding DINO products, RAW-FPV, MapBuild, and Runtime Prior consumption.
The six eval-suite rows and eleven live-agent rows contain 53 graded results:
48 passed, 3 failed, 2 blocked. These trial counts do not include the separate
deterministic-gate or product-row results.

## Provider matrix and placement

All four fixed-prior cells ran locally against the canonical read-only snapshot
under `assets/eval-priors/by-sha256/2cc758d39064a62f981e15dc8fa8ae09487e430a2548b52cd1ebc1fcd7f9f958/`.
The manifest has exactly four provider cells, all provider rows allow only
`["local"]`, and every row executed with `execution_target=local`.
No row contains a Codex Responses route or CloudML placement.

| Provider profile | Fixed-prior results |
| --- | --- |
| `mimo-responses` | 2 passed |
| `mimo-tp-openai-chat` | 1 passed, 1 blocked |
| `kimi-openai-chat` | 2 passed |
| `minimax-responses` | 2 passed |

Kimi quota failure did not recur in these two samples. This does not rerun or
close the historical State-First Kimi skill-delivery comparison: the current
default capability and skill-delivery rows use MiniMax.

The default MiniMax session row passed. Cleanup comparison scores were
static-full 3/3, no-skill 3/3, dynamic-full 2 passed/1 failed, dynamic-routed
3/3, and sandbox-skills 2 passed/1 blocked.

## Failures and blockers

| Row / trial | Recorded classification | Concrete evidence |
| --- | --- | --- |
| MiMo TP fixed-prior cleanup, trial 0 | `environment_blocked` | Model call remained in flight beyond the 180s stall threshold, after 41 successful calls. Total elapsed time was about 991s. No provider HTTP error was captured. |
| Direct `open-ended-goals-eval-suite`, room4-anchor sample | `private_goal_not_satisfied` | Grader required `room_6_inspection`; visited/observed evidence contained `room_2`. Failure: `required_waypoint_or_area_not_visited`. |
| MiniMax `openai-agents-sdk-open-task-live-eval`, drink sample | `private_goal_not_satisfied` | All 7 public waypoints were observed, but `exhausted_public_search_budget=false`. Failure: `public_search_not_authoritatively_exhausted`. |
| MiniMax dynamic-full cleanup, trial 1 | `harness_bug_unclassified` | First model response called `household__metric_map`; SDK exited with `Tool household__metric_map not found in agent roboclaws-household-world`. |
| MiniMax sandbox-skills cleanup, trial 2 | `model_or_provider_unavailable` | HTTP 500 body explicitly reported Token Plan usage limit reached, code 2056. `live_status.json` records `provider_transient_failure` / `upstream_unavailable`. |

These are recorded observations, not established root causes for the two
goal-predicate failures or the tool-name mismatch. A terminal `done` or successful
model call alone is not a passing evaluation.

No agent-initiated reruns or trial retries were added. The existing model-service
policy retried the MiniMax quota response once; both failed attempts are in the
event evidence. This is distinct from the disabled live-trial retry policy.

## Usage and publication limits

Summing reported numeric values in `model_call_metrics.jsonl` yields:

| Route / model | Input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| MiMo Responses / `mimo` | 2,385,218 | 703,872 | 17,152 |
| MiniMax Responses / `MiniMax-M3` | 42,908,075 | 12,809,459 | 159,039 |

These are partial reported totals: usage is available in 72 MiMo and 847 MiniMax
metric records. MiMo TP (`mimo-v2.6-pro`) and Kimi (`kimi-for-coding`) metric
files mark token usage unavailable despite successful live calls. The totals
are not a complete billing estimate; monetary cost is unavailable.

Opik projection was disabled because its endpoint was not configured. Local
JSON/Markdown remain canonical. No baseline/catalog promotion, provider default
change, or overwrite of historical results occurred.

## Next action

Investigate the two goal-predicate failures and the dynamic-full tool-name
mismatch from their saved traces. After MiniMax quota recovers, rerun the blocked
sandbox trial as a separate attempt; similarly recheck the MiMo TP stall without
replacing this packet. Passing reruns must retain links to these original
failures before any baseline promotion is considered.
