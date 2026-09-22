# Model And Provider Matrix

OpenAI Agents SDK launches require an explicit `provider_profile`. Roboclaws
supports six profiles and never retries one wire API through another.

| Profile | Network scope | Allowed eval targets | Wire API | Model identity | Required environment |
| --- | --- | --- | --- | --- | --- |
| `codex-responses` | Internal | Local, CloudML | Responses | Public label `codex`; opaque request model from environment | `CODEX_RESPONSES_BASE_URL`, `CODEX_RESPONSES_API_KEY`, `CODEX_RESPONSES_MODEL` |
| `mimo-responses` | Internal | Local, CloudML | Responses | `mimo-v2.6-pro` (strictly validated) | `MIMO_RESPONSES_BASE_URL`, `MIMO_RESPONSES_API_KEY`, `MIMO_RESPONSES_MODEL` |
| `mimo-tp-openai-chat` | External | Local, trusted GitHub Actions showcase | Chat Completions | `mimo-v2.6-pro` | `MIMO_OPENAI_BASE_URL`, `MIMO_TP_KEY` |
| `minimax-responses` | External | Local, trusted GitHub Actions showcase | Responses | Public MiniMax catalog model | `MM_BASE_URL`, `MM_API_KEY` |
| `kimi-openai-chat` | External | Local, trusted GitHub Actions showcase | Chat Completions | `kimi-for-coding` (diagnostic `k3`, `k3-256k`) | `KIMI_OPENAI_BASE_URL`, `KIMI_API_KEY` |
| `qwen-tp-responses` | External | Local, trusted GitHub Actions showcase | Responses | `qwen3.8-max` (variant `qwen3.8-flash`) | `QWEN_TP_BASE_URL`, `QWEN_TP_KEY` |

Token-plan describes provider access, not the wire protocol. The MiMo and Kimi
token-plan routes use Chat Completions, while the MiniMax and Qwen token-plan
routes use Responses.

Responses and Chat Completions are different transports. Responses can expose
provider-native reasoning and structured response items; Chat Completions uses
message/delta semantics. The runtime selects the matching SDK model class from
the profile and does not perform automatic fallback.

Kimi's thinking-only and public provider User-Agent compatibility rules remain
explicit. Codex and the environment-configured MiMo Responses route are
conservative, independent cells with text-only catalog capability, unknown
image transport, and no alias, pricing, or endpoint default. Codex uses a thin
transport adapter for ephemeral request metadata and omits the unsupported
default `truncation` setting; those details never enter artifacts.

The Qwen token-plan route is experimental pending the standard two-sample
fixed-prior consumer suite. Direct endpoint probes have live-proven text,
native tool calling, image input (provider enforces a 10px minimum edge), and
`reasoning.effort` control including a real `none` disable, so both transports
capabilities are declared supported; streaming and `previous_response_id`
continuation are not yet proven. Billing is subscription Credits with a 7-day
quota window and tier-dependent agent concurrency, not per-token dollars, so
catalog pricing stays 0.0 and eval batches must watch the tier limit.

`mimo-responses` is the internal Responses API route configured through
`MIMO_RESPONSES_*`. The hosted showcase uses the separate public MiMo
token-plan Chat route, `mimo-tp-openai-chat`, configured through
`MIMO_OPENAI_BASE_URL` and `MIMO_TP_KEY`. Provider placement is explicit and
never falls back between these two MiMo routes.

The established profiles pass provider health and the same two-sample fixed-prior
consumer suite. The representative Kimi open-task and cleanup smoke rows also
pass. The accepted matrix recorded no provider failures, privacy leaks, or
trajectory violations; provider-reported dollar cost was unavailable, while
usage data remains available where each provider exposes it.

Provider secrets and endpoint/request-model values remain in the gitignored
`.env`; readiness, benchmark, console, and run artifacts expose only public
profile/model labels.

## Showcase Capacity Lanes

The public showcase is organized by usable quota, not by a single global model
ranking:

| Lane | Routes | Display role |
| --- | --- | --- |
| Public primary, rank 1 | `minimax-responses` / `MiniMax-M3` | Default public live proof and first Map Build row. |
| Public primary, rank 2 | `mimo-tp-openai-chat` / `mimo-v2.6-pro` | Second public high-volume route with the same cleanup and open-ended proof shapes. |
| Public compatibility | `kimi-openai-chat` / `kimi-for-coding`; future `qwen-tp-responses` | Compatibility and transport coverage; not a quota or quality ranking. Qwen stays out of the maintained row set until its fixed-prior proof is complete. |
| Internal high-volume | `codex-responses`, `mimo-responses` | Local or CloudML status and capacity proof. These routes are not dispatched by the public GitHub showcase. |

The Pages report labels each row with its lane and capacity rank. Results across
lanes must not be read as a direct quality leaderboard: they have different
network placement, quota, and transport contracts.
