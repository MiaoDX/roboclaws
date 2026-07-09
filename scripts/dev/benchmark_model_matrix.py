#!/usr/bin/env python3
"""Benchmark model route support across OpenAI Chat, Responses, and Anthropic APIs.

Architecture layer: Harness recipes / dev provider benchmark. This script is a
periodic route-support probe; it does not register product provider routes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from roboclaws.agents.model_matrix_benchmark import (
    AGENT_BENCHMARK_CASES,
    DEFAULT_AGENT_CASE_MAX_TOKENS,
    DEFAULT_FIRST_CONTENT_MAX_TOKENS,
    DEFAULT_FIRST_CONTENT_PROMPT,
    DEFAULT_ITERATIONS,
    DEFAULT_LAYERS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROMPT,
    DEFAULT_STREAM_THROUGHPUT_MAX_TOKENS,
    DEFAULT_STREAM_THROUGHPUT_PROMPT,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    DEFAULT_THROUGHPUT_PROMPT,
    DEFAULT_TIMEOUT_S,
    LAYER_CHOICES,
    AgentBenchmarkCase,
    BenchmarkLayer,
    CaseResult,
    MatrixCase,
    TrialResult,
    default_cases,
    endpoint_url,
    headers_for_case,
    latest_usage_tokens,
    openai_chat_stream_event,
    openai_chat_stream_piece,
    output_text,
    payload_for_case,
    response_model,
    selected_agent_cases,
    selected_cases,
    usage_tokens,
)
from roboclaws.agents.work_network_gate import assert_no_work_network_codex_gpt55
from roboclaws.core.dotenv import update_env_from_dotenv_file
from roboclaws.core.json_sources import parse_json_object_text
from roboclaws.operator_console.redaction import redact_text


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    update_env_from_dotenv_file(path, os.environ)


def run_case(
    case: MatrixCase,
    *,
    layer: BenchmarkLayer,
    prompt: str,
    iterations: int,
    max_tokens: int,
    timeout_s: float,
    agent_case: AgentBenchmarkCase | None = None,
    env: dict[str, str] | None = None,
) -> CaseResult:
    env_map = os.environ if env is None else env
    api_key = env_map.get(case.api_key_env) or env_map.get(case.api_key_alt_env) or ""
    base_url = case.base_url.strip()
    if layer == "stream-throughput" and case.wire_api != "openai-chat":
        return _skipped_case(
            case,
            layer=layer,
            reason="stream-throughput is only implemented for OpenAI Chat streaming",
            iterations=iterations,
            max_tokens=max_tokens,
            base_url_configured=bool(base_url),
            agent_case=agent_case,
        )
    if not api_key:
        return _skipped_case(
            case,
            layer=layer,
            reason=_missing_key_label(case),
            iterations=iterations,
            max_tokens=max_tokens,
            base_url_configured=bool(base_url),
            agent_case=agent_case,
        )
    if not base_url:
        return _skipped_case(
            case,
            layer=layer,
            reason="missing base URL",
            iterations=iterations,
            max_tokens=max_tokens,
            base_url_configured=False,
            agent_case=agent_case,
        )

    trials = tuple(
        run_trial(
            case,
            index=index + 1,
            layer=layer,
            prompt=prompt,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            api_key=api_key,
            agent_case=agent_case,
        )
        for index in range(iterations)
    )
    return summarize_case(
        case,
        layer=layer,
        trials=trials,
        iterations=iterations,
        max_tokens=max_tokens,
        base_url_configured=True,
        agent_case=agent_case,
    )


def run_trial(
    case: MatrixCase,
    *,
    index: int,
    layer: BenchmarkLayer,
    prompt: str,
    max_tokens: int,
    timeout_s: float,
    api_key: str,
    agent_case: AgentBenchmarkCase | None = None,
) -> TrialResult:
    url = endpoint_url(case.base_url, case.wire_api)
    payload = payload_for_case(case, prompt=prompt, max_tokens=max_tokens)
    stream_openai_chat = case.wire_api == "openai-chat" and layer in {
        "first-content",
        "stream-throughput",
    }
    if stream_openai_chat:
        payload["stream"] = True
        if layer == "stream-throughput":
            payload["stream_options"] = {"include_usage": True}
    headers = headers_for_case(case, api_key=api_key)
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status_code = response.status
            content_type = response.headers.get("content-type", "")
            if stream_openai_chat:
                if status_code < 200 or status_code >= 300:
                    body = response.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"HTTP {status_code}: {body[:500]}")
                return _read_openai_chat_stream_trial(
                    response,
                    case=case,
                    index=index,
                    layer=layer,
                    started=started,
                    url=url,
                    agent_case=agent_case,
                )
            body = response.read().decode("utf-8", errors="replace")
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"HTTP {status_code}: {body[:500]}")
        if "json" not in content_type.lower():
            raise RuntimeError(f"expected JSON response, got {content_type}: {body[:500]}")
        data = parse_json_object_text(
            body,
            label="model-matrix provider response",
            source=f"{case.case_id} {layer}",
        )
        output = output_text(case.wire_api, data)
        if not output:
            raise RuntimeError("provider call completed without visible output")
        elapsed_s = time.monotonic() - started
        prompt_tokens, completion_tokens, total_tokens = usage_tokens(case.wire_api, data)
        measured_output_tokens, token_source = measured_output_token_count(
            output=output,
            completion_tokens=completion_tokens,
        )
        output_preview = _redact_benchmark_text(output[:120], extra_values=(case.base_url, url))
        return TrialResult(
            index=index,
            layer=layer,
            status="PASS",
            elapsed_s=round(elapsed_s, 3),
            agent_case_id=agent_case.case_id if agent_case else "",
            agent_case_label=agent_case.label if agent_case else "",
            response_model=response_model(case.wire_api, data),
            output_preview=output_preview,
            output_chars=len(output),
            measured_output_tokens=measured_output_tokens,
            output_token_count_source=token_source,
            output_tokens_per_s=_per_second(measured_output_tokens, elapsed_s),
            output_chars_per_s=_per_second(len(output), elapsed_s),
            first_content_s=round(elapsed_s, 3) if layer == "first-content" else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read(800).decode("utf-8", errors="replace")
        return TrialResult(
            index=index,
            layer=layer,
            status="FAIL",
            elapsed_s=round(time.monotonic() - started, 3),
            agent_case_id=agent_case.case_id if agent_case else "",
            agent_case_label=agent_case.label if agent_case else "",
            error_type="HTTPError",
            error=_redact_benchmark_text(
                f"HTTP {exc.code} {exc.reason}: {body[:600]}",
                extra_values=(case.base_url, url),
            ),
        )
    except Exception as exc:  # pragma: no cover - live provider shapes vary
        return TrialResult(
            index=index,
            layer=layer,
            status="FAIL",
            elapsed_s=round(time.monotonic() - started, 3),
            agent_case_id=agent_case.case_id if agent_case else "",
            agent_case_label=agent_case.label if agent_case else "",
            error_type=exc.__class__.__name__,
            error=_redact_benchmark_text(
                str(exc).replace("\n", " ")[:800],
                extra_values=(case.base_url, url),
            ),
        )


def _read_openai_chat_stream_trial(
    response: Any,
    *,
    case: MatrixCase,
    index: int,
    layer: BenchmarkLayer,
    started: float,
    url: str,
    agent_case: AgentBenchmarkCase | None = None,
) -> TrialResult:
    output_parts: list[str] = []
    response_model_name = ""
    first_content_at: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    try:
        for raw_line in response:
            event = openai_chat_stream_event(raw_line)
            if event is None:
                continue
            response_model_name = response_model_name or str(event.get("model") or "")
            prompt_tokens, completion_tokens, total_tokens = latest_usage_tokens(
                case.wire_api,
                event,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            piece = openai_chat_stream_piece(event)
            if not piece:
                continue
            if first_content_at is None:
                first_content_at = time.monotonic()
            output_parts.append(str(piece))
        completed_at = time.monotonic()
        output = "".join(output_parts).strip()
        if not output:
            raise RuntimeError("stream completed without visible output")
        elapsed_s = completed_at - started
        first_content_s = (first_content_at - started) if first_content_at is not None else None
        decode_s = (
            completed_at - first_content_at
            if first_content_at is not None and completed_at > first_content_at
            else None
        )
        measured_output_tokens, token_source = measured_output_token_count(
            output=output,
            completion_tokens=completion_tokens,
        )
        return TrialResult(
            index=index,
            layer=layer,
            status="PASS",
            elapsed_s=round(elapsed_s, 3),
            agent_case_id=agent_case.case_id if agent_case else "",
            agent_case_label=agent_case.label if agent_case else "",
            response_model=response_model_name,
            output_preview=_redact_benchmark_text(output[:120], extra_values=(case.base_url, url)),
            output_chars=len(output),
            measured_output_tokens=measured_output_tokens,
            output_token_count_source=token_source,
            output_tokens_per_s=_per_second(measured_output_tokens, elapsed_s),
            output_chars_per_s=_per_second(len(output), elapsed_s),
            first_content_s=round(first_content_s, 3) if first_content_s is not None else None,
            decode_s=round(decode_s, 3) if decode_s is not None else None,
            decode_output_tokens_per_s=_per_second(measured_output_tokens, decode_s or 0),
            decode_output_chars_per_s=_per_second(len(output), decode_s or 0),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    except Exception as exc:  # pragma: no cover - live provider stream chunks vary
        return TrialResult(
            index=index,
            layer=layer,
            status="FAIL",
            elapsed_s=round(time.monotonic() - started, 3),
            agent_case_id=agent_case.case_id if agent_case else "",
            agent_case_label=agent_case.label if agent_case else "",
            error_type=exc.__class__.__name__,
            error=_redact_benchmark_text(
                str(exc).replace("\n", " ")[:800],
                extra_values=(case.base_url, url),
            ),
        )


def measured_output_token_count(
    *,
    output: str,
    completion_tokens: int | None,
) -> tuple[int, str]:
    if completion_tokens is not None:
        return completion_tokens, "provider_usage"
    # Coarse fallback only. It keeps trend reports useful for providers that omit
    # usage, but it should not be treated as billing/tokenizer-accurate data.
    return max(1, round(len(output) / 4)), "estimated_chars_div_4"


def _per_second(value: int | None, elapsed_s: float) -> float | None:
    if value is None or elapsed_s <= 0:
        return None
    return round(value / elapsed_s, 3)


def _redact_benchmark_text(text: str, *, extra_values: tuple[str, ...] = ()) -> str:
    redacted = redact_text(text)
    for value in extra_values:
        if value and len(value) >= 6:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def summarize_case(
    case: MatrixCase,
    *,
    layer: BenchmarkLayer,
    trials: tuple[TrialResult, ...],
    iterations: int,
    max_tokens: int,
    base_url_configured: bool,
    agent_case: AgentBenchmarkCase | None = None,
) -> CaseResult:
    successes = [trial for trial in trials if trial.status == "PASS"]
    failures = [trial for trial in trials if trial.status != "PASS"]
    elapsed = [trial.elapsed_s for trial in successes]
    token_rates = [
        trial.output_tokens_per_s for trial in successes if trial.output_tokens_per_s is not None
    ]
    char_rates = [
        trial.output_chars_per_s for trial in successes if trial.output_chars_per_s is not None
    ]
    decode_token_rates = [
        trial.decode_output_tokens_per_s
        for trial in successes
        if trial.decode_output_tokens_per_s is not None
    ]
    decode_char_rates = [
        trial.decode_output_chars_per_s
        for trial in successes
        if trial.decode_output_chars_per_s is not None
    ]
    first_content = [
        trial.first_content_s for trial in successes if trial.first_content_s is not None
    ]
    decode_elapsed = [trial.decode_s for trial in successes if trial.decode_s is not None]
    token_sources = sorted(
        {trial.output_token_count_source for trial in successes if trial.output_token_count_source}
    )
    status = "PASS" if successes and not failures else "PARTIAL" if successes else "FAIL"
    first_success = successes[0] if successes else None
    return CaseResult(
        case_id=case.case_id,
        provider_id=case.provider_id,
        provider_label=case.provider_label,
        model=case.model,
        wire_api=case.wire_api,
        layer=layer,
        agent_case_id=agent_case.case_id if agent_case else "",
        agent_case_label=agent_case.label if agent_case else "",
        agent_case_source=agent_case.source if agent_case else "",
        expected_support=case.expected_support,
        status=status,
        api_key_env=case.api_key_env,
        api_key_alt_env=case.api_key_alt_env,
        base_url_configured=base_url_configured,
        iterations=iterations,
        max_tokens=max_tokens,
        success_count=len(successes),
        failure_count=len(failures),
        mean_s=round(statistics.fmean(elapsed), 3) if elapsed else None,
        median_s=round(statistics.median(elapsed), 3) if elapsed else None,
        min_s=round(min(elapsed), 3) if elapsed else None,
        max_s=round(max(elapsed), 3) if elapsed else None,
        mean_output_tokens_per_s=round(statistics.fmean(token_rates), 3) if token_rates else None,
        median_output_tokens_per_s=round(statistics.median(token_rates), 3)
        if token_rates
        else None,
        mean_output_chars_per_s=round(statistics.fmean(char_rates), 3) if char_rates else None,
        median_output_chars_per_s=round(statistics.median(char_rates), 3) if char_rates else None,
        mean_decode_output_tokens_per_s=round(statistics.fmean(decode_token_rates), 3)
        if decode_token_rates
        else None,
        median_decode_output_tokens_per_s=round(statistics.median(decode_token_rates), 3)
        if decode_token_rates
        else None,
        mean_decode_output_chars_per_s=round(statistics.fmean(decode_char_rates), 3)
        if decode_char_rates
        else None,
        median_decode_output_chars_per_s=round(statistics.median(decode_char_rates), 3)
        if decode_char_rates
        else None,
        median_first_content_s=round(statistics.median(first_content), 3)
        if first_content
        else None,
        median_decode_s=round(statistics.median(decode_elapsed), 3) if decode_elapsed else None,
        output_token_count_source=",".join(token_sources),
        response_model=first_success.response_model if first_success else "",
        output_preview=(first_success.output_preview if first_success else ""),
        note=case.note,
        trials=trials,
    )


def _skipped_case(
    case: MatrixCase,
    *,
    layer: BenchmarkLayer,
    reason: str,
    iterations: int,
    max_tokens: int,
    base_url_configured: bool,
    agent_case: AgentBenchmarkCase | None = None,
) -> CaseResult:
    return CaseResult(
        case_id=case.case_id,
        provider_id=case.provider_id,
        provider_label=case.provider_label,
        model=case.model,
        wire_api=case.wire_api,
        layer=layer,
        agent_case_id=agent_case.case_id if agent_case else "",
        agent_case_label=agent_case.label if agent_case else "",
        agent_case_source=agent_case.source if agent_case else "",
        expected_support=case.expected_support,
        status="SKIP",
        api_key_env=case.api_key_env,
        api_key_alt_env=case.api_key_alt_env,
        base_url_configured=base_url_configured,
        iterations=iterations,
        max_tokens=max_tokens,
        success_count=0,
        failure_count=0,
        skipped_reason=reason,
        note=case.note,
    )


def _missing_key_label(case: MatrixCase) -> str:
    if case.api_key_alt_env:
        return f"missing {case.api_key_env} or {case.api_key_alt_env}"
    return f"missing {case.api_key_env}"


def result_payload(results: list[CaseResult], *, args: argparse.Namespace) -> dict[str, Any]:
    statuses = {
        status: sum(1 for result in results if result.status == status)
        for status in (
            "PASS",
            "PARTIAL",
            "FAIL",
            "SKIP",
        )
    }
    return {
        "benchmark": "roboclaws_model_matrix_wire_support_v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "layers": args.layer or list(DEFAULT_LAYERS),
        "prompts": {
            "health": _redact_benchmark_text(args.prompt),
            "first-content": _redact_benchmark_text(args.first_content_prompt),
            "throughput": _redact_benchmark_text(args.throughput_prompt),
            "stream-throughput": _redact_benchmark_text(args.stream_throughput_prompt),
            "agent-case": [
                {
                    "case_id": agent_case.case_id,
                    "label": agent_case.label,
                    "source": agent_case.source,
                    "prompt_preview": _redact_benchmark_text(agent_case.prompt[:240]),
                }
                for agent_case in selected_agent_cases(
                    case_ids=set(args.agent_case),
                )
            ],
        },
        "iterations": args.iterations,
        "max_tokens": args.max_tokens,
        "first_content_max_tokens": args.first_content_max_tokens,
        "throughput_max_tokens": args.throughput_max_tokens,
        "stream_throughput_max_tokens": args.stream_throughput_max_tokens,
        "agent_case_max_tokens": args.agent_case_max_tokens,
        "timeout_s": args.timeout_s,
        "status_counts": statuses,
        "results": [asdict(result) for result in results],
    }


def write_payload(payload: dict[str, Any], output_dir: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "model_matrix_benchmark.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def print_table(results: list[CaseResult], *, output_path: Path) -> None:
    print("Roboclaws Model Matrix Benchmark")
    print(f"artifact: {output_path}")
    print(
        f"{'status':8} {'layer':17} {'case':40} {'wire':19} {'ok':>3} "
        f"{'p50':>8} {'tok/s':>9} {'dec/s':>9} detail"
    )
    for result in results:
        detail = result.skipped_reason if result.status == "SKIP" else result.response_model
        if result.status not in {"PASS", "SKIP"}:
            detail = _first_error(result)
        if result.layer == "agent-case" and result.agent_case_id:
            detail = f"{result.agent_case_id} {detail}".strip()
        if result.layer in {"first-content", "stream-throughput"} and result.status == "PASS":
            detail = f"{detail} first={_fmt(result.median_first_content_s)}"
        print(
            f"{result.status:8} {result.layer:17} {result.case_id:40} {result.wire_api:19} "
            f"{result.success_count:>3} {_fmt(result.median_s):>8} "
            f"{_fmt_rate(result.median_output_tokens_per_s):>9} "
            f"{_fmt_rate(result.median_decode_output_tokens_per_s):>9} {detail}"
        )


def _first_error(result: CaseResult) -> str:
    for trial in result.trials:
        if trial.status != "PASS":
            return f"{trial.error_type}: {trial.error}"
    return ""


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}s"


def _fmt_rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    cases = default_cases()
    providers = sorted({case.provider_id for case in cases})
    wires = sorted({case.wire_api for case in cases})
    agent_case_ids = [agent_case.case_id for agent_case in AGENT_BENCHMARK_CASES]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--output-dir", type=Path, default=Path("output/dev/model-matrix"))
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument(
        "--first-content-max-tokens",
        type=int,
        default=DEFAULT_FIRST_CONTENT_MAX_TOKENS,
    )
    parser.add_argument("--throughput-max-tokens", type=int, default=DEFAULT_THROUGHPUT_MAX_TOKENS)
    parser.add_argument(
        "--stream-throughput-max-tokens",
        type=int,
        default=DEFAULT_STREAM_THROUGHPUT_MAX_TOKENS,
    )
    parser.add_argument("--agent-case-max-tokens", type=int, default=DEFAULT_AGENT_CASE_MAX_TOKENS)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--first-content-prompt", default=DEFAULT_FIRST_CONTENT_PROMPT)
    parser.add_argument("--throughput-prompt", default=DEFAULT_THROUGHPUT_PROMPT)
    parser.add_argument("--stream-throughput-prompt", default=DEFAULT_STREAM_THROUGHPUT_PROMPT)
    parser.add_argument("--layer", action="append", choices=list(LAYER_CHOICES), default=[])
    parser.add_argument("--provider", action="append", choices=providers, default=[])
    parser.add_argument("--wire", action="append", choices=wires, default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--agent-case", action="append", choices=agent_case_ids, default=[])
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--list-agent-cases", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--fail-on-fail",
        action="store_true",
        help="Return failure when a selected case fails or is partial.",
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Return failure when a selected case is skipped.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_positive_args(args)
    if args.dotenv:
        load_dotenv(Path(args.dotenv))
    cases = default_cases()
    if _print_case_lists(args, cases):
        return 0
    selected = selected_cases(
        cases,
        providers=set(args.provider),
        wires=set(args.wire),
        case_ids=set(args.case),
    )
    unknown_cases = set(args.case) - {case.case_id for case in cases}
    if unknown_cases:
        raise SystemExit(f"unknown benchmark case(s): {', '.join(sorted(unknown_cases))}")
    if not selected:
        raise SystemExit("no benchmark cases selected")
    _assert_work_network_cases_allowed(selected)
    layers: tuple[BenchmarkLayer, ...] = tuple(args.layer or DEFAULT_LAYERS)

    results = _run_selected_cases(selected, layers=layers, args=args)
    payload = result_payload(results, args=args)
    output_path = write_payload(payload, args.output_dir)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_table(results, output_path=output_path)

    if args.fail_on_fail and any(result.status in {"FAIL", "PARTIAL"} for result in results):
        return 1
    if args.require_all and any(result.status == "SKIP" for result in results):
        return 1
    if all(result.status == "SKIP" for result in results):
        return 1
    return 0


def _assert_work_network_cases_allowed(
    selected: tuple[MatrixCase, ...],
    *,
    is_work_network: bool | None = None,
) -> None:
    assert_no_work_network_codex_gpt55(
        ((case.provider_id, case.model, case.case_id) for case in selected),
        item_label="benchmark case(s)",
        recommendation=(
            "Use a non-GPT case such as "
            "mimo-mify-responses:xiaomi-mimo-v2.5:openai-responses or "
            "minimax-responses:MiniMax-M3:responses, or retry off the work network."
        ),
        is_work_network=is_work_network,
    )


def _validate_positive_args(args: argparse.Namespace) -> None:
    for name in (
        "iterations",
        "max_tokens",
        "first_content_max_tokens",
        "throughput_max_tokens",
        "stream_throughput_max_tokens",
        "agent_case_max_tokens",
    ):
        if getattr(args, name) < 1:
            raise SystemExit(f"--{name.replace('_', '-')} must be >= 1")


def _print_case_lists(args: argparse.Namespace, cases: tuple[MatrixCase, ...]) -> bool:
    if args.list_cases:
        for case in cases:
            print(f"{case.case_id}\t{case.provider_id}\t{case.wire_api}\t{case.model}")
        return True
    if args.list_agent_cases:
        for agent_case in AGENT_BENCHMARK_CASES:
            print(f"{agent_case.case_id}\t{agent_case.label}\t{agent_case.source}")
        return True
    return False


def _run_selected_cases(
    selected: tuple[MatrixCase, ...],
    *,
    layers: tuple[BenchmarkLayer, ...],
    args: argparse.Namespace,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in selected:
        for layer in layers:
            for agent_case in _agent_cases_for_layer(layer, args=args):
                results.append(
                    run_case(
                        case,
                        layer=layer,
                        prompt=_prompt_for_layer(args, layer, agent_case=agent_case),
                        iterations=args.iterations,
                        max_tokens=_max_tokens_for_layer(args, layer),
                        timeout_s=args.timeout_s,
                        agent_case=agent_case,
                    )
                )
    return results


def _agent_cases_for_layer(
    layer: BenchmarkLayer, *, args: argparse.Namespace
) -> tuple[AgentBenchmarkCase | None, ...]:
    if layer != "agent-case":
        return (None,)
    return selected_agent_cases(case_ids=set(args.agent_case))


def _max_tokens_for_layer(args: argparse.Namespace, layer: BenchmarkLayer) -> int:
    if layer == "stream-throughput":
        return args.stream_throughput_max_tokens
    if layer == "agent-case":
        return args.agent_case_max_tokens
    if layer == "first-content":
        return args.first_content_max_tokens
    if layer == "throughput":
        return args.throughput_max_tokens
    return args.max_tokens


def _prompt_for_layer(
    args: argparse.Namespace,
    layer: BenchmarkLayer,
    *,
    agent_case: AgentBenchmarkCase | None = None,
) -> str:
    if layer == "stream-throughput":
        return args.stream_throughput_prompt
    if layer == "agent-case":
        if agent_case is None:
            raise ValueError("agent-case layer requires an agent benchmark case")
        return agent_case.prompt
    if layer == "first-content":
        return args.first_content_prompt
    if layer == "throughput":
        return args.throughput_prompt
    return args.prompt


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
