# Model And Provider Matrix

OpenAI Agents SDK launches require an explicit `provider_profile`. Roboclaws
supports four profiles and never retries one wire API through another.

| Profile | Wire API | Model identity | Required environment |
| --- | --- | --- | --- |
| `codex-responses` | Responses | Public label `codex`; opaque request model from environment | `CODEX_RESPONSES_BASE_URL`, `CODEX_RESPONSES_API_KEY`, `CODEX_RESPONSES_MODEL` |
| `mimo-responses` | Responses | Public label `mimo`; opaque request model from environment | `MIMO_RESPONSES_BASE_URL`, `MIMO_RESPONSES_API_KEY`, `MIMO_RESPONSES_MODEL` |
| `minimax-responses` | Responses | Public MiniMax catalog model | `MM_BASE_URL`, `MM_API_KEY` |
| `kimi-openai-chat` | Chat Completions | `kimi-k2.7-code` | `KIMI_OPENAI_BASE_URL`, `KIMI_API_KEY` |

Responses and Chat Completions are different transports. Responses can expose
provider-native reasoning and structured response items; Chat Completions uses
message/delta semantics. The runtime selects the matching SDK model class from
the profile and does not perform automatic fallback.

Kimi is the only Chat Completions profile. Its thinking-only and public
provider User-Agent compatibility rules remain explicit. Codex and MiMo are
conservative, independent cells with text-only catalog capability, unknown
image transport, and no alias, pricing, or endpoint default. Codex uses a thin
transport adapter for ephemeral request metadata and omits the unsupported
default `truncation` setting; those details never enter artifacts.

All four profiles pass provider health and the same two-sample fixed-prior
consumer suite. The representative Kimi open-task and cleanup smoke rows also
pass. The accepted matrix recorded no provider failures, privacy leaks, or
trajectory violations; provider-reported dollar cost was unavailable, while
usage data remains available where each provider exposes it.

Provider secrets and endpoint/request-model values remain in the gitignored
`.env`; readiness, benchmark, console, and run artifacts expose only public
profile/model labels.
