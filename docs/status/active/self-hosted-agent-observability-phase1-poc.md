# Self-Hosted Agent Observability Phase 1 Local PoC

Status: PHASE_1_COMPLETE

Source: `docs/plans/2026-08-06-self-hosted-agent-observability-platform.md`

Scope: deterministic and real local Phoenix projection plus opt-in self-host packaging. Provider
calls were limited to the two explicitly authorized serial proof cells; no robot or shared service
was touched.

## Pinned Components

| Component | Pin | Ownership |
| --- | --- | --- |
| OpenAI Agents SDK | `0.19.2` | existing optional runtime/dev extra |
| OpenInference Agents SDK instrumentor | `1.3.0` | maintainer `dev` extra |
| OTLP HTTP exporter | `1.36.0` | maintainer `dev` extra |
| Phoenix server | `arizephoenix/phoenix:11.20.0` | opt-in off-process Compose service |

The real opt-in adapter composes the pinned OpenInference Agents SDK processor with a bounded
OpenTelemetry batch processor and OTLP HTTP exporter. The deterministic processor remains a
separate injected-sink fixture. Both dependencies are locked and installed through the repo's
`dev` extra.

## Deterministic Matrix

| Requirement | Result | Evidence |
| --- | --- | --- |
| One correlated hierarchy | PASS | one terminal root plus Agent, LLM, and Tool records under `trace-1` |
| Duplicate span IDs | PASS | 4 serialized records, 4 unique span IDs |
| Run/session/trial identity | PASS | closed identity repeated on every outbound record |
| Model and usage | PASS | model, input/output, cache, and reasoning tokens preserved when supplied |
| Status and error | PASS | terminal status plus normalized category/type; raw error message omitted |
| Forbidden fields | PASS | zero forbidden fields/values over serialized outbound bytes |
| Reachable deterministic sink | PASS | exported=2000, dropped=0, failed=0 |
| Real Phoenix ingestion | PASS | one trace, 4 unique spans, 3 parent links in `roboclaws-phase1-verified-v2` |
| Real run/session identity | PASS | closed run and `session.id` visible on every Phoenix span |
| Injected exporter failure | PASS | 4 attempts, exported=0, dropped=0, failed=4; zero retry |
| Full queue | PASS | external-only drops counted; callbacks remain fail-open |
| Callback latency | PASS | fake p99=0.020257 ms; real adapter observed max=0.206031 ms, threshold=5 ms |
| Terminal flush | PASS | deterministic blocked-export test returned in <0.08 s; configured maximum=2 s |
| Deterministic wall-time overhead | PASS | paired SDK fake: 0.532821% over 3 x 20 runs, threshold=2% |
| Local Phoenix container | PASS | healthy localhost-only Phoenix 11.20.0 container |
| Dependency lock | PASS | `uv lock --check` and `uv sync --extra dev` pass |
| OpenInference/OTLP transport | PASS | 4/4 hierarchy spans exported, 0 failed |
| Repository regression suite | PASS | full standalone pytest suite completed at 100% |

The real adapter owns one bounded `BatchSpanProcessor` worker; SDK callbacks perform conversion
and enqueue but no network I/O. It has no custom retry or spool. `TelemetryRuntime` installs one
process-global `LocalTraceRouter` with `set_trace_processors(...)`; an explicitly enabled run binds
the local recorder and its run-owned `PhoenixTelemetryAdapter` through a fail-open composite sink.
This preserves per-run identity across sequential and continuation runs while retaining Phase 0
suppression of the OpenAI backend exporter. Fail-closed `TraceConfig` hides inputs,
outputs, messages, prompts, choices, tool definitions and payloads, invocation parameters,
images, and embeddings. Closed run identity is attached as resource and span attributes; the
operator session also uses the OpenInference `session.id` convention. Lifecycle calls and
callbacks are fail-open and bounded; callbacks after shutdown are ignored.

## Live User Gates

| Wire family | Status | Required approval |
| --- | --- | --- |
| `kimi-openai-chat` / `kimi-k2.7-code` | PASS | one serial run, 4 model calls, zero retries; Phoenix 18 spans / 1 trace |
| `minimax-responses` / `MiniMax-M3` | PASS | repair run, 6 model calls, zero retries; Phoenix 26 spans / 1 trace |

Both wire-family rows now have successful live evidence. The initial Responses attempt is retained
as a real budget-failure trace; the repair is a separate serial attempt with no automatic retry.
Both use `molmospaces/procthor-10k-val/0`, MuJoCo, world-public labels, and the prompt
`Observe the room once, then call done with a concise summary; do not move objects.` They run
serially with `ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS=0`,
`ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS=0`, and
`ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS=4`. Costs are not a gate because the routes use an existing
token plan or an internal free model. Credentials for both profiles are present, but
`scripts/dev/network_status.sh` currently reports `network: unknown` because
`ROBOCLAWS_WORK_NETWORK_PROBE_URL` is not configured. No provider readiness call was made.

Kimi observed evidence: local run `output/household/household-world/open-ended/openai-agents-live-world-public-labels/0807_1758/seed-7`
finished with `exit_status=0`, `terminated_by=agent_done`, and complete local artifacts. Phoenix
project `roboclaws-phase1-live-poc` contains 18 unique spans in one trace, 17 parent links, 2
Agent, 4 LLM, 3 Tool, and 9 Chain spans. All spans carry `chat-completions-0000`,
`phase1-live-poc`, and the closed run identity; four LLM spans preserve model and input/output
usage. The Phoenix response contained zero non-redacted sensitive input/output/tool values. The
runner reported `Session termination failed: All connection attempts failed` after the product
result, but the MCP server finished and the canonical report/run artifacts were written; this is
recorded as a non-fatal lifecycle limitation, not a provider failure.

Responses observed evidence: the initial local run at `.../0807_1800/seed-7` reached the provider
four times with zero retries, exported 21 spans, and failed only at the product turn budget with
`agent_sdk_turn_budget_exceeded`; Phoenix recorded one ERROR span and 20 OK spans. The explicit
repair at `.../0807_1801/seed-7` finished with `exit_status=0` and `agent_done`, exported 26
spans in one trace with 25 parent links, 2 Agent, 6 LLM, 5 Tool, and 13 Chain spans, and had
zero failed/dropped exports. All successful spans carry `responses-0001`, `phase1-live-poc`, and
the closed run identity; Phoenix recorded zero raw sensitive values. MiniMax Responses returned
model and usage summaries in the local sanitized event stream, but the pinned OpenInference
projection exposed neither `llm.model_name` nor token attributes on these LLM spans. This is
recorded as route-specific usage/model unavailability; no values are inferred or copied into
Phoenix.

Exact authorized commands, to be executed serially:

```bash
ROBOCLAWS_PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces \
ROBOCLAWS_PHOENIX_PROJECT=roboclaws-phase1-live-poc \
ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS=0 \
ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS=0 \
ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS=4 \
ROBOCLAWS_EVAL_TELEMETRY_IDENTITY='{"operator_session_id":"phase1-live-poc","suite_id":"observability-phase1","suite_version":"1","sample_id":"observe-once","trial_id":"chat-completions-0000","repetition":0}' \
just run::surface surface=household-world \
  world=molmospaces/procthor-10k-val/0 backend=mujoco \
  agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat \
  evidence_lane=world-public-labels \
  prompt="Observe the room once, then call done with a concise summary; do not move objects."

ROBOCLAWS_PHOENIX_OTLP_ENDPOINT=http://127.0.0.1:6006/v1/traces \
ROBOCLAWS_PHOENIX_PROJECT=roboclaws-phase1-live-poc \
ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS=0 \
ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS=0 \
ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS=4 \
ROBOCLAWS_EVAL_TELEMETRY_IDENTITY='{"operator_session_id":"phase1-live-poc","suite_id":"observability-phase1","suite_version":"1","sample_id":"observe-once","trial_id":"responses-0000","repetition":0}' \
just run::surface surface=household-world \
  world=molmospaces/procthor-10k-val/0 backend=mujoco \
  agent_engine=openai-agents-sdk provider_profile=minimax-responses \
  evidence_lane=world-public-labels \
  prompt="Observe the room once, then call done with a concise summary; do not move objects."
```

## Volume And Operations

The deterministic collector observed 756,890 serialized bytes for 2,000 terminal span records,
or 378.44 bytes/record. The fixture hierarchy uses four records, approximately 1.5 KiB raw per
run before any future OTLP envelopes and database indexes. At 10,000 equivalent runs this is about 15 MiB
raw; budget 3-10x (45-150 MiB) for transport, indexes, and database overhead until a real
Phoenix measurement replaces the estimate. A 30-day retention window at 10,000 runs/day is
therefore approximately 1.35-4.5 GiB. High-turn runs must be estimated from observed terminal
span counts, not this four-span fixture.

The local Compose ceiling is 2 CPU and 4 GiB RAM with a named persistent volume. The healthy PoC
container used about 224 MiB RAM after ingestion; its SQLite data directory was about 4.9 MB
after the verified hierarchy, the 240-span overhead matrix, and earlier local probe data. These
small-run figures do not replace the volume-based production estimate. Production
placement, authentication, backup/deletion, retention, and resource sizing remain Phase 2 human
decisions. The local service binds only to `127.0.0.1` and is never started by product runtime.

## Artifacts And Commands

- Adapter and deterministic fixture: `roboclaws/agents/phoenix_telemetry.py`
- Runtime composition: `roboclaws/agents/experiment_telemetry.py`
- Deterministic proofs: `tests/unit/agents/test_phoenix_telemetry.py`
- Deployment: `deploy/phoenix/compose.yaml`
- Config validator: `scripts/dev/validate_phoenix_deployment.sh`

The Phase 1 live path is disabled unless `ROBOCLAWS_PHOENIX_OTLP_ENDPOINT` is set to a localhost
`/v1/traces` endpoint. `ROBOCLAWS_PHOENIX_PROJECT` may select a closed project name and otherwise
defaults to `roboclaws-phase1-live-poc`. Remote collector endpoints are rejected during this PoC.

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/agents/test_experiment_telemetry.py \
  tests/unit/agents/test_phoenix_telemetry.py \
  tests/unit/agents/test_live_runtime_telemetry.py
.venv/bin/ruff check roboclaws/agents tests/unit/agents
.venv/bin/ruff format --check roboclaws/agents tests/unit/agents
./scripts/dev/validate_phoenix_deployment.sh
docker compose -f deploy/phoenix/compose.yaml up -d
uv lock --check
```

Next action: reconcile the completed Phase 1 report and stop at the separate Phoenix production
selection gate. Phoenix production placement, authentication, retention, backup/deletion, and
resource decisions remain Phase 2 human decisions.
