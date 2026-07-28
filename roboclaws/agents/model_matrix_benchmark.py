"""Catalog, result models, and wire helpers for the model-matrix benchmark."""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, Literal

from roboclaws.agents.provider_registry import provider_route_spec, route_base_url
from roboclaws.agents.provider_transport import provider_default_headers
from roboclaws.agents.thinking_policy import thinking_request_body_for_wire

WireApi = Literal["openai-chat", "openai-responses", "anthropic-messages"]
BenchmarkLayer = Literal["health", "first-content", "throughput", "stream-throughput", "agent-case"]

DEFAULT_PROMPT = "Health check. Reply exactly ok."
DEFAULT_FIRST_CONTENT_PROMPT = "First-content latency benchmark. Reply exactly: ok"
DEFAULT_THROUGHPUT_PROMPT = (
    "Throughput benchmark. Write one continuous English passage of about 700 words about "
    "household robotics evaluation, semantic maps, and model-provider reliability. Do not use "
    "bullet points or tables. Keep writing until the passage is complete."
)
DEFAULT_STREAM_THROUGHPUT_PROMPT = (
    "Sustained streaming throughput benchmark. Write one continuous English passage of about "
    "2500 words about household robotics evaluation, semantic maps, route reliability, "
    "simulation evidence, and long-running model-provider operations. Do not use bullet points, "
    "tables, headings, code blocks, or lists. Keep writing until the passage is complete."
)
DEFAULT_LAYERS: tuple[BenchmarkLayer, ...] = ("health", "throughput")
LAYER_CHOICES: tuple[BenchmarkLayer, ...] = (
    "health",
    "first-content",
    "throughput",
    "stream-throughput",
    "agent-case",
)
DEFAULT_ITERATIONS = 1
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_TOKENS = 512
DEFAULT_FIRST_CONTENT_MAX_TOKENS = 256
DEFAULT_THROUGHPUT_MAX_TOKENS = 2048
DEFAULT_STREAM_THROUGHPUT_MAX_TOKENS = 4096
DEFAULT_AGENT_CASE_MAX_TOKENS = 768


@dataclass(frozen=True)
class AgentBenchmarkCase:
    case_id: str
    label: str
    source: str
    prompt: str


AGENT_BENCHMARK_CASES: tuple[AgentBenchmarkCase, ...] = (
    AgentBenchmarkCase(
        case_id="cleanup-worklist-plan",
        label="Cleanup worklist next-action plan",
        source="output/household/verify-done-held-mimo-mify-responses-mimo/0605_1507/seed-7/agent_view.json",
        prompt=(
            "You are driving the Roboclaws household-world cleanup MCP surface. Use only public "
            "evidence. Private scorer truth is unavailable. Given this public cleanup worklist, "
            "produce the next six MCP actions and a one-sentence stop condition. Keep it "
            "concise.\n\n"
            "Tool surface: metric_map, observe, navigate_to_waypoint, navigate_to_object, pick, "
            "navigate_to_receptacle, open_receptacle, place, place_inside, close_receptacle, "
            "done.\n"
            "Worklist objects:\n"
            "- observed_001 Potato, room_2, last seen at generated_exploration_001, candidate "
            "anchor_fixture_002, recommended_tool=place_inside, state=observed.\n"
            "- observed_002 Plate, room_5, last seen at generated_exploration_008, candidate "
            "anchor_fixture_009, recommended_tool=place, state=observed.\n"
            "- observed_003 RemoteControl, room_3, last seen at generated_exploration_003, "
            "candidate anchor_fixture_006, recommended_tool=place, state=observed.\n"
            "- observed_004 Book, room_2, last seen at generated_exploration_002, candidate "
            "anchor_fixture_004, recommended_tool=place_inside, state=observed.\n"
            "- observed_005 Pillow, room_2, last seen at generated_exploration_002, candidate "
            "anchor_fixture_004, recommended_tool=place, state=observed.\n"
            "Return compact JSON with keys actions, risk_notes, stop_condition."
        ),
    ),
    AgentBenchmarkCase(
        case_id="runtime-map-summary",
        label="Runtime metric map status summary",
        source=(
            "output/evals/household_world_cleanup_capability/20260615_verify_cleanup/"
            "runs/cleanup_repeated_seed7/trial-0000/runtime_metric_map.json"
        ),
        prompt=(
            "Summarize this public Runtime Metric Map state for a coding agent about to continue "
            "a cleanup run. Do not invent private destinations. Include: coverage gaps, likely "
            "next waypoint, and what evidence should be requested before picking anything.\n\n"
            "Map state: schema=runtime_metric_map_v1, world=molmospaces/val_0, "
            "evidence_lane=world-public-labels, generated exploration candidates "
            "generated_exploration_001 through generated_exploration_014. Visited waypoints: "
            "001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011. Observed categories: "
            "Potato, Plate, RemoteControl, Book, Pillow. Public semantic anchors include "
            "countertop-like, table-like, desk-like, cabinet-like, sofa-like, and bed-like "
            "fixtures. Several observed objects have candidate_inferred destination policy, "
            "not private truth. Output 5 short bullets."
        ),
    ),
    AgentBenchmarkCase(
        case_id="camera-grounded-composite",
        label="Camera-grounded composite decision",
        source="docs/status/active/live-agent-runtime-sdk-spike.md",
        prompt=(
            "You are reviewing a camera-grounded cleanup turn from the OpenAI Agents SDK route. "
            "The optimized route should prefer a composite declare-and-act cadence when visual "
            "evidence is actionable, but it must preserve traceability. Decide the next tool call "
            "and explain briefly.\n\n"
            "Current turn: observe returned three visible candidates. vc_01 appears to be a plate "
            "on a dining table with bbox confidence 0.84. vc_02 appears to be a remote control on "
            "a sofa with confidence 0.79. vc_03 is uncertain clutter near a cabinet with "
            "confidence 0.41. Previous turn already moved a book to a shelf. The active policy "
            "says do not "
            "call standalone declaration tools after SDK continuation if a composite action can "
            "carry the declaration internally. Available tools: declare_visual_candidates, "
            "navigate_to_visual_candidate, inspect_visible_object, pick, place, place_inside, "
            "done. "
            "Return: selected_tool, arguments, why_not_the_others."
        ),
    ),
    AgentBenchmarkCase(
        case_id="sdk-speedup-verdict",
        label="Agent SDK speedup verdict",
        source="docs/status/active/agent-sdk-speedup-live-refresh-matrix.json",
        prompt=(
            "Given this sanitized Agent SDK performance row, decide whether it is an accepted "
            "speedup, expected-rejected evidence, or blocked evidence. Keep private data out.\n\n"
            "Row: provider_profile=mimo-mify-responses, model=mimo-v2.5, "
            "evidence_lane=camera-grounded-labels. "
            "Baseline completed with done and report artifacts. Candidate O+AC completed with "
            "done and same-or-better quality. Observed wall time delta=-659.477s and model API "
            "time delta=-653.563s. Same-dataset calibration has low explanatory power "
            "(r2=0.048291), and holdout calibration is weaker (r2=-4.79098), so normalized model "
            "work is diagnostic only. Privacy gate passed; source rows are sanitized and do not "
            "store raw prompts or model text. Output a verdict, the evidence that supports it, "
            "and one follow-up benchmark to run next."
        ),
    ),
)


@dataclass(frozen=True)
class MatrixCase:
    case_id: str
    provider_id: str
    provider_label: str
    model: str
    wire_api: WireApi
    api_key_env: str
    base_url: str
    api_key_alt_env: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    expected_support: str = "unknown"
    note: str = ""


@dataclass(frozen=True)
class TrialResult:
    index: int
    layer: BenchmarkLayer
    status: str
    elapsed_s: float
    agent_case_id: str = ""
    agent_case_label: str = ""
    response_model: str = ""
    output_preview: str = ""
    output_chars: int = 0
    measured_output_tokens: int | None = None
    output_token_count_source: str = ""
    output_tokens_per_s: float | None = None
    output_chars_per_s: float | None = None
    first_content_s: float | None = None
    decode_s: float | None = None
    decode_output_tokens_per_s: float | None = None
    decode_output_chars_per_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error_type: str = ""
    error: str = ""


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    provider_id: str
    provider_label: str
    model: str
    wire_api: WireApi
    layer: BenchmarkLayer
    agent_case_id: str
    agent_case_label: str
    agent_case_source: str
    expected_support: str
    status: str
    api_key_env: str
    api_key_alt_env: str
    base_url_configured: bool
    iterations: int
    max_tokens: int
    success_count: int
    failure_count: int
    skipped_reason: str = ""
    mean_s: float | None = None
    median_s: float | None = None
    min_s: float | None = None
    max_s: float | None = None
    mean_output_tokens_per_s: float | None = None
    median_output_tokens_per_s: float | None = None
    mean_output_chars_per_s: float | None = None
    median_output_chars_per_s: float | None = None
    mean_decode_output_tokens_per_s: float | None = None
    median_decode_output_tokens_per_s: float | None = None
    mean_decode_output_chars_per_s: float | None = None
    median_decode_output_chars_per_s: float | None = None
    median_first_content_s: float | None = None
    median_decode_s: float | None = None
    output_token_count_source: str = ""
    response_model: str = ""
    output_preview: str = ""
    note: str = ""
    trials: tuple[TrialResult, ...] = ()


def default_cases() -> tuple[MatrixCase, ...]:
    return (
        *_codex_env_cases(),
        *_mify_cases(),
        *_minimax_cases(),
        *_mimo_token_plan_cases(),
        *_mimo_inside_cases(),
        *_kimi_cases(),
        *_nvidia_cases(),
    )


def selected_cases(
    cases: tuple[MatrixCase, ...],
    *,
    providers: set[str],
    wires: set[str],
    case_ids: set[str],
) -> tuple[MatrixCase, ...]:
    selected = cases
    if providers:
        selected = tuple(case for case in selected if case.provider_id in providers)
    if wires:
        selected = tuple(case for case in selected if case.wire_api in wires)
    if case_ids:
        selected = tuple(case for case in selected if case.case_id in case_ids)
    return selected


def selected_agent_cases(*, case_ids: set[str]) -> tuple[AgentBenchmarkCase, ...]:
    if not case_ids:
        return AGENT_BENCHMARK_CASES
    return tuple(
        agent_case for agent_case in AGENT_BENCHMARK_CASES if agent_case.case_id in case_ids
    )


def _codex_env_cases() -> tuple[MatrixCase, ...]:
    route = provider_route_spec("codex-router-responses")
    base_url = route_base_url(route)
    model = route.default_model_id
    return (
        MatrixCase(
            case_id=f"codex-router-responses:{model}:responses",
            provider_id="codex-router-responses",
            provider_label="Codex router",
            model=model,
            wire_api="openai-responses",
            api_key_env=route.api_key_env or "",
            base_url=base_url,
            expected_support="native",
        ),
        MatrixCase(
            case_id=f"codex-router-responses:{model}:chat",
            provider_id="codex-router-responses",
            provider_label="Codex router",
            model=model,
            wire_api="openai-chat",
            api_key_env=route.api_key_env or "",
            base_url=base_url,
            expected_support="probe",
        ),
    )


def _mify_cases() -> tuple[MatrixCase, ...]:
    route = provider_route_spec("mimo-mify-responses")
    anthropic_route = provider_route_spec("mimo-mify-anthropic")
    base_url = route_base_url(route)
    return (
        *(
            MatrixCase(
                case_id=f"mimo-mify-responses:{_case_model_id(model)}:{wire}",
                provider_id="mimo-mify-responses",
                provider_label="MiMo mify",
                model=model,
                wire_api=wire,
                api_key_env=route.api_key_env or "",
                base_url=base_url,
                expected_support="probe" if wire == "openai-chat" else "native",
            )
            for model in ("xiaomi/mimo-v2.5", "xiaomi/mimo-v2.5-pro")
            for wire in ("openai-chat", "openai-responses")
        ),
        MatrixCase(
            case_id="mimo-mify-responses:xiaomi-mimo-v2.5:anthropic",
            provider_id="mimo-mify-responses",
            provider_label="MiMo mify",
            model="xiaomi/mimo-v2.5",
            wire_api="anthropic-messages",
            api_key_env=anthropic_route.api_key_env or "",
            base_url=route_base_url(anthropic_route),
            expected_support="native",
        ),
    )


def _minimax_cases() -> tuple[MatrixCase, ...]:
    route = provider_route_spec("minimax-responses")
    base_url = route_base_url(route)
    return (
        MatrixCase(
            case_id="minimax-responses:MiniMax-M3:responses",
            provider_id="minimax-responses",
            provider_label="MiniMax",
            model="MiniMax-M3",
            wire_api="openai-responses",
            api_key_env=route.api_key_env or "",
            base_url=base_url,
            expected_support="native",
            note="Default MiniMax model; official route is multimodal and supports image input.",
        ),
    )


def _mimo_token_plan_cases() -> tuple[MatrixCase, ...]:
    chat_route = provider_route_spec("mimo-tp-openai-chat")
    anthropic_route = provider_route_spec("mimo-tp-anthropic")
    return (
        *(
            MatrixCase(
                case_id=f"mimo-token-plan:{model}:{wire}",
                provider_id="mimo-token-plan",
                provider_label="MiMo token plan",
                model=model,
                wire_api=wire,
                api_key_env=chat_route.api_key_env or "",
                base_url=route_base_url(chat_route),
                expected_support="native" if wire == "openai-chat" else "probe",
            )
            for model in ("mimo-v2.5", "mimo-v2.5-pro")
            for wire in ("openai-chat", "openai-responses")
        ),
        MatrixCase(
            case_id="mimo-token-plan:mimo-v2.5:anthropic",
            provider_id="mimo-token-plan",
            provider_label="MiMo token plan",
            model="mimo-v2.5",
            wire_api="anthropic-messages",
            api_key_env=anthropic_route.api_key_env or "",
            base_url=route_base_url(anthropic_route),
            expected_support="native",
        ),
    )


def _mimo_inside_cases() -> tuple[MatrixCase, ...]:
    route = provider_route_spec("mimo-inside-openai-chat")
    base_url = route_base_url(route)
    return tuple(
        MatrixCase(
            case_id=f"mimo-inside-openai-chat:{model}:{wire}",
            provider_id="mimo-inside-openai-chat",
            provider_label="MiMo inside",
            model=model,
            wire_api=wire,
            api_key_env=route.api_key_env or "",
            base_url=base_url,
            expected_support="native" if wire == "openai-chat" else "probe",
            note=(
                "Default-enabled on-demand UltraSpeed route."
                if model == "mimo-1000"
                else "MiMo inside comparison row."
            ),
        )
        for model in ("mimo-v2.5", "mimo-v2.5-pro", "mimo-1000")
        for wire in ("openai-chat", "openai-responses")
    )


def _kimi_cases() -> tuple[MatrixCase, ...]:
    chat_route = provider_route_spec("kimi-openai-chat")
    return (
        MatrixCase(
            case_id="kimi:kimi-k2.7-code:chat",
            provider_id="kimi",
            provider_label="Kimi",
            model="kimi-k2.7-code",
            wire_api="openai-chat",
            api_key_env=chat_route.api_key_env or "",
            base_url=route_base_url(chat_route),
            headers=(("User-Agent", "claude-code/1.0.0"),),
            expected_support="native",
            note=(
                "Kimi K2.7 Code is the standard thinking-only coding route. "
                "No explicit thinking body is sent. The provider accepts and echoes "
                "arbitrary K2.7 suffixes, so benchmark the canonical model id."
            ),
        ),
    )


def _nvidia_cases() -> tuple[MatrixCase, ...]:
    base_url = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    return (
        MatrixCase(
            case_id="nvidia:nemotron-nano-vl:chat",
            provider_id="nvidia",
            provider_label="NVIDIA",
            model="nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
            wire_api="openai-chat",
            api_key_env="NV_API_KEY",
            api_key_alt_env="NVIDIA_API_KEY",
            base_url=base_url,
            expected_support="native",
        ),
        MatrixCase(
            case_id="nvidia:nemotron-nano-vl:responses",
            provider_id="nvidia",
            provider_label="NVIDIA",
            model="nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
            wire_api="openai-responses",
            api_key_env="NV_API_KEY",
            api_key_alt_env="NVIDIA_API_KEY",
            base_url=base_url,
            expected_support="probe",
        ),
    )


def _case_model_id(model: str) -> str:
    return model.replace("/", "-")


class ModelMatrixStreamSourceError(ValueError):
    """Raised when a provider stream emits malformed structured data."""


def openai_chat_stream_event(raw_line: bytes) -> dict[str, Any] | None:
    line = raw_line.decode("utf-8", errors="replace").strip()
    if not line:
        return None
    if line.startswith("data:"):
        line = line.removeprefix("data:").strip()
    elif line.startswith(("event:", "id:", "retry:", ":")) or not line.startswith("{"):
        return None
    if not line or line == "[DONE]":
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ModelMatrixStreamSourceError(
            f"model-matrix provider stream source must contain valid JSON object: {exc.msg}"
        ) from exc
    if not isinstance(event, dict):
        raise ModelMatrixStreamSourceError(
            "model-matrix provider stream source must contain a JSON object: "
            f"{type(event).__name__}"
        )
    return event


def latest_usage_tokens(
    wire_api: WireApi,
    event: dict[str, Any],
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
) -> tuple[int | None, int | None, int | None]:
    usage_prompt, usage_completion, usage_total = usage_tokens(wire_api, event)
    return (
        usage_prompt if usage_prompt is not None else prompt_tokens,
        usage_completion if usage_completion is not None else completion_tokens,
        usage_total if usage_total is not None else total_tokens,
    )


def openai_chat_stream_piece(event: dict[str, Any]) -> str:
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") if isinstance(first, dict) else {}
    if not isinstance(delta, dict):
        return ""
    return str(delta.get("content") or delta.get("reasoning_content") or "")


def endpoint_url(base_url: str, wire_api: WireApi) -> str:
    base = base_url.strip().rstrip("/")
    if wire_api == "openai-chat":
        return _openai_endpoint(base, "chat/completions")
    if wire_api == "openai-responses":
        return _openai_endpoint(base, "responses")
    return _anthropic_endpoint(base)


def payload_for_case(case: MatrixCase, *, prompt: str, max_tokens: int) -> dict[str, Any]:
    if case.wire_api == "openai-chat":
        payload: dict[str, Any] = {
            "model": case.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if case.provider_id == "kimi" and case.model.startswith("kimi-k2.7-code"):
            payload.update(
                thinking_request_body_for_wire(
                    provider_profile="kimi-openai-chat",
                    wire_api="chat-completions",
                    mode="default",
                )
            )
        return payload
    if case.wire_api == "openai-responses":
        payload = {
            "model": case.model,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "stream": False,
        }
        payload.update(
            thinking_request_body_for_wire(
                provider_profile=case.provider_id,
                wire_api="responses",
                mode="default",
            )
        )
        return payload
    return {
        "model": case.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }


def headers_for_case(case: MatrixCase, *, api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if case.wire_api == "anthropic-messages":
        headers["anthropic-version"] = "2023-06-01"
        headers["x-api-key"] = api_key
    headers.update(dict(case.headers))
    headers.update(provider_default_headers(case.provider_id))
    return headers


def output_text(wire_api: WireApi, data: dict[str, Any]) -> str:
    if wire_api == "openai-chat":
        return _openai_chat_output_text(data)
    if wire_api == "openai-responses":
        return _openai_responses_output_text(data)
    return _anthropic_messages_output_text(data)


def response_model(wire_api: WireApi, data: dict[str, Any]) -> str:
    if wire_api in {"openai-chat", "openai-responses"}:
        return str(data.get("model") or "")
    return str(data.get("model") or "")


def usage_tokens(
    wire_api: WireApi, data: dict[str, Any]
) -> tuple[int | None, int | None, int | None]:
    usage = data.get("usage") if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        return None, None, None
    if wire_api == "anthropic-messages":
        prompt_tokens = _int_or_none(usage.get("input_tokens"))
        completion_tokens = _int_or_none(usage.get("output_tokens"))
        total_tokens = (
            prompt_tokens + completion_tokens
            if prompt_tokens is not None and completion_tokens is not None
            else None
        )
        return prompt_tokens, completion_tokens, total_tokens
    return (
        _int_or_none(usage.get("prompt_tokens")),
        _int_or_none(usage.get("completion_tokens")),
        _int_or_none(usage.get("total_tokens")),
    )


def _openai_endpoint(base: str, suffix: str) -> str:
    if base.endswith("/" + suffix):
        return base
    parsed = urllib.parse.urlparse(base)
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/{suffix}"


def _anthropic_endpoint(base: str) -> str:
    if base.endswith("/v1/messages"):
        return base
    return f"{base}/v1/messages"


def _openai_chat_output_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or message.get("reasoning_content") or "").strip()


def _openai_responses_output_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if direct:
        return str(direct).strip()
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if isinstance(item, dict):
            parts.extend(_response_content_text_parts(item.get("content")))
    return "\n".join(parts).strip()


def _response_content_text_parts(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    return [str(part["text"]) for part in content if isinstance(part, dict) and part.get("text")]


def _anthropic_messages_output_text(data: dict[str, Any]) -> str:
    content = data.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text"))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        ).strip()
    return ""


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
