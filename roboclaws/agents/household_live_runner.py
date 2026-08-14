#!/usr/bin/env python3
"""Run one OpenAI Agents SDK household-world live-agent session."""

from __future__ import annotations

import argparse
import os

from roboclaws.agents.drivers.household_live import add_household_cleanup_live_runner_args
from roboclaws.agents.drivers.openai_agents_perf_profile import MODEL_THINKING_MODE_ENV
from roboclaws.agents.household_live_config import _env_bool
from roboclaws.agents.household_live_lifecycle import LiveOpenAIAgentsHouseholdRunner
from roboclaws.agents.thinking_policy import THINKING_MODES


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Own the cleanup MCP server, OpenAI Agents SDK runtime, checker, and "
            "status files for one experimental live run."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_household_cleanup_live_runner_args(parser, policy_default="openai_agents_agent")
    parser.add_argument("--provider-profile", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help=(
            "Maximum OpenAI Agents SDK agent turns inside one runner invocation. "
            "This is not runner-side continuation."
        ),
    )
    parser.add_argument(
        "--incomplete-turn-continuation-attempts",
        type=int,
        default=None,
        help=(
            "Bounded continuation attempts after a successful SDK turn ends without "
            "MCP done/run_result.json. The runner still never infers cleanup success."
        ),
    )
    parser.add_argument(
        "--cache-tools-list",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("ROBOCLAWS_OPENAI_AGENTS_CACHE_TOOLS_LIST", default=True),
        help=(
            "Ask the OpenAI Agents SDK MCP client to cache the cleanup tool list. "
            "The cleanup MCP tool catalog is static within one live run."
        ),
    )
    parser.add_argument(
        "--mcp-client-session-timeout-s",
        type=float,
        default=None,
        help=(
            "OpenAI Agents SDK MCP ClientSession read timeout. Visual cleanup lanes can "
            "exceed the SDK's short default while robot-view artifacts are captured."
        ),
    )
    parser.add_argument(
        "--agent-sdk-perf-profile",
        default="",
        help=(
            "Private OpenAI Agents SDK performance profile id. Known values: "
            "context_managed_v1, baseline."
        ),
    )
    parser.add_argument("--continuation-mode", default="")
    parser.add_argument(
        "--model-thinking-mode",
        choices=THINKING_MODES,
        default=os.environ.get(MODEL_THINKING_MODE_ENV, "default"),
        help=(
            "Provider-aware model thinking policy. default enables supported OpenAI "
            "Chat/Responses thinking, enabled forces it, disabled sends the provider-specific "
            "off switch for A/B runs."
        ),
    )
    parser.add_argument(
        "--model-input-compaction",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to the SDK call_model_input_filter compaction arm. This is private "
            "OpenAI Agents SDK candidate-I evidence and is disabled by default."
        ),
    )
    parser.add_argument("--model-input-compaction-min-chars", type=int, default=None)
    parser.add_argument(
        "--model-racing",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-C get_response model-call racing. "
            "stream_response remains single-arm."
        ),
    )
    parser.add_argument("--model-racing-arm-count", type=int, default=None)
    parser.add_argument(
        "--raw-fpv-image-memory",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-AA raw-FPV image-memory policy. "
            "This only compacts older image blocks before SDK model calls; reports and "
            "MCP traces keep full image artifacts."
        ),
    )
    parser.add_argument("--raw-fpv-image-memory-retain", type=int, default=None)
    parser.add_argument(
        "--camera-grounded-history-compaction",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-AC camera-grounded history compaction. "
            "Older camera-grounded observation/declaration outputs are summarized before "
            "SDK model calls while recent actionable outputs and MCP/report artifacts remain "
            "complete."
        ),
    )
    parser.add_argument("--camera-grounded-history-retain", type=int, default=None)
    parser.add_argument(
        "--camera-grounded-composite-tools",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Opt in to private Agent SDK Candidate-O MCP composite tools for "
            "camera-grounded-labels. The cleanup server enables the extra tool only "
            "for this SDK run."
        ),
    )
    parser.add_argument(
        "--robot-view-capture-policy",
        default="",
        help=(
            "Private Agent SDK Candidate-F robot-view report capture policy. "
            "Use action_timeline to keep before/after and cleanup action views while "
            "skipping report-only observe/scene_objects captures."
        ),
    )
    parser.add_argument("--context-soft-limit-tokens", type=int, default=None)
    parser.add_argument("--context-hard-limit-tokens", type=int, default=None)
    parser.add_argument("--max-observe-per-waypoint", type=int, default=None)
    parser.add_argument("--raw-fpv-candidate-budget", type=int, default=None)
    parser.add_argument("--raw-fpv-repeated-failure-limit", type=int, default=None)
    parser.add_argument("--done-retry-budget", type=int, default=None)
    parser.add_argument(
        "--model-service-retry-attempts",
        type=int,
        default=None,
        help=(
            "Bounded same-provider Agent SDK model-request retries for classified "
            "transient provider/model service failures. Set 0 to disable."
        ),
    )
    parser.add_argument(
        "--model-service-retry-sleep-s",
        type=float,
        default=None,
        help="Delay between Agent SDK model-service retry attempts.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return LiveOpenAIAgentsHouseholdRunner(parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
