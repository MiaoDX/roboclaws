# Model And Provider Matrix

OpenAI Agents SDK launches require an explicit `provider_profile`. Roboclaws
supports three profiles and never retries one wire API through another.

| Profile | Wire API | Model identity | Required environment |
| --- | --- | --- | --- |
| `custom-responses` | Responses | Public label `custom`; opaque request model from environment | `CUSTOM_RESPONSES_BASE_URL`, `CUSTOM_RESPONSES_API_KEY`, `CUSTOM_RESPONSES_MODEL` |
| `minimax-responses` | Responses | Public MiniMax catalog model | `MM_BASE_URL`, `MM_API_KEY` |
| `kimi-openai-chat` | Chat Completions | `kimi-k2.7-code` | `KIMI_OPENAI_BASE_URL`, `KIMI_API_KEY` |

Responses and Chat Completions are different transports. Responses can expose
provider-native reasoning and structured response items; Chat Completions uses
message/delta semantics. The runtime selects the matching SDK model class from
the profile and does not perform automatic fallback.

Kimi is the only Chat Completions profile. Its thinking-only and public
provider User-Agent compatibility rules remain explicit. The custom profile is
conservative: text-only catalog capability, unknown image transport, no alias,
pricing, or endpoint-specific headers. Tool calling must be proven against the
configured endpoint before it is treated as live evidence.

Provider secrets and custom endpoint/model values remain in the gitignored
`.env`; readiness, benchmark, console, and run artifacts expose only public
profile/model labels.
