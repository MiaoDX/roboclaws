# Model Matrix

This page is the short human summary for current model/provider routes.

Authoritative sources:

- Route metadata: `roboclaws/agents/provider_registry.py`
- Live route verdicts: `docs/human/model-route-verdicts.yaml`
- Local runtime keys: `docs/human/local-runtime.md`

Historical provider incidents and superseded model rows belong in
`docs/retrospectives/`, `docs/adr/`, or archived plans, not in this current
route summary.

## Default Routes

| Agent engine | Default provider profile | Default model | Current status |
| --- | --- | --- | --- |
| `openai-agents-sdk` | `codex-router-responses` | `gpt-5.6-sol` | Preferred product route when provider capacity is healthy; Router transport compatibility is handled internally. |
| `direct-runner` | none | none | Deterministic contract/eval baseline; no model route and not a live robot agent. |

Useful explicit profiles:

| Provider profile | Wire API | Default model | Notes |
| --- | --- | --- | --- |
| `mimo-mify-responses` | Responses | `xiaomi/mimo-v2.5-pro` | Default-enabled MiMo route. Chat, Responses, tool calling, and CloudML live probes are healthy. |
| `minimax-responses` | Responses | `MiniMax-M3` | Explicit OpenAI Agents SDK route. |
| `kimi-openai-chat` | OpenAI Chat | `kimi-k2.7-code` | Experimental OpenAI Agents SDK route. Keep the canonical model id; Kimi accepts arbitrary K2.7 suffixes and echoes them. |

Paused diagnostic profiles:

| Provider profile | Wire API | Model | Notes |
| --- | --- | --- | --- |
| `mimo-tp-openai-chat` | OpenAI Chat | `mimo-v2.5` | Retained for explicit diagnostics; excluded from default route and baseline selection. |
| `mimo-inside-openai-chat` | OpenAI Chat | `mimo-1000` | Retained for diagnostics and historical artifacts; the upstream channel has been removed. |

## Route Rules

- Structured lanes can use text-only routes when tool transport is healthy.
- Raw camera lanes require both image input support and verified runtime image
  transport for the selected engine/profile pair.
- `ROBOCLAWS_OPENAI_AGENTS_THINKING_MODE=default|enabled|disabled` is only for
  OpenAI Agents SDK routes. Responses routes map it to `reasoning`; generic
  Chat routes map it to the provider-specific thinking field.
- Kimi K2.7 Code routes are thinking-only and do not send the old explicit
  `thinking` body. A 2026-06-22 probe showed `kimi-k2.7-code-highspeed` and
  `kimi-k2.7-code-highspeed-not-exist` both return HTTP 200 with matching
  content/usage shape, so suffixes are not a reliable fast-mode contract.
- `disabled` thinking mode is for diagnostics only when the provider supports
  it.
- Do not infer route health from model capability alone; use
  `model-route-verdicts.yaml`.
- MiMo defaults use only `mimo-mify-responses` with
  `xiaomi/mimo-v2.5-pro`. Paused routes never silently fall back to Mify.
- On the work network, repo-local OpenAI Agents SDK routes may run after normal
  provider readiness checks. OpenClaw and system-provider guards still apply.

## Update Checklist

When a provider route changes:

1. Update `roboclaws/agents/provider_registry.py`.
2. Update `docs/human/model-route-verdicts.yaml` with live evidence.
3. Update this summary only if the default, health interpretation, or operator
   guidance changed.
4. Run the focused provider/route tests or the model-matrix benchmark command
   below.

## Useful Commands

```bash
just dev::model-matrix-benchmark --iterations 1 --timeout-s 240
just dev::model-matrix-benchmark --list-agent-cases
```

The benchmark writes under `output/dev/model-matrix/<timestamp>/`. Weekly
human-readable speed summaries live in
`docs/status/provider-benchmarks/`.
