# Codex Responses API investigation

Date: 2026-09-26

Owner: Agent Engine and Provider Profile HTTP transport layer.

## Disposition

Codex Responses support is retired from the active provider catalog, launch
validation, probes, benchmarks, and eval rows. CloudML batch evaluation is also
retired; local evaluation remains supported. The failed header experiment below
was removed with the Codex transport adapter. Historical evidence is retained.

The configured `codex-responses` route is not usable for the full Roboclaws
agent workflow at the time of testing. No verified client-side repair was found.
The remaining investigation needs the gateway operator's original upstream
errors and selected-channel configuration. This is not a claim that the
service is permanently or fundamentally unfixable.

Keep the current request-model configuration. An alternate test alias was used
only as a diagnostic control, not as a replacement provider or model.

## Tested change (removed)

`roboclaws/agents/provider_transport.py` temporarily added `OpenAI-Beta:
responses=experimental` and `originator: codex_cli_rs` alongside the existing
per-session `X-Codex-Window-Id`. Runtime and health probes share this helper.
The header experiment passed the 21 focused transport/provider-probe tests and
targeted Ruff checks, but did **not** repair the full live workflow.

All additional protocol variants below were temporary probes. No Lite adapter,
automatic fallback, credential change, server configuration change, or default
model change was installed.

## Evidence

Full program verification used the existing canonical map prior and the
`map_consumer_fixed_prior` suite with `openai-agents-sdk`, `codex-responses`,
`live_execution=run`, and `live_retry_limit=0`.

- Find-fridge sample: first model request failed with HTTP 403;
  one model call, zero MCP tool calls.
- Five-object cleanup sample: first model request failed with HTTP 403;
  one model call, zero MCP tool calls.
- Both failures were `bad_response_status_code` / `openai_error`, without a
  useful upstream explanation. These are provider failures, not evidence about
  the model's ability to solve the robotics tasks.

Artifacts:

- `output/evals/household_world_map_consumer_fixed_prior/codex-headers-full-program-20260926T0826/eval_results.json`
- The same directory's `eval_report.html` and per-run
  `provider_verification_metrics.json` files.
- `output/dev/codex-protocol-investigation/probes.jsonl` contains the subsequent
  redacted protocol probes and request IDs. No credentials, endpoint values,
  actual request-model names, or full request/response bodies are recorded.

| Protocol probe | Observed result |
| --- | --- |
| Typed user input, empty instructions, standard Responses | Completed with `ok`; later repeat timed out |
| Same initial request with an empty tools array | Completed with `ok` |
| Same initial request with medium reasoning effort | Completed with `ok` |
| Non-empty instructions or developer message | HTTP 403 |
| Standard function-tool declaration, optional or required | HTTP 403 |
| Lite header, streaming, priority tier, all-turns reasoning, serial tools; text only | Completed with `ok` |
| Lite plus tool declarations, including input `additional_tools` | HTTP 403 |
| Lite input tool namespace with item IDs and developer instruction metadata | HTTP 403 |
| Configured route, Agents SDK with instructions or tools | HTTP 403 |
| Alternate test route, same Agents SDK tool-call program | Completed: two model requests, one tool call, final `ok` |

The alternate-route control reported 302 input tokens and 20 output tokens;
provider-reported monetary cost was unavailable. No automatic retries were
enabled in these probes. Successful text-only responses do not establish native
tool or full-program availability. The Lite-versus-standard observations do not
prove that Lite is necessary: both formats produced successful text responses.

The final text/tool pair used string input; the subsequent repeated pair used
typed input. They are distinct request variants and must not be interpreted as
identical-payload repetitions.

## Community findings and limits

- [New API issue 6087](https://github.com/QuantumNous/new-api/issues/6087)
  describes CLI success but ordinary API/model-probe failure for a Lite model.
  The maintainer limits Codex-channel support to Codex CLI. Its reported 404 is
  not the same error as our 403, so it is a hypothesis source, not our root cause.
- [PR 6018](https://github.com/QuantumNous/new-api/pull/6018) merged request-field
  and header passthrough changes on 2026-07-11. The deployed version is unknown.
- [PR 4325](https://github.com/QuantumNous/new-api/pull/4325) merged streaming
  channel-health tests; it does not make every SDK request compatible.
- [PR 6964](https://github.com/QuantumNous/new-api/pull/6964), which proposed
  forcing upstream streaming and buffering for non-streaming clients, was
  closed **without merging**. An upgrade cannot be assumed to include it.
- [Codex client source](https://github.com/openai/codex/blob/main/codex-rs/core/src/client.rs)
  and its `responses_lite.rs` tests show that Lite includes body/tool/history
  differences beyond a header. Matching the tested initial tool shapes still
  did not yield a successful tool request through our configured route.

## Required gateway-side investigation

The existing inference key's read-only `/api/status` request returned HTTP 302;
the redirect was not followed. `/api/log/token` succeeded, but its 1,000 returned
entries were all consumption records (type 2), with no matching error record
for the request IDs below. This endpoint did not expose the required original
upstream failures. Deployment version and failed-channel details remain unknown.

For the investigation interval, the returned consumption records contained six
configured-model successes on one channel and two alternate-control successes
on a different channel. Their channel sets were disjoint. The alternate was
model-mapped; the configured successes were not marked mapped. This confirms
that the successful control does not establish compatibility of the intended
model's channel. It does not reveal which channel handled failed requests.

Locate these errors in gateway/admin logs using `X-Oneapi-Request-Id`:

- `202609260844547626006088268d9d6jeuhow7U`: string-input function-tool probe.
- `202609260846147049000578268d9d6iAFQARNP`: typed-input function-tool probe.

The corresponding local timestamps are recorded in `probes.jsonl`; use request
IDs rather than assuming the gateway clock matches the client clock.

Inspect the selected channel/type, original upstream HTTP body/status, request
policy and header/parameter overrides, model mapping, and whether custom
instructions/native tools are supported on that upstream. Compare those with
the successful alternate-route control. A generic 403 alone does not establish
missing model permission, unavailable channels, or a specific gateway policy.

Reopen client implementation only when that evidence identifies a supported
request contract or the upstream route is repaired. Acceptance remains both
complete fixed-prior consumer samples passing with the intended configured
model, not a text-only response or switching to the test alias.

## Retirement verification

Owner: Agent Engine / Provider Profiles and Eval Harness execution layers.

- Removed the Codex route, launch/environment entries, header and settings
  adapter, provider probes, benchmark route, and current eval cells/sample lists.
  Unknown probe selectors now fail rather than producing an empty success.
- Removed the repository CloudML batch-operations skill and current instructions.
  All catalog policies now require local execution. Frozen manifests requesting
  a non-local target fail before any row runs, including non-provider rows.
- Retained local evals, the other five provider profiles, historical artifacts,
  historical isolation attestations, and secret redaction for retired credentials.
  No remote task, artifact, or local credential configuration was deleted.
- The provider/agent/eval/launch/console/dev-tool suite executed 1,329 tests:
  1,325 passed, two skipped, and two obsolete test expectations failed. After
  updating the provider-cell count and the regrade fixture, all 54 tests in
  the affected selector, regrade, and provider-probe files passed (including a
  new retired-probe rejection check). The broad suite was not repeated.
- Repository-wide Ruff lint/format and `git diff --check` passed.
- Live `mimo-responses` Agents SDK health returned `ok` in 2.469 seconds with
  SDK retries disabled. This is availability evidence, not a new robotics
  scenario result; other providers were not re-probed in this retirement pass.
- `recommend profile=baseline-refresh` generated 29 selected rows and four
  fixed-prior provider cells (MiMo Responses, MiMo TP Chat, Kimi, MiniMax), all
  with local placement. The manifest is under
  `output/eval-harness/provider-retirement-review/`.

A preliminary whole-repository pytest run was interrupted before completion;
only the completed scoped suite and subsequent targeted checks are claimed.
