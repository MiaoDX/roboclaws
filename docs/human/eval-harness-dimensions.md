# Eval Harness Dimensions

This page inventories the current eval-harness test surface so maintainers can
choose which slices deserve ongoing support. It is descriptive, not a promise
that every combination should remain supported.

Source of truth:

- Row catalog: `skills/eval-harness/catalog/rows.json`
- Engine/provider catalog: `roboclaws/launch/agent_engines.py` and
  `roboclaws/agents/provider_registry.py`
- Eval suites: `evals/household_world/suites/*.json`
- Scope decision: `docs/adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md`

## Current Baseline Rows

The current named baseline profiles are:

| Profile | Rows | Intended use | Observed/estimated time |
| --- | ---: | --- | ---: |
| `baseline-core` | 18 | Normal broad local refresh without live providers. | 10-15 min |
| `baseline-live-default` | 24 | Core plus default GPT Router live capability proof. | 1.5-2 h |
| `baseline-refresh` | 27 | Release/nightly full baseline including alternate providers. | 2.5-3.5 h |

`profile=baseline-refresh` selects 27 rows: 26 required and 1 optional.

| Row kind | Count | Rows |
| --- | ---: | --- |
| `deterministic_gate` | 5 | `route-trace-contract-tests`, `eval-unit-tests`, `cleanup-contract-tests`, `agent-view-contract-tests`, `open-ended-household-contract-tests` |
| `eval_suite` | 6 | `smoke-regression-eval-suite`, `map-build-consumer-eval-suite`, `open-ended-goals-eval-suite`, `scene-sampler-stress-eval-suite`, `cleanup-capability-eval-suite`, `long-horizon-tasks-eval-suite` |
| `product_run` | 7 | `household-direct-world-public-product`, `planner-proof-dry-run-product`, `direct-camera-grounded-grounding-dino`, `direct-map-build-grounding-dino`, `direct-camera-raw-fpv`, `direct-map-build-world-public`, `direct-cleanup-runtime-prior-consumer` |
| `live_agent_eval` | 9 | four `map-build-consumer-openai-agents-sdk-*` provider rows, `openai-agents-sdk-open-task-live-eval`, `openai-agents-sdk-session-live-eval`, `openai-agents-sdk-cleanup-live-eval`, `openai-agents-sdk-cleanup-camera-raw-fpv-live-product`, `openai-agents-sdk-codex-router-responses-availability` |

| Runtime cost | Count | Rows |
| --- | ---: | --- |
| `deterministic` | 10 | five deterministic gates plus five synthetic/static eval-suite rows |
| `local-sim` | 6 | direct world-public cleanup, planner proof, direct RAW-FPV cleanup, direct map-build, runtime-prior cleanup consumer, long-horizon suite |
| `dino` | 2 | direct Grounding DINO cleanup and map-build rows |
| `live-agent` | 9 | OpenAI Agents SDK capability and provider rows |

## Agent Engines

| Engine | Catalog status | Default provider | Supported provider profiles | Keep-pressure |
| --- | --- | --- | --- | --- |
| `direct-runner` | In baseline catalog | none | none | High: deterministic product and suite proof. |
| `codex-cli` | Launch-supported, not in baseline catalog | `codex-router-responses` | `codex-router-responses`, `mimo-mify-responses`, `minimax-responses` | Add only when proving coding-agent MCP behavior is a current baseline claim. |
| `openai-agents-sdk` | In baseline catalog | `codex-router-responses` | Default-enabled: `codex-router-responses`, `mimo-mify-responses`, `minimax-responses`, `kimi-openai-chat`; diagnostic-only: `mimo-tp-openai-chat`, `mimo-inside-openai-chat` | Medium: useful route, but provider-matrix prone. |
| `claude-code` | Launch-supported, not in baseline catalog | `mimo-tp-anthropic` | `kimi-anthropic`, `mimo-tp-anthropic`, `mimo-mify-anthropic` | Discuss: add only if it protects a current coding-agent claim. |
| `openclaw-gateway` | Launch metadata only; validation-required | `kimi` | `kimi` | Low for normal baseline; explicit validation path only. |

## Provider Routes

| Provider profile | Engines | Default model | Wire API | Current route status |
| --- | --- | --- | --- | --- |
| `codex-router-responses` | `codex-cli`, `openai-agents-sdk` | `gpt-5.6-sol` | Responses | healthy for Codex; experimental for Agent SDK |
| `mimo-mify-responses` | `codex-cli`, `openai-agents-sdk` | `xiaomi/mimo-v2.5-pro` | Responses gateway | degraded for Codex; healthy for Agent SDK and selected in the alternate-provider baseline |
| `minimax-responses` | `codex-cli`, `openai-agents-sdk` | `MiniMax-M3` | Responses | blocked for Codex; healthy for Agent SDK |
| `mimo-tp-openai-chat` | `openai-agents-sdk` | `mimo-v2.5` | Chat Completions | healthy but paused; explicit diagnostics only |
| `mimo-inside-openai-chat` | `openai-agents-sdk` | `mimo-1000` | Chat Completions | paused; upstream channel removed |
| `kimi-openai-chat` | `openai-agents-sdk` | `kimi-k2.7-code` | Chat Completions | experimental |
| `kimi-anthropic` | `claude-code` | `kimi-k2.6` | Anthropic-compatible | healthy |
| `mimo-tp-anthropic` | `claude-code` | `mimo-v2.5` | Anthropic-compatible shim | healthy |
| `mimo-mify-anthropic` | `claude-code` | `xiaomi/mimo-v2.5` | Anthropic-compatible gateway | experimental |
| `kimi` | `openclaw-gateway` | `kimi-k2.6` | Anthropic-compatible | experimental validation route |

Provider availability is useful evidence, but it is not a robot capability
result. Treat provider sweeps as explicit opt-in rows, not default proof.

## Capability And Evidence Axes

| Axis | Current values | Current baseline rows |
| --- | --- | --- |
| Intent | `open-ended`, `cleanup`, `map-build`, `planner-proof`, `route-trace`, `eval-harness`, `eval-suite` | All current baseline rows are tagged through intent or suite. |
| Preset | no preset/open-ended, `cleanup`, `map-build` | Open-ended uses no public preset; cleanup/map-build use explicit presets. |
| Evidence lane | `world-public-labels`, `camera-raw-fpv`, `camera-grounded-labels` | World-public is the main lane; RAW-FPV and Grounding DINO are narrower slices. |
| Camera labeler | `grounding-dino` | Only for camera-grounded rows. |
| Backend | `mujoco` | Current baseline catalog is MuJoCo-focused. |
| World | `molmospaces/val_0`, `planner-proof/default`, scene-sampler worlds inside suites | Broader worlds are currently suite samples, not separate product rows. |
| Scenario setup | `baseline`, `relocate-cleanup-related-objects` | Cleanup rows mostly use relocate; map-build/open-ended use baseline. |
| Runtime prior | `runtime_map_prior=required` | Only the cleanup consumer row depends on the map-build row artifact. |

## Eval Suites

| Suite | Samples | What it protects |
| --- | ---: | --- |
| `smoke_regression` | 1 | Minimal cleanup regression confidence. |
| `cleanup_capability` | 1 repeated sample | Cleanup capability metrics such as repeated success. |
| `map_build_consumer` | 5 | Runtime Metric Map actionability and downstream consumption. |
| `open_ended_goals` | 3 | No-preset open household goals. |
| `scene_sampler_stress` | 16 | Scene-source sampling projection and map-build admission metadata. |
| `long_horizon_tasks` | 2 | Multi-room navigation, manipulation, final-state grading, and privacy. |

## Candidate Profile Groups

These are candidate groups for future catalog metadata. They should be allowed
to shrink or disappear when they no longer protect a current product claim.

| Candidate group | Would include | Main reason to keep | Main reason to cut or keep opt-in |
| --- | --- | --- | --- |
| `baseline-refresh` | The accepted complete baseline set | Release/nightly refresh after large code changes. | Expensive and easy to overrun attention. |
| `baseline-core` | Deterministic gates, eval suites, local-sim and DINO product rows | Fast broad confidence without live providers. | Still includes simulator/runtime assumptions. |
| `baseline-live-default` | Core plus default GPT Router live rows | Proves the primary live route without a provider sweep. | Still takes around 1.5-2 hours on a single visual slot. |
| `coding-agent` | Live coding-agent rows | Proves MCP behavior through real coding agents. | Should not become every provider permutation. |
| `codex` | Codex CLI rows | Current strongest coding-agent route. | Non-default providers should stay explicit. |
| `claude-code` | Claude Code rows if added | Useful parity check for second coding-agent runtime. | Not currently in baseline; add only for a current claim. |
| `agent-sdk` | OpenAI Agents SDK rows | Proves SDK route separately from coding-agent CLI behavior. | Experimental; can become provider-matrix heavy. |
| `inner-providers` | MiMo/Kimi/internal gateway routes | Checks internal route health when it matters. | Not core robot behavior. |
| `all-providers` | All supported provider routes for selected engines | Useful for provider maintenance sweeps. | Too broad for default baseline. |
| `open-ended` | Open-ended contract, suite, and live rows | Protects current no-preset household goal contract. | Should not pull cleanup-only rows unless needed. |
| `cleanup` | Cleanup contract, suite, product, and live rows | Protects primary household cleanup demo. | Keep perception variants separate. |
| `map-build` | Map-build suite/product rows and runtime-prior consumer | Protects Runtime Metric Map flow. | Consumer row couples to artifact ordering. |
| `perception-dino` | Grounding DINO rows | Protects deployable visual-grounding lane. | Sidecar dependency makes it opt-in on some hosts. |
| `raw-fpv` | RAW-FPV direct and live rows | Protects raw-camera agent route. | Expensive and live-session sensitive. |

## Initial Pruning Discussion Points

These are not decisions yet.

| Surface | Default stance to discuss | Rationale |
| --- | --- | --- |
| `all-providers` | Keep explicit opt-in only. | Provider health is not the repo's main purpose. |
| Non-default Codex provider routes | Keep out of default baseline. | Current route status includes degraded/blocked combinations. |
| Agent SDK provider matrix | Keep one healthy behavior row plus optional availability probes. | Avoid multiplying SDK rows by every provider. |
| Claude Code rows | Add only if we want a maintained second coding-agent route. | Launch supports it, but baseline currently does not. |
| OpenClaw Gateway | Keep outside baseline. | Validation-required private/maintainer path. |
| DINO rows | Keep as a focused perception group. | Valuable but sidecar-dependent. |
| RAW-FPV live row | Keep as focused high-value route, not every baseline run. | Live-session and provider capacity sensitive. |
| Scene sampler stress | Keep as suite, not product-row expansion. | Sample count is already the broad world coverage. |
